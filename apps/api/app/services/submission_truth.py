"""U5d — additive remediation for claimed-submitted-without-proof applications.

WHAT WENT WRONG (production forensics 2026-08-14T07:35:45Z,
``uat/reports/evidence/agents-uplift/u5d/FORENSICS.md``): the Submission Agent
returned ``submitted: true`` and the sentence *"Submitted your application for
… at WSP USA."* over a bookkeeping-only write that transmitted nothing. The
census found **346 rows** with ``status = 'submitted'`` and **0 rows in the
entire database — 0 / 606 — with a ``transmittedAt``**. Every one of those 346
is a claim with no evidence.

WHAT THIS MODULE DOES: reclassifies exactly those rows to an honest state,
``recorded_transmission_unverified`` — *"recorded — transmission unverified
(pre-fix)"* — and reports the count.

WHAT IT DELIBERATELY DOES NOT DO:

* it does not rewrite ``Application.status``. "Submitted" in the tracker is the
  user's OWN record of what the USER did; rewriting 346 rows of somebody's job
  search to repair OUR falsehood would destroy their data to fix our bug. The
  truth is ADDED beside the status, in a column of its own, and every read path
  carries both (``application_submission.submission_view``);
* it does not delete a row, drop a column, or touch ``ApplicationStatusEvent``
  history;
* it never writes a POSITIVE claim. It can only ever move a row from "claimed,
  unproven" to "explicitly marked unproven" — the direction that removes a
  falsehood. A row carrying real transmission evidence (``transmittedAt NOT
  NULL``) is never touched, and no code path here can set ``transmittedAt``.

Idempotent: the UPDATE is guarded on ``submissionTruthState IS NULL``, so a
second pass reclassifies 0 rows and an already-stamped row keeps its original
``submissionTruthAt``.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db import (
    ensure_application_submission_truth_columns,
    ensure_application_transmission_columns,
    get_connection,
    rows_to_dicts,
)

logger = logging.getLogger(__name__)

#: The honest reclassification: the row records that the user applied, and
#: records that Aether cannot show any evidence it transmitted anything.
STATE_UNVERIFIED = "recorded_transmission_unverified"

#: U5d-2 — the WRITE-TIME marker. :data:`STATE_UNVERIFIED` is retrospective
#: ("we cannot tell, after the fact, what this pre-fix row meant"); this one is
#: stamped by the bookkeeping writer ITSELF, in the same request that records
#: ``status='submitted'`` without transmission proof. The distinction is the
#: whole point: after this slice, an unmarked claimed-submitted row is a BUG
#: rather than an ambiguity, so the census predicate stops being an
#: investigation and becomes a self-evident invariant.
STATE_RECORDED_NOT_TRANSMITTED = "recorded_not_transmitted"

#: User-facing wording for :data:`STATE_UNVERIFIED`, served by
#: ``application_submission.submission_view`` so every surface says the same
#: sentence rather than inventing its own.
NOTE_UNVERIFIED = "recorded — transmission unverified (pre-fix)"

#: User-facing wording for :data:`STATE_RECORDED_NOT_TRANSMITTED`.
NOTE_RECORDED_NOT_TRANSMITTED = "recorded in your tracker — Aether transmitted nothing"

#: Human-readable note per state. A state with no note here is a programming
#: error, not a silent blank: ``submission_note_for`` returns ``None`` only for
#: an unstamped (NULL) row.
_NOTES = {
    STATE_UNVERIFIED: NOTE_UNVERIFIED,
    STATE_RECORDED_NOT_TRANSMITTED: NOTE_RECORDED_NOT_TRANSMITTED,
}

#: The columns the predicate names that are ADDITIVE — created lazily by the
#: ``ensure_*`` DDL (ADR-TR-1) rather than present in the base Prisma schema, so
#: either may legitimately be missing from a given database. Probed on
#: production 2026-08-14T09:00Z: ``transmittedAt`` present,
#: ``submissionTruthState`` ABSENT — which is exactly why a census must be able
#: to run without creating it (see :func:`_read_predicate`).
_ADDITIVE_PREDICATE_COLUMNS = ("transmittedAt", "submissionTruthState")


def _unverified_predicate(present: frozenset[str] | None = None) -> str:
    """The false-positive predicate, verbatim from the census: a row that CLAIMS
    a submission (``status = 'submitted'``) while carrying no transmission
    evidence whatsoever. Rows the user moved further along their own pipeline
    (screening / interview / offer) are deliberately excluded — those carry the
    user's own later, independent knowledge of what happened, and re-labelling
    them "unverified" would contradict evidence we do not have.

    ``present`` names the additive columns that actually exist right now. An
    absent additive column is logically NULL for every existing row, so dropping
    its ``IS NULL`` conjunct is an EXACT rewrite of the predicate, not an
    approximation — which is what lets the read-only census (below) run against
    a database whose truth columns have never been created, without creating
    them. ``None`` means "all present", the state every write path guarantees by
    calling :func:`_ensure_columns` first.
    """
    clauses = ['"status" = \'submitted\'::"ApplicationStatus"']
    clauses += [
        f'"{column}" IS NULL'
        for column in _ADDITIVE_PREDICATE_COLUMNS
        if present is None or column in present
    ]
    return "\n    AND ".join(clauses)


def submission_note_for(state: str | None) -> str | None:
    """The user-facing sentence for a persisted ``submissionTruthState``."""
    if not state:
        return None
    return _NOTES.get(state, state)


def _ensure_columns() -> None:
    ensure_application_transmission_columns()
    ensure_application_submission_truth_columns()


def _present_additive_columns() -> frozenset[str]:
    """Which additive predicate columns exist. Pure SELECT — issues NO DDL."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'Application'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = ANY(%s)",
                (list(_ADDITIVE_PREDICATE_COLUMNS),),
            )
            return frozenset(str(row[0]) for row in cur.fetchall())


