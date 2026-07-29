"""ML-W14 (HIGH, billing accuracy) — bill a run against the model that ACTUALLY
served it, not the config-derived intent.

Finding record: ``uat/reports/evidence/models-live/wave3-api/
item3-servedbymodel-fence-ruling.json`` (2026-07-29). When the ADMIN
free-chain rescue serves a run (OpenRouter HTTP 402 on the paid chain →
``LLMClient._auto`` continues into $0 ``:free`` models), the router still
records ``output["model"] = _model_for_agent(...)`` — CONFIG-derived intent —
and costs the run against THAT (paid) model's published price
(``routers/agents.py`` :889-903). So a $0 run inflates ``AgentRun.costUsd``,
``GET /agents/stats`` spend/ROI, and eats the user's USD spend cap.

Ground truth for the fix seam (fresh, on-disk, verified 2026-07-29):

- Every captured live OpenRouter 200 body carries a top-level ``"model"``
  echoing the served id — e.g.
  ``uat/reports/evidence/free-model-fallback/
  free-model-nvidia_nemotron-3-ultra-550b-a55b_free-response.json`` →
  ``"model": "nvidia/nemotron-3-ultra-550b-a55b:free"``. That field is the
  PROVIDER's own statement of what served, so it is what the client reads.
- In the 367-model catalog snapshot
  ``uat/reports/evidence/free-model-fallback/models-list-raw.json``, all 14
  ``:free``-suffixed ids have ``pricing.prompt == pricing.completion == 0``.
  So an OpenRouter ``:free`` id is a zero-price id by the provider's own
  convention, and a rescued run must record $0 even when the live catalog
  cache is cold.

Seam under test: ``llm_client`` observes the served id and publishes it via a
per-run ContextVar (``served_model_capture`` / ``get_last_served_model``);
``routers/agents.py::_execute_reserved_run`` reads it and, ONLY when it differs
from the intended model, records the served model and prices against it,
preserving the intent as ``output["requestedModel"]``.

PINs in this file (must pass BEFORE and AFTER): an un-rescued run's recorded
output and cost are unchanged, and a deterministic agent still records no model
and zero cost.
"""
from __future__ import annotations

import json

import pytest

_PAID_PRIMARY = "deepseek/deepseek-v4-pro"
_PAID_FALLBACK = "deepseek/deepseek-v4-flash"
_FREE_A = "nvidia/nemotron-3-ultra-550b-a55b:free"
_FREE_B = "nvidia/nemotron-3-super-120b-a12b:free"

#: Verbatim body OpenRouter returned for a paid model on the app's own
#: zero-credit key (probe artifact ``paid-model-claude-sonnet-5-response.json``).
_LIVE_402_BODY = (
    '{"error":{"message":"Insufficient credits. Add more using '
    'https://openrouter.ai/settings/credits","code":402,"metadata":'
    '{"limit_source":"openrouter_credits"}}}'
)


class _Resp:
    """Minimal httpx.Response stand-in (status_code / text / json())."""

    def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _ok(content: str, served_model: str | None) -> _Resp:
    """A live-shaped OpenAI-compatible 200. ``served_model`` mirrors the real
    provider bodies captured in the free-model probe artifacts; pass ``None`` to
    simulate a provider that omits the field."""
    payload: dict = {"choices": [{"message": {"content": content}}]}
    if served_model is not None:
        payload["model"] = served_model
    return _Resp(200, content, payload)


def _402() -> _Resp:
    return _Resp(402, _LIVE_402_BODY, {"error": {"code": 402}})


