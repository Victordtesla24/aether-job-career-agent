"""Raw psycopg2 access to the Prisma-managed PostgreSQL database (P2-S01).

The schema itself is owned by Prisma (``packages/db/src/schema.prisma``); the
API reads/writes it with plain SQL. Prisma-style URLs carry a ``?schema=``
query parameter that psycopg2 does not understand, so it is translated into a
``search_path`` option here.

The hosted PostgreSQL caps concurrent connections at 25 and kills idle
transactions, so connections are short-lived: open, use, close.
"""
from __future__ import annotations

import logging
import os
import secrets
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


def _translate_prisma_url(url: str) -> tuple[str, str | None]:
    """Strip Prisma's ``schema`` query param; return (dsn, schema)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    schema_values = params.pop("schema", None)
    schema = schema_values[0] if schema_values else None
    query = urlencode({k: v[0] for k, v in params.items()})
    dsn = urlunparse(parsed._replace(query=query))
    return dsn, schema


def get_database_url() -> str:
    """Resolve the database URL from the environment (test-swappable)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return url


@contextmanager
def get_connection() -> Iterator[psycopg2.extensions.connection]:
    """Yield a short-lived psycopg2 connection with the right search_path."""
    dsn, schema = _translate_prisma_url(get_database_url())
    options = f"-csearch_path={schema}" if schema else None
    conn = psycopg2.connect(dsn, options=options)
    try:
        yield conn
    finally:
        conn.close()


def new_id() -> str:
    """Generate a cuid-shaped identifier compatible with Prisma's ids."""
    return "c" + secrets.token_hex(12)


def rows_to_dicts(cursor: Any) -> list[dict[str, Any]]:
    """Materialize all rows of a cursor as column-name dicts."""
    columns = [col.name for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


#: Guard so the additive ``User`` profile columns are only ensured once per
#: worker process (see ``ensure_user_profile_columns``).
_user_profile_columns_ready = False


def ensure_user_profile_columns() -> None:
    """Idempotently add the additive profile columns to ``User`` on first use.

    ``targetRole``/``location``/``agentConfig``/``username`` were introduced
    after the original Prisma migration and only ALTER-added to the production
    ``aether`` schema. The shared test schema (``aether_test``) predates them,
    so any query that reads these columns would fail there with
    ``UndefinedColumn``.

    ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` is a no-op where the columns
    already exist (production) and safely backfills them everywhere else. The
    ``username`` column is additionally given a nullable UNIQUE index (multiple
    NULLs are allowed by Postgres, so pre-existing users without a username are
    unaffected) via ``CREATE UNIQUE INDEX IF NOT EXISTS``, keeping the whole
    migration additive and backward-compatible. A transaction-scoped advisory
    lock serializes concurrent first-hit callers so the DDL can't race,
    mirroring the pattern used for the agent config tables. ``TRUNCATE`` never
    drops columns, so this survives the test-suite teardown.
    """
    global _user_profile_columns_ready
    if _user_profile_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: even as a no-op, ALTER takes an ACCESS
            # EXCLUSIVE lock, so it stalls behind any concurrent reader and
            # dies on the hosted 5s statement timeout. Only reach for DDL
            # when a column is actually missing.
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'User'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('targetRole', 'location', 'agentConfig',"
                " 'username')"
            )
            row = cur.fetchone()
            if row and row[0] == 4:
                _user_profile_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240712,))
            cur.execute('ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "targetRole" text')
            cur.execute('ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "location" text')
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "agentConfig" jsonb'
            )
            cur.execute('ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "username" text')
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "User_username_key"'
                ' ON "User" ("username")'
            )
        conn.commit()
    _user_profile_columns_ready = True


#: Guard so the additive admin/security columns are only ensured once per worker
#: process (see ``ensure_admin_user_columns``).
_admin_user_columns_ready = False


