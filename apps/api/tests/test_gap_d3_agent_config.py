"""GAP-D3 — full per-agent config persistence (temperature, thinkingEffort,
provider, authMode, credentialRef), GET config endpoints (previously 405),
billing audit provenance, and the subscription quota 429 contract.

DB-backed; uses the shared ``client`` / ``auth_headers`` / ``test_user_id``
fixtures. No live LLM call is made — the LLM-backed agents are driven through
``_record_run`` with a stub callable so the audit/quota logic is exercised
deterministically.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.repositories.user_provider_credential import (
    AgentQuotaBlockRepository,
    UserProviderCredentialRepository,
)
from app.routers.agents import AGENT_CATALOG, _record_run
from app.services import credential_vault as vault


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


def _tailor_stub():
    return {"resume_id": "r1", "changes": [], "rejected": []}


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------


def test_put_config_persists_temperature_and_thinking(client, auth_headers):
    r = client.put(
        "/agents/config/resumeTailoring",
        json={"temperature": 0.9, "thinkingEffort": "high"}, headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["temperature"] == 0.9 and body["thinkingEffort"] == "high"

    g = client.get("/agents/config/resumeTailoring", headers=auth_headers)
    assert g.status_code == 200
    got = g.json()
    assert got["temperature"] == 0.9 and got["thinkingEffort"] == "high"


def test_partial_update_merges_over_existing(client, auth_headers):
    client.put(
        "/agents/config/coverLetter",
        json={"temperature": 0.3, "model": "claude-sonnet-5"}, headers=auth_headers,
    )
    client.put(
        "/agents/config/coverLetter",
        json={"thinkingEffort": "low"}, headers=auth_headers,
    )
    got = client.get("/agents/config/coverLetter", headers=auth_headers).json()
    assert got["temperature"] == 0.3
    assert got["model"] == "claude-sonnet-5"
    assert got["thinkingEffort"] == "low"


def test_invalid_agent_key_is_404(client, auth_headers):
    assert client.put(
        "/agents/config/nope", json={"temperature": 0.5}, headers=auth_headers
    ).status_code == 404
    assert client.get("/agents/config/nope", headers=auth_headers).status_code == 404


def test_temperature_out_of_range_is_422(client, auth_headers):
    assert client.put(
        "/agents/config/coverLetter", json={"temperature": 2.5}, headers=auth_headers
    ).status_code == 422
    assert client.put(
        "/agents/config/coverLetter", json={"temperature": -0.1}, headers=auth_headers
    ).status_code == 422


def test_invalid_thinking_effort_is_422(client, auth_headers):
    assert client.put(
        "/agents/config/coverLetter",
        json={"thinkingEffort": "extreme"}, headers=auth_headers,
    ).status_code == 422


def test_get_config_list_covers_all_agents(client, auth_headers):
    lst = client.get("/agents/config", headers=auth_headers).json()
    assert len(lst) == len(AGENT_CATALOG)
    assert {c["key"] for c in lst} == {a["key"] for a in AGENT_CATALOG}


def test_all_agent_keys_accepted(client, auth_headers):
    assert len(AGENT_CATALOG) >= 22
    for entry in AGENT_CATALOG:
        r = client.put(
            f"/agents/config/{entry['key']}",
            json={"temperature": 0.5, "thinkingEffort": "medium"}, headers=auth_headers,
        )
        assert r.status_code == 200, (entry["key"], r.text)


def test_credential_ref_must_belong_to_user(client, auth_headers):
    r = client.put(
        "/agents/config/resumeTailoring",
        json={"credentialRef": "does-not-exist"}, headers=auth_headers,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Billing audit (GAP-D3)
# ---------------------------------------------------------------------------


def test_billing_audit_records_api_key_metered_path(
    client, auth_headers, test_user_id, monkeypatch
):
    # Consumer subscription OAuth was removed (GAP-AUTH-001): the only supported
    # Anthropic credential is an API key, and it always audits as metered_api.
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    repo = UserProviderCredentialRepository()

    repo.upsert(
        test_user_id, "anthropic", auth_mode="api_key", secret="sk-ant-api-key0002",
    )
    out = _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    assert out["billingAudit"]["authMode"] == "api_key"
    assert out["billingAudit"]["quotaPath"] == "metered_api"
    assert out["billingAudit"]["provider"] == "anthropic"


def test_billing_audit_persisted_to_agent_run(
    client, auth_headers, test_user_id, monkeypatch
):
    from app.db import get_connection

    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    UserProviderCredentialRepository().upsert(
        test_user_id, "anthropic", auth_mode="api_key", secret="sk-ant-api-persist9",
    )
    out = _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    run_id = out["run_id"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "billingAuditJson" FROM "AgentRun" WHERE "id" = %s', (run_id,)
            )
            audit = cur.fetchone()[0]
    assert audit is not None
    assert audit["authMode"] == "api_key"


def test_deterministic_agent_billing_audit_is_none(client, auth_headers, test_user_id):
    out = _record_run(
        test_user_id, "scout", {}, lambda: {"persisted": 0, "updated": 0, "errors": []}
    )
    assert out["billingAudit"] == {"quotaPath": "none"}


# ---------------------------------------------------------------------------
# Quota exhaustion 429 (GAP-D3)
# ---------------------------------------------------------------------------


def test_quota_block_returns_429_with_retry_after(
    client, auth_headers, test_user_id, monkeypatch
):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    AgentQuotaBlockRepository().set_block(
        test_user_id, "anthropic",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        reason="subscription_quota_exceeded",
    )
    with pytest.raises(HTTPException) as ei:
        _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    assert ei.value.status_code == 429
    detail = ei.value.detail
    assert detail["error"] == "subscription_quota_exceeded"
    assert detail["retryAfter"] > 0
    assert "API-key" in detail["suggestion"]
