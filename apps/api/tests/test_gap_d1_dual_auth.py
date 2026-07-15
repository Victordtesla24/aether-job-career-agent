"""GAP-D1 / GAP-E5 / GAP-NEW-001 — per-user encrypted credentials, native
Anthropic API-key auth, per-user resolution precedence, and no cross-provider
billing.

Consumer Anthropic subscription OAuth was REMOVED for compliance
(GAP-AUTH-001) — its endpoint/header/quota-recording tests moved out and the
compliance contract now lives in ``test_gap_p5_auth_compliance.py``. The
retained (but unused) ``AnthropicOAuthState`` table is still exercised here to
prove the additive, backward-compatible schema keeps working.

Outbound HTTP (the live Messages call) is mocked — these tests never touch the
network. DB-backed tests use the shared ``client`` / ``auth_headers`` /
``test_user_id`` fixtures.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.repositories.user_provider_credential import (
    AgentQuotaBlockRepository,
    AnthropicOAuthStateRepository,
    UserProviderCredentialRepository,
)
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


def test_subscription_oauth_header_is_rejected():
    # Subscription OAuth transport was removed (GAP-AUTH-001): the only
    # supported Anthropic auth is x-api-key, so any other mode is a hard error.
    with pytest.raises(RuntimeError):
        anthropic_auth_headers("subscription_oauth", "sk-ant-oat-token")


def test_api_key_header_uses_x_api_key_not_bearer():
    h = anthropic_auth_headers("api_key", "sk-ant-api-key")
    assert h["x-api-key"] == "sk-ant-api-key"
    assert "Authorization" not in h
    assert "anthropic-beta" not in h


# ---------------------------------------------------------------------------
# 3. Per-user credential storage (encrypted, masked)
# ---------------------------------------------------------------------------


def test_upsert_user_credential_api_key_encrypts_and_masks(
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


def test_repo_retains_legacy_subscription_oauth_check(
    client, auth_headers, test_user_id
):
    # GAP-AUTH-001: the write-path (router) rejects new subscription_oauth creds
    # and resolution never uses them, but the storage CHECK is deliberately left
    # relaxed (additive, backward-compatible) so a PRE-EXISTING legacy row still
    # loads without a constraint error. This locks that retention in.
    repo = UserProviderCredentialRepository()
    row = repo.upsert(
        test_user_id, "anthropic", auth_mode="subscription_oauth",
        secret="sk-ant-oat-token9999",
    )
    assert row["authMode"] == "subscription_oauth"
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
# 6. Quota cooldown — a pre-existing block still short-circuits a live call
#    honestly (backward-compat; new blocks are no longer recorded now that
#    consumer subscription billing is removed — GAP-AUTH-001).
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
