"""GAP-P7-DEF-A (Phase-7, CRITICAL) — dual-mode Anthropic credential.

TDD fail-before suite for the approved blueprint
``docs/delivery/PHASE7-DEFECT-A-BLUEPRINT.md`` (fable-5 APPROVED 2026-07-17,
ruling ADR-P7-01). The Phase-7 operator brief supersedes ADR-P6-OAUTH: a user
may paste their OWN ``claude setup-token`` output (``sk-ant-oat01-…``) as an
Anthropic credential. The in-app OAuth *authorize* flow (``subscription_oauth``)
stays removed — that is the retained NON-goal, still asserted here.

Live-probe corrections baked into these tests (BINDING per the gap record):
- ``oauth_token`` mode is transported with ``Authorization: Bearer <token>`` +
  ``anthropic-beta: oauth-2025-04-20`` — NOT ``x-api-key`` (x-api-key returns
  401 for an oat01 token; Bearer+beta returns 200 — see
  ``uat/reports/evidence/phase7/claude-code-token-verification.md``).
- ``api_key`` mode (``sk-ant-api…``) is unchanged: ``x-api-key``.
- The atomic ``.env`` write targets the **repo-root** ``.env`` (resolved from a
  new ``AETHER_ENV_FILE_PATH`` setting), 600-perms, token never logged.

Two kinds of test live here, clearly separated:

  * "NEW-CONTRACT (fail-before)" — exercise behaviour that does NOT exist yet;
    these MUST FAIL against current ``main`` (assertion/ error) and pass only
    after the fix. This is the fail-before gate.
  * "REGRESSION GUARD (pass-before-and-after)" — lock in behaviour the fix must
    NOT break (api_key path unchanged; subscription_oauth still rejected; no
    cross-provider/-mode substitution). Correct TDD keeps these GREEN before AND
    after — they are not fail-before by design.

UPDATE-MARKER (comment only — NO edit performed in this STEP-7): the oat-
rejection tests in ``tests/test_gap_p5_auth_compliance.py`` (namely
``test_put_deployment_credential_rejects_subscription_oauth`` /
``test_put_user_credential_rejects_subscription_oauth`` and the
"x-api-key ONLY / OAuth transport gone" header assertions) are SUPERSEDED by
ADR-P7-01 and blueprint §7.1. They must be inverted/replaced during the
implementation step — NOT in this failing-test commit.

Outbound HTTP is always mocked (``httpx.post`` stubbed) — no live Anthropic
call is ever made by this suite.
"""
from __future__ import annotations

import os
import stat

import httpx
import pytest

from app.repositories.provider_credential import ProviderCredentialRepository
from app.services import credential_vault as vault
from app.services.llm_client import (
    LLMClient,
    ProviderCredentialResolution,
    QuotaExhaustedError,
    resolve_credential,
    user_credential_context,
    verify_resolved_credential,
)

# ---------------------------------------------------------------------------
# Fake token constants — NEVER a real secret. Only the prefix is load-bearing
# (the blueprint derives authMode from the prefix; §1 prefix mapping).
# ---------------------------------------------------------------------------
OAT01_TOKEN = "sk-ant-oat01-FAKEtestTOKENvalue0000000000deadbeef"
API03_KEY = "sk-ant-api03-FAKEtestCONSOLEkeyvalue0000000000"
GARBAGE_SECRET = "sk-GARBAGE-not-a-real-credential"
LEGACY_SUBSCRIPTION_OAUTH = "sk-ant-oat-LEGACYnotOat01token"

_ELLIPSIS = "…"


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    """Deterministic Fernet key so encrypt/decrypt agree within a test."""
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture()
def _clean_provider_credentials():
    """ProviderCredential has no FK to User, so conftest never truncates it —
    self-clean it and reset the repo's process-level table-ready cache."""
    from app.db import get_connection
    from app.repositories import provider_credential as pc_module

    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS "ProviderCredential"')
        conn.commit()
    pc_module._table_ready = False


