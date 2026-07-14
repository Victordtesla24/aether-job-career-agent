"""Matcher Agent — promotes the pipeline's inline match step to a first-class,
runnable, audited agent (P4 decomposition fix).

The matcher was already executing inside ``run_pipeline`` (ranking fit-scored
jobs and selecting the best-fit target) but was invisible in the agent catalog
and could not be triggered on its own. This class extracts that logic verbatim
so it can be dispatched via ``/agents/matcher/run`` and rendered as the
``jobMatching`` catalog card, while the pipeline reuses the same code path.

Deterministic: it ranks already-scored jobs by ``fitScore`` — no LLM call, no
spend (mirrors ``ScoutAgent``/``FitScorerAgent``'s plain-class, DI-defaulting
pattern).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.repositories.job import JobRepository


@dataclass
class MatchResult:
    """Ranking outcome for the audit ``output`` (asdict-serialized by the
    router's ``_record_run``). Field names match the dict the pipeline's inline
    matcher previously produced, so downstream consumers are unchanged."""

    matched: int
    top_job_id: Optional[str]
    top_job_title: Optional[str] = None
    top_company: Optional[str] = None
    top_fit_score: Optional[float] = None


class MatcherAgent:
    """Ranks a user's fit-scored jobs and selects the top match."""

    def __init__(self, repository: JobRepository | None = None) -> None:
        self._jobs = repository or JobRepository()

    def run(self, user_id: str) -> MatchResult:
        """Return the best-fit job for ``user_id`` (highest ``fitScore``).

        Returns a zero/None result when nothing has been discovered/scored yet —
        never fabricates a match.
        """
        jobs = self._jobs.list_by_user(user_id, sort="fitScore")
        if not jobs:
            return MatchResult(matched=0, top_job_id=None)
        top = jobs[0]
        return MatchResult(
            matched=len(jobs),
            top_job_id=top["id"],
            top_job_title=top.get("title"),
            top_company=top.get("company"),
            top_fit_score=top.get("fitScore"),
        )