def ensure_admin_user_columns() -> None:
    """Idempotently add the additive admin/security columns to ``User``.

    ``isAdmin`` (privilege gate, GAP-P6-ADMIN-001), ``suspended`` (GAP-P6 §15
    account suspension) and ``lastLoginAt`` (§15 user list) are additive columns.
    They are introduced by lazy DDL (ADR-TR-1) — there is no migration runner —
    so every admin/auth read path calls this first, mirroring
    ``ensure_user_profile_columns``.

    ``ADD COLUMN ... NOT NULL DEFAULT false`` is a metadata-only change on
    PostgreSQL (the constant default is not rewritten across existing rows), so
    it is fast and safe on the production ``User`` table and backfills the shared
    test schema. A transaction-scoped advisory lock serializes concurrent
    first-hit callers so the DDL cannot race; ``TRUNCATE`` never drops columns,
    so this survives the test-suite teardown.
    """
    global _admin_user_columns_ready
    if _admin_user_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: skip the ACCESS EXCLUSIVE ALTER when both
            # columns already exist (production / warm test schema).
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'User'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('isAdmin', 'suspended', 'lastLoginAt')"
            )
            row = cur.fetchone()
            if row and row[0] == 3:
                _admin_user_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240720,))
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "isAdmin" boolean'
                " NOT NULL DEFAULT false"
            )
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "suspended" boolean'
                " NOT NULL DEFAULT false"
            )
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "lastLoginAt" timestamptz'
            )
        conn.commit()
    _admin_user_columns_ready = True


#: Guard so the additive ``Resume`` approval column is only ensured once per
#: worker process (see ``ensure_resume_columns``).
_resume_columns_ready = False


def ensure_resume_columns() -> None:
    """Idempotently add the additive ``Resume.approvalStatus`` column on first use.

    ``approvalStatus`` (MV-resume-studio-001) records the human-in-the-loop review
    state of a résumé version — ``pending`` for a freshly tailored child version
    that awaits sign-off, ``approved``/``rejected`` once the linked
    ``ApprovalRequest`` is resolved. It is introduced by lazy DDL (ADR-TR-1 — there
    is no migration runner), so the résumé read/write paths call this first,
    mirroring ``ensure_user_profile_columns``.

    ``ADD COLUMN ... NOT NULL DEFAULT 'approved'`` is a metadata-only change on
    PostgreSQL (the constant default is not rewritten across existing rows), so it
    is fast and safe on the production ``Resume`` table and backfills the shared
    test schema. Defaulting to ``approved`` keeps EVERY pre-existing résumé
    version (the immutable base and all historical tailored versions) usable and
    downloadable exactly as before — backward compatible; only newly tailored
    versions are created ``pending``. A transaction-scoped advisory lock serializes
    concurrent first-hit callers so the DDL cannot race; ``TRUNCATE`` never drops
    columns, so this survives the test-suite teardown.
    """
    global _resume_columns_ready
    if _resume_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: skip the ACCESS EXCLUSIVE ALTER when the column
            # already exists (production / warm test schema).
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Resume'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'approvalStatus'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _resume_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240721,))
            cur.execute(
                'ALTER TABLE "Resume" ADD COLUMN IF NOT EXISTS "approvalStatus" text'
                " NOT NULL DEFAULT 'approved'"
            )
        conn.commit()
    _resume_columns_ready = True


#: Guard so the additive ``ApprovalRequest`` execution column is only ensured
#: once per worker process (see ``ensure_approval_columns``).
_approval_columns_ready = False


def ensure_approval_columns() -> None:
    """Idempotently add the additive ``ApprovalRequest.executedAt`` column on first use.

    ``executedAt`` (MV-approval-modal-010) is the idempotency marker for the
    ``/approvals/{id}/execute`` side-effect: the endpoint claims an approved
    request by conditionally stamping this column exactly once, so a
    double-submit/retry cannot fire the same real Gmail send twice. Introduced by
    lazy DDL (ADR-TR-1 — there is no migration runner), mirroring
    ``ensure_resume_columns``.

    ``ADD COLUMN ... timestamptz`` with no default is a metadata-only change on
    PostgreSQL (existing rows read ``NULL`` = "never executed"), so it is fast and
    safe on the production ``ApprovalRequest`` table and backfills the shared test
    schema — fully backward compatible; the ``ApprovalStatus`` enum is untouched. A
    transaction-scoped advisory lock serializes concurrent first-hit callers so the
    DDL cannot race; ``TRUNCATE`` never drops columns, so this survives teardown.
    """
    global _approval_columns_ready
    if _approval_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: skip the ACCESS EXCLUSIVE ALTER when the column
            # already exists (production / warm test schema).
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'ApprovalRequest'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'executedAt'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _approval_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240725,))
            cur.execute(
                'ALTER TABLE "ApprovalRequest" '
                'ADD COLUMN IF NOT EXISTS "executedAt" timestamptz'
            )
        conn.commit()
    _approval_columns_ready = True