def _clear_anthropic_env(monkeypatch):
    """Remove every env var that could resolve an Anthropic credential so the
    stored DB row (or its absence) is the ONLY source under test."""
    for var in (
        "ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY", "ABACUS_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


class _StubResponse:
    """Minimal httpx.Response stand-in for the transport assertions."""

    def __init__(self, status_code: int = 200, text: str = "{}", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


# ===========================================================================
# NEW-CONTRACT (fail-before) — credential write path (§2, §14.2)
# ===========================================================================


def test_oat01_token_accepted_returns_200(
    client, auth_headers, monkeypatch, _clean_provider_credentials
):
    """A ``sk-ant-oat01-`` token PUT to the deployment credential endpoint must
    be accepted (200) and stored with server-derived authMode ``oauth_token``.

    FAIL-BEFORE: current ``_validate_provider_auth`` rejects any authMode other
    than ``api_key`` and any anthropic secret not prefixed ``sk-ant-api`` → 422.
    """
    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "oauth_token", "secret": OAT01_TOKEN},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    assert OAT01_TOKEN not in put.text  # plaintext never echoed

    providers = client.get("/agents/providers", headers=auth_headers)
    assert providers.status_code == 200, providers.text
    anthropic = next(p for p in providers.json() if p["id"] == "anthropic")
    assert anthropic["authMode"] == "oauth_token"
    assert anthropic["status"] == "connected"


def test_garbage_credential_returns_422_naming_both_formats(
    client, auth_headers, _clean_provider_credentials
):
    """An unrecognised anthropic secret is a 422 whose message names BOTH
    accepted formats (Console ``sk-ant-api`` AND OAuth ``sk-ant-oat01-``), per
    GATE-04 / J1 step 10.

    FAIL-BEFORE: current 422 message only names ``sk-ant-api``.
    """
    res = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "api_key", "secret": GARBAGE_SECRET},
        headers=auth_headers,
    )
    assert res.status_code == 422, res.text
    body = res.text
    assert "sk-ant-api" in body
    assert "sk-ant-oat01-" in body  # the new format MUST be named too
    assert GARBAGE_SECRET not in body  # the value itself is never echoed


def test_oat01_writes_env_var_atomically(
    client, auth_headers, monkeypatch, tmp_path, _clean_provider_credentials
):
    """Saving an oat01 credential writes ``CLAUDE_CODE_OAUTH_TOKEN=<token>`` to
    the env file named by ``AETHER_ENV_FILE_PATH`` (§3.3).

    FAIL-BEFORE: the save is rejected (422) and no env-write logic exists, so
    the target file is never created.
    """
    env_file = tmp_path / ".env"
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(env_file))

    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "oauth_token", "secret": OAT01_TOKEN},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    assert env_file.exists(), "env file was not written"
    content = env_file.read_text()
    assert f"CLAUDE_CODE_OAUTH_TOKEN={OAT01_TOKEN}" in content
    # Exactly one such line — the write replaces-or-appends, never duplicates.
    assert content.count("CLAUDE_CODE_OAUTH_TOKEN=") == 1


def test_oat01_env_var_has_600_permissions(
    client, auth_headers, monkeypatch, tmp_path, _clean_provider_credentials
):
    """The written env file must be mode 0o600 (temp+fchmod+rename, §3.3).

    FAIL-BEFORE: no file is written, so there is nothing at 0o600.
    """
    env_file = tmp_path / ".env"
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(env_file))

    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "oauth_token", "secret": OAT01_TOKEN},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    assert env_file.exists(), "env file was not written"
    mode = stat.S_IMODE(os.stat(env_file).st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_token_never_logged_in_response_body(
    client, auth_headers, monkeypatch, caplog, tmp_path, _clean_provider_credentials
):
    """The full oat01 token is never echoed in the response nor emitted to logs;
    only the masked ``…last4`` hint is exposed (§9 security invariant).

    FAIL-BEFORE: the save is rejected (422) so the 200/masked-hint contract does
    not hold yet (the first assertion fails against current code).
    """
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(tmp_path / ".env"))
    caplog.set_level("DEBUG")

    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "oauth_token", "secret": OAT01_TOKEN},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    row = put.json()
    assert row.get("secretHint") == f"{_ELLIPSIS}{OAT01_TOKEN[-4:]}"
    assert OAT01_TOKEN not in put.text
    # The full token must never reach the logs either.
    assert OAT01_TOKEN not in caplog.text
    providers = client.get("/agents/providers", headers=auth_headers)
    assert OAT01_TOKEN not in providers.text


# ===========================================================================
# NEW-CONTRACT (fail-before) — per-mode verify transport (§4, §5.1)
# ===========================================================================


