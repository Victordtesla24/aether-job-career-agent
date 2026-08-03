"""Retire the fit scores that were persisted BEFORE the evidence gate existed.

WHY THIS MODULE EXISTS
----------------------
Commit ``557739e`` added :func:`app.services.fit_evidence.has_scorable_evidence`
so a posting with no real text is never GIVEN a fit score. It did nothing about
the scores already sitting in the database, and it could not: ``FitScorerAgent``
skipped every job that already carried one. Measured in production on
2026-08-03, at the commit that shipped that gate:

    48 scored rows whose evidence text is below the gate
        seek-alert       45  (average 15 characters of description)
        smartrecruiters   3
    top of that set: 76.76, 74.63, 73.51 — higher than EVERY row that carries a
    real description (those top out around 56).

The board orders by ``fitScore DESC NULLS LAST``. So the gate's own honest
refusals (NULL) sorted last while the pre-gate junk sorted FIRST: shipping the
gate alone left the user's board still led by postings the scorer now refuses
to score at all.

WHAT IT DOES, AND WHAT IT DELIBERATELY DOES NOT
-----------------------------------------------
* CLEARS ``fitScore``/``atsScore`` (to NULL — see
  :meth:`app.repositories.job.JobRepository.clear_fit_score`) on every row whose
  evidence text is below the gate. Nothing else about the row is touched: the
  description, the status and the job itself are left exactly as they are.
  History is never deleted here.
* DOES NOT SCORE ANYTHING. Scoring needs the owning user's own résumé
  (NF-final-B-008) and belongs to the fit-scorer run, which picks up every
  cleared row automatically the moment it carries real evidence again — that is
  how a SmartRecruiters row whose description gets backfilled (db30f33) is
  re-derived. :func:`count_rescorable` reports how many rows are waiting for
  that, so "nothing was re-derived" can never hide.
* JUDGES ROWS IN PYTHON, not in SQL, using the same
  :func:`app.services.fit_evidence.job_evidence_text` +
  :func:`app.services.fit_evidence.has_scorable_evidence` the scorer uses. A
  hand-written SQL length expression would be a second, drifting definition of
  the gate, and it cannot faithfully reproduce ``str.strip()`` semantics over a
  whitespace-only description. Rows are streamed in keyset-paged batches so the
  scan is memory-bounded however large the table grows.

Idempotent and additive: a second run finds nothing left to clear, and no
schema change is involved.

WHERE IT RUNS
-------------
Automatically, from two places — nobody has to remember a script:

1. ``app.main._lifespan`` — every application start, for every user. This is
   what remediates the rows that already exist. It is best-effort: a failure is
   logged loudly and the API still boots (same availability ruling as
   BLOCKER-001 — never convert a data problem into an outage).
2. ``FitScorerAgent.run`` — per row, per run, through the same gate. That path
   keeps the invariant true between restarts.

``scripts/fit_score_evidence_sweep.py`` is the operator entrypoint for
reporting/verification; it is not required for the fix to take effect.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Iterator

from app.db import get_connection, rows_to_dicts
from app.services.fit_evidence import (
    MIN_SCORABLE_CHARS,
    has_scorable_evidence,
    job_evidence_text,
)

logger = logging.getLogger(__name__)

#: Rows fetched per round-trip. Bounded so the startup sweep's memory cost does
#: not grow with the table.
_BATCH_SIZE = 500

_EVIDENCE_COLUMNS = '"id", "title", "description", "requirements"'


@dataclass
class FitScoreRemediation:
    """Honest before/after accounting for one sweep (§8.1(a))."""

    #: Scored rows examined.
    scanned: int = 0
    #: Rows whose persisted score was retired by THIS sweep.
    cleared: int = 0
    #: Scored-but-evidence-free rows found before the sweep wrote anything.
    before_scored_without_evidence: int = 0
    #: The same count, RE-READ from the database after the commit — never the
    #: arithmetic the caller could have done itself.
    after_scored_without_evidence: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iter_scored_jobs(
    user_id: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Stream every row that carries a persisted score, in keyset-paged batches.

    A row is "scored" if EITHER score column is set — a half-written pair is
    exactly the kind of row this sweep must not miss.
    """
    clauses = ['("fitScore" IS NOT NULL OR "atsScore" IS NOT NULL)', '"id" > %s']
    if user_id is not None:
        clauses.append('"userId" = %s')
    sql = (
        f'SELECT {_EVIDENCE_COLUMNS} FROM "Job" '
        f'WHERE {" AND ".join(clauses)} ORDER BY "id" LIMIT {_BATCH_SIZE}'
    )
    last_id = ""
    while True:
        params: list[Any] = [last_id]
        if user_id is not None:
            params.append(user_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                batch = rows_to_dicts(cur)
        if not batch:
            return
        yield batch
        last_id = batch[-1]["id"]


def scored_without_evidence(user_id: str | None = None) -> list[str]:
    """Ids of persisted scores that the evidence gate would refuse to compute.

    Read-only. This is the measurement behind both the ``before`` and the
    ``after`` count, so they are produced by identical code against the real
    table rather than by counting what the sweep believes it did.
    """
    offenders: list[str] = []
    for batch in _iter_scored_jobs(user_id):
        offenders.extend(
            row["id"]
            for row in batch
            if not has_scorable_evidence(job_evidence_text(row))
        )
    return offenders


def count_rescorable(user_id: str | None = None) -> int:
    """Rows that DO carry real evidence but have no score yet.

    These are re-derived by the next fit-scorer run for their owner (it scores
    every unscored job that passes the gate). Counted here so a sweep can state
    what is still owed instead of implying the board is fully scored.

    ``"fitScore" IS NULL`` is the predicate on purpose: it is exactly the
    condition ``FitScorerAgent.run`` uses to decide a row still needs scoring,
    so this count can never claim work the scorer would not actually do.
    """
    clauses = ['"fitScore" IS NULL', '"id" > %s']
    if user_id is not None:
        clauses.append('"userId" = %s')
    sql = (
        f'SELECT {_EVIDENCE_COLUMNS} FROM "Job" '
        f'WHERE {" AND ".join(clauses)} ORDER BY "id" LIMIT {_BATCH_SIZE}'
    )
    last_id = ""
    total = 0
    while True:
        params: list[Any] = [last_id]
        if user_id is not None:
            params.append(user_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                batch = rows_to_dicts(cur)
        if not batch:
            return total
        total += sum(
            1 for row in batch if has_scorable_evidence(job_evidence_text(row))
        )
        last_id = batch[-1]["id"]


def _clear(job_ids: list[str]) -> int:
    if not job_ids:
        return 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Job" SET "fitScore" = NULL, "atsScore" = NULL, '
                '"updatedAt" = NOW() WHERE "id" = ANY(%s) '
                'AND ("fitScore" IS NOT NULL OR "atsScore" IS NOT NULL)',
                (job_ids,),
            )
            cleared = cur.rowcount
        conn.commit()
    return cleared


def remediate_unscorable_fit_scores(
    user_id: str | None = None,
) -> FitScoreRemediation:
    """Clear every persisted score whose row is below the evidence gate.

    Pass ``user_id`` to scope the sweep to one account; the default sweeps every
    row in the table, which is what the startup path needs.
    """
    result = FitScoreRemediation()
    offenders: list[str] = []
    for batch in _iter_scored_jobs(user_id):
        result.scanned += len(batch)
        offenders.extend(
            row["id"]
            for row in batch
            if not has_scorable_evidence(job_evidence_text(row))
        )
    result.before_scored_without_evidence = len(offenders)

    for start in range(0, len(offenders), _BATCH_SIZE):
        result.cleared += _clear(offenders[start : start + _BATCH_SIZE])

    if offenders:
        # Re-read the offending set from the database, AFTER the commit — never
        # the arithmetic (before - cleared) the caller could have done itself.
        result.after_scored_without_evidence = len(scored_without_evidence(user_id))
    else:
        # Nothing was written, so the scan just completed IS the after-state.
        # Repeating it would be a second full pass on every application start
        # (the steady-state case) to re-derive a zero we have already measured.
        result.after_scored_without_evidence = result.before_scored_without_evidence
    if result.cleared or result.after_scored_without_evidence:
        logger.warning(
            "fit-score evidence remediation: scanned=%d cleared=%d "
            "before=%d after=%d (gate=%d chars, scope=%s)",
            result.scanned,
            result.cleared,
            result.before_scored_without_evidence,
            result.after_scored_without_evidence,
            MIN_SCORABLE_CHARS,
            user_id or "all users",
        )
    return result
