"""U1X-a RELIABILITY — failing tests for the retired-U1 reliability fixes
folded into U1X-a's backend slice (U-PLAN.md "U1X BUILD PLAN" SLICES →
U1X-a: "PLUS the retired-U1 reliability fixes in the same files").

Ground truth (U-PLAN.md GROUND TRUTH, agents-uplift discovery, live-verified
2026-08-13): 402s are driven by an OVERSIZED ``max_tokens`` ask — the tailor
entailment call effectively requests up to 65536 completion tokens because
``_build_openrouter_request`` (llm_client.py) OMITS ``max_tokens`` entirely on
every non-free-chain attempt, so the upstream provider default (as large as
65536 for a reasoning-tier model) applies instead of a size actually
affordable within the remaining OpenRouter credit. The 503 storm since 08-10
is wall-clock budget exhaustion: the production budget is 65s
(``AETHER_LLM_BUDGET_SECONDS``) but observed REASONING-tier call latency was
70.9-94.4s, yet ``LLMClient._model_chain`` always plans a FIXED 2-attempt
(primary + fallback) chain regardless of whether either attempt can possibly
fit inside what remains of the budget. Additionally, no endpoint exists today
for a user/operator to see the real remaining OpenRouter credit (grepped:
zero hits for "credits"/"remaining_credit" anywhere in apps/api/app) — so a
402 storm is invisible until it has already happened.

PINNED CONTRACT for the fixer (exact names — match these or these tests will
legitimately still fail after implementation):

  * ``app.services.llm_client.size_max_tokens_for_call(prompt_name: str, *,
    remaining_credit_usd: float, completion_price_per_m: float) -> int`` —
    the ``max_tokens`` to actually REQUEST for a call of this class, capped to
    what ``remaining_credit_usd`` can afford at ``completion_price_per_m``
    ($/M completion tokens) — replacing today's "omit max_tokens → whatever
    the upstream provider defaults to" behaviour. Must never return a value
    anywhere near the unbounded ask that reached 65536 in production.
  * ``app.services.llm_client.plan_attempt_count(*, budget_seconds: float,
    per_attempt_seconds: float, requested_attempts: int) -> int`` — the
    largest attempt count ``<= requested_attempts`` such that
    ``count * per_attempt_seconds <= budget_seconds``, or ``0`` when not even
    ONE attempt fits (an honest fail-fast signal instead of guaranteeing a
    mid-flight cutoff the caller can't distinguish from a real failure).
  * ``app.services.llm_client.CreditsUnavailableError`` — new exception
    (mirrors ``ModelCatalogError``'s honest-failure role) raised by
    ``get_openrouter_credits`` when no credential/cache/upstream is
    reachable — a credits check must fail CLOSED, never fabricate numbers.
  * ``app.services.llm_client.get_openrouter_credits(*, force_refresh: bool =
    False) -> dict`` — ``{"remaining": float, "total": float, "asOf": str}``
    from OpenRouter's real ``GET /credits``, cached >= 60s (mirrors the
    existing ``_MODEL_CATALOG_TTL`` cache pattern already used for
    ``list_provider_models``).
  * ``GET /agents/providers/openrouter/credits`` — new OPERATOR-scoped route
    (mirrors ``/agents/providers/{provider}/models``, same ``AdminUser``
    gate as the rest of the deployment-wide provider family, F-01) returning
    that same envelope. On honest unavailability it still answers 200 with
    an explicit ``{"available": false, "remaining": null, "total": null,
    "asOf": null}`` — never a fabricated 200 with fake numbers, never an
    opaque 500.

Test-authorship only — no fix is implemented in this file.
"""

from __future__ import annotations

import uuid

import pytest

from app.services import credential_vault as vault


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


def _register(client, email: str) -> tuple[dict[str, str], str]:
    creds = {"email": email, "password": "Passw0rd1"}
    r = client.post("/auth/register", json=creds)
    assert r.status_code in (201, 409), r.text
    login = client.post("/auth/login", json=creds)
    assert login.status_code == 200, login.text
    body = login.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["userId"]


@pytest.fixture()
def admin_headers(client, promote_user_to_admin) -> dict[str, str]:
    headers, uid = _register(client, f"u1x-rel-admin-{uuid.uuid4().hex[:8]}@example.com")
    promote_user_to_admin(uid)
    return headers


# --------------------------------------------------------------------------- #
# max_tokens sizing — kill the unbounded (effectively 65536) ask
# --------------------------------------------------------------------------- #


def test_max_tokens_sizing_helper_caps_to_affordable_window():
    """FAILS NOW: ``size_max_tokens_for_call`` does not exist — every live
    call omits ``max_tokens`` entirely (``_build_openrouter_request``),
    letting the upstream provider default (as large as 65536 for a
    reasoning-tier model) apply regardless of remaining credit."""
    from app.services.llm_client import size_max_tokens_for_call

    # $0.01 remaining credit at the anthropic PREMIUM tier's real completion
    # price ($75/M, llm_client._STATIC_MODEL_CATALOG['anthropic']) affords
    # ~133 tokens — nowhere near the unbounded ask that reached 65536 in
    # production.
    affordable = size_max_tokens_for_call(
        "tailor_entailment", remaining_credit_usd=0.01, completion_price_per_m=75.0
    )
    assert 0 < affordable < 65536, affordable
    assert affordable <= 200, (
        f"$0.01 at $75/M should afford roughly 133 tokens, got {affordable}"
    )

    # Ample credit still gets a sane per-call-class ceiling — never the
    # unbounded upstream default.
    generous = size_max_tokens_for_call(
        "tailor_entailment", remaining_credit_usd=1000.0, completion_price_per_m=75.0
    )
    assert 0 < generous < 65536, generous


