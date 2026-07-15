"""GAP-D1 / GAP-E5 / GAP-NEW-001 — per-user credentials, dual-auth Anthropic
(API key vs subscription OAuth), PKCE flow, per-user resolution precedence,
no cross-provider billing, and subscription quota exhaustion.

Outbound HTTP (the Anthropic token exchange and the live Messages call) is
mocked — these tests never touch the network. DB-backed tests use the shared
``client`` / ``auth_headers`` / ``test_user_id`` fixtures.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.repositories.user_provider_credential import (
    AgentQuotaBlockRepository,
    AnthropicOAuthStateRepository,
    UserProviderCredentialRepository,
)
from app.services import anthropic_oauth
from app.services import credential_vault as vault
from app.services.llm_client import (
    LLMClient,
    QuotaExhaustedError,
    anthropic_auth_headers,
    resolve_user_credential,
    user_credential_context,
)


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    """A deterministic Fernet key for the whole test (encrypt+decrypt agree)."""
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


# ---------------------------------------------------------------------------
# 1. Anthropic dual-auth headers (pure — the billing-separation contract)
# ---------------------------------------------------------------------------


def test_subscription_header_uses_bearer_not_x_api_key():
    h = anthropic_auth_headers("subscription_oauth", "sk-ant-oat-token")
    assert h["Authorization"] == "Bearer sk-ant-oat-token"
    assert h["anthropic-beta"] == "oauth-2025-04-20"
    assert "x-api-key" not in h


def test_api_key_header_uses_x_api_key_not_bearer():
    h = anthropic_auth_headers("api_key", "sk-ant-api-key")
    assert h["x-api-key"] == "sk-ant-api-key"
    assert "Authorization" not in h
    assert "anthropic-beta" not in h


# ---------------------------------------------------------------------------
# 2. PKCE + signed state (pure)
# ---------------------------------------------------------------------------


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = anthropic_oauth.generate_pkce()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert challenge == expected
    assert 43 <= len(verifier) <= 128


def test_state_sign_and_verify_roundtrip():
    token = anthropic_oauth.sign_state("user-123")
    assert anthropic_oauth.verify_state(token) == "user-123"


def test_verify_state_rejects_tampered_token():
    import jwt

    with pytest.raises(jwt.PyJWTError):
        anthropic_oauth.verify_state("not-a-jwt")


# ---------------------------------------------------------------------------
# 3. Per-user credential storage (encrypted, masked)
# ---------------------------------------------------------------------------


def test_upsert_user_credential_api_key_and_subscription(
    client, auth_headers, test_user_id
):
    repo = UserProviderCredentialRepository()
    row = repo.upsert(
        test_user_id, "anthropic", auth_mode="api_key",
        secret="sk-ant-api-secret1234",
    )
    assert row["authMode"] == "api_key"
    assert row["secretHint"].endswith("1234")
    assert "secret1234" not in str(row)  # ciphertext/hint only, never plaintext
    assert repo.get_secret(test_user_id, "anthropic")["secret"] == "sk-ant-api-secret1234"

    # Rotating to a subscription token replaces authMode + secret in place.
    row2 = repo.upsert(
        test_user_id, "anthropic", auth_mode="subscription_oauth",
        secret="sk-ant-oat-token9999",
    )
    assert row2["authMode"] == "subscription_oauth"
    got = repo.get_secret(test_user_id, "anthropic")
    assert got["authMode"] == "subscription_oauth"
    assert got["secret"] == "sk-ant-oat-token9999"


# ---------------------------------------------------------------------------
# 4. OAuth state — create, single-use consume, expiry
# ---------------------------------------------------------------------------


def test_oauth_state_create_and_single_use_consume(client, auth_headers, test_user_id):
    import uuid

    token = f"state-{uuid.uuid4().hex}"
    repo = AnthropicOAuthStateRepository()
    repo.create(token, test_user_id, "verifier-xyz")
    row = repo.consume(token)
    assert row is not None
    assert row["userId"] == test_user_id and row["codeVerifier"] == "verifier-xyz"
    # A state token can never be replayed.
    assert repo.consume(token) is None


def test_oauth_state_expired_is_not_consumable(client, auth_headers, test_user_id):
    import uuid

    from app.db import get_connection

    token = f"state-old-{uuid.uuid4().hex}"
    repo = AnthropicOAuthStateRepository()
    repo.create(token, test_user_id, "verifier-old")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "AnthropicOAuthState" SET "expiresAt" = now() - interval \'1 minute\' '
                'WHERE "stateToken" = %s',
                (token,),
            )
        conn.commit()
    assert repo.consume(token) is None


# ---------------------------------------------------------------------------
# 5. resolve_user_credential precedence + no cross-provider (GAP-E5)
# ---------------------------------------------------------------------------


def test_resolve_prefers_user_credential_then_agent_ref(
    client, auth_headers, test_user_id
):
    repo = UserProviderCredentialRepository()
    cred = repo.upsert(
        test_user_id, "anthropic", auth_mode="api_key",
        secret="sk-ant-api-USERKEY01",
    )
    # (2) no agent key -> the user's own provider credential.
    res = resolve_user_credential("anthropic", test_user_id)
    assert res is not None
    assert res.source == "user_credential"
    assert res.secret == "sk-ant-api-USERKEY01"

    # (1) an AgentConfig.credentialRef pin wins for that agent.
    r = client.put(
        "/agents/config/resumeTailoring",
        json={"credentialRef": cred["id"]}, headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    res2 = resolve_user_credential("anthropic", test_user_id, "resumeTailoring")
    assert res2 is not None and res2.source == "user_credential_ref"


def test_resolve_falls_back_to_env_when_no_user_credential(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setattr(
        "app.repositories.provider_credential.ProviderCredentialRepository.get_secret",
        lambda self, provider: None,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-envkey")
    res = resolve_user_credential("openrouter", test_user_id)
    assert res is not None
    assert res.source == "environment" and res.secret == "sk-or-envkey"


def test_no_cross_provider_billing_for_user(
    client, auth_headers, test_user_id, monkeypatch
):
    # The user has ONLY an Anthropic credential; an OpenRouter model must NEVER
    # be served with it — resolution returns None instead of rerouting.
    monkeypatch.setattr(
        "app.repositories.provider_credential.ProviderCredentialRepository.get_secret",
        lambda self, provider: None,
    )
    for var in (
        "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "AETHER_LLM_API_KEY",
        "AETHER_LLM_BASE_URL", "ABACUS_API_KEY", "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    UserProviderCredentialRepository().upsert(
        test_user_id, "anthropic", auth_mode="api_key", secret="sk-ant-api-only",
    )
    assert resolve_user_credential("openrouter", test_user_id) is None


# ---------------------------------------------------------------------------
# 6. Anthropic OAuth endpoints (start / callback) — token exchange mocked
# ---------------------------------------------------------------------------


def test_oauth_start_501_when_not_configured(client, auth_headers, monkeypatch):
    monkeypatch.delenv("AETHER_ANTHROPIC_OAUTH_CLIENT_ID", raising=False)
    r = client.get("/agents/auth/anthropic/start", headers=auth_headers)
    assert r.status_code == 501
    assert r.json()["detail"]["error"] == "not_configured"


def test_oauth_start_returns_authorize_url(client, auth_headers, monkeypatch):
    monkeypatch.setenv("AETHER_ANTHROPIC_OAUTH_CLIENT_ID", "test-client-id")
    r = client.get("/agents/auth/anthropic/start", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authorizeUrl"].startswith("https://claude.ai/oauth/authorize")
    assert "code_challenge=" in body["authorizeUrl"]
    assert "code_challenge_method=S256" in body["authorizeUrl"]
    assert "state=" in body["authorizeUrl"]


def test_oauth_callback_exchanges_stores_and_masks(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_ANTHROPIC_OAUTH_CLIENT_ID", "test-client-id")
    start = client.get("/agents/auth/anthropic/start", headers=auth_headers).json()
    state = start["state"]

    monkeypatch.setattr(
        anthropic_oauth, "_post_token",
        lambda data, timeout=15.0: {
            "access_token": "sk-ant-oat-SECRET7777",
            "refresh_token": "sk-ant-ort-REFRESH",
            "expires_in": 3600,
            "scope": "user:inference",
        },
    )
    r = client.get(
        "/agents/auth/anthropic/callback",
        params={"code": "auth-code-xyz", "state": state}, headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authMode"] == "subscription_oauth"
    assert body["hint"].endswith("7777")
    # The token itself is NEVER returned to the client.
    assert "SECRET7777" not in str(body)

    # It is now the user's resolvable subscription credential.
    res = resolve_user_credential("anthropic", test_user_id)
    assert res is not None and res.auth_mode == "subscription_oauth"


def test_oauth_callback_rejects_bad_state(client, auth_headers, monkeypatch):
    monkeypatch.setenv("AETHER_ANTHROPIC_OAUTH_CLIENT_ID", "test-client-id")
    r = client.get(
        "/agents/auth/anthropic/callback",
        params={"code": "c", "state": "forged-state"}, headers=auth_headers,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 7. Subscription quota exhaustion (429) — no silent reroute
# ---------------------------------------------------------------------------


def test_active_quota_block_prevents_live_call(client, auth_headers, test_user_id):
    AgentQuotaBlockRepository().set_block(
        test_user_id, "anthropic",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        reason="subscription_quota_exceeded",
    )
    llm = LLMClient(mode="live")
    with user_credential_context(test_user_id, "resumeTailoring"):
        with pytest.raises(QuotaExhaustedError):
            llm._call_live("sys", "user", model="claude-haiku-4-5", temperature=0.0)


def test_anthropic_429_records_quota_block(
    client, auth_headers, test_user_id, monkeypatch
):
    import httpx

    UserProviderCredentialRepository().upsert(
        test_user_id, "anthropic", auth_mode="subscription_oauth",
        secret="sk-ant-oat-sub12345",
    )

    class _FakeResp:
        status_code = 429
        text = '{"type":"error","error":{"type":"rate_limit_error","message":"quota"}}'

        def json(self):  # pragma: no cover - not reached on 429 path
            return {}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp())
    llm = LLMClient(mode="live")
    with user_credential_context(test_user_id, None):
        with pytest.raises(QuotaExhaustedError):
            llm._call_live("s", "u", model="claude-haiku-4-5", temperature=0.0)
    assert (
        AgentQuotaBlockRepository().get_active(test_user_id, "anthropic") is not None
    )
