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
                continue
            try:
                jd = self._job_text(job)
                score = self._engine.score(resume_text, jd)
                self._repository.update_fit_score(job["id"], score.overall, score.overall)
                result.scored += 1
            except Exception as exc:  # noqa: BLE001 — one bad job must not sink the run
                result.errors.append(f"{job['id']}: {exc}")
        return result

    @staticmethod
    def _job_text(job: dict[str, Any]) -> str:
        requirements = job.get("requirements")
        if isinstance(requirements, str):
            try:
                requirements = json.loads(requirements)
            except ValueError:
                requirements = [requirements]
        req_text = " ".join(requirements or [])
        return f"{job['title']} {job.get('description', '')} {req_text}".strip()
