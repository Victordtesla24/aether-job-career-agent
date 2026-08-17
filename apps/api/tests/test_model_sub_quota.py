"""MODEL-SUB-QUOTA — every Claude request is served by the operator's Anthropic
subscription, never by an API key and never through OpenRouter.

OWNER DIRECTIVE (2026-08-17, binding, verbatim intent):

    "I want all the claude requests to use my Anthropic Pro Subscription quota
     instead of consuming extra credits via an API_KEY including for openrouter."

DEVIATION THIS FILE PINS OUT OF EXISTENCE. ``resolve_provider`` used a pure
slash heuristic: ANY ``vendor/model`` id billed through OpenRouter, so a
``anthropic/claude-…`` pick (the owner's ``coverLetter`` AgentConfig was pinned
exactly that: ``anthropic/claude-opus-5``) burned OpenRouter credits to serve a
Claude model, while the identical bare ``claude-…`` id was served free by the
subscription. The two forms name the SAME model — routing them to different
billing accounts was the defect.

WHAT "ALIGNED" MEANS (the six clauses, one section each below):

1. NORMALIZATION AT THE ROUTING SEAM — ``^claude-`` or ``^anthropic/claude-``
   (case-insensitive) resolves ``provider='anthropic'`` and is served via the
   native Messages API with the ``anthropic/`` namespace STRIPPED to the bare
   id. Same model, direct provider — NOT a substitution (ADR-ML-3 intact). The
   slash rule is untouched for every non-Claude id.
2. OPENROUTER HARD GUARD — the OpenRouter request builder REFUSES a Claude
   model outright, so no code path can burn OpenRouter credit on Claude even if
   routing were bypassed.
3. CREDENTIAL PIN — a Claude request resolves the DB ``ProviderCredential``
   ``provider=anthropic authMode=oauth_token`` row (production shape: ``.env``
   carries NO ``ANTHROPIC_API_KEY``); with no Anthropic credential the run
   fails HONESTLY and fires ZERO HTTP — never a reroute to OpenRouter.
4. SAVE-TIME VALIDATION + DATA REPAIR — the per-agent save normalizes
   ``anthropic/claude-X`` -> ``claude-X`` and rejects an unknown Claude id 422
   (never a silent swap); the repair script normalizes existing AgentConfig
   rows and CLEARS (never substitutes) a pin whose bare id is not in the
   catalog, recording each change.
5. DISCLOSURE — no picker path offers a Claude id that would route OpenRouter:
   the curated OpenRouter catalog carries no ``anthropic/claude-*`` row.
6. PROOF — the billing audit for a Claude run reports
   ``provider=anthropic``/``authMode=oauth_token``.

Every test here is written RED-first against the pre-fix tree; outbound HTTP is
always a monkeypatched ``httpx.post`` — these tests never touch the network.
"""
from __future__ import annotations

import copy

import pytest

from app.repositories.provider_credential import ProviderCredentialRepository
from app.services import credential_vault as vault
from app.services.llm_client import (
    LLMClient,
    LLMUnavailableError,
    build_anthropic_request,
    resolve_provider,
    user_model_context,
)

#: A real id from the app's static Anthropic catalog, in both spellings.
_BARE = "claude-opus-4-8"
_SLASH = "anthropic/claude-opus-4-8"
#: A Claude id the Anthropic catalog does NOT offer (the owner's live pin).
_UNKNOWN_SLASH = "anthropic/claude-opus-5"
_UNKNOWN_BARE = "claude-opus-5"
#: A genuine OpenRouter model — the slash rule must be unchanged for it.
_OPENROUTER = "deepseek/deepseek-v4-pro"

_OAT = "sk-ant-oat01-model-sub-quota-test-token"

_GOOD_JSON = '{"hook_reason": "x", "body": "a\\n\\nb"}'