def test_verify_endpoint_oat01_uses_bearer_and_beta_header(monkeypatch):
    """The verify round-trip for an ``oauth_token`` credential sends
    ``Authorization: Bearer`` + ``anthropic-beta: oauth-2025-04-20`` and does
    NOT send ``x-api-key`` (live-probe correction).

    FAIL-BEFORE: ``anthropic_auth_headers('oauth_token', …)`` raises today, so
    the verify aborts before any HTTP and no headers are ever captured.
    """
    captured: dict[str, dict] = {}

    def _fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured["headers"] = dict(headers or {})
        return _StubResponse(status_code=200, text="{}", payload={"content": []})

    monkeypatch.setattr(httpx, "post", _fake_post)

    cred = ProviderCredentialResolution(
        provider="anthropic", auth_mode="oauth_token", secret=OAT01_TOKEN,
        base_url=None, source="database",
    )
    ok, status_token, _detail = verify_resolved_credential("anthropic", cred)

    assert "headers" in captured, "no HTTP was issued — header builder rejected oauth_token"
    sent = {k.lower(): v for k, v in captured["headers"].items()}
    assert sent.get("authorization") == f"Bearer {OAT01_TOKEN}"
    assert sent.get("anthropic-beta") == "oauth-2025-04-20"
    assert "x-api-key" not in sent
    assert ok is True and status_token == "ok"


# ===========================================================================
# NEW-CONTRACT (fail-before) — quota exhaustion never falls through (§5.4)
# ===========================================================================


def test_quota_exhaustion_oat01_does_not_fall_through_to_api_key(monkeypatch):
    """A subscription-quota 429 on an oauth_token call surfaces an explicit
    ``QuotaExhaustedError`` (→ HTTP 429) and NEVER retries with a different
    (api_key) credential — no silent cross-credential billing (GATE-06).

    FAIL-BEFORE: current ``_call_live`` cannot even build the oauth_token request
    (header builder raises) and has no 429→QuotaExhaustedError wiring, so a plain
    ``RuntimeError`` is raised instead of ``QuotaExhaustedError``.
    """
    # No pre-existing cooldown block should short-circuit the run.
    monkeypatch.setattr(
        "app.services.llm_client._active_quota_block", lambda uid, prov: None
    )

    oauth_cred = ProviderCredentialResolution(
        provider="anthropic", auth_mode="oauth_token", secret=OAT01_TOKEN,
        base_url=None, source="database",
    )
    monkeypatch.setattr(
        "app.services.llm_client.resolve_user_credential",
        lambda provider, user_id=None, agent_key=None: oauth_cred,
    )

    calls: list[dict] = []

    def _fake_post(url, json=None, headers=None, timeout=None, **kw):
        calls.append(dict(headers or {}))
        return _StubResponse(
            status_code=429,
            text='{"type":"error","error":{"type":"rate_limit_error","message":'
                 '"You have exceeded your plan usage limit / quota."}}',
            payload={
                "type": "error",
                "error": {
                    "type": "rate_limit_error",
                    "message": "You have exceeded your plan usage limit / quota.",
                },
            },
        )

    monkeypatch.setattr(httpx, "post", _fake_post)

    llm = LLMClient(mode="live")
    with user_credential_context("quota-test-user", "coverLetter"):
        with pytest.raises(QuotaExhaustedError):
            llm._call_live(
                "sys", "usr", model="claude-opus-4-8", temperature=0.0
            )

    # Whatever HTTP was made, the api_key secret must never have been used —
    # there is no reroute to a second credential.
    for sent in calls:
        lowered = {k.lower(): v for k, v in sent.items()}
        assert lowered.get("x-api-key") != API03_KEY
        assert API03_KEY not in lowered.values()


# ===========================================================================
# NEW-CONTRACT (fail-before) — billing audit records oauth_token (§5.3, GATE-05)
# ===========================================================================


def test_billing_audit_records_auth_mode_oauth(
    client, auth_headers, test_user_id, monkeypatch, _clean_provider_credentials
):
    """After an oauth_token credential is stored, the run billing audit records
    ``authMode == 'oauth_token'`` for an Anthropic-routed agent.

    FAIL-BEFORE: the credential cannot be stored (422), so resolution yields no
    credential and the audit records ``authMode == None``.
    """
    from app.routers.agents import _billing_audit

    _clear_anthropic_env(monkeypatch)
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-opus-4-8")

    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "oauth_token", "secret": OAT01_TOKEN},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text

    audit, provider = _billing_audit(test_user_id, "coverLetter")
    assert provider == "anthropic"
    assert audit["authMode"] == "oauth_token"


