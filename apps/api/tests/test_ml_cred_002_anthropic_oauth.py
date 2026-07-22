"""ML-agents-cred-002 (MODELS-LIVE, BLOCKER) — in-app "Connect with Anthropic"
(subscription) OAuth authorize/exchange/refresh flow.

TDD fail-before suite for the operator-mandated flow (ADR-ML-1) ruled on and
approved for implementation in ``docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md``
(ADR-ML-2 + ADR-ML-2a) and specified in ``docs/delivery/ML-agents-cred-002-
BLUEPRINT.md`` (the two blueprints on disk CONFLICT on the authorize URL/scope
— ADR-ML-2a's ruling is authoritative and is what this file pins).

**Nothing under test exists in current code.** ``apps/api/app/services/
anthropic_oauth.py`` does not exist; ``agents.py`` has no
``/providers/anthropic/oauth/{start,exchange,refresh}`` routes (only a
tombstone comment at agents.py:2422-2430 recording that the OLD, non-compliant
in-app OAuth was removed). Every test below is written to FAIL against the
current tree — via ``ModuleNotFoundError``/``ImportError`` for the
module-level tests, and ``404 Not Found`` for the router tests — and to PASS
once the fixer implements the module + routes below.

**Required module surface** (the contract this suite pins for the fixer —
mirrors ``docs/delivery/ML-agents-cred-002-BLUEPRINT.md`` §2/§4.1, reconciled
by ADR-ML-2a's DECISION-1 token-store ruling):

    apps/api/app/services/anthropic_oauth.py
        AUTHORIZE_URL, CLIENT_ID, SCOPE, TOKEN_URL, REDIRECT_URI  (module
            "constants" — MUST be re-read from os.environ on every call, not
            frozen at import time, so tests can monkeypatch them; mirrors the
            existing lazy-env-read convention in llm_client.get_anthropic_max_tokens)
        generate_pkce() -> tuple[str, str]           # (verifier, challenge) S256
        generate_state() -> str                      # opaque, url-safe
        build_authorize_url(challenge: str, state: str) -> str
        class OAuthExchangeError(RuntimeError): ...
        _post_token(body: dict) -> dict               # isolated httpx.post wrapper
                                                        # (THE monkeypatch seam)
        exchange_code(code: str, verifier: str, state: str) -> dict
            # -> {"access_token", "refresh_token", "expires_at", "scope"}
        refresh_tokens(refresh_token: str) -> dict
        refresh_if_needed(user_id: str) -> str | None
            # Auto-refresh-before-expiry hook (ADR-ML-2 ruling #3, DECISION-1b).
            # MUST write a refreshed access token into the SAME deployment-wide
            # ProviderCredential("anthropic") row llm_client.resolve_credential
            # already reads (ADR-ML-2a DECISION-1 — "single authoritative
            # source wired into the EXISTING runtime resolver"), so cron/
            # background (no user_id) live calls see the refreshed token too.
            # On refresh failure: AnthropicOAuthTokenRepository.mark_needs_reauth
            # and raise/return honestly — NEVER return a stale token, NEVER
            # fall through to another provider.

    apps/api/app/routers/agents.py (new routes, deployment-wide + auth
        required, per ADR-ML-2 ruling #2 + ADR-ML-2a):
        POST /agents/providers/anthropic/oauth/start
            -> 200 {"authorizeUrl": str}; 503 if AETHER_CREDENTIAL_KEY absent.
        POST /agents/providers/anthropic/oauth/exchange  body {"pastedCode": str}
            -> 200 masked provider-status object (authMode == "oauth_token");
               422 malformed paste (no '#' / empty half); 400 unknown/expired/
               replayed state; 502 honest token-endpoint error (incl.
               unexpected response shape — defensive parse, never fake success).
        POST /agents/providers/anthropic/oauth/refresh
            -> 200 rotated masked status; 502 honest error + needs_reauth
               marked on failure (no cross-provider fallback).

Run under the shared test DB lock (schema=aether_test ONLY):
    flock /tmp/aether-pytest.lock python3 -m pytest \
        tests/test_ml_cred_002_anthropic_oauth.py -q
"""
from __future__ import annotations