#: Guard so the additive ``Job`` dedup columns are only ensured once per
#: worker process (see ``ensure_job_dedup_columns``).
_job_dedup_columns_ready = False


def ensure_job_dedup_columns() -> None:
    """Idempotently add the additive ``Job.dedupHash`` and ``Job.contentHash``
    columns on first use.

    ``dedupHash`` (Phase 2A — NULL sourceUrl dedup fix) is a composite hash of
    (userId + title + company + location) that closes the PostgreSQL NULL != NULL
    gap in the ``@@unique([userId, sourceUrl])`` constraint.  Jobs that share
    the same ``dedupHash`` are considered duplicates and are upserted instead of
    inserted.

    ``contentHash`` (Phase 2A — secondary dedup signal) is sha256 of the first
    500 characters of the job description.  It catches near-duplicate postings
    that may have slightly different titles, companies, or locations.

    ``ADD COLUMN ... text`` with no default is a metadata-only change on
    PostgreSQL (existing rows read ``NULL`` = no hash yet computed), so it is
    fast and safe on the production ``Job`` table and backfills the shared test
    schema — fully backward compatible.  A transaction-scoped advisory lock
    serializes concurrent first-hit callers so the DDL cannot race; ``TRUNCATE``
    never drops columns, so this survives teardown.  Introduced by lazy DDL
    (ADR-TR-1 — there is no migration runner), mirroring
    ``ensure_resume_columns``.
    """
    global _job_dedup_columns_ready
    if _job_dedup_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Job'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('dedupHash', 'contentHash')"
            )
            row = cur.fetchone()
            if row and row[0] == 2:
                _job_dedup_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240730,))
            cur.execute(
                'ALTER TABLE "Job" '
                'ADD COLUMN IF NOT EXISTS "dedupHash" text'
            )
            cur.execute(
                'ALTER TABLE "Job" '
                'ADD COLUMN IF NOT EXISTS "contentHash" text'
            )
        conn.commit()
    _job_dedup_columns_ready = True


#: Guard so the additive ``StoryEntry`` dedup column is only ensured once per
#: worker process (see ``ensure_story_dedup_column``).
_story_dedup_column_ready = False


def ensure_story_dedup_column() -> None:
    """Idempotently add the additive ``StoryEntry.contentHash`` column on first use.

    ``contentHash`` (G-P4-STORY-DEDUP-004) is a sha256 of
    (userId + title + situation + task + action + result). Stories that share
    the same ``contentHash`` are duplicates; the repository returns the existing
    row instead of inserting another one.

    ``ADD COLUMN IF NOT EXISTS text`` with no default is a metadata-only change
    on PostgreSQL (existing rows read ``NULL`` = no hash yet computed), so it is
    fast, safe on the production table, and backfills the shared test schema.
    A transaction-scoped advisory lock serializes concurrent first-hit callers
    so the DDL cannot race; ``TRUNCATE`` never drops columns, so the
    process-wide latch survives test teardown. Lazy DDL per ADR-TR-1 (there is
    no migration runner in this repo) — mirrors ``ensure_job_dedup_columns``.

    MUST be called by EVERY repository path that reads or writes the column —
    both ``StoryRepository.create`` and ``StoryRepository.update``. An update
    path that skipped it raised ``psycopg2.UndefinedColumn`` -> HTTP 500 on the
    first ``PUT /stories/{id}`` against a schema that had never run the DDL
    (WIP-BRANCH-AUDIT-2026-07-29 blocker #2).
    """
    global _story_dedup_column_ready
    if _story_dedup_column_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'StoryEntry'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'contentHash'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _story_dedup_column_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (9380710313,))
            cur.execute(
                'ALTER TABLE "StoryEntry" '
                'ADD COLUMN IF NOT EXISTS "contentHash" text'
            )
        conn.commit()
    _story_dedup_column_ready = True


