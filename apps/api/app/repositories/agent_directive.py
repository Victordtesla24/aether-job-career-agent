"""AgentDirective repository — ADR-AGI-2 P1 (ORCH-B1-BLUEPRINT-2026-08-14.md §2.2).

Additive, lazy-idempotent DDL (ADR-TR-1) mirroring ``repositories/background_jobs.py``:
ONE advisory-locked transaction running ``CREATE TABLE / INDEX IF NOT EXISTS``
only, ensured on first use. There is no migration runner in this repo; this
module is the sole mechanism that creates the table in production. Documentary
mirror: ``apps/api/migrations/0030_agent_directive.sql`` +
``packages/db/src/schema.prisma``.

No FK to ``"User"`` (matches ``BackgroundJob``/``Offer``/``UsageQuota``) so the
shared test-suite's ``TRUNCATE "User"`` never trips, and a deleted user's
directive history is never silently made un-queryable.

IMMUTABILITY IS STRUCTURAL, NOT PROCEDURAL (ADR-AGI-2 "Immutable history —
directives are never edited or deleted — superseded with rationale"). This
class exposes NO method that updates ``directive``, ``rationale`` or
``metricsCited`` on an existing row. The only mutating writes are:

* :meth:`issue` — flips a PRIOR active row to ``superseded`` (status +
  ``supersededById`` only) in the SAME transaction that inserts the new
  ``active`` row. The prior row's instruction content is never touched.
* :meth:`record_outcome` — merges an outcome observation. It never touches the
  instruction itself (``directive``/``rationale``/``metricsCited``).

The partial unique index ``AgentDirective_active_key`` makes "at most one
active directive per (user, agent)" a DB fact, not a convention — and
:meth:`issue` additionally serializes on a two-argument advisory lock (the
same idiom ``BackgroundJobRepository.create_singleton`` uses) so two
concurrent issuances for the same (user, agent) cannot both observe "no
active row" and both try to insert one.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

logger = logging.getLogger(__name__)

#: Distinct advisory-lock id for this table's DDL. Registry check against the
#: full in-tree grep (2026-08-14, this branch — post-dates the blueprint's
#: design-tree snapshot, which did not yet have ``answer_bank.py``'s
#: ``7420260821``): highest claimed id on THIS branch is 7420260821. This id
#: (7420260816) is free and matches the blueprint's assignment.
_AGENT_DIRECTIVE_LOCK = 7420260816

#: Classid for the two-argument advisory lock that serializes ``issue()`` per
#: (agentKey, userId) — the same idiom ``BackgroundJobRepository.
#: create_singleton`` uses for its own find-or-create race. A distinct
#: namespace from the one-argument DDL locks above (the two forms never
#: collide with each other in Postgres).
_DIRECTIVE_ISSUE_LOCK_CLASS = 20260816

_directive_table_ready = False

_COLUMNS_SQL = (
    '"id","userId","agentKey","directive","clamped","rejectedKeys","rationale",'
    '"metricsCited","issuedBy","status","supersededById","outcome",'
    '"issuedAt","expiresAt","createdAt","updatedAt"'
)


def _reset_agent_directive_table_for_tests() -> None:
    """Test hook: force the DDL to re-run (mirrors every sibling repo)."""
    global _directive_table_ready
    _directive_table_ready = False


def ensure_agent_directive_table() -> None:
    """Create the ``AgentDirective`` table + indexes on first use (ADR-TR-1).

    Additive and idempotent; serialized by one transaction-scoped advisory
    lock so concurrent ``CREATE TABLE IF NOT EXISTS`` cannot race on
    ``pg_type``. DDL exactly per ORCH-B1-BLUEPRINT-2026-08-14.md §2.2.
    """
    global _directive_table_ready
    if _directive_table_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(%s)", (_AGENT_DIRECTIVE_LOCK,)
            )
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "AgentDirective" (
                    "id"             text        PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    "userId"         text        NOT NULL,
                    "agentKey"       text        NOT NULL,
                    "directive"      jsonb       NOT NULL,
                    "clamped"        jsonb,
                    "rejectedKeys"   jsonb,
                    "rationale"      text        NOT NULL,
                    "metricsCited"   jsonb       NOT NULL,
                    "issuedBy"       text        NOT NULL DEFAULT 'supervisor-rules',
                    "status"         text        NOT NULL DEFAULT 'active',
                    "supersededById" text,
                    "outcome"        jsonb,
                    "issuedAt"       timestamptz NOT NULL DEFAULT now(),
                    "expiresAt"      timestamptz,
                    "createdAt"      timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"      timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "AgentDirective_active_key" '
                'ON "AgentDirective" ("userId", "agentKey") WHERE "status" = \'active\''
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "AgentDirective_user_agent_issued_idx" '
                'ON "AgentDirective" ("userId", "agentKey", "issuedAt" DESC)'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "AgentDirective_status_expires_idx" '
                'ON "AgentDirective" ("status", "expiresAt")'
            )
        conn.commit()
    _directive_table_ready = True


class AgentDirectiveRepository:
    """Immutable-history CRUD for ``AgentDirective`` — create/supersede/list
    ONLY. No ``update`` of directive content; no ``delete``, ever."""

    def list_active(
        self, user_id: str, agent_key: str | None = None
    ) -> list[dict[str, Any]]:
        """Active, unexpired directives for this user (optionally one agent).

        ``expiresAt`` in the past is excluded here even if :meth:`expire_due`
        has not yet swept it — a read must never show an amendment as live
        past its own stated horizon just because the sweep hasn't run.
        """
        ensure_agent_directive_table()
        clauses = ['"userId" = %s', '"status" = \'active\'']
        params: list[Any] = [user_id]
        if agent_key is not None:
            clauses.append('"agentKey" = %s')
            params.append(agent_key)
        clauses.append('("expiresAt" IS NULL OR "expiresAt" > NOW())')
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS_SQL} FROM "AgentDirective" '
                    f'WHERE {" AND ".join(clauses)} '
                    'ORDER BY "agentKey", "issuedAt" DESC',
                    tuple(params),
                )
                return rows_to_dicts(cur)

    def list_history(
        self, user_id: str, agent_key: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Every directive ever issued for ``(user_id, agent_key)``, newest
        first — active AND superseded. Immutable history survives supersession
        by construction: :meth:`issue` never deletes a row."""
        ensure_agent_directive_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS_SQL} FROM "AgentDirective" '
                    'WHERE "userId" = %s AND "agentKey" = %s '
                    'ORDER BY "issuedAt" DESC LIMIT %s',
                    (user_id, agent_key, limit),
                )
                return rows_to_dicts(cur)

    def issue(
        self,
        user_id: str,
        agent_key: str,
        *,
        directive: dict[str, Any],
        rationale: str,
        metrics_cited: dict[str, Any],
        clamped: dict[str, Any] | None = None,
        rejected_keys: Sequence[str] = (),
        issued_by: str = "supervisor-rules",
        expires_at: datetime | None = None,
    ) -> str:
        """Issue a directive, superseding any currently-active one for this
        (user, agent) in the SAME transaction.

        Ordering matters: the prior active row is flipped to ``superseded``
        BEFORE the new row is inserted, so the partial unique index
        (``WHERE status = 'active'``) never sees two active rows for the same
        key even momentarily. The two-argument advisory lock serializes this
        whole read-flip-insert sequence per ``(agentKey, userId)`` so a
        concurrent caller cannot interleave between the SELECT and the
        INSERT — exactly the race ``BackgroundJobRepository.create_singleton``
        already closes the same way.
        """
        ensure_agent_directive_table()
        new_directive_id = new_id()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
                    (_DIRECTIVE_ISSUE_LOCK_CLASS, f"{agent_key}:{user_id}"),
                )
                cur.execute(
                    'SELECT "id" FROM "AgentDirective" '
                    'WHERE "userId" = %s AND "agentKey" = %s AND "status" = \'active\'',
                    (user_id, agent_key),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        'UPDATE "AgentDirective" SET "status" = \'superseded\', '
                        '"supersededById" = %s, "updatedAt" = NOW() WHERE "id" = %s',
                        (new_directive_id, existing[0]),
                    )
                cur.execute(
                    'INSERT INTO "AgentDirective" '
                    '("id","userId","agentKey","directive","clamped","rejectedKeys",'
                    '"rationale","metricsCited","issuedBy","status","expiresAt") '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,\'active\',%s)',
                    (
                        new_directive_id, user_id, agent_key,
                        json.dumps(directive),
                        json.dumps(clamped) if clamped is not None else None,
                        json.dumps(list(rejected_keys)),
                        rationale, json.dumps(metrics_cited), issued_by,
                        expires_at,
                    ),
                )
            conn.commit()
        return new_directive_id

    def supersede(self, directive_id: str, *, reason: str) -> bool:
        """Retire an active directive WITHOUT replacing it (rules S4: the
        metrics recovered, so the baseline should simply reassert itself).

        The reason is recorded onto ``outcome`` — never onto ``rationale``,
        which is the immutable record of why the directive was ISSUED, not
        why it was retired. Returns ``True`` iff a row was actually active
        and flipped (idempotent no-op otherwise, never an error)."""
        ensure_agent_directive_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AgentDirective" SET "status" = \'superseded\', '
                    '"outcome" = COALESCE("outcome", \'{}\'::jsonb) || %s::jsonb, '
                    '"updatedAt" = NOW() '
                    'WHERE "id" = %s AND "status" = \'active\'',
                    (json.dumps({"retiredReason": reason}), directive_id),
                )
                changed = cur.rowcount > 0
            conn.commit()
        return changed

    def expire_due(self, now: datetime | None = None) -> int:
        """Sweep every active-but-past-``expiresAt`` row to ``status =
        'expired'``. Returns the count changed. Best-effort housekeeping —
        :meth:`list_active` already excludes expired-but-unswept rows on
        read, so a missed sweep is never user-visible, only a history-label
        staleness."""
        ensure_agent_directive_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                if now is None:
                    cur.execute(
                        'UPDATE "AgentDirective" SET "status" = \'expired\', '
                        '"updatedAt" = NOW() '
                        'WHERE "status" = \'active\' AND "expiresAt" IS NOT NULL '
                        'AND "expiresAt" <= NOW()'
                    )
                else:
                    cur.execute(
                        'UPDATE "AgentDirective" SET "status" = \'expired\', '
                        '"updatedAt" = NOW() '
                        'WHERE "status" = \'active\' AND "expiresAt" IS NOT NULL '
                        'AND "expiresAt" <= %s',
                        (now,),
                    )
                count = cur.rowcount
            conn.commit()
        return count

    def record_outcome(self, directive_id: str, outcome: dict[str, Any]) -> None:
        """Merge an outcome observation onto a directive row (P1: adherence;
        P2: efficacy scoring). The ONLY mutating write besides ``status`` —
        never touches ``directive``/``rationale``/``metricsCited``."""
        ensure_agent_directive_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AgentDirective" SET '
                    '"outcome" = COALESCE("outcome", \'{}\'::jsonb) || %s::jsonb, '
                    '"updatedAt" = NOW() WHERE "id" = %s',
                    (json.dumps(outcome), directive_id),
                )
            conn.commit()
