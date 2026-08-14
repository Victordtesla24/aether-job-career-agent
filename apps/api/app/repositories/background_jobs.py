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
#: (7420240720 was WRONG — it collides with db.py:ensure_admin_user_columns; fixed
#: per reviewer BLOCKING-4.)
_BACKGROUND_JOB_LOCK = 7420240722

#: Classid for the TWO-ARGUMENT advisory lock that serializes singleton
#: enqueues (``pg_advisory_xact_lock(classid, hashtext(key))``). Deliberately a
#: separate namespace from the one-argument bigint DDL locks above — the two
#: forms cannot collide with each other in Postgres, and no other call site in
#: this repo uses the two-argument form (grep ``pg_advisory_xact_lock(%s,``).
_SINGLETON_ENQUEUE_LOCK_CLASS = 20240722

#: Guard so the DDL only runs once per worker process.
_bg_ready = False

#: Non-terminal statuses — the only ones a terminal transition may claim.
_NON_TERMINAL = ("enqueued", "processing")

#: Agents of which a user may have at most ONE run in flight at a time
#: (MON-020). ``scout`` is a whole-account discovery pass: two concurrent
#: passes search the same boards for the same user, double the upstream API
#: calls and race each other's upserts, so a second request is not a second
#: unit of work — it is the same one, asked for twice.
#:
#: ``tailor``/``coverLetter``/``pipeline`` are deliberately NOT here: those are
#: per-job units of work and running several at once is legitimate.
#:
#: U-AGI P1-A (F-R8-1) extends this from ``scout`` alone to the whole ``silo``
#: execution class of the charter (``routers.agents._EXEC_CLASS_BY_BACKEND``),
#: because that field is DECORATIVE without a database backstop: enabling
#: ``AETHER_ASYNC_GENERATION`` does NOT create mutual exclusion — this tuple and
#: :data:`_SINGLETON_INDEX_NAME` do. Each addition carries a cited hazard
#: (``uat/reports/evidence/market-perf/u-agi/p1a/EXEC-CLASSES.md`` §2):
#:
#: * ``submission`` — the (userId, jobId) ACTIVE-application slot; a second
#:   concurrent run can put a SECOND application in front of the same employer.
#: * ``emailAgent`` — triage's ``EmailThread`` upsert is SELECT-then-INSERT
#:   behind a NON-unique index, its classification write is last-writer-wins,
#:   and one Gmail OAuth credential is serialized only WITHIN a process.
#: * ``notification`` — two stacked check-then-act writes (approval dedupe and
#:   the digest row) with no unique index behind either.
#: * ``recruiterOutreach`` / ``reference`` — no race proven; siloed because
#:   U-AGI §5.3 makes them T3 approval-gated real-world actors and the
#:   conservative class is mandated for outbound side effects. The charter
#:   records that distinction as ``siloBasis: tier-conservative`` so this set
#:   never claims a race it cannot cite.
#:
#: This tuple is the AUTHORITY on who may take an exclusive slot
#: (:meth:`BackgroundJobRepository.create_singleton` hard-refuses anything
#: outside it); the partial unique index in :func:`_ensure_table` is the
#: DB-level half that makes a claim atomic across processes. A test pins this
#: tuple equal to the charter's ``silo`` set, so the two can never disagree.
_SINGLETON_AGENTS = (
    "scout",
    "submission",
    "emailAgent",
    "notification",
    "recruiterOutreach",
    "reference",
)