def test_max_tokens_sizing_helper_never_returns_zero_or_negative():
    """A near-zero remaining credit must still floor at SOME minimum usable
    size (an honest failure belongs to the credits check / 402 path, not a
    max_tokens=0 request that can never produce output)."""
    from app.services.llm_client import size_max_tokens_for_call

    tiny = size_max_tokens_for_call(
        "tailor_entailment", remaining_credit_usd=0.0001, completion_price_per_m=75.0
    )
    assert tiny > 0, tiny


# --------------------------------------------------------------------------- #
# Wall-clock attempt planner — fewer, better-sized attempts
# --------------------------------------------------------------------------- #


def test_attempt_planner_fits_attempts_to_wall_clock_budget():
    """FAILS NOW: ``plan_attempt_count`` does not exist —
    ``LLMClient._model_chain`` always plans a fixed 2-attempt
    (primary + fallback) chain with no regard for whether either attempt can
    fit inside what remains of the wall-clock budget."""
    from app.services.llm_client import plan_attempt_count

    # Both attempts comfortably fit.
    assert plan_attempt_count(
        budget_seconds=65.0, per_attempt_seconds=25.0, requested_attempts=2
    ) == 2
    # Only ONE of the two requested attempts fits — the chain must shrink,
    # not promise a second attempt it structurally can't deliver.
    assert plan_attempt_count(
        budget_seconds=65.0, per_attempt_seconds=40.0, requested_attempts=2
    ) == 1
    # Live observed REASONING-tier latency (94.4s, agents-uplift discovery)
    # exceeds even the FULL 65s production budget — not even ONE attempt
    # fits. The planner must say so honestly (0), not silently promise 1 or 2
    # anyway and guarantee a mid-flight cutoff indistinguishable from a real
    # failure.
    assert plan_attempt_count(
        budget_seconds=65.0, per_attempt_seconds=94.4, requested_attempts=2
    ) == 0


# --------------------------------------------------------------------------- #
# Honest OpenRouter credits proxy
# --------------------------------------------------------------------------- #


def test_get_openrouter_credits_fetches_and_caches(monkeypatch):
    """FAILS NOW: ``get_openrouter_credits`` does not exist — there is no
    code path anywhere that surfaces the real remaining OpenRouter credit."""
    from app.services import llm_client

    class _Cred:
        secret = "sk-or-test-credits"
        base_url = "https://openrouter.ai/api/v1"

    monkeypatch.setattr(llm_client, "resolve_credential", lambda *a, **k: _Cred())

    calls = {"n": 0}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            # OpenRouter's real /credits shape.
            return {"data": {"total_credits": 2850.50, "total_usage": 2751.74}}

    def _fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        assert url.endswith("/credits")
        assert headers["Authorization"] == "Bearer sk-or-test-credits"
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "get", _fake_get)

    first = llm_client.get_openrouter_credits()
    assert first["remaining"] == pytest.approx(98.76, abs=0.01)
    assert first["total"] == pytest.approx(2850.50, abs=0.01)
    assert first.get("asOf"), "asOf must be a real ISO-8601 timestamp"

    # Second call within the >=60s TTL must be served from cache, not refetch.
    second = llm_client.get_openrouter_credits()
    assert second == first
    assert calls["n"] == 1, "credits must be cached (>=60s TTL), not refetched every call"


def test_get_openrouter_credits_fails_closed_when_no_credential(monkeypatch):
    """No OpenRouter credential resolvable → honest failure, never fabricated
    numbers (mirrors ``ModelCatalogError``'s honest-failure contract)."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client, "resolve_credential", lambda *a, **k: None)

    with pytest.raises(llm_client.CreditsUnavailableError):
        llm_client.get_openrouter_credits(force_refresh=True)


def test_credits_endpoint_returns_envelope(client, admin_headers, monkeypatch):
    """FAILS NOW: no such route exists (404) — nothing ever proxies
    OpenRouter's GET /credits to the app."""
    monkeypatch.setattr(
        "app.services.llm_client.get_openrouter_credits",
        lambda **k: {
            "remaining": 98.76,
            "total": 2850.50,
            "asOf": "2026-08-13T12:00:00+00:00",
        },
    )
    r = client.get("/agents/providers/openrouter/credits", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["remaining"] == pytest.approx(98.76)
    assert body["total"] == pytest.approx(2850.50)
    assert body.get("asOf") == "2026-08-13T12:00:00+00:00"


def test_credits_endpoint_fails_closed_honestly_not_500(client, admin_headers, monkeypatch):
    """An upstream/credential failure must render an honest, structured
    "unavailable" response — never a 500, never fabricated numbers."""
    from app.services.llm_client import CreditsUnavailableError

    def _boom(**k):
        raise CreditsUnavailableError("no OpenRouter credential configured")

    monkeypatch.setattr("app.services.llm_client.get_openrouter_credits", _boom)

    r = client.get("/agents/providers/openrouter/credits", headers=admin_headers)
    assert r.status_code == 200, (
        f"a credits-unavailable condition must be an honest 200 envelope, "
        f"not {r.status_code}: {r.text}"
    )
    body = r.json()
    assert body.get("available") is False, body
    assert body.get("remaining") is None, body


def test_credits_endpoint_is_operator_scoped(client, auth_headers):
    """The credits figure reflects the DEPLOYMENT-WIDE OpenRouter account
    balance (billing-sensitive), so it follows the SAME F-01 operator-only
    gate as the rest of the deployment-wide provider family
    (GET /agents/providers, .../credential, .../verify)."""
    r = client.get("/agents/providers/openrouter/credits", headers=auth_headers)
    assert r.status_code == 403, r.text
