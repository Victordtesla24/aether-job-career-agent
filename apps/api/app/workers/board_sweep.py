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
from typing import Any, Iterator

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


#: Candidate rows the sweep's target walk pulls per round-trip (MON-001). Same
#: value and same reason as ``JobRepository._BOARD_PAGE_SIZE`` /
#: ``_SCORING_BATCH_SIZE``: a per-STATEMENT bound so the cost of ONE statement
#: stays flat as the board grows, instead of scaling with it. It is NOT a
#: result cap — the walk pages until the eligible set is exhausted, so every
#: eligible job is still considered on every call (see
#: ``_candidates_with_failure_counts``).
_CANDIDATE_PAGE_SIZE = 500

#: The sweep's eligibility gate (``{job}`` = the ``"Job"`` alias), lifted
#: VERBATIM out of the pre-MON-001 ``_next_target`` / ``_saturated_job_ids``
#: statements so the bounded walk selects exactly the same row set it always
#: did: ``tailoring`` jobs, or ``screening``/``matched`` jobs that carry a
#: fitScore; never ``applied``/``archived``; never a job that already has an
#: ``Application`` row.
_ELIGIBLE_JOB_PREDICATE = '''
    (
      ({job}."status" = 'tailoring')
   OR ({job}."status" IN ('screening','matched')
       AND {job}."fitScore" IS NOT NULL)
    )
    AND {job}."status" NOT IN ('applied','archived')
    AND NOT EXISTS (
          SELECT 1 FROM "Application" a
          WHERE a."jobId" = {job}."id" AND a."userId" = {job}."userId"
        )
'''


def _iter_candidate_pages(
    user_id: str, attempted: set[str]
) -> Iterator[list[dict[str, Any]]]:
    """Walk this user's ELIGIBLE, not-yet-attempted jobs in bounded
    keyset-paged batches — the narrow four-column projection the sweep's
    target selection actually reads, and NOT one row of ``"AgentRun"``
    (MON-001).

    The cover-failure backoff used to be a correlated subquery inside this
    statement: for every candidate row Postgres re-scanned that user's whole
    ``coverLetter`` history twice, joined on ``input->>'job_id'`` — a JSONB
    extraction no index can serve. Cost therefore scaled with (eligible jobs)
    x (AgentRun rows), which is what the hosted 5 s ``statement_timeout``
    killed on every ~10-minute ``board_sweep_user`` tick (MONITORING-LEDGER
    MON-001: ``psycopg2.errors.QueryCanceled``, 100% failure for one user).
    The backoff is now counted set-wise, once per page, by
    ``_letterless_counts``.

    Same idiom as ``JobRepository.iter_scoring_candidates`` (BLOCKER-007) and
    ``JobRepository.list_by_user`` (BLOCKER-008): the cursor advances on
    ``"id"`` — served by ``Job_pkey``, and no sweep write touches it — and the
    connection is released before each page is yielded, so the caller's own
    reads/writes never run inside a held read connection (the hosted database
    caps concurrent connections at 25).
    """
    from app.db import get_connection

    sql = f'''
        SELECT j."id", j."status", j."fitScore", j."createdAt"
        FROM "Job" j
        WHERE j."userId" = %s
          AND j."id" > %s
          AND j."id" != ALL(%s)
          AND {_ELIGIBLE_JOB_PREDICATE.format(job="j")}
        ORDER BY j."id"
        LIMIT {int(_CANDIDATE_PAGE_SIZE)}
    '''
    excluded = list(attempted) or ["-"]
    last_id = ""
    while True:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id, last_id, excluded))
                page = [
                    {"id": row[0], "status": row[1], "fitScore": row[2],
                     "createdAt": row[3]}
                    for row in cur.fetchall()
                ]
        if not page:
            return
        yield page
        last_id = page[-1]["id"]


