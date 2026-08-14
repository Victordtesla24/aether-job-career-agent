"""RunPlan repository — the Supervisor's plan, recorded SERVER-side (ADR-AGI-3).

Why this table exists at all: the only "run a set of agents" control the product
shipped is client-owned (``OrchestrationMap.tsx``'s ``runPlan``). Closing the tab
aborts the batch and the server holds no record that a plan was ever running —
so nothing can narrate it honestly afterwards, nothing can say where it halted,
and nothing can tell the user what was NOT attempted.

Additive, lazy-idempotent DDL (ADR-TR-1), following
``repositories/background_jobs.py`` exactly: ONE advisory-locked transaction
running ``CREATE TABLE / INDEX IF NOT EXISTS`` only, ensured on first use. There
is no migration runner in this repo; ``_ensure_table`` is the sole mechanism that
creates the table in production, and the migrator applies the same idempotent DDL
at deploy. No FK to ``User`` (matching ``UsageQuota`` / ``BackgroundJob``) so the
shared test-suite's ``TRUNCATE "User"`` never trips.

Nothing here dispatches, reserves or bills: this module records what a plan IS
and what each of its steps DID.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.db import get_connection, new_id, rows_to_dicts

logger = logging.getLogger(__name__)

#: Distinct advisory-lock id. Registry of table-DDL advisory locks in this repo
#: (grep pg_advisory_xact_lock): db.py 7420240712 & 7420240720; routers/agents
#: 7420240711; interviews/networking 7420240713/714; google_credential 715;
#: job_source_status/provider_credential/gmail_service 716; user_provider_credential
#: 717; gmail_account 718; billing 719; admin 721; background_jobs 722;
#: EmailThread aiScore (gmail_service) 723; run_plan 724.
#: Next genuinely-free id: 725.
_RUN_PLAN_LOCK = 7420240724

_ready = False

_COLS = (
    '"id","userId","status","initiator","concurrency","spacingSeconds",'
    '"steps","summary","haltedAtStep","haltReason",'
    '"startedAt","finishedAt","createdAt","updatedAt"'
)

#: Terminal plan states — the only ones a finished plan may hold.
#: ``partial`` exists because the two-value alternative would force a lie: a plan
#: whose spine broke while nine enrichment agents ran is neither a success nor a
#: stop, and calling it either would misreport what the user actually got.
TERMINAL_STATUSES = ("completed", "partial", "halted", "failed")


def _reset_ready_for_tests() -> None:
    """Test hook: force the DDL to re-run."""
    global _ready
    _ready = False


def _ensure_table() -> None:
    global _ready
    if _ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_RUN_PLAN_LOCK,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "RunPlan" (
                    "id"             text PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    "userId"         text        NOT NULL,
                    "status"         text        NOT NULL DEFAULT 'planned',
                    "initiator"      text        NOT NULL DEFAULT 'user',
                    "concurrency"    integer     NOT NULL DEFAULT 1,
                    "spacingSeconds" double precision NOT NULL DEFAULT 0,
                    "steps"          jsonb       NOT NULL,
                    "summary"        jsonb,
                    "haltedAtStep"   text,
                    "haltReason"     text,
                    "startedAt"      timestamptz,
                    "finishedAt"     timestamptz,
                    "createdAt"      timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"      timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "RunPlan_userId_createdAt_idx" '
                'ON "RunPlan" ("userId", "createdAt" DESC)'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "RunPlan_status_idx" '
                'ON "RunPlan" ("status")'
            )
        conn.commit()
    _ready = True


class RunPlanRepository:
    """CRUD + step-state lifecycle for a recorded Supervisor plan."""

    def create(
        self,
        user_id: str,
        *,
        steps: list[dict[str, Any]],
        concurrency: int,
        spacing_seconds: float,
        initiator: str = "user",
    ) -> str:
        """Persist a plan in the ``planned`` state with every step ``pending``.

        The step rows are stored verbatim from the planner (including each
        step's rationale) so the plan the user was SHOWN and the plan that RAN
        are provably the same object — not two independent computations that
        could drift between the preview and the dispatch.
        """
        _ensure_table()
        plan_id = new_id()
        stored = [{**step, "state": "pending", "detail": {}} for step in steps]
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "RunPlan" '
                    '("id","userId","status","initiator","concurrency",'
                    '"spacingSeconds","steps") '
                    "VALUES (%s,%s,'planned',%s,%s,%s,%s::jsonb)",
                    (
                        plan_id,
                        user_id,
                        initiator,
                        int(concurrency),
                        float(spacing_seconds),
                        json.dumps(stored),
                    ),
                )
            conn.commit()
        return plan_id

    def get(self, plan_id: str) -> Optional[dict[str, Any]]:
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLS} FROM "RunPlan" WHERE "id"=%s', (plan_id,)
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def get_for_user(self, plan_id: str, user_id: str) -> Optional[dict[str, Any]]:
        """Owner-scoped read. A plan belonging to anyone else resolves to
        ``None`` so the caller returns an honest 404 and never confirms that
        someone else's plan exists."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLS} FROM "RunPlan" WHERE "id"=%s AND "userId"=%s',
                    (plan_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def list_recent(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLS} FROM "RunPlan" WHERE "userId"=%s '
                    'ORDER BY "createdAt" DESC LIMIT %s',
                    (user_id, max(0, int(limit))),
                )
                return rows_to_dicts(cur)

    def mark_running(self, plan_id: str) -> bool:
        """``planned`` → ``running``. Returns True iff THIS call transitioned it,
        so a re-delivered queue message cannot restart a plan already in
        flight."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE \"RunPlan\" SET \"status\"='running',"
                    '"startedAt"=COALESCE("startedAt", now()),"updatedAt"=now() '
                    "WHERE \"id\"=%s AND \"status\"='planned' RETURNING \"id\"",
                    (plan_id,),
                )
                claimed = cur.fetchone() is not None
            conn.commit()
        return claimed

    def record_step_state(
        self, plan_id: str, key: str, state: str, detail: dict[str, Any] | None = None
    ) -> None:
        """Stamp one step's state on the stored plan.

        A jsonb rewrite of the single matching element: narration may only be
        fed from a PERSISTED transition (the SSE module already refuses to
        animate steps nothing records), so this write is what makes a live
        plan narratable at all.
        """
        _ensure_table()
        payload = json.dumps({"state": state, "detail": detail or {}})
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    UPDATE "RunPlan" SET "steps" = (
                        SELECT jsonb_agg(
                            CASE WHEN step->>'key' = %s
                                 THEN step || %s::jsonb
                                 ELSE step END
                            ORDER BY ord
                        )
                        FROM jsonb_array_elements("steps")
                             WITH ORDINALITY AS t(step, ord)
                    ), "updatedAt" = now()
                    WHERE "id" = %s
                    ''',
                    (key, payload, plan_id),
                )
            conn.commit()

    def finish(
        self,
        plan_id: str,
        status: str,
        *,
        summary: dict[str, Any] | None = None,
        halted_at_step: str | None = None,
        halt_reason: str | None = None,
    ) -> bool:
        """Atomic first-terminal-wins finish. Returns True iff THIS call
        performed the transition, mirroring ``BackgroundJob.mark_completed`` so a
        watchdog that already terminated the plan cannot be stomped."""
        _ensure_table()
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"{status!r} is not a terminal RunPlan status")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "RunPlan" SET "status"=%s,"summary"=%s::jsonb,'
                    '"haltedAtStep"=%s,"haltReason"=%s,"finishedAt"=now(),'
                    '"updatedAt"=now() '
                    "WHERE \"id\"=%s AND \"status\" IN ('planned','running') "
                    'RETURNING "id"',
                    (
                        status,
                        json.dumps(summary, default=str) if summary is not None else None,
                        halted_at_step,
                        halt_reason,
                        plan_id,
                    ),
                )
                claimed = cur.fetchone() is not None
            conn.commit()
        return claimed
