"""AgentRun repository — execution audit trail (P2-S08)."""
from __future__ import annotations

import json
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

_COLUMNS = (
    '"id", "userId", "agentName", "status", "input", "output", "error", '
    '"costUsd", "startedAt", "completedAt", "createdAt"'
)


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
