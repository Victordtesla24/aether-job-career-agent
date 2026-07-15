"""Per-user, per-source discovery sync status (GAP-SRC-002).

One row per (userId, source) recording the outcome of the most recent scout
run for that source: how many postings it fetched and persisted, the last
error (if any), and an ``ok``/``error``/``skipped`` status. This is what makes
per-source discovery health honestly visible instead of a silent ``persisted=0``.

The table is additive and carries no FK to ``User`` — mirroring
``GoogleCredential``/``AgentConfig`` — so the shared test-suite's ``TRUNCATE``
never trips over it. First-hit creation is serialized by a transaction-scoped
advisory lock so concurrent ``CREATE TABLE IF NOT EXISTS`` cannot race on
Postgres's ``pg_type`` index.
"""
from __future__ import annotations

from typing import Any, Optional

from app.db import get_connection, rows_to_dicts

#: Distinct advisory-lock id (see AgentConfig 7420240711, User 7420240712,
#: CareerProfile 7420240713, OutreachTask 7420240714, GoogleCredential
#: 7420240715).
_STATUS_TABLE_LOCK = 7420240716

_SELECT_COLS = (
    '"userId", "source", "lastSyncAt", "lastFetched", "lastPersisted", '
    '"lastError", "status"'
)

#: Guard so table creation only runs once per worker process.
_table_ready = False


class JobSourceStatusRepository:
    """Read/write access to the ``JobSourceStatus`` store."""

    def _ensure_table(self) -> None:
        if _table_ready:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Fast path: skip the ACCESS EXCLUSIVE-taking DDL when the table
                # already exists (mirrors GoogleCredential / user profile cols).
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_name = 'JobSourceStatus'"
                    " AND table_schema = ANY(current_schemas(false))"
                )
                row = cur.fetchone()
                if row and row[0] == 1:
                    self._mark_ready()
                    return
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (_STATUS_TABLE_LOCK,))
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS "JobSourceStatus" (
                        "userId"        text NOT NULL,
                        "source"        text NOT NULL,
                        "lastSyncAt"    timestamptz NOT NULL DEFAULT now(),
                        "lastFetched"   integer NOT NULL DEFAULT 0,
                        "lastPersisted" integer NOT NULL DEFAULT 0,
                        "lastError"     text,
                        "status"        text NOT NULL DEFAULT 'ok',
                        PRIMARY KEY ("userId", "source")
                    )
                    '''
                )
            conn.commit()
        self._mark_ready()

    @staticmethod
    def _mark_ready() -> None:
        global _table_ready
        _table_ready = True

    def upsert(
        self,
        user_id: str,
        source: str,
        *,
        fetched: int,
        persisted: int,
        error: Optional[str],
        status: str,
    ) -> dict[str, Any]:
        """Insert or overwrite the (userId, source) status row for a run."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "JobSourceStatus"
                        ("userId", "source", "lastSyncAt", "lastFetched",
                         "lastPersisted", "lastError", "status")
                    VALUES (%s, %s, now(), %s, %s, %s, %s)
                    ON CONFLICT ("userId", "source") DO UPDATE SET
                        "lastSyncAt" = now(),
                        "lastFetched" = EXCLUDED."lastFetched",
                        "lastPersisted" = EXCLUDED."lastPersisted",
                        "lastError" = EXCLUDED."lastError",
                        "status" = EXCLUDED."status"
                    RETURNING {_SELECT_COLS}
                    ''',
                    (user_id, source, fetched, persisted, error, status),
                )
                row = rows_to_dicts(cur)[0]
            conn.commit()
        return row

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        """Every source's latest sync status for a user, ordered by source."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_SELECT_COLS} FROM "JobSourceStatus" '
                    'WHERE "userId" = %s ORDER BY "source"',
                    (user_id,),
                )
                return rows_to_dicts(cur)