#: Name of the partial unique index that enforces the exclusive slot.
#:
#: Versioned on purpose. ``CREATE UNIQUE INDEX IF NOT EXISTS`` will NOT re-write
#: an index that already exists, so changing the rule under the OLD name would
#: leave every deployment still enforcing the old one while the code claims
#: otherwise — the exact "decorative field" failure F-R8-1 names. Bump this name
#: whenever the rule changes.
#:
#: A version bump alone is not enough, and :func:`_ensure_table` does not rely on
#: one: a database that ran an INTERMEDIATE build already holds this name with
#: that build's definition, and no future bump can help it. The definition is
#: therefore verified at ensure-time and replaced when it does not match.
#:
#: It is keyed on ``singletonKey`` — the CLAIM — not on ``agentKey``, and that
#: distinction is load-bearing rather than cosmetic. An ``(userId, agentKey)``
#: index over the extended silo set would have made a perfectly legitimate second
#: ``emailAgent`` run a raw unique-violation 500: that backend has MODES, and its
#: async route enqueues without claiming (``agents.py`` emailAgent branch), so a
#: user asking for a draft reply while a triage job is in flight would have hit
#: it. Routing that route through the claim instead would be worse — the caller
#: would get back the id of a job doing something they did not ask for, which is
#: silent substitution. Keying on the claim keeps the exclusive slot exactly as
#: strong for everything that TAKES one, and changes nothing for anything that
#: does not.
_SINGLETON_INDEX_NAME = "BackgroundJob_active_singleton_v2_idx"

#: Name of the ORIGINAL scout-only index (MON-020), which this one ADDS TO and
#: does NOT replace.
#:
#: Calling it "superseded" and dropping it was a real weakening, caught by
#: ``test_mon020_async_scout.py`` (``test_active_scout_singleton_is_enforced_by_
#: a_partial_unique_index``): the two indexes enforce DIFFERENT rules and
#: neither contains the other.
#: ``_SCOUT_INDEX_NAME`` constrains every ACTIVE ``scout`` row however it was
#: written — including an insert that never went through ``create_singleton`` —
#: which is exactly the defence-in-depth MON-020 shipped. The claim-keyed index
#: constrains only rows that OPTED IN by claiming, which is what lets a silo
#: agent with modes still be enqueued honestly (see above). Drop the scout index
#: and a future code path that enqueues discovery without claiming gets two
#: concurrent passes with no database left to stop it. So it stays.
#:
#: It stays for ``scout`` ALONE, and that is not an oversight: ``scout`` is a
#: whole-account pass, so a second active row is never legitimate. ``submission``
#: and ``emailAgent`` are per-job / per-mode, where a second active row IS
#: legitimate, and an ``agentKey``-keyed index over them would turn ordinary work
#: into a 500.
_SCOUT_INDEX_NAME = "BackgroundJob_active_singleton_idx"

#: Agents constrained by :data:`_SCOUT_INDEX_NAME` on EVERY insert path. A
#: superset of this is not free — see above — so it is exactly the shipped set.
_ALWAYS_SINGLETON_AGENTS = ("scout",)

