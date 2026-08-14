"""U-AX build spec item 4a — GET /analytics/agent-policy.

Per U-PLAN.md U-AX BUILD SPEC ADDITIONS item 2(a): "a 'Agent Performance
Policy' panel — current rigor tier, WHICH metrics triggered it (conversion vs
20% target, dimension scores vs 80% floor), and what the agents are doing
differently at this tier" + item 5: "the metrics it consumes ... last-run
policy tier" per agent.

This endpoint does not exist on ``main`` (grep negative for
``agent-policy``/``agent_policy`` across ``apps/api/app/routers`` — verified
2026-08-13). Written BEFORE implementation.

CONTRACT PINNED BY THIS FILE (test-author decision on response shape; the
tier semantics themselves come from ``app.services.quality_policy`` per
``test_uax_rigor_policy.py``):

    GET /analytics/agent-policy ->
    {
      "tier": "standard" | "heightened" | "insufficient_data",
      "triggers": [str, ...],
      "metricSnapshot": {"sampleSize": int, "conversionRate": float,
                          "dimensionScores": {...}},
      "perAgent": [
        {"agentKey": str, "backend": str, "lastRun": {...} | null}, ...
      ]
    }

Run under ``flock /tmp/aether-pytest.lock``.
"""
from __future__ import annotations


class TestAgentPolicyEndpointAuth:
    def test_requires_authentication(self, client):
        resp = client.get("/analytics/agent-policy")
        assert resp.status_code == 401


class TestAgentPolicyEndpointShape:
    def test_returns_200_with_the_documented_shape(self, client, auth_headers):
        resp = client.get("/analytics/agent-policy", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) >= {"tier", "triggers", "metricSnapshot", "perAgent"}
        assert body["tier"] in ("standard", "heightened", "insufficient_data")
        assert isinstance(body["triggers"], list)
        assert isinstance(body["perAgent"], list)

    def test_fresh_user_with_zero_applications_is_honestly_insufficient_data(
        self, client, auth_headers
    ):
        """A brand-new fixture user (0 submissions, 0 recorded conversions)
        must NEVER be reported as 'standard' (healthy) — that would fabricate
        confidence in a rate computed from zero real signal."""
        resp = client.get("/analytics/agent-policy", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["tier"] == "insufficient_data"

    def test_per_agent_covers_every_runnable_catalog_agent(self, client, auth_headers):
        """Per-agent visibility (U-AX item 5): every REAL (backend-having)
        catalog agent must appear, honestly reporting 'never run' (null
        lastRun) rather than being silently omitted."""
        from app.routers.agents import AGENT_CATALOG

        resp = client.get("/analytics/agent-policy", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        per_agent = resp.json()["perAgent"]
        reported_keys = {row["agentKey"] for row in per_agent}
        real_keys = {a["key"] for a in AGENT_CATALOG if a.get("backend")}
        assert real_keys <= reported_keys, (
            f"missing real agents in perAgent: {real_keys - reported_keys}"
        )
        tailoring_row = next(r for r in per_agent if r["agentKey"] == "resumeTailoring")
        assert tailoring_row["lastRun"] is None  # never run for this fresh user
