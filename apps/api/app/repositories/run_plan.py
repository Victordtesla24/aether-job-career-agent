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

#: Classid for the TWO-ARGUMENT advisory lock that serializes plan ADMISSION
#: (``pg_advisory_xact_lock(classid, hashtext(userId))``), mirroring
#: ``background_jobs._SINGLETON_ENQUEUE_LOCK_CLASS`` (20240722) — a separate
#: Postgres key space from the one-argument bigint DDL locks above, so the two
#: forms cannot collide. Distinct classid so a plan admission and a singleton
#: enqueue for the same user never serialize against each other.
_PLAN_ADMISSION_LOCK_CLASS = 20240724

#: Name of the partial unique index enforcing ONE live plan per user.
#:
#: Versioned for the same reason as ``background_jobs._SINGLETON_INDEX_NAME``:
#: ``CREATE UNIQUE INDEX IF NOT EXISTS`` will not re-write an index that already
#: exists, so changing the RULE under the OLD name leaves every database that
#: ran an earlier build still enforcing the earlier rule while the code claims
#: otherwise. Bump this name whenever the predicate or the key columns change.
RUN_PLAN_ACTIVE_INDEX = "RunPlan_active_per_user_v1_idx"

#: Plan statuses that HOLD the per-user admission slot. Kept next to
#: :data:`TERMINAL_STATUSES` (which is its exact complement) because the index
#: predicate below and the admission query must never disagree.
LIVE_STATUSES = ("planned", "running")

_ready = False

#: Set only once the admission index verifiably EXISTS — deliberately not folded
#: into ``_ready``; see :func:`_ensure_admission_index`.
_index_ready = False

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

#: What a released plan SAYS about itself. A plan row is the only record that a
#: run ever existed, so a release states which question it answered — "did a
#: worker ever pick this up?" vs "did the worker die mid-run?" — and never
#: silently deletes or silently re-uses the row. Whatever step states the plan
#: had persisted before it went quiet are left exactly as they were: that IS the
#: last thing known to be true about it.
_STALE_PLANNED_REASON = (
    "no worker claimed this plan within the queue window, so it was released "
    "and never started"
)
_STALE_RUNNING_REASON = (
    "the worker stopped reporting on this plan past its execution ceiling, so "
    "it was released; the steps below are the last states it recorded"
)


def _reset_ready_for_tests() -> None:
    """Test hook: force the DDL to re-run."""
    global _ready, _index_ready
    _ready = False
    _index_ready = False


def _ensure_admission_index() -> None:
    """Idempotently add the partial UNIQUE index behind plan admission.

    Separate from the table DDL, and guarded by its OWN flag, because unlike a
    ``CREATE TABLE`` this statement is DATA-DEPENDENT: it fails while any user
    still holds two live plans — the exact state the race being closed here
    produced, so the databases most in need of the index are the ones most
    likely to reject it. Two consequences, both deliberate:

    * it runs inside a SAVEPOINT and NEVER propagates. Letting it raise would
      turn the first plan request after a deploy into a 500 on an unrelated
      path, and the advisory lock in :meth:`RunPlanRepository.create_admitted`
      still enforces the rule across processes without it. The log says which
      guarantee the deployment is actually running on — the code never claims
      an index it does not have;
    * ``_index_ready`` is set ONLY when the index verifiably exists, so a later
      call retries once an operator has finished the duplicates. Baking the
      skip into the same one-shot flag as the table would mean a deployment
      that started dirty stayed unindexed until someone restarted every worker
      (``db.ensure_application_unique_active_index`` records the same reasoning).
    """
    global _index_ready
    if _index_ready:
        return
    live = ", ".join(f"'{s}'" for s in LIVE_STATUSES)
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: one catalog lookup once the index is there.
            cur.execute(
                "SELECT 1 FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE c.relname = %s "
                "AND n.nspname = ANY(current_schemas(false))",
                (RUN_PLAN_ACTIVE_INDEX,),
            )
            if cur.fetchone() is not None:
                _index_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_RUN_PLAN_LOCK,))
            cur.execute("SAVEPOINT run_plan_active_idx")
            try:
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    f'"{RUN_PLAN_ACTIVE_INDEX}" ON "RunPlan" ("userId") '
                    f'WHERE "status" IN ({live})'
                )
            except Exception:  # noqa: BLE001 — data-dependent; never fatal here
                cur.execute("ROLLBACK TO SAVEPOINT run_plan_active_idx")
                logger.warning(
                    "%s could not be created — a user already holds more than "
                    "one plan in %s. Admission still holds on the advisory lock "
                    "in create_admitted; finish the duplicates and the next "
                    "call adds the index.",
                    RUN_PLAN_ACTIVE_INDEX,
                    LIVE_STATUSES,
                    exc_info=True,
                )
            else:
                cur.execute("RELEASE SAVEPOINT run_plan_active_idx")
                _index_ready = True
        conn.commit()


