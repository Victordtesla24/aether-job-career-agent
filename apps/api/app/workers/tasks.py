"""ARQ task bodies for async background generation (GAP-P7-ASYNC-001 §4.3).

Zero logic duplication: every task reuses the EXACT service code the sync
endpoints use. Single-agent jobs run ``agents._agent_callable`` +
``agents._execute_reserved_run`` (the §4.1 split of ``_record_run``); pipeline
jobs run ``agents._pipeline_core`` (the extraction the sync handler also calls).

The blocking sync service call is offloaded to a thread via
``asyncio.to_thread`` (mirroring what FastAPI already does for the sync ``def``
handlers), so ARQ's single event loop is never blocked for the 60-300 s
generation. ``to_thread`` copies the current ``contextvars.Context``, so the
``shared_budget`` ContextVar and per-user credential context propagate.

Failure contract (blueprint §4.3 / §9):
- NEVER fixture content on failure — ``mark_failed`` writes an honest error
  string only; ``result`` stays null.
- ALWAYS refund the reserved run(s). Single-agent: ``_execute_reserved_run``
  refunds on every failure path. Pipeline: a mid-run crash refunds every run
  the composite reserved (fable-5 condition 1 — a failed composite is not
  billed; completed sub-steps of a crashed pipeline are not separately charged).
- NO re-raise for permanent/business errors (no ARQ retry with the same bad
  input); only an explicit ``_TransientError`` re-raises for a retry.
- NO secret logging — logs ``type(e).__name__`` + message only.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.repositories.background_jobs import BackgroundJobRepository
from app.repositories.billing import UsageQuotaRepository

logger = logging.getLogger("aether.worker")


class _TransientError(Exception):
    """Infra-level (pre-generation) error safe for ARQ to retry. No generation
    path raises this today; all generation failures are terminal + refunded so a
    retry can never run against an already-refunded reservation."""


def _honest_message(exc: BaseException) -> str:
    """An honest, secret-free failure string. Never fixture content."""
    name = type(exc).__name__
    msg = str(exc).strip()
    return (f"{name}: {msg}" if msg else f"generation failed ({name})")[:500]


def _wrap_worker_budget(name: str, fn):
    """Wrap ``fn`` in the worker's (more generous, edge-free) LLM budget."""
    from app.services.llm_client import (
        get_worker_budget_seconds,
        get_worker_cover_budget_seconds,
        shared_budget,
    )

    seconds = (
        get_worker_cover_budget_seconds()
        if name == "coverLetter"
        else get_worker_budget_seconds()
    )

    def _run():
        with shared_budget(seconds):
            return fn()

    return _run


def _run_single_agent_body(job: dict[str, Any]) -> dict[str, Any]:
    """Execute a single-agent job by REUSING the sync service path. Quota was
    reserved and the AgentRun row created at enqueue; here we only execute."""
    from app.repositories.agent_run import AgentRunRepository
    from app.routers.agents import (
        _LLM_TIER_BY_BACKEND,
        _agent_callable,
        _billing_audit,
        _execute_reserved_run,
    )

    user_id = job["userId"]
    agent_key = job["agentKey"]
    run_id = job.get("runId")
    params = job.get("params") or {}
    metered = agent_key in _LLM_TIER_BY_BACKEND
    quota_repo = UsageQuotaRepository() if metered else None
    audit = _billing_audit(user_id, agent_key)[0]
    try:
        name, fn = _agent_callable(user_id, agent_key, params)
    except BaseException:
        # Callable resolution failed AFTER the enqueue-time reservation -> refund
        # here (it never reached _execute_reserved_run, which owns the refund).
        if quota_repo is not None and job.get("quotaReserved"):
            quota_repo.refund_run(user_id)
        if run_id:
            try:
                AgentRunRepository().finish(
                    run_id, "failed", error="callable resolution failed"
                )
            except Exception:  # noqa: BLE001 — audit best-effort
                pass
        raise
    budgeted = _wrap_worker_budget(name, fn)
    return _execute_reserved_run(run_id, user_id, name, params, budgeted, quota_repo, audit)


def _run_pipeline_body(user_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a pipeline job by REUSING the sync ``_pipeline_core`` orchestration
    (per-step atomic reserve/refund via ``_record_run``), under the worker's
    shared pipeline budget."""
    from app.routers.agents import _pipeline_core
    from app.services.llm_client import get_worker_pipeline_budget_seconds

    return _pipeline_core(
        user_id, params, budget_seconds=get_worker_pipeline_budget_seconds()
    )


def _runs_used(user_id: str) -> int:
    try:
        q = UsageQuotaRepository().get_by_user(user_id)
        return int(q["runsUsed"]) if q else 0
    except Exception:  # noqa: BLE001
        return 0


def _refund_pipeline_outstanding(user_id: str, before: int) -> None:
    """Refund every run reserved during a crashed pipeline (fable-5 condition 1).

    A failed step's own ``_record_run`` already refunded it; the remaining
    ``runsUsed - before`` corresponds to reservations the crash left standing
    (and, for a non-completing composite, completed sub-steps that are not
    separately billed). ``refund_run`` floors at 0."""
    delta = _runs_used(user_id) - before
    repo = UsageQuotaRepository()
    for _ in range(max(0, delta)):
        repo.refund_run(user_id)


async def run_agent_job(ctx: Any, job_id: str) -> None:
    """ARQ task: process one BackgroundJob to a terminal state (blueprint §4.3)."""
    repo = BackgroundJobRepository()
    job = repo.mark_processing(job_id)
    if job is None:
        return  # missing or already terminal — nothing to do
    user_id = job["userId"]

    if job["agentKey"] == "pipeline":
        before = _runs_used(user_id)
        try:
            result = await asyncio.to_thread(
                _run_pipeline_body, user_id, job.get("params") or {}
            )
        except _TransientError:
            raise
        except Exception as exc:  # noqa: BLE001 — terminal, honest, refunded
            _refund_pipeline_outstanding(user_id, before)
            repo.mark_failed(job_id, _honest_message(exc), refunded=True)
            logger.error(
                "pipeline job %s failed: %s: %s", job_id, type(exc).__name__, exc
            )
            return
        repo.mark_completed(job_id, result)
        return

    try:
        result = await asyncio.to_thread(_run_single_agent_body, job)
    except _TransientError:
        raise
    except Exception as exc:  # noqa: BLE001
        # _execute_reserved_run already refunded on its failure paths.
        repo.mark_failed(job_id, _honest_message(exc), refunded=True)
        logger.error("job %s failed: %s: %s", job_id, type(exc).__name__, exc)
        return
    repo.mark_completed(job_id, result)


async def sweep_stale_jobs(ctx: Any) -> int:
    """ARQ cron: fail + refund abandoned jobs nobody polls (blueprint §7.4).

    Bounds quota leakage when a worker dies before writing a terminal state."""
    from app.routers.agents import _job_stale_thresholds

    repo = BackgroundJobRepository()
    enq, proc = _job_stale_thresholds()
    stale = repo.sweep_stale(enq, proc)
    for job in stale:
        if job.get("quotaReserved") and job.get("quotaRefundedAt") is None:
            try:
                UsageQuotaRepository().refund_run(job["userId"])
            except Exception:  # noqa: BLE001
                pass
        repo.mark_failed(
            job["id"], "generation timed out (worker unavailable)", refunded=True
        )
    return len(stale)