def _letterless_counts(user_id: str, job_ids: list[str]) -> dict[str, int]:
    """``{job_id: letterless coverLetter runs}`` for the supplied, explicitly
    BOUNDED id set — one statement that walks the user's ``coverLetter``
    history ONCE, instead of once per candidate job (MON-001).

    Same three predicates, same meaning, as the correlated form it replaces:
    ``_COVER_RUN_PRODUCED_NO_LETTER`` is what gets counted, the window is
    ``cover_failure_window_hours()``, and the floor is
    ``_SINCE_LAST_SUCCESS_OR_CLEAR`` — the later of the job's last GENUINELY
    produced letter and its last ops-clear stamp — expressed as a ``GROUP BY``
    (``floors``) rather than a correlated ``MAX``. Set-wise is the same shape
    ``JobRepository._autopilot_suppression_expiry_sql`` already uses for the
    board's suppression hint (BLOCKER-008), whose equivalence against the
    correlated form was measured row-by-row over 5932 production jobs with 0
    mismatches.

    Jobs with no qualifying run are ABSENT from the mapping; callers read that
    as 0. ``window`` is inlined as a validated positive int (never a raw
    string), the same precedent BLOCKER-008 set for this predicate's SQL text.
    """
    from app.db import get_connection

    if not job_ids:
        return {}
    window = cover_failure_window_hours()
    sql = f'''
        WITH targets AS (
            SELECT j."id", j."coverFailureClearedAt"
            FROM "Job" j
            WHERE j."userId" = %s AND j."id" = ANY(%s)
        ),
        runs AS (
            SELECT (r."input"->>'job_id') AS job_id, r."createdAt",
                   {_COVER_RUN_PRODUCED_A_LETTER.format(run="r").strip()}
                       AS produced_letter,
                   {_COVER_RUN_PRODUCED_NO_LETTER.format(run="r").strip()}
                       AS letterless
            FROM "AgentRun" r
            WHERE r."userId" = %s AND r."agentName" = 'coverLetter'
        ),
        floors AS (
            SELECT job_id, MAX("createdAt") AS last_letter
            FROM runs WHERE produced_letter GROUP BY job_id
        )
        SELECT t."id", count(*)
        FROM targets t
        JOIN runs x ON x.job_id = t."id"
        LEFT JOIN floors f ON f.job_id = t."id"
        WHERE x.letterless
          AND x."createdAt" >= NOW() - (INTERVAL '1 hour' * {int(window)})
          AND x."createdAt" > GREATEST(
                COALESCE(f.last_letter, '-infinity'::timestamptz),
                COALESCE(t."coverFailureClearedAt", '-infinity'::timestamptz))
        GROUP BY t."id"
    '''
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, job_ids, user_id))
            return {row[0]: int(row[1]) for row in cur.fetchall()}


def _candidates_with_failure_counts(
    user_id: str, attempted: set[str]
) -> list[dict[str, Any]]:
    """Every eligible, not-yet-attempted job of this user, each carrying its
    current ``coverFailures`` count — read in bounded statements only
    (MON-001).

    BOUNDED, NOT TRUNCATED: the page size caps what ONE statement costs, never
    how many jobs are considered. Both callers below see the identical row set
    the single unbounded statement used to produce, so neither the target
    choice nor the saturated set can silently shrink as a board grows.
    """
    from app.db import ensure_job_cover_suppression_column

    ensure_job_cover_suppression_column()
    candidates: list[dict[str, Any]] = []
    for page in _iter_candidate_pages(user_id, attempted):
        counts = _letterless_counts(user_id, [row["id"] for row in page])
        for row in page:
            row["coverFailures"] = counts.get(row["id"], 0)
            candidates.append(row)
    return candidates


