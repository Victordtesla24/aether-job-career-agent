"""Job repository — raw psycopg2 against the Prisma ``Job`` table (P2-S02)."""
from __future__ import annotations

import json
import os
from typing import Any, Iterator

from app.db import (
    ensure_job_cover_suppression_column,
    ensure_job_dedup_columns,
    ensure_job_last_seen_column,
    get_connection,
    new_id,
    rows_to_dicts,
)
from app.services.dedup import (
    compute_description_hash,
    compute_null_source_url_hash,
    normalize_source_url,
)
from app.services.discovery.base_adapter import JobRaw

_JOB_COLUMNS = (
    '"id", "userId", "title", "company", "location", "remote", "salaryMin", '
    '"salaryMax", "currency", "description", "requirements", "source", '
    '"sourceUrl", "status", "fitScore", "atsScore", "saved", "postedAt", '
    '"createdAt", "updatedAt"'
)

#: Read projection = the write projection plus ``lastSeenAt`` (BLOCKER-006):
#: the time a discovery sweep last found this listing still published at its
#: source. Only the READ paths need it (the active feed decides liveness from
#: it, and the UI states it), so the ``RETURNING`` clauses of create/update
#: stay on ``_JOB_COLUMNS`` and need no extra DDL guard.
_JOB_READ_COLUMNS = _JOB_COLUMNS + ', "lastSeenAt"'

#: Projection for the FIT-SCORER's read path (BLOCKER-007) — deliberately NOT
#: ``_JOB_READ_COLUMNS``. It is exactly the six values
#: :meth:`app.agents.fit_scorer.FitScorerAgent.run` reads: ``id`` (the write
#: key), ``fitScore``/``atsScore`` (the score-present decision), and
#: ``title``/``description``/``requirements`` (the evidence text built by
#: :func:`app.services.fit_evidence.job_evidence_text`). Same column set as
#: ``fit_score_remediation._EVIDENCE_COLUMNS`` plus the two score columns.
#:
#: The board's projection additionally evaluates THREE correlated subqueries
#: PER ROW (``tailoredResumeId``, ``tailoredResumeStatus``, and
#: ``autopilotSuppressedUntil``, which itself runs three more correlated scans
#: of ``AgentRun``). The scorer reads none of them, and paying for them was the
#: bulk of the cost that put this read over the hosted 5 s statement timeout.
_JOB_SCORING_COLUMNS = (
    '"id", "title", "description", "requirements", "fitScore", "atsScore"'
)

#: Rows the fit-scorer pulls per round-trip. Bounded so the cost of ONE
#: statement stays flat as the catalog grows, instead of scaling with it —
#: mirrors ``fit_score_remediation._BATCH_SIZE`` (the other keyset-paged sweep
#: over this table) so both walk it the same way.
_SCORING_BATCH_SIZE = 500

_TAILORED_RESUME_SUBQUERY = (
    '(SELECT r."id" FROM "Resume" r '
    'WHERE r."userId" = j."userId" AND r."sourceJobId" = j."id" '
    'AND r."approvalStatus" != \'rejected\' '
    'ORDER BY r."version" DESC LIMIT 1) AS "tailoredResumeId"'
)

_TAILORED_RESUME_STATUS_SUBQUERY = (
    '(SELECT r."approvalStatus" FROM "Resume" r '
    'WHERE r."userId" = j."userId" AND r."sourceJobId" = j."id" '
    'AND r."approvalStatus" != \'rejected\' '
    'ORDER BY r."version" DESC LIMIT 1) AS "tailoredResumeStatus"'
)

