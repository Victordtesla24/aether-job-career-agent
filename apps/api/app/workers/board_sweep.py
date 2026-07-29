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
from datetime import timedelta
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
#: Maximum LETTERLESS coverLetter runs per job within the failure window
#: (``_COVER_RUN_PRODUCED_NO_LETTER``) before the sweep PERMANENTLY skips that
#: job for the rest of the window. Without this, a job whose cover letter is
#: permanently unfabricatable (FabricationGuard correctly rejecting every
#: attempt) gets retried every cron tick forever — 13+ failed attempts over
#: 14h observed in production. The FabricationGuard is working AS DESIGNED;
#: the bug was the sweep had no persistent backoff (the per-stretch in-memory
#: ``attempted`` set resets every tick). The window ensures a transient cause
#: (e.g. a resume update that fixes the grounding) eventually re-eligibilises
#: the job without code changes.
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


def user_has_board_work(user_id: str) -> bool:
    """Whether this ONE user has actionable board work right now.

    The single-user variant of ``eligible_users`` — used by the event-driven
    trigger (``enqueue_user_sweep``) so a freshly-scored user is enqueued only
    when they actually have tailoring/cover work pending, not unconditionally.
    """
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT 1 FROM "Job" j
                WHERE j."userId" = %s
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
                LIMIT 1
                ''',
                (user_id,),
            )
            return cur.fetchone() is not None


def enqueue_user_sweep(user_id: str) -> str | None:
    """Event-driven trigger: enqueue one sweep stretch for this user NOW.

    Closes the latency gap the operator flagged: the discovery cron runs
    scout → fit-scorer synchronously, but the board sweep that consumes the
    freshly-scored jobs runs on a SEPARATE 10-minute ARQ cron tick — so a user
    whose jobs just landed could wait up to 10 minutes before any tailoring /
    cover work starts. This seam lets the scout + fit-scorer completion paths
    (and an explicit operator endpoint) enqueue the user's sweep immediately,
    using the SAME idempotent ``_job_id`` dedup the cron uses
    (``board-sweep:<user_id>``), so an event trigger racing the cron can NEVER
    stack a second concurrent sweep for the same user.

    Gated by ``sweep_enabled()`` (kill-switch parity with the cron) and by
    ``user_has_board_work`` (no-op when the user has nothing actionable — e.g.
    a scout that found zero new jobs, or a fit-scorer that re-scored an
    already-complete board). Returns the ARQ job id (or None when skipped /
    the enqueue was deduped against an in-flight stretch).

    Never raises on an enqueue failure: the event trigger is best-effort
    automation layered ON TOP of the cron, so a transient redis outage must
    not crash the discovery run that triggered it. The cron still fires and
    picks the user up on its next tick.
    """
    if not sweep_enabled():
        return None
    if not user_has_board_work(user_id):
        return None
    try:
        from app.workers.queue import get_arq_pool

        pool = get_arq_pool()
        import asyncio

        job = asyncio.run(
            pool.enqueue_job("board_sweep_user", user_id, _job_id=f"board-sweep:{user_id}")
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; cron is the floor
        logger.warning(
            "board-sweep event trigger %s: enqueue failed (cron will retry): %s",
            user_id, exc,
        )
        return None
    if job is None:
        logger.info(
            "board-sweep event trigger %s: deduped (stretch already queued/running)",
            user_id,
        )
        return None
    logger.info("board-sweep event trigger %s: sweep enqueued", user_id)
    return getattr(job, "job_id", None)


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


#: SQL predicate (``{run}`` = the ``AgentRun`` alias) for a coverLetter run
#: that produced NO LETTER — the thing the backoff must count.
#:
#: ML-W-19 (uat/reports/evidence/prod-verify-3/item2-autopilot-ticks.txt): the
#: DOMINANT letterless outcome is NOT ``status='failed'``. A fabrication /
#: §10.2-structural guard rejection is deliberately recorded as
#: ``status='completed'`` with ``output.coverLetterUnavailable = true``
#: (GAP-P4-002 — the guard WORKING is not a failure, and an owner-visible red
#: "failed" row for a correct refusal would be dishonest the other way). Every
#: writer of that shape — ``app/routers/agents.py`` (sync guard-rejection
#: degrade), ``app/workers/tasks.py`` (async worker) and the
#: ``CoverLetterResult.cover_letter_unavailable`` dataclass field that
#: ``asdict()`` surfaces for the LLM-unavailable-on-first-draft degrade
#: (ML-cover-002) — is matched here, in BOTH the camelCase and snake_case
#: spellings that actually reach the JSONB column.
#:
#: Counting only ``failed`` made the whole backoff dead code for that mode:
#: measured live, 4 jobs with 76 letterless runs each in the trailing 24h all
#: reported an effective failure count of ZERO, and the sweep re-attempted the
#: identical jobs every tick forever (453 letterless runs vs 1 real letter in
#: 24h), burning real paid tokens.
#:
#: Predicate discipline matches the frontend's ``coverLetterDegraded``
#: (apps/web/src/components/dashboard/feed.ts): ``=== true`` there, jsonb
#: ``= 'true'::jsonb`` here — an explicit boolean ``true``, never a truthy
#: coercion, so no unrelated output shape can be misread as a degrade.
_COVER_RUN_PRODUCED_NO_LETTER = '''
    ({run}."status" = 'failed'
     OR ({run}."status" = 'completed'
         AND ({run}."output"->'coverLetterUnavailable' = 'true'::jsonb
              OR {run}."output"->'cover_letter_unavailable' = 'true'::jsonb)))
