"""FitScorer agent — ATS-scores every unscored job for a user (P2-S04).

Scores against the CALLER's OWN base resume text and REFUSES
(``MissingResumeError`` -> 422) when the user has no resume on file — a
no-resume user is NEVER scored against the bundled operator resume
(NF-final-B-008), so no operator-derived ``fitScore`` is ever persisted or
shown as their own. Runs :class:`ATSEngine` against each job description and
persists ``fitScore``/``atsScore`` via the job repository.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.repositories.job import JobRepository
from app.services.ats_engine import ATSEngine
from app.services.fit_evidence import (
    MIN_SCORABLE_CHARS,
    has_scorable_evidence,
    job_evidence_text,
)
from app.services.resume_grounding import require_user_resume_text

__all__ = [
    "FitScoreResult",
    "FitScorerAgent",
    "MIN_SCORABLE_CHARS",
    "get_base_resume_path",
    "has_scorable_evidence",
]

#: Repo-root bundled base resume (read-only). Overridable for tests/deploys.
_DEFAULT_RESUME = Path(__file__).resolve().parents[4] / "assets" / "resume" / "Vik_Resume_Final.pdf"


def get_base_resume_path() -> Path:
    return Path(os.environ.get("AETHER_RESUME_PDF", str(_DEFAULT_RESUME)))


@dataclass
class FitScoreResult:
    scored: int = 0
    errors: list[str] = field(default_factory=list)
    #: Postings left UNSCORED because they carry too little real text for a
    #: score to mean anything (v5). Not a failure — an honest refusal.
    skipped_no_evidence: int = 0
    #: Postings whose ALREADY-PERSISTED score was retired by this run because
    #: the row does not carry enough evidence to justify it. These are the
    #: pre-gate scores (see :meth:`FitScorerAgent.run`); a subset of
    #: ``skipped_no_evidence``, counted separately so a remediating run is
    #: visibly different from a run that merely refused new work.
    cleared_no_evidence: int = 0


class FitScorerAgent:
    """Scores all unscored jobs for a user with the deterministic ATS engine."""

    def __init__(
        self, repository: JobRepository | None = None, engine: ATSEngine | None = None
    ) -> None:
        self._repository = repository or JobRepository()
        self._engine = engine or ATSEngine()

    def run(self, user_id: str, rescore: bool = False) -> FitScoreResult:
        result = FitScoreResult()
        # Score ONLY against the caller's own resume; refuse (no operator
        # fallback, no operator-derived fitScore) when they have none — the
        # reserved run is refunded on this exception (NF-final-B-008).
        resume_text = require_user_resume_text(
            user_id, "Add your resume before scoring jobs against it."
        )
        # BLOCKER-007: read through the scorer's own bounded, narrow projection
        # — NOT the board's ``list_by_user``, whose unbounded three-correlated-
        # subqueries-per-row SELECT crossed the hosted 5 s statement timeout at
        # 5848 rows and made this endpoint 500 on every discovery cycle. Same
        # rows, same order-independent semantics; see
        # ``JobRepository.iter_scoring_candidates`` for why nothing is filtered
        # out in SQL.
        for job in self._repository.iter_scoring_candidates(user_id):
            # EITHER column being set means a score is persisted on this row —
            # a half-written pair is exactly what remediation must not miss.
            # The SKIP decision below deliberately stays on "fitScore is not
            # None", the condition this loop has always used, so this change
            # retires stale scores WITHOUT quietly altering which rows a normal
            # run re-scores.
            has_persisted_score = (
                job.get("fitScore") is not None or job.get("atsScore") is not None
            )
            try:
                jd = self._job_text(job)
                if not has_scorable_evidence(jd):
                    # HONEST REFUSAL: leave fitScore NULL rather than persist a
                    # spuriously-high number derived from a teaser line. The job
                    # still shows on the board — it is simply unranked, which is
                    # the truth, instead of being ranked top on no evidence.
                    if has_persisted_score:
                        # ...and RETIRE a score this row should never have had.
                        # The gate (557739e) only stopped NEW junk from being
                        # written; the rows scored before it shipped were
                        # unreachable, because the skip-if-already-scored branch
                        # below walked straight past them. Production still had
                        # 48 of them, led by a 76.76 on a 29-character posting —
                        # above every row carrying a real description. The board
                        # sorts fitScore DESC NULLS LAST, so the junk led the
                        # board while the gate's own refusals sorted last.
                        self._repository.clear_fit_score(job["id"])
                        result.cleared_no_evidence += 1
                    result.skipped_no_evidence += 1
                    continue
                if job.get("fitScore") is not None and not rescore:
                    # RT-005 self-heal: a job scored before agent stage-sync
                    # existed may still sit at "discovered" — advance it so the
                    # board stays truthful. Guarded forward-only: never demotes
                    # a manual move.
                    self._repository.advance_status(
                        job["id"], "screening", allowed_from={"discovered"}
                    )
                    continue
                score = self._engine.score(resume_text, jd)
                self._repository.update_fit_score(job["id"], score.overall, score.overall)
                # RT-005: a scored job has been evaluated — its board card
                # belongs in "Evaluating", not "Discovered". Forward-only.
                self._repository.advance_status(
                    job["id"], "screening", allowed_from={"discovered"}
                )
                result.scored += 1
            except Exception as exc:  # noqa: BLE001 — one bad job must not sink the run
                result.errors.append(f"{job['id']}: {exc}")
        return result

    @staticmethod
    def _job_text(job: dict[str, Any]) -> str:
        """Text scored against the résumé.

        Delegates to :func:`app.services.fit_evidence.job_evidence_text` so the
        scoring path and the startup remediation judge a row on exactly the
        same string — see that module's docstring for why it is a leaf.

        NOTE (v5): callers must check :func:`has_scorable_evidence` first — a
        posting with almost no description scores spuriously HIGH, because the
        engine has nearly no tokens to mismatch against."""
        return job_evidence_text(job)