import base64
import hashlib
import importlib
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services import credential_vault as vault

# ---------------------------------------------------------------------------
# Fake token constants — NEVER a real secret. Shape mirrors ML-agents-cred-001
# anchors (sk-ant-oat01- access, sk-ant-ort01- refresh, per ADR-ML-2 ruling #4).
# ---------------------------------------------------------------------------
FAKE_ACCESS_1 = "sk-ant-oat01-FAKEtestACCESSvalue0000000000deadbeef"
FAKE_ACCESS_2 = "sk-ant-oat01-FAKEtestACCESSvalue1111111111deadbeef"
FAKE_REFRESH_1 = "sk-ant-ort01-FAKEtestREFRESHvalue0000000000deadbeef"
FAKE_REFRESH_2 = "sk-ant-ort01-FAKEtestREFRESHvalue1111111111deadbeef"


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    """Deterministic Fernet key so encrypt/decrypt agree within a test."""
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch, tmp_path):
    """A credential save must NEVER touch the real repo-root ``.env`` during
    tests — default the oauth_token sync target to a per-test tmp file."""
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(tmp_path / "default.env"))


@pytest.fixture()
def _clean_anthropic_oauth_state():
    """None of ProviderCredential / AnthropicOAuthState / AnthropicOAuthToken /
    UserProviderCredential carry an FK to ``User``, so conftest's per-test
    ``_truncate_tables`` never touches them (mirrors test_ml_cred_001.py's
    ``_clean_provider_credentials``). Self-clean after each test so state
    tokens / stored credentials from one test never leak into the next."""
    from app.db import get_connection
    from app.repositories import provider_credential as pc_module
    from app.repositories import user_provider_credential as upc_module

    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS "ProviderCredential"')
            cur.execute('DROP TABLE IF EXISTS "AnthropicOAuthState"')
            cur.execute('DROP TABLE IF EXISTS "AnthropicOAuthToken"')
            cur.execute('DROP TABLE IF EXISTS "UserProviderCredential"')
        conn.commit()
    pc_module._table_ready = False
    upc_module._reset_ready_for_tests()


def _clear_anthropic_env(monkeypatch):
    """Remove every env var that could resolve an Anthropic credential so the
    stored DB row (or its absence) is the ONLY source under test."""
    for var in (
        "ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY", "ABACUS_API_KEY",
        "AETHER_ANTHROPIC_OAUTH_AUTHORIZE_URL", "AETHER_ANTHROPIC_OAUTH_CLIENT_ID",
        "AETHER_ANTHROPIC_OAUTH_SCOPE",
    ):
        monkeypatch.delenv(var, raising=False)


def _raw_state_row(state_token: str) -> dict | None:
    """Direct SQL peek at an ``AnthropicOAuthState`` row WITHOUT consuming it
    (``AnthropicOAuthStateRepository.consume`` is a destructive fetch-and-delete
    — using it here would break the exchange test that needs the row intact)."""
    from app.db import get_connection, rows_to_dicts

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "stateToken", "userId", "codeVerifier", "expiresAt" '
                'FROM "AnthropicOAuthState" WHERE "stateToken" = %s',
                (state_token,),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def _expire_state_row(state_token: str) -> None:
    """Force a live state row into the past so a subsequent consume() honestly
    reports it as expired (single-use TTL enforcement, not just unknown-token)."""
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "AnthropicOAuthState" SET "expiresAt" = now() - interval \'1 minute\' '
                'WHERE "stateToken" = %s',
                (state_token,),
            )
        conn.commit()


def _extract_state_from_authorize_url(authorize_url: str) -> str:
    qs = parse_qs(urlsplit(authorize_url).query)
    assert "state" in qs, f"authorizeUrl carries no state param: {authorize_url}"
    return qs["state"][0]