def _ensure_table() -> None:
    global _ready
    if _ready:
        _ensure_admission_index()
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
    # R-1 admission, DB half: at most ONE live plan per user. The advisory lock
    # in ``create_admitted`` serializes the check; THIS is what makes the rule
    # hold even if a future caller forgets to take it, which is the difference
    # between an invariant and a convention. Its own transaction and its own
    # flag — see :func:`_ensure_admission_index`.
    _ensure_admission_index()


class RunPlanRepository:
    """CRUD + step-state lifecycle for a recorded Supervisor plan."""

    def create_admitted(
        self,
        user_id: str,
        *,
        steps: list[dict[str, Any]],
        concurrency: int,
        spacing_seconds: float,
        planned_stale_seconds: float,
        running_stale_seconds: float,
        initiator: str = "user",
    ) -> tuple[str, bool]:
        """Admit ONE plan per user, then persist it ``planned`` / all-pending.

        Returns ``(plan_id, created)`` — ``created`` is True only when THIS call
        inserted the row; when the user already holds a live plan the EXISTING
        id comes back and nothing is inserted, so the caller can refuse
        honestly and point at the run the user already has. The shape
        deliberately mirrors ``BackgroundJobRepository.create_singleton``.

        WHY (ADR-AGI-3 R-1, and ``BUILD-P1A.md`` open item #3): the silo class
        closes the per-BACKEND race — a second plan's ``scout``/``submission``
        step loses the DB claim and refuses. The other 13 backends take no
        claim, so without this a double-click produced two plans and up to 26
        duplicate METERED dispatches from one user action. Admission is the
        plan-level equivalent of that claim.

        Atomicity: the release, the check and the insert are ONE transaction,
        serialized by a transaction-scoped advisory lock on the user, so two API
        processes cannot both pass the "no live plan" check; the partial unique
        index from :func:`_ensure_table` is the second, independent line of
        defence. The lock is released by the commit, i.e. only once the row the
        next caller must see is durable.

        STALENESS RELEASE (the caveat the build's own recommendation carried): a
        worker SIGKILLed mid-plan leaves a ``running`` row forever, which would
        lock the user out of Run-everything with no way back. A live plan older
        than its window is therefore failed HONESTLY here — recorded, never
        deleted — before the check. Both windows are the CALLER's to supply so
        this module holds no dispatch policy; the router passes the same two the
        job watchdog uses, and the comparison runs entirely on the DATABASE
        clock (the hosted Postgres is measured ~3s ahead of the app server).

        The step rows are stored verbatim from the planner (including each
        step's rationale) so the plan the user was SHOWN and the plan that RAN
        are provably the same object — not two independent computations that
        could drift between the preview and the dispatch.
        """
        _ensure_table()
        plan_id = new_id()
        stored = [{**step, "state": "pending", "detail": {}} for step in steps]
        live = ", ".join(f"'{s}'" for s in LIVE_STATUSES)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
                    (_PLAN_ADMISSION_LOCK_CLASS, user_id),
                )
                cur.execute(
                    f'''
                    UPDATE "RunPlan" SET
                        "status"='failed',
                        "haltReason" = CASE WHEN "status"='running' THEN %s ELSE %s END,
                        "summary" = COALESCE("summary", '{{}}'::jsonb)
                            || jsonb_build_object('releasedAsStale', true),
                        "finishedAt"=now(), "updatedAt"=now()
                    WHERE "userId"=%s AND "status" IN ({live})
                      AND COALESCE("startedAt","createdAt") < now() - make_interval(
                          secs => CASE WHEN "status"='running' THEN %s ELSE %s END)
                    RETURNING "id"
                    ''',
                    (
                        _STALE_RUNNING_REASON,
                        _STALE_PLANNED_REASON,
                        user_id,
                        float(running_stale_seconds),
                        float(planned_stale_seconds),
                    ),
                )
                released = [r[0] for r in cur.fetchall()]
                if released:
                    logger.warning(
                        "released %d stale run plan(s) for user %s: %s",
                        len(released), user_id, ", ".join(released),
                    )
                cur.execute(
                    f'SELECT "id" FROM "RunPlan" WHERE "userId"=%s '
                    f'AND "status" IN ({live}) ORDER BY "createdAt" LIMIT 1',
                    (user_id,),
                )
                existing = cur.fetchone()
                if existing is not None:
                    conn.commit()
                    return str(existing[0]), False
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
        return plan_id, True

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
