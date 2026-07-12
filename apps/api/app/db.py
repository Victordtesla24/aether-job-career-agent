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

    ``targetRole``/``location``/``agentConfig`` were introduced after the
    original Prisma migration and only ALTER-added to the production ``aether``
    schema. The shared test schema (``aether_test``) predates them, so any
    query that reads these columns would fail there with ``UndefinedColumn``.

    ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` is a no-op where the columns
    already exist (production) and safely backfills them everywhere else. A
    transaction-scoped advisory lock serializes concurrent first-hit callers so
    the DDL can't race, mirroring the pattern used for the agent config tables.
    ``TRUNCATE`` never drops columns, so this survives the test-suite teardown.
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
                " AND column_name IN ('targetRole', 'location', 'agentConfig')"
            )
            row = cur.fetchone()
            if row and row[0] == 3:
                _user_profile_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240712,))
            cur.execute('ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "targetRole" text')
            cur.execute('ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "location" text')
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "agentConfig" jsonb'
            )
        conn.commit()
    _user_profile_columns_ready = True