'''

#: SQL predicate (``{run}`` = the ``AgentRun`` alias) for a coverLetter run
#: that GENUINELY produced a letter. ML-W-19: a ``completed`` status alone is
#: no longer proof of success — only a non-null letter id is. ``->>`` yields
#: SQL NULL both when the key is absent and when its value is JSON ``null``,
#: which is exactly the honest-degrade shape (``"cover_letter_id": null``), so
#: a degraded run can never satisfy this. Both spellings are accepted for the
#: same reason as above.
_COVER_RUN_PRODUCED_A_LETTER = '''
    ({run}."status" = 'completed'
     AND ({run}."output"->>'cover_letter_id' IS NOT NULL
          OR {run}."output"->>'coverLetterId' IS NOT NULL))
'''

#: Correlated-subquery fragment (reused verbatim by ``_cover_failure_count``,
#: ``_saturated_job_ids`` and ``_next_target``) that floors the failure count
#: at the LATER of the job's own last GENUINELY SUCCESSFUL coverLetter run or
#: its own last ops-clear stamp (``Job.coverFailureClearedAt`` — ML-W-12).
#:
#: Before this floor, a job's failure count was a flat "failures in the
#: trailing window" — so a job that failed 3x and THEN succeeded (or was
#: ops-cleared) stayed excluded from ``_next_target`` for the rest of the
#: window even though it no longer needed to be: the sweep never re-attempts
#: an excluded job, so it could never earn the success that would otherwise
#: clear it. Flooring the count at the last success/clear timestamp makes a
#: success (from ANY path — the sweep itself, a manual retry through the UI,
#: or an ops clear) immediately un-wedge the job, with NO historical
#: ``AgentRun`` row ever rewritten.
#:
#: ML-W-19: the "last success" term used to be ``status='completed'``, which
#: after GAP-P4-002 MATCHES the letterless degrades — so every degraded run
#: also reset the floor past all earlier real failures. It is now the
#: genuinely-produced-a-letter predicate: a degraded ``completed`` run neither
#: clears the counter nor is cleared by a later degraded run.
_SINCE_LAST_SUCCESS_OR_CLEAR = f'''
    GREATEST(
        COALESCE(
            (SELECT MAX(r2."createdAt") FROM "AgentRun" r2
             WHERE r2."userId" = {{user_ref}} AND r2."agentName" = 'coverLetter'
               AND {_COVER_RUN_PRODUCED_A_LETTER.format(run="r2").strip()}
               AND (r2."input"->>'job_id') = {{job_ref}}),
            '-infinity'::timestamptz),
        COALESCE(
            (SELECT j2."coverFailureClearedAt" FROM "Job" j2 WHERE j2."id" = {{job_ref}}),
            '-infinity'::timestamptz))