#: Guard so the additive ``Job.coverFailureClearedAt`` column is only ensured
#: once per worker process (see ``ensure_job_cover_suppression_column``).
_job_cover_suppression_column_ready = False


def ensure_job_cover_suppression_column() -> None:
    """Idempotently add the additive ``Job.coverFailureClearedAt`` column.

    ML-W-12: the board-sweep cover-failure backoff (RT-007,
    ``app.workers.board_sweep``) permanently excludes a job from
    ``_next_target`` once it accrues ``max_cover_failures()`` failed
    coverLetter ``AgentRun`` rows inside ``cover_failure_window_hours()`` —
    correct for a job whose letter is genuinely unfabricatable, but with no
    way to clear early. When the failures were actually caused by a pipeline
    bug that has since been fixed and deployed, every job that failed under
    the old broken code stays wedged for the rest of the window: it is
    excluded from selection, so it can never earn the new success that would
    otherwise clear it.

    ``coverFailureClearedAt`` is the additive escape hatch: ops (via
    ``scripts/clear_cover_suppression.py``) stamps ``NOW()`` on a currently-
    suppressed job, and the failure-count queries only count failures AFTER
    this timestamp (or after the job's own last successful coverLetter
    completion, whichever is later) — the historical ``AgentRun`` audit trail
    is never rewritten, only what counts going forward changes.

    ``ADD COLUMN ... timestamptz`` with no default is a metadata-only change
    on PostgreSQL (existing rows read NULL = never cleared), so it is fast and
    safe on the production ``Job`` table and backfills the shared test schema.
    Lazy DDL per ADR-TR-1 (there is no migration runner); mirrors
    ``ensure_job_dedup_columns``.
    """
    global _job_cover_suppression_column_ready
    if _job_cover_suppression_column_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Job'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'coverFailureClearedAt'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _job_cover_suppression_column_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240740,))
            cur.execute(
                'ALTER TABLE "Job" '
                'ADD COLUMN IF NOT EXISTS "coverFailureClearedAt" timestamptz'
            )
        conn.commit()
    _job_cover_suppression_column_ready = True


#: Name of the partial unique index enforcing "one ACTIVE Application per
#: (userId, jobId)" — see ``ensure_application_unique_active_index``.
APPLICATION_UNIQUE_ACTIVE_INDEX = "Application_user_job_active_key"

#: Statuses that count as an "active" (currently-being-pursued) application
#: for the one-per-job invariant below. Mirrors the RT-004 promotion-guard
#: predicate in ``app.routers.applications`` (``submit_application``,
#: ``move_application``) exactly — 'draft' rows are letter-version history
#: (many allowed per job) and 'rejected'/'withdrawn' are terminal (a user may
#: re-apply after either, so multiple closed rows per job are legitimate).
APPLICATION_ACTIVE_STATUSES = ("submitted", "screening", "interview", "offer")

#: Guard so the additive Application unique-active-per-job index is only
#: ensured once per worker process THIS run has actually created it (see
#: ``ensure_application_unique_active_index``). Deliberately NOT set when
#: creation is skipped for existing violations, so a later call (once ops
#: cleans them up) can still succeed without requiring a worker restart.
_application_unique_active_index_ready = False


