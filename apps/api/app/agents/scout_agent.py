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
from app.services.discovery import qualification
from app.services.discovery.adapter_registry import ADAPTERS
from app.services.discovery.base_adapter import SourceBlockedError

logger = logging.getLogger(__name__)


@dataclass
class ScoutResult:
    """Summary of a scout run."""

    persisted: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)
    #: v5 agent-qualification accounting — how the board decision was actually
    #: made this run. Surfaced so "we considered everything" is never implied.
    qualification: dict[str, Any] = field(default_factory=dict)
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
        # v5: role fit is decided HERE, against the user's real résumé, not by a
        # title regex inside an adapter. Adapters now return every posting the
        # user could actually take (location gate only); qualification scores the
        # rest with the real ATS engine. Résumé load is best-effort — with none,
        # qualification falls back to the title fast path and says so.
        resume_text = ""
        engine = None
        try:
            from app.services.ats_engine import ATSEngine
            from app.services.resume_grounding import require_user_resume_text

            resume_text = require_user_resume_text(
                user_id, "Add your resume so discovered jobs can be scored against it."
            )
            engine = ATSEngine()
        except Exception as exc:  # noqa: BLE001 — never sink a sweep over scoring setup
            logger.warning(
                "scout: qualification degraded to the title fast path (%s: %s)",
                type(exc).__name__, exc,
            )
        # The decider's cut comes from this user's REAL existing board scores,
        # not a constant. Best-effort: absent history it falls back to the live
        # distribution of the batch actually fetched.
        history_scores: list[float] = []
        try:
            history_scores = [
                float(j["fitScore"])
                for j in self._repository.list_by_user(user_id)
                if j.get("fitScore") is not None
            ]
        except Exception as exc:  # noqa: BLE001 — history is an optimisation, not a gate
            logger.warning("scout: could not load score history (%s)", exc)
        qual_totals: dict[str, Any] = {
            "qualified": 0, "judged": 0, "rejected": 0,
            "unjudged": 0, "errors": [], "decisionBasis": "",
        }
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
            except SourceBlockedError as exc:
                # RT-008: the ADAPTER determined its source permanently blocks
                # automated access from this server (e.g. wellfound 403). Not
                # user-actionable, so it is a disclosed "blocked" state, NOT a
                # run error re-alarming every sync. Narrow by TYPE, never by
                # error string — a plain AdapterFetchError (incl. an ATS
                # provider 403ing across all boards) stays an honest error.
                message = f"{type(exc).__name__}: {exc}"
                logger.info("scout: %s blocked upstream: %s", source, message)
                src["status"] = "blocked"
                src["error"] = message
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
            # Agent qualification: decide which of these the user should see.
            qres = qualification.qualify(
                jobs,
                resume_text=resume_text,
                engine=engine,
                history_scores=history_scores,
            )
            # Persist what the agent QUALIFIED plus anything it could not judge.
            # A posting is only ever dropped on real evidence (scored below this
            # user's own bar) — never because we lacked a résumé, an engine, or
            # compute budget. Unjudged rows persist unranked and are scored on a
            # later sweep by fitScorer.
            jobs = list(qres.qualified) + list(qres.unjudged_jobs)
            src["qualified"] = len(qres.qualified)
            src["unjudged"] = len(qres.unjudged_jobs)
            for key, value in qres.as_dict().items():
                if key == "errors":
                    qual_totals["errors"].extend(value)
                elif key == "decisionBasis":
                    if value:
                        qual_totals["decisionBasis"] = value
                else:
                    qual_totals[key] = qual_totals.get(key, 0) + value
            no_source_url = 0
            for job in jobs:
                if not job.get("sourceUrl"):
                    title = job.get("title", "")[:80]
                    company = job.get("company", "")[:80]
                    logger.warning(
                        "scout: %s job skipped — empty sourceUrl (title=%r company=%r); "
                        "the adapter MUST populate sourceUrl for deduplication",
                        source, title, company,
                    )
                    no_source_url += 1
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
            if no_source_url:
                logger.warning(
                    "scout: %s dropped %d/%d jobs with empty sourceUrl — "
                    "deduplication requires every job to carry its real apply URL",
                    source, no_source_url, len(jobs),
                )
            result.per_source.append(src)
            self._record_status(user_id, src)
        result.qualification = qual_totals
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
