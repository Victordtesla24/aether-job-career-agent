"""ML-W-19 / ML-W-20 — board-sweep cover-failure suppression + continuation honesty.

Evidence: ``uat/reports/evidence/prod-verify-3/PROD-VERIFY-3.json`` and
``uat/reports/evidence/prod-verify-3/item2-autopilot-ticks.txt`` (live
production, build A9oWykjgwicZnpi434scd / git 26cea22, 2026-07-29T17:00-17:26Z).

W-19 (CRITICAL) — the cover-failure suppression is dead code for the DOMINANT
failure mode. A fabrication/structural guard rejection is recorded as an
``AgentRun`` with ``status='completed'`` and ``output.coverLetterUnavailable =
true`` (GAP-P4-002: the guard WORKING is not a failure), but the suppression
counted only ``status='failed'`` AND floored its 24h window at the last
``status='completed'`` run — so each degraded run simultaneously (a) failed to
increment the counter and (b) reset the floor past every earlier real failure.
Measured live: 4 jobs × 76 letterless runs each in the trailing 24h, every one
of them reporting ``effective_failure_count = 0``; 453 letterless runs vs 1
real letter; two consecutive ticks byte-for-byte identical. The autopilot
retried forever, burning real paid tokens.

W-20 (HIGH) — ``board_sweep_user`` logged "re-enqueued continuation" without
checking ``enqueue_job``'s return value. arq returns ``None`` when a job with
that id already exists (its own still-running job key, then its retained
result key), so the continuation NEVER happened while the log claimed it did —
a silent 17:08→17:20 idle window observed live.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from app.workers import board_sweep

# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(conn, user_id: str, *, status: str = "screening",
              fit: float | None = 80.0, title: str = "Engineer") -> str:
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


def _seed_cover_run(conn, user_id: str, job_id: str, *, status: str,
                    output: dict | None = None, minutes_ago: float = 0.0) -> str:
    """Seed one coverLetter ``AgentRun`` with an explicit status, output JSONB
    and age. ``minutes_ago`` keeps failure/success ordering deterministic
    regardless of statement timing."""
    run_id = _uid()
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
    return run_id


def _degraded_output(*, camel: bool = True) -> dict:
    """The EXACT honest-degrade JSONB shape production writes.

    camelCase: ``app/routers/agents.py`` (guard-rejection degrade) and
    ``app/workers/tasks.py`` (async worker). snake_case: the
    ``CoverLetterResult`` dataclass field ``cover_letter_unavailable`` that
    ``asdict()`` puts on the run output for the LLM-unavailable-on-first-draft
    degrade (ML-cover-002)."""
    key = "coverLetterUnavailable" if camel else "cover_letter_unavailable"
    return {
        "cover_letter_id": None,
        key: True,
        "reason": "['onboarding']",
        "message": (
            "An auto-generated cover letter couldn't be produced without "
            "unverifiable wording, so it was withheld."
        ),
    }


def _success_output(*, camel: bool = False) -> dict:
    """The EXACT shape a GENUINE success writes (``asdict(CoverLetterResult)``
    via ``_dispatch``): a real ``cover_letter_id`` and the degrade flag false."""
    key = "coverLetterId" if camel else "cover_letter_id"
    return {
        key: _uid(),
        "cover_letter": "Dear Hiring Manager, ...",
        "approval_id": _uid(),
        "approval_status": "pending",
        "flagged": [],
        "cover_letter_unavailable": False,
    }


def _stamp_cleared(conn, job_id: str) -> None:
    from app.db import ensure_job_cover_suppression_column

    ensure_job_cover_suppression_column()
    with conn.cursor() as cur:
        cur.execute('UPDATE "Job" SET "coverFailureClearedAt" = NOW() WHERE "id" = %s',
                    (job_id,))
    conn.commit()


def _far_deadline() -> float:
    return time.monotonic() + 3600.0


# ---------------------------------------------------------------------------
# W-19 — the suppression predicate
# ---------------------------------------------------------------------------


class TestDegradedRunsCountAsCoverFailures:
    """W-19(a): a guard-rejected / letterless ``completed`` run produced NO
    letter, so it MUST count toward the cover-failure backoff exactly like a
    ``failed`` run. Before this fix each one counted zero."""

    def test_degraded_completed_runs_count_and_suppress(self, db_session, user_id):
        job = _seed_job(db_session, user_id, fit=80.0)
        for minutes_ago in (30, 20, 10):
            _seed_cover_run(db_session, user_id, job, status="completed",
                            output=_degraded_output(), minutes_ago=minutes_ago)

        assert board_sweep._cover_failure_count(user_id, job) == 3
        assert board_sweep._next_target(user_id, set()) is None
        assert board_sweep._saturated_job_ids(user_id, set()) == [job]

    def test_snake_case_degrade_flag_counts_too(self, db_session, user_id):
        """``asdict(CoverLetterResult)`` writes the snake_case flag on the
        LLM-unavailable-first-draft degrade — the same letterless outcome."""
        job = _seed_job(db_session, user_id, fit=80.0)
        for minutes_ago in (30, 20, 10):
            _seed_cover_run(db_session, user_id, job, status="completed",
                            output=_degraded_output(camel=False),
                            minutes_ago=minutes_ago)

        assert board_sweep._cover_failure_count(user_id, job) == 3
        assert board_sweep._next_target(user_id, set()) is None

    def test_degraded_run_does_not_reset_the_floor(self, db_session, user_id):
        """W-19(b): a degraded ``completed`` run must neither clear the counter
        nor erase EARLIER failures. Before the fix it did both."""
        job = _seed_job(db_session, user_id, fit=80.0)
        _seed_cover_run(db_session, user_id, job, status="failed", minutes_ago=180)
        _seed_cover_run(db_session, user_id, job, status="failed", minutes_ago=170)
        _seed_cover_run(db_session, user_id, job, status="completed",
                        output=_degraded_output(), minutes_ago=90)

        assert board_sweep._cover_failure_count(user_id, job) == 3
        assert board_sweep._next_target(user_id, set()) is None

    def test_ordinary_completed_run_without_a_letter_is_neutral(self, db_session, user_id):
        """A ``completed`` coverLetter run carrying NEITHER the degrade flag
        nor a letter id (legacy/partial audit rows) must not be invented into
        a failure — only the explicit honest-degrade signal counts."""
        job = _seed_job(db_session, user_id, fit=80.0)
        for minutes_ago in (30, 20, 10):
            _seed_cover_run(db_session, user_id, job, status="completed",
                            output={"duration_ms": 1200}, minutes_ago=minutes_ago)

        assert board_sweep._cover_failure_count(user_id, job) == 0
        target = board_sweep._next_target(user_id, set())
        assert target is not None and target["job_id"] == job


class TestOnlyGenuineSuccessClears:
    """W-19(b): the 24h window floors ONLY on a run that genuinely produced a
    letter (non-null ``cover_letter_id``/``coverLetterId``) or on the ops
    ``Job.coverFailureClearedAt`` stamp."""

    def test_genuine_success_clears_degraded_failures(self, db_session, user_id):
        job = _seed_job(db_session, user_id, fit=80.0)
        for minutes_ago in (180, 170, 160):
            _seed_cover_run(db_session, user_id, job, status="completed",
                            output=_degraded_output(), minutes_ago=minutes_ago)
        _seed_cover_run(db_session, user_id, job, status="completed",
                        output=_success_output(), minutes_ago=90)

        assert board_sweep._cover_failure_count(user_id, job) == 0
        target = board_sweep._next_target(user_id, set())
        assert target is not None and target["job_id"] == job

    def test_camel_case_letter_id_also_clears(self, db_session, user_id):
        job = _seed_job(db_session, user_id, fit=80.0)
        for minutes_ago in (180, 170, 160):
            _seed_cover_run(db_session, user_id, job, status="failed",
                            minutes_ago=minutes_ago)
        _seed_cover_run(db_session, user_id, job, status="completed",
                        output=_success_output(camel=True), minutes_ago=90)

        assert board_sweep._cover_failure_count(user_id, job) == 0

    def test_ops_clear_stamp_clears_degraded_failures(self, db_session, user_id):
        job = _seed_job(db_session, user_id, fit=80.0)
        for minutes_ago in (30, 20, 10):
            _seed_cover_run(db_session, user_id, job, status="completed",
                            output=_degraded_output(), minutes_ago=minutes_ago)
        assert board_sweep._next_target(user_id, set()) is None

        _stamp_cleared(db_session, job)

        assert board_sweep._cover_failure_count(user_id, job) == 0
        target = board_sweep._next_target(user_id, set())
        assert target is not None and target["job_id"] == job


class TestSuppressionExpiryMathWithDegradedRuns:
    """W-19 + ML-W-12 coherence: the honest "failure-suppressed until <time>"
    tick log must compute its expiry from the SAME predicate, so degraded
    runs both trigger the log and set its clock."""

    def _created_at(self, conn, run_id: str):
        with conn.cursor() as cur:
            cur.execute('SELECT "createdAt" FROM "AgentRun" WHERE "id" = %s', (run_id,))
            return cur.fetchone()[0]

    def test_expiry_is_the_oldest_of_the_limit_most_recent_degrades(
        self, db_session, user_id
    ):
        from datetime import timedelta

        job = _seed_job(db_session, user_id, fit=80.0)
        # 4 degraded runs; with limit=3 the clock is set by the SECOND-oldest
        # (the oldest of the 3 most recent) ageing out of the 24h window.
        _seed_cover_run(db_session, user_id, job, status="completed",
                        output=_degraded_output(), minutes_ago=200)
        pivot = _seed_cover_run(db_session, user_id, job, status="completed",
                                output=_degraded_output(), minutes_ago=150)
        for minutes_ago in (100, 50):
            _seed_cover_run(db_session, user_id, job, status="completed",
                            output=_degraded_output(), minutes_ago=minutes_ago)

        expected = self._created_at(db_session, pivot) + timedelta(
            hours=board_sweep.cover_failure_window_hours()
        )
        assert board_sweep._job_suppression_expiry(user_id, job) == expected
        assert board_sweep._earliest_suppression_expiry(user_id, [job]) == (
            expected.replace(microsecond=0).isoformat()
        )

    def test_tick_log_names_degraded_suppression_with_expiry(
        self, db_session, user_id, monkeypatch, caplog
    ):
        job = _seed_job(db_session, user_id, fit=95.0)
        for minutes_ago in (120, 110, 100):
            _seed_cover_run(db_session, user_id, job, status="completed",
                            output=_degraded_output(), minutes_ago=minutes_ago)
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda *a, **k: pytest.fail("suppressed job must not be attempted"),
        )
        caplog.set_level(logging.INFO, logger="app.workers.board_sweep")
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert summary["reason"] == "skipped-failures"
        assert summary["skipped_failures"] == 1
        assert summary["processed"] == 0
        expiry = summary.get("suppression_expiry")
        assert expiry, "summary must carry a computed suppression_expiry"
        assert "failure-suppressed until" in caplog.text, caplog.text
        assert expiry in caplog.text, caplog.text


class TestStretchSummaryDoesNotClaimADegradedCover:
    """W-19(a), third site: the in-stretch counters must use the SAME
    predicate. A cover run that returns the honest degrade produced NO letter,
    so counting it as ``covers`` would claim a letter that does not exist."""

    def test_degraded_cover_return_counts_as_failure_not_cover(
        self, db_session, user_id, monkeypatch, caplog
    ):
        job = _seed_job(db_session, user_id, fit=80.0)

        def _fake_run(uid, agent, params):
            if agent == "coverLetter":
                return {"cover_letter_id": None, "coverLetterUnavailable": True}
            return {}

        monkeypatch.setattr(board_sweep, "_run_agent", _fake_run)
        caplog.set_level(logging.INFO, logger="app.workers.board_sweep")
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert summary["tailored"] == 1
        assert summary["covers"] == 0
        assert summary["processed"] == 0
        assert summary["failures"] == 1
        assert job in caplog.text

    def test_real_cover_return_still_counts_as_a_cover(
        self, db_session, user_id, monkeypatch
    ):
        _seed_job(db_session, user_id, fit=80.0)
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda uid, agent, params: (
                _success_output() if agent == "coverLetter" else {}
            ),
        )
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert summary["covers"] == 1
        assert summary["processed"] == 1
        assert summary["failures"] == 0


class TestOpsScriptPredicateStaysInLockstep:
    """W-19 + ML-W-12: ``scripts/clear_cover_suppression.py`` duplicates the
    suppression predicate by design (zero import-time side effects). Both
    files document that the duplicate must be updated in lockstep — this test
    is the enforcement: the script must find a job suppressed by DEGRADED
    runs, exactly as ``_saturated_job_ids`` does."""

    def _run_script(self, *args: str) -> subprocess.CompletedProcess:
        api_dir = Path(__file__).resolve().parent.parent
        return subprocess.run(
            [sys.executable, "scripts/clear_cover_suppression.py", *args],
            cwd=str(api_dir), capture_output=True, text=True,
            env=os.environ.copy(), timeout=30,
        )

    def test_script_sees_degraded_suppression_and_clears_it(self, db_session, user_id):
        job = _seed_job(db_session, user_id, fit=80.0)
        for minutes_ago in (30, 20, 10):
            _seed_cover_run(db_session, user_id, job, status="completed",
                            output=_degraded_output(), minutes_ago=minutes_ago)
        assert board_sweep._next_target(user_id, set()) is None

        dry = self._run_script("--dry-run", "--user-id", user_id)
        assert dry.returncode == 0, dry.stderr
        assert job in dry.stdout, dry.stdout
        assert board_sweep._next_target(user_id, set()) is None

        real = self._run_script("--user-id", user_id)
        assert real.returncode == 0, real.stderr
        assert "Cleared 1 job" in real.stdout, real.stdout

        target = board_sweep._next_target(user_id, set())
        assert target is not None and target["job_id"] == job

    def test_script_ignores_a_job_cleared_by_a_genuine_letter(
        self, db_session, user_id
    ):
        """A job whose degrades were followed by a REAL letter is not
        suppressed, so the ops script must leave it alone."""
        job = _seed_job(db_session, user_id, fit=80.0)
        for minutes_ago in (180, 170, 160):
            _seed_cover_run(db_session, user_id, job, status="completed",
                            output=_degraded_output(), minutes_ago=minutes_ago)
        _seed_cover_run(db_session, user_id, job, status="completed",
                        output=_success_output(), minutes_ago=90)

        out = self._run_script("--dry-run", "--user-id", user_id)
        assert out.returncode == 0, out.stderr
        assert "No currently-suppressed jobs found" in out.stdout, out.stdout


# ---------------------------------------------------------------------------
# W-20 — continuation enqueue honesty
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Models arq's ``enqueue_job`` contract: returns the Job, or ``None``
    when a job with that id already exists (arq/connections.py — see the
    semantics pin below)."""

    def __init__(self, result: object | None) -> None:
        self.result = result
        self.calls: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, fn: str, *args, **kwargs):
        self.calls.append((fn, args, kwargs))
        return self.result


