"""``ApplicationStatusEvent`` — the per-application status transition history.

U-AX instrumentation item 1 (absorbing the original U4 plan). Until now
``Application.status`` was a CURRENT-SNAPSHOT column with no history at all:
the funnel could say "202 submitted, 0 interviews" but nothing anywhere could
say WHEN an application moved, by what mechanism, or which policy tier the
agents were operating at when it did. That makes the conversion number
un-attributable — you cannot prove a cohort improved if you never recorded
when each application entered its stage.

This table records one row per REAL transition, written by every code path
that changes ``Application.status`` (all five, enumerated in
``docs/`` and grep-verified at build time):

  1. ``routers/jobs.py``            — POST /jobs/{id}/apply (draft -> submitted)
  2. ``routers/applications.py``    — POST /applications/{id}/submit
  3. ``repositories/approval.py``   — an application_submit approval decision
  4. ``services/stage_transitions.py`` — the kanban stage move
  5. ``services/application_submission.py`` — a real email transmission

Provisioned by lazy, advisory-locked idempotent DDL (:func:`ensure_application_status_event_table`)
— the ONLY additive-migration mechanism in this codebase (ADR-TR-1, "no
migration runner"; same pattern as ``db.ensure_application_transmission_columns``
and ``services/offers._ensure_offers_table``).

HONEST BACKFILL. Applications that already existed when this table was created
have a status but no recorded history — their transitions genuinely were not
observed. The backfill therefore writes exactly ONE row per such application:
``toStatus`` = the status it is actually in, ``fromStatus`` = NULL (unknown —
never guessed as 'draft'), ``at`` = the row's own ``updatedAt`` (the only real
timestamp available), and ``source`` = ``'backfill:current-status'`` so every
consumer can tell a reconstructed genesis row from an observed transition.
Nothing is invented; the provenance is on the row.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

logger = logging.getLogger(__name__)

_COLUMNS = '"id", "applicationId", "fromStatus", "toStatus", "at", "source"'

#: Distinct from every other advisory-lock id in the codebase (7420260803 /
#: 7420260804 in ``app/db.py``, the offers lock in ``services/offers.py``).
_STATUS_EVENT_LOCK = 7420260814

#: Provenance marker for rows reconstructed from a pre-existing snapshot rather
#: than observed as they happened. Consumers MUST render these differently from
#: real transitions.
BACKFILL_SOURCE = "backfill:current-status"

_table_ready = False


def ensure_application_status_event_table() -> None:
    """Idempotently create ``"ApplicationStatusEvent"`` and backfill genesis rows.

    Lock-free existence fast-path, then a transaction-scoped advisory lock
    serialising concurrent first-hit callers around ``CREATE TABLE IF NOT
    EXISTS``. ``TRUNCATE`` never drops tables, so the process-wide latch
    survives test teardown.

    ``seq bigserial`` exists so chronological ordering is TOTAL: two events can
    share a millisecond (a transition and its backfilled genesis row can even
    share ``updatedAt``), and "which came first" must never depend on tie-break
    luck. ``at`` remains the wall-clock truth; ``seq`` is only the tiebreaker.

    The FK is ``ON DELETE CASCADE``: an application's history is meaningless
    without the application, and it also lets the test suite's
    ``TRUNCATE "Application" CASCADE`` clean this table for free.
    """
    global _table_ready
    if _table_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_name = 'ApplicationStatusEvent'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _table_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_STATUS_EVENT_LOCK,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "ApplicationStatusEvent" (
                    "id"            text PRIMARY KEY,
                    "seq"           bigserial   NOT NULL,
                    "applicationId" text        NOT NULL
                        REFERENCES "Application"("id") ON DELETE CASCADE,
                    "fromStatus"    text,
                    "toStatus"      text        NOT NULL,
                    "at"            timestamptz NOT NULL DEFAULT now(),
                    "source"        text        NOT NULL
                )
                '''
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_appstatusevent_app_at"'
                ' ON "ApplicationStatusEvent" ("applicationId", "at", "seq")'
            )
            # Honest genesis backfill — see the module docstring. Runs once,
            # inside the same locked transaction as the CREATE, so it cannot
            # double-insert even if two processes hit this simultaneously.
            cur.execute(
                f'''
                INSERT INTO "ApplicationStatusEvent" ({_COLUMNS})
                SELECT md5(random()::text || clock_timestamp()::text),
                       "id", NULL, "status"::text,
                       COALESCE("updatedAt", "createdAt"), %s
                FROM "Application"
                ''',
                (BACKFILL_SOURCE,),
            )
        conn.commit()
    _table_ready = True


def record_status_event(
    application_id: str,
    from_status: str | None,
    to_status: str,
    source: str,
) -> dict[str, Any] | None:
    """Append ONE observed transition. Returns the stored row.

    ``from_status`` is nullable and must be passed as ``None`` when the prior
    status genuinely was not read — a guessed "draft" would be a fabrication in
    the one table whose whole purpose is provenance.

    A no-op transition (``from_status == to_status``) is deliberately NOT
    written: the status did not change, so recording a "transition" would
    inflate every cohort count downstream.
    """
    if from_status is not None and from_status == to_status:
        return None
    ensure_application_status_event_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'''
                INSERT INTO "ApplicationStatusEvent"
                    ("id", "applicationId", "fromStatus", "toStatus", "source")
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {_COLUMNS}
                ''',
                (new_id(), application_id, from_status, to_status, source),
            )
            rows = rows_to_dicts(cur)
        conn.commit()
    return rows[0] if rows else None


def record_status_event_best_effort(
    application_id: str,
    from_status: str | None,
    to_status: str,
    source: str,
) -> None:
    """:func:`record_status_event`, but an audit failure never fails the user's
    action.

    Losing one history row is bad; refusing a user's submission because an
    analytics INSERT failed is worse. The failure is LOGGED at warning level
    with the application id — an operator can see it happened, so this is a
    degraded-and-recorded path, not a silent swallow.
    """
    try:
        record_status_event(application_id, from_status, to_status, source)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ApplicationStatusEvent write failed for application %s (%s -> %s, "
            "source=%s): %s",
            application_id, from_status, to_status, source, exc,
        )


def list_status_events(application_id: str) -> list[dict[str, Any]]:
    """This application's transitions, oldest first (total order via ``seq``)."""
    ensure_application_status_event_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "ApplicationStatusEvent"'
                ' WHERE "applicationId" = %s ORDER BY "at" ASC, "seq" ASC',
                (application_id,),
            )
            return rows_to_dicts(cur)


def current_status(application_id: str) -> str | None:
    """The application's status as stored TODAY — read before a transition so
    the recorded ``fromStatus`` is observed rather than assumed."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status"::text FROM "Application" WHERE "id" = %s',
                (application_id,),
            )
            row = cur.fetchone()
    return str(row[0]) if row else None
