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
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

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
            # Comfortably above the User.agentConfig column's live DB default
            # match threshold (80 — information_schema.columns.column_default
            # for "User"."agentConfig", applied out-of-band to the freshly-
            # cloned schema, no matching migration file), so all three stay
            # ELIGIBLE — this test measures ordering, not the fit gate (that's
            # AUD-COV-2's own suite). Relative order preserved: 60<75<90.
            _seed_job(db_session, user_id, fit=85.0),
            _seed_job(db_session, user_id, fit=99.0),
            _seed_job(db_session, user_id, fit=92.0),
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
        # Both jobs clear the user's match threshold (AUD-COV-2's gate; the
        # live schema's User.agentConfig column default is 80 — see
        # information_schema.columns.column_default, out-of-band, no matching
        # migration file), so what this test measures is purely the ORDER: a
        # cover-only completion outranks a better-fitting fresh job. ``stuck``
        # deliberately has the LOWER of the two passing scores, which is the
        # whole point — it still goes first.
        stuck = _seed_job(db_session, user_id, status="tailoring", fit=85.0)
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
            "failures": 0, "reason": "board-complete", "skipped_failures": 0,
            # CRITICAL-3: eligible jobs an aborted stretch left unattempted.
            # Always present (0 on a clean, complete board) so an abort can
            # never be mistaken for a finished board.
            "suppressed": 0,
            # ML-STOPALL-001: jobs skipped honestly because the dispatched
            # agent is paused by the user's own AgentConfig. Always present
            # (0 here — nothing was paused on this board).
            "skipped_paused": 0,
            # AUD-COV-2: eligible jobs autopilot declined to auto-generate for
            # because they sit below the user's own matchThreshold. Always
            # present (0 here — this board's only job is already applied to).
            "skipped_low_fit": 0,
            "needs_continuation": False,
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
        # Above the live schema's User.agentConfig column default match
        # threshold (80 — see information_schema.columns.column_default,
        # out-of-band, no matching migration file) so ``good`` stays eligible;
        # this test measures guard-rejection recovery, not the fit gate.
        good = _seed_job(db_session, user_id, fit=85.0)
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


