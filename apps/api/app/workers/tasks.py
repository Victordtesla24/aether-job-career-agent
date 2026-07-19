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
    """An honest, secret-free failure string. Never fixture content.

    An :class:`HTTPException` already carries a user-facing ``detail`` a router
    deliberately chose (e.g. the honest LLM-unavailable message of
    MV-cover-letter-studio-005) — surface that verbatim rather than prefixing it
    with the exception class + status code (which would re-expose
    'HTTPException: 503: …' on the polled BackgroundJob.error)."""
    from fastapi import HTTPException

    if isinstance(exc, HTTPException):
        detail = str(exc.detail).strip()
        return (detail or f"generation failed ({type(exc).__name__})")[:500]
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
        # Callable resolution failed. Record the AgentRun as failed; the enqueue
        # reservation refund is performed by run_agent_job's atomic, idempotent,
        # first-terminal-wins path (mark_failed -> refund_single_reservation), so
        # it is NOT refunded here (avoids a double-refund with the watchdog).
        if run_id:
            try:
                AgentRunRepository().finish(
                    run_id, "failed", error="callable resolution failed"
                )
            except Exception:  # noqa: BLE001 — audit best-effort
                pass
        raise
    budgeted = _wrap_worker_budget(name, fn)
    # manage_quota=False: the worker performs the refund/spend via the atomic
    # BackgroundJob transition in run_agent_job, not inside _execute_reserved_run,
    # so a watchdog cannot double-refund or resurrect the job (BLOCKING-1/2).
    return _execute_reserved_run(
        run_id, user_id, name, params, budgeted, quota_repo, audit, manage_quota=False
    )


