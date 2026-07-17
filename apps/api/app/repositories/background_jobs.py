"""BackgroundJob repository — async generation job spine (GAP-P7-ASYNC-001).

Additive, lazy-idempotent DDL (ADR-TR-1) mirroring
``billing._ensure_billing_tables``: ONE advisory-locked transaction running
``CREATE TABLE / INDEX IF NOT EXISTS`` only, ensured on first use. No FK to
``User`` (matches ``UsageQuota``) so the shared test-suite's ``TRUNCATE "User"``
never trips. There is no migration runner (ADR-TR-1); ``_ensure_table`` is the
sole mechanism that creates the table in production, and the ``migrator`` also
applies the same idempotent DDL at deploy.

Naming verified against ``billing.py`` (quoted PascalCase table, camelCase
columns, ``text`` PK defaulting to ``gen_random_uuid()::text``, ``timestamptz``
audit columns). See ``docs/delivery/PHASE7-ASYNC-BLUEPRINT.md`` §2.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.db import get_connection, new_id, rows_to_dicts

#: Distinct advisory-lock id (next free after billing's 7420240719).
_BACKGROUND_JOB_LOCK = 7420240720

#: Guard so the DDL only runs once per worker process.
_bg_ready = False

_COLS = (
    '"id","userId","agentKey","runId","params","status","arqJobId","result",'
    '"error","attempts","quotaReserved","quotaReservedAt","quotaRefundedAt",'
    '"startedAt","finishedAt","createdAt","updatedAt"'
)


def _reset_bg_ready_for_tests() -> None:
    """Test hook: force the DDL to re-run."""
    global _bg_ready
    _bg_ready = False


def _ensure_table() -> None:
    """Create the BackgroundJob table + indexes on first use (ADR-TR-1).

    Additive and idempotent; serialized by one transaction-scoped advisory lock
    so concurrent ``CREATE TABLE IF NOT EXISTS`` cannot race on ``pg_type``.
    """
    global _bg_ready
    if _bg_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_BACKGROUND_JOB_LOCK,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "BackgroundJob" (
                    "id"              text PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    "userId"          text        NOT NULL,
                    "agentKey"        text        NOT NULL,
                    "runId"           text,
                    "params"          jsonb,
                    "status"          text        NOT NULL DEFAULT 'enqueued',
                    "arqJobId"        text,
                    "result"          jsonb,
                    "error"           text,
                    "attempts"        integer     NOT NULL DEFAULT 0,
                    "quotaReserved"   boolean     NOT NULL DEFAULT false,
                    "quotaReservedAt" timestamptz,
                    "quotaRefundedAt" timestamptz,
                    "startedAt"       timestamptz,
                    "finishedAt"      timestamptz,
                    "createdAt"       timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"       timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "BackgroundJob_userId_createdAt_idx" '
                'ON "BackgroundJob" ("userId", "createdAt" DESC)'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "BackgroundJob_status_idx" '
                'ON "BackgroundJob" ("status")'
            )
        conn.commit()
    _bg_ready = True


class BackgroundJobRepository:
    """CRUD + lifecycle for async generation jobs."""

    def create(
        self,
        user_id: str,
        agent_key: str,
        *,
        run_id: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
        quota_reserved: bool = False,
        arq_job_id: Optional[str] = None,
    ) -> str:
        _ensure_table()
        job_id = new_id()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "BackgroundJob" '
                    '("id","userId","agentKey","runId","params","status","arqJobId",'
                    '"quotaReserved","quotaReservedAt") '
                    "VALUES (%s,%s,%s,%s,%s::jsonb,'enqueued',%s,%s,"
                    "CASE WHEN %s THEN now() ELSE NULL END)",
                    (
                        job_id,
                        user_id,
                        agent_key,
                        run_id,
                        json.dumps(params) if params is not None else None,
                        arq_job_id,
                        quota_reserved,
                        quota_reserved,
                    ),
                )
            conn.commit()
        return job_id

    def set_arq_job_id(self, job_id: str, arq_job_id: Optional[str]) -> None:
        if not arq_job_id:
            return
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "BackgroundJob" SET "arqJobId"=%s,"updatedAt"=now() '
                    'WHERE "id"=%s',
                    (arq_job_id, job_id),
                )
            conn.commit()

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLS} FROM "BackgroundJob" WHERE "id"=%s', (job_id,)
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def get_for_user(self, job_id: str, user_id: str) -> Optional[dict[str, Any]]:
        """Owner-scoped read for the polling endpoint (no cross-user leakage)."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLS} FROM "BackgroundJob" '
                    'WHERE "id"=%s AND "userId"=%s',
                    (job_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def mark_processing(self, job_id: str) -> Optional[dict[str, Any]]:
        """Transition enqueued/processing -> processing (idempotent on retry).

        Returns the current row, or ``None`` if the job is already terminal
        (completed/failed) or missing — the worker then no-ops."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE \"BackgroundJob\" SET \"status\"='processing', "
                    '"startedAt"=COALESCE("startedAt", now()), '
                    '"attempts"="attempts"+1, "updatedAt"=now() '
                    "WHERE \"id\"=%s AND \"status\" IN ('enqueued','processing') "
                    f"RETURNING {_COLS}",
                    (job_id,),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def mark_completed(self, job_id: str, result: Any) -> None:
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE \"BackgroundJob\" SET \"status\"='completed', "
                    '"result"=%s::jsonb, "error"=NULL, "finishedAt"=now(), '
                    '"updatedAt"=now() WHERE "id"=%s',
                    (
                        json.dumps(result, default=str) if result is not None else None,
                        job_id,
                    ),
                )
            conn.commit()

    def mark_failed(self, job_id: str, error: str, *, refunded: bool = False) -> None:
        """Terminal failure: honest error string only, NEVER fixture content;
        ``result`` stays null. Optionally stamps the quota refund time."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE \"BackgroundJob\" SET \"status\"='failed', "
                    '"error"=%s, "finishedAt"=now(), "updatedAt"=now(), '
                    '"quotaRefundedAt"=CASE WHEN %s THEN now() ELSE "quotaRefundedAt" END '
                    'WHERE "id"=%s',
                    (str(error)[:1000], refunded, job_id),
                )
            conn.commit()

    def mark_refunded(self, job_id: str) -> None:
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "BackgroundJob" SET "quotaRefundedAt"=now(),'
                    '"updatedAt"=now() WHERE "id"=%s',
                    (job_id,),
                )
            conn.commit()

    def sweep_stale(
        self, enqueued_secs: int, processing_secs: int
    ) -> list[dict[str, Any]]:
        """Return jobs stuck in a non-terminal state past the staleness window
        (watchdog cron input). Read-only; the caller fails+refunds each."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLS} FROM "BackgroundJob" WHERE '
                    "(\"status\"='enqueued' AND \"createdAt\" "
                    "< now() - make_interval(secs => %s)) OR "
                    "(\"status\"='processing' AND COALESCE(\"startedAt\",\"createdAt\") "
                    "< now() - make_interval(secs => %s))",
                    (enqueued_secs, processing_secs),
                )
                rows = rows_to_dicts(cur)
        return rows
