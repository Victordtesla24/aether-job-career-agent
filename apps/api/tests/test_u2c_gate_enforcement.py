"""U2c — the gate reaches the real pipeline, the real record and the real human.

``test_u2c_quality_gate.py`` pins the gate's own arithmetic and the loop's
bounded iteration. This file pins the three places that make it MATTER:

* the TAILORING agent arms the gate and persists the verdict, so a below-floor
  résumé is flagged on the artifact itself (card + Studio read it back);
* the APPROVAL flow refuses to approve a below-floor artifact without an
  explicit human acknowledgment, quoting the failing dimensions;
* the RUN record carries the per-attempt trail the Supervisor's directive loop
  consumes (ADR-AGI-2) — additive columns only.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.db import get_connection, new_id
from app.repositories.approval import ApprovalRepository


class TestTailoringAgentArmsTheGate:
    def test_run_constructs_the_loop_with_the_floor_and_bounded_attempts(
        self, monkeypatch: Any
    ) -> None:
        """The gate is armed at the ONE production seam that owns the decision
        — not left as an opt-in nobody opts into."""
        from app.agents import tailor_agent as tailor_agent_module
        from app.services import quality_gate

        captured: dict[str, Any] = {}

        class _CaptureLoop:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

            def run(self, *a: Any, **k: Any) -> Any:
                raise RuntimeError("stop-before-llm")

        monkeypatch.setenv(quality_gate.GATE_ATTEMPTS_ENV, "1")
        monkeypatch.setattr(tailor_agent_module, "TailoringLoop", _CaptureLoop)
        monkeypatch.setattr(tailor_agent_module, "build_career_corpus", lambda *a, **k: "")
        monkeypatch.setattr(tailor_agent_module, "build_story_evidence", lambda *a, **k: "")
        monkeypatch.setattr(tailor_agent_module, "build_corpus_evidence", lambda *a, **k: "")

        agent = tailor_agent_module.TailoringAgent.__new__(
            tailor_agent_module.TailoringAgent
        )
        agent._service = object()
        agent._ats_engine = object()
        agent._stories = None
        agent._jobs = type(
            "J",
            (),
            {
                "get_by_id": staticmethod(
                    lambda *a, **k: {
                        "id": "j1",
                        "title": "Backend Engineer",
                        "company": "Acme",
                        "description": "Own the platform.",
                    }
                )
            },
        )()
        agent.ensure_base_resume = lambda user_id: {  # noqa: ARG005
            "sections": {"raw_text": "Experienced engineer.", "bullets": []}
        }

        with pytest.raises(RuntimeError, match="stop-before-llm"):
            agent.run("u1", "j1")

        assert captured.get("dimension_floor") == quality_gate.QUALITY_FLOOR
        assert captured.get("gate_extra_attempts") == 1

    def test_the_verdict_is_persisted_on_the_run_summary(self) -> None:
        """``tailoringSummary`` is what a reload renders. A verdict that lives
        only in one HTTP response is not an enforcement — it is a toast."""
        from app.agents.tailor_agent import build_tailoring_summary
        from app.services.quality_gate import QUALITY_FLOOR

        gate = {
            "artifact": "resume_tailor",
            "floor": QUALITY_FLOOR,
            "passed": False,
            "dimensions": [],
            "failing": [
                {
                    "key": "keywordMatch",
                    "label": "Keyword Match",
                    "score": 61.0,
                    "floor": QUALITY_FLOOR,
                    "measured": True,
                    "passed": False,
                    "unmeasuredReason": None,
                }
            ],
            "failingLabels": ["Keyword Match"],
            "summary": "Below quality floor: 1 dimension did not clear the 80% floor.",
            "acknowledgementLabel": "Approve anyway — 1 dimension below floor",
        }
        summary = build_tailoring_summary(
            target_score=85.0,
            best_score=90.0,
            best_iteration=1,
            iterations_run=3,
            reached_target=False,
            stop_reason="quality_gate_cap",
            requires_review=True,
            warning="…",
            unreachable_keywords=[],
            gap_keywords=[],
            net_changes=2,
            quality_gate=gate,
            gate_attempts_used=2,
        )
        assert summary["qualityGate"] == gate
        assert summary["belowQualityFloor"] is True
        assert summary["failingDimensions"] == ["Keyword Match"]
        assert summary["gateAttemptsUsed"] == 2

    def test_a_missing_verdict_is_not_a_below_floor_claim(self) -> None:
        """Artifacts produced before this gate existed carry no verdict.
        Reporting them as below the floor would claim a judgement that was
        never made."""
        from app.agents.tailor_agent import build_tailoring_summary

        summary = build_tailoring_summary(
            target_score=85.0, best_score=90.0, best_iteration=1, iterations_run=1,
            reached_target=True, stop_reason="target_reached", requires_review=False,
            warning=None, unreachable_keywords=[], gap_keywords=[], net_changes=1,
            quality_gate=None, gate_attempts_used=0,
        )
        assert summary["qualityGate"] is None
        assert summary["belowQualityFloor"] is False
        assert summary["failingDimensions"] == []


class TestApprovalRequiresExplicitAcknowledgement:
    """RULES item 1: "below-threshold artifacts require explicit user
    acknowledgment to approve"."""

    def _pending_below_floor(self, user_id: str) -> dict[str, Any]:
        return ApprovalRepository().create(
            user_id,
            "application_submit",
            {
                "kind": "resume_tailor",
                "resume_id": new_id(),
                "job_id": new_id(),
                "job_title": "Backend Engineer",
                "company": "Acme",
                "qualityGate": {
                    "artifact": "resume_tailor",
                    "floor": 80.0,
                    "passed": False,
                    "dimensions": [],
                    "failing": [
                        {"key": "keywordMatch", "label": "Keyword Match",
                         "score": 61.0, "floor": 80.0, "measured": True,
                         "passed": False, "unmeasuredReason": None},
                        {"key": "experienceMatch", "label": "Experience Match",
                         "score": 70.0, "floor": 80.0, "measured": True,
                         "passed": False, "unmeasuredReason": None},
                    ],
                    "failingLabels": ["Keyword Match", "Experience Match"],
                    "summary": (
                        "Below quality floor: 2 dimensions did not clear the "
                        "80% floor — Keyword Match (61.0% vs 80% floor); "
                        "Experience Match (70.0% vs 80% floor)."
                    ),
                    "acknowledgementLabel": "Approve anyway — 2 dimensions below floor",
                },
            },
        )

    def test_approving_without_acknowledgement_is_refused_and_says_why(
        self, client, auth_headers, test_user_id
    ) -> None:
        approval = self._pending_below_floor(test_user_id)
        resp = client.post(
            f"/approvals/{approval['id']}/approve", json={}, headers=auth_headers
        )
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        # The refusal names the real failing dimensions, not a generic warning.
        assert "Keyword Match" in detail
        assert "Experience Match" in detail
        assert "Approve anyway — 2 dimensions below floor" in detail

        # ...and the approval is genuinely still pending, not half-resolved.
        assert (
            ApprovalRepository().get_by_id(approval["id"], test_user_id)["status"]
            == "pending"
        )

    def test_explicit_acknowledgement_approves_and_is_recorded(
        self, client, auth_headers, test_user_id
    ) -> None:
        approval = self._pending_below_floor(test_user_id)
        resp = client.post(
            f"/approvals/{approval['id']}/approve",
            json={"acknowledge_below_floor": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "approved"

        row = ApprovalRepository().get_by_id(approval["id"], test_user_id)
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        # The acknowledgment is auditable on the row itself — "the user was
        # told and said yes anyway" must survive the request that carried it.
        assert payload["acknowledgedBelowFloor"] is True

    def test_rejecting_a_below_floor_artifact_needs_no_acknowledgement(
        self, client, auth_headers, test_user_id
    ) -> None:
        """The gate exists to stop a below-floor artifact being ACCEPTED by
        accident. Refusing one is the safe direction and must never be
        obstructed."""
        approval = self._pending_below_floor(test_user_id)
        resp = client.post(
            f"/approvals/{approval['id']}/reject", json={}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rejected"

    def test_an_artifact_that_cleared_the_floor_approves_unchanged(
        self, client, auth_headers, test_user_id
    ) -> None:
        approval = ApprovalRepository().create(
            test_user_id,
            "application_submit",
            {
                "kind": "resume_tailor",
                "resume_id": new_id(),
                "job_id": new_id(),
                "qualityGate": {
                    "artifact": "resume_tailor", "floor": 80.0, "passed": True,
                    "dimensions": [], "failing": [], "failingLabels": [],
                    "summary": "Every quality dimension is above the 80% floor.",
                    "acknowledgementLabel": "Approve anyway — 0 dimensions below floor",
                },
            },
        )
        resp = client.post(
            f"/approvals/{approval['id']}/approve", json={}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text

    def test_a_legacy_approval_without_a_verdict_approves_unchanged(
        self, client, auth_headers, test_user_id
    ) -> None:
        """Every approval created before this slice carries no verdict. The
        gate must not retroactively block them on a judgement never made."""
        approval = ApprovalRepository().create(
            test_user_id,
            "application_submit",
            {"kind": "resume_tailor", "resume_id": new_id(), "job_id": new_id()},
        )
        resp = client.post(
            f"/approvals/{approval['id']}/approve", json={}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text


class TestRunInstrumentation:
    """RULES item 5: iteration attempts + outcomes recorded ON THE RUN, for the
    Supervisor's directive loop (ADR-AGI-2). Additive fields only."""

    def test_ddl_is_additive_and_idempotent(self, db_session) -> None:
        from app.repositories.agent_run import ensure_agent_run_quality_columns

        ensure_agent_run_quality_columns()
        ensure_agent_run_quality_columns()  # second call must be a no-op
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT column_name FROM information_schema.columns '
                "WHERE table_name = 'AgentRun' AND column_name IN "
                "('qualityAttempts','qualityGateState')"
            )
            cols = {r[0] for r in cur.fetchall()}
        assert cols == {"qualityAttempts", "qualityGateState"}

    def test_attempts_and_final_state_are_recorded_from_the_run_output(
        self, test_user_id
    ) -> None:
        from app.repositories.agent_run import (
            AgentRunRepository,
            ensure_agent_run_quality_columns,
        )

        ensure_agent_run_quality_columns()
        runs = AgentRunRepository()
        run = runs.start(test_user_id, "tailor", {"job_id": "j1"})
        runs.record_quality_instrumentation(
            run["id"],
            {
                "iterations": [
                    {
                        "iteration": 1,
                        "score": 90.0,
                        "qualityGate": {
                            "passed": False,
                            "failingLabels": ["Keyword Match"],
                            "dimensions": [
                                {"key": "keywordMatch", "score": 61.0, "passed": False}
                            ],
                        },
                    },
                    {
                        "iteration": 2,
                        "score": 92.0,
                        "qualityGate": {
                            "passed": True, "failingLabels": [],
                            "dimensions": [
                                {"key": "keywordMatch", "score": 84.0, "passed": True}
                            ],
                        },
                    },
                ],
                "tailoringSummary": {
                    "belowQualityFloor": False,
                    "stopReason": "target_reached",
                    "gateAttemptsUsed": 1,
                    "failingDimensions": [],
                },
            },
        )

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "qualityAttempts", "qualityGateState" FROM "AgentRun" '
                    'WHERE "id" = %s',
                    (run["id"],),
                )
                attempts, state = cur.fetchone()

        assert state == "passed"
        assert attempts["attempts"] == 2
        assert attempts["stopReason"] == "target_reached"
        assert attempts["gateAttemptsUsed"] == 1
        # One entry per attempt, each with its OWN real score — never a summary
        # standing in for the trail.
        assert [a["iteration"] for a in attempts["perAttempt"]] == [1, 2]
        assert [a["score"] for a in attempts["perAttempt"]] == [90.0, 92.0]
        assert attempts["perAttempt"][0]["failingLabels"] == ["Keyword Match"]
        assert attempts["perAttempt"][1]["gatePassed"] is True

    def test_a_below_floor_run_records_the_honest_terminal_state(
        self, test_user_id
    ) -> None:
        from app.repositories.agent_run import (
            AgentRunRepository,
            ensure_agent_run_quality_columns,
        )

        ensure_agent_run_quality_columns()
        runs = AgentRunRepository()
        run = runs.start(test_user_id, "tailor", {"job_id": "j2"})
        runs.record_quality_instrumentation(
            run["id"],
            {
                "iterations": [
                    {"iteration": 1, "score": 90.0,
                     "qualityGate": {"passed": False,
                                     "failingLabels": ["Keyword Match"],
                                     "dimensions": []}},
                ],
                "tailoringSummary": {
                    "belowQualityFloor": True,
                    "stopReason": "quality_gate_cap",
                    "gateAttemptsUsed": 2,
                    "failingDimensions": ["Keyword Match"],
                },
            },
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "qualityAttempts", "qualityGateState" FROM "AgentRun" '
                    'WHERE "id" = %s',
                    (run["id"],),
                )
                attempts, state = cur.fetchone()
        assert state == "below_floor"
        assert attempts["failingDimensions"] == ["Keyword Match"]

    def test_a_run_with_no_gate_records_nothing_rather_than_a_placeholder(
        self, test_user_id
    ) -> None:
        from app.repositories.agent_run import (
            AgentRunRepository,
            ensure_agent_run_quality_columns,
        )

        ensure_agent_run_quality_columns()
        runs = AgentRunRepository()
        run = runs.start(test_user_id, "discovery", {})
        runs.record_quality_instrumentation(run["id"], {"jobs": 3})
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "qualityAttempts", "qualityGateState" FROM "AgentRun" '
                    'WHERE "id" = %s',
                    (run["id"],),
                )
                attempts, state = cur.fetchone()
        assert attempts is None
        assert state is None
