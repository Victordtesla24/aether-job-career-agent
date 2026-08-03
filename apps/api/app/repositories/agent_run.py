"""AgentRun repository — execution audit trail (P2-S08)."""
from __future__ import annotations

import json
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

_COLUMNS = (
    '"id", "userId", "agentName", "status", "input", "output", "error", '
    '"costUsd", "startedAt", "completedAt", "createdAt"'
)

#: Rows that are still ``running`` but that no live process owns any more
#: (CRITICAL-1). TWO disjoint arms, and the split is the whole safety argument:
#:
#:   * ``heartbeatAt IS NOT NULL`` — the owning process DID stamp progress at
#:     least once, so a missing recent stamp is positive evidence that it died.
#:     Reconciled on heartbeat staleness alone, never on age: a legitimately
#:     long run keeps stamping and is therefore untouchable however old it gets.
#:   * ``heartbeatAt IS NULL`` — no stamp was EVER recorded (the row predates
#:     this watchdog, or its process died before execution began). There is no
#:     liveness evidence either way, so the generous wall-clock ceiling applies.
#:
#: Both timestamps are compared with ``NOW()`` so the naive ``timestamp``
#: columns round-trip through exactly the same server ``TimeZone`` conversion
#: that wrote them — self-consistent regardless of what that setting is.
_ABANDONED_PREDICATE = '''
    "status" = 'running'::"AgentRunStatus"
    AND (
        ("heartbeatAt" IS NOT NULL
         AND "heartbeatAt" < NOW() - make_interval(secs => %s))
        OR
        ("heartbeatAt" IS NULL
         AND COALESCE("startedAt", "createdAt")
             < NOW() - make_interval(secs => %s))
    )
'''

_heartbeat_column_ready = False


def ensure_heartbeat_column() -> None:
    """Additive, idempotent DDL for ``AgentRun.heartbeatAt`` (CRITICAL-1).

    ``AgentRun`` is Prisma-managed (``packages/db/src/schema.prisma``) and the
    column is declared there too; this lazy ``ADD COLUMN IF NOT EXISTS`` is the
    same belt-and-braces pattern ``user_provider_credential`` already uses for
    ``billingAuditJson``, so a deploy that has not re-run Prisma still gets a
    working watchdog. Documentary mirror:
    ``apps/api/migrations/0026_agent_run_heartbeat.sql``.

    ``timestamp`` (not ``timestamptz``) deliberately matches the existing
    ``startedAt``/``completedAt`` columns so every comparison in this module is
    against columns written the same way.
    """
    global _heartbeat_column_ready
    if _heartbeat_column_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'ALTER TABLE "AgentRun" '
                'ADD COLUMN IF NOT EXISTS "heartbeatAt" timestamp'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "AgentRun_status_heartbeatAt_idx" '
                'ON "AgentRun" ("status", "heartbeatAt")'
            )
        conn.commit()
    _heartbeat_column_ready = True