class _Resp:
    """Minimal httpx.Response stand-in (status_code / text / json())."""

    def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _anthropic_ok(content: str) -> _Resp:
    """A native Messages API 200 (NOT the OpenAI-compatible shape)."""
    return _Resp(
        200,
        content,
        {"content": [{"type": "text", "text": content}], "stop_reason": "end_turn"},
    )


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture(autouse=True)
def _clean_provider_credentials():
    """``ProviderCredential`` is created lazily and is NOT in the truncate list."""
    from app.db import get_connection
    from app.repositories import provider_credential as pc_module

    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS "ProviderCredential"')
        conn.commit()
    pc_module._table_ready = False


@pytest.fixture()
def subscription_env(monkeypatch):
    """PRODUCTION SHAPE: an OpenRouter key present, and the ONLY Anthropic
    credential is the deployment-wide ``oauth_token`` DB row (no
    ``ANTHROPIC_API_KEY`` anywhere — mirrors the served ``.env``)."""
    for var in (
        "ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN", "ABACUS_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    ProviderCredentialRepository().upsert(
        "anthropic", auth_mode="oauth_token", secret=_OAT
    )
    return None


@pytest.fixture()
def no_anthropic_credential_env(monkeypatch):
    """OpenRouter is fully configured; Anthropic has NO credential at all."""
    for var in (
        "ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN", "ABACUS_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    return None


def _install_transport(monkeypatch, responder):
    """Record every outgoing request and answer via ``responder(url, payload)``."""
    import httpx

    sent: list[dict] = []

    def _post(url, **kwargs):  # noqa: ANN001 — httpx.post signature
        payload = kwargs.get("json") or {}
        sent.append(
            {
                "url": url,
                "json": copy.deepcopy(payload),
                "headers": dict(kwargs.get("headers") or {}),
            }
        )
        return responder(url, payload)

    monkeypatch.setattr(httpx, "post", _post)
    return sent


def _pin(user_id: str, agent_key: str, model: str) -> None:
    """Seed an ``AgentConfig.model`` row directly — the shapes below are the
    LEGACY ones the save endpoint now rejects, so they cannot be written
    through the API."""
    from app.db import get_connection
    from app.routers.agents import _ensure_agent_config_schema

    _ensure_agent_config_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "AgentConfig" ("userId","agentKey","model","updatedAt") '
                "VALUES (%s,%s,%s,NOW()) "
                'ON CONFLICT ("userId","agentKey") '
                'DO UPDATE SET "model" = EXCLUDED."model"',
                (user_id, agent_key, model),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# CLAUSE 1 — normalization at the routing seam
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    [
        _BARE,
        _SLASH,
        "claude-sonnet-4-6",
        "anthropic/claude-sonnet-4-6",
        "ANTHROPIC/Claude-Opus-4-8",  # case-insensitive
        "  anthropic/claude-haiku-4-5  ",  # whitespace-tolerant
        _UNKNOWN_SLASH,
    ],
)
def test_every_claude_spelling_resolves_to_the_anthropic_subscription(model):
    """OWNER DIRECTIVE: a Claude model is a Claude model in BOTH spellings, and
    both must be served by the subscription.

    FAILS NOW for every ``anthropic/claude-…`` row: today's slash heuristic
    returns ``'openrouter'`` for them, which is the exact "extra credits" path
    the directive forbids.
    """
    assert resolve_provider(model) == "anthropic", model


@pytest.mark.parametrize(
    "model",
    [
        _OPENROUTER,
        "qwen/qwen3-235b-a22b:free",
        "openai/gpt-5.6-sol",
        "x-ai/grok-4",
        # NOT a Claude id — the ``anthropic/`` namespace alone must not capture
        # a non-Claude model OpenRouter happens to serve under it.
        "anthropic/some-non-claude-model",
    ],
)
def test_non_claude_slash_ids_still_route_to_openrouter(model):
    """ZERO-REGRESSION PIN: the slash rule is unchanged for everything else."""
    assert resolve_provider(model) == "openrouter", model


