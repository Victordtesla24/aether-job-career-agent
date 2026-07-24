"""RT-007 — continuous board-sweep autopilot.

Operator mandate: agents must keep working until the board is complete (or a
~10-minute stretch ends) — never one-job-per-manual-run. These tests pin the
sweep's ORCHESTRATION contract with the agent-execution seam
(``board_sweep._run_agent``) monkeypatched; the real tailor/cover behaviors
are covered by their own suites (and RT-005 stage-sync), and the wired-up
sweep is verified live on production.
"""
from __future__ import annotations

import json
import time
import uuid

import pytest
from fastapi import HTTPException

from app.workers import board_sweep


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(
    conn, user_id: str, *, status: str = "screening", fit: float | None = 80.0,
    title: str = "Engineer",
) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, title, "Acme", "Build.", "greenhouse",
             f"https://example.com/job/{job_id}", status, fit),
        )
    conn.commit()
    return job_id


def _seed_application(conn, user_id: str, job_id: str, *, status: str = "draft") -> str:
    app_id, resume_id = _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "t"}), "hash-t"),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"createdAt","updatedAt") VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",'
            "NOW(),NOW())",
            (app_id, user_id, job_id, resume_id, status),
        )
    conn.commit()
    return app_id


def _far_deadline() -> float:
    return time.monotonic() + 3600.0


class TestSweepProcessesWholeBoard:
    def test_all_eligible_jobs_processed_best_fit_first(
        self, db_session, user_id, monkeypatch
    ):
        ids = [
            _seed_job(db_session, user_id, fit=60.0),
            _seed_job(db_session, user_id, fit=90.0),
            _seed_job(db_session, user_id, fit=75.0),
        ]
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda uid, agent, params: calls.append((agent, params["job_id"])) or {},
        )
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["reason"] == "board-complete"
        assert summary["processed"] == 3 and summary["covers"] == 3
        # Every job got tailor THEN cover, ordered by fitScore descending.
        expected_order = [ids[1], ids[2], ids[0]]
        assert calls == [
            pair for jid in expected_order for pair in (("tailor", jid), ("coverLetter", jid))
        ]

    def test_tailoring_job_gets_cover_only_and_goes_first(
        self, db_session, user_id, monkeypatch
    ):
        stuck = _seed_job(db_session, user_id, status="tailoring", fit=10.0)
        fresh = _seed_job(db_session, user_id, status="screening", fit=99.0)
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda uid, agent, params: calls.append((agent, params["job_id"])) or {},
        )
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["processed"] == 2
        assert calls[0] == ("coverLetter", stuck)  # completion outranks fitScore
        assert calls[1:] == [("tailor", fresh), ("coverLetter", fresh)]

    def test_job_with_existing_application_is_done(
        self, db_session, user_id, monkeypatch
    ):
        done = _seed_job(db_session, user_id)
        _seed_application(db_session, user_id, done, status="submitted")
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda *a, **k: pytest.fail("must not run agents for a done job"),
        )
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary == {
            "user_id": user_id, "processed": 0, "tailored": 0, "covers": 0,
            "failures": 0, "reason": "board-complete",
        }

    def test_unscored_discovered_jobs_are_not_touched(
        self, db_session, user_id, monkeypatch
    ):
        _seed_job(db_session, user_id, status="discovered", fit=None)
        _seed_job(db_session, user_id, status="screening", fit=None)
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda *a, **k: pytest.fail("unscored jobs are the fit-scorer's turf"),
        )
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["processed"] == 0 and summary["reason"] == "board-complete"


