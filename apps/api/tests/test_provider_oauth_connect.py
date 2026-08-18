"""GAP-PROVIDER-OAUTH-1 — seamless, provider-agnostic, per-user OAuth connect
with an app-hosted callback (auto-return, zero-paste primary path; automatic
code_relay fallback for a provider/config that cannot accept our redirect).

TDD fail-before suite. Nothing under test exists in current code before this
slice: ``app.services.provider_oauth_registry`` and
``app.services.openrouter_oauth`` do not exist, and ``agents.py`` has no
``/agents/user/providers/{provider}/oauth/{start,callback,exchange}`` routes.
Every test below fails against the pre-slice tree — ``ModuleNotFoundError``/
``ImportError`` for the module-level tests, ``404 Not Found`` for the router
tests — and passes once the fixer's implementation lands.

**Critical invariant pinned repeatedly below** (per-route, not just once):
this whole family writes ONLY the caller's own ``UserProviderCredential``
row. The deployment-wide ``ProviderCredential`` store — the row the OLD,
admin-only ``/agents/providers/anthropic/oauth/*`` family and every bare
``claude-*``/cron run resolve through — must be completely untouched by
every route added here.

Run under this wave's isolated schema/lock (see the fixer's own instructions
for the exact provision/drop invocation):
    AETHER_TEST_SCHEMA=aether_test_provoauth \
      flock /tmp/aether-pytest-provoauth.lock python3 -m pytest \
      tests/test_provider_oauth_connect.py -q
"""
from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services import credential_vault as vault

# --------------------------------------------------------------------------- #
# Fixtures — mirrors test_ml_cred_002_anthropic_oauth.py's conventions.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    """Deterministic Fernet key so encrypt/decrypt agree within a test."""
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch, tmp_path):
    """A credential save must NEVER touch the real repo-root ``.env`` during
    tests — default the oauth_token sync target to a per-test tmp file."""
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(tmp_path / "default.env"))