def _run_pipeline_body(user_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a pipeline job by REUSING the sync ``_pipeline_core`` orchestration
    (per-step atomic reserve/refund via ``_record_run``), under the worker's
    shared pipeline budget."""
    from app.routers.agents import _pipeline_core
    from app.services.llm_client import get_worker_pipeline_budget_seconds

    return _pipeline_core(
        user_id, params, budget_seconds=get_worker_pipeline_budget_seconds()
    )


def _refund_for_job(repo: "BackgroundJobRepository", job: dict[str, Any]) -> None:
    """Refund a terminated job's reservation(s), scoped to THIS job and idempotent
    (reviewer BLOCKING-1/3). Single-agent: the one enqueue reservation via the
    atomic claim CTE; pipeline: this job's own outstanding count (never a
    user-wide runsUsed delta)."""
    if job.get("agentKey") == "pipeline":
        repo.refund_pipeline_outstanding(job["id"])
    else:
        repo.refund_single_reservation(job["id"])


async def run_agent_job(ctx: Any, job_id: str) -> None:
    """ARQ task: process one BackgroundJob to a terminal state (blueprint §4.3).

    Terminal transitions are atomic first-terminal-wins (reviewer BLOCKING-2): the
    winner of mark_failed/mark_completed performs the associated billing side
    effect exactly once (refund on fail via the atomic claim; spend on complete)."""
    from app.agents.tailor_agent import NoChangesApplied
    from app.routers.agents import _pipeline_job_ctx
    from app.services.resume_grounding import MissingResumeError

    repo = BackgroundJobRepository()
    job = repo.mark_processing(job_id)
    if job is None:
        return  # missing or already terminal — nothing to do
    user_id = job["userId"]

    if job["agentKey"] == "pipeline":
        # Scope per-step reserves/refunds to THIS job so a mid-pipeline crash
        # refunds only its own outstanding reservations (BLOCKING-3). to_thread
        # copies the context, so the ContextVar propagates into _pipeline_core.
        token = _pipeline_job_ctx.set(job_id)
        try:
            result = await asyncio.to_thread(
                _run_pipeline_body, user_id, job.get("params") or {}
            )
        except _TransientError:
            _pipeline_job_ctx.reset(token)
            raise
        except Exception as exc:  # noqa: BLE001 — terminal, honest, refunded
            _pipeline_job_ctx.reset(token)
            if repo.mark_failed(job_id, _honest_message(exc)):
                repo.refund_pipeline_outstanding(job_id)
            logger.error(
                "pipeline job %s failed: %s: %s", job_id, type(exc).__name__, exc
            )
            return
        _pipeline_job_ctx.reset(token)
        repo.mark_completed(job_id, result)  # first-wins; if a stale watchdog beat
        # it, the job stays failed and no spend accrues (per-step spend already
        # recorded, but the composite reservation was refunded by that watchdog).
        return

    try:
        result = await asyncio.to_thread(_run_single_agent_body, job)
    except _TransientError:
        raise
    except NoChangesApplied as exc:
        # MV-adv-A-002: every proposed edit was rejected by the anti-fabrication
        # guard — a legitimate business no-op, NOT a failure. Mirror the honest
        # synchronous ``/tailor/run`` contract (agents.py ``run_tailor``'s
        # ``except NoChangesApplied`` handling): complete the job with an honest
        # no-op result and refund the reservation (never billed for a run that
        # changed nothing) — matching Resume Studio's no-op handling
        # (MV-resume-studio-003). Never marked 'failed', so no leaked
        # exception-class text ever reaches the client's error path.
        honest_result = {
            "resume_id": None,
            "changes": 0,
            "rejected": exc.rejected,
            "conversionMetrics": None,
            "noChangesApplied": True,
            "approvalRequired": False,
            "message": str(exc),
        }
        if repo.mark_completed(job_id, honest_result):
            repo.refund_single_reservation(job_id)
        logger.info("job %s no-op (NoChangesApplied): 0 net edits, refunded", job_id)
        return
    except MissingResumeError as exc:
        # NF-final-PII-002: an OUTBOUND generation path (cover letter, tailor,
        # fit-scorer) refused because this user has no résumé of their own — a
        # legitimate, honest refusal (NF-final-B-001/005/008), NOT a failure.
        # Mirror the NoChangesApplied handling immediately above: complete the
        # job with the SAME honest, PII-free message the synchronous 422 path
        # surfaces (main.py's ``MissingResumeError`` handler renders
        # ``str(exc)`` verbatim) and refund the reservation — never "failed",
        # and never the leaked "MissingResumeError:" class prefix the generic
        # ``except Exception`` branch below would add via ``_honest_message``.
        honest_message = str(exc).strip() or "Add your resume before generating this."
        honest_result = {
            "resume_id": None,
            "missingResume": True,
            "message": honest_message,
        }
        if repo.mark_completed(job_id, honest_result):
            repo.refund_single_reservation(job_id)
        logger.info(
            "job %s refused (MissingResumeError): no resume on file, refunded", job_id
        )
        return
    except Exception as exc:  # noqa: BLE001
        # First-terminal-wins: only the winner refunds (atomic + idempotent claim),
        # so a watchdog that already failed+refunded this job is not double-counted.
        if repo.mark_failed(job_id, _honest_message(exc)):
            repo.refund_single_reservation(job_id)
        logger.error("job %s failed: %s: %s", job_id, type(exc).__name__, exc)
        return
    # Success: record spend ONLY if we win the terminal transition. If a stale
    # watchdog already failed+refunded this job, mark_completed is a no-op and we
    # skip spend — the job stays failed and the user is not billed (no free run).
    if repo.mark_completed(job_id, result):
        if job.get("quotaReserved"):
            try:
                UsageQuotaRepository().record_spend(
                    user_id, float(result.get("costUsd", 0) or 0)
                )
            except Exception:  # noqa: BLE001 — spend accounting best-effort
                pass


async def sweep_stale_jobs(ctx: Any) -> int:
    """ARQ cron: fail + refund abandoned jobs nobody polls (blueprint §7.4).

    Bounds quota leakage when a worker dies before writing a terminal state. Uses
    the same atomic first-terminal-wins + scoped-idempotent refund as the lazy
    watchdog (reviewer BLOCKING-1/2/3), so a sweep racing a lazy-GET poll or a
    live worker refunds each reservation exactly once."""
    from app.routers.agents import _job_stale_thresholds

    repo = BackgroundJobRepository()
    enq, proc = _job_stale_thresholds()
    stale = repo.sweep_stale(enq, proc)
    swept = 0
    for job in stale:
        if repo.mark_failed(job["id"], "generation timed out (worker unavailable)"):
            _refund_for_job(repo, job)
            swept += 1
    return swept