_COLS = (
    '"id","userId","agentKey","singletonKey","runId","params","status",'
    '"arqJobId","result",'
    '"error","attempts","quotaReserved","quotaReservedAt","quotaRefundedAt",'
    '"quotaReservedCount","quotaRefundedCount",'
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
                    "quotaReservedCount" integer  NOT NULL DEFAULT 0,
                    "quotaRefundedCount" integer  NOT NULL DEFAULT 0,
                    "startedAt"       timestamptz,
                    "finishedAt"      timestamptz,
                    "createdAt"       timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"       timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            # Additive backfill for a table created before the count columns
            # existed (pipeline reservation-scoped refund — reviewer BLOCKING-3).
            cur.execute(
                'ALTER TABLE "BackgroundJob" '
                'ADD COLUMN IF NOT EXISTS "quotaReservedCount" integer NOT NULL DEFAULT 0'
            )
            cur.execute(
                'ALTER TABLE "BackgroundJob" '
                'ADD COLUMN IF NOT EXISTS "quotaRefundedCount" integer NOT NULL DEFAULT 0'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "BackgroundJob_userId_createdAt_idx" '
                'ON "BackgroundJob" ("userId", "createdAt" DESC)'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "BackgroundJob_status_idx" '
                'ON "BackgroundJob" ("status")'
            )
            # MON-020: at most ONE ACTIVE run per (user, singleton agent). This
            # PARTIAL UNIQUE index is the DB-level half of the duplicate-run
            # guard — it closes the lookup-then-create window that no amount of
            # application-side checking can close across two API processes.
            # Additive and IF NOT EXISTS like every other statement here.
            #
            # Partial on purpose: it constrains only ``enqueued``/``processing``
            # rows of the agents in ``_SINGLETON_AGENTS``, so completed/failed
            # history accumulates freely and the per-job agents (tailor,
            # coverLetter, pipeline) keep running many at once.
            #
            # Wrapped in a SAVEPOINT because it is the ONE statement here whose
            # success depends on existing DATA: a table that already holds two
            # active scout rows for one user cannot take the index. That is
            # loudly logged rather than swallowed, and the enqueue path is still
            # correct without it (``create_singleton`` serializes on an advisory
            # lock in the SAME transaction as its INSERT) — but it must not take
            # the rest of this DDL down with it.
            #
            # The claim column: NULL for an ordinary enqueue, the agent key for
            # a row that took the exclusive slot (see ``create_singleton``).
            # Additive and nullable, so every pre-existing row keeps the honest
            # value "this row never claimed a slot".
            cur.execute(
                'ALTER TABLE "BackgroundJob" '
                'ADD COLUMN IF NOT EXISTS "singletonKey" text'
            )
            # (1) The ORIGINAL scout rule, unchanged and NOT superseded: every
            # ACTIVE scout row, however it was written. This is the one that
            # holds when a caller never went through ``create_singleton`` at all.
            scout_agents = ", ".join(f"'{a}'" for a in _ALWAYS_SINGLETON_AGENTS)
            cur.execute("SAVEPOINT bg_scout_idx")
            try:
                cur.execute(
                    'CREATE UNIQUE INDEX IF NOT EXISTS '
                    f'"{_SCOUT_INDEX_NAME}" ON "BackgroundJob" '
                    f'("userId","agentKey") WHERE "agentKey" IN ({scout_agents}) '
                    "AND \"status\" IN ('enqueued','processing')"
                )
            except Exception:  # noqa: BLE001 — data-dependent; never fatal here
                cur.execute("ROLLBACK TO SAVEPOINT bg_scout_idx")
                logger.warning(
                    "%s could not be created — duplicate active rows already "
                    "exist for a (userId, agentKey) in %s.",
                    _SCOUT_INDEX_NAME, _ALWAYS_SINGLETON_AGENTS, exc_info=True,
                )
            else:
                cur.execute("RELEASE SAVEPOINT bg_scout_idx")
            # (2) The CLAIM rule, which ADDS the other five silo agents. It is
            # keyed on the claim, and :data:`_SINGLETON_AGENTS` is the
            # Python-side authority for who may take one (``create_singleton``
            # hard-refuses anything outside it).
            cur.execute("SAVEPOINT bg_singleton_idx")
            try:
                # A versioned NAME is not by itself proof of the RULE. Any
                # database that ran an earlier build of this index — every
                # developer machine and the shared test schema did — still holds
                # it under this name with the OLD key columns, and
                # ``IF NOT EXISTS`` keeps it forever. That is not cosmetic: the
                # superseded rule was keyed ``("userId","agentKey")``, so an
                # ordinary unclaimed enqueue (a second ``emailAgent`` draft while
                # a triage job is in flight) hits a raw unique-violation 500 on a
                # deployment that believes it is enforcing the claim rule.
                # Observed, not theorised: it failed two tests of this suite
                # against a schema in exactly that state.
                #
                # So the DEFINITION is checked, and a mismatch is replaced inside
                # this savepoint — if the CREATE below then fails on existing
                # data, the DROP rolls back with it and the database keeps
                # whatever protection it had.
                cur.execute(
                    "SELECT pg_get_indexdef(c.oid) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relname = %s "
                    "AND n.nspname = ANY(current_schemas(false))",
                    (_SINGLETON_INDEX_NAME,),
                )
                existing = cur.fetchone()
                if existing and '"singletonKey"' not in (existing[0] or ""):
                    logger.warning(
                        "%s exists with a superseded definition (%s) — replacing "
                        "it with the claim-keyed rule.",
                        _SINGLETON_INDEX_NAME,
                        existing[0],
                    )
                    cur.execute(f'DROP INDEX "{_SINGLETON_INDEX_NAME}"')
                cur.execute(
                    'CREATE UNIQUE INDEX IF NOT EXISTS '
                    f'"{_SINGLETON_INDEX_NAME}" ON "BackgroundJob" '
                    '("userId","singletonKey") WHERE "singletonKey" IS NOT NULL '
                    "AND \"status\" IN ('enqueued','processing')"
                )
            except Exception:  # noqa: BLE001 — data-dependent; never fatal here
                cur.execute("ROLLBACK TO SAVEPOINT bg_singleton_idx")
                logger.warning(
                    "%s could not be created — duplicate active CLAIMED rows "
                    "already exist for a (userId, singletonKey) in %s. The "
                    "advisory-lock guard in create_singleton still holds; "
                    "resolve the duplicates and restart to add the index.",
                    _SINGLETON_INDEX_NAME,
                    _SINGLETON_AGENTS,
                    exc_info=True,
                )
            else:
                cur.execute("RELEASE SAVEPOINT bg_singleton_idx")
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

    def create_singleton(
        self,
        user_id: str,
        agent_key: str,
        *,
        run_id: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
        quota_reserved: bool = False,
        arq_job_id: Optional[str] = None,
    ) -> tuple[str, bool]:
        """Find-or-create THE active job for ``(user_id, agent_key)`` (MON-020).

        Returns ``(job_id, created)``: ``created`` is True only when THIS call
        inserted the row. When the user already has an ``enqueued``/``processing``
        job for this agent, the EXISTING id comes back and nothing is inserted —
        which is what makes a second Sync click (or a second tab, or the third
        button that hits the same endpoint) idempotent rather than a second
        discovery pass.

        Atomicity: the check and the insert are ONE transaction, serialized by a
        transaction-scoped advisory lock on ``(agent_key, user_id)``, so two API
        processes cannot both pass the "no active job" check. The lock is
        released by the commit at the end, i.e. only after the row that the next
        caller must see is durable. The partial unique index created in
        :func:`_ensure_table` is the second, independent line of defence.

        The ``WHERE NOT EXISTS``/re-read pair is retried a bounded number of
        times for one specific benign race: under READ COMMITTED each statement
        takes a fresh snapshot, so the active job can reach a terminal state
        BETWEEN the insert-check and the re-read, leaving neither a new row nor
        an existing one. Re-running the insert then simply succeeds. It never
        loops on a stable state, and it never invents a job id.

        Refuses an agent outside :data:`_SINGLETON_AGENTS`: the advisory lock
        alone would give a WEAKER guarantee than the caller is entitled to
        assume, because the partial unique index that backs it covers only
        those agents. Failing loudly beats silently degrading the guard.
        """
        if agent_key not in _SINGLETON_AGENTS:
            raise ValueError(
                f"{agent_key!r} is not a singleton agent; the partial unique "
                f"index covers only {_SINGLETON_AGENTS}. Extend both together "
                "or use create()."
            )
        _ensure_table()
        insert_sql = (
            'INSERT INTO "BackgroundJob" '
            '("id","userId","agentKey","singletonKey","runId","params","status",'
            '"arqJobId","quotaReserved","quotaReservedAt") '
            "SELECT %s,%s,%s,%s,%s,%s::jsonb,'enqueued',%s,%s,"
            "CASE WHEN %s THEN now() ELSE NULL END "
            'WHERE NOT EXISTS (SELECT 1 FROM "BackgroundJob" '
            'WHERE "userId"=%s AND "singletonKey"=%s AND "status" IN %s) '
            'RETURNING "id"'
        )
        select_sql = (
            'SELECT "id" FROM "BackgroundJob" WHERE "userId"=%s '
            'AND "singletonKey"=%s AND "status" IN %s '
            'ORDER BY "createdAt" DESC LIMIT 1'
        )
        params_json = json.dumps(params) if params is not None else None
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
                    (_SINGLETON_ENQUEUE_LOCK_CLASS, f"{agent_key}:{user_id}"),
                )
                for _ in range(3):
                    cur.execute(
                        insert_sql,
                        (
                            new_id(),
                            user_id,
                            agent_key,
                            agent_key,  # singletonKey — THIS row holds the slot
                            run_id,
                            params_json,
                            arq_job_id,
                            quota_reserved,
                            quota_reserved,
                            user_id,
                            agent_key,
                            _NON_TERMINAL,
                        ),
                    )
                    inserted = cur.fetchone()
                    if inserted is not None:
                        conn.commit()
                        return str(inserted[0]), True
                    cur.execute(select_sql, (user_id, agent_key, _NON_TERMINAL))
                    existing = cur.fetchone()
                    if existing is not None:
                        conn.commit()
                        return str(existing[0]), False
            conn.rollback()
        raise RuntimeError(
            f"could not claim the active {agent_key} job for user {user_id}"
        )

    def find_active(self, user_id: str, agent_key: str) -> Optional[dict[str, Any]]:
        """The user's newest non-terminal job for ``agent_key``, or None.

        Read-only lookup used BEFORE the enqueue so the caller can apply the
        same lazy staleness watchdog the poll route applies (a job whose worker
        died must not keep the user from starting a new run)."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLS} FROM "BackgroundJob" WHERE "userId"=%s '
                    'AND "agentKey"=%s AND "status" IN %s '
                    'ORDER BY "createdAt" DESC LIMIT 1',
                    (user_id, agent_key, _NON_TERMINAL),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def set_run_id(self, job_id: str, run_id: Optional[str]) -> None:
        """Attach the AgentRun audit row to a job created before it.

        ``create_singleton`` inserts the job FIRST (that insert is the atomic
        claim), so the audit row is written only by the caller that actually
        won the claim — no orphan "running" AgentRun rows from a lost race."""
        if not run_id:
            return
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "BackgroundJob" SET "runId"=%s,"updatedAt"=now() '
                    'WHERE "id"=%s',
                    (run_id, job_id),
                )
            conn.commit()

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

    def mark_completed(self, job_id: str, result: Any) -> bool:
        """Atomic first-terminal-wins transition to completed. Guarded on the
        CURRENT status so a watchdog that already marked the job failed cannot be
        stomped back to completed (reviewer BLOCKING-2). Returns True iff THIS
        call performed the transition."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE \"BackgroundJob\" SET \"status\"='completed', "
                    '"result"=%s::jsonb, "error"=NULL, "finishedAt"=now(), '
                    "\"updatedAt\"=now() WHERE \"id\"=%s AND \"status\" IN "
                    "('enqueued','processing') RETURNING \"id\"",
                    (
                        json.dumps(result, default=str) if result is not None else None,
                        job_id,
                    ),
                )
                won = cur.fetchone() is not None
            conn.commit()
        return won

    def mark_failed(self, job_id: str, error: str, *, refunded: bool = False) -> bool:
        """Atomic first-terminal-wins transition to failed. Guarded on the CURRENT
        status (reviewer BLOCKING-2). Honest error string only, NEVER fixture
        content; ``result`` stays null. Returns True iff THIS call transitioned
        the job (the caller then performs the associated refund exactly once)."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE \"BackgroundJob\" SET \"status\"='failed', "
                    '"error"=%s, "finishedAt"=now(), "updatedAt"=now(), '
                    '"quotaRefundedAt"=CASE WHEN %s THEN now() ELSE "quotaRefundedAt" END '
                    "WHERE \"id\"=%s AND \"status\" IN ('enqueued','processing') "
                    'RETURNING "id"',
                    (str(error)[:1000], refunded, job_id),
                )
                won = cur.fetchone() is not None
            conn.commit()
        return won

    def refund_single_reservation(self, job_id: str) -> bool:
        """Atomically claim + refund the SINGLE enqueue-time reservation of a
        single-agent job, in ONE statement (reviewer BLOCKING-1). A data-modifying
        CTE flips ``quotaRefundedAt`` from NULL under a row lock (WHERE
        quotaRefundedAt IS NULL AND quotaReserved) and, only if it claimed,
        decrements ``UsageQuota.runsUsed`` by 1 (floored at 0). Idempotent: a
        second concurrent firing matches 0 rows and refunds nothing. Returns True
        iff THIS call performed the refund."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    WITH claim AS (
                        UPDATE "BackgroundJob"
                           SET "quotaRefundedAt" = now(),
                               "quotaRefundedCount" = GREATEST("quotaRefundedCount", 1),
                               "updatedAt" = now()
                         WHERE "id" = %s
                           AND "quotaReserved" = true
                           AND "quotaRefundedAt" IS NULL
                        RETURNING "userId"
                    )
                    UPDATE "UsageQuota" q
                       SET "runsUsed" = GREATEST(q."runsUsed" - 1, 0),
                           "updatedAt" = now()
                      FROM claim
                     WHERE q."userId" = claim."userId"
                    RETURNING q."userId"
                    ''',
                    (job_id,),
                )
                claimed = cur.fetchone() is not None
            conn.commit()
        return claimed

    def increment_reserved(self, job_id: str, n: int = 1) -> None:
        """Record that this (pipeline) job reserved ``n`` more metered run(s)."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "BackgroundJob" SET "quotaReservedCount"='
                    '"quotaReservedCount"+%s,"updatedAt"=now() WHERE "id"=%s',
                    (n, job_id),
                )
            conn.commit()

    def increment_refunded(self, job_id: str, n: int = 1) -> None:
        """Record that this (pipeline) job already refunded ``n`` reserved run(s)
        (a step that failed and refunded itself)."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "BackgroundJob" SET "quotaRefundedCount"='
                    '"quotaRefundedCount"+%s,"updatedAt"=now() WHERE "id"=%s',
                    (n, job_id),
                )
            conn.commit()

    def refund_pipeline_outstanding(self, job_id: str) -> int:
        """Refund EXACTLY this pipeline job's own outstanding reservations
        (reviewer BLOCKING-3) — never a user-wide runsUsed delta. Under a row
        lock (SELECT ... FOR UPDATE) compute ``outstanding = quotaReservedCount −
        quotaRefundedCount`` for THIS job, decrement ``UsageQuota.runsUsed`` by
        that many (floored at 0), and set ``quotaRefundedCount = quotaReservedCount``.
        Idempotent + scoped: a second call, or a concurrent same-user run, sees
        outstanding 0 for this job and refunds nothing. Returns the count refunded."""
        _ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "userId","quotaReservedCount","quotaRefundedCount" '
                    'FROM "BackgroundJob" WHERE "id"=%s FOR UPDATE',
                    (job_id,),
                )
                row = cur.fetchone()
                if row is None:
                    conn.commit()
                    return 0
                user_id = row[0]
                outstanding = int(row[1] or 0) - int(row[2] or 0)
                if outstanding <= 0:
                    conn.commit()
                    return 0
                cur.execute(
                    'UPDATE "BackgroundJob" SET "quotaRefundedCount"='
                    '"quotaReservedCount","updatedAt"=now() WHERE "id"=%s',
                    (job_id,),
                )
                cur.execute(
                    'UPDATE "UsageQuota" SET "runsUsed"=GREATEST("runsUsed"-%s,0),'
                    '"updatedAt"=now() WHERE "userId"=%s',
                    (outstanding, user_id),
                )
            conn.commit()
        return outstanding

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
