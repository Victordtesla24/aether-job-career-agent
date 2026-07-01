"""Scout agent (P2-S02): discover jobs across adapters and persist them.

``run_scout`` queries each configured adapter, then upserts the results via
:class:`~app.repositories.job.JobRepository` so re-runs are idempotent. A single
adapter failing (network/markup) must not sink the whole run, so per-adapter
errors are captured and reported rather than raised.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from psycopg2.extensions import connection as PgConnection

from app.repositories.job import JobRepository
from app.services.discovery.base_adapter import BaseAdapter

logger = logging.getLogger("aether.scout")


@dataclass
class ScoutResult:
    """Summary of a Scout run."""

    discovered: int = 0
    persisted: int = 0
    errors: list[str] = field(default_factory=list)


def run_scout(
    conn: PgConnection,
    user_id: str,
    query: str,
    location: str,
    adapters: Sequence[BaseAdapter],
) -> ScoutResult:
    """Run every adapter and persist discovered jobs for ``user_id``."""
    repo = JobRepository(conn)
    result = ScoutResult()

    for adapter in adapters:
        source = getattr(adapter, "source", adapter.__class__.__name__)
        try:
            jobs = adapter.fetch(query=query, location=location)
        except Exception as exc:  # noqa: BLE001 — isolate per-adapter failures
            logger.warning("Scout adapter %s failed: %s", source, exc)
            result.errors.append(f"{source}: {exc}")
            continue

        result.discovered += len(jobs)
        for job_raw in jobs:
            try:
                repo.create(user_id, job_raw)
                result.persisted += 1
            except Exception as exc:  # noqa: BLE001 — one bad row must not abort
                logger.warning("Failed to persist job from %s: %s", source, exc)
                result.errors.append(f"{source} persist: {exc}")

    logger.info(
        "Scout run for user=%s query=%r location=%r discovered=%d persisted=%d",
        user_id,
        query,
        location,
        result.discovered,
        result.persisted,
    )
    return result
