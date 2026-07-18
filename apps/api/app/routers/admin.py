"""Admin router — Admin Tier 1 (§15) + security (GAP-P6-ADMIN-001/003, SEC-001).

Mounted at prefix ``/admin`` in ``app.main``; the platform ingress maps external
``/api/*`` onto the API service, so the public contract is ``/api/admin/...``.
EVERY route depends on ``AdminUser`` — a non-admin gets 403, an anonymous caller
gets 401 (the ``get_current_user`` chain runs first). Every MUTATION appends an
immutable ``AdminAuditLog`` row (actor, action, target, detail, ip) — no admin
action is silent, and the audit log is append-only (no delete/edit routes).

All spend figures are USD (LLM providers bill USD; §14.8) — never AUD.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, ValidationError

from app.middleware.auth import AdminUser
from app.repositories import admin as admin_repo

router = APIRouter()


def _client_ip(request: Request) -> Optional[str]:
    """Best-effort caller IP. Behind Envoy->nginx the socket peer is nginx, so
    prefer the forwarded chain's first hop when present."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip() or None
    return request.client.host if request.client else None


# --------------------------------------------------------------------------- #
# Health overview
# --------------------------------------------------------------------------- #


@router.get("/health")
def admin_health(_admin: AdminUser) -> dict[str, Any]:
    """Service / agent-success-rate / cron / provider status overview."""
    return admin_repo.health_overview()


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #


@router.get("/users")
def admin_list_users(
    _admin: AdminUser,
    q: Optional[str] = Query(default=None),
    plan: Optional[str] = Query(default=None),
    suspended: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List users with plan, signup date, last login and LLM spend (USD)."""
    return admin_repo.list_users(
        query=q, plan=plan, suspended=suspended, limit=limit, offset=offset
    )


@router.get("/users/{user_id}")
def admin_user_detail(_admin: AdminUser, user_id: str) -> dict[str, Any]:
    """User detail: activity, subscription, quota, recent runs, spend (USD)."""
    detail = admin_repo.get_user_detail(user_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return detail


class SpendCapRequest(BaseModel):
    spendCapUsd: float = Field(ge=0)


async def _parse_spend_cap_body(request: Request) -> SpendCapRequest:
    """Decode + validate the spend-cap body AFTER the auth dependency has
    resolved (MV-admin-settings-003 — the identical body-before-auth hazard
    and fix as MV-admin-settings-002's ``_parse_settings_body``).

    Declaring a Pydantic body parameter makes FastAPI decode the request body
    BEFORE dependencies for syntactically-broken JSON, so an anonymous caller
    could receive a 422 instead of a 401. Reading the body here, inside the
    handler (after ``AdminUser`` already resolved), keeps this route
    auth-gated first for EVERY body shape.
    """
    try:
        raw = await request.json()
    except Exception as exc:  # noqa: BLE001 — malformed / non-JSON body
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Request body is not valid JSON."
        ) from exc
    try:
        return SpendCapRequest.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, jsonable_encoder(exc.errors())
        ) from exc


@router.post("/users/{user_id}/spend-cap")
async def admin_set_spend_cap(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """Set the per-user USD spend cap (flows into the metered-run reserve)."""
    body = await _parse_spend_cap_body(request)
    if not admin_repo.user_exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    cap = admin_repo.set_spend_cap(user_id, body.spendCapUsd)
    admin_repo.write_audit(
        admin["id"],
        "set_spend_cap",
        target_type="user",
        target_id=user_id,
        detail={"spendCapUsd": cap},
        ip=_client_ip(request),
    )
    return {"userId": user_id, "spendCapUsd": cap, "currency": "USD"}


@router.post("/users/{user_id}/suspend")
def admin_suspend_user(admin: AdminUser, user_id: str, request: Request) -> dict[str, Any]:
    """Suspend a user (403 on their authenticated routes until unsuspended)."""
    if not admin_repo.user_exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    suspended = admin_repo.set_suspended(user_id, True)
    admin_repo.write_audit(
        admin["id"],
        "suspend_user",
        target_type="user",
        target_id=user_id,
        detail={"suspended": suspended},
        ip=_client_ip(request),
    )
    return {"userId": user_id, "suspended": suspended}


@router.post("/users/{user_id}/unsuspend")
def admin_unsuspend_user(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """Lift a suspension."""
    if not admin_repo.user_exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    suspended = admin_repo.set_suspended(user_id, False)
    admin_repo.write_audit(
        admin["id"],
        "unsuspend_user",
        target_type="user",
        target_id=user_id,
        detail={"suspended": suspended},
        ip=_client_ip(request),
    )
    return {"userId": user_id, "suspended": suspended}


# --------------------------------------------------------------------------- #
# Spend
# --------------------------------------------------------------------------- #


@router.get("/spend")
def admin_spend(_admin: AdminUser) -> dict[str, Any]:
    """Total + per-user LLM spend (USD, SUM of AgentRun.costUsd)."""
    return admin_repo.spend_overview()


# --------------------------------------------------------------------------- #
# Settings (signup toggle + email-verification placeholder)
# --------------------------------------------------------------------------- #


class SettingsRequest(BaseModel):
    signupEnabled: Optional[bool] = None
    emailVerificationEnabled: Optional[bool] = None


@router.get("/settings")
def admin_get_settings(_admin: AdminUser) -> dict[str, Any]:
    return admin_repo.get_settings()


@router.post("/settings")
def admin_update_settings(
    admin: AdminUser, body: SettingsRequest, request: Request
) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    if body.signupEnabled is not None:
        admin_repo.set_setting(admin_repo.SIGNUP_ENABLED_KEY, bool(body.signupEnabled))
        changed["signupEnabled"] = bool(body.signupEnabled)
    if body.emailVerificationEnabled is not None:
        admin_repo.set_setting(
            admin_repo.EMAIL_VERIFICATION_KEY, bool(body.emailVerificationEnabled)
        )
        changed["emailVerificationEnabled"] = bool(body.emailVerificationEnabled)
    admin_repo.write_audit(
        admin["id"],
        "update_settings",
        target_type="settings",
        target_id="global",
        detail=changed,
        ip=_client_ip(request),
    )
    return admin_repo.get_settings()


# --------------------------------------------------------------------------- #
# Audit log (append-only)
# --------------------------------------------------------------------------- #


@router.get("/audit-log")
def admin_audit_log(
    _admin: AdminUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Paginated, append-only admin audit log (newest first)."""
    return admin_repo.list_audit(limit=limit, offset=offset)