def ensure_application_unique_active_index() -> None:
    """Idempotently add a partial UNIQUE index enforcing one ACTIVE
    ``Application`` per (``userId``, ``jobId``) on first use.

    NTH-R10 (wave35-sonnet-review-verdict.json): the RT-004 promotion guards
    in ``app.routers.applications`` (``submit_application``,
    ``move_application``) are check-then-act — each SELECTs for an existing
    active application for the job, then promotes its OWN draft, with no
    atomicity between the two. Two concurrent promotions of two DIFFERENT
    draft rows for the SAME job can both pass the SELECT (each reads before
    the other commits) and both pass their own single-row compare-and-swap
    (different rows, both starting 'draft'), minting two active applications
    for one job — the cross-row version of the bug the per-row CAS closed.
    Only the database itself can really close this, hence the partial
    unique index; the callers additionally catch the resulting
    ``UniqueViolation`` and map it to the identical 409 the check-then-act
    guard already returns, so the client contract is unchanged.

    LIVE EVIDENCE (2026-07-29, read-only probe against the production
    ``aether`` schema, ``uat/reports/evidence/models-live/`` — see the
    ML-W-17 fix commit): 2 (userId, jobId) pairs already violate this
    invariant (21 extra rows total — the same live "11+ cards for one job"
    duplication RT-004's board-dedup was built to tolerate). Creating the
    index unconditionally would raise ``UniqueViolation`` on the very first
    call in production and 500 an unrelated request. So: before attempting
    creation, this checks for existing violations and, if any are found,
    logs an honest WARNING (with the violation count) and returns WITHOUT
    creating the index or failing the request — the existing check-then-act
    409 guard remains the only protection for those jobs until ops runs a
    cleanup (e.g. moving all-but-the-most-advanced duplicate to
    'withdrawn'), at which point a later call in this (or a fresh) worker
    process creates the index for real.

    ``CREATE UNIQUE INDEX IF NOT EXISTS`` is additive (ADR-TR-1 lazy DDL, no
    migration runner in this repo) and a transaction-scoped advisory lock
    serializes concurrent first-hit callers so the DDL cannot race, mirroring
    ``ensure_job_dedup_columns``. ``TRUNCATE`` never drops indexes, so this
    survives test-suite teardown.
    """
    global _application_unique_active_index_ready
    if _application_unique_active_index_ready:
        return
    active_statuses_sql = ",".join(f"'{s}'" for s in APPLICATION_ACTIVE_STATUSES)
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: skip everything below once the index
            # already exists (production after cleanup, or a warm process).
            cur.execute(
                "SELECT 1 FROM pg_indexes"
                " WHERE schemaname = ANY(current_schemas(false))"
                " AND tablename = 'Application'"
                " AND indexname = %s",
                (APPLICATION_UNIQUE_ACTIVE_INDEX,),
            )
            if cur.fetchone() is not None:
                _application_unique_active_index_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240751,))
            # Re-check inside the lock — a concurrent first-hit caller may
            # have already created it while this one waited.
            cur.execute(
                "SELECT 1 FROM pg_indexes"
                " WHERE schemaname = ANY(current_schemas(false))"
                " AND tablename = 'Application'"
                " AND indexname = %s",
                (APPLICATION_UNIQUE_ACTIVE_INDEX,),
            )
            if cur.fetchone() is not None:
                conn.commit()
                _application_unique_active_index_ready = True
                return
            cur.execute(
                f'SELECT count(*) FROM ('
                f'  SELECT 1 FROM "Application"'
                f'  WHERE "status" IN ({active_statuses_sql})'
                f'  GROUP BY "userId", "jobId" HAVING count(*) > 1'
                f") violations"
            )
            violation_groups = cur.fetchone()[0]
            if violation_groups:
                logger.warning(
                    "ensure_application_unique_active_index: %d (userId, jobId) "
                    "pair(s) already violate the one-active-application-per-job "
                    "invariant -- SKIPPING index creation so this request does "
                    "not fail. The check-then-act 409 guard in "
                    "app.routers.applications remains the only protection for "
                    "those jobs until the duplicates are cleaned up (NTH-R10).",
                    violation_groups,
                )
                conn.commit()
                return
            cur.execute(
                f'CREATE UNIQUE INDEX IF NOT EXISTS "{APPLICATION_UNIQUE_ACTIVE_INDEX}"'
                f' ON "Application" ("userId", "jobId")'
                f'  WHERE "status" IN ({active_statuses_sql})'
            )
        conn.commit()
    _application_unique_active_index_ready = True
