"""AgentDirective API — ADR-AGI-2 P1 (ORCH-B1-BLUEPRINT-2026-08-14.md §5.2).

A NEW, small router — deliberately NOT added to ``routers/agents.py`` (the
most-contested file in the tree right now: B1a/u2c/B6/D.524 all touch it).
Mounted at the SAME ``/agents`` prefix as ``agents.router`` in
``app.main.create_app``, so the public paths are exactly
``GET /agents/directives``, ``GET /agents/directives/history`` and
``POST /agents/directives/evaluate``.

Three routes, deliberately:

* ``GET /directives`` — active directives for every agent, one round trip.
* ``GET /directives/history`` — immutable history (incl. superseded) for ONE
  agent (``AgentDirectiveRepository.list_history`` requires an agent key —
  history is per-agent, not a global feed, so a caller must name one).
* ``POST /directives/evaluate`` — runs the Supervisor's Stage-1 rules
  evaluation for the CALLING user. This is the P1 issuance path and the ONLY
  one (blueprint DEV-6): the handler takes NO body — there is no field a
  caller can populate to make an arbitrary directive get stored. Every
  directive this endpoint can possibly create is computed by
  ``app.services.supervisor_rules.evaluate`` from real, already-instrumented
  metrics.

Every route is owner-scoped by construction: both repository methods take
``user_id`` from the authenticated caller, never from a request parameter, so
there is no id to guess and no cross-user leakage to test for.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from app.middleware.auth import CurrentUser
from app.rate_limit import SlidingWindowRateLimiter, _raise_429
from app.repositories.agent_directive import AgentDirectiveRepository

router = APIRouter()


def _isoformat(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _directive_out(row: dict[str, Any]) -> dict[str, Any]:
    """The wire shape for one directive row — blueprint §5.2's documented
    response, field-for-field. The FE (§8) reads ``rationale`` VERBATIM off
    this — it never composes its own explanation."""
    return {
        "id": row["id"],
        "agentKey": row["agentKey"],
        "status": row["status"],
        "directive": row.get("directive") or {},
        "clamped": row.get("clamped") or {},
        "rejectedKeys": row.get("rejectedKeys") or [],
        "rationale": row.get("rationale"),
        "metricsCited": row.get("metricsCited") or {},
        "issuedBy": row.get("issuedBy"),
        "supersededById": row.get("supersededById"),
        "outcome": row.get("outcome"),
        "issuedAt": _isoformat(row.get("issuedAt")),
        "expiresAt": _isoformat(row.get("expiresAt")),
    }


@router.get("/directives")
def get_active_directives(current_user: CurrentUser) -> dict[str, Any]:
    """Active directives for every agent this user has one for.

    ``paused`` reflects ``AETHER_AGI_DIRECTIVES_ENABLED`` (ADR-AGI-2's
    reversibility clause). When paused the array is STILL returned — history
    is never a lie — so the FE can render "not currently applied" rather than
    hiding rows that are, in fact, on record.
    """
    from app.routers.agents import agent_directives_enabled

    rows = AgentDirectiveRepository().list_active(current_user["id"])
    enabled = agent_directives_enabled()
    return {
        "directives": [_directive_out(row) for row in rows],
        "paused": not enabled,
        "pausedReason": (
            None
            if enabled
            else (
                "Directive issuance is paused on this deployment "
                "(AETHER_AGI_DIRECTIVES_ENABLED)."
            )
        ),
    }


@router.get("/directives/history")
def get_directive_history(
    current_user: CurrentUser,
    agentKey: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Every directive ever issued for ONE agent, newest first — active and
    superseded both (immutability: supersession never removes a row)."""
    rows = AgentDirectiveRepository().list_history(
        current_user["id"], agentKey, limit=limit
    )
    return {"agentKey": agentKey, "history": [_directive_out(row) for row in rows]}


@router.post("/directives/evaluate")
def evaluate_directives(request: Request, current_user: CurrentUser) -> dict[str, Any]:
    """Run the Supervisor's Stage-1 rules evaluation for the CALLING user.

    DEV-6: this is the ONLY way an ``AgentDirective`` is created. The handler
    declares NO body parameter — a caller cannot supply directive content,
    only trigger the deterministic evaluator
    (``app.services.supervisor_rules.rules_stage_evaluate``), which computes
    every field from real, already-instrumented metrics.

    Rate-limited like the neighbouring admin-ish/automation-triggering routes
    (``run_scout``'s cooldown, ``checkout``/``portal``): $0 and deterministic,
    but it still does DB reads/writes per call, so a per-user cooldown caps a
    button-mash from doing needless work rather than protecting a scarce
    upstream quota.
    """
    limiter: SlidingWindowRateLimiter | None = getattr(
        request.app.state, "agent_directives_evaluate_rate_limiter", None
    )
    if limiter is not None and not limiter.allow(current_user["id"]):
        _raise_429(
            limiter.retry_after(current_user["id"]),
            "Directive evaluation is rate-limited on this account. "
            "Please wait and try again.",
        )
    from app.services.supervisor_rules import rules_stage_evaluate

    return rules_stage_evaluate(current_user["id"])
