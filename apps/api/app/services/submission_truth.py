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

#: User-facing wording for :data:`STATE_UNVERIFIED`, served by
#: ``application_submission.submission_view`` so every surface says the same
#: sentence rather than inventing its own.
NOTE_UNVERIFIED = "recorded — transmission unverified (pre-fix)"

#: Human-readable note per state. A state with no note here is a programming
#: error, not a silent blank: ``submission_note_for`` returns ``None`` only for
#: an unstamped (NULL) row.
_NOTES = {STATE_UNVERIFIED: NOTE_UNVERIFIED}

#: The false-positive predicate, verbatim from the census: a row that CLAIMS a
#: submission (``status = 'submitted'``) while carrying no transmission
#: evidence whatsoever. Rows the user moved further along their own pipeline
#: (screening / interview / offer) are deliberately excluded — those carry the
#: user's own later, independent knowledge of what happened, and re-labelling
#: them "unverified" would contradict evidence we do not have.
_UNVERIFIED_PREDICATE = '''
    "status" = 'submitted'::"ApplicationStatus"
    AND "transmittedAt" IS NULL
    AND "submissionTruthState" IS NULL
'''


def submission_note_for(state: str | None) -> str | None:
    """The user-facing sentence for a persisted ``submissionTruthState``."""
    if not state:
        return None
    return _NOTES.get(state, state)


def _ensure_columns() -> None:
    ensure_application_transmission_columns()
    ensure_application_submission_truth_columns()


def count_unverified_submissions(user_id: str | None = None) -> int:
    """How many rows still claim a submission with no transmission evidence.

    Counted for real against the predicate the backfill uses, so the "before"
    number and the reclassified number can never drift apart.
    """
    _ensure_columns()
    sql = f'SELECT count(*) FROM "Application" WHERE {_UNVERIFIED_PREDICATE}'
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
        WHERE {_UNVERIFIED_PREDICATE}
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


def unverified_submission_ids(user_id: str | None = None, limit: int = 50) -> list[str]:
    """Sample of the rows the predicate matches — for evidence capture only."""
    _ensure_columns()
    sql = f'SELECT "id" FROM "Application" WHERE {_UNVERIFIED_PREDICATE}'
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
