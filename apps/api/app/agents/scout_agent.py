"""Scout agent — runs discovery adapters and persists results (P2-S02).

The scout fans out over every registered job-board adapter, normalizes the
postings, and upserts them for the requesting user. Duplicate ``sourceUrl``s
are absorbed by the repository's (userId, sourceUrl) upsert, so repeated runs
are idempotent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.repositories.job import JobRepository
from app.services.discovery.adapter_registry import ADAPTERS

logger = logging.getLogger(__name__)


@dataclass
class ScoutResult:
    """Summary of a scout run."""

    persisted: int = 0
    errors: list[str] = field(default_factory=list)


class ScoutAgent:
    """Discovers jobs across all sources and persists them for a user."""

    def __init__(self, repository: JobRepository | None = None) -> None:
        self._repository = repository or JobRepository()

    def run(self, user_id: str, query: str, location: str) -> ScoutResult:
        result = ScoutResult()
        for source, adapter_cls in ADAPTERS.items():
            try:
                jobs = adapter_cls().fetch(query=query, location=location)
            except NotImplementedError as exc:
                # Live mode not available for this source — skip, don't fail.
                logger.info("scout: skipping %s (%s)", source, exc)
                continue
            except Exception as exc:  # noqa: BLE001 — one bad source must not sink the run
                logger.warning("scout: %s adapter failed: %s", source, exc)
                result.errors.append(f"{source}: {exc}")
                continue
            for job in jobs:
                if not job.get("sourceUrl"):
                    continue
                self._repository.create(user_id, job)
                result.persisted += 1
        return result