# ===========================================================================
# REGRESSION GUARD (pass-before-and-after) — api_key path is byte-for-byte
# unchanged; subscription_oauth stays blocked; no cross-mode substitution.
# ===========================================================================


def test_api03_key_still_accepted_returns_200(
    client, auth_headers, _clean_provider_credentials
):
    """REGRESSION: a Console ``sk-ant-api03-`` key is still accepted (200) and
    stored as ``api_key``. The fix must not disturb the existing path."""
    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "api_key", "secret": API03_KEY},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    anthropic = next(
        p for p in client.get("/agents/providers", headers=auth_headers).json()
        if p["id"] == "anthropic"
    )
    assert anthropic["authMode"] == "api_key"


def test_api03_does_not_write_env_var(
    client, auth_headers, monkeypatch, tmp_path, _clean_provider_credentials
):
    """REGRESSION/invariant: saving an api_key credential NEVER writes
    ``CLAUDE_CODE_OAUTH_TOKEN`` — the ``.env`` write is oauth_token-only (§3.3,
    GATE)."""
    env_file = tmp_path / ".env"  # deliberately absent
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(env_file))

    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "api_key", "secret": API03_KEY},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    if env_file.exists():
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env_file.read_text()


def test_verify_endpoint_api03_uses_x_api_key(monkeypatch):
    """REGRESSION: verify for an ``api_key`` credential still sends ``x-api-key``
    and no OAuth transport headers."""
    captured: dict[str, dict] = {}

    def _fake_post(url, json=None, headers=None, timeout=None, **kw):
        captured["headers"] = dict(headers or {})
        return _StubResponse(status_code=200, text="{}", payload={"content": []})

    monkeypatch.setattr(httpx, "post", _fake_post)

    cred = ProviderCredentialResolution(
        provider="anthropic", auth_mode="api_key", secret=API03_KEY,
        base_url=None, source="database",
    )
    ok, status_token, _detail = verify_resolved_credential("anthropic", cred)

    sent = {k.lower(): v for k, v in captured.get("headers", {}).items()}
    assert sent.get("x-api-key") == API03_KEY
    assert "authorization" not in sent
    assert "anthropic-beta" not in sent
    assert ok is True and status_token == "ok"


def test_billing_audit_records_auth_mode_api_key(
    client, auth_headers, test_user_id, monkeypatch, _clean_provider_credentials
):
    """REGRESSION: an api_key credential yields ``authMode == 'api_key'`` in the
    run billing audit."""
    from app.routers.agents import _billing_audit

    _clear_anthropic_env(monkeypatch)
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-opus-4-8")

    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "api_key", "secret": API03_KEY},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text

    audit, provider = _billing_audit(test_user_id, "coverLetter")
    assert provider == "anthropic"
    assert audit["authMode"] == "api_key"


def test_no_cross_credential_substitution(monkeypatch, _clean_provider_credentials):
    """REGRESSION/invariant: the resolver never returns a different-provider or
    different-authMode secret than the one stored for the requested provider
    (ADR-PC-2). Covers oauth_token as well as api_key."""
    _clear_anthropic_env(monkeypatch)

    repo = ProviderCredentialRepository()
    repo.upsert("anthropic", auth_mode="oauth_token", secret=OAT01_TOKEN)
    repo.upsert("openrouter", auth_mode="api_key", secret="sk-or-DISTINCTvalue")

    anth = resolve_credential("anthropic")
    assert anth is not None
    assert anth.provider == "anthropic"
    assert anth.auth_mode == "oauth_token"
    assert anth.secret == OAT01_TOKEN

    orr = resolve_credential("openrouter")
    assert orr is not None
    assert orr.provider == "openrouter"
    assert orr.secret == "sk-or-DISTINCTvalue"

    # No leakage across providers.
    assert anth.secret != orr.secret
    assert OAT01_TOKEN not in (orr.secret or "")


def test_legacy_subscription_oauth_label_still_rejected(
    client, auth_headers, _clean_provider_credentials
):
    """REGRESSION (ADR-P7-01 NON-goal): the in-app OAuth *authorize* label
    ``subscription_oauth`` (and a non-oat01 ``sk-ant-oat`` secret) stays a 422 on
    the write path — only the pasted ``sk-ant-oat01-`` token is new."""
    res = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "subscription_oauth", "secret": LEGACY_SUBSCRIPTION_OAUTH},
        headers=auth_headers,
    )
    assert res.status_code == 422, res.text
