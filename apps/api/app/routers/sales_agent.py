"""Sales Agent admin router — mounted at ``/admin/sales-agent`` (public
contract ``/api/admin/sales-agent/*``).

EVERY route depends on ``AdminUser``: anonymous → 401, non-admin → 403 —
the whole surface is admin-only (build brief §4.4: the sales agent must not
appear on any user-facing dashboard; its visibility lives entirely under
``/admin``).

Honesty contract: every number returned here is a live database query
(:meth:`SalesRepository.overview` et al). ``replyRate`` is ``null`` — not
``0`` — when no real send exists. Once a send exists it is replied threads
over sent threads, written only by the inbound reply observer.
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


# ----------------------------------------------------------------- strategy
@router.get("/strategy")
def strategy(_admin: AdminUser) -> dict[str, Any]:
    """Read-only handoff for the founder and the orchestrator.

    This is not a second marketing agent. It reports live Sales AI facts and
    the next human actions. First-touch landings are accounts whose signup
    URL carried ``utm_source=aether_sales_agent``. That is a landing count,
    not a proven causal conversion.
    """
    from app.repositories.admin_metrics import sales_ai_cost_usd_30d
    from app.services.stripe_gateway import app_base_url

    repo = _repo()
    repo.seed_default_campaigns()
    ov = repo.overview()
    campaigns = repo.list_campaigns()
    active = [c for c in campaigns if c.get("active")]
    inactive = [c for c in campaigns if not c.get("active")]
    generated = [
        c["name"]
        for c in inactive
        if "(agent-generated)" in str(c.get("name") or "")
    ]
    h = health(_admin)
    next_actions: list[str] = []
    if h.get("status") == "error":
        next_actions.append(
            "The sales scheduler is not healthy. Read the health detail "
            "before treating outbound as running."
        )
    if h.get("status") == "stale":
        next_actions.append(
            "The sales scheduler is stale. Production expects an ARQ cron "
            "tick every 30 minutes on aether-prod-worker. Live mode does not "
            "mean the agent is working until lastRunAt is fresh."
        )
    if h.get("dryRun"):
        next_actions.append(
            "Outbound is in shadow mode. Keep it there until every live "
            "template uses the current product URL."
        )
    else:
        next_actions.append(
            "Outbound is live. Treat replyRate as observed replies on mailed "
            "threads, not as a conversion rate."
        )
    if generated:
        next_actions.append(
            "Generated campaigns start inactive. Read the copy, then activate "
            "only the ones a human stands behind."
        )
    if int(ov.get("emailsSent") or 0) == 0:
        next_actions.append(
            "No real sends yet, so replyRate stays not measured."
        )
    next_actions.append(
        "Sales AI first-touch landings are accounts whose signup URL carried "
        "utm_source=aether_sales_agent. Treat attributedPaid as a landing "
        "count, not a proven causal conversion."
    )
    next_actions.append(
        "Keep AETHERAGENT20 inactive until a human chooses to run that "
        "one-time 20 percent offer."
    )
    return {
        "productUrl": app_base_url(),
        "enabled": bool(h.get("enabled")),
        "dryRun": bool(h.get("dryRun")),
        "lastRunAt": h.get("lastRunAt"),
        "healthStatus": h.get("status"),
        "healthDetail": h.get("detail"),
        "emailsSent": ov["emailsSent"],
        "dryRunLogged": ov["dryRunLogged"],
        "repliesObserved": ov["repliesObserved"],
        "replyRate": ov["replyRate"],
        "leads": ov["leads"],
        "campaignsActive": len(active),
        "campaignsInactive": len(inactive),
        "inactiveGeneratedNames": generated,
        "linkedinDraftsQueued": ov["linkedinDraftsQueued"],
        "suppressionCount": ov["suppressionCount"],
        "attributedSignups": int(ov.get("attributedSignups") or 0),
        "attributedPaid": int(ov.get("attributedPaid") or 0),
        "llmCostUsd30d": sales_ai_cost_usd_30d(),
        "cannotAttribute": False,
        "cannotAttributeReason": (
            "First-touch count of accounts whose signup URL carried "
            "utm_source=aether_sales_agent. That is a landing, not a proven "
            "causal conversion."
        ),
        "nextActions": next_actions,
    }


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
def create_campaign(payload: CampaignCreate, admin: AdminUser) -> dict[str, Any]:
    if payload.type not in CAMPAIGN_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"type must be one of {sorted(CAMPAIGN_TYPES)}",
        )
    row = _repo().create_campaign(
        name=payload.name, ctype=payload.type,
        template_body=payload.templateBody, active=payload.active,
    )
    # MP-020: every admin mutation leaves an AdminAuditLog row.
    from app.repositories.admin import write_audit

    write_audit(
        admin["id"],
        "sales_campaign.created",
        target_type="sales_campaign",
        target_id=row["id"],
        detail={"name": payload.name, "type": payload.type, "active": payload.active},
    )
    return row


@router.get("/campaigns/{campaign_id}/preview")
def campaign_preview(campaign_id: str, _admin: AdminUser) -> dict[str, Any]:
    """Brand-templated HTML preview of a campaign, rendered EXACTLY like a
    live send: ``{{name}}`` personalization (sample name), then the
    server-side compliance footer, then the branded wrapper. Read-only —
    nothing is sent or recorded."""
    from app.agents.sales_agent import (
        append_compliance_footer,
        personalize_template,
        rewrite_retired_product_urls,
    )
    from app.services.sales_branding import render_sales_outreach_html

    repo = _repo()
    repo.seed_default_campaigns()
    campaign = repo.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    body = append_compliance_footer(
        rewrite_retired_product_urls(
            personalize_template(campaign["templateBody"], "Alex")
        )
    )
    return {
        "campaignId": campaign["id"],
        "name": campaign["name"],
        "sampleName": "Alex",
        "html": render_sales_outreach_html(campaign["name"], body),
    }


@router.put("/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: str, payload: CampaignUpdate, admin: AdminUser
) -> dict[str, Any]:
    row = _repo().update_campaign(
        campaign_id,
        name=payload.name,
        template_body=payload.templateBody,
        active=payload.active,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    # MP-020: audit only the fields the admin actually changed (non-None).
    from app.repositories.admin import write_audit

    changed = {
        key: value
        for key, value in (
            ("name", payload.name),
            ("templateBody", payload.templateBody),
            ("active", payload.active),
        )
        if value is not None
    }
    write_audit(
        admin["id"],
        "sales_campaign.updated",
        target_type="sales_campaign",
        target_id=campaign_id,
        detail=changed,
    )
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
    repo = _repo()
    repo.seed_default_campaigns()
    rows, total = repo.list_outreach(
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
def run_now(admin: AdminUser) -> dict[str, Any]:
    """Trigger one full pipeline run synchronously (honest no-op when the
    feature flag is off; shadow mode logs ``dry_run`` rows, sends nothing)."""
    try:
        result = run_sales_agent(trigger="manual")
    except Exception as exc:  # noqa: BLE001 — surface the real reason, not a 500 page
        logger.exception("manual sales agent run failed")
        raise HTTPException(
            status_code=502, detail=f"Sales agent run failed: {exc}"
        ) from exc
    # MP-020: every admin mutation is audit-logged — manual pipeline triggers
    # are privileged actions with outbound-email side effects.
    from app.repositories.admin import write_audit

    write_audit(
        admin["id"],
        "sales_agent.run_now",
        target_type="sales_agent",
        detail={"ran": bool(result.get("ran"))},
    )
    return result


# ----------------------------------------------------------------- generate
@router.post("/generate")
def generate_content(admin: AdminUser) -> dict[str, Any]:
    """Ask the agent to author fresh marketing content NOW (synchronous):
    two new campaign templates (created INACTIVE, awaiting human activation)
    and three LinkedIn drafts — all real LLM output through the dynamically
    routed model, grounded only in verifiable product facts, recorded as a
    real AgentRun. LLM failure surfaces as an honest 502, never as
    hand-written copy pretending to be agent output."""
    from app.agents.sales_agent import generate_sales_marketing_content

    try:
        result = generate_sales_marketing_content(trigger="manual")
    except Exception as exc:  # noqa: BLE001 — surface the real reason
        logger.exception("sales agent content generation failed")
        raise HTTPException(
            status_code=502, detail=f"Content generation failed: {exc}"
        ) from exc
    # MP-020: audit-log manual content generation (admin mutation — creates
    # campaign templates and LinkedIn drafts).
    from app.repositories.admin import write_audit

    write_audit(
        admin["id"],
        "sales_marketing.generated",
        target_type="sales_agent",
        detail={
            "campaignsCreated": len(result.get("campaignsCreated") or []),
            "campaignsSkipped": len(result.get("campaignsSkipped") or []),
            "linkedinDrafts": int(result.get("linkedinDrafts") or 0),
            "promosCreated": len(result.get("promosCreated") or []),
            "errors": len(result.get("errors") or []),
        },
    )
    return result


# ------------------------------------------------ persistent brand editor
class BrandTemplateUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    footnote: str = Field(min_length=1, max_length=4000)
    footer: str = Field(min_length=1, max_length=4000)


class BrandArtifactCreate(BaseModel):
    """Human-authored copy only; rendering is deterministic and local."""

    title: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=400)
    cta: str = Field(min_length=1, max_length=120)


@router.get("/brand/templates")
def list_brand_templates(_admin: AdminUser) -> dict[str, Any]:
    from app.repositories.brand_templates import BrandTemplateRepository

    return {"templates": BrandTemplateRepository().list_templates()}


@router.put("/brand/templates/{kind}")
def update_brand_template(
    kind: str, payload: BrandTemplateUpdate, admin: AdminUser
) -> dict[str, Any]:
    """Persist only the auto-reply override and audit it atomically."""
    from app.repositories.admin import _ensure_admin_schema, write_audit
    from app.repositories.brand_templates import BrandTemplateRepository

    repo = BrandTemplateRepository()
    _ensure_admin_schema()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                row = repo.update(
                    kind,
                    body=payload.body,
                    footnote=payload.footnote,
                    footer=payload.footer,
                    cur=cur,
                )
                write_audit(
                    admin["id"],
                    "brand_template.updated",
                    target_type="brand_template",
                    target_id=kind,
                    detail={"kind": kind, "fields": ["body", "footnote", "footer"]},
                    cur=cur,
                )
            conn.commit()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown document kind.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return row


@router.post("/brand/artifacts", status_code=status.HTTP_201_CREATED)
def create_brand_artifact(
    payload: BrandArtifactCreate, admin: AdminUser
) -> Any:
    """Create or reuse an auditable, design-system-grounded SVG poster.

    This admin-only endpoint accepts supplied copy rather than an LLM prompt:
    it cannot fabricate performance claims and has no social-posting path.
    Identical normalized input returns its existing artifact (200), not a new
    creative.
    """
    from app.repositories.admin import _ensure_admin_schema, write_audit
    from app.services.brand_artifacts import ARTIFACT_KIND, build_poster

    try:
        artifact_input, digest, svg = build_poster(
            payload.title, payload.message, payload.cta
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repo = _repo()
    _ensure_admin_schema()
    row, reused = repo.get_or_create_brand_artifact(
        kind=ARTIFACT_KIND,
        input_hash=digest,
        artifact_input=artifact_input,
        content=svg,
        created_by_id=admin["id"],
    )
    if not reused:
        write_audit(
            admin["id"],
            "sales_brand_artifact.created",
            target_type="sales_brand_artifact",
            target_id=row["id"],
            detail={"kind": ARTIFACT_KIND, "inputHash": digest},
        )
    response = {
        "id": row["id"],
        "kind": row["kind"],
        "inputHash": row["inputHash"],
        "input": row["input"],
        "svg": row["content"],
        "createdAt": row["createdAt"],
        "reused": reused,
    }
    if reused:
        # FastAPI allows the endpoint's default 201 but dedupe is observable.
        from fastapi.encoders import jsonable_encoder
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_200_OK, content=jsonable_encoder(response)
        )
    return response


# ----------------------------------------------------------- brand documents
@router.get("/brand/documents")
def brand_documents(_admin: AdminUser) -> dict[str, Any]:
    """Registry of Brand-tab artefacts (emails, invoice, business card,
    documents) plus the live plan catalog they render against, and the
    static brand assets served by the web app."""
    from app.repositories.billing import PlanRepository
    from app.services.brand_documents import DOCUMENT_KINDS

    plans = PlanRepository().list_active()
    return {
        "documents": [
            {
                "kind": kind,
                "title": meta["title"],
                "description": meta["description"],
                "needsPlan": meta["needsPlan"],
                "allowsImg": bool(meta.get("allowsImg")),
            }
            for kind, meta in DOCUMENT_KINDS.items()
        ],
        "plans": [
            {
                "id": p["id"],
                "name": p["name"],
                "priceAudMonthly": float(p["priceAudMonthly"] or 0),
                "priceAudAnnual": float(p["priceAudAnnual"] or 0),
            }
            for p in plans
        ],
        "assets": [
            {"name": "aether-mark.png", "path": "/brand/aether-mark.png",
             "description": "Primary Aether brand mark (design-system PNG, "
                            "used in branded emails)."},
            {"name": "aether-mark-512.png", "path": "/brand/aether-mark-512.png",
             "description": "High-resolution 512px brand mark."},
            {"name": "aether-mark.svg", "path": "/brand/aether-mark.svg",
             "description": "Gold-gradient monogram mark on black."},
            {"name": "aether-wordmark.svg", "path": "/brand/aether-wordmark.svg",
             "description": "Horizontal wordmark lockup."},
            {"name": "aether-icon.svg", "path": "/brand/aether-icon.svg",
             "description": "Square app icon / favicon source."},
        ],
    }


@router.get("/brand/documents/{kind}/preview")
def brand_document_preview(
    kind: str,
    _admin: AdminUser,
    plan: str = Query("starter"),
    interval: str = Query("monthly"),
) -> dict[str, Any]:
    """Branded HTML preview of an admin document template. Plan-backed kinds
    render against the LIVE Plan catalog row (real prices + gst_breakdown);
    customer fields render as explicit merge fields — nothing is fabricated."""
    from app.repositories.billing import PlanRepository
    from app.repositories.brand_templates import BrandTemplateRepository
    from app.services.brand_documents import DOCUMENT_KINDS, render_document

    if kind not in DOCUMENT_KINDS:
        raise HTTPException(status_code=404, detail="Unknown document kind.")
    if interval not in ("monthly", "annual"):
        raise HTTPException(
            status_code=422, detail="interval must be 'monthly' or 'annual'."
        )
    plan_row = None
    if DOCUMENT_KINDS[kind]["needsPlan"]:
        plan_row = PlanRepository().get(plan)
        if plan_row is None:
            raise HTTPException(status_code=404, detail="Unknown plan id.")
    return {
        "kind": kind,
        "title": DOCUMENT_KINDS[kind]["title"],
        "planId": plan_row["id"] if plan_row else None,
        "interval": interval if plan_row else None,
        "html": render_document(
            kind,
            plan_row,
            interval,
            editable_template=BrandTemplateRepository().get_stored(kind),
        ),
    }


def _arq_sales_cron_registered() -> bool:
    try:
        from app.workers.sales_cron import sales_agent_cron
        from app.workers.settings import WorkerSettings

        jobs = getattr(WorkerSettings, "cron_jobs", None) or []
        return any(
            getattr(job, "coroutine", None) is sales_agent_cron for job in jobs
        )
    except Exception:  # noqa: BLE001 — absence of the scheduler is the signal
        return False


def _systemd_sales_timer_active() -> bool:
    try:
        import subprocess

        completed = subprocess.run(
            ["systemctl", "is-active", "aether-sales-agent.timer"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return completed.stdout.strip() == "active"
    except Exception:  # noqa: BLE001 — no systemctl means the unit is not active
        return False


# -------------------------------------------------------------------- health
@router.get("/health")
def health(_admin: AdminUser) -> dict[str, Any]:
    """Scheduler health: mechanism on this VPS first, then the run ledger.

    Hostinger production schedules this agent as an ARQ cron on
    ``aether-prod-worker`` (minutes 15 and 45). The Abacus systemd timer must
    not be enabled alongside ARQ. A fresh AgentRun row is not enough if the
    scheduler itself is missing.
    """
    from datetime import datetime, timezone

    repo = _repo()
    admin_id = resolve_admin_user_id()
    enabled = sales_agent_enabled()
    dry_run = sales_agent_dry_run()
    sending_accounts = (
        len(repo.sales_sending_accounts(admin_id)) if admin_id else 0
    )
    scheduler_registered = _arq_sales_cron_registered()
    systemd_timer_active = _systemd_sales_timer_active()
    base: dict[str, Any] = {
        "enabled": enabled,
        "dryRun": dry_run,
        "sendingAccounts": sending_accounts,
        "intervalMinutes": 30,
        "staleAfterMinutes": _HEALTH_STALE_MINUTES,
        "schedulerKind": "arq_cron",
        "schedulerRegistered": scheduler_registered,
        "systemdTimerActive": systemd_timer_active,
    }
    last = None
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
        if not scheduler_registered:
            return {
                **base,
                "status": "error",
                "detail": (
                    "sales_agent_cron is not registered on WorkerSettings. "
                    "Hostinger schedules Sales AI via ARQ on aether-prod-worker."
                ),
                "lastRunAt": None,
            }
        return {**base, "status": "error",
                "detail": "Could not read the sales agent run ledger.",
                "lastRunAt": None}
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    last_iso = last.isoformat() if last is not None else None

    if not scheduler_registered:
        detail = (
            "sales_agent_cron is not registered on WorkerSettings. "
            "Hostinger schedules Sales AI via ARQ cron on aether-prod-worker."
        )
        if systemd_timer_active:
            detail += (
                " aether-sales-agent.timer is also active; disable it."
            )
        return {
            **base,
            "status": "error",
            "detail": detail,
            "lastRunAt": last_iso,
        }
    if systemd_timer_active:
        return {
            **base,
            "status": "error",
            "detail": (
                "Both ARQ sales_agent_cron and aether-sales-agent.timer are "
                "active. Disable the systemd timer on this VPS to prevent "
                "double-sends."
            ),
            "lastRunAt": last_iso,
        }
    if last is None:
        return {
            **base,
            "status": "not_configured" if enabled else "disabled",
            "detail": "No sales agent runs recorded yet.",
            "lastRunAt": None,
        }
    age_min = int((datetime.now(timezone.utc) - last).total_seconds() // 60)
    if age_min <= _HEALTH_STALE_MINUTES:
        return {
            **base,
            "status": "ok",
            "detail": f"Last run {age_min} min ago (ARQ cron fires every 30 min).",
            "lastRunAt": last_iso,
        }
    return {
        **base,
        "status": "stale",
        "detail": (
            f"Sales agent has not run in {age_min} min "
            "(expected every 30 min via ARQ cron on aether-prod-worker)."
        ),
        "lastRunAt": last_iso,
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
def put_config(payload: ConfigUpdate, admin: AdminUser) -> dict[str, Any]:
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
    # MP-020: audit-log config mutation (model override change).
    from app.repositories.admin import write_audit

    write_audit(
        admin["id"],
        "sales_agent_config.updated",
        target_type="agent_config",
        detail={"model": model},
    )
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
    account_id: str, payload: SendingAccountUpdate, admin: AdminUser
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
    # MP-020: audit-log sending-account toggle (success only — a 404 above
    # mutates nothing and therefore writes no audit row).
    from app.repositories.admin import write_audit

    write_audit(
        admin["id"],
        "sales_sending_account.updated",
        target_type="gmail_account",
        target_id=account_id,
        detail={"enabled": payload.enabled},
    )
    return {"accountId": account_id, "usedForSalesAgent": payload.enabled}
