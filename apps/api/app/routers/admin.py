"""Admin router — Admin Tier 1 (§15) + security (GAP-P6-ADMIN-001/003, SEC-001).

Mounted at prefix ``/admin`` in ``app.main``; the platform ingress maps external
``/api/*`` onto the API service, so the public contract is ``/api/admin/...``.
EVERY route depends on ``AdminUser`` — a non-admin gets 403, an anonymous caller
gets 401 (the ``get_current_user`` chain runs first). Every MUTATION appends an
immutable ``AdminAuditLog`` row (actor, action, target, detail, ip) — no admin
action is silent, and the audit log is append-only (no delete/edit routes).

The ADMIN-FULL account-management routes go one step further: the mutation and
its audit row share ONE cursor in ONE transaction (the pattern
``billing.perform_admin_cancel`` / ``perform_admin_refund`` established), so a
failure between them — pool exhaustion, a transient DB blip, a worker restart —
rolls BOTH back. "Audited" is therefore not best-effort: a durable admin
mutation with no audit row is not a state this router can reach.

All spend figures are USD (LLM providers bill USD; §14.8) — never AUD.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, StrictBool, ValidationError

from app.db import ensure_password_reset_columns, get_connection
from app.middleware.auth import AdminUser
from app.repositories import admin as admin_repo
from app.repositories.user import UserRepository, validate_password_policy
from app.security import hash_password
from app.services import entitlements

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
# User management (ADMIN-FULL) — entitlement, credentials, Stripe-linked actions
#
# USER MANDATE (2026-08-14): "admin users can change plans, subscriptions,
# username/password of ANY user". Every route below is ``AdminUser``-gated and
# every mutation appends an ``AdminAuditLog`` row with actor, target, action and
# before->after for NON-SECRET fields. A password change logs the EVENT and never
# any value — audit is universal, secrets are not audit material.
#
# BILLING INVARIANTS (sacred): a plan change here is an in-app ENTITLEMENT
# override (immediate, Stripe-independent, and VISIBLY an override in this
# response + the audit row). Where a real Stripe subscription exists, cancel and
# refund route through the EXISTING billing service paths — this router never
# hand-mutates billing state, so no-double-billing / refund-revoke / dunning
# grace stay exactly as they were.
# --------------------------------------------------------------------------- #


async def _parse_json_object(request: Request) -> dict[str, Any]:
    """Decode a JSON object body AFTER ``AdminUser`` has resolved.

    Same body-before-auth hazard (and the same fix) as ``_parse_settings_body``:
    a Pydantic body parameter would make FastAPI decode the body BEFORE
    dependencies, so an anonymous caller could see a 422 instead of a 401.
    """
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001 — malformed / non-JSON / empty body
        return {}
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Request body must be an object."
        )
    return raw


def _require_user(user_id: str) -> None:
    if not admin_repo.user_exists(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")


@router.post("/users/{user_id}/entitlement")
async def admin_set_entitlement(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """Grant / replace / clear a user's in-app entitlement override.

    Body ``{"kind": "comp"|"tier"|"unlimited"|"none", "planId"?, "note"?}``.
    ``none`` clears the override. ``comp``/``tier`` require a real plan id and
    apply that plan's ceiling to ``UsageQuota`` IMMEDIATELY — while leaving the
    ``Subscription`` row (the Stripe truth) untouched, so a paying customer's
    billing record is never silently contradicted.

    ATOMIC WITH ITS AUDIT ROW: the override write, the post-write ``resolve``
    that produces the audit ``after``, and the ``AdminAuditLog`` insert all run
    on ONE cursor in ONE transaction (the pattern ``perform_admin_cancel`` /
    ``perform_admin_refund`` already use). A failure anywhere in that window
    rolls the whole thing back, so there is no such thing as a durable,
    unaudited entitlement change.
    """
    body = await _parse_json_object(request)
    _require_user(user_id)
    kind = str(body.get("kind") or "").strip().lower()
    clearing = kind in ("none", "clear", "")
    plan_id = body.get("planId")
    note = body.get("note")

    # Every lazy-DDL / row-seed side effect happens OUTSIDE the transaction:
    # inside it, the cur paths issue no DDL and open no second connection.
    entitlements.prepare_override_write(user_id)
    admin_repo._ensure_admin_schema()

    with get_connection() as conn:
        with conn.cursor() as cur:
            # ``before`` is read on the SAME cursor as the write, so the audit
            # pair cannot straddle someone else's concurrent change.
            before = entitlements.resolve(user_id, cur=cur).as_dict()
            if clearing:
                entitlements.clear_override(user_id, cur=cur)
            else:
                try:
                    entitlements.set_override(
                        user_id,
                        kind=kind,
                        plan_id=str(plan_id) if plan_id else None,
                        note=str(note) if note else None,
                        actor_id=admin["id"],
                        cur=cur,
                    )
                except ValueError as exc:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
                    ) from exc
            after = entitlements.resolve(user_id, cur=cur).as_dict()
            admin_repo.write_audit(
                admin["id"],
                "clear_entitlement_override"
                if clearing
                else "set_entitlement_override",
                target_type="user",
                target_id=user_id,
                detail={"before": before, "after": after},
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()
    return {"userId": user_id, "entitlement": after}


@router.post("/users/{user_id}/password")
async def admin_set_password(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """Set a user's password on their behalf.

    The value is validated against the SAME policy self-service registration
    uses, hashed with the SAME hasher (``app.security.hash_password``), and
    written through ``UserRepository.set_password`` — which stamps
    ``passwordChangedAt`` and therefore invalidates every session token minted
    before this moment (O-4). The plaintext is never logged, never echoed back,
    and never written to the audit row: the audit records that the event
    happened, not what it was.

    ATOMIC WITH ITS AUDIT ROW: the hash write and the ``AdminAuditLog`` insert
    share one cursor in one transaction. Before this, a failure between them
    (pool exhaustion, a DB blip, a worker restart) left the target locked out of
    every existing session by a password change nothing recorded.
    """
    body = await _parse_json_object(request)
    _require_user(user_id)
    new_password = body.get("newPassword")
    if not isinstance(new_password, str) or not new_password:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "newPassword is required."
        )
    problems = validate_password_policy(new_password)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "; ".join(problems))

    # Lazy DDL first, outside the transaction (see admin_set_entitlement).
    ensure_password_reset_columns()
    admin_repo._ensure_admin_schema()
    password_hash = hash_password(new_password)
    with get_connection() as conn:
        with conn.cursor() as cur:
            UserRepository().set_password(user_id, password_hash, cur=cur)
            admin_repo.write_audit(
                admin["id"],
                "set_user_password",
                target_type="user",
                target_id=user_id,
                # NEVER the value — not the password, not the hash, not a prefix.
                detail={"sessionsInvalidated": True},
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()
    return {"userId": user_id, "passwordChanged": True, "sessionsInvalidated": True}


@router.post("/users/{user_id}/identity")
async def admin_update_identity(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """Change a user's email / username / display name.

    Both login identities are UNIQUE, so a collision is an honest 409 rather than
    a silently-ignored write. The audit row carries the full before->after pair.

    ATOMIC WITH ITS AUDIT ROW: the identity write and the ``AdminAuditLog``
    insert share one cursor in one transaction, so a caller can never end up
    logging in under an email nothing recorded the change of.
    """
    body = await _parse_json_object(request)
    _require_user(user_id)
    email = body.get("email")
    username = body.get("username")
    name = body.get("name")
    if email is None and username is None and name is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Provide at least one of email, username or name.",
        )
    if email is not None:
        email = str(email).strip()
        if "@" not in email or " " in email or len(email) < 3:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "email is not a valid address."
            )
    if username is not None:
        username = str(username).strip()
    if name is not None:
        name = str(name).strip()

    admin_repo._ensure_admin_schema()  # lazy DDL first, outside the transaction
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                before, after = admin_repo.update_user_identity(
                    user_id, email=email, username=username, name=name, cur=cur
                )
            except admin_repo.IdentityConflictError as exc:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, f"That {exc} is already taken."
                ) from exc
            except LookupError as exc:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, "User not found"
                ) from exc

            admin_repo.write_audit(
                admin["id"],
                "update_user_identity",
                target_type="user",
                target_id=user_id,
                detail={"before": before, "after": after},
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()
    return {"userId": user_id, "before": before, "after": after}


@router.post("/users/{user_id}/subscription/cancel")
async def admin_cancel_subscription(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """Cancel a user's REAL Stripe subscription through the billing service.

    Body ``{"atPeriodEnd": true}`` (default) schedules cancellation at the end of
    the paid period; ``false`` revokes immediately via the shared
    ``_revoke_to_free`` handler. A user with no Stripe subscription gets an
    honest 409 — the lever for that case is an entitlement override.
    """
    body = await _parse_json_object(request)
    _require_user(user_id)
    from app.routers.billing import perform_admin_cancel

    at_period_end = body.get("atPeriodEnd", True)
    if not isinstance(at_period_end, bool):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "atPeriodEnd must be a boolean."
        )
    return perform_admin_cancel(
        actor_user_id=admin["id"],
        target_user_id=user_id,
        at_period_end=at_period_end,
        ip=_client_ip(request),
    )


@router.post("/users/{user_id}/subscription/refund")
async def admin_refund_subscription(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """Refund this user's latest paid charge via the EXISTING admin-refund path
    (``billing.perform_admin_refund``) — same gateway calls, same
    ``_revoke_to_free``, same audit action as ``POST /billing/admin/refund``."""
    await _parse_json_object(request)
    _require_user(user_id)
    from app.routers.billing import perform_admin_refund

    return perform_admin_refund(
        actor_user_id=admin["id"], target_user_id=user_id, ip=_client_ip(request)
    )


@router.get("/users/{user_id}/audit")
def admin_user_audit(
    _admin: AdminUser,
    user_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """The append-only audit trail for ONE user (newest first)."""
    return admin_repo.list_audit(
        limit=limit, offset=offset, target_type="user", target_id=user_id
    )


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
    # INC-B-002 / FE-D-002(b): pydantic's default LAX bool coercion silently
    # accepts a materially wider set of non-boolean JSON values than the
    # JSON boolean literals ``true``/``false`` -- bare ints ``1``/``0`` and
    # the strings "yes"/"no"/"on"/"off"/"TRUE" -- and this endpoint was
    # PERSISTING that coerced value (200, not 422). ``StrictBool`` requires
    # the input to already be a genuine JSON boolean; a clearly-malformed
    # value (e.g. the string "banana", a bare int like 123, an array, an
    # object) still 422s exactly as before via pydantic's own
    # ``bool_parsing``/``bool_type`` errors -- this only narrows what
    # COUNTED as "close enough" to true/false.
    emailVerificationEnabled: Optional[StrictBool] = None


async def _parse_settings_body(request: Request) -> SettingsRequest:
    """Decode + validate the settings body, raising the same honest 422 FastAPI
    would — but only AFTER the auth dependency has resolved (MV-admin-settings-002).

    Declaring a Pydantic body parameter makes FastAPI decode the request body
    BEFORE dependencies for syntactically-broken JSON, so an anonymous caller
    could receive a 422 instead of a 401. Reading the body here, inside the
    handler, keeps every /admin/* request auth-gated first for EVERY body shape.
    """
    try:
        raw = await request.json()
    except Exception as exc:  # noqa: BLE001 — malformed / non-JSON body
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Request body is not valid JSON."
        ) from exc
    try:
        return SettingsRequest.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, jsonable_encoder(exc.errors())
        ) from exc


@router.get("/settings")
def admin_get_settings(_admin: AdminUser) -> dict[str, Any]:
    return admin_repo.get_settings()


@router.post("/settings")
async def admin_update_settings(
    admin: AdminUser, request: Request
) -> dict[str, Any]:
    body = await _parse_settings_body(request)
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
