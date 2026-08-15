"""Sales Agent admin router — mounted at ``/admin/sales-agent`` (public
contract ``/api/admin/sales-agent/*``).

EVERY route depends on ``AdminUser``: anonymous → 401, non-admin → 403 —
the whole surface is admin-only (build brief §4.4: the sales agent must not
appear on any user-facing dashboard; its visibility lives entirely under
``/admin``).

Honesty contract: every number returned here is a live database query
(:meth:`SalesRepository.overview` et al). ``replyRate`` is ``null`` — not
``0`` — when it is genuinely not observable.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.agents.sales_agent import (
    AGENT_KEY,
    ensure_agent_config,
    resolve_admin_user_id,
    resolve_model,
    run_sales_agent,
    sales_agent_dry_run,
    sales_agent_enabled,
)
from app.db import get_connection
from app.middleware.auth import AdminUser
from app.repositories.sales import (
    CAMPAIGN_TYPES,
    SalesRepository,
)
from app.services.llm_client import _STATIC_MODEL_CATALOG

logger = logging.getLogger("aether.sales_agent")

router = APIRouter()

#: 2× the 30-min timer interval — the health alarm line (mirrors the
#: discovery scheduler's 3×-interval convention, tightened per build brief).
_HEALTH_STALE_MINUTES = 60


def _repo() -> SalesRepository:
    return SalesRepository()


# ------------------------------------------------------------------ overview
@router.get("/overview")
def overview(_admin: AdminUser) -> dict[str, Any]:
    repo = _repo()
    repo.seed_default_campaigns()  # UI never starts empty
    return repo.overview()


# --------------------------------------------------------------------- leads
@router.get("/leads")
def list_leads(
    _admin: AdminUser,
    lead_status: Optional[str] = Query(None, alias="status"),
    source: Optional[str] = None,
    consent_type: Optional[str] = Query(None, alias="consentType"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows, total = _repo().list_leads(
        status=lead_status, source=source, consent_type=consent_type,
        limit=limit, offset=offset,
    )
    return {"leads": rows, "total": total, "limit": limit, "offset": offset}


# ----------------------------------------------------------------- campaigns
class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str
    templateBody: str = Field(min_length=1, max_length=20000)
    active: bool = True


class CampaignUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    templateBody: Optional[str] = Field(None, min_length=1, max_length=20000)
    active: Optional[bool] = None


@router.get("/campaigns")
def list_campaigns(_admin: AdminUser) -> dict[str, Any]:
    repo = _repo()
    repo.seed_default_campaigns()
    return {"campaigns": repo.list_campaigns()}


@router.post("/campaigns", status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignCreate, _admin: AdminUser) -> dict[str, Any]:
    if payload.type not in CAMPAIGN_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"type must be one of {sorted(CAMPAIGN_TYPES)}",
        )
    return _repo().create_campaign(
        name=payload.name, ctype=payload.type,
        template_body=payload.templateBody, active=payload.active,
    )


@router.put("/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: str, payload: CampaignUpdate, _admin: AdminUser
) -> dict[str, Any]:
    row = _repo().update_campaign(
        campaign_id,
        name=payload.name,
        template_body=payload.templateBody,
        active=payload.active,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return row


# -------------------------------------------------------------- outreach log
@router.get("/outreach-log")
def outreach_log(
    _admin: AdminUser,
    outcome: Optional[str] = None,
    channel: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows, total = _repo().list_outreach(
        outcome=outcome, channel=channel, limit=limit, offset=offset
    )
    return {"entries": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/suppressions")
def suppressions(_admin: AdminUser) -> dict[str, Any]:
    repo = _repo()
    return {
        "suppressions": repo.list_suppressions(),
        "total": repo.suppression_count(),
    }


# ------------------------------------------------------------------- run-now
@router.post("/run-now")
def run_now(_admin: AdminUser) -> dict[str, Any]:
    """Trigger one full pipeline run synchronously (honest no-op when the
    feature flag is off; shadow mode logs ``dry_run`` rows, sends nothing)."""
    try:
        return run_sales_agent(trigger="manual")
    except Exception as exc:  # noqa: BLE001 — surface the real reason, not a 500 page
        logger.exception("manual sales agent run failed")
        raise HTTPException(
            status_code=502, detail=f"Sales agent run failed: {exc}"
        ) from exc


# -------------------------------------------------------------------- health
@router.get("/health")
def health(_admin: AdminUser) -> dict[str, Any]:
    """Timer health from the run ledger (mirrors the discovery scheduler's
    honest pattern): ok ≤ 60 min (2× the 30-min interval), else stale."""
    from datetime import datetime, timezone

    repo = _repo()
    admin_id = resolve_admin_user_id()
    enabled = sales_agent_enabled()
    dry_run = sales_agent_dry_run()
    sending_accounts = (
        len(repo.sales_sending_accounts(admin_id)) if admin_id else 0
    )
    base: dict[str, Any] = {
        "enabled": enabled,
        "dryRun": dry_run,
        "sendingAccounts": sending_accounts,
        "intervalMinutes": 30,
        "staleAfterMinutes": _HEALTH_STALE_MINUTES,
    }
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT MAX("startedAt") FROM "AgentRun" '
                    'WHERE "agentName" = %s',
                    (AGENT_KEY,),
                )
                row = cur.fetchone()
        last = row[0] if row else None
    except Exception:  # noqa: BLE001 — DB probe failure is itself the signal
        return {**base, "status": "error",
                "detail": "Could not read the sales agent run ledger."}
    if last is None:
        return {
            **base,
            "status": "not_configured" if enabled else "disabled",
            "detail": "No sales agent runs recorded yet.",
            "lastRunAt": None,
        }
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age_min = int((datetime.now(timezone.utc) - last).total_seconds() // 60)
    if age_min <= _HEALTH_STALE_MINUTES:
        return {
            **base,
            "status": "ok",
            "detail": f"Last run {age_min} min ago (timer fires every 30 min).",
            "lastRunAt": last.isoformat(),
        }
    return {
        **base,
        "status": "stale",
        "detail": (
            f"Sales agent has not run in {age_min} min "
            "(expected every 30 min)."
        ),
        "lastRunAt": last.isoformat(),
    }


# -------------------------------------------------------------------- config
class ConfigUpdate(BaseModel):
    model: Optional[str] = Field(None, max_length=200)


@router.get("/config")
def get_config(_admin: AdminUser) -> dict[str, Any]:
    admin_id = resolve_admin_user_id()
    if admin_id is None:
        raise HTTPException(
            status_code=409,
            detail="No admin user matches AETHER_ADMIN_EMAIL.",
        )
    ensure_agent_config(admin_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "model","enabled" FROM "AgentConfig" '
                'WHERE "userId" = %s AND "agentKey" = %s',
                (admin_id, AGENT_KEY),
            )
            row = cur.fetchone()
    model, source = resolve_model()
    return {
        "configuredModel": row[0] if row else None,
        "resolvedModel": model,
        "resolvedModelSource": source,
        "enabled": sales_agent_enabled(),
        "dryRun": sales_agent_dry_run(),
        "knownAnthropicModels": [
            e["id"] for e in _STATIC_MODEL_CATALOG.get("anthropic", [])
        ],
    }


@router.put("/config")
def put_config(payload: ConfigUpdate, _admin: AdminUser) -> dict[str, Any]:
    """Set (or clear with null) the model override in AgentConfig. The model
    id is free-form on purpose — the catalog evolves; routing is dynamic."""
    admin_id = resolve_admin_user_id()
    if admin_id is None:
        raise HTTPException(
            status_code=409,
            detail="No admin user matches AETHER_ADMIN_EMAIL.",
        )
    ensure_agent_config(admin_id)
    model = (payload.model or "").strip() or None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "AgentConfig" SET "model" = %s, "updatedAt" = NOW() '
                'WHERE "userId" = %s AND "agentKey" = %s',
                (model, admin_id, AGENT_KEY),
            )
        conn.commit()
    resolved, source = resolve_model()
    return {
        "configuredModel": model,
        "resolvedModel": resolved,
        "resolvedModelSource": source,
    }


# --------------------------------------------------------- sending accounts
class SendingAccountUpdate(BaseModel):
    enabled: bool


@router.get("/sending-accounts")
def sending_accounts(_admin: AdminUser) -> dict[str, Any]:
    """The admin's connected Gmail accounts (public shape, NO tokens) with
    the ``usedForSalesAgent`` flag."""
    admin_id = resolve_admin_user_id()
    if admin_id is None:
        return {"accounts": [], "detail": "No admin user matches AETHER_ADMIN_EMAIL."}
    return {"accounts": _repo().list_gmail_accounts_public(admin_id)}


@router.post("/sending-accounts/{account_id}")
def set_sending_account(
    account_id: str, payload: SendingAccountUpdate, _admin: AdminUser
) -> dict[str, Any]:
    admin_id = resolve_admin_user_id()
    if admin_id is None:
        raise HTTPException(
            status_code=409,
            detail="No admin user matches AETHER_ADMIN_EMAIL.",
        )
    updated = _repo().set_sales_sending_account(
        admin_id, account_id, payload.enabled
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Gmail account not found.")
    return {"accountId": account_id, "usedForSalesAgent": payload.enabled}