class TestCoverFailureBackoff:
    """RT-007 hotfix: a job whose coverLetter draft is PERMANENTLY
    unfabricatable (FabricationGuard correctly rejecting every attempt) must
    NOT be retried every cron tick forever — 13+ failed attempts over 14h
    observed in production before this fix. The sweep backs off after
    ``max_cover_failures()`` failures in a sliding window.
    """

    def _seed_failed_cover_runs(self, conn, user_id: str, job_id: str, n: int) -> None:
        """Seed ``n`` failed coverLetter AgentRun rows for this job+user."""
        import uuid as _uuid

        with conn.cursor() as cur:
            for _ in range(n):
                run_id = "c" + _uuid.uuid4().hex[:24]
                cur.execute(
                    'INSERT INTO "AgentRun" '
                    '("id","userId","agentName","status","input","createdAt","startedAt") '
                    "VALUES (%s,%s,'coverLetter','failed'::\"AgentRunStatus\",%s,NOW(),NOW())",
                    (run_id, user_id, json.dumps({"job_id": job_id})),
                )
        conn.commit()

    def test_job_skipped_after_max_cover_failures(
        self, db_session, user_id, monkeypatch
    ):
        """A job with ``max_cover_failures()`` coverLetter failures in the
        window is PERMANENTLY skipped — the sweep does not retry it."""
        bad = _seed_job(db_session, user_id, fit=95.0)
        # Above the live schema's User.agentConfig column default match
        # threshold (80 — see information_schema.columns.column_default,
        # out-of-band, no matching migration file) so ``good`` stays eligible;
        # this test measures the cover-failure backoff, not the fit gate.
        good = _seed_job(db_session, user_id, fit=85.0)
        # Seed exactly MAX_COVER_FAILURES failed cover runs for `bad`.
        self._seed_failed_cover_runs(db_session, user_id, bad,
                                     board_sweep.MAX_COVER_FAILURES)
        calls: list[str] = []
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda uid, agent, params: calls.append(params["job_id"]) or {},
        )
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        # `good` was processed; `bad` was skipped.
        assert good in calls
        assert bad not in calls
        assert summary["processed"] == 1
        # `bad` remains on the board but saturated — honest reason.
        assert summary["reason"] == "skipped-failures"
        assert summary["skipped_failures"] == 1

    def test_failure_below_threshold_still_processed(
        self, db_session, user_id, monkeypatch
    ):
        """A job with fewer than ``max_cover_failures()`` failures is still
        eligible — the backoff only kicks in AT the threshold, not below it."""
        job = _seed_job(db_session, user_id, fit=80.0)
        # Seed MAX_COVER_FAILURES - 1 failures — below threshold.
        self._seed_failed_cover_runs(db_session, user_id, job,
                                     board_sweep.MAX_COVER_FAILURES - 1)
        calls: list[str] = []
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda uid, agent, params: calls.append(params["job_id"]) or {},
        )
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert job in calls
        assert summary["processed"] == 1

    def test_skipped_failures_reason_when_all_jobs_saturated(
        self, db_session, user_id, monkeypatch
    ):
        """When ALL eligible jobs are failure-saturated, the summary reason is
        ``skipped-failures`` (not ``board-complete``) so the operator can tell
        the sweep is backing off, not done."""
        bad = _seed_job(db_session, user_id, fit=95.0)
        self._seed_failed_cover_runs(db_session, user_id, bad,
                                     board_sweep.MAX_COVER_FAILURES)
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda *a, **k: pytest.fail("saturated job must not be attempted"),
        )
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["reason"] == "skipped-failures"
        assert summary["skipped_failures"] == 1
        assert summary["processed"] == 0

    def test_cover_failure_count_helper(self, db_session, user_id):
        """The ``_cover_failure_count`` helper counts failed coverLetter
        AgentRuns for this job+user in the window."""
        job = _seed_job(db_session, user_id, fit=80.0)
        assert board_sweep._cover_failure_count(user_id, job) == 0
        self._seed_failed_cover_runs(db_session, user_id, job, 2)
        assert board_sweep._cover_failure_count(user_id, job) == 2

    def test_env_tunable_max_failures(self, db_session, user_id, monkeypatch):
        """``AETHER_BOARD_SWEEP_MAX_COVER_FAILURES`` tightens/loosens the
        backoff threshold without a redeploy."""
        job = _seed_job(db_session, user_id, fit=80.0)
        monkeypatch.setenv("AETHER_BOARD_SWEEP_MAX_COVER_FAILURES", "5")
        self._seed_failed_cover_runs(db_session, user_id, job, 3)
        # 3 failures < threshold 5 — still eligible.
        assert board_sweep._cover_failure_count(user_id, job) == 3
        assert board_sweep.max_cover_failures() == 5
        target = board_sweep._next_target(user_id, set())
        assert target is not None and target["job_id"] == job