'''


def _cover_failure_count(user_id: str, job_id: str) -> int:
    """Count LETTERLESS coverLetter AgentRuns for this user+job inside the
    failure window AND since the job's last genuine success/clear. Used by
    ``_next_target``'s SQL (correlated subquery) and exposed standalone for
    observability/tests.

    "Letterless" is ``_COVER_RUN_PRODUCED_NO_LETTER``: a ``failed`` run OR a
    ``completed`` run carrying the honest ``coverLetterUnavailable`` degrade
    flag (ML-W-19 — the latter is the dominant mode in production and used to
    count zero).

    A job is PERMANENTLY skipped once this reaches ``max_cover_failures()``
    inside the window — the FabricationGuard is correctly rejecting every
    cover draft (e.g. the resume never proves 'onboarding' experience the
    LLM keeps first-person-claiming from the job title 'Onboarding PM'), and
    retrying every cron tick forever wastes LLM budget and looks like a stuck
    agent to the user. A subsequent coverLetter run that genuinely produces a
    letter (or an ops clear, ML-W-12) resets this count to 0 — see
    ``_SINCE_LAST_SUCCESS_OR_CLEAR``.
    """
    from app.db import ensure_job_cover_suppression_column, get_connection

    ensure_job_cover_suppression_column()
    window = cover_failure_window_hours()
    since_floor = _SINCE_LAST_SUCCESS_OR_CLEAR.format(
        user_ref="%s", job_ref="%s"
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'''
                SELECT count(*) FROM "AgentRun" r
                WHERE r."userId" = %s
                  AND r."agentName" = 'coverLetter'
                  AND {_COVER_RUN_PRODUCED_NO_LETTER.format(run="r")}
                  AND r."createdAt" >= NOW() - INTERVAL '%s hours'
                  AND (r."input"->>'job_id') = %s
                  AND r."createdAt" > {since_floor}
                ''',
                (user_id, window, job_id, user_id, job_id, job_id),
            )
            row = cur.fetchone()
    return row[0] if row else 0


def _saturated_job_ids(user_id: str, attempted: set[str]) -> list[str]:
    """Ids of eligible jobs that are CURRENTLY skipped solely due to the cover
    failure backoff (they have ``max_cover_failures()``+ letterless coverLetter
    runs since their last genuine success/clear, in the window, but no
    Application yet).
    Used to distinguish "board truly complete" (``board-complete``) from "all
    remaining jobs are failure-saturated" (``skipped-failures``) in the
    stretch summary — the latter tells the operator the sweep is NOT done,
    it's backing off — and (ML-W-12) to compute the honest tick log's
    earliest suppression-expiry time via ``_job_suppression_expiry``.
    """
    from app.db import ensure_job_cover_suppression_column, get_connection

    ensure_job_cover_suppression_column()
    window = cover_failure_window_hours()
    limit = max_cover_failures()
    since_floor = _SINCE_LAST_SUCCESS_OR_CLEAR.format(
        user_ref='j."userId"', job_ref='j."id"'
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'''
                SELECT j."id" FROM "Job" j
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
                          AND {_COVER_RUN_PRODUCED_NO_LETTER.format(run="r")}
                          AND r."createdAt" >= NOW() - INTERVAL '%s hours'
                          AND (r."input"->>'job_id') = j."id"
                          AND r."createdAt" > {since_floor}
                      ) >= %s
                ''',
                (user_id, list(attempted) or ["-"], user_id, window, limit),
            )
            return [row[0] for row in cur.fetchall()]


def _saturated_job_count(user_id: str, attempted: set[str]) -> int:
    """Count variant of ``_saturated_job_ids`` — kept for callers that only
    need the count."""
    return len(_saturated_job_ids(user_id, attempted))


def _job_suppression_expiry(user_id: str, job_id: str) -> Any | None:
    """Wall-clock time at which THIS job's cover-failure suppression naturally
    expires under the CURRENT data (the in-window failure count, counted
    since the job's last success/clear, drops back below
    ``max_cover_failures()``). ``None`` if the job is not currently saturated.

    ML-W-12: used only to build the honest tick log's earliest
    suppression-expiry time — never consulted by ``_next_target``, which
    re-derives eligibility fresh on every call.
    """
    from app.db import ensure_job_cover_suppression_column, get_connection

    ensure_job_cover_suppression_column()
    window = cover_failure_window_hours()
    limit = max_cover_failures()
    since_floor = _SINCE_LAST_SUCCESS_OR_CLEAR.format(user_ref="%s", job_ref="%s")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'''
                SELECT r."createdAt" FROM "AgentRun" r
                WHERE r."userId" = %s
                  AND r."agentName" = 'coverLetter'
                  AND {_COVER_RUN_PRODUCED_NO_LETTER.format(run="r")}
                  AND r."createdAt" >= NOW() - INTERVAL '%s hours'
                  AND (r."input"->>'job_id') = %s
                  AND r."createdAt" > {since_floor}
                ORDER BY r."createdAt" ASC
                ''',
                (user_id, window, job_id, user_id, job_id, job_id),
            )
            rows = [r[0] for r in cur.fetchall()]
    if len(rows) < limit:
        return None
    # The run whose exit from the window drops the in-window count below
    # `limit` — i.e. the oldest of the `limit` most-recent qualifying
    # failures. Once IT ages past the window, expiry occurs.
    idx = len(rows) - limit
    return rows[idx] + timedelta(hours=window)


def _earliest_suppression_expiry(user_id: str, job_ids: list[str]) -> str | None:
    """ISO-8601 (UTC, second precision) timestamp of the EARLIEST time any of
    ``job_ids`` naturally re-eligibilises. ``None`` if none are computable.
    Powers the honest "all N eligible jobs failure-suppressed until <time>"
    tick log (ML-W-12) — replaces the old ``processed=0`` line that gave no
    indication anything was wrong, let alone when it would resolve.
    """
    expiries = [
        e for e in (_job_suppression_expiry(user_id, jid) for jid in job_ids)
        if e is not None
    ]
    if not expiries:
        return None
    return min(expiries).replace(microsecond=0).isoformat()


def _next_target(user_id: str, attempted: set[str]) -> dict[str, str] | None:
    """The next job to process: cover-only completions first (finish work a
    prior stretch started), then full runs by fitScore descending.

    Jobs that have ``max_cover_failures()``+ LETTERLESS coverLetter AgentRuns
    (``_COVER_RUN_PRODUCED_NO_LETTER``: failed, or completed-with-the-honest-
    degrade-flag) inside the ``cover_failure_window_hours()`` sliding window,
    SINCE their last genuine success or ops-clear, are PERMANENTLY excluded —
    the sweep no longer retries a permanently unfabricatable job every cron
    tick (13+ failed attempts over 14h, then 76 letterless attempts per job
    per 24h after the degrade shape changed, observed in production before
    this fix). The guard's rejections are correct; the bug was the sweep had
    no persistent backoff that could see them (the per-stretch in-memory
    ``attempted`` set resets every tick). Once the oldest letterless run ages
    past the window, OR the job earns a coverLetter run that genuinely
    produces a letter, OR ops clears it (``Job.coverFailureClearedAt``,
    ML-W-12), the job re-eligibilises without code changes.
    """
    from app.db import ensure_job_cover_suppression_column, get_connection

    ensure_job_cover_suppression_column()
    window = cover_failure_window_hours()
    limit = max_cover_failures()
    since_floor = _SINCE_LAST_SUCCESS_OR_CLEAR.format(
        user_ref='j."userId"', job_ref='j."id"'
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'''
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
                          AND {_COVER_RUN_PRODUCED_NO_LETTER.format(run="r")}
                          AND r."createdAt" >= NOW() - INTERVAL '%s hours'
                          AND (r."input"->>'job_id') = j."id"
                          AND r."createdAt" > {since_floor}
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