# ---------------------------------------------------------------------------
# Autopilot suppression visibility (QA #4 residual — "autopilot goes quiet
# ~24h with no in-app explanation"). The board-sweep autopilot
# (``app/workers/board_sweep.py``, RT-007 / ML-W-19) permanently skips a job
# once it accrues ``max_cover_failures()`` LETTERLESS coverLetter AgentRun
# rows inside ``cover_failure_window_hours()`` since the job's own last
# genuine success/ops-clear — correct backoff behaviour, but until now
# invisible: nothing in the job payload told the owner WHY a job simply
# stopped progressing.
#
# THIRD-COPY WARNING — this is now the THIRD place that encodes the
# letterless-run predicate / since-last-success-or-clear floor, after:
#   1. ``app/workers/board_sweep.py`` — the SOURCE OF TRUTH
#      (``_COVER_RUN_PRODUCED_NO_LETTER``, ``_COVER_RUN_PRODUCED_A_LETTER``,
#      ``_SINCE_LAST_SUCCESS_OR_CLEAR``, ``_job_suppression_expiry``).
#   2. ``scripts/clear_cover_suppression.py`` — the ops escape hatch, kept
#      standalone by design (zero import-time side effects).
#   3. HERE — a correlated subquery (the same RT-010 style as
#      ``_TAILORED_RESUME_SUBQUERY`` above) so ``GET /jobs`` and
#      ``GET /jobs/{id}`` can expose the expiry without importing the ARQ
#      worker module into the API request path.
# Deliberately NOT implemented by importing ``app.workers.board_sweep`` — do
# not "fix" this by adding that import; keep it mirrored, and update ALL
# THREE copies together on any predicate change or the UI, ops tool and the
# sweep itself will disagree about which jobs are suppressed.
# ---------------------------------------------------------------------------


def _autopilot_max_cover_failures() -> int:
    """Mirrors ``app.workers.board_sweep.max_cover_failures()`` — reads the
    SAME env var (default 3) so this mirror can never drift from the
    worker's runtime-tunable value."""
    try:
        return max(1, int(os.environ.get("AETHER_BOARD_SWEEP_MAX_COVER_FAILURES", "3")))
    except (TypeError, ValueError):
        return 3


def _autopilot_cover_failure_window_hours() -> int:
    """Mirrors ``app.workers.board_sweep.cover_failure_window_hours()`` —
    reads the SAME env var (default 24)."""
    try:
        return max(1, int(os.environ.get(
            "AETHER_BOARD_SWEEP_COVER_FAILURE_WINDOW_HOURS", "24")))
    except (TypeError, ValueError):
        return 24


#: Mirrors ``board_sweep._COVER_RUN_PRODUCED_NO_LETTER`` verbatim (see
#: THIRD-COPY WARNING above): a coverLetter ``AgentRun`` that produced NO
#: letter — either ``status='failed'``, or a ``completed`` run carrying the
#: honest ``coverLetterUnavailable`` degrade flag (either spelling).
_AP_COVER_RUN_PRODUCED_NO_LETTER = '''
    ({run}."status" = 'failed'
     OR ({run}."status" = 'completed'
         AND ({run}."output"->'coverLetterUnavailable' = 'true'::jsonb
              OR {run}."output"->'cover_letter_unavailable' = 'true'::jsonb)))
'''

#: Mirrors ``board_sweep._COVER_RUN_PRODUCED_A_LETTER`` verbatim: only a
#: non-null letter id counts as a genuine success.
_AP_COVER_RUN_PRODUCED_A_LETTER = '''
    ({run}."status" = 'completed'
     AND ({run}."output"->>'cover_letter_id' IS NOT NULL
          OR {run}."output"->>'coverLetterId' IS NOT NULL))
'''

#: Mirrors ``board_sweep._SINCE_LAST_SUCCESS_OR_CLEAR`` verbatim, pre-bound to
#: this module's fixed query shape (always a correlated subquery against the
#: outer ``"Job" j``, unlike board_sweep's multi-shape template).
_AP_SINCE_LAST_SUCCESS_OR_CLEAR = f'''
    GREATEST(
        COALESCE(
            (SELECT MAX(r2."createdAt") FROM "AgentRun" r2
             WHERE r2."userId" = j."userId" AND r2."agentName" = 'coverLetter'
               AND {_AP_COVER_RUN_PRODUCED_A_LETTER.format(run="r2").strip()}
               AND (r2."input"->>'job_id') = j."id"),
            '-infinity'::timestamptz),
        COALESCE(j."coverFailureClearedAt", '-infinity'::timestamptz))
'''


