"""RT-007 — continuous board-sweep autopilot (operator mandate 2026-07-24).

"The agents must run continuously until the board is empty or for ~10 minutes
in a stretch — users must not manually run agents, and one run must not stop
at a single tailored résumé + cover letter."

An ARQ cron tick (every 10 min, env-gated) enqueues one bounded SWEEP STRETCH
per user who has actionable board work. A stretch walks ALL eligible jobs —
not just the matcher's single top job — running tailor + cover letter for each
through the SAME reserved-run machinery the manual endpoints use
(``_dispatch`` → ``_record_run``: atomic quota reserve/refund, AgentRun audit
rows, honest 429 on plan-quota exhaustion), so autopilot work is billed,
audited, and bounded exactly like manual work, and every generated artifact
still lands behind the existing human-approval gate (pending ApprovalRequest +
draft Application) — the sweep AUTOMATES GENERATION, never submission.

Eligibility (kept consistent with RT-004 card dedup and RT-005 stage-sync):
- ``tailoring`` jobs with NO Application row → cover-only completion (a prior
  run tailored but the cover step failed/was interrupted);
- ``screening``/``matched`` jobs with a fitScore and NO Application row →
  full tailor + cover;
- a job with ANY Application row is done (its letter versions live behind one
  board card) and is never re-processed.

Bounds (all env-tunable): stretch wall-clock, jobs-per-stretch cap, one
attempt per job per stretch (failures are recorded and skipped, never
tight-looped), consecutive-LLM-outage circuit breaker, per-tick user cap,
and the plan quota itself — quota exhaustion ends the stretch honestly.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

#: Minimum wall-clock (s) that must remain in the stretch before STARTING a
#: full tailor+cover job / a cover-only completion. Sized so a typical step
#: (observed live: tailor 60-190s, cover 20-60s) finishes inside the ARQ
#: function timeout (900s) even when started at the threshold.
MIN_SECONDS_FULL_JOB = 240.0
MIN_SECONDS_COVER_ONLY = 120.0
#: Consecutive LLM-unavailable failures that abort the stretch (systemic
#: outage — retrying more jobs would burn attempts for nothing).
LLM_OUTAGE_BREAKER = 3
#: Maximum coverLetter failures per job within the failure window before the
#: sweep PERMANENTLY skips that job for the rest of the window. Without this,
#: a job whose cover letter is permanently unfabricatable (FabricationGuard
#: correctly rejecting every attempt) gets retried every cron tick forever —
#: 13+ failed attempts over 14h observed in production. The FabricationGuard
#: is working AS DESIGNED; the bug was the sweep had no persistent backoff
#: (the per-stretch in-memory ``attempted`` set resets every tick). The window
#: ensures a transient cause (e.g. a resume update that fixes the grounding)
#: eventually re-eligibilises the job without code changes.
MAX_COVER_FAILURES = 3
COVER_FAILURE_WINDOW_HOURS = 24


def sweep_enabled() -> bool:
    """Kill-switch: ``AETHER_BOARD_SWEEP_ENABLED`` (code default OFF; the
    production ``.env`` turns it on at deploy)."""
    return os.environ.get("AETHER_BOARD_SWEEP_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def sweep_stretch_seconds() -> float:
    """Stretch wall-clock budget (default 540s ≈ the operator's ~10 minutes;
    floored at 60 so a bad value can never make stretches useless)."""
    try:
        seconds = float(os.environ.get("AETHER_BOARD_SWEEP_STRETCH_SECONDS", "540"))
    except ValueError:
        seconds = 540.0
    return max(60.0, seconds)


def sweep_max_jobs() -> int:
    """Jobs processed per stretch cap (default 10)."""
    try:
        return max(1, int(os.environ.get("AETHER_BOARD_SWEEP_MAX_JOBS", "10")))
    except (TypeError, ValueError):
        return 10


def sweep_user_cap() -> int:
    """Users enqueued per cron tick cap (default 20)."""
    try:
        return max(1, int(os.environ.get("AETHER_BOARD_SWEEP_MAX_USERS", "20")))
    except (TypeError, ValueError):
        return 20


def max_cover_failures() -> int:
    """Max coverLetter failures per job before the sweep skips it (default 3).

    Env-tunable so an operator can tighten or loosen the backoff without a
    redeploy: ``AETHER_BOARD_SWEEP_MAX_COVER_FAILURES``.
    """
    try:
        return max(1, int(os.environ.get("AETHER_BOARD_SWEEP_MAX_COVER_FAILURES",
                                          str(MAX_COVER_FAILURES))))
    except (TypeError, ValueError):
        return MAX_COVER_FAILURES


def cover_failure_window_hours() -> int:
    """Sliding window (hours) for counting coverLetter failures (default 24).

    Env-tunable: ``AETHER_BOARD_SWEEP_COVER_FAILURE_WINDOW_HOURS``. A job
    failure-saturated inside the window is skipped; once the oldest failure
    ages past the window the job re-eligibilises (transient-cause tolerance).
    """
    try:
        return max(1, int(os.environ.get(
            "AETHER_BOARD_SWEEP_COVER_FAILURE_WINDOW_HOURS",
            str(COVER_FAILURE_WINDOW_HOURS))))
    except (TypeError, ValueError):
        return COVER_FAILURE_WINDOW_HOURS


def eligible_users(limit: int | None = None) -> list[str]:
    """User ids with actionable board work, oldest-touched first."""
    from app.db import get_connection

    limit = limit or sweep_user_cap()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT j."userId", MIN(j."updatedAt") AS oldest
                FROM "Job" j
                WHERE (
                        (j."status" = 'tailoring')
                     OR (j."status" IN ('screening','matched')
                         AND j."fitScore" IS NOT NULL)
                      )
                  AND j."status" NOT IN ('applied','archived')
                  AND NOT EXISTS (
                        SELECT 1 FROM "Application" a
                        WHERE a."jobId" = j."id" AND a."userId" = j."userId"
                      )
                GROUP BY j."userId"
                ORDER BY oldest ASC
                LIMIT %s
                ''',
                (limit,),
            )
            return [row[0] for row in cur.fetchall()]


def _cover_failure_count(user_id: str, job_id: str) -> int:
    """Count failed coverLetter AgentRuns for this user+job inside the
    failure window. Used by ``_next_target``'s SQL (correlated subquery) and
    exposed standalone for observability/tests.

    A job is PERMANENTLY skipped once this reaches ``max_cover_failures()``
    inside the window — the FabricationGuard is correctly rejecting every
    cover draft (e.g. the resume never proves 'onboarding' experience the
    LLM keeps first-person-claiming from the job title 'Onboarding PM'), and
    retrying every cron tick forever wastes LLM budget and looks like a stuck
    agent to the user.
    """
    from app.db import get_connection

    window = cover_failure_window_hours()
    limit = max_cover_failures()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT count(*) FROM "AgentRun"
                WHERE "userId" = %s
                  AND "agentName" = 'coverLetter'
                  AND "status" = 'failed'
                  AND "createdAt" >= NOW() - INTERVAL '%s hours'
                  AND ("input"->>'job_id') = %s
                ''',
                (user_id, window, job_id),
            )
            row = cur.fetchone()
    return row[0] if row else 0


def _saturated_job_count(user_id: str, attempted: set[str]) -> int:
    """Count eligible jobs that are CURRENTLY skipped solely due to the cover
    failure backoff (they have ``max_cover_failures()``+ coverLetter failures
    in the window but no Application yet). Used to distinguish "board truly
    complete" (``board-complete``) from "all remaining jobs are failure-
    saturated" (``skipped-failures``) in the stretch summary — the latter
    tells the operator the sweep is NOT done, it's backing off.
    """
    from app.db import get_connection

    window = cover_failure_window_hours()
    limit = max_cover_failures()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT count(*) FROM "Job" j
                WHERE j."userId" = %s
                  AND j."id" != ALL(%s)
                  AND (
                        (j."status" = 'tailoring')
                     OR (j."status" IN ('screening','matched')
                         AND j."fitScore" IS NOT NULL)
                      )
                  AND j."status" NOT IN ('applied','archived')
                  AND NOT EXISTS (
                        SELECT 1 FROM "Application" a
                        WHERE a."jobId" = j."id" AND a."userId" = j."userId"
                      )
                  AND (
                        SELECT count(*) FROM "AgentRun" r
                        WHERE r."userId" = %s
                          AND r."agentName" = 'coverLetter'
                          AND r."status" = 'failed'
                          AND r."createdAt" >= NOW() - INTERVAL '%s hours'
                          AND (r."input"->>'job_id') = j."id"
                      ) >= %s
                ''',
                (user_id, list(attempted) or ["-"], user_id, window, limit),
            )
            row = cur.fetchone()
    return row[0] if row else 0


def _next_target(user_id: str, attempted: set[str]) -> dict[str, str] | None:
    """The next job to process: cover-only completions first (finish work a
    prior stretch started), then full runs by fitScore descending.

    Jobs that have ``max_cover_failures()``+ coverLetter AgentRun failures
    inside the ``cover_failure_window_hours()`` sliding window are PERMANENTLY
    excluded — the sweep no longer retries a permanently unfabricatable job
    every cron tick (13+ failed attempts over 14h observed in production before
    this fix). The guard's rejections are correct; the bug was the sweep had
    no persistent backoff (the per-stretch in-memory ``attempted`` set resets
    every tick). Once the oldest failure ages past the window a transient
    cause (e.g. a resume update) re-eligibilises the job without code changes.
    """
    from app.db import get_connection

    window = cover_failure_window_hours()
    limit = max_cover_failures()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT j."id", j."status" FROM "Job" j
                WHERE j."userId" = %s
                  AND j."id" != ALL(%s)
                  AND (
                        (j."status" = 'tailoring')
                     OR (j."status" IN ('screening','matched')
                         AND j."fitScore" IS NOT NULL)
                      )
                  AND j."status" NOT IN ('applied','archived')
                  AND NOT EXISTS (
                        SELECT 1 FROM "Application" a
                        WHERE a."jobId" = j."id" AND a."userId" = j."userId"
                      )
                  AND (
                        SELECT count(*) FROM "AgentRun" r
                        WHERE r."userId" = %s
                          AND r."agentName" = 'coverLetter'
                          AND r."status" = 'failed'
                          AND r."createdAt" >= NOW() - INTERVAL '%s hours'
                          AND (r."input"->>'job_id') = j."id"
                      ) < %s
                ORDER BY (j."status" = 'tailoring') DESC, j."fitScore" DESC NULLS LAST,
                         j."createdAt" ASC
                LIMIT 1
                ''',
                (user_id, list(attempted) or ["-"], user_id, window, limit),
            )
            row = cur.fetchone()
    if row is None:
        return None
    job_id, job_status = row
    return {
        "job_id": job_id,
        "mode": "cover_only" if job_status == "tailoring" else "full",
    }


def _run_agent(user_id: str, agent_key: str, params: dict[str, Any]) -> dict[str, Any]:
    """One reserved, budgeted agent run — the exact machinery manual runs use.

    Module-level seam (tests monkeypatch it) wrapping the router ``_dispatch``
    in the worker-tier LLM budget, mirroring ``_wrap_worker_budget``.

    Board sweep is an AUTOMATED system operation — it passes ``system_run=True``
    to skip the paywall gate and ``skip_quota=True`` so the plan-quota reserve
    is skipped. The user's paid quota must NOT be consumed by automated
    infrastructure. The audit row is still stamped ``systemRun: true`` so the
    exemption is honestly traceable.
    """
    from app.routers.agents import _dispatch
    from app.services.llm_client import (
        get_worker_budget_seconds,
        get_worker_cover_budget_seconds,
        shared_budget,
    )

    seconds = (
        get_worker_cover_budget_seconds()
        if agent_key == "coverLetter"
        else get_worker_budget_seconds()
    )
    with shared_budget(seconds):
        return _dispatch(user_id, agent_key, params, system_run=True, skip_quota=True)


def sweep_user_stretch(
    user_id: str,
    *,
    deadline: float | None = None,
    max_jobs: int | None = None,
) -> dict[str, Any]:
    """One bounded sweep stretch for one user. Returns an honest summary."""
    from fastapi import HTTPException

    from app.agents.cover_letter_agent import FabricationError, StructuralError
    from app.agents.tailor_agent import NoChangesApplied
    from app.services.llm_client import LLMUnavailableError, QuotaExhaustedError
    from app.services.resume_grounding import MissingResumeError

    deadline = deadline if deadline is not None else time.monotonic() + sweep_stretch_seconds()
    max_jobs = max_jobs or sweep_max_jobs()
    attempted: set[str] = set()
    summary: dict[str, Any] = {
        "user_id": user_id, "processed": 0, "tailored": 0, "covers": 0,
        "failures": 0, "reason": "board-complete",
        "skipped_failures": 0,
    }
    llm_outages = 0
    while True:
        if summary["processed"] + summary["failures"] >= max_jobs:
            summary["reason"] = "job-cap"
            break
        target = _next_target(user_id, attempted)
        if target is None:
            # Distinguish "board truly complete" from "all remaining jobs
            # are failure-saturated" — the latter means the sweep is NOT
            # done, it's backing off on permanently-failing jobs.
            saturated = _saturated_job_count(user_id, attempted)
            if saturated > 0:
                summary["reason"] = "skipped-failures"
                summary["skipped_failures"] = saturated
            else:
                summary["reason"] = "board-complete"
            break
        remaining = deadline - time.monotonic()
        needed = (
            MIN_SECONDS_COVER_ONLY
            if target["mode"] == "cover_only"
            else MIN_SECONDS_FULL_JOB
        )
        if remaining < needed:
            summary["reason"] = "deadline"
            break
        job_id = target["job_id"]
        attempted.add(job_id)
        try:
            if target["mode"] == "full":
                try:
                    _run_agent(user_id, "tailor", {"job_id": job_id})
                    summary["tailored"] += 1
                except NoChangesApplied:
                    # The guards rejected every rewrite — honest no-op, run
                    # refunded. The cover letter still proceeds from the base
                    # résumé (same degrade the manual pipeline uses).
                    pass
            _run_agent(user_id, "coverLetter", {"job_id": job_id})
            summary["covers"] += 1
            summary["processed"] += 1
            llm_outages = 0
        except MissingResumeError:
            summary["reason"] = "no-resume"
            break
        except (QuotaExhaustedError,) as exc:
            summary["reason"] = "quota-exhausted"
            logger.info("board-sweep %s: quota exhausted: %s", user_id, exc)
            break
        except HTTPException as exc:
            if exc.status_code == 429:
                summary["reason"] = "quota-exhausted"
                logger.info("board-sweep %s: plan quota 429 — stopping", user_id)
                break
            summary["failures"] += 1
            logger.warning(
                "board-sweep %s job %s: HTTP %s: %s",
                user_id, job_id, exc.status_code, exc.detail,
            )
        except (FabricationError, StructuralError) as exc:
            # The anti-fabrication/structure guard rejected the artifact — the
            # guard WORKING. Recorded + refunded by the run machinery; skip.
            summary["failures"] += 1
            logger.info("board-sweep %s job %s: guard rejection: %s", user_id, job_id, exc)
        except LLMUnavailableError as exc:
            summary["failures"] += 1
            llm_outages += 1
            logger.warning("board-sweep %s job %s: LLM unavailable: %s", user_id, job_id, exc)
            if llm_outages >= LLM_OUTAGE_BREAKER:
                summary["reason"] = "llm-unavailable"
                break
        except Exception as exc:  # noqa: BLE001 — one bad job never sinks the sweep
            summary["failures"] += 1
            logger.exception("board-sweep %s job %s: unexpected: %s", user_id, job_id, exc)
    logger.info(
        "board-sweep %s: %s (processed=%s tailored=%s covers=%s failures=%s)",
        user_id, summary["reason"], summary["processed"], summary["tailored"],
        summary["covers"], summary["failures"],
    )
    return summary


async def board_sweep_user(ctx: Any, user_id: str) -> dict[str, Any]:
    """ARQ task: run one sweep stretch for one user off the event loop."""
    import asyncio

    return await asyncio.to_thread(sweep_user_stretch, user_id)


async def board_sweep_cron(ctx: Any) -> int:
    """ARQ cron: enqueue one stretch per user with actionable board work.

    ``_job_id`` makes the enqueue idempotent while a user's stretch is queued
    or running (ARQ dedups on job id), so overlapping ticks can never stack
    concurrent sweeps for the same user.
    """
    if not sweep_enabled():
        return 0
    users = eligible_users()
    enqueued = 0
    for uid in users:
        job = await ctx["redis"].enqueue_job(
            "board_sweep_user", uid, _job_id=f"board-sweep:{uid}"
        )
        if job is not None:
            enqueued += 1
    if users:
        logger.info("board-sweep cron: %d user(s) eligible, %d enqueued", len(users), enqueued)
    return enqueued
