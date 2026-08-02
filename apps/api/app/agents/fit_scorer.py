"""FitScorer agent — ATS-scores every unscored job for a user (P2-S04).

Scores against the CALLER's OWN base resume text and REFUSES
(``MissingResumeError`` -> 422) when the user has no resume on file — a
no-resume user is NEVER scored against the bundled operator resume
(NF-final-B-008), so no operator-derived ``fitScore`` is ever persisted or
shown as their own. Runs :class:`ATSEngine` against each job description and
persists ``fitScore``/``atsScore`` via the job repository.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.repositories.job import JobRepository
from app.services.ats_engine import ATSEngine
from app.services.resume_grounding import require_user_resume_text

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


#: Minimum characters of real posting text before a fit score means anything.
#: MEASURED, not guessed (2026-08-02, production): rows with <200 chars of
#: description scored avg 58.9 / max 78.6, while rows carrying a real
#: description scored avg 40.8 / max 56.5. A posting with an EMPTY description
#: scored 74.63 — the highest on the board. With almost no text the engine has
#: nearly nothing to mismatch, so emptiness reads as a perfect fit and the
#: least-informative jobs float to the top of the user's board.
MIN_SCORABLE_CHARS = 200


def has_scorable_evidence(job_text: str) -> bool:
    """True when a posting carries enough real text for a score to mean anything."""
    return len((job_text or "").strip()) >= MIN_SCORABLE_CHARS


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
        for job in self._repository.list_by_user(user_id):
            if job.get("fitScore") is not None and not rescore:
                # RT-005 self-heal: a job scored before agent stage-sync existed
                # may still sit at "discovered" — advance it so the board stays
                # truthful. Guarded forward-only: never demotes a manual move.
                self._repository.advance_status(
                    job["id"], "screening", allowed_from={"discovered"}
                )
                continue
            try:
                jd = self._job_text(job)
                if not has_scorable_evidence(jd):
                    # HONEST REFUSAL: leave fitScore NULL rather than persist a
                    # spuriously-high number derived from a teaser line. The job
                    # still shows on the board — it is simply unranked, which is
                    # the truth, instead of being ranked top on no evidence.
                    result.skipped_no_evidence += 1
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

        NOTE (v5): callers must check :func:`has_scorable_evidence` first — a
        posting with almost no description scores spuriously HIGH, because the
        engine has nearly no tokens to mismatch against."""
        requirements = job.get("requirements")
        if isinstance(requirements, str):
            try:
                requirements = json.loads(requirements)
            except ValueError:
                requirements = [requirements]
        req_text = " ".join(requirements or [])
        return f"{job['title']} {job.get('description', '')} {req_text}".strip()