def _autopilot_suppressed_until_subquery() -> str:
    """Correlated subquery (RT-010 style) computing the wall-clock time this
    job's cover-failure suppression naturally expires — ``NULL`` when the job
    is not currently suppressed.

    Mirrors ``board_sweep._job_suppression_expiry()``: with the window's
    letterless runs (since the job's last success/clear) ordered oldest to
    newest, the job is suppressed once there are ``>= limit`` of them, and
    the expiry clock is set by the OLDEST of the ``limit`` most-recent ones
    ageing out of the window. Ordering DESC and taking ``OFFSET (limit - 1)
    LIMIT 1`` lands on exactly that row: with ``N >= limit`` qualifying rows
    it is the ``limit``-th most recent one; with ``N < limit`` rows the
    OFFSET exceeds the result set and the subquery returns NULL — the same
    "not suppressed" answer as the Python function's ``len(rows) < limit``
    guard.

    Also mirrors ``board_sweep._saturated_job_ids``'s eligibility gate
    (``tailoring``, or ``screening``/``matched`` with a fitScore; not
    ``applied``/``archived``; no ``Application`` row yet) — a job outside the
    sweep's eligibility (e.g. already applied) must never show a suppression
    hint even if its historical ``AgentRun`` rows would otherwise satisfy the
    count, because the sweep is no longer tracking it.

    ``limit``/``window`` are inlined as validated positive ints (never raw
    strings) rather than bind params: this subquery text is spliced into the
    middle of a larger SELECT whose own ``%s`` placeholders are positionally
    bound from ``list_by_user``'s/``get_by_id``'s own params list, so adding
    more ``%s`` here would require re-deriving that ordering — the tailored-
    resume subqueries above set the same precedent of literal (non-templated)
    SQL text.
    """
    limit = _autopilot_max_cover_failures()
    window = _autopilot_cover_failure_window_hours()
    offset = limit - 1
    return f'''
        (CASE WHEN (
                ( (j."status" = 'tailoring')
               OR (j."status" IN ('screening', 'matched') AND j."fitScore" IS NOT NULL) )
                AND j."status" NOT IN ('applied', 'archived')
                AND NOT EXISTS (
                      SELECT 1 FROM "Application" a
                      WHERE a."jobId" = j."id" AND a."userId" = j."userId"
                    )
              )
              THEN (
                SELECT r."createdAt" + (INTERVAL '1 hour' * {window})
                FROM "AgentRun" r
                WHERE r."userId" = j."userId"
                  AND r."agentName" = 'coverLetter'
                  AND {_AP_COVER_RUN_PRODUCED_NO_LETTER.format(run="r")}
                  AND r."createdAt" >= NOW() - (INTERVAL '1 hour' * {window})
                  AND (r."input"->>'job_id') = j."id"
                  AND r."createdAt" > {_AP_SINCE_LAST_SUCCESS_OR_CLEAR}
                ORDER BY r."createdAt" DESC
                OFFSET {offset} LIMIT 1
              )
              ELSE NULL
         END) AS "autopilotSuppressedUntil"
    '''


VALID_STATUSES = frozenset(
    {
        "discovered", "screening", "matched", "tailoring",
        "ready", "applied", "archived", "rejected",
    }
)