def _cover_result_degraded(result: Any) -> bool:
    """Whether a coverLetter run RETURNED an honest "no letter produced"
    degrade instead of raising (``cover_letter_agent`` ML-cover-002 path).

    The in-memory twin of ``_COVER_RUN_PRODUCED_NO_LETTER``'s degrade half —
    same two spellings, same ``is True`` / ``=== true`` strictness as the SQL
    and as ``feed.ts``'s ``coverLetterDegraded``. Without it the stretch
    summary counts a letterless run as ``covers`` and the tick log claims a
    cover letter that does not exist, while the DB-backed suppression counts
    the very same run as a failure (ML-W-19).
    """
    if not isinstance(result, dict):
        return False
    return (
        result.get("coverLetterUnavailable") is True
        or result.get("cover_letter_unavailable") is True
    )


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
            saturated_ids = _saturated_job_ids(user_id, attempted)
            if saturated_ids:
                summary["reason"] = "skipped-failures"
                summary["skipped_failures"] = len(saturated_ids)
                # ML-W-12: earliest time any saturated job naturally
                # re-eligibilises, for the honest tick log below.
                summary["suppression_expiry"] = _earliest_suppression_expiry(
                    user_id, saturated_ids
                )
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
            cover_out = _run_agent(user_id, "coverLetter", {"job_id": job_id})
            if _cover_result_degraded(cover_out):
                # ML-W-19: the cover agent completed with an honest "no letter
                # produced" degrade rather than raising. No letter exists, so
                # this is a failure for counting purposes — exactly what the
                # DB-backed suppression now records for the same run. Counting
                # it as a cover would make the tick log claim work that never
                # shipped. Deliberately does NOT reset ``llm_outages``: this
                # degrade fires precisely when the writing model was
                # unavailable, so clearing the outage breaker here would
                # defeat it.
                summary["failures"] += 1
                logger.info(
                    "board-sweep %s job %s: cover degraded — no letter produced",
                    user_id, job_id,
                )
            else:
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
    if summary["reason"] == "skipped-failures" and summary["processed"] == 0:
        # ML-W-12: a tick that skips EVERY eligible job due to cover-failure
        # suppression must say so explicitly, with the earliest time the
        # suppression naturally clears — the old
        # "skipped-failures (processed=0 ...)" line was technically accurate
        # but read as routine/healthy background noise, hiding that the
        # sweep was doing NOTHING for potentially the entire failure window
        # (up to `cover_failure_window_hours()`, default 24h) with no signal
        # of when or whether it would recover on its own.
        logger.info(
            "board-sweep %s: all %d eligible job(s) failure-suppressed until %s",
            user_id, summary["skipped_failures"],
            summary.get("suppression_expiry") or "unknown",
        )
    else:
        logger.info(
            "board-sweep %s: %s (processed=%s tailored=%s covers=%s failures=%s)",
            user_id, summary["reason"], summary["processed"], summary["tailored"],
            summary["covers"], summary["failures"],
        )
    # RT-008: signal the caller (board_sweep_user) whether this stretch was
    # cut off by a soft limit (job-cap or deadline) — more work exists but we
    # hit bounds. board_sweep_user uses this to decide whether to re-enqueue
    # itself so the sweep continues until the board is truly empty, per the
    # operator mandate ("keep working non-stop until the pipeline is cleared").
    # board-complete / quota-exhausted / no-resume / llm-unavailable are HARD
    # stops — retrying immediately would either find nothing or fail again.
    summary["needs_continuation"] = summary["reason"] in ("job-cap", "deadline")
    return summary