def test_normalize_model_id_strips_only_the_anthropic_claude_namespace():
    """The ``anthropic/`` prefix is stripped to the bare id — same model, direct
    provider. Nothing else in the id is touched, and no other id is rewritten
    (a rewrite that changed the MODEL would be an ADR-ML-3 substitution)."""
    from app.services.llm_client import normalize_model_id

    assert normalize_model_id(_SLASH) == _BARE
    assert normalize_model_id("ANTHROPIC/Claude-Opus-4-8") == "Claude-Opus-4-8"
    assert normalize_model_id(_UNKNOWN_SLASH) == _UNKNOWN_BARE
    # Already bare / not Claude / empty -> returned unchanged (stripped only).
    assert normalize_model_id(_BARE) == _BARE
    assert normalize_model_id(_OPENROUTER) == _OPENROUTER
    assert normalize_model_id("anthropic/some-non-claude-model") == (
        "anthropic/some-non-claude-model"
    )
    assert normalize_model_id("") == ""
    assert normalize_model_id(None) == ""  # type: ignore[arg-type]


def test_slash_claude_run_hits_the_native_anthropic_api_with_the_bare_id(
    monkeypatch, subscription_env, tmp_path
):
    """THE keystone end-to-end assertion (clauses 1 + 3 together).

    A user-chosen ``anthropic/claude-opus-4-8`` must produce EXACTLY ONE
    request, to ``api.anthropic.com/v1/messages``, carrying the BARE model id
    and the subscription's ``oauth_token`` headers.

    FAILS NOW: the request goes to ``openrouter.ai/api/v1/chat/completions``
    with the slash id and the OpenRouter bearer key — the owner's credits.
    """
    sent = _install_transport(monkeypatch, lambda url, p: _anthropic_ok(_GOOD_JSON))
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with user_model_context(_SLASH):
        out = llm.complete("cover_letter", "sys", "usr", model=_SLASH)

    assert out == _GOOD_JSON
    assert len(sent) == 1, sent
    assert "api.anthropic.com" in sent[0]["url"], sent[0]["url"]
    assert "openrouter" not in sent[0]["url"].lower(), sent[0]["url"]
    # The anthropic/ namespace is stripped for the API call — same model.
    assert sent[0]["json"]["model"] == _BARE, sent[0]["json"]
    # Subscription transport: Bearer + the oauth beta header, never x-api-key.
    headers = {k.lower(): v for k, v in sent[0]["headers"].items()}
    assert headers.get("authorization") == f"Bearer {_OAT}", sorted(headers)
    assert headers.get("anthropic-beta") == "oauth-2025-04-20", sorted(headers)
    assert "x-api-key" not in headers, sorted(headers)


def test_non_claude_pick_still_bills_openrouter_end_to_end(
    monkeypatch, subscription_env, tmp_path
):
    """ZERO-REGRESSION PIN (the other side of clause 1): a deliberate
    OpenRouter pick still goes to OpenRouter with the OpenRouter key."""
    sent = _install_transport(
        monkeypatch,
        lambda url, p: _Resp(200, _GOOD_JSON,
                             {"choices": [{"message": {"content": _GOOD_JSON}}]}),
    )
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with user_model_context(_OPENROUTER):
        out = llm.complete("cover_letter", "sys", "usr", model=_OPENROUTER)

    assert out == _GOOD_JSON
    assert len(sent) == 1, sent
    assert "openrouter.ai" in sent[0]["url"], sent[0]["url"]
    assert sent[0]["json"]["model"] == _OPENROUTER


# ---------------------------------------------------------------------------
# CLAUSE 2 — OpenRouter hard guard (belt and braces)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", [_BARE, _SLASH, "claude-haiku-4-5", _UNKNOWN_SLASH])
def test_openrouter_request_builder_refuses_any_claude_model(model):
    """Even with routing bypassed, no OpenRouter body can carry a Claude model.

    FAILS NOW: the builder happily builds a Claude request against the
    OpenRouter credential.
    """
    from app.services.llm_client import (
        ClaudeOnOpenRouterError,
        ProviderCredentialResolution,
        _build_openrouter_request,
    )

    cred = ProviderCredentialResolution(
        "openrouter", "api_key", "sk-or-test", None, "environment"
    )
    with pytest.raises(ClaudeOnOpenRouterError) as exc:
        _build_openrouter_request(model, "sys", "usr", 0.7, cred)
    msg = str(exc.value)
    assert model.strip() in msg, msg
    assert "anthropic" in msg.lower(), msg