class TestCoverFailureAutoClearAndHonestLogging:
    """ML-W-12 (QA #2, uat/reports/evidence/prod-verify-2-wave2/PROD-VERIFY-2.json):
    the cover-failure suppression above (``TestCoverFailureBackoff``) is
    DB-backed with NO way to clear early — after the underlying cover-letter
    defect that CAUSED a batch of failures is fixed and deployed, every job
    that failed under the old broken code stays wedged for the rest of the
    24h window: it is excluded from ``_next_target``, so it can never earn
    the new success that would otherwise auto-clear it, and the tick log
    reports a healthy-looking ``skipped-failures (processed=0 ...)`` the
    whole time. Two behaviors are locked here (the third — the ops clear
    script — has its own end-to-end test below):
      1. a successful coverLetter completion resets a job's failure count;
      2. a tick that skips ALL eligible jobs due to suppression says so
         explicitly, with the earliest suppression-expiry time.
    """

    def _seed_cover_run(
        self, conn, user_id: str, job_id: str, status: str, minutes_ago: float,
        output: dict | None = None,
    ) -> None:
        """Seed one coverLetter AgentRun at an EXPLICIT relative timestamp
        (rather than bare ``NOW()``) so ordering between failures and a later
        success/clear is deterministic regardless of statement timing.

        ML-W-19: ``output`` matters now. A ``completed`` status alone is no
        longer proof a letter was produced — a guard rejection completes with
        ``output.coverLetterUnavailable = true`` and no letter — so the
        success case must seed the letter id a real success writes."""
        run_id = "c" + uuid.uuid4().hex[:24]
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "AgentRun" '
                '("id","userId","agentName","status","input","output","createdAt","startedAt") '
                "VALUES (%s,%s,'coverLetter',%s::\"AgentRunStatus\",%s,%s,"
                "NOW() - (%s || ' minutes')::interval, NOW())",
                (run_id, user_id, status, json.dumps({"job_id": job_id}),
                 json.dumps(output) if output is not None else None, minutes_ago),
            )
        conn.commit()

    def test_success_resets_failure_count(self, db_session, user_id):
        """(1/3) fail-before: today a job that failed MAX_COVER_FAILURES
        times and THEN got a successful coverLetter completion stays
        permanently excluded — the count never resets, so a real fix landing
        and succeeding does not un-wedge the job. One success must."""
        job = _seed_job(db_session, user_id, fit=80.0)
        for minutes_ago in (180, 170, 160):
            self._seed_cover_run(db_session, user_id, job, "failed", minutes_ago)
        # A LATER successful completion (e.g. a manual retry after the
        # underlying pipeline bug was fixed and deployed) — carrying the
        # ``cover_letter_id`` a real success always writes (ML-W-19).
        self._seed_cover_run(
            db_session, user_id, job, "completed", 90,
            output={"cover_letter_id": "c" + uuid.uuid4().hex[:24], "flagged": []},
        )

        assert board_sweep._cover_failure_count(user_id, job) == 0
        target = board_sweep._next_target(user_id, set())
        assert target is not None and target["job_id"] == job

    def test_tick_log_names_all_jobs_suppressed_with_expiry(
        self, db_session, user_id, monkeypatch, caplog
    ):
        """(2/3) fail-before: a tick that skips every eligible job purely due
        to cover-failure suppression must log an explicit, actionable line —
        not the old healthy-looking 'skipped-failures (processed=0 ...)' —
        including the earliest time the suppression naturally clears."""
        bad = _seed_job(db_session, user_id, fit=95.0)
        for minutes_ago in (120, 110, 100):
            self._seed_cover_run(db_session, user_id, bad, "failed", minutes_ago)
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda *a, **k: pytest.fail("saturated job must not be attempted"),
        )
        caplog.set_level(logging.INFO, logger="app.workers.board_sweep")
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert summary["reason"] == "skipped-failures"
        assert summary["processed"] == 0
        expiry = summary.get("suppression_expiry")
        assert expiry, "summary must carry a computed suppression_expiry"
        assert "failure-suppressed until" in caplog.text, caplog.text
        assert expiry in caplog.text, caplog.text


class TestOpsClearScript:
    """ML-W-12 (3/3): ``scripts/clear_cover_suppression.py`` is the ops
    escape hatch for jobs wedged by a NOW-FIXED pipeline defect. Exercised
    exactly as ops would invoke it (subprocess, real CLI args) against the
    live test DB — not just its importable functions — so the dry-run/
    real-run/idempotency contract is verified end-to-end.
    """

    def _run_script(self, *args: str) -> subprocess.CompletedProcess:
        api_dir = Path(__file__).resolve().parent.parent
        return subprocess.run(
            [sys.executable, "scripts/clear_cover_suppression.py", *args],
            cwd=str(api_dir),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            timeout=30,
        )

    def test_dry_run_reports_then_real_run_clears_and_reeligibilises(
        self, db_session, user_id
    ):
        job = _seed_job(db_session, user_id, fit=80.0)
        with db_session.cursor() as cur:
            for _ in range(board_sweep.MAX_COVER_FAILURES):
                run_id = "c" + uuid.uuid4().hex[:24]
                cur.execute(
                    'INSERT INTO "AgentRun" '
                    '("id","userId","agentName","status","input","createdAt","startedAt") '
                    "VALUES (%s,%s,'coverLetter','failed'::\"AgentRunStatus\",%s,NOW(),NOW())",
                    (run_id, user_id, json.dumps({"job_id": job})),
                )
        db_session.commit()
        # Confirm the job is genuinely wedged before touching the script.
        assert board_sweep._next_target(user_id, set()) is None

        dry = self._run_script("--dry-run", "--user-id", user_id)
        assert dry.returncode == 0, dry.stderr
        assert job in dry.stdout
        assert "Dry run" in dry.stdout
        # Dry run must not have modified anything.
        assert board_sweep._next_target(user_id, set()) is None

        real = self._run_script("--user-id", user_id)
        assert real.returncode == 0, real.stderr
        assert "Cleared 1 job" in real.stdout

        target = board_sweep._next_target(user_id, set())
        assert target is not None and target["job_id"] == job

        # Idempotent: re-running finds nothing left to clear.
        again = self._run_script("--user-id", user_id)
        assert again.returncode == 0, again.stderr
        assert "No currently-suppressed jobs found" in again.stdout