class AgentRunRepository:
    def start(
        self, user_id: str, agent_name: str, input_: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "AgentRun"
                        ("id", "userId", "agentName", "status", "input", "startedAt")
                    VALUES (%s, %s, %s, 'running'::"AgentRunStatus", %s, NOW())
                    RETURNING {_COLUMNS}
                    ''',
                    (new_id(), user_id, agent_name, json.dumps(input_ or {})),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def finish(
        self,
        run_id: str,
        status: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        cost_usd: float | None = None,
    ) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "AgentRun"
                    SET "status" = %s::"AgentRunStatus", "output" = %s,
                        "error" = %s, "costUsd" = %s, "completedAt" = NOW()
                    WHERE "id" = %s
                    RETURNING {_COLUMNS}
                    ''',
                    (status, json.dumps(output or {}), error, cost_usd, run_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def heartbeat(self, run_id: str) -> bool:
        """Stamp liveness for a RUNNING run. Returns False once it is terminal.

        The ``status = 'running'`` predicate is what makes the heartbeat loop
        self-terminating and makes a stamp on an already-reconciled run
        impossible — a heartbeat can never resurrect a finished row.
        """
        ensure_heartbeat_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AgentRun" SET "heartbeatAt" = NOW() '
                    'WHERE "id" = %s AND "status" = \'running\'::"AgentRunStatus"',
                    (run_id,),
                )
                stamped = cur.rowcount > 0
            conn.commit()
        return stamped

    def count_abandoned(
        self, heartbeat_stale_seconds: float, max_run_seconds: float
    ) -> int:
        """How many ``running`` rows currently have nothing alive behind them."""
        ensure_heartbeat_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT COUNT(*) FROM "AgentRun" WHERE {_ABANDONED_PREDICATE}',
                    (heartbeat_stale_seconds, max_run_seconds),
                )
                row = cur.fetchone()
            conn.commit()
        return int(row[0]) if row else 0

    def list_abandoned(
        self,
        heartbeat_stale_seconds: float,
        max_run_seconds: float,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Abandoned ``running`` rows plus the numbers the honest error cites."""
        ensure_heartbeat_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    SELECT "id", "userId", "agentName", "startedAt", "createdAt",
                           "heartbeatAt",
                           EXTRACT(EPOCH FROM (
                               NOW() - COALESCE("startedAt", "createdAt")
                           )) AS "ageSeconds",
                           CASE WHEN "heartbeatAt" IS NULL THEN NULL ELSE
                               EXTRACT(EPOCH FROM (NOW() - "heartbeatAt"))
                           END AS "heartbeatAgeSeconds"
                    FROM "AgentRun"
                    WHERE {_ABANDONED_PREDICATE}
                    ORDER BY COALESCE("startedAt", "createdAt") ASC
                    LIMIT %s
                    ''',
                    (heartbeat_stale_seconds, max_run_seconds, limit),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows

    def fail_abandoned(self, run_id: str, error: str) -> bool:
        """Atomically fail ONE abandoned run. First-terminal-wins.

        The ``status = 'running'`` guard means a reconciler racing a worker that
        is finishing the very same run loses cleanly: whoever writes the
        terminal state first wins and the other observes ``False``. The row is
        never deleted and is never marked ``completed`` — an abandoned run
        produced no output, and saying otherwise would be a fabrication.
        """
        ensure_heartbeat_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AgentRun" '
                    'SET "status" = \'failed\'::"AgentRunStatus", "error" = %s, '
                    '    "completedAt" = NOW() '
                    'WHERE "id" = %s AND "status" = \'running\'::"AgentRunStatus"',
                    (error, run_id),
                )
                won = cur.rowcount > 0
            conn.commit()
        return won

    def set_billing_audit(
        self, run_id: str, audit: dict[str, Any]
    ) -> None:
        """Persist the billing-provenance audit for a run (GAP-D3).

        Writes the additive ``billingAuditJson`` column (created by the lazy DDL
        in ``user_provider_credential._ensure_user_agent_tables``). Best-effort:
        a missing column must never fail an otherwise-successful run, so the
        caller guards this.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AgentRun" SET "billingAuditJson" = %s WHERE "id" = %s',
                    (json.dumps(audit), run_id),
                )
            conn.commit()

    def list_recent(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "AgentRun" WHERE "userId" = %s '
                    'ORDER BY "createdAt" DESC LIMIT %s',
                    (user_id, limit),
                )
                return rows_to_dicts(cur)

    def get_by_id(self, run_id: str, user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "AgentRun" '
                    'WHERE "id" = %s AND "userId" = %s',
                    (run_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def last_run_by_agent(self, user_id: str) -> dict[str, dict[str, Any]]:
        """Latest run per agent name for the dashboard's agent grid."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    SELECT DISTINCT ON ("agentName") {_COLUMNS}
                    FROM "AgentRun" WHERE "userId" = %s
                    ORDER BY "agentName", "createdAt" DESC
                    ''',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return {row["agentName"]: row for row in rows}

    def recent_runs_by_agent(
        self, user_id: str, window: int = 3
    ) -> dict[str, list[dict[str, Any]]]:
        """The most-recent ``window`` runs per agent name, newest-first.

        Backs the windowed, transient-tolerant agent status on the Agents
        screen (ML-agents-err-001): the catalog must tell a one-off transient
        upstream blip apart from chronic breakage, which needs the last N runs
        per agent — not just the single latest that ``last_run_by_agent``
        returns. Additive; ``last_run_by_agent`` and its callers are unchanged.
        Same column set as the other reads, scoped to the caller's own runs.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    SELECT {_COLUMNS} FROM (
                        SELECT {_COLUMNS},
                               ROW_NUMBER() OVER (
                                   PARTITION BY "agentName"
                                   ORDER BY "createdAt" DESC
                               ) AS _rn
                        FROM "AgentRun" WHERE "userId" = %s
                    ) ranked
                    WHERE _rn <= %s
                    ORDER BY "agentName", "createdAt" DESC
                    ''',
                    (user_id, window),
                )
                rows = rows_to_dicts(cur)
        result: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(row["agentName"], []).append(row)
        return result