@pytest.fixture(autouse=True)
def _clear_anthropic_app_callback_env(monkeypatch):
    """Every test starts from the honest default (no operator-registered
    app-callback client) unless it explicitly opts in — a leaked env value
    from another test/process must never silently flip the flow."""
    monkeypatch.delenv("ANTHROPIC_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("ANTHROPIC_OAUTH_REDIRECT_URI", raising=False)
    monkeypatch.delenv("OPENROUTER_OAUTH_REDIRECT_URI", raising=False)


@pytest.fixture()
def _clean_provider_oauth_state():
    """None of ProviderCredential / AnthropicOAuthState / UserProviderCredential
    carry an FK to ``User``, so conftest's per-test ``_truncate_tables`` never
    touches them (mirrors test_ml_cred_002_anthropic_oauth.py). Self-clean
    after each test so state tokens / stored credentials never leak forward."""
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


FAKE_OR_KEY = "sk-or-v1-FAKEtestOPENROUTERkey0000000000deadbeef"
FAKE_ANTHROPIC_ACCESS = "sk-ant-oat01-FAKEtestACCESSvalue0000000000deadbeef"
FAKE_ANTHROPIC_REFRESH = "sk-ant-ort01-FAKEtestREFRESHvalue0000000000deadbeef"


def _register_second_user(client) -> tuple[dict, str]:
    """Register + login a SECOND, independent user (distinct from the
    ``auth_headers``/``test_user_id`` fixture user) for cross-user checks."""
    email = f"provoauth-{uuid.uuid4().hex[:8]}@example.com"
    creds = {"email": email, "password": "Sup3rSecret"}
    reg = client.post("/auth/register", json=creds)
    assert reg.status_code in (201, 409), reg.text
    login = client.post("/auth/login", json=creds)
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _qs(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def _first(qs: dict[str, list[str]], key: str) -> str | None:
    values = qs.get(key)
    return values[0] if values else None


def _state_from_start(body: dict) -> str:
    """Recover the opaque state token from a ``/oauth/start`` response,
    regardless of whether it rides as a plain ``state`` query param
    (Anthropic) or embedded inside ``callback_url`` (OpenRouter — its
    redirect echoes back only ``code``, never ``state``; see
    ``openrouter_oauth.py``'s module docstring)."""
    qs = _qs(body["authorizeUrl"])
    state = _first(qs, "state")
    if state:
        return state
    callback_url = _first(qs, "callback_url")
    assert callback_url, f"no state and no callback_url in {body['authorizeUrl']}"
    inner_state = _first(_qs(callback_url), "state")
    assert inner_state, f"no state embedded in callback_url: {callback_url}"
    return inner_state


def _raw_state_row(state_token: str) -> dict | None:
    """Direct SQL peek at an ``AnthropicOAuthState`` row WITHOUT consuming it."""
    from app.db import get_connection, rows_to_dicts

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "stateToken", "userId", "codeVerifier", "provider", '
                '"redirectUri", "expiresAt" FROM "AnthropicOAuthState" '
                'WHERE "stateToken" = %s',
                (state_token,),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def _expire_state_row(state_token: str) -> None:
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "AnthropicOAuthState" SET "expiresAt" = now() - interval \'1 minute\' '
                'WHERE "stateToken" = %s',
                (state_token,),
            )
        conn.commit()


# ===========================================================================
# 1. Descriptor resolution — both Anthropic and OpenRouter resolve correctly.
# FAIL-BEFORE: app.services.provider_oauth_registry does not exist ->
# ModuleNotFoundError.
# ===========================================================================


def test_openrouter_descriptor_supports_oauth_app_callback_no_client_id_needed():
    from app.services import provider_oauth_registry as registry

    d = registry.get_oauth_descriptor("openrouter")
    assert d is not None
    assert d.supports_oauth is True
    assert d.flow == "app_callback"
    assert d.token_auth_mode == "api_key"
    redirect = d.redirect_uri()
    assert "/agents/user/providers/openrouter/oauth/callback" in redirect


def test_anthropic_descriptor_defaults_to_code_relay_public_client_cannot_register_callback():
    """The public Claude Code CLI client only accepts Anthropic-hosted /
    loopback redirects — so with no operator override, the honest flow is
    code_relay, never a false zero-paste claim."""
    from app.services import provider_oauth_registry as registry

    d = registry.get_oauth_descriptor("anthropic")
    assert d is not None
    assert d.supports_oauth is True
    assert d.flow == "code_relay"
    assert d.token_auth_mode == "oauth_token"
    from app.services import anthropic_oauth

    assert d.redirect_uri() == anthropic_oauth.REDIRECT_URI


def test_anthropic_descriptor_switches_to_app_callback_when_operator_registers_client(
    monkeypatch,
):
    monkeypatch.setenv("ANTHROPIC_OAUTH_CLIENT_ID", "operator-registered-client-id")
    monkeypatch.setenv(
        "ANTHROPIC_OAUTH_REDIRECT_URI", "https://example-app.test/api/agents/user/providers/anthropic/oauth/callback"
    )
    from app.services import provider_oauth_registry as registry

    d = registry.get_oauth_descriptor("anthropic")
    assert d.flow == "app_callback"
    assert d.redirect_uri() == (
        "https://example-app.test/api/agents/user/providers/anthropic/oauth/callback"
    )
    url = d.build_authorize_url("chal123", "state123", d.redirect_uri())
    qs = _qs(url)
    assert _first(qs, "client_id") == "operator-registered-client-id"
    assert _first(qs, "redirect_uri") == d.redirect_uri()


@pytest.mark.parametrize("provider", ["openai", "gemini", "bedrock", "groq", "abacus", "not-a-real-provider"])
def test_api_key_only_and_unknown_providers_have_no_oauth_descriptor(provider):
    from app.services import provider_oauth_registry as registry

    assert registry.get_oauth_descriptor(provider) is None


# ===========================================================================
# 2. POST /agents/user/providers/{provider}/oauth/start
# FAIL-BEFORE: route absent -> 404 (openrouter/anthropic module tests above
# already fail-before for the right reason via ModuleNotFoundError).
# ===========================================================================


def test_start_openrouter_returns_real_authorize_url_no_client_id_and_persists_state(
    client, auth_headers, test_user_id, _clean_provider_oauth_state,
):
    resp = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "openrouter"
    assert body["flow"] == "app_callback"
    authorize_url = body["authorizeUrl"]
    assert authorize_url.startswith("https://openrouter.ai/auth?"), authorize_url

    qs = _qs(authorize_url)
    assert _first(qs, "code_challenge"), authorize_url
    assert _first(qs, "code_challenge_method") == "S256", authorize_url
    # OpenRouter needs no client_id / app registration (verified live docs).
    assert "client_id" not in qs, authorize_url
    callback_url = _first(qs, "callback_url")
    assert callback_url and "/agents/user/providers/openrouter/oauth/callback" in callback_url

    state = _state_from_start(body)
    row = _raw_state_row(state)
    assert row is not None, "no state row was persisted for the returned state"
    assert row["userId"] == test_user_id
    assert row["provider"] == "openrouter"
    assert row["codeVerifier"]
    assert row["codeVerifier"] not in resp.text, "the PKCE verifier must never reach the client"


def test_start_anthropic_default_resolves_code_relay_flow(
    client, auth_headers, test_user_id, _clean_provider_oauth_state,
):
    from app.services import anthropic_oauth

    resp = client.post("/agents/user/providers/anthropic/oauth/start", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "anthropic"
    assert body["flow"] == "code_relay"

    qs = _qs(body["authorizeUrl"])
    assert _first(qs, "redirect_uri") == anthropic_oauth.REDIRECT_URI
    assert _first(qs, "client_id")
    assert _first(qs, "code_challenge")
    assert _first(qs, "code_challenge_method") == "S256"

    state = _state_from_start(body)
    row = _raw_state_row(state)
    assert row is not None
    assert row["provider"] == "anthropic"
    assert row["userId"] == test_user_id


def test_start_anthropic_app_callback_when_operator_configured_client(
    client, auth_headers, monkeypatch, _clean_provider_oauth_state,
):
    monkeypatch.setenv("ANTHROPIC_OAUTH_CLIENT_ID", "operator-registered-client-id")
    monkeypatch.setenv(
        "ANTHROPIC_OAUTH_REDIRECT_URI",
        "https://example-app.test/api/agents/user/providers/anthropic/oauth/callback",
    )
    resp = client.post("/agents/user/providers/anthropic/oauth/start", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["flow"] == "app_callback"
    qs = _qs(body["authorizeUrl"])
    assert _first(qs, "client_id") == "operator-registered-client-id"
    assert _first(qs, "redirect_uri") == (
        "https://example-app.test/api/agents/user/providers/anthropic/oauth/callback"
    )


def test_start_unknown_or_api_key_only_provider_404(client, auth_headers, _clean_provider_oauth_state):
    resp = client.post("/agents/user/providers/openai/oauth/start", headers=auth_headers)
    assert resp.status_code == 404, resp.text


def test_start_503_when_credential_key_absent(client, auth_headers, monkeypatch, _clean_provider_oauth_state):
    monkeypatch.delenv("AETHER_CREDENTIAL_KEY", raising=False)
    resp = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    assert resp.status_code == 503, resp.text


def test_start_called_twice_persists_two_distinct_states(client, auth_headers, _clean_provider_oauth_state):
    first = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    second = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    assert first.status_code == 200 and second.status_code == 200
    s1 = _state_from_start(first.json())
    s2 = _state_from_start(second.json())
    assert s1 != s2
    r1, r2 = _raw_state_row(s1), _raw_state_row(s2)
    assert r1 is not None and r2 is not None
    assert r1["codeVerifier"] != r2["codeVerifier"]


# ===========================================================================
# 3. GET /agents/user/providers/{provider}/oauth/callback — app_callback
#    happy path (OpenRouter). CRITICAL: only the per-user row is written.
# FAIL-BEFORE: route absent -> 404 (distinct from the 200-with-html this
# suite pins).
# ===========================================================================


def test_callback_openrouter_happy_path_persists_only_user_row_never_deployment_row(
    client, auth_headers, test_user_id, monkeypatch, _clean_provider_oauth_state,
):
    start = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    state = _state_from_start(start.json())

    from app.services import openrouter_oauth

    def _fake_post_exchange(body):
        assert body.get("code") == "FAKEOPENROUTERCODE", body
        assert body.get("code_verifier"), body
        return {"key": FAKE_OR_KEY}

    monkeypatch.setattr(openrouter_oauth, "_post_exchange", _fake_post_exchange)

    callback = client.get(
        "/agents/user/providers/openrouter/oauth/callback",
        params={"code": "FAKEOPENROUTERCODE", "state": state},
    )
    assert callback.status_code == 200, callback.text
    assert "text/html" in callback.headers.get("content-type", "")
    assert FAKE_OR_KEY not in callback.text, "the issued key must never reach the popup body"
    assert '"connected": true' in callback.text or '"connected":true' in callback.text

    from app.repositories.provider_credential import ProviderCredentialRepository
    from app.repositories.user_provider_credential import UserProviderCredentialRepository

    mine = UserProviderCredentialRepository().get_secret(test_user_id, "openrouter")
    assert mine is not None, "the callback must persist to THIS user's own UserProviderCredential row"
    assert mine["authMode"] == "api_key"
    assert mine["secret"] == FAKE_OR_KEY

    # CRITICAL: the deployment-wide row must remain completely untouched.
    assert ProviderCredentialRepository().get_secret("openrouter") is None, (
        "the app-hosted callback must NEVER write the deployment-wide "
        "ProviderCredential row — only the caller's own UserProviderCredential"
    )

    from app.repositories.user_provider_credential import AnthropicOAuthStateRepository

    assert AnthropicOAuthStateRepository().consume(state) is None, "state must be single-use"


def test_callback_unknown_state_is_honest_failure_nothing_stored(
    client, _clean_provider_oauth_state,
):
    resp = client.get(
        "/agents/user/providers/openrouter/oauth/callback",
        params={"code": "SOMECODE", "state": "totally-unknown-state-token"},
    )
    assert resp.status_code == 200, resp.text  # never strands the popup with a raw 4xx
    assert '"connected": false' in resp.text or '"connected":false' in resp.text

    from app.repositories.provider_credential import ProviderCredentialRepository

    assert ProviderCredentialRepository().get_secret("openrouter") is None


def test_callback_expired_state_is_honest_failure(
    client, auth_headers, monkeypatch, _clean_provider_oauth_state,
):
    start = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    state = _state_from_start(start.json())
    _expire_state_row(state)

    from app.services import openrouter_oauth

    monkeypatch.setattr(
        openrouter_oauth, "_post_exchange",
        lambda body: pytest.fail("token endpoint must never be called for an expired state"),
    )
    resp = client.get(
        "/agents/user/providers/openrouter/oauth/callback",
        params={"code": "SOMECODE", "state": state},
    )
    assert resp.status_code == 200, resp.text
    assert '"connected": false' in resp.text or '"connected":false' in resp.text


def test_callback_missing_code_or_state_is_honest_failure(client, _clean_provider_oauth_state):
    resp = client.get("/agents/user/providers/openrouter/oauth/callback", params={"state": "x"})
    assert resp.status_code == 200, resp.text
    assert '"connected": false' in resp.text or '"connected":false' in resp.text


def test_callback_provider_error_param_passthrough_is_honest_failure(
    client, auth_headers, _clean_provider_oauth_state,
):
    start = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    state = _state_from_start(start.json())
    resp = client.get(
        "/agents/user/providers/openrouter/oauth/callback",
        params={"state": state, "error": "access_denied"},
    )
    assert resp.status_code == 200, resp.text
    assert "access_denied" in resp.text
    assert '"connected": false' in resp.text or '"connected":false' in resp.text


def test_callback_unsupported_provider_is_honest_failure(client, _clean_provider_oauth_state):
    resp = client.get(
        "/agents/user/providers/openai/oauth/callback",
        params={"code": "x", "state": "y"},
    )
    assert resp.status_code == 200, resp.text
    assert '"connected": false' in resp.text or '"connected":false' in resp.text


def test_callback_provider_mismatch_is_honest_failure(
    client, auth_headers, _clean_provider_oauth_state,
):
    """A state minted for one provider must never complete another's exchange
    — hitting anthropic's callback with an openrouter-minted state is rejected."""
    start = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    state = _state_from_start(start.json())
    resp = client.get(
        "/agents/user/providers/anthropic/oauth/callback",
        params={"code": "x", "state": state},
    )
    assert resp.status_code == 200, resp.text
    assert '"connected": false' in resp.text or '"connected":false' in resp.text

    from app.repositories.provider_credential import ProviderCredentialRepository

    assert ProviderCredentialRepository().get_secret("anthropic") is None


def test_callback_provider_mismatch_leaves_state_intact_for_the_correct_provider(
    client, auth_headers, test_user_id, monkeypatch, _clean_provider_oauth_state,
):
    """P3-1 (RUN-20260818T0223Z): an unauthenticated cross-provider replay of
    a live ``state`` must NOT burn it — the state's own provider's callback
    must still be able to complete the connect afterward. Before the fix, the
    mismatched callback deleted the row unconditionally on first use, so this
    legitimate follow-up call would 200 with ``connected: false`` (state
    unknown/expired) instead of actually connecting."""
    start = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    state = _state_from_start(start.json())

    # An unauthenticated party who merely observed `state` replays it against
    # the WRONG provider's callback first.
    mismatch = client.get(
        "/agents/user/providers/anthropic/oauth/callback",
        params={"code": "x", "state": state},
    )
    assert mismatch.status_code == 200, mismatch.text
    assert '"connected": false' in mismatch.text or '"connected":false' in mismatch.text

    from app.services import openrouter_oauth

    monkeypatch.setattr(
        openrouter_oauth, "_post_exchange", lambda body: {"key": FAKE_OR_KEY}
    )

    # The legitimate owner's retry, against the CORRECT provider, must still
    # succeed — the mismatched attempt above must not have consumed the state.
    legit = client.get(
        "/agents/user/providers/openrouter/oauth/callback",
        params={"code": "FAKEOPENROUTERCODE", "state": state},
    )
    assert legit.status_code == 200, legit.text
    assert '"connected": true' in legit.text or '"connected":true' in legit.text, (
        "the cross-provider mismatch attempt burned the state — the "
        f"legitimate owner's retry could not complete: {legit.text}"
    )

    from app.repositories.user_provider_credential import UserProviderCredentialRepository

    mine = UserProviderCredentialRepository().get_secret(test_user_id, "openrouter")
    assert mine is not None and mine["secret"] == FAKE_OR_KEY

    # Still genuinely single-use: a second legitimate redeem must now fail.
    from app.repositories.user_provider_credential import AnthropicOAuthStateRepository

    assert AnthropicOAuthStateRepository().consume(state) is None, "state must be single-use"


# ===========================================================================
# 4. POST /agents/user/providers/{provider}/oauth/exchange — code_relay
#    fallback (Anthropic's default flow). CRITICAL: only the per-user row.
# FAIL-BEFORE: route absent -> 404.
# ===========================================================================


def test_exchange_code_relay_anthropic_happy_path_persists_only_user_row(
    client, auth_headers, test_user_id, monkeypatch, _clean_provider_oauth_state,
):
    start = client.post("/agents/user/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    assert start.json()["flow"] == "code_relay"
    state = _state_from_start(start.json())

    from app.services import anthropic_oauth

    def _fake_post_token(body):
        assert body.get("state") == state, body
        assert body.get("grant_type") == "authorization_code", body
        return {
            "access_token": FAKE_ANTHROPIC_ACCESS,
            "refresh_token": FAKE_ANTHROPIC_REFRESH,
            "expires_in": 31536000,
        }

    monkeypatch.setattr(anthropic_oauth, "_post_token", _fake_post_token)

    exchange = client.post(
        "/agents/user/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"FAKECODE#{state}"},
        headers=auth_headers,
    )
    assert exchange.status_code == 200, exchange.text
    assert FAKE_ANTHROPIC_ACCESS not in exchange.text
    assert FAKE_ANTHROPIC_REFRESH not in exchange.text

    from app.repositories.provider_credential import ProviderCredentialRepository
    from app.repositories.user_provider_credential import UserProviderCredentialRepository

    mine = UserProviderCredentialRepository().get_secret(test_user_id, "anthropic")
    assert mine is not None
    assert mine["authMode"] == "oauth_token"
    assert mine["secret"] == FAKE_ANTHROPIC_ACCESS

    # CRITICAL: never the deployment-wide row (that stays the admin-only
    # /agents/providers/anthropic/oauth/exchange route's job).
    assert ProviderCredentialRepository().get_secret("anthropic") is None

    from app.repositories.user_provider_credential import AnthropicOAuthStateRepository

    assert AnthropicOAuthStateRepository().consume(state) is None, "state must be single-use"


def test_exchange_malformed_pasted_code_422(client, auth_headers, _clean_provider_oauth_state):
    resp = client.post(
        "/agents/user/providers/anthropic/oauth/exchange",
        json={"pastedCode": "no-hash-separator"},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


def test_exchange_unknown_state_400(client, auth_headers, _clean_provider_oauth_state):
    resp = client.post(
        "/agents/user/providers/anthropic/oauth/exchange",
        json={"pastedCode": "SOMECODE#totally-unknown-state"},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text


def test_exchange_cross_user_state_rejected(
    client, auth_headers, _clean_provider_oauth_state,
):
    """User A starts the connect (mints a state bound to A); user B must
    never be able to complete A's exchange with it."""
    start = client.post("/agents/user/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    state = _state_from_start(start.json())

    other_headers, other_id = _register_second_user(client)
    resp = client.post(
        "/agents/user/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"SOMECODE#{state}"},
        headers=other_headers,
    )
    assert resp.status_code == 403, resp.text

    from app.repositories.user_provider_credential import UserProviderCredentialRepository

    assert UserProviderCredentialRepository().get_secret(other_id, "anthropic") is None


def test_exchange_cross_user_state_rejected_leaves_state_intact_for_the_owner(
    client, auth_headers, test_user_id, monkeypatch, _clean_provider_oauth_state,
):
    """P3-1 (RUN-20260818T0223Z): user B's rejected cross-user attempt must
    NOT burn user A's state — A's own subsequent, legitimate retry with the
    SAME state must still succeed. Before the fix, ``consume`` deleted the
    row unconditionally before the ownership check ran, so this genuine retry
    would 400 'unknown, expired, or already used' even though A never
    completed a real exchange."""
    start = client.post("/agents/user/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    state = _state_from_start(start.json())

    other_headers, other_id = _register_second_user(client)
    attack = client.post(
        "/agents/user/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"SOMECODE#{state}"},
        headers=other_headers,
    )
    assert attack.status_code == 403, attack.text

    from app.services import anthropic_oauth

    monkeypatch.setattr(
        anthropic_oauth,
        "_post_token",
        lambda body: {
            "access_token": FAKE_ANTHROPIC_ACCESS,
            "refresh_token": FAKE_ANTHROPIC_REFRESH,
            "expires_in": 31536000,
        },
    )

    retry = client.post(
        "/agents/user/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"REALCODE#{state}"},
        headers=auth_headers,
    )
    assert retry.status_code == 200, (
        "user B's rejected cross-user attempt burned user A's still-pending "
        f"state — A's own legitimate retry failed: {retry.text}"
    )

    from app.repositories.user_provider_credential import UserProviderCredentialRepository

    mine = UserProviderCredentialRepository().get_secret(test_user_id, "anthropic")
    assert mine is not None and mine["secret"] == FAKE_ANTHROPIC_ACCESS
    assert UserProviderCredentialRepository().get_secret(other_id, "anthropic") is None

    # Still genuinely single-use: a second legitimate redeem must now fail.
    replay = client.post(
        "/agents/user/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"REALCODE#{state}"},
        headers=auth_headers,
    )
    assert replay.status_code == 400, replay.text


def test_exchange_provider_mismatch_400(client, auth_headers, _clean_provider_oauth_state):
    """A state minted for openrouter must not complete anthropic's exchange."""
    start = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    state = _state_from_start(start.json())
    resp = client.post(
        "/agents/user/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"SOMECODE#{state}"},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text


def test_exchange_upstream_rejection_is_honest_4xx_nothing_stored(
    client, auth_headers, test_user_id, monkeypatch, _clean_provider_oauth_state,
):
    start = client.post("/agents/user/providers/anthropic/oauth/start", headers=auth_headers)
    state = _state_from_start(start.json())

    from app.services import anthropic_oauth

    def _reject(body):
        raise anthropic_oauth.OAuthExchangeError("invalid_grant", upstream_status=400)

    monkeypatch.setattr(anthropic_oauth, "_post_token", _reject)

    resp = client.post(
        "/agents/user/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"BADCODE#{state}"},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text

    from app.repositories.user_provider_credential import UserProviderCredentialRepository

    assert UserProviderCredentialRepository().get_secret(test_user_id, "anthropic") is None


def test_exchange_unknown_or_api_key_only_provider_404(client, auth_headers, _clean_provider_oauth_state):
    resp = client.post(
        "/agents/user/providers/openai/oauth/exchange",
        json={"pastedCode": "x#y"},
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text


# ===========================================================================
# 5. Regression guard — neither per-user route may sync
#    CLAUDE_CODE_OAUTH_TOKEN into the operator-facing repo-root .env
#    (RUN-20260818T0223Z deploy-merge resolution, P1 fix — see
#    docs/delivery/evidence/RUN-20260818T0223Z/FEAT-PROVIDER/
#    09-deploy-merge-resolution.md §2.4 and the follow-up adversarial review
#    at 10-resolution-security-review.md §1c, which proved by mutation that
#    NOTHING in the mandated + recommended battery (128 tests) caught this
#    call being reintroduced into user_provider_oauth_callback/_exchange).
#
#    Mirrors test_user_anthropic_oauth_mint.py::test_user_save_does_not_
#    sync_oauth_token_into_deployment_env's byte-identical-after pattern:
#    pre-write the isolated env file with a fake OPERATOR token line
#    (overriding the autouse _isolate_env_file fixture's own tmp_path target
#    for this one test), run the route, assert the file is untouched
#    byte-for-byte afterwards — not merely "does not exist", so a bug that
#    APPENDS or rewrites the line (rather than creating a fresh file) is
#    caught too. Every test below also asserts the credential really did
#    land as `authMode == "oauth_token"` in UserProviderCredential, so a
#    vacuous pass (the sync-guarded branch never actually being reached) is
#    ruled out.
# ===========================================================================


def test_callback_anthropic_app_callback_oauth_token_never_syncs_operator_env(
    client, auth_headers, test_user_id, monkeypatch, tmp_path, _clean_provider_oauth_state,
):
    """The app-hosted callback is reachable for Anthropic once an operator
    registers a client (see test_start_anthropic_app_callback_when_operator_
    configured_client) — and Anthropic's descriptor is `token_auth_mode ==
    "oauth_token"` regardless of flow, which is the exact condition the
    removed sync call was guarded on. Must still never touch the operator's
    restart-survival CLAUDE_CODE_OAUTH_TOKEN line."""
    env_file = tmp_path / "operator.env"
    original = "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-OPERATORkeepme\n"
    env_file.write_text(original)
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(env_file))

    monkeypatch.setenv("ANTHROPIC_OAUTH_CLIENT_ID", "operator-registered-client-id")
    monkeypatch.setenv(
        "ANTHROPIC_OAUTH_REDIRECT_URI",
        "https://example-app.test/api/agents/user/providers/anthropic/oauth/callback",
    )
    start = client.post("/agents/user/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    assert start.json()["flow"] == "app_callback"
    state = _state_from_start(start.json())

    from app.services import anthropic_oauth

    def _fake_post_token(body):
        return {
            "access_token": FAKE_ANTHROPIC_ACCESS,
            "refresh_token": FAKE_ANTHROPIC_REFRESH,
            "expires_in": 31536000,
        }

    monkeypatch.setattr(anthropic_oauth, "_post_token", _fake_post_token)

    callback = client.get(
        "/agents/user/providers/anthropic/oauth/callback",
        params={"code": "FAKECODE", "state": state},
    )
    assert callback.status_code == 200, callback.text
    assert '"connected": true' in callback.text or '"connected":true' in callback.text

    from app.repositories.user_provider_credential import UserProviderCredentialRepository

    mine = UserProviderCredentialRepository().get_secret(test_user_id, "anthropic")
    assert mine is not None, "precondition: the credential must actually have been stored"
    assert mine["authMode"] == "oauth_token", (
        "precondition: this must be the exact oauth_token branch the removed "
        "sync call was guarded on — otherwise this test would pass vacuously"
    )

    assert env_file.read_text() == original, (
        "the app-hosted callback must NEVER touch the operator's "
        "CLAUDE_CODE_OAUTH_TOKEN .env line, even for an oauth_token credential"
    )
    assert FAKE_ANTHROPIC_ACCESS not in env_file.read_text()


def test_exchange_anthropic_code_relay_oauth_token_never_syncs_operator_env(
    client, auth_headers, test_user_id, monkeypatch, tmp_path, _clean_provider_oauth_state,
):
    """The code_relay exchange (Anthropic's default flow, no operator
    override needed) must never touch the operator's restart-survival
    CLAUDE_CODE_OAUTH_TOKEN line either."""
    env_file = tmp_path / "operator.env"
    original = "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-OPERATORkeepme\n"
    env_file.write_text(original)
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(env_file))

    start = client.post("/agents/user/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    assert start.json()["flow"] == "code_relay"
    state = _state_from_start(start.json())

    from app.services import anthropic_oauth

    def _fake_post_token(body):
        return {
            "access_token": FAKE_ANTHROPIC_ACCESS,
            "refresh_token": FAKE_ANTHROPIC_REFRESH,
            "expires_in": 31536000,
        }

    monkeypatch.setattr(anthropic_oauth, "_post_token", _fake_post_token)

    exchange = client.post(
        "/agents/user/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"FAKECODE#{state}"},
        headers=auth_headers,
    )
    assert exchange.status_code == 200, exchange.text

    from app.repositories.user_provider_credential import UserProviderCredentialRepository

    mine = UserProviderCredentialRepository().get_secret(test_user_id, "anthropic")
    assert mine is not None, "precondition: the credential must actually have been stored"
    assert mine["authMode"] == "oauth_token", (
        "precondition: this must be the exact oauth_token branch the removed "
        "sync call was guarded on — otherwise this test would pass vacuously"
    )

    assert env_file.read_text() == original, (
        "the code_relay exchange must NEVER touch the operator's "
        "CLAUDE_CODE_OAUTH_TOKEN .env line, even for an oauth_token credential"
    )
    assert FAKE_ANTHROPIC_ACCESS not in env_file.read_text()


def test_callback_openrouter_api_key_never_syncs_operator_env(
    client, auth_headers, test_user_id, monkeypatch, tmp_path, _clean_provider_oauth_state,
):
    """OpenRouter's descriptor is `token_auth_mode == "api_key"`, so the
    removed sync call's guard (`token_auth_mode == "oauth_token"`) never
    fires for it either way — recorded here as a "where applicable" companion
    to the two Anthropic tests above, not a mutation-killer for this specific
    defect (openrouter is never oauth_token mode), so a future change that
    widens the guard's condition still has a regression test watching it."""
    env_file = tmp_path / "operator.env"
    original = "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-OPERATORkeepme\n"
    env_file.write_text(original)
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(env_file))

    start = client.post("/agents/user/providers/openrouter/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    state = _state_from_start(start.json())

    from app.services import openrouter_oauth

    monkeypatch.setattr(openrouter_oauth, "_post_exchange", lambda body: {"key": FAKE_OR_KEY})

    callback = client.get(
        "/agents/user/providers/openrouter/oauth/callback",
        params={"code": "FAKEOPENROUTERCODE", "state": state},
    )
    assert callback.status_code == 200, callback.text
    assert '"connected": true' in callback.text or '"connected":true' in callback.text

    from app.repositories.user_provider_credential import UserProviderCredentialRepository

    mine = UserProviderCredentialRepository().get_secret(test_user_id, "openrouter")
    assert mine is not None, "precondition: the credential must actually have been stored"
    assert mine["authMode"] == "api_key"

    assert env_file.read_text() == original, (
        "an openrouter connect must never touch the operator's "
        "CLAUDE_CODE_OAUTH_TOKEN .env line"
    )
    assert FAKE_OR_KEY not in env_file.read_text()


# ===========================================================================
# 6. Informational finding (RUN-20260818T0223Z third-party adversarial
#    review) — defense-in-depth: `provider` must never be able to break out
#    of the <script> block `_oauth_popup_html` embeds it in, independent of
#    whatever the routing layer currently allows through `{provider}`.
# ===========================================================================


def test_oauth_popup_html_escapes_script_breakout_in_provider_json_literal():
    """A direct unit-level call (bypassing routing entirely, per the
    finding's own note that routing currently blocks every path that could
    deliver a literal '/' into `provider`) — this is the seam that keeps the
    escaping a property of the function, not an accident of routing."""
    import json
    import re

    from app.routers.agents import _oauth_popup_html

    hostile_provider = "anthropic</script><script>alert(document.domain)</script>"
    html_doc = _oauth_popup_html(provider=hostile_provider, connected=True)

    match = re.search(r"var payload = (\{.*\});", html_doc)
    assert match, html_doc
    payload_literal = match.group(1)

    # The attacker's own `</script>`/`<script>` sequences must never survive
    # into the JSON literal verbatim — that is exactly what would let a
    # browser's HTML parser terminate the real <script> block early and
    # execute the attacker's injected markup as a sibling <script> tag.
    assert "</script" not in payload_literal.lower()
    assert "<script" not in payload_literal.lower()

    # Defense-in-depth, not data corruption: a real browser's JS engine
    # evaluates the unicode escape identically to a literal '<', so the
    # provider value still round-trips losslessly once unescaped the same way.
    parsed = json.loads(payload_literal.replace("\\u003c", "<"))
    assert parsed == {
        "source": "aether-oauth",
        "provider": hostile_provider,
        "connected": True,
    }


def test_oauth_popup_html_ordinary_provider_unaffected():
    """Regression guard: escaping must not change behaviour for the normal
    case (no '<' in the provider id)."""
    from app.routers.agents import _oauth_popup_html

    html_doc = _oauth_popup_html(provider="openrouter", connected=True)
    assert '"provider": "openrouter"' in html_doc or '"provider":"openrouter"' in html_doc
    assert "\\u003c" not in html_doc