def _seed_deployment_anthropic_credential(secret: str) -> None:
    """Seed the deployment-wide ProviderCredential('anthropic') row directly
    (bypassing the exchange endpoint) so refresh/auto-refresh tests can start
    from an already-connected state."""
    from app.repositories.provider_credential import ProviderCredentialRepository

    ProviderCredentialRepository().upsert("anthropic", auth_mode="oauth_token", secret=secret)


def _fake_token_response(access: str, refresh: str, *, expires_in: int = 31536000) -> dict:
    """A well-formed token-endpoint JSON body (the shape ``_post_token`` must
    return on 2xx) — the single seam ``anthropic_oauth._post_token`` is
    monkeypatched to return in the happy-path tests."""
    return {"access_token": access, "refresh_token": refresh, "expires_in": expires_in}


# ===========================================================================
# 1. POST /oauth/start — 200, authorizeUrl + persisted state row
# FAIL-BEFORE (WHY): route does not exist on the router at all → 404.
# ===========================================================================


def test_oauth_start_returns_authorize_url_and_persists_state(
    client, auth_headers, test_user_id, _clean_anthropic_oauth_state
):
    resp = client.post("/agents/providers/anthropic/oauth/start", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "authorizeUrl" in body, body
    authorize_url = body["authorizeUrl"]

    qs = parse_qs(urlsplit(authorize_url).query)
    assert qs.get("client_id"), authorize_url
    assert qs.get("response_type") == ["code"], authorize_url
    assert qs.get("code_challenge"), authorize_url
    assert qs.get("code_challenge_method") == ["S256"], authorize_url
    assert qs.get("state"), authorize_url

    state = qs["state"][0]
    row = _raw_state_row(state)
    assert row is not None, "no AnthropicOAuthState row was persisted for the returned state"
    assert row["userId"] == test_user_id
    assert row["codeVerifier"], "codeVerifier must be stored server-side"

    # The verifier is NEVER re-exposed to the client (server-side PKCE only).
    assert row["codeVerifier"] not in resp.text


def test_oauth_start_503_when_credential_key_absent(
    client, auth_headers, monkeypatch, _clean_anthropic_oauth_state
):
    """The refresh token can't be stored honestly without the vault key — the
    endpoint must fail closed (503), never silently proceed unencrypted."""
    monkeypatch.delenv("AETHER_CREDENTIAL_KEY", raising=False)
    resp = client.post("/agents/providers/anthropic/oauth/start", headers=auth_headers)
    assert resp.status_code == 503, resp.text


# ===========================================================================
# 2. Authorize URL host/scope: env-overridable, default to SUBSCRIPTION
#    setup-token values (ADR-ML-2a RULING) — NOT org:create_api_key.
# FAIL-BEFORE (WHY): ``app.services.anthropic_oauth`` module does not exist
# → ModuleNotFoundError.
# ===========================================================================


def test_authorize_url_defaults_to_subscription_setup_token_flow(_clean_anthropic_oauth_state):
    from app.services import anthropic_oauth

    verifier, challenge = anthropic_oauth.generate_pkce()
    state = anthropic_oauth.generate_state()
    url = anthropic_oauth.build_authorize_url(challenge, state)

    parts = urlsplit(url)
    qs = parse_qs(parts.query)
    # ADR-ML-2a RULING: default = the `claude setup-token` SUBSCRIPTION flow
    # (scope centered on user:inference), NOT the org:create_api_key
    # console/API-key-creation flow Blueprint B proposed.
    origin = f"{parts.scheme}://{parts.netloc}{parts.path}"
    assert origin == "https://claude.com/cai/oauth/authorize", url
    assert qs.get("scope") == ["user:inference"], url
    assert "org:create_api_key" not in url
    assert qs.get("client_id") == ["9d1c250a-e61b-44d9-88ed-5944d1962f5e"], url
    assert qs.get("code_challenge") == [challenge], url
    assert qs.get("code_challenge_method") == ["S256"], url
    assert qs.get("state") == [state], url


def test_authorize_url_constants_are_env_overridable(monkeypatch, _clean_anthropic_oauth_state):
    """ADR-ML-2a: 'the fixer MUST centralize authorize_url + client_id + scope
    as env-overridable constants (AETHER_ANTHROPIC_OAUTH_AUTHORIZE_URL /
    _CLIENT_ID / _SCOPE)' — this de-risks the INFERRED authorize host without
    a code change if the operator's live consent click reveals the other
    candidate URL is correct instead."""
    monkeypatch.setenv(
        "AETHER_ANTHROPIC_OAUTH_AUTHORIZE_URL", "https://example-staging.test/oauth/authorize"
    )
    monkeypatch.setenv("AETHER_ANTHROPIC_OAUTH_CLIENT_ID", "staging-client-id-override")
    monkeypatch.setenv("AETHER_ANTHROPIC_OAUTH_SCOPE", "user:inference staging:extra")

    from app.services import anthropic_oauth

    importlib.reload(anthropic_oauth)  # tolerate either import-time-frozen or lazy env reads
    try:
        verifier, challenge = anthropic_oauth.generate_pkce()
        state = anthropic_oauth.generate_state()
        url = anthropic_oauth.build_authorize_url(challenge, state)
        parts = urlsplit(url)
        qs = parse_qs(parts.query)
        origin = f"{parts.scheme}://{parts.netloc}{parts.path}"
        assert origin == "https://example-staging.test/oauth/authorize", url
        assert qs.get("client_id") == ["staging-client-id-override"], url
        assert qs.get("scope") == ["user:inference staging:extra"], url
    finally:
        monkeypatch.undo()
        importlib.reload(anthropic_oauth)  # restore defaults for subsequent tests


# ===========================================================================
# 3. PKCE: two starts produce different verifier/challenge + different state
# FAIL-BEFORE (WHY): ModuleNotFoundError (module absent).
# ===========================================================================


def test_pkce_two_generations_differ_and_challenge_is_s256_of_verifier(
    _clean_anthropic_oauth_state,
):
    from app.services import anthropic_oauth

    v1, c1 = anthropic_oauth.generate_pkce()
    v2, c2 = anthropic_oauth.generate_pkce()
    s1 = anthropic_oauth.generate_state()
    s2 = anthropic_oauth.generate_state()

    assert v1 != v2, "two PKCE generations must not reuse the same verifier"
    assert c1 != c2, "two PKCE generations must not reuse the same challenge"
    assert s1 != s2, "two state generations must not collide"

    # S256: challenge == base64url(sha256(verifier)) with no padding.
    digest = hashlib.sha256(v1.encode()).digest()
    expected_c1 = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert c1 == expected_c1, "code_challenge must be the S256 digest of its own verifier"


def test_oauth_start_called_twice_persists_two_distinct_state_rows(
    client, auth_headers, _clean_anthropic_oauth_state
):
    first = client.post("/agents/providers/anthropic/oauth/start", headers=auth_headers)
    second = client.post("/agents/providers/anthropic/oauth/start", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    state1 = _extract_state_from_authorize_url(first.json()["authorizeUrl"])
    state2 = _extract_state_from_authorize_url(second.json()["authorizeUrl"])
    assert state1 != state2

    row1 = _raw_state_row(state1)
    row2 = _raw_state_row(state2)
    assert row1 is not None and row2 is not None
    assert row1["codeVerifier"] != row2["codeVerifier"]


# ===========================================================================
# 4. exchange happy path: mocked token endpoint -> 200, token stored,
#    authMode oauth_token, state consumed (single-use).
# FAIL-BEFORE (WHY): route absent -> 404 at the `start` setup step itself.
# ===========================================================================


def test_exchange_happy_path_stores_oauth_token_and_consumes_state(
    client, auth_headers, test_user_id, monkeypatch, _clean_anthropic_oauth_state
):
    start = client.post("/agents/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    state = _extract_state_from_authorize_url(start.json()["authorizeUrl"])

    from app.services import anthropic_oauth

    def _fake_post_token(body):
        assert body.get("state") == state, body
        return {
            "access_token": FAKE_ACCESS_1,
            "refresh_token": FAKE_REFRESH_1,
            "expires_in": 31536000,
            "token_type": "Bearer",
        }

    monkeypatch.setattr(anthropic_oauth, "_post_token", _fake_post_token)

    exchange = client.post(
        "/agents/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"FAKEONETIMECODE#{state}"},
        headers=auth_headers,
    )
    assert exchange.status_code == 200, exchange.text
    assert FAKE_ACCESS_1 not in exchange.text
    assert FAKE_REFRESH_1 not in exchange.text

    from app.repositories.provider_credential import ProviderCredentialRepository
    from app.repositories.user_provider_credential import AnthropicOAuthTokenRepository

    pc = ProviderCredentialRepository().get_secret("anthropic")
    assert pc is not None, (
        "exchange must persist the access token to ProviderCredential "
        "(deployment-wide, DECISION-1)"
    )
    assert pc["authMode"] == "oauth_token"
    assert pc["secret"] == FAKE_ACCESS_1

    tok = AnthropicOAuthTokenRepository().get(test_user_id)
    assert tok is not None, "refresh material must be persisted in AnthropicOAuthToken"
    assert tok["refreshCipher"], "refresh cipher must be stored (non-empty)"

    # Single-use: the state must now be consumed (a second consume() -> None).
    from app.repositories.user_provider_credential import AnthropicOAuthStateRepository

    assert AnthropicOAuthStateRepository().consume(state) is None, (
        "the state row must be deleted (single-use) once the exchange succeeds"
    )


def test_exchange_sends_json_body_with_expected_grant_fields(
    client, auth_headers, monkeypatch, _clean_anthropic_oauth_state
):
    """Exchange & refresh bodies are JSON (not form-encoded — deliberately NOT
    the deleted historical module's shape) and MUST include ``state``."""
    start = client.post("/agents/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    state = _extract_state_from_authorize_url(start.json()["authorizeUrl"])

    from app.services import anthropic_oauth

    captured: dict = {}

    def _fake_post_token(body):
        captured.update(body)
        return _fake_token_response(FAKE_ACCESS_1, FAKE_REFRESH_1)

    monkeypatch.setattr(anthropic_oauth, "_post_token", _fake_post_token)

    resp = client.post(
        "/agents/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"FAKEONETIMECODE#{state}"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured.get("grant_type") == "authorization_code", captured
    assert captured.get("code") == "FAKEONETIMECODE", captured
    assert captured.get("state") == state, captured
    assert captured.get("code_verifier"), (
        "the server-held verifier must be sent, never the client's"
    )
    assert captured.get("client_id"), captured


# ===========================================================================
# 5. exchange with unknown/expired/replayed state -> 4xx, nothing stored.
# FAIL-BEFORE (WHY): the `start` setup call 404s (route absent).
# ===========================================================================


def test_exchange_unknown_state_rejected(client, auth_headers, _clean_anthropic_oauth_state):
    resp = client.post(
        "/agents/providers/anthropic/oauth/exchange",
        json={"pastedCode": "SOMECODE#totally-unknown-state-token-xyz"},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    from app.repositories.provider_credential import ProviderCredentialRepository

    assert ProviderCredentialRepository().get_secret("anthropic") is None


def test_exchange_expired_state_rejected(
    client, auth_headers, monkeypatch, _clean_anthropic_oauth_state
):
    start = client.post("/agents/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    state = _extract_state_from_authorize_url(start.json()["authorizeUrl"])
    _expire_state_row(state)

    from app.services import anthropic_oauth

    monkeypatch.setattr(
        anthropic_oauth, "_post_token",
        lambda body: pytest.fail("token endpoint must never be called for an expired state"),
    )

    resp = client.post(
        "/agents/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"SOMECODE#{state}"},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text


def test_exchange_replayed_state_rejected_single_use(
    client, auth_headers, monkeypatch, _clean_anthropic_oauth_state
):
    start = client.post("/agents/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    state = _extract_state_from_authorize_url(start.json()["authorizeUrl"])

    from app.services import anthropic_oauth

    monkeypatch.setattr(
        anthropic_oauth, "_post_token",
        lambda body: _fake_token_response(FAKE_ACCESS_1, FAKE_REFRESH_1),
    )

    first = client.post(
        "/agents/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"FAKECODE#{state}"},
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text

    replay = client.post(
        "/agents/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"FAKECODE#{state}"},
        headers=auth_headers,
    )
    assert replay.status_code == 400, replay.text


# ===========================================================================
# 6. exchange with unexpected token-endpoint shape -> honest error,
#    NOTHING stored (defensive parse, never a fake success).
# FAIL-BEFORE (WHY): the `start` setup call 404s (route absent).
# ===========================================================================


def test_exchange_unexpected_token_response_shape_is_honest_error(
    client, auth_headers, monkeypatch, _clean_anthropic_oauth_state
):
    start = client.post("/agents/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    state = _extract_state_from_authorize_url(start.json()["authorizeUrl"])

    from app.services import anthropic_oauth

    # A nominal 2xx-shaped dict MISSING access_token — the parser must not
    # silently treat this as success.
    monkeypatch.setattr(
        anthropic_oauth, "_post_token",
        lambda body: {"token_type": "Bearer", "expires_in": 31536000},
    )

    resp = client.post(
        "/agents/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"FAKECODE#{state}"},
        headers=auth_headers,
    )
    assert resp.status_code in (400, 422) or resp.status_code >= 500, resp.text
    assert resp.status_code != 200, (
        "an unexpected token-endpoint shape must NEVER be a fake success"
    )

    from app.repositories.provider_credential import ProviderCredentialRepository

    assert ProviderCredentialRepository().get_secret("anthropic") is None, (
        "nothing may be stored when the token-endpoint response shape is unrecognized"
    )
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "AnthropicOAuthToken"')
            count = cur.fetchone()[0]
    assert count == 0, "no AnthropicOAuthToken row may be written on a malformed token response"


# ===========================================================================
# 7. exchange with malformed pastedCode (no '#' / empty half) -> 422 honest.
# FAIL-BEFORE (WHY): with no route, POST returns 404 — distinct from the 422
# this test pins, so this correctly fails-before for the right reason (the
# assertion is an exact status match, not a lenient 4xx range).
# ===========================================================================


@pytest.mark.parametrize(
    "pasted,label",
    [
        ("justacodenohashmark", "no-hash-separator"),
        ("CODEVALUE#", "empty-state-half"),
        ("#STATEVALUE", "empty-code-half"),
        ("", "empty-string"),
    ],
)
def test_exchange_malformed_pasted_code_rejected_422(
    client, auth_headers, pasted, label, _clean_anthropic_oauth_state
):
    resp = client.post(
        "/agents/providers/anthropic/oauth/exchange",
        json={"pastedCode": pasted},
        headers=auth_headers,
    )
    assert resp.status_code == 422, f"[{label}] {resp.text}"
    # Neither half of a malformed paste (nor any literal secret) is echoed back.
    if pasted:
        assert pasted not in resp.text, f"[{label}] the submitted value must never be echoed"


# ===========================================================================
# 8. refresh happy path: mocked refresh -> new access+refresh rotated+stored.
# FAIL-BEFORE (WHY): route absent -> 404.
# ===========================================================================


def test_refresh_happy_path_rotates_and_stores_new_token(
    client, auth_headers, test_user_id, monkeypatch, _clean_anthropic_oauth_state
):
    from app.repositories.provider_credential import ProviderCredentialRepository
    from app.repositories.user_provider_credential import AnthropicOAuthTokenRepository

    _seed_deployment_anthropic_credential(FAKE_ACCESS_1)
    AnthropicOAuthTokenRepository().upsert(
        test_user_id,
        access_ciphertext=vault.encrypt(FAKE_ACCESS_1),
        refresh_ciphertext=vault.encrypt(FAKE_REFRESH_1),
        secret_hint=vault.secret_hint(FAKE_ACCESS_1),
        expires_at="2020-01-01T00:00:00Z",
        scopes="user:inference",
    )

    from app.services import anthropic_oauth

    def _fake_post_token(body):
        assert body.get("grant_type") == "refresh_token", body
        assert body.get("refresh_token") == FAKE_REFRESH_1, body
        return _fake_token_response(FAKE_ACCESS_2, FAKE_REFRESH_2)

    monkeypatch.setattr(anthropic_oauth, "_post_token", _fake_post_token)

    resp = client.post("/agents/providers/anthropic/oauth/refresh", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert FAKE_ACCESS_2 not in resp.text
    assert FAKE_REFRESH_2 not in resp.text

    pc = ProviderCredentialRepository().get_secret("anthropic")
    assert pc["secret"] == FAKE_ACCESS_2, "the deployment-wide credential must be rotated"

    tok = AnthropicOAuthTokenRepository().get(test_user_id)
    assert vault.decrypt(tok["ciphertext"]) == FAKE_ACCESS_2
    assert vault.decrypt(tok["refreshCipher"]) == FAKE_REFRESH_2
    assert tok["scopes"] != "needs_reauth"


# ===========================================================================
# 9. refresh FAILURE -> needs_reauth marked, honest error, NO cross-provider
#    fallback (never reroutes to openrouter / never fabricates success).
# FAIL-BEFORE (WHY): route absent -> 404.
# ===========================================================================


def test_refresh_failure_marks_needs_reauth_honest_error_no_cross_provider_fallback(
    client, auth_headers, test_user_id, monkeypatch, _clean_anthropic_oauth_state
):
    from app.repositories.user_provider_credential import AnthropicOAuthTokenRepository

    _seed_deployment_anthropic_credential(FAKE_ACCESS_1)
    AnthropicOAuthTokenRepository().upsert(
        test_user_id,
        access_ciphertext=vault.encrypt(FAKE_ACCESS_1),
        refresh_ciphertext=vault.encrypt(FAKE_REFRESH_1),
        secret_hint=vault.secret_hint(FAKE_ACCESS_1),
        expires_at="2020-01-01T00:00:00Z",
        scopes="user:inference",
    )

    from app.services import anthropic_oauth

    def _fail_post_token(body):
        raise anthropic_oauth.OAuthExchangeError("invalid_grant: refresh token expired or revoked")

    monkeypatch.setattr(anthropic_oauth, "_post_token", _fail_post_token)

    _clear_anthropic_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key-untouched-000")

    resp = client.post("/agents/providers/anthropic/oauth/refresh", headers=auth_headers)
    assert resp.status_code >= 400, resp.text
    assert resp.status_code != 200, "a refresh failure must never be reported as a success"
    assert FAKE_REFRESH_1 not in resp.text

    tok = AnthropicOAuthTokenRepository().get(test_user_id)
    assert tok is not None
    assert tok["scopes"] == "needs_reauth", (
        "AnthropicOAuthTokenRepository.mark_needs_reauth must set scopes='needs_reauth' "
        "on a refresh failure so the credential is never silently reused"
    )

    # No cross-provider fallthrough: the untouched OpenRouter env credential
    # resolves exactly as itself — never substituted with (or contaminated
    # by) anything from the failed Anthropic refresh.
    from app.services.llm_client import resolve_credential

    openrouter_cred = resolve_credential("openrouter")
    assert openrouter_cred is not None
    assert openrouter_cred.provider == "openrouter"
    assert openrouter_cred.secret == "or-fake-key-untouched-000"


# ===========================================================================
# 10. resolve_provider UNCHANGED — regression guard (pins current, already-
#     correct behaviour; must PASS both before and after the fix).
# ===========================================================================


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-3-5-sonnet-20241022", "anthropic"),
        ("claude-opus-4-1", "anthropic"),
        ("anthropic-internal-alias", "anthropic"),
        ("anthropic/claude-3.5-sonnet", "openrouter"),
        ("deepseek/deepseek-chat", "openrouter"),
        ("openai/gpt-4o", "openrouter"),
    ],
)
def test_resolve_provider_unchanged_regression_guard(model, expected):
    from app.services.llm_client import resolve_provider

    assert resolve_provider(model) == expected, model


# ===========================================================================
# 11. Auto-refresh hook: a near-expiry token triggers refresh before use; a
#     fresh token does not (no HTTP call).
# FAIL-BEFORE (WHY): ModuleNotFoundError (module absent).
# ===========================================================================


def test_refresh_if_needed_triggers_refresh_when_expiring_and_propagates_to_resolver(
    test_user_id, monkeypatch, _clean_anthropic_oauth_state, client, auth_headers
):
    # `client`/`auth_headers` are only requested to get a real, already-
    # migrated DB + a concrete user id via the shared fixture chain.
    from app.repositories.user_provider_credential import AnthropicOAuthTokenRepository
    from app.services import anthropic_oauth
    from app.services.llm_client import resolve_credential

    _seed_deployment_anthropic_credential(FAKE_ACCESS_1)
    AnthropicOAuthTokenRepository().upsert(
        test_user_id,
        access_ciphertext=vault.encrypt(FAKE_ACCESS_1),
        refresh_ciphertext=vault.encrypt(FAKE_REFRESH_1),
        secret_hint=vault.secret_hint(FAKE_ACCESS_1),
        # Well within any sane refresh-skew window (blueprint default 5 min).
        expires_at="2020-01-01T00:00:00Z",
        scopes="user:inference",
    )

    calls: list[dict] = []

    def _fake_post_token(body):
        calls.append(body)
        return _fake_token_response(FAKE_ACCESS_2, FAKE_REFRESH_2)

    monkeypatch.setattr(anthropic_oauth, "_post_token", _fake_post_token)

    result = anthropic_oauth.refresh_if_needed(test_user_id)
    assert len(calls) == 1, "an expiring-soon token must trigger exactly one refresh HTTP call"
    assert result == FAKE_ACCESS_2

    _clear_anthropic_env(monkeypatch)
    cred = resolve_credential("anthropic")
    assert cred is not None
    assert cred.secret == FAKE_ACCESS_2, (
        "the refreshed token must propagate to the SAME deployment-wide "
        "ProviderCredential row the live-call resolver reads (ADR-ML-2a "
        "DECISION-1) — otherwise a background/cron run with no user context "
        "would still see the stale token"
    )


def test_refresh_if_needed_does_not_refresh_a_fresh_token(
    test_user_id, monkeypatch, _clean_anthropic_oauth_state, client, auth_headers
):
    from app.repositories.provider_credential import ProviderCredentialRepository
    from app.repositories.user_provider_credential import AnthropicOAuthTokenRepository
    from app.services import anthropic_oauth

    _seed_deployment_anthropic_credential(FAKE_ACCESS_1)
    AnthropicOAuthTokenRepository().upsert(
        test_user_id,
        access_ciphertext=vault.encrypt(FAKE_ACCESS_1),
        refresh_ciphertext=vault.encrypt(FAKE_REFRESH_1),
        secret_hint=vault.secret_hint(FAKE_ACCESS_1),
        expires_at="2099-01-01T00:00:00Z",  # far in the future — not expiring
        scopes="user:inference",
    )

    def _must_not_be_called(body):
        pytest.fail("refresh_if_needed must NOT call the token endpoint for a fresh token")

    monkeypatch.setattr(anthropic_oauth, "_post_token", _must_not_be_called)

    result = anthropic_oauth.refresh_if_needed(test_user_id)
    assert result == FAKE_ACCESS_1

    pc = ProviderCredentialRepository().get_secret("anthropic")
    assert pc["secret"] == FAKE_ACCESS_1, "a fresh token must be left completely untouched"