def _read_predicate(read_only: bool) -> str:
    """Resolve the predicate for a read, ensuring the columns unless forbidden.

    ``read_only=True`` is the contract the ops one-shot's DRY RUN advertises to
    an operator pointing it at production: SELECTs only, no DDL. It is honoured
    here rather than merely documented — see
    ``scripts/backfill_submission_truth.py`` and
    ``TestBackfillOpsScript::test_dry_run_never_reaches_the_ddl_helpers``.
    """
    if read_only:
        return _unverified_predicate(_present_additive_columns())
    _ensure_columns()
    return _unverified_predicate()


def count_unverified_submissions(
    user_id: str | None = None, *, read_only: bool = False
) -> int:
    """How many rows still claim a submission with no transmission evidence.

    Counted for real against the predicate the backfill uses, so the "before"
    number and the reclassified number can never drift apart.

    ``read_only=True`` additionally guarantees the count costs no DDL.
    """
    sql = f'SELECT count(*) FROM "Application" WHERE {_read_predicate(read_only)}'
    params: tuple[Any, ...] = ()
    if user_id is not None:
        sql += ' AND "userId" = %s'
        params = (user_id,)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
    return int(row[0]) if row else 0


def backfill_unverified_submissions(user_id: str | None = None) -> dict[str, Any]:
    """Reclassify claimed-submitted-without-proof rows. Additive, idempotent.

    ``user_id=None`` sweeps every user (the one-shot ops remediation);
    otherwise it is scoped to one owner.

    Returns ``{"reclassified": N, "remaining": M, "state": ...}`` where ``N``
    is the REAL ``rowcount`` of the UPDATE — never an estimate, never the
    pre-count — and ``M`` is a fresh re-count afterwards, so a partial pass
    can never be reported as a complete one.
    """
    _ensure_columns()
    sql = f'''
        UPDATE "Application"
        SET "submissionTruthState" = %s, "submissionTruthAt" = NOW()
        WHERE {_unverified_predicate()}
    '''
    params: tuple[Any, ...] = (STATE_UNVERIFIED,)
    if user_id is not None:
        sql += ' AND "userId" = %s'
        params = (*params, user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            reclassified = int(cur.rowcount)
        conn.commit()
    remaining = count_unverified_submissions(user_id)
    if reclassified:
        logger.info(
            "u5d.submission_truth.backfill reclassified=%s remaining=%s scope=%s",
            reclassified, remaining, user_id or "all-users",
        )
    return {
        "reclassified": reclassified,
        "remaining": remaining,
        "state": STATE_UNVERIFIED,
        "note": NOTE_UNVERIFIED,
    }


def mark_recorded_not_transmitted(user_id: str, application_id: str) -> bool:
    """Stamp the WRITE-TIME marker on one row. Returns whether it was stamped.

    U5d-2. Called by every path that records ``status='submitted'`` WITHOUT
    transmission proof — the Jobs board's Apply button
    (``jobs.submit_application_for_job``) and the tracker's own "mark as
    submitted" control (``applications.submit_application``). Those writes are
    honest bookkeeping of something the USER did elsewhere; what was missing is
    that the row said so at the moment it was written, instead of only after a
    later census sweep guessed at it.

    A ONE-WAY DOOR, enforced in SQL rather than by convention:

    * ``"transmittedAt" IS NULL`` — a row carrying real transmission evidence
      can never be re-labelled "not transmitted". This function cannot write a
      falsehood in the dangerous direction even if a caller misuses it.
    * ``"submissionTruthState" IS NULL`` — idempotent. A second call stamps
      nothing and preserves the ORIGINAL ``submissionTruthAt``, so the marker's
      timestamp keeps meaning "when this was first recorded without proof".
    * it never touches ``status`` — the user's own tracker history, exactly as
      the backfill refuses to (see this module's docstring).

    Best-effort by design: bookkeeping the user asked for must not fail because
    an additive truth column could not be stamped. The failure is logged, and
    the pre-existing census/backfill still catches such a row.
    """
    try:
        _ensure_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    UPDATE "Application"
                    SET "submissionTruthState" = %s, "submissionTruthAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                      AND "transmittedAt" IS NULL
                      AND "submissionTruthState" IS NULL
                    ''',
                    (STATE_RECORDED_NOT_TRANSMITTED, application_id, user_id),
                )
                stamped = cur.rowcount > 0
            conn.commit()
    except Exception as exc:  # noqa: BLE001 — an additive marker is never fatal
        logger.warning(
            "u5d2.submission_truth.mark_recorded_not_transmitted failed for "
            "application %s (%s) — the row is unmarked and stays visible to the "
            "existing census",
            application_id, type(exc).__name__,
        )
        return False
    return stamped


def unverified_submission_ids(
    user_id: str | None = None, limit: int = 50, *, read_only: bool = False
) -> list[str]:
    """Sample of the rows the predicate matches — for evidence capture only.

    ``read_only=True`` guarantees the sample costs no DDL (see
    :func:`_read_predicate`).
    """
    sql = f'SELECT "id" FROM "Application" WHERE {_read_predicate(read_only)}'
    params: tuple[Any, ...] = ()
    if user_id is not None:
        sql += ' AND "userId" = %s'
        params = (user_id,)
    sql += ' ORDER BY "createdAt" DESC LIMIT %s'
    params = (*params, max(0, int(limit)))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [str(r["id"]) for r in rows_to_dicts(cur)]