class TestSweepBounds:
    def test_deadline_stops_before_starting_a_job(self, db_session, user_id, monkeypatch):
        _seed_job(db_session, user_id)
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda *a, **k: pytest.fail("no job may start past the deadline"),
        )
        summary = board_sweep.sweep_user_stretch(
            user_id, deadline=time.monotonic() + 5.0
        )
        assert summary["reason"] == "deadline" and summary["processed"] == 0

    def test_job_cap_bounds_the_stretch(self, db_session, user_id, monkeypatch):
        for _ in range(4):
            _seed_job(db_session, user_id)
        monkeypatch.setattr(board_sweep, "_run_agent", lambda *a, **k: {})
        summary = board_sweep.sweep_user_stretch(
            user_id, deadline=_far_deadline(), max_jobs=2
        )
        assert summary["reason"] == "job-cap" and summary["processed"] == 2

    def test_quota_429_ends_the_stretch_honestly(self, db_session, user_id, monkeypatch):
        for _ in range(3):
            _seed_job(db_session, user_id)
        calls: list[str] = []

        def _quota_blocked(uid, agent, params):
            calls.append(agent)
            raise HTTPException(429, "Plan run quota exhausted")

        monkeypatch.setattr(board_sweep, "_run_agent", _quota_blocked)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["reason"] == "quota-exhausted"
        assert len(calls) == 1  # stopped at the FIRST 429 — no quota grinding

    def test_llm_outage_circuit_breaker(self, db_session, user_id, monkeypatch):
        from app.services.llm_client import LLMUnavailableError

        for _ in range(5):
            _seed_job(db_session, user_id)

        def _down(uid, agent, params):
            raise LLMUnavailableError("LLM backend unavailable")

        monkeypatch.setattr(board_sweep, "_run_agent", _down)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["reason"] == "llm-unavailable"
        assert summary["failures"] == board_sweep.LLM_OUTAGE_BREAKER

    def test_guard_rejection_moves_on_to_next_job(self, db_session, user_id, monkeypatch):
        from app.agents.cover_letter_agent import FabricationError

        bad = _seed_job(db_session, user_id, fit=95.0)
        good = _seed_job(db_session, user_id, fit=50.0)
        calls: list[tuple[str, str]] = []

        def _selective(uid, agent, params):
            calls.append((agent, params["job_id"]))
            if agent == "coverLetter" and params["job_id"] == bad:
                raise FabricationError(flagged=["invented-claim"])
            return {}

        monkeypatch.setattr(board_sweep, "_run_agent", _selective)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["processed"] == 1 and summary["failures"] == 1
        assert ("coverLetter", good) in calls  # the sweep kept going

    def test_missing_resume_refuses_without_burning_attempts(
        self, db_session, user_id, monkeypatch
    ):
        from app.services.resume_grounding import MissingResumeError

        _seed_job(db_session, user_id)

        def _refuse(uid, agent, params):
            raise MissingResumeError("Add your resume first.")

        monkeypatch.setattr(board_sweep, "_run_agent", _refuse)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["reason"] == "no-resume" and summary["processed"] == 0


class TestEligibilityAndCron:
    def test_eligible_users_includes_actionable_excludes_done(
        self, db_session, user_id
    ):
        _seed_job(db_session, user_id)  # actionable
        assert user_id in board_sweep.eligible_users(limit=50)
        done_user = _uid()
        with db_session.cursor() as cur:
            cur.execute(
                'INSERT INTO "User" ("id","email","passwordHash","updatedAt") '
                "VALUES (%s,%s,'x',NOW())",
                (done_user, f"{done_user}@t.dev"),
            )
        db_session.commit()
        jid = _seed_job(db_session, done_user)
        _seed_application(db_session, done_user, jid, status="submitted")
        assert done_user not in board_sweep.eligible_users(limit=50)

    def test_cron_is_a_noop_when_disabled(self, monkeypatch):
        import asyncio

        monkeypatch.delenv("AETHER_BOARD_SWEEP_ENABLED", raising=False)

        class _NoRedis:
            async def enqueue_job(self, *a, **k):  # pragma: no cover — must not run
                pytest.fail("disabled cron must not enqueue")

        result = asyncio.run(board_sweep.board_sweep_cron({"redis": _NoRedis()}))
        assert result == 0

    def test_cron_enqueues_dedup_job_ids_when_enabled(
        self, db_session, user_id, monkeypatch
    ):
        import asyncio

        _seed_job(db_session, user_id)
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")
        seen: list[tuple[str, str]] = []

        class _Redis:
            async def enqueue_job(self, fn, uid, _job_id=None):
                seen.append((fn, _job_id))
                return object()

        n = asyncio.run(board_sweep.board_sweep_cron({"redis": _Redis()}))
        assert n >= 1
        assert ("board_sweep_user", f"board-sweep:{user_id}") in seen
