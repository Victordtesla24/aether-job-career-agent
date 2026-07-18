"""Raw psycopg2 access to the Prisma-managed PostgreSQL database (P2-S01).

The schema itself is owned by Prisma (``packages/db/src/schema.prisma``); the
API reads/writes it with plain SQL. Prisma-style URLs carry a ``?schema=``
query parameter that psycopg2 does not understand, so it is translated into a
``search_path`` option here.

The hosted PostgreSQL caps concurrent connections at 25 and kills idle
transactions, so connections are short-lived: open, use, close.
"""
from __future__ import annotations

import os
import secrets
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg2
import psycopg2.extras


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