def test_openrouter_builder_guard_leaves_non_claude_models_alone():
    """ZERO-REGRESSION PIN: the guard is Claude-only."""
    from app.services.llm_client import (
        ProviderCredentialResolution,
        _build_openrouter_request,
    )

    cred = ProviderCredentialResolution(
        "openrouter", "api_key", "sk-or-test", None, "environment"
    )
    req = _build_openrouter_request(_OPENROUTER, "sys", "usr", 0.7, cred)
    assert req["json"]["model"] == _OPENROUTER


# ---------------------------------------------------------------------------
# CLAUSE 3 — credential pin: oauth subscription, or an honest failure
# ---------------------------------------------------------------------------


def test_claude_request_resolves_the_oauth_subscription_row_not_an_api_key(
    subscription_env,
):
    """Production shape: the DB oauth row is the sole Anthropic credential and
    IS what a Claude request resolves."""
    from app.services.llm_client import resolve_user_credential

    cred = resolve_user_credential(resolve_provider(_SLASH), None, None)
    assert cred is not None
    assert cred.provider == "anthropic"
    assert cred.auth_mode == "oauth_token"
    assert cred.source == "database"


def test_claude_run_without_the_subscription_row_fails_honestly_and_fires_no_http(
    monkeypatch, no_anthropic_credential_env, tmp_path
):
    """No Anthropic credential must NOT become an OpenRouter Claude call.

    The run fails honestly (``LLMUnavailableError`` -> the llm_unavailable 503
    surface) with ZERO outbound requests — never a silent fallback onto the
    OpenRouter credential that is sitting right there.
    """
    sent = _install_transport(
        monkeypatch,
        lambda url, p: _Resp(200, _GOOD_JSON,
                             {"choices": [{"message": {"content": _GOOD_JSON}}]}),
    )
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with pytest.raises(LLMUnavailableError):
        with user_model_context(_SLASH):
            llm.complete("cover_letter", "sys", "usr", model=_SLASH)

    assert sent == [], f"a Claude run reached the network without Anthropic: {sent}"


def test_build_anthropic_request_is_reachable_for_the_bare_id(subscription_env):
    """The transport half of the pin: the bare id builds a valid Messages
    request against the oauth credential (no api-key header)."""
    req = build_anthropic_request(
        _BARE, "sys", "usr", auth_mode="oauth_token", secret=_OAT
    )
    assert req["url"].endswith("/v1/messages")
    assert req["json"]["model"] == _BARE
    assert req["headers"]["authorization"] == f"Bearer {_OAT}"


# ---------------------------------------------------------------------------
# CLAUSE 4 — save-time normalization + validation, and the data repair
# ---------------------------------------------------------------------------


def test_saving_a_slash_claude_pin_persists_the_bare_id(client, auth_headers):
    """A user (or a legacy client) saving ``anthropic/claude-opus-4-8`` gets the
    SAME model, pinned in the form that routes to the subscription.

    FAILS NOW: the slash id is persisted verbatim and would route OpenRouter.
    """
    put = client.put(
        "/agents/config/coverLetter", json={"model": _SLASH}, headers=auth_headers
    )
    assert put.status_code == 200, put.text
    assert put.json()["model"] == _BARE, put.text
    got = client.get("/agents/config/coverLetter", headers=auth_headers)
    assert got.json()["model"] == _BARE, got.text


def test_saving_an_unknown_claude_id_is_rejected_422_never_substituted(
    client, auth_headers
):
    """An id the Anthropic catalog does not offer is an honest 422 — the app
    must never quietly pin a DIFFERENT model instead (ADR-ML-3)."""
    for bad in (_UNKNOWN_SLASH, _UNKNOWN_BARE):
        r = client.put(
            "/agents/config/coverLetter", json={"model": bad}, headers=auth_headers
        )
        assert r.status_code == 422, f"{bad} -> {r.status_code}: {r.text}"
        assert "model" in str(r.json().get("detail", "")).lower(), r.text
    # And nothing was written: the agent keeps its previous (default) model.
    got = client.get("/agents/config/coverLetter", headers=auth_headers)
    assert got.json()["model"] not in (_UNKNOWN_SLASH, _UNKNOWN_BARE), got.text


