"""Scout agent — runs discovery adapters and persists results (P2-S02).

The scout fans out over every registered job-board adapter, normalizes the
postings, and upserts them for the requesting user. Duplicate ``sourceUrl``s
are absorbed by the repository's (userId, sourceUrl) upsert, so repeated runs
are idempotent.

Honest per-source status (GAP-SRC-002): a source whose live fetch FAILS is
recorded as a per-source error (never swallowed as a benign skip), and every
run returns a ``per_source`` breakdown of ``{source, fetched, persisted,
updated, error, status}``. That breakdown is also persisted to
``JobSourceStatus`` so discovery health is visible even between runs. Only a
source that genuinely has no live mode (``NotImplementedError`` — the legacy
fixture-only LinkedIn/Indeed adapters) is a benign ``skipped``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.repositories.job import JobRepository
from app.repositories.job_source_status import JobSourceStatusRepository
from app.services.discovery.adapter_registry import ADAPTERS

logger = logging.getLogger(__name__)


@dataclass
class ScoutResult:
    """Summary of a scout run."""

    persisted: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)
    #: One entry per source: {source, fetched, persisted, updated, error, status}.
    per_source: list[dict[str, Any]] = field(default_factory=list)


class ScoutAgent:
    """Discovers jobs across all sources and persists them for a user."""

    def __init__(
        self,
        repository: JobRepository | None = None,
        status_repository: JobSourceStatusRepository | None = None,
    ) -> None:
        self._repository = repository or JobRepository()
        self._status_repository = status_repository or JobSourceStatusRepository()

    def run(self, user_id: str, query: str, location: str) -> ScoutResult:
        result = ScoutResult()
        # Cross-source dedupe within a run: (company, title, apply URL).
        seen: set[tuple[str, str, str]] = set()
        for source, adapter_cls in ADAPTERS.items():
            src: dict[str, Any] = {
                "source": source,
                "fetched": 0,
                "persisted": 0,
                "updated": 0,
                "error": None,
                "status": "ok",
            }
            try:
                jobs = adapter_cls().fetch(query=query, location=location)
            except NotImplementedError as exc:
                # Source has no live mode at all (legacy fixture-only) — a
                # genuine skip, not a failure.
                logger.info("scout: skipping %s (no live mode: %s)", source, exc)
                src["status"] = "skipped"
                result.per_source.append(src)
                self._record_status(user_id, src)
                continue
            except Exception as exc:  # noqa: BLE001 — SURFACE the failure, don't swallow it
                message = f"{type(exc).__name__}: {exc}"
                logger.warning("scout: %s adapter failed: %s", source, message)
                src["status"] = "error"
                src["error"] = message
                result.errors.append(f"{source}: {message}")
                result.per_source.append(src)
                self._record_status(user_id, src)
                continue

            src["fetched"] = len(jobs)
            for job in jobs:
                if not job.get("sourceUrl"):
                    continue
                key = (
                    job["company"].strip().lower(),
                    job["title"].strip().lower(),
                    job["sourceUrl"].strip(),
                )
                if key in seen:
                    continue
                seen.add(key)
                row = self._repository.create(user_id, job)
                # The repository upserts on (userId, sourceUrl): only a row that
                # was actually inserted counts as a discovery — a re-discovered
                # job is a refresh, not a new role.
                if isinstance(row, dict) and row.get("wasInserted") is False:
                    result.updated += 1
                    src["updated"] += 1
                else:
                    result.persisted += 1
                    src["persisted"] += 1
            result.per_source.append(src)
            self._record_status(user_id, src)
        return result

    def _record_status(self, user_id: str, src: dict[str, Any]) -> None:
        """Persist a per-source status row. Best-effort: a status-write failure
        is logged (never silently ignored) and never fails the run — the fetch
        errors themselves are already surfaced in ``per_source``/``errors``."""
        try:
            self._status_repository.upsert(
                user_id,
                src["source"],
                fetched=src["fetched"],
                persisted=src["persisted"],
                error=src["error"],
                status=src["status"],
            )
        except Exception as exc:  # noqa: BLE001 — additive status store; run stays valid
            logger.warning(
                "scout: failed to persist source status for %s: %s", src["source"], exc
            )
