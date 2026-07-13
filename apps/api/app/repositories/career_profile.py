"""CareerProfile persistence — consolidated career-data store (GAP-P4-047).

One row per ``(userId, source)`` where ``source`` ∈ {github, portfolio,
linkedin}. Each row records the last ingestion's ``status``, the source
``url``, the normalized ``content`` (jsonb), a flattened text ``summary`` used
as tailoring / cover-letter evidence, and an explicit per-source ``error``
state when a fetch/parse fails (D-0031: failures surface honestly, never as
fabricated data).

The table is additive and carries no FK to ``User`` — mirroring ``AgentConfig``
/ ``AgentProvider`` — so the shared test-suite's ``TRUNCATE "User"`` never trips
over it. First-hit creation is serialized by a transaction-scoped advisory lock
so concurrent ``CREATE TABLE IF NOT EXISTS`` cannot race on Postgres's
``pg_type`` index.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.db import get_connection, rows_to_dicts

#: Canonical career-data sources, in the order they join the evidence corpus.
CAREER_SOURCES = ("github", "portfolio", "linkedin")

#: Distinct advisory-lock id (see AgentConfig/User column bootstraps).
_CAREER_TABLE_LOCK = 7420240713

#: Columns returned by every read so callers get a stable shape.
_SELECT_COLS = (
    '"userId", "source", "status", "url", "content", "summary", "error", "syncedAt"'
)

#: Guard so table creation only runs once per worker process.
_table_ready = False


class CareerProfileRepository:
    """Read/write access to the ``CareerProfile`` store."""

    def _ensure_table(self) -> None:
        global _table_ready
        if _table_ready:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (_CAREER_TABLE_LOCK,))
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS "CareerProfile" (
                        "userId"    text NOT NULL,
                        "source"    text NOT NULL,
                        "status"    text NOT NULL DEFAULT 'pending',
                        "url"       text,
                        "content"   jsonb,
                        "summary"   text,
                        "error"     text,
                        "syncedAt"  timestamptz,
                        "updatedAt" timestamptz NOT NULL DEFAULT NOW(),
                        PRIMARY KEY ("userId", "source")
                    )
                    '''
                )
            conn.commit()
        _table_ready = True

    def upsert(
        self,
        user_id: str,
        source: str,
        *,
        status: str,
        url: Optional[str] = None,
        content: Optional[dict[str, Any]] = None,
        summary: Optional[str] = None,
        error: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert or replace the row for ``(user_id, source)``."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "CareerProfile"
                        ("userId", "source", "status", "url", "content", "summary",
                         "error", "syncedAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT ("userId", "source") DO UPDATE SET
                        "status"    = EXCLUDED."status",
                        "url"       = EXCLUDED."url",
                        "content"   = EXCLUDED."content",
                        "summary"   = EXCLUDED."summary",
                        "error"     = EXCLUDED."error",
                        "syncedAt"  = EXCLUDED."syncedAt",
                        "updatedAt" = NOW()
                    RETURNING {_SELECT_COLS}
                    ''',
                    (
                        user_id,
                        source,
                        status,
                        url,
                        json.dumps(content) if content is not None else None,
                        summary,
                        error,
                    ),
                )
                row = rows_to_dicts(cur)[0]
            conn.commit()
        return row

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        """All stored career-data rows for ``user_id``."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_SELECT_COLS} FROM "CareerProfile" WHERE "userId" = %s',
                    (user_id,),
                )
                return rows_to_dicts(cur)

    def get(self, user_id: str, source: str) -> Optional[dict[str, Any]]:
        """The stored row for one ``source`` (or ``None``)."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_SELECT_COLS} FROM "CareerProfile" '
                    'WHERE "userId" = %s AND "source" = %s',
                    (user_id, source),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None
