"""GAP-AUTH-001 / ADR-P7-01 — the in-app Anthropic OAuth *authorize* flow stays removed.

The consumer Claude Free/Pro/Max in-app OAuth *authorize* flow
(``claude.ai/oauth/authorize``, the ``subscription_oauth`` label) is NON-COMPLIANT
in a third-party product and remains removed — that is the retained ADR-P7-01
NON-goal. These tests lock in that removal:

- the subscription OAuth start/callback endpoints no longer exist;
- the credential write-path rejects the ``subscription_oauth`` label / a legacy
  non-oat01 ``sk-ant-oat`` secret for Anthropic (deployment-wide, per-user, and
  per-agent config);
- the header builder rejects the ``subscription_oauth`` label transport;
- a pre-existing ``subscription_oauth`` credential is never used for a live call
  (honest fall-through, never a faked success).

NOTE (GAP-P7-DEF-A / ADR-P7-01): a *user-pasted* ``claude setup-token`` output
(``sk-ant-oat01-…``, authMode ``oauth_token``) is a DISTINCT, now-SUPPORTED
mechanism — accepted by the write-path and transported via
``Authorization: Bearer`` + ``anthropic-beta: oauth-2025-04-20``. Its contract is
covered in ``test_gap_p7_def_a_dual_mode.py``; the assertions here concern only
the still-removed in-app ``subscription_oauth`` flow.

Outbound HTTP is never touched — the resolution/header assertions are pure and
the endpoint assertions only exercise routing.
"""
from __future__ import annotations

import pytest

from app.repositories.user_provider_credential import UserProviderCredentialRepository
from app.services import credential_vault as vault
from app.services.llm_client import (
    anthropic_auth_headers,
    resolve_user_credential,
)


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    """Deterministic Fernet key so encrypt/decrypt agree within a test."""
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


# ---------------------------------------------------------------------------
# 1. The subscription OAuth endpoints are gone (removed -> 404, disabled -> 410).
# ---------------------------------------------------------------------------


def test_anthropic_oauth_start_endpoint_removed(client, auth_headers):
    r = client.get("/agents/auth/anthropic/start", headers=auth_headers)
    assert r.status_code in (404, 410), r.text


def test_anthropic_oauth_callback_endpoint_removed(client, auth_headers):
    r = client.get(
        "/agents/auth/anthropic/callback",
        params={"code": "x", "state": "y"},
        headers=auth_headers,
    )
    assert r.status_code in (404, 410), r.text


# ---------------------------------------------------------------------------
# 2. The write-path rejects subscription_oauth for Anthropic.
# ---------------------------------------------------------------------------


def test_put_deployment_credential_rejects_subscription_oauth(
    client, auth_headers, monkeypatch
):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
    r = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "subscription_oauth", "secret": "sk-ant-oat-abcd1234"},
        headers=auth_headers,
    )
    assert r.status_code in (400, 422), r.text


def test_put_user_credential_rejects_subscription_oauth(
    client, auth_headers, monkeypatch
):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
    r = client.put(
        "/agents/user/providers/anthropic/credential",
        json={"authMode": "subscription_oauth", "secret": "sk-ant-oat-abcd1234"},
        headers=auth_headers,
    )
    assert r.status_code in (400, 422), r.text


def test_agent_config_rejects_subscription_oauth_authmode(client, auth_headers):
    r = client.put(
        "/agents/config/resumeTailoring",
        json={"authMode": "subscription_oauth"},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 3. Native Anthropic auth is x-api-key ONLY.
# ---------------------------------------------------------------------------


def test_anthropic_headers_use_x_api_key_only():
    h = anthropic_auth_headers("api_key", "sk-ant-api-KEY1234")
    assert h["x-api-key"] == "sk-ant-api-KEY1234"
    assert h["anthropic-version"] == "2023-06-01"
    # The subscription OAuth transport must be gone entirely.
    assert "Authorization" not in h
    assert "anthropic-beta" not in h


def test_anthropic_headers_reject_subscription_oauth():
    with pytest.raises(RuntimeError):
        anthropic_auth_headers("subscription_oauth", "sk-ant-oat-token")


# ---------------------------------------------------------------------------
# 4. A pre-existing subscription_oauth credential is never used for a live call.
# ---------------------------------------------------------------------------


def test_preexisting_subscription_oauth_credential_not_resolved(
    client, auth_headers, test_user_id, monkeypatch
):
    # Simulate a legacy row written before the feature was removed: the repo
    # layer + retained CHECK still permit the value, but resolution must skip it.
    UserProviderCredentialRepository().upsert(
        test_user_id,
        "anthropic",
        auth_mode="subscription_oauth",
        secret="sk-ant-oat-LEGACY9999",
    )
    # No deployment-wide row and no env key to fall back to.
    monkeypatch.setattr(
        "app.repositories.provider_credential.ProviderCredentialRepository.get_secret",
        lambda self, provider: None,
    )
    for var in ("ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL"):
        monkeypatch.delenv(var, raising=False)

    res = resolve_user_credential("anthropic", test_user_id)
    # The legacy subscription token must NEVER be handed to the live path.
    assert res is None or (
        res.auth_mode == "api_key" and not res.secret.startswith("sk-ant-oat")
    )