def _sweep_priority(candidate: dict[str, Any]) -> tuple[int, float, Any]:
    """``_next_target``'s ordering, applied after the bounded walk instead of
    inside it (BLOCKER-008 does the same for the board read).

    Reproduces the pre-MON-001 ``ORDER BY (status = 'tailoring') DESC,
    "fitScore" DESC NULLS LAST, "createdAt" ASC`` exactly: cover-only
    completions first (finish work a prior stretch started), then best fit,
    then oldest. A missing fitScore sorts last (``+inf`` under the ascending
    ``-fitScore`` key), which is what ``NULLS LAST`` means here. Remaining ties
    resolve by ``"id"`` because Python's sort is stable and the walk yields
    id-ascending — the SQL left those ties to the planner.
    """
    fit = candidate.get("fitScore")
    return (
        0 if candidate["status"] == "tailoring" else 1,
        float("inf") if fit is None else -float(fit),
        candidate["createdAt"],
    )


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

    MON-001: reads through the bounded walk above. It used to be the more
    severe of the two offending statements — the same per-candidate-row
    ``"AgentRun"`` correlation as ``_next_target``, and no ``LIMIT`` at all.
    """
    limit = max_cover_failures()
    return [
        candidate["id"]
        for candidate in _candidates_with_failure_counts(user_id, attempted)
        if candidate["coverFailures"] >= limit
    ]


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

    MON-001: the exclusion is applied to a bounded, set-wise failure count
    (``_candidates_with_failure_counts``) instead of a correlated
    ``"AgentRun"`` subquery evaluated per candidate row — same jobs, same
    priority order, but the cost of one statement no longer scales with
    (eligible jobs) x (that user's AgentRun history), which is what the hosted
    5 s statement timeout was cancelling on every tick.
    """
    limit = max_cover_failures()
    eligible = [
        candidate
        for candidate in _candidates_with_failure_counts(user_id, attempted)
        if candidate["coverFailures"] < limit
    ]
    if not eligible:
        return None
    target = min(eligible, key=_sweep_priority)
    return {
        "job_id": target["id"],
        "mode": "cover_only" if target["status"] == "tailoring" else "full",
    }