#: Cooldown (seconds) before re-enqueuing a continued stretch. Long enough
#: that a stretch which finished in well under a second (e.g. every
#: remaining job was skipped for cover-failure saturation) can't tight-loop
#: the worker; short enough that "non-stop until empty" stays honest.
_CONTINUATION_COOLDOWN_SECONDS = 15.0


async def board_sweep_user(ctx: Any, user_id: str) -> dict[str, Any]:
    """ARQ task: run one sweep stretch for one user off the event loop.

    RT-008 continuous-sweep enforcement: when the stretch stops because it hit
    a SOFT limit (job-cap or deadline — ``needs_continuation`` is True), more
    board work exists and the operator mandate is "keep working non-stop until
    the pipeline is cleared" — so this ASKS for an immediate continuation
    instead of waiting for the next 10-minute cron tick. A HARD stop
    (board-complete, quota-exhausted, no-resume, llm-unavailable) does NOT
    ask — retrying immediately would just find nothing new or fail again for
    the same reason.

    ML-W-20 — the enqueue RESULT is now inspected and reported honestly.
    ``ArqRedis.enqueue_job`` returns ``None`` (never raises) when a job with
    that ``_job_id`` already exists: ``arq/connections.py`` checks
    ``pipe.exists(job_key, result_key_prefix + job_id)`` before queueing. Both
    keys work against a self-continuation — the job key of the CURRENTLY
    RUNNING job is still present while this coroutine runs, and after it
    finishes the result key is retained for ``WorkerSettings.keep_result``
    (300s). Production therefore refused every continuation while this
    function logged "re-enqueued continuation" unconditionally: an observed
    17:07:57Z claim followed by a silent idle window until the 17:20 cron tick
    (uat/reports/evidence/prod-verify-3/item2-autopilot-ticks.txt). The log
    now states which of the two actually happened, and the summary carries
    ``continuation_enqueued`` so callers/tests can assert it.

    The ``_job_id`` deliberately STAYS the canonical ``board-sweep:<user_id>``.
    A unique per-continuation id would make the enqueue succeed, but it would
    also leave the 10-minute cron tick (and ``enqueue_user_sweep``) deduping
    against a different key — stacking a SECOND concurrent stretch for the
    same user for most of a chain, with two ``_next_target`` selections racing
    on the same board: duplicate tailoring, duplicate letters, doubled real
    LLM spend, and duplicate Application rows. Single-flight is worth more
    than the bounded recovery cost of a refusal, which the same evidence
    measures at exactly one cron period. So when arq refuses, the cron IS the
    continuation — and the log says so instead of claiming otherwise.
    """
    import asyncio

    summary = await asyncio.to_thread(sweep_user_stretch, user_id)
    if summary.get("needs_continuation") and sweep_enabled():
        summary["continuation_enqueued"] = False
        try:
            job = await ctx["redis"].enqueue_job(
                "board_sweep_user",
                user_id,
                _job_id=f"board-sweep:{user_id}",
                _defer_by=_CONTINUATION_COOLDOWN_SECONDS,
            )
        except Exception:  # noqa: BLE001 — best-effort; next cron tick is the floor
            logger.exception("board-sweep %s: failed to re-enqueue continuation", user_id)
        else:
            if job is None:
                logger.info(
                    "board-sweep %s: continuation refused (dedup) — next cron "
                    "tick will resume (reason=%s)",
                    user_id, summary["reason"],
                )
            else:
                summary["continuation_enqueued"] = True
                logger.info(
                    "board-sweep %s: re-enqueued continuation "
                    "(reason=%s, cooldown=%.0fs)",
                    user_id, summary["reason"], _CONTINUATION_COOLDOWN_SECONDS,
                )
    return summary


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
