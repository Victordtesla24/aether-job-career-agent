"""GAP-P7-ASYNC-001 — billing-integrity concurrency tests (reviewer re-fix).

The adversarial review (uat/reports/evidence/phase7/review-async.json) found 4
billing-integrity defects in the refund/concurrency path that the original 13
tests miss because none exercise concurrency. These tests encode the fixed
contract and FAIL against the pre-fix code (fail-before), PASS after:

- BLOCKING-1: two concurrent watchdog firings on one reserved job must refund the
  reservation EXACTLY once (atomic claim-and-refund, not SELECT-then-two-UPDATEs).
- BLOCKING-2: a lazy/cron watchdog that already marked a job failed+refunded must
  NOT be resurrected to completed by a slow-but-alive worker (status-guarded,
  first-terminal-wins), and no free run / un-refund results.
- BLOCKING-3: a mid-pipeline-crash refund must refund ONLY this job's own
  outstanding reservations (tracked on the BackgroundJob row), never a user-wide
  runsUsed delta that would steal quota from a concurrent same-user run.
- BLOCKING-4: BackgroundJob's advisory-lock id must not collide with db.py's.

Redis-free: refunds/transitions are exercised directly through the repository +
``_apply_stale_watchdog`` and by invoking ``run_agent_job`` with a stubbed body.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid

import pytest

from app.db import get_connection, new_id
from app.repositories.billing import UsageQuotaRepository, ensure_user_billing


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def bg_table(client):
    """Ensure the BackgroundJob table (incl. the additive count columns) exists
    and is empty. Depends on ``client`` so the standard per-test TRUNCATE runs
    first."""
    from app.repositories.background_jobs import _ensure_table, _reset_bg_ready_for_tests

    _reset_bg_ready_for_tests()
    _ensure_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('TRUNCATE TABLE "BackgroundJob"')
        conn.commit()
    return True


def _set_paid_plan(user_id: str) -> None:
    ensure_user_billing(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=%s,"updatedAt"=now() '
                'WHERE "userId"=%s',
                ("pro", "active", user_id),
            )
            cur.execute(
                'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=100,'
                '"updatedAt"=now() WHERE "userId"=%s',
                ("pro", user_id),
            )
        conn.commit()


def _set_runs_used(user_id: str, n: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "UsageQuota" SET "runsUsed"=%s,"updatedAt"=now() '
                'WHERE "userId"=%s',
                (n, user_id),
            )
        conn.commit()


def _runs_used(user_id: str) -> int:
    return int(UsageQuotaRepository().get_by_user(user_id)["runsUsed"])


def _seed_bg_job(
    user_id: str,
    agent_key: str,
    *,
    status: str = "enqueued",
    quota_reserved: bool = False,
    started_age_secs: int | None = None,
) -> str:
    """Insert a BackgroundJob. ``started_age_secs`` backdates startedAt/createdAt
    so the staleness watchdog treats the row as abandoned."""
    job_id = new_id()
    started = "now()" if started_age_secs is None else (
        f"now() - make_interval(secs => {int(started_age_secs)})"
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "BackgroundJob" '
                '("id","userId","agentKey","status","quotaReserved","quotaReservedAt",'
                f'"startedAt","createdAt") VALUES (%s,%s,%s,%s,%s,'
                "CASE WHEN %s THEN now() ELSE NULL END,"
                f"{started},{started})",
                (job_id, user_id, agent_key, status, quota_reserved, quota_reserved),
            )
        conn.commit()
    return job_id


def _get_bg_job(job_id: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","status","result","error","quotaReservedCount",'
                '"quotaRefundedCount","quotaRefundedAt" FROM "BackgroundJob" '
                'WHERE "id"=%s',
                (job_id,),
            )
            row = cur.fetchone()
            cols = [c.name for c in cur.description]
    assert row is not None, f"BackgroundJob {job_id} not found"
    rec = dict(zip(cols, row))
    if isinstance(rec.get("result"), str):
        rec["result"] = json.loads(rec["result"])
    return rec


# ===========================================================================
# BLOCKING-1: concurrent watchdog refunds decrement the reservation exactly once
# ===========================================================================


def test_concurrent_watchdog_refunds_decrement_reservation_once(
    client, auth_headers, test_user_id, bg_table
):
    from app.repositories.background_jobs import BackgroundJobRepository
    from app.routers.agents import _apply_stale_watchdog

    _set_paid_plan(test_user_id)
    # runsUsed=3 == this job's 1 reservation + 2 unrelated concurrent runs. A
    # correct single refund lands on 2; a double-refund lands on 1 (the GREATEST
    # floor cannot mask it because we start above 1).
    _set_runs_used(test_user_id, 3)
    job_id = _seed_bg_job(
        test_user_id, "tailor", status="processing", quota_reserved=True,
        started_age_secs=1200,
    )
    repo = BackgroundJobRepository()
    # Two concurrent pollers (e.g. two browser tabs) both read the SAME pre-write
    # stale snapshot, then both act — the exact TOCTOU the fix must defeat.
    snap = repo.get_for_user(job_id, test_user_id)
    _apply_stale_watchdog(dict(snap), repo)  # caller 1
    _apply_stale_watchdog(dict(snap), repo)  # caller 2 (same stale snapshot)

    assert _runs_used(test_user_id) == 2  # refunded EXACTLY once (never 3 -> 1)
    assert _get_bg_job(job_id)["status"] == "failed"


# ===========================================================================
# BLOCKING-2: watchdog-failed job is not resurrected by a slow worker
# ===========================================================================


def test_watchdog_fail_then_slow_worker_complete_stays_failed(
    client, auth_headers, test_user_id, bg_table
):
    from app.repositories.background_jobs import BackgroundJobRepository
    from app.routers.agents import _apply_stale_watchdog

    _set_paid_plan(test_user_id)
    _set_runs_used(test_user_id, 1)  # this job's reservation
    job_id = _seed_bg_job(
        test_user_id, "tailor", status="processing", quota_reserved=True,
        started_age_secs=1200,
    )
    repo = BackgroundJobRepository()

    # Watchdog fails + refunds the stale job.
    _apply_stale_watchdog(repo.get_for_user(job_id, test_user_id), repo)
    assert _get_bg_job(job_id)["status"] == "failed"
    assert _runs_used(test_user_id) == 0

    # The slow-but-alive worker finishes LATER and tries to complete the job.
    won = repo.mark_completed(job_id, {"resume_id": "late-result"})
    assert won is False  # cannot resurrect a terminal job (first-terminal-wins)

    row = _get_bg_job(job_id)
    assert row["status"] == "failed"        # stays failed
    assert row["result"] is None            # completed result never surfaced
    assert _runs_used(test_user_id) == 0    # refund stays exactly one; no free run


# ===========================================================================
# BLOCKING-3: pipeline crash refund is scoped to THIS job, not a user-wide delta
# ===========================================================================


def test_pipeline_partial_refund_scoped_under_concurrent_same_user(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    from app.repositories.background_jobs import BackgroundJobRepository
    from app.workers import tasks as wtasks
    from app.workers.tasks import run_agent_job

    _set_paid_plan(test_user_id)
    # Unrelated concurrent run B for the same user: reserved 1 and completed.
    UsageQuotaRepository().reserve(test_user_id)  # runsUsed = 1 (B)
    job_id = _seed_bg_job(test_user_id, "pipeline", status="enqueued")

    def _crashing_body(user_id, params):
        # Job A's metered step reserves 1 (runsUsed=2) and records it on THIS job.
        UsageQuotaRepository().reserve(user_id)
        BackgroundJobRepository().increment_reserved(job_id)
        # A DIFFERENT concurrent same-user run C reserves 1 and completes (stays).
        UsageQuotaRepository().reserve(user_id)  # runsUsed = 3 (C)
        raise RuntimeError("crash after A reserved, with B and C concurrently active")

    monkeypatch.setattr(wtasks, "_run_pipeline_body", _crashing_body, raising=True)
    asyncio.run(run_agent_job({}, job_id))

    # Only A's OWN single reservation is refunded: 3 -> 2. B's and C's runs (which
    # A must never touch) stay charged.
    assert _runs_used(test_user_id) == 2
    assert _get_bg_job(job_id)["status"] == "failed"

    # Idempotent: re-refunding A's outstanding is a no-op (outstanding now 0).
    BackgroundJobRepository().refund_pipeline_outstanding(job_id)
    assert _runs_used(test_user_id) == 2


# ===========================================================================
# BLOCKING-4: BackgroundJob advisory-lock id is distinct (no db.py collision)
# ===========================================================================


def test_background_job_advisory_lock_id_distinct():
    import inspect

    import app.db as dbmod
    from app.repositories.admin import _ADMIN_LOCK
    from app.repositories.background_jobs import _BACKGROUND_JOB_LOCK
    from app.repositories.billing import _BILLING_LOCK

    db_ids = {
        int(x)
        for x in re.findall(
            r'pg_advisory_xact_lock\(%s\)",\s*\((\d+),', inspect.getsource(dbmod)
        )
    }
    assert db_ids, "expected to find advisory-lock ids in app.db"
    assert _BACKGROUND_JOB_LOCK not in db_ids, (
        f"BackgroundJob lock {_BACKGROUND_JOB_LOCK} collides with db.py {db_ids}"
    )
    assert _BACKGROUND_JOB_LOCK != _BILLING_LOCK
    assert _BACKGROUND_JOB_LOCK != _ADMIN_LOCK
