"""ORCH-ADV — one career operating loop, honest copy, team dependencies.

Independent adversarial review (ORCH-ADV-001..014) proved the three-map
orchestration payload fabricated capabilities (Learning Loop "re-tunes",
Adzuna/ABS on marketTrends, "applications submitted" on an agent that
transmits nothing) and hid the Story Bank → tailoring team behind a split
the codebase itself called the product's most important fact.

These tests pin the replacement contract. Written BEFORE the map rewrite.
Run under ``flock /tmp/aether-pytest.lock``.
"""
from __future__ import annotations

import inspect
import re

from app.routers.agents import AGENT_CATALOG, _ORCHESTRATION_MAPS, _pipeline_core


def _flatten(maps: list[dict]) -> list[dict]:
    return [a for m in maps for s in m.get("stages", []) for a in s.get("agents", [])]


def _maps(client, auth_headers) -> list[dict]:
    resp = client.get("/agents/orchestration-map", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body.get("maps"), list)
    return body["maps"]


class TestOneOperatingLoop:
    def test_subscriber_console_is_exactly_one_placed_map(self, client, auth_headers):
        maps = _maps(client, auth_headers)
        placed = [m for m in maps if m["key"] != "unmapped"]
        assert len(placed) == 1, [m["key"] for m in placed]
        assert placed[0]["key"] == "career-operating-loop"
        assert placed[0]["name"] == "Career Search Operating Loop"

    def test_subtitle_does_not_claim_automatic_retuning(self, client, auth_headers):
        maps = _maps(client, auth_headers)
        blob = " ".join(
            f"{m.get('name', '')} {m.get('subtitle') or ''}" for m in maps
        ).lower()
        assert "re-tune" not in blob
        assert "retune" not in blob
        assert "re-tunes" not in blob

    def test_every_catalog_agent_is_placed_once_on_the_loop(self, client, auth_headers):
        maps = _maps(client, auth_headers)
        keys = [a["agentKey"] for a in _flatten(maps)]
        assert len(keys) == len(set(keys))
        assert set(keys) == {a["key"] for a in AGENT_CATALOG}

    def test_stage_order_makes_the_team_visible(self, client, auth_headers):
        loop = next(m for m in _maps(client, auth_headers) if m["key"] == "career-operating-loop")
        stages = [s["stage"] for s in loop["stages"]]
        by_agent = {
            a["agentKey"]: s["stage"]
            for s in loop["stages"]
            for a in s["agents"]
        }
        assert by_agent["orchestration"] == stages[0]
        assert stages.index(by_agent["storyExtraction"]) < stages.index(by_agent["resumeTailoring"])
        assert stages.index(by_agent["resumeTailoring"]) < stages.index(by_agent["coverLetter"])
        assert stages.index(by_agent["coverLetter"]) < stages.index(by_agent["compliance"])
        assert stages.index(by_agent["compliance"]) < stages.index(by_agent["submission"])
        assert by_agent["emailAgent"] != by_agent["submission"]
        assert by_agent["learningFeedback"] == stages[-1]


class TestHonestMetrics:
    def _metrics(self, client, auth_headers, key: str) -> list[str]:
        agent = next(a for a in _flatten(_maps(client, auth_headers)) if a["agentKey"] == key)
        return list(agent["metricsConsumed"])

    def _thresholds(self, client, auth_headers, key: str) -> list[str]:
        agent = next(a for a in _flatten(_maps(client, auth_headers)) if a["agentKey"] == key)
        return list(agent["thresholds"])

    def test_market_trends_metrics_are_own_feed_only(self, client, auth_headers):
        metrics = " ".join(self._metrics(client, auth_headers, "marketTrends")).lower()
        assert "adzuna" not in metrics
        assert "abs" not in metrics
        assert "keyword" in metrics or "own feed" in metrics or "your own" in metrics

    def test_submission_does_not_claim_applications_submitted(self, client, auth_headers):
        metrics = " ".join(self._metrics(client, auth_headers, "submission")).lower()
        assert "applications submitted" not in metrics
        assert "queued" in metrics or "approval" in metrics

    def test_submission_does_not_own_the_interview_conversion_threshold(
        self, client, auth_headers
    ):
        assert self._thresholds(client, auth_headers, "submission") == []

    def test_notification_does_not_claim_status_transitions(self, client, auth_headers):
        metrics = " ".join(self._metrics(client, auth_headers, "notification")).lower()
        assert "transition" not in metrics

    def test_scheduling_does_not_claim_interviews_scheduled(self, client, auth_headers):
        metrics = " ".join(self._metrics(client, auth_headers, "scheduling")).lower()
        assert "interviews scheduled" not in metrics
        assert "draft" in metrics or "proposal" in metrics or "availability" in metrics

    def test_writing_agents_do_not_consume_interview_conversion(self, client, auth_headers):
        for key in ("resumeTailoring", "coverLetter"):
            metrics = " ".join(self._metrics(client, auth_headers, key)).lower()
            assert "interview conversion" not in metrics, key

    def test_salary_intelligence_does_not_say_benchmarks(self, client, auth_headers):
        metrics = " ".join(self._metrics(client, auth_headers, "salaryIntelligence")).lower()
        assert "benchmark" not in metrics


class TestTeamFields:
    def test_every_agent_declares_team_role_and_neighbours(self, client, auth_headers):
        for entry in _flatten(_maps(client, auth_headers)):
            assert isinstance(entry.get("teamRole"), str) and entry["teamRole"].strip()
            assert isinstance(entry.get("dependsOn"), list)
            assert isinstance(entry.get("supports"), list)
            blob = entry["teamRole"].lower()
            assert "re-tune" not in blob and "retune" not in blob

    def test_story_extraction_supports_the_writing_agents(self, client, auth_headers):
        story = next(
            a for a in _flatten(_maps(client, auth_headers)) if a["agentKey"] == "storyExtraction"
        )
        assert "resumeTailoring" in story["supports"]
        assert "coverLetter" in story["supports"]
        assert "interviewPrep" in story["supports"]

    def test_tailoring_depends_on_story_extraction(self, client, auth_headers):
        tailor = next(
            a for a in _flatten(_maps(client, auth_headers)) if a["agentKey"] == "resumeTailoring"
        )
        assert "storyExtraction" in tailor["dependsOn"]

    def test_sales_agent_is_not_on_the_subscriber_map(self, client, auth_headers):
        keys = {a["agentKey"] for a in _flatten(_maps(client, auth_headers))}
        assert "salesAgent" not in keys
        assert "sales" not in {k.lower() for k in keys}


class TestSupervisorPlanIsConsumed:
    def test_pipeline_core_reads_the_recorded_supervisor_plan(self):
        src = inspect.getsource(_pipeline_core)
        assert re.search(r"sup_out\.get\(\s*[\"']plan[\"']", src), (
            "supervisor records a plan that _pipeline_core never reads"
        )


class TestStaticMapTable:
    def test_checked_in_maps_tuple_is_one_operating_loop(self):
        assert len(_ORCHESTRATION_MAPS) == 1
        key, name, subtitle, stages = _ORCHESTRATION_MAPS[0]
        assert key == "career-operating-loop"
        assert "re-tune" not in subtitle.lower()
        placed = [k for _stage, keys in stages for k in keys]
        assert placed[0] == "orchestration"
        assert placed[-1] == "learningFeedback"
        assert set(placed) == {a["key"] for a in AGENT_CATALOG}