def _canned_summary(**over) -> dict:
    summary = {
        "user_id": "u", "processed": 3, "tailored": 3, "covers": 3,
        "failures": 0, "reason": "deadline", "skipped_failures": 0,
        "needs_continuation": True,
    }
    summary.update(over)
    return summary


class TestContinuationEnqueueHonesty:
    def test_arq_returns_none_for_a_duplicate_job_id(self):
        """Semantics pin (proof for the design choice below): arq refuses an
        enqueue whose ``_job_id`` already has a job key OR a retained result
        key, returning ``None``. A job that re-enqueues ITSELF under its own
        id is therefore ALWAYS refused — its own job key is still present.
        Read from the INSTALLED arq so an upgrade that changes this fails
        here rather than silently in production."""
        from arq.connections import ArqRedis

        src = inspect.getsource(ArqRedis.enqueue_job)
        assert "if await pipe.exists(job_key, result_key_prefix + job_id):" in src
        assert "return None" in src
        assert "None`` if a job with this ID already exists" in (
            ArqRedis.enqueue_job.__doc__ or ""
        )

    def test_dedup_refusal_is_logged_honestly(self, monkeypatch, caplog):
        """W-20 fail-before: a refused enqueue used to log 're-enqueued
        continuation' — a claim the evidence disproves (17:08→17:20 idle)."""
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")
        monkeypatch.setattr(board_sweep, "sweep_user_stretch",
                            lambda uid: _canned_summary())
        redis = _FakeRedis(None)
        caplog.set_level(logging.INFO, logger="app.workers.board_sweep")

        summary = asyncio.run(board_sweep.board_sweep_user({"redis": redis}, "u1"))

        assert len(redis.calls) == 1
        assert "re-enqueued continuation" not in caplog.text, caplog.text
        assert "continuation refused (dedup)" in caplog.text, caplog.text
        assert "next cron tick will resume" in caplog.text, caplog.text
        assert summary["continuation_enqueued"] is False

    def test_accepted_enqueue_is_logged_as_enqueued(self, monkeypatch, caplog):
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")
        monkeypatch.setattr(board_sweep, "sweep_user_stretch",
                            lambda uid: _canned_summary(reason="job-cap"))
        redis = _FakeRedis(object())
        caplog.set_level(logging.INFO, logger="app.workers.board_sweep")

        summary = asyncio.run(board_sweep.board_sweep_user({"redis": redis}, "u1"))

        assert "re-enqueued continuation" in caplog.text, caplog.text
        assert "refused" not in caplog.text, caplog.text
        assert summary["continuation_enqueued"] is True

    def test_continuation_keeps_the_canonical_single_flight_job_id(
        self, monkeypatch, caplog
    ):
        """Regression pin: the continuation MUST stay on the canonical
        ``board-sweep:<uid>`` id. A unique per-continuation id would make the
        enqueue succeed, but it would also stop deduping against the 10-minute
        cron tick — stacking a SECOND concurrent stretch for the same user
        (duplicate tailoring/letters, doubled real LLM spend)."""
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")
        monkeypatch.setattr(board_sweep, "sweep_user_stretch",
                            lambda uid: _canned_summary())
        redis = _FakeRedis(None)
        caplog.set_level(logging.INFO, logger="app.workers.board_sweep")

        asyncio.run(board_sweep.board_sweep_user({"redis": redis}, "u1"))

        fn, args, kwargs = redis.calls[0]
        assert fn == "board_sweep_user" and args == ("u1",)
        assert kwargs["_job_id"] == "board-sweep:u1"

    def test_hard_stop_does_not_enqueue_anything(self, monkeypatch, caplog):
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")
        monkeypatch.setattr(
            board_sweep, "sweep_user_stretch",
            lambda uid: _canned_summary(reason="board-complete",
                                        needs_continuation=False),
        )
        redis = _FakeRedis(object())
        caplog.set_level(logging.INFO, logger="app.workers.board_sweep")

        summary = asyncio.run(board_sweep.board_sweep_user({"redis": redis}, "u1"))

        assert redis.calls == []
        assert "continuation" not in caplog.text.lower(), caplog.text
        assert "continuation_enqueued" not in summary

    def test_enqueue_exception_never_claims_a_continuation(self, monkeypatch, caplog):
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")
        monkeypatch.setattr(board_sweep, "sweep_user_stretch",
                            lambda uid: _canned_summary())

        class _BoomRedis:
            async def enqueue_job(self, *a, **k):
                raise RuntimeError("redis down")

        caplog.set_level(logging.INFO, logger="app.workers.board_sweep")
        summary = asyncio.run(board_sweep.board_sweep_user({"redis": _BoomRedis()}, "u1"))

        assert "re-enqueued continuation" not in caplog.text, caplog.text
        assert summary["continuation_enqueued"] is False