def _remaining_eligible_count(user_id: str, attempted: set[str]) -> int:
    """Eligible jobs this stretch has NOT attempted yet.

    CRITICAL-3 requirement 4 ("never silently swallow"): when the stretch
    aborts on an upstream refusal it is abandoning real, queued work. That
    number goes into the summary and the log so an aborted stretch can never be
    mistaken for a finished board — the old code broke out with no record of
    how much it left behind.
    """
    from app.db import get_connection

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
                ''',
                (user_id, list(attempted) or ["-"]),
            )
            row = cur.fetchone()
    return row[0] if row else 0


def _llm_failure(exc: BaseException) -> Any | None:
    """The classified :class:`LLMUnavailableError` behind ``exc``, or ``None``.

    CRITICAL-3 — THE bug this whole module's breaker was missing. The sweep
    calls agents through ``_run_agent`` -> ``app.routers.agents._dispatch``,
    and ``_dispatch`` converts every ``LLMUnavailableError`` into
    ``HTTPException(503, ...) from exc``. So ``sweep_user_stretch``'s
    ``except LLMUnavailableError`` clause — with its ``LLM_OUTAGE_BREAKER``
    circuit breaker — was UNREACHABLE on the only path that can reach it: the
    503 landed in ``except HTTPException``, was counted as an ordinary
    per-job failure, and the stretch ground through all ``max_jobs`` jobs.
    Measured live 2026-08-02: 10 jobs x 37 attempts each, 60 failed tailor
    runs per hour, every one a paid POST to an upstream returning HTTP 402.

    ``raise ... from exc`` sets ``__cause__``, so the class survives the HTTP
    translation and is recovered here. Both the direct exception and the
    wrapped one are handled, so the seam works whether the sweep is calling
    the router or an agent directly.

    A RAW transport error (``InsufficientCreditsError`` / ``ProviderAuthError``)
    that arrives without the chain's classified wrapper is normalised into the
    same shape. That is not hypothetical: ``LLMClient.complete`` bypasses
    ``_auto`` entirely in ``live``/``record`` mode and propagates the raw error,
    and the end-to-end 402 test in
    ``tests/test_critical3_llm_circuit_breaker.py`` caught the sweep walking
    all 10 jobs on exactly that path. Classification must not depend on which
    code path the error travelled.
    """
    from app.services.llm_client import (
        LLM_FAILURE_RETRYABLE,
        LLMUnavailableError,
        classify_llm_failure,
    )

    for candidate in (exc, getattr(exc, "__cause__", None)):
        if candidate is None:
            continue
        if isinstance(candidate, LLMUnavailableError):
            return candidate
        failure_class = classify_llm_failure(candidate)
        if failure_class != LLM_FAILURE_RETRYABLE:
            return LLMUnavailableError(str(candidate), failure_class=failure_class)
    return None


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


def _spend_cap_breach(user_id: str) -> dict[str, Any] | None:
    """The user's quota row when their USD spend cap is already reached, else None.

    S-4. The sweep passes ``skip_quota=True`` so its runs never eat a paid RUN
    allowance — but they spend the user's REAL DOLLARS, so the USD cap has to
    stop them. ``_record_run`` is the authoritative gate (it re-reads the same
    row immediately before any LLM call and raises an honest 429); this check
    exists so the stretch STOPS at the cap instead of walking the rest of the
    board collecting one 429 per job, and so the reason it stopped is recorded.

    A quota store that cannot be read is NOT treated as "under the cap": the
    exception propagates to the caller, which stops the stretch. Guessing
    "probably fine" here is exactly the silent bypass this fix removes.
    """
    from app.repositories.billing import UsageQuotaRepository

    quota = UsageQuotaRepository().get_or_create(user_id)
    if quota is None:
        return None
    if float(quota["spendUsedUsd"]) >= float(quota["spendCapUsd"]):
        return quota
    return None


def _record_spend_cap_stop(user_id: str, quota: dict[str, Any]) -> None:
    """Persist an honest AgentRun row saying autopilot stopped at the spend cap.

    Without a row the user sees autopilot simply go quiet: the board stops
    advancing with nothing in "Recent runs" explaining why. This records the
    stop as a failed ``boardSweep`` run carrying the actual numbers, costs $0
    (no LLM call is made), and is written once per stopped stretch.
    """
    from app.repositories.agent_run import AgentRunRepository

    used = float(quota["spendUsedUsd"])
    cap = float(quota["spendCapUsd"])
    runs = AgentRunRepository()
    run = runs.start(
        user_id,
        "boardSweep",
        {"reason": "spend_cap_exceeded", "spendUsedUsd": used, "spendCapUsd": cap},
    )
    runs.finish(
        run["id"],
        "failed",
        output={
            "stopped": True,
            "reason": "spend_cap_exceeded",
            "spendUsedUsd": used,
            "spendCapUsd": cap,
        },
        error=(
            f"Autopilot stopped: this period's AI spend cap of ${cap:.2f} is "
            f"reached (${used:.2f} used). No further automated runs will start "
            "until the cap resets or is raised."
        ),
        cost_usd=0.0,
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
        # CRITICAL-3: eligible jobs this stretch deliberately did NOT attempt
        # because it aborted on an upstream refusal. Always present so a caller
        # never has to guess whether an abort left work behind.
        "suppressed": 0,
    }
    llm_outages = 0

    def _abort_on_llm(llm_exc: Any, job_id: str) -> None:
        """Record + log an abort caused by an upstream LLM refusal.

        Sets the honest reason (``llm-<class>``) and counts the eligible jobs
        left unattempted, so the tick log states what was abandoned instead of
        going quiet.
        """
        failure_class = getattr(llm_exc, "failure_class", "unknown")
        summary["reason"] = (
            "llm-unavailable" if getattr(llm_exc, "retryable", True)
            else f"llm-{failure_class}"
        )
        summary["suppressed"] = _remaining_eligible_count(user_id, attempted)
        logger.warning(
            "board-sweep %s: ABORTING stretch after job %s — upstream LLM "
            "failure class=%s retryable=%s; %d eligible job(s) suppressed "
            "(not attempted) rather than retried: %s",
            user_id, job_id, failure_class,
            getattr(llm_exc, "retryable", True), summary["suppressed"], llm_exc,
        )

    while True:
        if summary["processed"] + summary["failures"] >= max_jobs:
            summary["reason"] = "job-cap"
            break
        # S-4: the USD spend cap is checked BEFORE every dispatch, so a user at
        # their ceiling costs zero further LLM calls this stretch (and every
        # later stretch) instead of the sweep spending unbounded real money the
        # cap could not see.
        breach = _spend_cap_breach(user_id)
        if breach is not None:
            summary["reason"] = "spend-cap-reached"
            summary["spendUsedUsd"] = float(breach["spendUsedUsd"])
            summary["spendCapUsd"] = float(breach["spendCapUsd"])
            logger.warning(
                "board-sweep %s: STOPPING — USD spend cap reached "
                "(used $%.4f of $%.2f cap). No further automated runs will "
                "start for this user until the cap resets or is raised.",
                user_id, summary["spendUsedUsd"], summary["spendCapUsd"],
            )
            _record_spend_cap_stop(user_id, breach)
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
            # CRITICAL-3: recover the LLM failure class the router wrapped into
            # this HTTPException. Without this the breaker below never saw a
            # single outage and the stretch burned its whole job cap against a
            # provider that had already refused.
            llm_exc = _llm_failure(exc)
            if llm_exc is not None:
                if not llm_exc.retryable:
                    # 402 / 401 — the answer will not change by asking again.
                    # ONE attempt, then stop, with the reason on the record.
                    _abort_on_llm(llm_exc, job_id)
                    break
                llm_outages += 1
                logger.warning(
                    "board-sweep %s job %s: LLM unavailable (%d/%d before "
                    "circuit opens): %s",
                    user_id, job_id, llm_outages, LLM_OUTAGE_BREAKER, exc.detail,
                )
                if llm_outages >= LLM_OUTAGE_BREAKER:
                    _abort_on_llm(llm_exc, job_id)
                    break
                continue
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
            # Direct (un-wrapped) path — kept for callers that bypass the
            # router. Same classification rules as the wrapped path above.
            summary["failures"] += 1
            if not exc.retryable:
                _abort_on_llm(exc, job_id)
                break
            llm_outages += 1
            logger.warning(
                "board-sweep %s job %s: LLM unavailable (%d/%d before circuit "
                "opens): %s",
                user_id, job_id, llm_outages, LLM_OUTAGE_BREAKER, exc,
            )
            if llm_outages >= LLM_OUTAGE_BREAKER:
                _abort_on_llm(exc, job_id)
                break
        except Exception as exc:  # noqa: BLE001 — one bad job never sinks the sweep
            summary["failures"] += 1
            # CRITICAL-3: classify BEFORE writing this off as "unexpected".
            # A raw transport refusal (402/401) that reached here un-wrapped is
            # still an upstream saying no — grinding through the rest of the
            # board would repeat a paid, already-answered question.
            llm_exc = _llm_failure(exc)
            if llm_exc is not None and not llm_exc.retryable:
                _abort_on_llm(llm_exc, job_id)
                break
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
    #
    # CRITICAL-3: ``processed > 0`` is now REQUIRED. A stretch that failed
    # every one of its ``max_jobs`` attempts also reports ``job-cap`` — and
    # that is exactly what happened for days in production: 10 consecutive
    # failures against an upstream returning 402 were read as "we ran out of
    # room, there is more to do", so the sweep asked to be run again. Progress
    # is the only honest justification for continuing; zero completions means
    # the cap was consumed by failures and the next cron tick (10 minutes of
    # cooling) is the right cadence, not an immediate re-enqueue.
    summary["needs_continuation"] = (
        summary["reason"] in ("job-cap", "deadline") and summary["processed"] > 0
    )
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
