"""ML-W25 — QA #4 residual: in-app autopilot suppression visibility.

PRODUCTION-HARDENING-RUN-2026-07-29.md, QA closure #4 (19:25Z): "autopilot
suppression LIVE-VERIFIED (honest suppressed-until line firing...)" but the
same entry lists as OPEN/queued: "in-app autopilot suppression visibility (no
UI/API exposes it...)". The board-sweep backoff (RT-007/ML-W19,
``app.workers.board_sweep``) correctly stops retrying a job once it accrues
``max_cover_failures()`` LETTERLESS coverLetter runs in the trailing
``cover_failure_window_hours()`` — but the ONLY place that fact was visible
was a server log line. From the owner's perspective a suppressed job's
autopilot just goes quiet for up to 24h with no explanation anywhere in the
product.

This closes the residual: ``GET /jobs`` and ``GET /jobs/{id}`` now carry a
per-job ``autopilotSuppressedUntil`` (nullable ISO timestamp), computed by a
correlated subquery (RT-010 style, ``app/repositories/job.py``) that is a
THIRD mirror of the board-sweep suppression predicate — the other two being
``app/workers/board_sweep.py`` (source of truth) and
``scripts/clear_cover_suppression.py`` (ops escape hatch). This test suite
is the lockstep enforcement for the new mirror, the same role
``TestOpsScriptPredicateStaysInLockstep`` plays for the script.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest

from app.workers import board_sweep


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


def _degraded_output() -> dict:
    return {
        "cover_letter_id": None,
        "coverLetterUnavailable": True,
        "reason": "['onboarding']",
        "message": "An auto-generated cover letter couldn't be produced without "
                    "unverifiable wording, so it was withheld.",
    }


def _seed_resume(conn, user_id: str) -> str:
    resume_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash","updatedAt") '
            'VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"raw_text": "cv"}), "h"),
        )
    conn.commit()
    return resume_id


def _seed_application(conn, user_id: str, job_id: str, resume_id: str, *, status: str = "draft") -> str:
    app_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",NOW(),NOW())',
            (app_id, user_id, job_id, resume_id, status),
        )
    conn.commit()
    return app_id


def _saturate(conn, user_id: str, job_id: str) -> None:
    """Seed exactly ``max_cover_failures()`` letterless runs, oldest first."""
    limit = board_sweep.max_cover_failures()
    ages = [30 + (limit - 1 - i) * 10 for i in range(limit)]  # descending age
    for minutes_ago in ages:
        _seed_cover_run(conn, user_id, job_id, status="completed",
                        output=_degraded_output(), minutes_ago=minutes_ago)


class TestAutopilotSuppressedUntilExposed:
    """A saturated, still-eligible job carries a non-null expiry that agrees
    EXACTLY with ``board_sweep._job_suppression_expiry`` — the lockstep
    check across the third mirror."""

    def test_list_jobs_exposes_matching_expiry(self, db_session, user_id, client, auth_headers):
        job = _seed_job(db_session, user_id, status="screening", fit=80.0)
        _saturate(db_session, user_id, job)

        expected = board_sweep._job_suppression_expiry(user_id, job)
        assert expected is not None, "test setup must actually saturate the job"

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        assert row["autopilotSuppressedUntil"] is not None
        got = datetime.fromisoformat(row["autopilotSuppressedUntil"])
        assert got == expected

    def test_get_job_detail_exposes_matching_expiry(self, db_session, user_id, client, auth_headers):
        job = _seed_job(db_session, user_id, status="screening", fit=80.0)
        _saturate(db_session, user_id, job)

        expected = board_sweep._job_suppression_expiry(user_id, job)
        assert expected is not None

        row = client.get(f"/jobs/{job}", headers=auth_headers).json()
        assert row["autopilotSuppressedUntil"] is not None
        got = datetime.fromisoformat(row["autopilotSuppressedUntil"])
        assert got == expected

    def test_tailoring_status_job_also_exposed(self, db_session, user_id, client, auth_headers):
        """Cover-only completions (job stuck at ``tailoring``) are equally
        eligible for the sweep and must carry the same honest expiry."""
        job = _seed_job(db_session, user_id, status="tailoring", fit=None)
        _saturate(db_session, user_id, job)

        expected = board_sweep._job_suppression_expiry(user_id, job)
        assert expected is not None

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        got = datetime.fromisoformat(row["autopilotSuppressedUntil"])
        assert got == expected


class TestAutopilotSuppressedUntilNullWhenNotSuppressed:
    def test_clean_job_is_null(self, db_session, user_id, client, auth_headers):
        job = _seed_job(db_session, user_id, status="screening", fit=80.0)

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        assert row["autopilotSuppressedUntil"] is None

    def test_below_threshold_is_null(self, db_session, user_id, client, auth_headers):
        job = _seed_job(db_session, user_id, status="screening", fit=80.0)
        limit = board_sweep.max_cover_failures()
        for minutes_ago in range(limit - 1):
            _seed_cover_run(db_session, user_id, job, status="completed",
                            output=_degraded_output(), minutes_ago=minutes_ago * 10 + 10)

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        assert row["autopilotSuppressedUntil"] is None

    def test_genuine_success_clears_it(self, db_session, user_id, client, auth_headers):
        job = _seed_job(db_session, user_id, status="screening", fit=80.0)
        _saturate(db_session, user_id, job)
        assert board_sweep._job_suppression_expiry(user_id, job) is not None

        _seed_cover_run(db_session, user_id, job, status="completed",
                        output={"cover_letter_id": _uid(), "cover_letter_unavailable": False},
                        minutes_ago=1)

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        assert row["autopilotSuppressedUntil"] is None

    def test_ops_clear_stamp_clears_it(self, db_session, user_id, client, auth_headers):
        from app.db import ensure_job_cover_suppression_column

        job = _seed_job(db_session, user_id, status="screening", fit=80.0)
        _saturate(db_session, user_id, job)
        assert board_sweep._job_suppression_expiry(user_id, job) is not None

        ensure_job_cover_suppression_column()
        with db_session.cursor() as cur:
            cur.execute('UPDATE "Job" SET "coverFailureClearedAt" = NOW() WHERE "id" = %s', (job,))
        db_session.commit()

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        assert row["autopilotSuppressedUntil"] is None


class TestAutopilotSuppressedUntilRespectsSweepEligibility:
    """A job outside the sweep's own eligibility gate must never show a
    suppression hint, even with a qualifying letterless-run history —
    mirrors ``board_sweep._saturated_job_ids``'s WHERE clause."""

    def test_job_with_an_application_already_is_null(self, db_session, user_id, client, auth_headers):
        job = _seed_job(db_session, user_id, status="screening", fit=80.0)
        _saturate(db_session, user_id, job)
        assert board_sweep._job_suppression_expiry(user_id, job) is not None  # sweep-level: saturated

        resume = _seed_resume(db_session, user_id)
        _seed_application(db_session, user_id, job, resume, status="draft")

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        assert row["autopilotSuppressedUntil"] is None

    def test_applied_job_is_null(self, db_session, user_id, client, auth_headers):
        job = _seed_job(db_session, user_id, status="applied", fit=80.0)
        _saturate(db_session, user_id, job)

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        assert row["autopilotSuppressedUntil"] is None

    def test_archived_job_is_null(self, db_session, user_id, client, auth_headers):
        job = _seed_job(db_session, user_id, status="archived", fit=80.0)
        _saturate(db_session, user_id, job)

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        assert row["autopilotSuppressedUntil"] is None

    def test_no_fitscore_screening_job_is_null(self, db_session, user_id, client, auth_headers):
        """``screening`` with NO fitScore is not yet sweep-eligible at all
        (mirrors ``_saturated_job_ids``'s fitScore IS NOT NULL guard)."""
        job = _seed_job(db_session, user_id, status="screening", fit=None)
        _saturate(db_session, user_id, job)

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        assert row["autopilotSuppressedUntil"] is None


class TestOtherJobsUnaffected:
    def test_new_job_added_after_column_used_lazily_still_works(self, db_session, user_id, client, auth_headers):
        """Sanity: the lazy ``coverFailureClearedAt`` DDL and the new
        subquery never break an ordinary list/detail call for an unrelated
        job with no AgentRun history at all."""
        job = _seed_job(db_session, user_id, status="discovered", fit=None)

        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == job)
        assert row["autopilotSuppressedUntil"] is None
        assert row["title"] == "Engineer"

        detail = client.get(f"/jobs/{job}", headers=auth_headers).json()
        assert detail["autopilotSuppressedUntil"] is None