def test_repair_normalizes_known_pins_and_clears_unknown_ones(
    client, auth_headers, test_user_id
):
    """The one-time idempotent repair for rows written BEFORE this fix.

    ``anthropic/claude-opus-4-8`` -> ``claude-opus-4-8`` (same model, now
    subscription-routed). ``anthropic/claude-opus-5`` (not in the catalog — the
    owner's live pin) -> CLEARED to NULL so the tier default (a
    subscription-served Claude) applies; never a silent swap to a different
    model. Re-running changes nothing.
    """
    from app.services.model_pin_repair import repair_claude_model_pins

    _pin(test_user_id, "coverLetter", _UNKNOWN_SLASH)
    _pin(test_user_id, "resumeTailoring", _SLASH)
    _pin(test_user_id, "jobDiscovery", _OPENROUTER)

    report = repair_claude_model_pins(apply=True)
    assert report["normalized"] >= 1, report
    assert report["cleared"] >= 1, report

    def _model(agent_key: str):
        r = client.get(f"/agents/config/{agent_key}", headers=auth_headers)
        assert r.status_code == 200, r.text
        return r.json()["model"]

    assert _model("resumeTailoring") == _BARE
    # Cleared -> the response falls back to the catalog default, which is a
    # subscription-served Claude id, NOT the un-catalogued pin.
    assert _model("coverLetter") != _UNKNOWN_SLASH
    assert _model("coverLetter") != _UNKNOWN_BARE
    # A genuine OpenRouter pick is untouched.
    assert _model("jobDiscovery") == _OPENROUTER

    # Idempotent: a second run has nothing left to do.
    again = repair_claude_model_pins(apply=True)
    assert again["normalized"] == 0 and again["cleared"] == 0, again


def test_repair_records_every_change_it_makes(client, auth_headers, test_user_id):
    """A cleared pin is never silent — each change leaves an audit trace."""
    from app.db import get_connection, rows_to_dicts
    from app.services.model_pin_repair import repair_claude_model_pins

    _pin(test_user_id, "coverLetter", _UNKNOWN_SLASH)
    repair_claude_model_pins(apply=True)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "action", "detailJson" FROM "AdminAuditLog" '
                "WHERE \"action\" = 'agent_model_pin_repair'"
            )
            rows = rows_to_dicts(cur)
    assert rows, "the repair recorded no trace of the pin it cleared"
    blob = str(rows)
    assert _UNKNOWN_SLASH in blob, blob


def test_repair_dry_run_changes_nothing(client, auth_headers, test_user_id):
    """``apply=False`` reports what it WOULD do and writes nothing."""
    from app.db import get_connection, rows_to_dicts
    from app.services.model_pin_repair import repair_claude_model_pins

    _pin(test_user_id, "resumeTailoring", _SLASH)
    report = repair_claude_model_pins(apply=False)
    assert report["normalized"] == 1, report

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "model" FROM "AgentConfig" WHERE "userId" = %s AND "agentKey" = %s',
                (test_user_id, "resumeTailoring"),
            )
            rows = rows_to_dicts(cur)
    assert rows[0]["model"] == _SLASH, "a dry run mutated the row"


