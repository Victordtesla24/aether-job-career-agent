"""TTL cache for fetched company facts (AUD-COV-3).

One row per (normalized) company name, holding the last successfully-fetched
factual snapshot of that company plus the URL it was sourced from and when it
was fetched. Read by :func:`app.services.company_facts.fetch_company_facts`
before any live network call, so a company already fetched inside the TTL
window never triggers a second live fetch.

The table is additive and keyed by company name only (no ``userId``, no FK to
``User``) — mirroring ``JobSourceStatus``/``GoogleCredential`` — so the shared
test-suite's per-test ``TRUNCATE`` never trips over it, and one cached fact
about a real company is legitimately shared across every user who applies
there. First-hit creation is serialized by a transaction-scoped advisory lock
so concurrent ``CREATE TABLE IF NOT EXISTS`` cannot race on Postgres's
``pg_type`` index (same pattern as every other lazily-created table in this
repo — see ``JobSourceStatusRepository._ensure_table``).
"""
from __future__ import annotations

from typing import Any, Optional

from app.db import get_connection, rows_to_dicts

#: Distinct advisory-lock id (see AgentConfig 7420240711, User 7420240712,
#: CareerProfile 7420240713, OutreachTask 7420240714, GoogleCredential
#: 7420240715, JobSourceStatus 7420240716, ... — this repo's convention is one
#: distinct id per lazily-created table).
_TABLE_LOCK = 7420260818

_SELECT_COLS = '"company", "facts", "sourceUrl", "fetchedAt"'

#: Guard so table creation only runs once per worker process.
_table_ready = False


def _normalize(company: str) -> str:
    """Case-insensitive cache key — "Nearmap" and "NEARMAP" are one entry."""
    return (company or "").strip().casefold()


class CompanyFactsRepository:
    """Read/write access to the ``CompanyFactsCache`` store."""

    def _ensure_table(self) -> None:
        global _table_ready
        if _table_ready:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Fast path: skip the ACCESS EXCLUSIVE-taking DDL when the table
                # already exists (mirrors JobSourceStatus/GoogleCredential).
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_name = 'CompanyFactsCache'"
                    " AND table_schema = ANY(current_schemas(false))"
                )
                row = cur.fetchone()
                if row and row[0] == 1:
                    _table_ready = True
                    return
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TABLE_LOCK,))
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS "CompanyFactsCache" (
                        "company"    text PRIMARY KEY,
                        "facts"      text NOT NULL,
                        "sourceUrl"  text,
                        "fetchedAt"  timestamptz NOT NULL DEFAULT now()
                    )
                    '''
                )
            conn.commit()
        _table_ready = True

    def get_fresh(self, company: str, *, ttl_seconds: float) -> Optional[dict[str, Any]]:
        """The cached row for ``company`` iff younger than ``ttl_seconds``.

        Freshness is decided by the DATABASE clock (``EXTRACT(EPOCH FROM (now()
        - "fetchedAt"))``), not the app server's, mirroring
        ``JobSourceStatusRepository.latest_block`` — the hosted Postgres clock
        can run measurably ahead of the app server. Returns ``None`` on a
        cold, missing, or stale entry; the caller's honest cache-miss path
        re-fetches live rather than ever serving expired facts as current.
        """
        self._ensure_table()
        key = _normalize(company)
        if not key:
            return None
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_SELECT_COLS}, '
                    'EXTRACT(EPOCH FROM (now() - "fetchedAt")) AS "ageSeconds" '
                    'FROM "CompanyFactsCache" WHERE "company" = %s',
                    (key,),
                )
                rows = rows_to_dicts(cur)
        if not rows or float(rows[0]["ageSeconds"]) > ttl_seconds:
            return None
        return rows[0]

    def upsert(self, company: str, *, facts: str, source_url: str | None) -> None:
        """Insert or overwrite the cached facts for ``company``."""
        self._ensure_table()
        key = _normalize(company)
        if not key:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "CompanyFactsCache"
                        ("company", "facts", "sourceUrl", "fetchedAt")
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT ("company") DO UPDATE SET
                        "facts" = EXCLUDED."facts",
                        "sourceUrl" = EXCLUDED."sourceUrl",
                        "fetchedAt" = now()
                    ''',
                    (key, facts, source_url),
                )
            conn.commit()