@pytest.fixture()
def openrouter_env(monkeypatch):
    """Env exactly like production: paid primary + PAID fallback, OpenRouter key."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.delenv("AETHER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ABACUS_API_KEY", raising=False)
    monkeypatch.setenv("AETHER_MODEL_REASONING", _PAID_PRIMARY)
    monkeypatch.setenv("AETHER_MODEL_FALLBACK", _PAID_FALLBACK)
    monkeypatch.setenv("AETHER_ADMIN_FREE_FALLBACK_MODELS", f"{_FREE_A},{_FREE_B}")
    return None


def _install_transport(monkeypatch, responder):
    """Route every live call through ``responder(model_id)``; record the ids."""
    import httpx

    seen: list[str] = []

    def _post(url, **kwargs):  # noqa: ANN001 — httpx.post signature
        model = kwargs["json"]["model"]
        seen.append(model)
        return responder(model)

    monkeypatch.setattr(httpx, "post", _post)
    return seen


def _set_is_admin(user_id: str, value: bool) -> None:
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "isAdmin" = %s WHERE "id" = %s', (value, user_id)
            )
        conn.commit()


def _clear_admin_cache() -> None:
    from app.services import llm_client

    getattr(llm_client, "_admin_flag_cache", {}).clear()


def _rescue_responder(model: str) -> _Resp:
    """The live 402-rescue shape: every paid model 402s, free models serve."""
    if model.endswith(":free"):
        return _ok('{"ok": true}', model)
    return _402()


# ---------------------------------------------------------------------------
# (a) llm_client — observe the served model authoritatively
# ---------------------------------------------------------------------------


def test_served_model_is_read_from_the_provider_response_body(
    monkeypatch, openrouter_env, tmp_path
):
    """FAILS NOW: ``body["model"]`` is on the wire (and in every captured probe
    artifact) but never read — the served id exists only as a local in ``_auto``
    and is discarded. The client must publish the PROVIDER's own statement of
    which model served."""
    from app.services.llm_client import (
        LLMClient,
        get_last_served_model,
        served_model_capture,
    )

    # The provider echoes a DIFFERENT id from the one asked for (e.g. a routed
    # variant); the authoritative answer is the provider's, not ours.
    _install_transport(monkeypatch, lambda m: _ok("hello", "vendor/actually-served"))
    llm = LLMClient(mode="live", fixture_dir=tmp_path)

    with served_model_capture():
        out = llm._call_live("sys", "usr", model="vendor/asked-for", temperature=0.0)
        assert out == "hello"
        assert get_last_served_model() == "vendor/actually-served"


def test_served_model_falls_back_to_the_requested_id_when_the_body_omits_it(
    monkeypatch, openrouter_env, tmp_path
):
    """No fabrication either way: a provider that omits ``model`` leaves the id
    we actually put on the wire as the honest answer."""
    from app.services.llm_client import (
        LLMClient,
        get_last_served_model,
        served_model_capture,
    )

    _install_transport(monkeypatch, lambda m: _ok("hello", None))
    llm = LLMClient(mode="live", fixture_dir=tmp_path)

    with served_model_capture():
        llm._call_live("sys", "usr", model="vendor/asked-for", temperature=0.0)
        assert get_last_served_model() == "vendor/asked-for"


def test_anthropic_transport_also_reports_the_served_model(monkeypatch, tmp_path):
    """The direct-Anthropic branch returns through ``parse_anthropic_response``;
    its Messages API body carries ``model`` too, and must be observed the same
    way (billing separation is untouched — this only records what served)."""
    from app.services.llm_client import (
        LLMClient,
        get_last_served_model,
        served_model_capture,
    )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test")
    monkeypatch.delenv("AETHER_LLM_API_KEY", raising=False)
    body = {
        "model": "claude-sonnet-4-5-20250929",
        "content": [{"type": "text", "text": "hi"}],
        "stop_reason": "end_turn",
    }
    _install_transport(monkeypatch, lambda m: _Resp(200, "hi", body))
    llm = LLMClient(mode="live", fixture_dir=tmp_path)

    with served_model_capture():
        assert llm._call_live(
            "sys", "usr", model="claude-sonnet-4-5", temperature=0.0
        ) == "hi"
        assert get_last_served_model() == "claude-sonnet-4-5-20250929"


def test_admin_free_rescue_publishes_the_free_model_as_the_served_model(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """The defect's root observation: after the rescue serves the run, the
    served model is the FREE one, not the paid model the chain started on."""
    from app.services.llm_client import (
        LLMClient,
        get_last_served_model,
        served_model_capture,
        user_credential_context,
    )

    _set_is_admin(test_user_id, True)
    _clear_admin_cache()
    seen = _install_transport(monkeypatch, _rescue_responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with served_model_capture(), user_credential_context(test_user_id, "coverLetter"):
        llm.complete("cover_letter", "sys", "usr", model=_PAID_PRIMARY)
        assert get_last_served_model() == _FREE_A
    assert seen == [_PAID_PRIMARY, _PAID_FALLBACK, _FREE_A], seen


def test_no_served_model_is_published_when_every_attempt_fails(
    monkeypatch, openrouter_env, tmp_path
):
    """Honesty pin: a run with no successful call publishes NOTHING, so the
    router can never stamp a candidate model as if it had served."""
    from app.services.llm_client import (
        LLMClient,
        LLMUnavailableError,
        get_last_served_model,
        served_model_capture,
    )

    _install_transport(monkeypatch, lambda m: _402())
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with served_model_capture():
        with pytest.raises(LLMUnavailableError):
            llm.complete("cover_letter", "sys", "usr", model=_PAID_PRIMARY)
        assert get_last_served_model() is None


def test_free_model_ids_price_at_zero_without_a_warm_catalog():
    """A ``:free`` OpenRouter id costs $0 by the provider's own id convention
    (all 14 ``:free`` ids in the live catalog snapshot are priced 0/0), so a
    cold catalog cache must not fall through to the flat non-zero default and
    invent spend for a free run."""
    from app.routers.agents import _DEFAULT_PRICE, _price_for

    assert _price_for(_FREE_A) == (0.0, 0.0)
    assert _price_for(_FREE_B) == (0.0, 0.0)
    # Contrast: a paid unknown id still gets the bounded default, unchanged.
    assert _price_for("vendor/totally-unknown") == _DEFAULT_PRICE


def test_test_run_estimate_for_a_free_model_is_an_honest_zero(
    monkeypatch, client, auth_headers
):
    """Consequence pin for the rule above, on the OTHER ``_price_for`` caller
    (the ``POST /agents/test-run`` preview): a $0 model previews $0 — an honest
    zero that is still distinguishable from the deterministic agents' ``null``.
    A PRICED model's preview is unchanged and is pinned by
    ``test_agents_screen.py::test_test_run_estimates_no_charge``."""
    monkeypatch.setenv("AETHER_MODEL_REASONING", _FREE_A)
    res = client.post(
        "/agents/test-run", json={"agent_key": "resumeTailoring"}, headers=auth_headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["model"] == _FREE_A
    assert body["estCost"] == 0.0
    assert body["creditsCharged"] == 0.0


# ---------------------------------------------------------------------------
# (b) routers/agents.py — record + bill the SERVED model
# ---------------------------------------------------------------------------


def _run_cover_letter(tmp_path, user_id: str) -> dict:
    """A metered coverLetter run whose body makes a REAL client call through the
    mocked transport — the exact production shape (``_record_run`` →
    ``_execute_reserved_run`` → agent → ``LLMClient``)."""
    from app.routers.agents import _record_run
    from app.services.llm_client import LLMClient

    def _fn() -> dict:
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        return {"content": llm.complete("cover_letter", "sys", "usr")}

    return _record_run(user_id, "coverLetter", {}, _fn)


def test_rescued_run_records_the_served_free_model_and_zero_cost(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """THE DEFECT. FAILS NOW: ``output["model"]`` is the paid primary and
    ``costUsd`` is that paid model's published price applied to the measured
    I/O — for a run a $0 free model actually served."""
    _set_is_admin(test_user_id, True)
    _clear_admin_cache()
    _install_transport(monkeypatch, _rescue_responder)

    out = _run_cover_letter(tmp_path, test_user_id)

    assert out["model"] == _FREE_A, (
        "the model recorded on the run must be the one that ACTUALLY served it"
    )
    assert out["requestedModel"] == _PAID_PRIMARY, (
        "the intended (config-derived) model must be preserved, not erased"
    )
    assert out["costUsd"] == 0.0, (
        "a $0 free-model rescue must record $0 — got " f"{out['costUsd']!r}"
    )
    # Tokens are a MEASURED I/O size, independent of price: still recorded.
    assert out["tokensIn"] > 0 and out["tokensOut"] > 0


def test_an_unpriceable_served_model_never_down_prices_the_run(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """Safety rail against the fix's own failure mode: if the served id has NO
    established price (unknown to the static table, the catalog and the ``:free``
    convention), adopting ``_price_for``'s flat default for a run whose INTENDED
    model is properly priced would silently down-price it — a spend-cap bypass.
    The served id is still recorded; the price stays the intended model's."""
    from app.routers.agents import _DEFAULT_PRICE, _price_for
    from app.services import llm_client

    _unpriced = "vendor/unpriced-rescue"  # no ':free', in no catalog
    monkeypatch.setenv("AETHER_ADMIN_FREE_FALLBACK_MODELS", _unpriced)
    _set_is_admin(test_user_id, True)
    _clear_admin_cache()
    _install_transport(
        monkeypatch,
        lambda m: _ok('{"ok": true}', m) if m == _unpriced else _402(),
    )
    # Give the INTENDED model a real, non-default catalog price.
    llm_client._MODEL_CATALOG_CACHE["openrouter"] = (
        1.0e18,  # far-future timestamp: never treated as stale during the test
        [{"id": _PAID_PRIMARY, "promptPerM": 3.0, "completionPerM": 15.0}],
    )
    try:
        assert _price_for(_unpriced) == _DEFAULT_PRICE  # premise of this test
        out = _run_cover_letter(tmp_path, test_user_id)
    finally:
        llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)

    assert out["model"] == _unpriced  # honest record of what served
    assert out["requestedModel"] == _PAID_PRIMARY
    price_in, price_out = (0.003, 0.015)  # $3/M and $15/M -> per-1K
    assert out["costUsd"] == pytest.approx(
        round(
            out["tokensIn"] / 1000 * price_in + out["tokensOut"] / 1000 * price_out, 6
        )
    ), "an unpriceable served model must not down-price the run to the flat default"


