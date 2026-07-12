"""AGT-AGENTS — tests for the Agents screen endpoints (design/screens/agents.html):
catalog, per-agent config, provider connections, aggregate stats and test-run.

All state is persisted to the additive ``AgentConfig`` / ``AgentProvider`` tables
(created lazily by the router); these tests assert real persistence and the
derived-status / real-stats contracts.
"""
from __future__ import annotations

import pytest

from app.db import get_connection


@pytest.fixture()
def user_id(client, auth_headers, db_session) -> str:
    with db_session.cursor() as cur:
        cur.execute('SELECT "id" FROM "User" LIMIT 1')
        return cur.fetchone()[0]


@pytest.fixture(autouse=True)
def _clean_agent_tables():
    """Screen-scoped tables are not in conftest's cleanup list — clear them and
    reset the router's process-level ``_tables_ready`` cache so the next test
    re-creates them."""
    from app.routers import agents as agents_module

    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS "AgentConfig"')
            cur.execute('DROP TABLE IF EXISTS "AgentProvider"')
        conn.commit()
    agents_module._tables_ready = False


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def test_catalog_lists_full_roster_with_defaults(client, auth_headers):
    res = client.get("/agents/catalog", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["counts"]["total"] == len(body["agents"]) >= 20
    for a in body["agents"]:
        assert a["status"] in {"active", "paused", "error", "planned"}
        assert a["model"]
        assert a["tip"]
        # Honesty contract: an agent with no backend implementation is
        # "planned" (a roadmap card), never presented as running.
        if a["backend"] is None:
            assert a["status"] == "planned"
        else:
            assert a["status"] != "planned"
    assert body["counts"]["planned"] == sum(
        1 for a in body["agents"] if a["backend"] is None
    )
    # The runnable agents map to real backends.
    runnable = {a["key"] for a in body["agents"] if a["runnable"]}
    assert {"jobDiscovery", "resumeTailoring", "coverLetter", "matchScoring"} <= runnable


def test_disabling_agent_marks_it_paused_and_persists(client, auth_headers):
    # Must be an IMPLEMENTED agent — planned cards stay "planned" regardless.
    res = client.put(
        "/agents/config/coverLetter",
        json={"enabled": False},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["enabled"] is False

    cat = client.get("/agents/catalog", headers=auth_headers).json()
    entry = next(a for a in cat["agents"] if a["key"] == "coverLetter")
    assert entry["status"] == "paused"
    assert entry["enabled"] is False
    assert cat["counts"]["paused"] >= 1


def test_reassign_agent_model_persists(client, auth_headers):
    res = client.put(
        "/agents/config/resumeTailoring", json={"model": "gpt-4o"}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["model"] == "gpt-4o"
    # The catalog card shows the model the agent ACTUALLY runs on (the LLM
    # tier resolved from env), not the stored preference — no dishonest
    # "assigned model" display while the runtime is pinned to its tier.
    from app.services.llm_client import get_model

    cat = client.get("/agents/catalog", headers=auth_headers).json()
    entry = next(a for a in cat["agents"] if a["key"] == "resumeTailoring")
    assert entry["model"] == get_model("REASONING")


def test_config_unknown_agent_404(client, auth_headers):
    res = client.put("/agents/config/nope", json={"enabled": False}, headers=auth_headers)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def test_providers_seed_six(client, auth_headers):
    res = client.get("/agents/providers", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 6
    ids = {p["id"] for p in body}
    assert ids == {"anthropic", "openrouter", "openai", "gemini", "bedrock", "groq"}
    bedrock = next(p for p in body if p["id"] == "bedrock")
    assert bedrock["status"] == "unconfigured"


def test_provider_connect_without_credential_409(client, auth_headers):
    # A provider with no key on the server can never be marked connected —
    # that would fabricate a connection status.
    res = client.put(
        "/agents/providers/bedrock", json={"status": "connected"}, headers=auth_headers
    )
    assert res.status_code == 409


def test_provider_connect_with_credential_persists(client, auth_headers, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_credential")
    res = client.put(
        "/agents/providers/groq", json={"status": "connected"}, headers=auth_headers
    )
    assert res.status_code == 200
    providers = client.get("/agents/providers", headers=auth_headers).json()
    groq = next(p for p in providers if p["id"] == "groq")
    assert groq["status"] == "connected"


def test_provider_status_is_env_derived(client, auth_headers, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    providers = client.get("/agents/providers", headers=auth_headers).json()
    by_id = {p["id"]: p for p in providers}
    assert by_id["openrouter"]["status"] == "connected"
    assert by_id["openai"]["status"] == "unconfigured"


def test_provider_model_switch_persists(client, auth_headers, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client.put(
        "/agents/providers/anthropic",
        json={"model": "claude-3.5-haiku"},
        headers=auth_headers,
    )
    providers = client.get("/agents/providers", headers=auth_headers).json()
    anthropic = next(p for p in providers if p["id"] == "anthropic")
    assert anthropic["model"] == "claude-3.5-haiku"


def test_provider_unknown_404(client, auth_headers):
    res = client.put("/agents/providers/nope", json={"status": "connected"}, headers=auth_headers)
    assert res.status_code == 404


def test_provider_invalid_status_422(client, auth_headers):
    res = client.put("/agents/providers/openai", json={"status": "bogus"}, headers=auth_headers)
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Stats + test-run
# ---------------------------------------------------------------------------


def test_stats_shape_and_realism(client, auth_headers):
    res = client.get("/agents/stats", headers=auth_headers)
    assert res.status_code == 200
    s = res.json()
    for key in ("spendUsd", "tokensTotal", "successRate", "taskCount", "providerCount"):
        assert key in s
    assert s["providerCount"] == 6
    # With no runs the success rate defaults to 100 and counts are zero.
    assert 0 <= s["successRate"] <= 100


def test_stats_reflect_a_real_run(client, auth_headers):
    # storyExtractor runs against fixtures in replay mode → a real completed run.
    run = client.post("/agents/story-extractor/run", headers=auth_headers)
    assert run.status_code == 200
    s = client.get("/agents/stats", headers=auth_headers).json()
    assert s["taskCount"] >= 1
    assert s["mostActiveAgent"] is not None
    # Cost + tokens are now populated from the measured run I/O.
    assert s["tokensTotal"] > 0
    assert s["spendUsd"] >= 0


def test_test_run_estimates_no_charge(client, auth_headers):
    res = client.post(
        "/agents/test-run", json={"agent_key": "resumeTailoring"}, headers=auth_headers
    )
    assert res.status_code == 200
    body = res.json()
    from app.services.llm_client import get_model

    assert body["model"] == get_model("REASONING")
    assert body["estCost"] > 0
    assert body["creditsCharged"] == 0.0
    # "Actual" figures are real run history — null until the agent has run.
    assert body["actualCost"] is None or body["actualCost"] >= 0


def test_test_run_unknown_agent_404(client, auth_headers):
    res = client.post("/agents/test-run", json={"agent_key": "nope"}, headers=auth_headers)
    assert res.status_code == 404


def test_endpoints_require_auth(client):
    assert client.get("/agents/catalog").status_code == 401
    assert client.get("/agents/providers").status_code == 401
    assert client.get("/agents/stats").status_code == 401