def test_the_agents_own_seeded_default_is_accepted_not_422d(client, auth_headers):
    """A client echoing back the value the app itself rendered must not be
    rejected. ``storyExtraction``'s seeded ``recommended`` is a Claude id the
    Anthropic catalog does not carry — but the app wrote it, and
    ``_user_model_override`` treats a stored value equal to it as "no choice
    made", so it never reaches a model. 422-ing our own default would be
    nonsense; an arbitrary unknown Claude id is still rejected (test above).
    """
    from app.routers.agents import _CATALOG_BY_KEY

    seeded = _CATALOG_BY_KEY["storyExtraction"]["recommended"]
    assert seeded.startswith("claude-"), seeded  # the case this guards
    r = client.put(
        "/agents/config/storyExtraction", json={"model": seeded}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["model"] == seeded


def test_repair_leaves_a_seeded_default_row_untouched(client, auth_headers, test_user_id):
    """The repair reports it, and changes nothing: clearing a seed would render
    the identical value again from the catalog — a change that changes nothing.
    """
    from app.db import get_connection, rows_to_dicts
    from app.routers.agents import _CATALOG_BY_KEY
    from app.services.model_pin_repair import repair_claude_model_pins

    seeded = _CATALOG_BY_KEY["storyExtraction"]["recommended"]
    _pin(test_user_id, "storyExtraction", seeded)

    report = repair_claude_model_pins(apply=True)
    assert report["skippedSeedDefaults"] >= 1, report
    assert report["cleared"] == 0, report

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "model" FROM "AgentConfig" WHERE "userId" = %s AND "agentKey" = %s',
                (test_user_id, "storyExtraction"),
            )
            rows = rows_to_dicts(cur)
    assert rows[0]["model"] == seeded


def test_a_legacy_slash_pin_still_in_the_db_is_normalized_at_read_time(
    client, auth_headers, test_user_id
):
    """Belt-and-braces for a row written before the repair runs: the run path
    reads it through the same normalization, so it can never route OpenRouter."""
    from app.routers.agents import _user_model_override

    _pin(test_user_id, "coverLetter", _SLASH)
    assert _user_model_override(test_user_id, "coverLetter") == _BARE


# ---------------------------------------------------------------------------
# CLAUSE 5 — disclosure: no picker path offers a Claude id that bills OpenRouter
# ---------------------------------------------------------------------------


def test_curated_openrouter_catalog_offers_no_claude_models():
    """The picker's OpenRouter catalog must not carry a Claude row — those are
    offered under the Anthropic (subscription) group instead, and picking one
    here would now be routed away from OpenRouter anyway (confusing + wrong)."""
    from app.services.llm_client import _curate_openrouter_models

    raw = [
        {"id": "anthropic/claude-opus-4.8", "name": "Claude Opus 4.8",
         "pricing": {"prompt": "0.000015", "completion": "0.000075"},
         "context_length": 200000},
        {"id": "anthropic/claude-sonnet-5", "name": "Claude Sonnet 5",
         "pricing": {"prompt": "0.000003", "completion": "0.000015"},
         "context_length": 200000},
        {"id": _OPENROUTER, "name": "DeepSeek V4 Pro",
         "pricing": {"prompt": "0.0000005", "completion": "0.000002"},
         "context_length": 128000},
    ]
    ids = [m["id"] for m in _curate_openrouter_models(raw)]
    assert _OPENROUTER in ids, ids
    assert not [i for i in ids if "claude" in i.lower()], ids


def test_anthropic_catalog_still_offers_the_claude_models(client, auth_headers):
    """The Claude models remain offerable — via the Anthropic catalog, which is
    what the subscription serves."""
    r = client.get("/agents/providers/anthropic/models", headers=auth_headers)
    assert r.status_code == 200, r.text
    ids = [m["id"] for m in r.json()["models"]]
    assert _BARE in ids, ids
    assert not [i for i in ids if "/" in i], ids


# ---------------------------------------------------------------------------
# CLAUSE 6 — proof: the billing audit names the subscription
# ---------------------------------------------------------------------------


def test_billing_audit_for_a_claude_pin_reports_anthropic_oauth(
    client, auth_headers, test_user_id, subscription_env
):
    """The disclosure the reviewer reads on a dispatched run.

    FAILS NOW for a slash pin: the audit reports ``provider='openrouter'``.
    """
    from app.routers.agents import _billing_audit

    _pin(test_user_id, "coverLetter", _SLASH)
    audit, provider = _billing_audit(test_user_id, "coverLetter")
    assert provider == "anthropic", audit
    assert audit["provider"] == "anthropic", audit
    assert audit["authMode"] == "oauth_token", audit
    assert audit["credentialSource"] == "database", audit