def test_rescued_run_does_not_consume_the_usd_spend_cap(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """Spend-cap interaction: the accumulation path must use the CORRECTED
    cost. FAILS NOW: the paid model's price is accumulated against the cap."""
    from app.repositories.billing import UsageQuotaRepository

    _set_is_admin(test_user_id, True)
    _clear_admin_cache()
    _install_transport(monkeypatch, _rescue_responder)

    quotas = UsageQuotaRepository()
    before = float((quotas.get_by_user(test_user_id) or {}).get("spendUsedUsd") or 0.0)
    _run_cover_letter(tmp_path, test_user_id)
    after = float((quotas.get_by_user(test_user_id) or {}).get("spendUsedUsd") or 0.0)

    assert after == pytest.approx(before), (
        "a free-model-served run must not consume the USD spend cap — "
        f"spend moved {before!r} -> {after!r}"
    )


def test_unrescued_run_records_exactly_what_it_records_today(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """PIN (passes BEFORE and AFTER): when the intended model serves the run,
    the recorded output and its cost are byte-for-byte today's — same key set,
    same model stamp, no ``requestedModel`` key, and cost still computed from
    the intended model's price by the unchanged formula."""
    from app.routers.agents import _price_for

    _set_is_admin(test_user_id, True)  # admin, but nothing 402s → no rescue
    _clear_admin_cache()
    seen = _install_transport(monkeypatch, lambda m: _ok("served fine", m))

    out = _run_cover_letter(tmp_path, test_user_id)

    assert seen == [_PAID_PRIMARY], seen
    assert out["model"] == _PAID_PRIMARY
    assert "requestedModel" not in out, (
        "no substitution happened, so the normal case must not grow a key"
    )
    assert set(out) == {
        "content", "duration_ms", "approvalRequired", "billingAudit",
        "model", "tokensIn", "tokensOut", "costUsd", "run_id",
    }, sorted(out)
    price_in, price_out = _price_for(_PAID_PRIMARY)
    assert out["costUsd"] == pytest.approx(
        round(
            out["tokensIn"] / 1000 * price_in + out["tokensOut"] / 1000 * price_out,
            6,
        )
    )
    assert out["costUsd"] > 0.0


def test_deterministic_agent_still_records_no_model_and_zero_cost(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """PIN (passes BEFORE and AFTER): the ``model is None`` branch — a
    deterministic agent makes no LLM call, so nothing is observed and nothing
    is stamped or charged."""
    from app.routers.agents import _record_run

    out = _record_run(test_user_id, "scout", {}, lambda: {"jobs": 0})

    assert out["model"] is None
    assert out["costUsd"] == 0.0
    assert "requestedModel" not in out


def test_served_model_observation_does_not_leak_into_the_next_run(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """The observation is scoped to ONE run. After a rescued run, a subsequent
    run whose callable makes no LLM call at all must fall back to the intended
    model — never inherit the previous run's served id."""
    _set_is_admin(test_user_id, True)
    _clear_admin_cache()
    _install_transport(monkeypatch, _rescue_responder)

    rescued = _run_cover_letter(tmp_path, test_user_id)
    assert rescued["model"] == _FREE_A

    from app.routers.agents import _record_run

    second = _record_run(test_user_id, "coverLetter", {}, lambda: {"content": "x"})
    assert second["model"] == _PAID_PRIMARY, second
    assert "requestedModel" not in second


def test_rescued_run_json_round_trips_for_the_audit_row(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """The corrected fields are persisted on the AgentRun output the owner-facing
    'Recent runs' table and ``GET /agents/stats`` read, not just returned."""
    from app.repositories.agent_run import AgentRunRepository

    _set_is_admin(test_user_id, True)
    _clear_admin_cache()
    _install_transport(monkeypatch, _rescue_responder)

    out = _run_cover_letter(tmp_path, test_user_id)
    stored = AgentRunRepository().last_run_by_agent(test_user_id)["coverLetter"]
    stored_output = stored["output"]
    if isinstance(stored_output, str):  # driver-dependent JSON handling
        stored_output = json.loads(stored_output)

    assert stored_output["model"] == _FREE_A
    assert stored_output["requestedModel"] == _PAID_PRIMARY
    assert float(stored["costUsd"] or 0.0) == 0.0
    assert out["run_id"] == stored["id"]
