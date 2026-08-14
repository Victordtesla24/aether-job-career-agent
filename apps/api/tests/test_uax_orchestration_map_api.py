"""U-AX build spec item 5 — the Agent Orchestration section:
GET /agents/orchestration-map.

Per U-PLAN.md U-AX BUILD SPEC ADDITIONS item 5 (binding): "the Agents page's
orchestration section presents ALL 22 agents in one DEFINED end-to-end
workflow map (discovery -> fit-scoring -> tailoring -> cover letter ->
quality gates -> submission -> tracking -> learning loop), each agent
showing: its role/stage in the workflow, real vs planned status (HONEST --
planned agents render as labeled roadmap stages, never fake execution), the
metrics it consumes, its threshold responsibilities, last-run policy tier,
and its improvement trend across runs."

ARCHITECTURAL FREEDOM (same item, user ~23:1xZ, binding): "one or MULTIPLE
workflow maps allowed -- the constraint is the END RESULT (thresholds met,
visible per-run improvement, subscriber value), not the map count." This file
therefore asserts the END RESULT (every catalog agent accounted for, honest
real/planned status, a stage label, metric/threshold visibility) without
pinning how many maps or what they are named.

This endpoint does not exist on ``main`` (grep negative for
``orchestration-map``/``orchestration_map`` across
``apps/api/app/routers/agents.py`` -- verified 2026-08-13; the existing
``Orchestration.tsx`` FE widget / MV-agent-monitor-00x coverage is a task-queue
+ pause/override panel, a DIFFERENT thing from this end-to-end workflow map).
Written BEFORE implementation.

CONTRACT PINNED BY THIS FILE (test-author decision on response shape --
deliberately loose on map count/naming per the freedom clause above):

    GET /agents/orchestration-map ->
    {
      "maps": [
        {
          "key": str, "name": str,
          "stages": [
            {"stage": str, "agents": [
              {"agentKey": str, "name": str, "backend": str | null,
               "status": "real" | "planned",
               "metricsConsumed": [str, ...], "thresholds": [str, ...],
               "lastRunPolicyTier": str | null, "trend": <any, present> },
              ...
            ]},
            ...
          ],
        },
        ...
      ]
    }

Run under ``flock /tmp/aether-pytest.lock``.
"""
from __future__ import annotations


def _flatten_agents(maps: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in maps:
        for stage in m.get("stages", []):
            out.extend(stage.get("agents", []))
    return out


class TestOrchestrationMapAuth:
    def test_requires_authentication(self, client):
        resp = client.get("/agents/orchestration-map")
        assert resp.status_code == 401


class TestOrchestrationMapCoverage:
    def test_returns_200_with_at_least_one_map(self, client, auth_headers):
        resp = client.get("/agents/orchestration-map", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body.get("maps"), list) and len(body["maps"]) >= 1

    def test_every_catalog_agent_is_present_exactly_once_across_all_maps(
        self, client, auth_headers
    ):
        """The mission's '22 agents' language (live-corrected by the scout to
        the CATALOG count, which is >=22 -- 18 is the distinct-runs-so-far
        count, a different number) must be satisfied against
        ``AGENT_CATALOG`` -- never a hardcoded literal that silently drifts
        when a new agent is added to the catalog."""
        from app.routers.agents import AGENT_CATALOG

        resp = client.get("/agents/orchestration-map", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        agents = _flatten_agents(resp.json()["maps"])
        assert len(AGENT_CATALOG) >= 22
        seen_keys = [a["agentKey"] for a in agents]
        assert len(seen_keys) == len(set(seen_keys)), "an agent key appears in the map more than once"
        assert set(seen_keys) == {a["key"] for a in AGENT_CATALOG}, (
            "orchestration map does not account for exactly the catalog's agent set"
        )

    def test_status_is_honest_real_vs_planned_matching_catalog_backend(
        self, client, auth_headers
    ):
        """Planned agents (no backend implementation) must NEVER render as
        'real' -- that would be fake execution (U-AX item 5, binding)."""
        from app.routers.agents import AGENT_CATALOG

        resp = client.get("/agents/orchestration-map", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        by_key = {a["key"]: a for a in AGENT_CATALOG}
        for entry in _flatten_agents(resp.json()["maps"]):
            assert entry["status"] in ("real", "planned")
            catalog_entry = by_key[entry["agentKey"]]
            expected = "real" if catalog_entry.get("backend") else "planned"
            assert entry["status"] == expected, (
                f"{entry['agentKey']}: status={entry['status']!r} but catalog "
                f"backend={catalog_entry.get('backend')!r} implies {expected!r}"
            )

    def test_every_agent_carries_a_stage_and_metric_threshold_visibility_fields(
        self, client, auth_headers
    ):
        resp = client.get("/agents/orchestration-map", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        maps = resp.json()["maps"]
        stage_names: set[str] = set()
        for m in maps:
            for stage in m.get("stages", []):
                stage_name = stage.get("stage")
                assert isinstance(stage_name, str) and stage_name.strip()
                stage_names.add(stage_name)
                for entry in stage.get("agents", []):
                    assert isinstance(entry.get("metricsConsumed"), list)
                    assert isinstance(entry.get("thresholds"), list)
                    assert "lastRunPolicyTier" in entry
                    assert "trend" in entry
        # Not pinning exact stage names (architectural freedom over
        # decomposition/naming) -- but a single undifferentiated bucket would
        # not be "a workflow map", so the pipeline must be broken into a
        # reasonable number of distinct stages.
        assert len(stage_names) >= 5, f"too few distinct stages: {stage_names}"

    def test_a_real_agent_with_no_runs_yet_is_honestly_null_not_fabricated(
        self, client, auth_headers
    ):
        """A fresh fixture user has run nothing -- every real agent's
        lastRunPolicyTier/trend must say so honestly, never invent a tier or
        a trend out of zero runs."""
        resp = client.get("/agents/orchestration-map", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        agents = _flatten_agents(resp.json()["maps"])
        real_agents = [a for a in agents if a["status"] == "real"]
        assert real_agents, "expected at least one real agent in the catalog"
        for entry in real_agents:
            assert entry["lastRunPolicyTier"] is None