class JobRepository:
    """CRUD over the ``Job`` table using short-lived psycopg2 connections."""

    def create(self, user_id: str, job_raw: JobRaw) -> dict[str, Any]:
        """Insert a discovered job; idempotent upsert on (userId, sourceUrl).

        Dedup strategy (Phase 2A):
        1. sourceUrl is normalized (strip tracking params, lowercase, etc.)
           before insert, so the DB-level ON CONFLICT catches more matches.
        2. For NULL sourceUrl jobs: a composite hash of
           (userId + title + company + location) is computed and checked
           against the ``dedupHash`` column — if a match exists, the job is
           treated as an update (returning wasInserted=False).
        3. A ``contentHash`` (sha256 of first 500 chars of description) is
           stored as a secondary dedup signal for future use.

        Every call — insert OR re-discovery of an already-persisted listing —
        stamps ``lastSeenAt = NOW()`` (BLOCKER-006). This method is the single
        path every adapter's results flow through, so reaching it is proof the
        source returned this listing on this sweep, i.e. it is still published
        and still applicable. ``postedAt`` is never bumped: the posting date
        and the sighting are different facts and the UI states both.
        """
        ensure_job_dedup_columns()
        ensure_job_last_seen_column()

        requirements = json.dumps(job_raw.get("requirements") or [])
        raw_source_url = job_raw.get("sourceUrl")
        normalized_url = normalize_source_url(raw_source_url)

        dedup_hash: str | None = None
        content_hash: str | None = None
        if job_raw.get("description"):
            content_hash = compute_description_hash(job_raw["description"])
        if normalized_url is None:
            dedup_hash = compute_null_source_url_hash(
                user_id,
                job_raw["title"],
                job_raw["company"],
                job_raw.get("location"),
            )

        with get_connection() as conn:
            with conn.cursor() as cur:
                if dedup_hash is not None:
                    cur.execute(
                        'SELECT "id" FROM "Job" '
                        'WHERE "userId" = %s AND "dedupHash" = %s LIMIT 1',
                        (user_id, dedup_hash),
                    )
                    existing = cur.fetchone()
                    if existing:
                        existing_id = existing[0]
                        cur.execute(
                            """
                            UPDATE "Job" SET
                                "title" = %s,
                                "company" = %s,
                                "location" = %s,
                                "remote" = %s,
                                "description" = %s,
                                "requirements" = %s,
                                "salaryMin" = COALESCE(%s, "Job"."salaryMin"),
                                "salaryMax" = COALESCE(%s, "Job"."salaryMax"),
                                "currency" = COALESCE(%s, "Job"."currency"),
                                "postedAt" = COALESCE(%s, "Job"."postedAt"),
                                "sourceUrl" = %s,
                                "contentHash" = COALESCE(%s, "Job"."contentHash"),
                                "lastSeenAt" = NOW(),
                                "updatedAt" = NOW()
                            WHERE "id" = %s
                            RETURNING """
                            + _JOB_COLUMNS
                            + """, FALSE AS "wasInserted"
                            """,
                            (
                                job_raw["title"],
                                job_raw["company"],
                                job_raw.get("location"),
                                job_raw.get("remote", False),
                                job_raw.get("description", ""),
                                requirements,
                                job_raw.get("salaryMin"),
                                job_raw.get("salaryMax"),
                                job_raw.get("currency"),
                                job_raw.get("postedAt"),
                                normalized_url,
                                content_hash,
                                existing_id,
                            ),
                        )
                        rows = rows_to_dicts(cur)
                        conn.commit()
                        return rows[0]

                cur.execute(
                    f"""
                    INSERT INTO "Job" (
                        "id", "userId", "title", "company", "location", "remote",
                        "description", "requirements", "source", "sourceUrl",
                        "salaryMin", "salaryMax", "currency", "postedAt",
                        "dedupHash", "contentHash", "lastSeenAt", "updatedAt"
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        NOW(), NOW()
                    )
                    ON CONFLICT ("userId", "sourceUrl") DO UPDATE SET
                        "title" = EXCLUDED."title",
                        "company" = EXCLUDED."company",
                        "location" = EXCLUDED."location",
                        "remote" = EXCLUDED."remote",
                        "description" = EXCLUDED."description",
                        "requirements" = EXCLUDED."requirements",
                        "salaryMin" = COALESCE(EXCLUDED."salaryMin", "Job"."salaryMin"),
                        "salaryMax" = COALESCE(EXCLUDED."salaryMax", "Job"."salaryMax"),
                        "currency" = COALESCE(EXCLUDED."currency", "Job"."currency"),
                        "postedAt" = COALESCE(EXCLUDED."postedAt", "Job"."postedAt"),
                        "dedupHash" = COALESCE(EXCLUDED."dedupHash", "Job"."dedupHash"),
                        "contentHash" = COALESCE(EXCLUDED."contentHash", "Job"."contentHash"),
                        "lastSeenAt" = NOW(),
                        "updatedAt" = NOW()
                    RETURNING {_JOB_COLUMNS}, (xmax = 0) AS "wasInserted"
                    """,
                    (
                        new_id(),
                        user_id,
                        job_raw["title"],
                        job_raw["company"],
                        job_raw.get("location"),
                        job_raw.get("remote", False),
                        job_raw.get("description", ""),
                        requirements,
                        job_raw["source"],
                        normalized_url,
                        job_raw.get("salaryMin"),
                        job_raw.get("salaryMax"),
                        job_raw.get("currency"),
                        job_raw.get("postedAt"),
                        dedup_hash,
                        content_hash,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def list_by_user(
        self,
        user_id: str,
        status: str | None = None,
        source: str | None = None,
        saved: bool | None = None,
        sort: str = "createdAt",
    ) -> list[dict[str, Any]]:
        clauses = ['"userId" = %s']
        params: list[Any] = [user_id]
        if status is not None:
            clauses.append('"status" = %s')
            params.append(status)
        if source is not None:
            clauses.append('"source" = %s')
            params.append(source)
        if saved is not None:
            clauses.append('"saved" = %s')
            params.append(saved)
        order_column = {
            "createdAt": '"createdAt"',
            "fitScore": '"fitScore"',
            "fit_score": '"fitScore"',
            "title": '"title"',
            "company": '"company"',
        }.get(sort, '"createdAt"')
        ensure_job_cover_suppression_column()
        ensure_job_last_seen_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_JOB_READ_COLUMNS}, {_TAILORED_RESUME_SUBQUERY}, '
                    f'{_TAILORED_RESUME_STATUS_SUBQUERY}, '
                    f'{_autopilot_suppressed_until_subquery()} '
                    f'FROM "Job" j WHERE {" AND ".join(clauses)} '
                    f"ORDER BY {order_column} DESC NULLS LAST",
                    params,
                )
                return rows_to_dicts(cur)

    def iter_scoring_candidates(self, user_id: str) -> Iterator[dict[str, Any]]:
        """Stream EVERY job of ``user_id`` for the fit-scorer, one row at a time,
        read in bounded keyset-paged batches (BLOCKER-007).

        WHY THIS EXISTS, AND NOT ``list_by_user``
        -----------------------------------------
        The scorer used to read through :meth:`list_by_user` — the board's
        projection: every column plus three correlated subqueries per row, and
        no ``LIMIT``. Measured read-only against production on 2026-08-09 with
        5848 rows on the owner account, that statement was CANCELED at 5005.9 ms
        by the hosted 5 s ``statement_timeout`` (it needs 5701.5 ms when the
        timeout is raised), so ``POST /agents/fit-scorer/run`` had returned 500
        on all 66 discovery cycles since 2026-08-07T22:05Z and nothing was being
        scored at all. The SAME catalog read through THIS method, measured the
        same way: all 5848 rows in 13 statements, slowest statement 107.7 ms
        (46x under the cap), 1831.7 ms end to end — of which ~130 ms per batch
        is connection setup, the price of the short-lived-connection rule below.

        SAME ROWS, NOT FEWER — this is a bounded read, not a truncated one
        ------------------------------------------------------------------
        Every job belonging to ``user_id`` is still yielded, in one run. There
        is deliberately NO ``fitScore IS NULL`` predicate: the scorer's pass
        over already-scored rows is what retires pre-gate junk scores
        (``clear_fit_score``) and what self-heals a scored job still parked at
        ``discovered`` — filtering those rows out in SQL would silently stop
        both. The evidence gate likewise stays in Python
        (:func:`app.services.fit_evidence.has_scorable_evidence`); a SQL length
        expression would be a second, drifting definition of it, for the reasons
        set out in :mod:`app.services.fit_score_remediation`.

        The keyset cursor advances on ``id``, which no scorer write touches, so
        the in-loop score/status updates cannot make the walk skip or repeat a
        row. A job INSERTED by a concurrent sweep whose ``id`` sorts BELOW the
        current cursor is not seen by the run in progress; the next discovery
        cycle picks it up, exactly as it would have before this change (that
        job did not exist when the old single ``SELECT`` ran either).

        The connection is released before each batch is yielded, so the caller's
        per-row writes never run inside a held read connection (the hosted
        database caps concurrent connections at 25).
        """
        sql = (
            f'SELECT {_JOB_SCORING_COLUMNS} FROM "Job" '
            f'WHERE "userId" = %s AND "id" > %s '
            f'ORDER BY "id" LIMIT {int(_SCORING_BATCH_SIZE)}'
        )
        last_id = ""
        while True:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (user_id, last_id))
                    batch = rows_to_dicts(cur)
            if not batch:
                return
            yield from batch
            last_id = batch[-1]["id"]

    def get_by_id(self, job_id: str, user_id: str) -> dict[str, Any] | None:
        ensure_job_cover_suppression_column()
        ensure_job_last_seen_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_JOB_READ_COLUMNS}, {_TAILORED_RESUME_SUBQUERY}, '
                    f'{_TAILORED_RESUME_STATUS_SUBQUERY}, '
                    f'{_autopilot_suppressed_until_subquery()} '
                    f'FROM "Job" j WHERE "id" = %s AND "userId" = %s',
                    (job_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def update_status(self, job_id: str, status: str) -> dict[str, Any] | None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid job status '{status}'. Valid: {sorted(VALID_STATUSES)}")
        return self._update(job_id, '"status" = %s::"JobStatus"', (status,))

    def advance_status(
        self, job_id: str, status: str, *, allowed_from: set[str] | frozenset[str]
    ) -> bool:
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid job status '{status}'. Valid: {sorted(VALID_STATUSES)}"
            )
        bad = set(allowed_from) - VALID_STATUSES
        if bad:
            raise ValueError(
                f"Invalid allowed_from statuses {sorted(bad)}. "
                f"Valid: {sorted(VALID_STATUSES)}"
            )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE "Job" SET "status" = %s::"JobStatus", "updatedAt" = NOW()
                    WHERE "id" = %s AND "status"::text = ANY(%s)
                    """,
                    (status, job_id, sorted(allowed_from)),
                )
                advanced = cur.rowcount == 1
            conn.commit()
        return advanced

    def update_fit_score(
        self, job_id: str, fit_score: float, ats_score: float
    ) -> dict[str, Any] | None:
        return self._update(
            job_id, '"fitScore" = %s, "atsScore" = %s', (fit_score, ats_score)
        )

    def clear_fit_score(self, job_id: str) -> dict[str, Any] | None:
        """Retire a persisted score (v5 evidence gate remediation).

        NULL — not 0 — is the honest value: the board sorts
        ``fitScore DESC NULLS LAST``, so an unscorable posting drops out of the
        ranking instead of being ranked last on a number nobody computed.
        Idempotent: clearing an already-NULL row is a no-op UPDATE.
        """
        return self._update(job_id, '"fitScore" = NULL, "atsScore" = NULL', ())

    def toggle_saved(self, job_id: str, user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE "Job" SET "saved" = NOT "saved", "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    RETURNING {_JOB_COLUMNS}
                    """,
                    (job_id, user_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def _update(self, job_id: str, set_clause: str, params: tuple) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE "Job" SET {set_clause}, "updatedAt" = NOW()
                    WHERE "id" = %s
                    RETURNING {_JOB_COLUMNS}
                    """,
                    (*params, job_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None
