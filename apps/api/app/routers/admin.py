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

import asyncio
import logging
import math
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, StrictBool, ValidationError

from app.db import (
    ensure_password_reset_columns,
    ensure_user_lifecycle_columns,
    get_connection,
)
from app.middleware.auth import (
    AdminUser,
    session_invalidation_boundary,
    stamp_invalidates_tokens_minted_before,
)
from app.redaction import redact_validation_errors
from app.repositories import admin as admin_repo
from app.repositories import admin_billing as admin_billing_repo
from app.repositories import admin_metrics as admin_metrics_repo
from app.repositories import sales_agents as sales_agents_repo
from app.repositories.billing import (
    PlanRepository,
    _ensure_billing_tables,
    ensure_user_billing,
)
from app.repositories.user import UserRepository, validate_password_policy
from app.security import hash_password
from app.services import entitlements, stripe_gateway

router = APIRouter()

logger = logging.getLogger(__name__)


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
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            # SEC-422: same redaction the app-wide RequestValidationError
            # handler applies — these hand-rolled echoes bypass it because
            # the body is parsed inside the handler (auth-before-body), so
            # they must call the shared sanitizer themselves.
            jsonable_encoder(redact_validation_errors(exc.errors())),
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
    """Suspend a user (403 on their authenticated routes until unsuspended).

    ADMIN-2.0 PROTECTED ACCOUNTS: an admin account and the §14.7 owner identity
    are REFUSED here, server-side. Suspension 403s every authenticated route,
    /admin/* included, so suspending the last administrator (or the owner the
    environment re-creates on every boot) locks the operator out of the very
    surface that could undo it. Hiding the button is not a protection; this is.
    """
    target = admin_repo.account_guard_context(user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    protected = admin_repo.protected_account_reason(target)
    if protected:
        raise HTTPException(status.HTTP_409_CONFLICT, protected)
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
    ``passwordChangedAt`` (O-4). The plaintext is never logged, never echoed
    back, and never written to the audit row: the audit records that the event
    happened, not what it was.

    SESSION INVALIDATION IS EARNED, NOT ASSERTED. An admin reaches for this
    route to cut off a compromised or abusive session NOW, so the response may
    not simply claim it. A bare ``now()`` stamp does NOT invalidate a token
    minted earlier in the same whole second — ``iat`` is truncated to seconds
    and ``_IAT_GRACE_SECONDS`` forgives that much — and because the check
    compares two fixed timestamps, such a token then survives for the REST of
    its 24h TTL, not for one more second. So this route waits for
    ``session_invalidation_boundary`` (at most ~1.25s, mostly absorbed by
    bcrypt) before writing, then re-reads the stamp it actually wrote and
    reports ``sessionsInvalidated`` from
    ``stamp_invalidates_tokens_minted_before``. ``true`` therefore means "every
    token minted before ``sessionsInvalidatedBefore`` is already rejected", and
    a ``false`` (clock skew beyond the margin) is reported honestly rather than
    papered over. The grace window itself is untouched: a login AFTER the change
    is still never falsely 401'd.

    An identity whose password §14.7 owns (``AETHER_ADMIN_PASSWORD_HASH``) is
    REFUSED with 409 — ``apply_admin_rotation`` re-applies that hash on every
    boot, so accepting the change here would report success for a write the
    next restart silently reverts.

    ATOMIC WITH ITS AUDIT ROW: the hash write and the ``AdminAuditLog`` insert
    share one cursor in one transaction. Before this, a failure between them
    (pool exhaustion, a DB blip, a worker restart) left the target locked out of
    every existing session by a password change nothing recorded.
    """
    received_at = time.time()
    body = await _parse_json_object(request)
    _require_user(user_id)
    target = UserRepository().get_auth_context(user_id)
    if admin_repo.password_is_env_managed(target.get("email") if target else None):
        raise HTTPException(
            status.HTTP_409_CONFLICT, admin_repo.ENV_MANAGED_PASSWORD_MESSAGE
        )
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
    # ``set_password`` also writes ``mustChangePassword`` (ADMIN-2.0), so its
    # column must exist before the transaction opens — named explicitly here
    # rather than relying on ``_ensure_admin_schema`` happening to cover it.
    ensure_user_lifecycle_columns()
    admin_repo._ensure_admin_schema()
    password_hash = hash_password(new_password)

    # Clear the iat-truncation boundary BEFORE stamping, so the invalidation
    # this route reports is real (see the docstring). Bounded by construction:
    # the boundary is < 1.25s past the second the request arrived in, and the
    # bcrypt hash above has already spent part of it. ``asyncio.sleep`` keeps
    # the event loop free for other requests while it elapses.
    delay = session_invalidation_boundary(received_at) - time.time()
    if delay > 0:
        await asyncio.sleep(delay)

    with get_connection() as conn:
        with conn.cursor() as cur:
            UserRepository().set_password(user_id, password_hash, cur=cur)
            # Read back the stamp on the SAME cursor: what the response claims
            # is derived from what was actually written, never assumed.
            cur.execute(
                'SELECT "passwordChangedAt" FROM "User" WHERE "id"=%s', (user_id,)
            )
            row = cur.fetchone()
            sessions_invalidated = stamp_invalidates_tokens_minted_before(
                row[0] if row else None, received_at
            )
            admin_repo.write_audit(
                admin["id"],
                "set_user_password",
                target_type="user",
                target_id=user_id,
                # NEVER the value — not the password, not the hash, not a prefix.
                detail={"sessionsInvalidated": sessions_invalidated},
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()

    if not sessions_invalidated:
        # Honest, actionable, and value-free: the password DID change, but the
        # lockout the admin came for is not provable, so say so instead of
        # returning the optimistic default.
        logger.warning(
            "admin password change for userId=%s could not confirm session "
            "invalidation — the passwordChangedAt stamp did not clear the iat "
            "grace window, which points at clock skew between the API and the "
            "database. Existing sessions for this user may still be live.",
            user_id,
        )
    return {
        "userId": user_id,
        "passwordChanged": True,
        "sessionsInvalidated": sessions_invalidated,
        "sessionsInvalidatedBefore": (
            datetime.fromtimestamp(received_at, tz=timezone.utc).isoformat()
            if sessions_invalidated
            else None
        ),
    }


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
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            # SEC-422: same redaction the app-wide RequestValidationError
            # handler applies — these hand-rolled echoes bypass it because
            # the body is parsed inside the handler (auth-before-body), so
            # they must call the shared sanitizer themselves.
            jsonable_encoder(redact_validation_errors(exc.errors())),
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


# --------------------------------------------------------------------------- #
# ADMIN-2.0 — account lifecycle (create / soft-delete / restore)
#
# Every route below is ``AdminUser``-gated, parses its body AFTER auth (the
# body-before-auth hazard ``_parse_json_object`` exists for), and commits its
# mutation together with its ``AdminAuditLog`` row on ONE cursor in ONE
# transaction — the ADMIN-FULL discipline, unchanged.
# --------------------------------------------------------------------------- #

#: Temp-password alphabet. Ambiguous glyphs (0/O, 1/l/I) are omitted because a
#: human retypes this once from a screen; the symbol set is punctuation every
#: keyboard layout can produce.
_TEMP_PW_LOWER = "abcdefghijkmnopqrstuvwxyz"
_TEMP_PW_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_TEMP_PW_DIGITS = "23456789"
_TEMP_PW_SYMBOLS = "!@#$%^&*-_=+"
_TEMP_PW_ALPHABET = _TEMP_PW_LOWER + _TEMP_PW_UPPER + _TEMP_PW_DIGITS + _TEMP_PW_SYMBOLS


def _generate_temp_password(length: int = 20) -> str:
    """A cryptographically-random temporary password (``secrets``, never
    ``random``), guaranteed to satisfy ``validate_password_policy``.

    One character is drawn from each class first so the result cannot randomly
    lack the digit the policy requires, then the remainder is filled uniformly
    and the whole thing shuffled — so the guaranteed characters carry no
    positional information.
    """
    length = max(16, int(length))
    chars = [
        secrets.choice(_TEMP_PW_LOWER),
        secrets.choice(_TEMP_PW_UPPER),
        secrets.choice(_TEMP_PW_DIGITS),
        secrets.choice(_TEMP_PW_SYMBOLS),
    ]
    chars.extend(secrets.choice(_TEMP_PW_ALPHABET) for _ in range(length - len(chars)))
    # secrets.SystemRandom().shuffle uses the same CSPRNG as secrets.choice.
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _clean_email(raw: Any) -> str:
    """Validate + normalise an email argument, or raise the honest 422."""
    if not isinstance(raw, str):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "email must be a string."
        )
    email = raw.strip()
    if "@" not in email or " " in email or len(email) < 3:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "email is not a valid address."
        )
    return email


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def admin_create_user(admin: AdminUser, request: Request) -> dict[str, Any]:
    """Create an account on a user's behalf.

    Body ``{"email": ..., "name"?: ...}``. The response carries a generated
    temporary password EXACTLY ONCE — it is hashed with the same hasher
    registration uses, never stored in plaintext, never logged, and never
    written to the audit row (the audit records that an account was created and
    by whom; a credential is not audit material). There is no second endpoint
    that can read it back: if the admin loses it, the remedy is the existing
    ``POST /admin/users/{id}/password``.

    ``mustChangePassword`` is stamped ``true`` and is TRUTHFUL rather than
    decorative: ``UserRepository.set_password`` clears it the moment the account
    owner sets a password of their own, so the flag means "this account is still
    on the credential an admin generated" for exactly as long as that is true.
    (Enforcing a reset in the sign-in UI is the follow-up front-end slice; the
    backend records the state, and nothing here claims the redirect exists.)

    PRIVILEGE: an admin-created account is an ORDINARY account. ``isAdmin`` is
    not settable through this route at any cost — granting admin stays a
    separate, deliberate act, so a single compromised admin session cannot mint
    a persistent second operator in one call.
    """
    body = await _parse_json_object(request)
    email = _clean_email(body.get("email"))
    raw_name = body.get("name")
    if raw_name is not None and not isinstance(raw_name, str):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "name must be a string."
        )
    name = raw_name.strip() if isinstance(raw_name, str) else None

    temp_password = _generate_temp_password()
    problems = validate_password_policy(temp_password)
    if problems:  # pragma: no cover — generator is constructed to satisfy the policy
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to generate a compliant temporary password.",
        )
    password_hash = hash_password(temp_password)

    # Every lazy-DDL / schema side effect happens OUTSIDE the transaction.
    admin_repo._ensure_admin_schema()
    ensure_password_reset_columns()
    ensure_user_lifecycle_columns()
    _ensure_billing_tables()

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                created = admin_repo.create_user(
                    cur,
                    email=email,
                    name=name,
                    password_hash=password_hash,
                    must_change_password=True,
                )
            except admin_repo.DuplicateUserError as exc:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "That email is already registered."
                ) from exc
            # Free Subscription + UsageQuota in the SAME transaction, so a
            # created account can never exist without the billing rows every
            # admin/entitlement read expects.
            ensure_user_billing(created["id"], cur=cur)
            admin_repo.write_audit(
                admin["id"],
                "create_user",
                target_type="user",
                target_id=created["id"],
                # NEVER the password — not the value, not the hash, not a prefix.
                detail={
                    "email": email,
                    "name": name,
                    "mustChangePassword": True,
                    "isAdmin": False,
                },
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()

    return {
        "userId": created["id"],
        "email": created["email"],
        "name": created.get("name"),
        # Shown ONCE. Not retrievable afterwards, by anyone, through any route.
        "tempPassword": temp_password,
        "mustChangePassword": True,
        "createdAt": (
            created["createdAt"].isoformat() if created.get("createdAt") else None
        ),
    }


@router.delete("/users/{user_id}")
async def admin_delete_user(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """SOFT-delete an account (the scout's ratified strategy).

    Body ``{"confirmEmail": "<the target's email>"}`` — a typed confirmation,
    matched case-insensitively, so a mis-routed id cannot delete the wrong
    person. A mismatch is a 422 and writes nothing.

    WHY SOFT: every child table (Job, Resume, Application, AgentRun, Contact,
    EmailThread, StoryEntry) cascades from ``User.id``, so a hard delete would
    destroy the work the account produced and orphan the billing/audit history
    that still references it. The scout did NOT prove a safe cascade, so this
    route does not pretend one exists. ``deletedAt`` is stamped AND the account
    is suspended — suspension is the enforcement the auth dependency already
    honours on every authenticated route, so "deleted" means the account really
    cannot be used, not merely that a flag was set. ``POST .../restore`` reverses
    it.

    PROTECTED ACCOUNTS (server-side, not a hidden button): an admin account and
    the §14.7 owner identity are refused with an honest 409.
    """
    body = await _parse_json_object(request)
    admin_repo._ensure_admin_schema()
    ensure_user_lifecycle_columns()

    target = admin_repo.account_guard_context(user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    confirm = body.get("confirmEmail")
    if (
        not isinstance(confirm, str)
        or not confirm.strip()
        or confirm.strip().lower() != str(target.get("email") or "").strip().lower()
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "confirmEmail must match the target account's email address exactly.",
        )

    protected = admin_repo.protected_account_reason(target)
    if protected:
        raise HTTPException(status.HTTP_409_CONFLICT, protected)

    if target.get("deletedAt") is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This account is already deleted."
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                result = admin_repo.soft_delete_user(cur, user_id)
            except LookupError as exc:  # lost a race with a concurrent delete
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "This account is already deleted."
                ) from exc
            admin_repo.write_audit(
                admin["id"],
                "delete_user",
                target_type="user",
                target_id=user_id,
                detail={
                    "mode": "soft",
                    "email": target.get("email"),
                    "previousSuspended": bool(target.get("suspended")),
                    "deletedAt": result["deletedAt"].isoformat(),
                },
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()

    return {
        "userId": user_id,
        "deleted": True,
        "mode": "soft",
        "deletedAt": result["deletedAt"].isoformat(),
        "suspended": bool(result["suspended"]),
        "note": (
            "Soft delete: the account is suspended and hidden from normal use, "
            "and its jobs, applications, runs and audit history are preserved. "
            "Reversible with POST /admin/users/{id}/restore."
        ),
    }


@router.post("/users/{user_id}/restore")
async def admin_restore_user(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """Reverse a soft delete.

    Deliberately does NOT lift the suspension: restoring the record and handing
    the account its access back are two decisions, and silently un-suspending
    would also erase a suspension that predated the delete. The response reports
    the surviving ``suspended`` flag so the admin sees exactly what is still in
    force rather than assuming the account is live again.
    """
    await _parse_json_object(request)
    admin_repo._ensure_admin_schema()
    ensure_user_lifecycle_columns()

    target = admin_repo.account_guard_context(user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if target.get("deletedAt") is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This account is not deleted."
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                result = admin_repo.restore_user(cur, user_id)
            except LookupError as exc:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "This account is not deleted."
                ) from exc
            admin_repo.write_audit(
                admin["id"],
                "restore_user",
                target_type="user",
                target_id=user_id,
                detail={
                    "email": target.get("email"),
                    "suspended": bool(result["suspended"]),
                },
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()

    suspended = bool(result["suspended"])
    return {
        "userId": user_id,
        "deleted": False,
        "deletedAt": None,
        "suspended": suspended,
        "note": (
            "Restored. The account is still suspended — lift it deliberately "
            "with POST /admin/users/{id}/unsuspend."
            if suspended
            else "Restored."
        ),
    }


# --------------------------------------------------------------------------- #
# ADMIN-2.0 — custom per-user pricing
# --------------------------------------------------------------------------- #

#: Sanity ceiling for an admin-set subscription amount (AUD). Not a business
#: rule — a fat-finger guard, so a stray keystroke cannot bill a customer five
#: figures a month.
_MAX_CUSTOM_PRICE_AUD = 100_000.0


def _parse_amount_aud(raw: Any) -> float:
    """Validate an AUD amount, or raise the honest 422.

    ``bool`` is rejected explicitly: ``isinstance(True, int)`` is True in
    Python, so without this ``{"amountAud": true}`` would silently price a
    subscription at A$1.00.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "amountAud must be a number."
        )
    amount = round(float(raw), 2)
    if amount <= 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "amountAud must be greater than 0."
        )
    if amount > _MAX_CUSTOM_PRICE_AUD:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"amountAud must be at most {_MAX_CUSTOM_PRICE_AUD:.0f} AUD.",
        )
    return amount


def _parse_interval(raw: Any) -> str:
    if raw not in ("month", "year"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "interval must be either 'month' or 'year'.",
        )
    return str(raw)


def _require_stripe_configured() -> None:
    if not stripe_gateway.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Billing is not configured on this deployment yet",
        )


@router.post("/users/{user_id}/subscription/price")
async def admin_set_custom_price(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """Set a NEGOTIATED subscription amount for one customer.

    Body ``{"amountAud": <number>, "interval": "month"|"year"}``.

    NO-DOUBLE-BILLING (the invariant this route is written around): the
    customer's EXISTING Stripe subscription is repriced IN PLACE — a new
    ``Price`` object is created (a catalogue entry that charges nobody) and the
    subscription's single line item is pointed at it. A second subscription is
    never opened, which is precisely the failure PAY-R1-02 / PAY-R3-01 exist to
    prevent.

    NO SURPRISE CHARGE: the switch runs with ``proration_behavior="none"``, so
    Stripe writes no invoice items for the period already paid — nobody is
    charged, credited or refunded by this call. The negotiated amount simply
    takes effect at the next renewal, and the response says so rather than
    implying immediate effect.

    An account with no LIVE Stripe subscription is an honest 409: there is
    nothing to reprice, and the in-app lever for that case is an entitlement
    override (``POST /admin/users/{id}/entitlement``). No GST line is added —
    the operator is not GST-registered.
    """
    body = await _parse_json_object(request)
    _require_user(user_id)
    _require_stripe_configured()
    amount = _parse_amount_aud(body.get("amountAud"))
    interval = _parse_interval(body.get("interval"))

    admin_billing_repo.ensure_custom_price_columns()
    local = admin_billing_repo.local_billing_row(user_id)
    subscription_id = local.get("stripeSubscriptionId") if local else None
    status_ok = bool(
        local and local.get("status") in admin_billing_repo.BILLABLE_STATUSES
    )
    if not subscription_id or not status_ok:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This user has no live Stripe subscription to reprice — use an "
            "entitlement override instead.",
        )

    plan_id = str(local.get("planId") or "custom") if local else "custom"
    plan = PlanRepository().get(plan_id)
    product_id = plan.get("stripeProductId") if plan else None
    plan_name = (plan.get("name") if plan else None) or plan_id

    price = stripe_gateway.create_price(
        amount_aud=amount,
        interval=interval,
        user_id=user_id,
        product_id=product_id,
        product_name=f"Aether {plan_name} (custom price)",
    )
    price_id = price["id"]
    applied = stripe_gateway.set_subscription_price(
        subscription_id=subscription_id,
        new_price_id=price_id,
        user_id=user_id,
        plan_id=plan_id,
        interval=interval,
    )

    before = local.get("customPrice") if local else None
    admin_repo._ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            admin_billing_repo.set_custom_price(
                cur,
                user_id,
                amount_aud=amount,
                interval=interval,
                stripe_price_id=price_id,
                actor_user_id=admin["id"],
            )
            admin_repo.write_audit(
                admin["id"],
                "set_custom_price",
                target_type="user",
                target_id=user_id,
                detail={
                    "before": before,
                    "after": {
                        "amountAud": amount,
                        "interval": interval,
                        "stripePriceId": price_id,
                        "currency": "AUD",
                    },
                    "stripeSubscriptionId": subscription_id,
                    "prorationBehavior": "none",
                },
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()

    return {
        "userId": user_id,
        "amountAud": amount,
        "interval": interval,
        "currency": "AUD",
        "planId": plan_id,
        "stripePriceId": price_id,
        "stripeSubscriptionId": applied.get("id") or subscription_id,
        "prorationBehavior": "none",
        "effectiveFrom": "next_renewal",
        "note": (
            "The existing subscription was repriced in place with no proration: "
            "no charge, credit or refund was raised, and the new amount applies "
            "from the next renewal."
        ),
    }


# --------------------------------------------------------------------------- #
# ADMIN-2.0 — billing surface (local row vs Stripe truth) + local-only reconcile
# --------------------------------------------------------------------------- #


def _stripe_truth(local: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Everything Stripe knows about this customer, or an honest reason why not.

    A Stripe read that FAILS is reported as unavailable with its reason — never
    silently rendered as "no subscription", which would look identical to a
    genuinely empty Stripe account and could talk an admin into clearing a live
    customer's row.
    """
    if not stripe_gateway.is_configured():
        return {
            "available": False,
            "reason": "Billing is not configured on this deployment (no Stripe key).",
            "customer": None,
            "subscription": None,
            "subscriptions": [],
            "invoices": [],
            "paymentMethod": None,
        }
    customer_id = (local or {}).get("stripeCustomerId")
    subscription_id = (local or {}).get("stripeSubscriptionId")
    if not customer_id:
        return {
            "available": True,
            "reason": None,
            "customer": None,
            "subscription": None,
            "subscriptions": [],
            "invoices": [],
            "paymentMethod": None,
            "note": "No Stripe customer id is recorded locally for this account.",
        }
    try:
        customer = stripe_gateway.retrieve_customer(customer_id)
        subscriptions = (
            stripe_gateway.list_subscriptions(customer_id) if customer else []
        )
        subscription = (
            stripe_gateway.retrieve_subscription(subscription_id)
            if (subscription_id and customer)
            else None
        )
        invoices = stripe_gateway.list_invoices(customer_id) if customer else []
        payment_method = (
            stripe_gateway.payment_method_summary(customer_id) if customer else None
        )
    except Exception as exc:  # noqa: BLE001 — degrade honestly, never fabricate
        logger.warning(
            "admin billing surface: Stripe read failed for customer=%s: %s",
            customer_id,
            type(exc).__name__,
        )
        return {
            "available": False,
            "reason": f"Stripe read failed ({type(exc).__name__}).",
            "customer": None,
            "subscription": None,
            "subscriptions": [],
            "invoices": [],
            "paymentMethod": None,
        }
    return {
        "available": True,
        "reason": None,
        "customer": customer,
        "subscription": subscription,
        "subscriptions": subscriptions,
        "invoices": invoices,
        "paymentMethod": payment_method,
    }


def _live_subscriptions(stripe_truth: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        s
        for s in (stripe_truth.get("subscriptions") or [])
        if s.get("status") in stripe_gateway.LIVE_SUBSCRIPTION_STATUSES
    ]


def _mismatch(local: Optional[dict[str, Any]], truth: dict[str, Any]) -> dict[str, Any]:
    """Compare the local row against Stripe — or say the comparison did not run.

    ``evaluated: false`` is the whole point of this shape: when Stripe cannot be
    read, "no mismatch" would be a claim we have no basis for.
    """
    if not truth.get("available"):
        return {"evaluated": False, "hasMismatch": False, "reasons": []}
    reasons: list[str] = []
    local = local or {}
    local_paid = (local.get("planId") or "free") != "free" and local.get(
        "status"
    ) in admin_billing_repo.BILLABLE_STATUSES
    live = _live_subscriptions(truth)
    if local.get("stripeCustomerId") and truth.get("customer") is None:
        reasons.append(
            "The locally recorded Stripe customer does not resolve at Stripe."
        )
    if local_paid and not live:
        reasons.append(
            "The local row shows a paid, billable plan but Stripe has no live "
            "subscription for this customer."
        )
    if not local_paid and live:
        reasons.append(
            "Stripe shows a live subscription but the local row is not on a "
            "billable paid plan."
        )
    if local.get("stripeSubscriptionId") and truth.get("subscription") is None:
        reasons.append(
            "The locally recorded Stripe subscription id does not resolve at Stripe."
        )
    stripe_sub = truth.get("subscription")
    if stripe_sub and local.get("status") and stripe_sub.get("status") != local.get(
        "status"
    ):
        reasons.append(
            f"Status differs: local '{local.get('status')}' vs Stripe "
            f"'{stripe_sub.get('status')}'."
        )
    return {"evaluated": True, "hasMismatch": bool(reasons), "reasons": reasons}


@router.get("/users/{user_id}/billing")
def admin_user_billing(_admin: AdminUser, user_id: str) -> dict[str, Any]:
    """The local ``Subscription`` row and Stripe's own truth, SIDE BY SIDE.

    The two can disagree — the owner account is the live proof: a stale local
    ``pro/active`` row from an early test signup, with nothing cancellable at
    Stripe behind it. Rendering one number and calling it "the subscription"
    would hide exactly the discrepancy an admin needs to see, so this route
    returns both plus an explicit ``mismatch`` verdict (including
    ``evaluated: false`` when Stripe could not be read at all).

    The payment method is a MASKED summary — brand, last four digits and expiry,
    the only fields Stripe exposes.
    """
    _require_user(user_id)
    admin_billing_repo.ensure_custom_price_columns()
    local = admin_billing_repo.local_billing_row(user_id)
    truth = _stripe_truth(local)
    return {
        "userId": user_id,
        "currency": "AUD",
        "local": local,
        "stripe": truth,
        "mismatch": _mismatch(local, truth),
    }


@router.post("/users/{user_id}/billing/reconcile-local")
async def admin_reconcile_local_billing(
    admin: AdminUser, user_id: str, request: Request
) -> dict[str, Any]:
    """Clear a STALE LOCAL subscription row. Performs ZERO Stripe mutations.

    The owner's exact case: a local row claiming ``pro/active`` while Stripe has
    nothing to cancel, which makes every "Cancel" affordance a 409 and inflates
    any naive revenue figure. The fix belongs in OUR database, not Stripe's.

    SAFETY ORDER — Stripe is consulted FIRST and its answer is binding:
      * a live subscription at Stripe (``active``/``trialing``/``past_due``/...)
        is an honest 409; the row is not stale, it is correct;
      * a Stripe read we cannot perform (no key configured, while a customer id
        IS on file) is a 503, because "Stripe shows nothing" would be an
        assertion with nothing behind it;
      * only when Stripe genuinely shows no live subscription — or there is no
        Stripe customer on file at all — is the local row cleared, through the
        SAME ``_revoke_to_free`` handler the webhooks use, with
        ``cancel_stripe=False`` so not one Stripe call is made.
    """
    await _parse_json_object(request)
    _require_user(user_id)
    admin_billing_repo.ensure_custom_price_columns()
    local = admin_billing_repo.local_billing_row(user_id)
    if local is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This user has no local subscription row."
        )
    stale_candidate = (local.get("planId") or "free") != "free" or bool(
        local.get("stripeSubscriptionId")
    )
    if not stale_candidate:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The local row is already Free with no Stripe subscription — "
            "there is nothing to reconcile.",
        )

    customer_id = local.get("stripeCustomerId")
    if not customer_id:
        stripe_checked = "no_customer_on_file"
    else:
        _require_stripe_configured()
        try:
            customer = stripe_gateway.retrieve_customer(customer_id)
            subscriptions = (
                stripe_gateway.list_subscriptions(customer_id) if customer else []
            )
        except Exception as exc:  # noqa: BLE001 — never guess Stripe's answer
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"Could not read Stripe to verify this row ({type(exc).__name__}); "
                "refusing to clear a local row without Stripe's answer.",
            ) from exc
        live = [
            s
            for s in subscriptions
            if s.get("status") in stripe_gateway.LIVE_SUBSCRIPTION_STATUSES
        ]
        if live:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Stripe shows a live subscription for this customer "
                f"({live[0].get('id')}, status '{live[0].get('status')}') — the "
                "local row is not stale. Cancel or refund it instead.",
            )
        stripe_checked = (
            "no_live_subscription" if customer else "customer_not_found_at_stripe"
        )

    from app.routers.billing import _revoke_to_free

    _ensure_billing_tables()
    admin_repo._ensure_admin_schema()
    before = {
        "planId": local.get("planId"),
        "status": local.get("status"),
        "stripeSubscriptionId": local.get("stripeSubscriptionId"),
        "customPrice": local.get("customPrice"),
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            # cancel_stripe=False — the whole point: local cleanup only.
            _revoke_to_free(cur, user_id, cancel_stripe=False)
            admin_billing_repo.clear_custom_price(cur, user_id)
            admin_repo.write_audit(
                admin["id"],
                "reconcile_local_subscription",
                target_type="user",
                target_id=user_id,
                detail={
                    "before": before,
                    "after": {"planId": "free", "status": "canceled"},
                    "stripeChecked": stripe_checked,
                    "stripeMutated": False,
                },
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()

    return {
        "userId": user_id,
        "reconciled": True,
        "before": before,
        "after": {
            "planId": "free",
            "status": "canceled",
            "stripeSubscriptionId": None,
            "customPrice": None,
        },
        "stripeChecked": stripe_checked,
        "stripeMutated": False,
    }


class PlanPricingRequest(BaseModel):
    priceAudMonthly: Optional[float] = Field(default=None, ge=0)
    priceAudAnnual: Optional[float] = Field(default=None, ge=0)


def _catalog_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """The catalog editor's public shape; Stripe ids are references, not writes."""
    return {
        "id": plan["id"],
        "name": plan["name"],
        "priceAudMonthly": float(plan["priceAudMonthly"]),
        "priceAudAnnual": (
            float(plan["priceAudAnnual"]) if plan["priceAudAnnual"] is not None else None
        ),
        "stripeProductId": plan.get("stripeProductId"),
        "stripePriceIdMonthly": plan.get("stripePriceIdMonthly"),
        "stripePriceIdAnnual": plan.get("stripePriceIdAnnual"),
        "active": bool(plan["active"]),
    }


@router.get("/plans")
def admin_list_plans(_admin: AdminUser) -> dict[str, Any]:
    """All local catalog plans; this route makes no Stripe call."""
    return {"plans": [_catalog_plan(plan) for plan in PlanRepository().list_all()]}


@router.put("/plans/{plan_id}/pricing")
async def admin_update_plan_pricing(
    admin: AdminUser, plan_id: str, request: Request
) -> dict[str, Any]:
    """Change catalog prices for future checkout only; never reprice subscribers.

    Stripe Price objects are immutable and existing subscriptions retain their
    current Stripe Price. We deliberately keep the locally configured Stripe ids
    as metadata: changing catalog amounts requires the operator's existing
    Stripe-price setup workflow before a new checkout can use new IDs.
    """
    body = await _parse_json_object(request)
    if any(
        isinstance(body.get(field), bool) for field in ("priceAudMonthly", "priceAudAnnual")
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Prices must be numbers.")
    try:
        pricing = PlanPricingRequest.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            jsonable_encoder(redact_validation_errors(exc.errors())),
        ) from exc
    if pricing.priceAudMonthly is None and pricing.priceAudAnnual is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Provide priceAudMonthly or priceAudAnnual.",
        )
    values = (pricing.priceAudMonthly, pricing.priceAudAnnual)
    if any(value is not None and not math.isfinite(value) for value in values):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Prices must be finite numbers.")

    _ensure_billing_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","name","priceAudMonthly","priceAudAnnual" '
                'FROM "Plan" WHERE "id"=%s FOR UPDATE',
                (plan_id,),
            )
            columns = ("id", "name", "priceAudMonthly", "priceAudAnnual")
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
            if not rows:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
            plan = rows[0]
            before = {
                "priceAudMonthly": float(plan["priceAudMonthly"]),
                "priceAudAnnual": (
                    float(plan["priceAudAnnual"]) if plan["priceAudAnnual"] is not None else None
                ),
            }
            after = {
                "priceAudMonthly": (
                    pricing.priceAudMonthly
                    if pricing.priceAudMonthly is not None
                    else before["priceAudMonthly"]
                ),
                "priceAudAnnual": (
                    pricing.priceAudAnnual
                    if pricing.priceAudAnnual is not None
                    else before["priceAudAnnual"]
                ),
            }
            cur.execute(
                'UPDATE "Plan" SET "priceAudMonthly"=%s,"priceAudAnnual"=%s,'
                '"updatedAt"=now() WHERE "id"=%s',
                (after["priceAudMonthly"], after["priceAudAnnual"], plan_id),
            )
            admin_repo.write_audit(
                admin["id"],
                "update_plan_pricing",
                target_type="plan",
                target_id=plan_id,
                detail={"before": before, "after": after, "stripeMetadataChanged": False},
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()
    return {"id": plan_id, "name": plan["name"], **after, "currency": "AUD"}


@router.get("/billing/summary")
def admin_billing_summary(_admin: AdminUser) -> dict[str, Any]:
    """Revenue totals for the executive dashboard, honestly derived.

    Only Stripe-backed, non-admin, non-deleted rows count as revenue; the rows
    that do NOT count are reported as their own figures (``unbackedPaidRows``,
    ``excludedAdminRows``, ``excludedDeletedRows``) instead of being folded in
    silently. Annual subscriptions are normalised to a monthly figure by
    dividing by 12, which is why the payload is flagged ``estimate: true``.
    """
    return admin_billing_repo.billing_summary()


# --------------------------------------------------------------------------- #
# ADMIN-2.0 — promotions (Stripe Coupon + PromotionCode)
#
# MONEY SAFETY: a Coupon is a discount DEFINITION and a PromotionCode is the
# string a customer can type at checkout. Creating, listing or deactivating them
# moves no money and charges nobody — which is exactly why these are the only
# live-Stripe writes this feature's verification is allowed to perform.
# --------------------------------------------------------------------------- #

_PROMO_DURATIONS = ("once", "repeating", "forever")


def _parse_promo_body(body: dict[str, Any]) -> dict[str, Any]:
    """Validate a promo request into gateway kwargs, or raise the honest 422."""
    percent_off = body.get("percentOff")
    amount_off = body.get("amountOffAud")
    if percent_off is not None and amount_off is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Provide either percentOff or amountOffAud — not both.",
        )
    if percent_off is None and amount_off is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Provide a percentOff or an amountOffAud.",
        )
    if percent_off is not None:
        if isinstance(percent_off, bool) or not isinstance(percent_off, (int, float)):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "percentOff must be a number."
            )
        percent_off = round(float(percent_off), 2)
        if not 0 < percent_off <= 100:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "percentOff must be greater than 0 and at most 100.",
            )
    if amount_off is not None:
        amount_off = _parse_amount_aud(amount_off)

    duration = body.get("duration") or "once"
    if duration not in _PROMO_DURATIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"duration must be one of {', '.join(_PROMO_DURATIONS)}.",
        )
    duration_in_months = body.get("durationInMonths")
    if duration == "repeating":
        if (
            isinstance(duration_in_months, bool)
            or not isinstance(duration_in_months, int)
            or duration_in_months < 1
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "durationInMonths (a positive integer) is required when "
                "duration is 'repeating'.",
            )
    else:
        duration_in_months = None

    code = body.get("code")
    if code is not None:
        if not isinstance(code, str) or not code.strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "code must be a non-empty string when provided.",
            )
        code = code.strip().upper()

    max_redemptions = body.get("maxRedemptions")
    if max_redemptions is not None:
        if (
            isinstance(max_redemptions, bool)
            or not isinstance(max_redemptions, int)
            or max_redemptions < 1
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "maxRedemptions must be a positive integer when provided.",
            )

    name = body.get("name")
    if name is not None and not isinstance(name, str):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "name must be a string."
        )

    return {
        "name": name,
        "percent_off": percent_off,
        "amount_off_aud": amount_off,
        "duration": duration,
        "duration_in_months": duration_in_months,
        "code": code,
        "max_redemptions": max_redemptions,
    }


@router.get("/promos")
def admin_list_promos(_admin: AdminUser) -> dict[str, Any]:
    """Promotion codes as STRIPE holds them — no local mirror to drift."""
    _require_stripe_configured()
    promos = stripe_gateway.list_promotion_codes()
    return {"promos": promos, "total": len(promos)}


@router.post("/promos", status_code=status.HTTP_201_CREATED)
async def admin_create_promo(admin: AdminUser, request: Request) -> dict[str, Any]:
    """Create a Stripe Coupon and its customer-facing PromotionCode.

    Body: ``{"percentOff"|"amountOffAud", "duration", "durationInMonths"?,
    "code"?, "maxRedemptions"?, "name"?}``. Creating a discount charges nobody;
    money only moves when a customer redeems the code at their own checkout.
    """
    body = await _parse_json_object(request)
    _require_stripe_configured()
    args = _parse_promo_body(body)

    coupon = stripe_gateway.create_coupon(
        name=args["name"],
        percent_off=args["percent_off"],
        amount_off_aud=args["amount_off_aud"],
        duration=args["duration"],
        duration_in_months=args["duration_in_months"],
    )
    promo = stripe_gateway.create_promotion_code(
        coupon_id=coupon["id"],
        code=args["code"],
        max_redemptions=args["max_redemptions"],
    )
    admin_repo.write_audit(
        admin["id"],
        "create_promo",
        target_type="promo",
        target_id=promo.get("id"),
        detail={
            "code": promo.get("code"),
            "couponId": coupon["id"],
            "percentOff": args["percent_off"],
            "amountOffAud": args["amount_off_aud"],
            "duration": args["duration"],
            "durationInMonths": args["duration_in_months"],
            "maxRedemptions": args["max_redemptions"],
        },
        ip=_client_ip(request),
    )
    return {
        "promotionCodeId": promo.get("id"),
        "code": promo.get("code"),
        "couponId": coupon["id"],
        "percentOff": args["percent_off"],
        "amountOffAud": args["amount_off_aud"],
        "duration": args["duration"],
        "durationInMonths": args["duration_in_months"],
        "maxRedemptions": args["max_redemptions"],
        "expiresAt": promo.get("expiresAt"),
        "active": bool(promo.get("active", True)),
        "currency": "AUD",
    }


@router.delete("/promos/{promotion_code_id}")
def admin_deactivate_promo(
    admin: AdminUser, promotion_code_id: str, request: Request
) -> dict[str, Any]:
    """Deactivate a promotion code (``active=false``).

    Deliberately a deactivation, not a coupon delete: it is reversible and it
    preserves the redemption history of every customer who already used the code.
    """
    _require_stripe_configured()
    result = stripe_gateway.deactivate_promotion_code(promotion_code_id)
    admin_repo.write_audit(
        admin["id"],
        "deactivate_promo",
        target_type="promo",
        target_id=promotion_code_id,
        detail={"active": False},
        ip=_client_ip(request),
    )
    return {
        "promotionCodeId": result.get("id") or promotion_code_id,
        "active": bool(result.get("active", False)),
    }


# --------------------------------------------------------------------------- #
# ADMIN-2.0 BE-2 — sales agents (referral codes, attribution, commission)
#
# A sales agent is a human reseller with a referral code. There is deliberately
# NO delete route: a distributed code lives on in links and in the attribution
# history of every account it brought in, so "remove" means deactivate — the
# code stops attributing and the earned history stays readable.
# --------------------------------------------------------------------------- #


def _clean_agent_name(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "name is required."
        )
    return raw.strip()


def _clean_optional_text(raw: Any, field: str) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} must be a string."
        )
    return raw.strip() or None


def _clean_commission_pct(raw: Any) -> float:
    """0..100 inclusive, as a real number.

    ``bool`` is rejected explicitly: ``True`` is an ``int`` in Python and would
    silently become a 1% commission.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "commissionPct must be a number between 0 and 100.",
        )
    value = float(raw)
    if value < 0 or value > 100:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "commissionPct must be between 0 and 100.",
        )
    return value


def _clean_agent_status(raw: Any) -> str:
    if not isinstance(raw, str) or raw.strip().lower() not in (
        sales_agents_repo.SALES_AGENT_STATUSES
    ):
        allowed = " | ".join(sales_agents_repo.SALES_AGENT_STATUSES)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"status must be one of: {allowed}. There is no delete: an agent "
            "whose code is already in circulation is deactivated, never erased.",
        )
    return raw.strip().lower()


@router.get("/sales-agents")
def admin_list_sales_agents(
    _admin: AdminUser,
    status_filter: Optional[str] = Query(default=None, alias="status"),
) -> dict[str, Any]:
    """Sales agents with their REAL attributed signup / conversion counts."""
    cleaned = _clean_agent_status(status_filter) if status_filter else None
    return sales_agents_repo.list_agents(status=cleaned)


@router.post("/sales-agents", status_code=status.HTTP_201_CREATED)
async def admin_create_sales_agent(admin: AdminUser, request: Request) -> dict[str, Any]:
    """Register a sales agent and mint (or accept) their referral code.

    Body ``{"name", "email"?, "referralCode"?, "commissionPct"?, "notes"?}``.
    An omitted code is generated with ``secrets`` — a guessable referral code is
    an attribution somebody else can claim. Codes are stored uppercase, so
    ``?ref=jane-2026`` and ``?ref=JANE-2026`` are the same agent.

    The agent row and its ``AdminAuditLog`` entry are written on ONE cursor in
    ONE transaction, so an agent can never exist unaudited.
    """
    body = await _parse_json_object(request)
    name = _clean_agent_name(body.get("name"))
    email = _clean_optional_text(body.get("email"), "email")
    notes = _clean_optional_text(body.get("notes"), "notes")
    commission_pct = _clean_commission_pct(body.get("commissionPct", 0))

    raw_code = body.get("referralCode")
    if raw_code is None:
        referral_code = sales_agents_repo.allocate_referral_code(name)
    else:
        try:
            referral_code = sales_agents_repo.normalize_referral_code(raw_code)
        except sales_agents_repo.InvalidReferralCodeError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
            ) from exc

    # Every lazy-DDL side effect happens OUTSIDE the transaction.
    admin_repo._ensure_admin_schema()
    sales_agents_repo.ensure_sales_agent_schema()

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                created = sales_agents_repo.create_agent(
                    cur,
                    name=name,
                    email=email,
                    referral_code=referral_code,
                    commission_pct=commission_pct,
                    notes=notes,
                    actor_user_id=admin["id"],
                )
            except sales_agents_repo.DuplicateReferralCodeError as exc:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Referral code '{referral_code}' is already in use.",
                ) from exc
            admin_repo.write_audit(
                admin["id"],
                "create_sales_agent",
                target_type="sales_agent",
                target_id=created["id"],
                detail={
                    "name": name,
                    "email": email,
                    "referralCode": referral_code,
                    "commissionPct": commission_pct,
                },
                ip=_client_ip(request),
                cur=cur,
            )
        conn.commit()
    return sales_agents_repo._agent_view(created, {"signups": 0, "converted": 0})


@router.patch("/sales-agents/{agent_id}")
async def admin_update_sales_agent(
    admin: AdminUser, agent_id: str, request: Request
) -> dict[str, Any]:
    """Update an agent — including ``status: "inactive"``, which IS the delete.

    ``referralCode`` is immutable: the code is already printed on links the
    agent has handed out, and rewriting it would silently break every one of
    them while orphaning nothing (attribution stores the agent id, not the
    code). Mint a second agent instead if a new code is wanted.
    """
    body = await _parse_json_object(request)
    if "referralCode" in body:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "referralCode cannot be changed: the code is already in circulation "
            "on links this agent has distributed. Create a new agent instead.",
        )

    changes: dict[str, Any] = {}
    if "name" in body:
        changes["name"] = _clean_agent_name(body.get("name"))
    if "email" in body:
        changes["email"] = _clean_optional_text(body.get("email"), "email")
    if "notes" in body:
        changes["notes"] = _clean_optional_text(body.get("notes"), "notes")
    if "commissionPct" in body:
        changes["commissionPct"] = _clean_commission_pct(body.get("commissionPct"))
    if "status" in body:
        changes["status"] = _clean_agent_status(body.get("status"))
    if not changes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No updatable field supplied (name, email, notes, commissionPct, status).",
        )

    admin_repo._ensure_admin_schema()
    sales_agents_repo.ensure_sales_agent_schema()

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                updated = sales_agents_repo.update_agent(cur, agent_id, changes)
            except sales_agents_repo.SalesAgentNotFoundError as exc:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, "Sales agent not found"
                ) from exc
            admin_repo.write_audit(
                admin["id"],
                "update_sales_agent",
                target_type="sales_agent",
                target_id=agent_id,
                detail={"changed": changes},
                ip=_client_ip(request),
                cur=cur,
            )
            # Same cursor: the counts the caller gets back are the ones that
            # hold in the transaction it just committed, and the response shape
            # matches the list route's exactly (no field that appears on one
            # and vanishes on the other).
            counts = sales_agents_repo.attribution_counts(cur)
        conn.commit()
    return sales_agents_repo._agent_view(updated, counts.get(agent_id, {}))


@router.get("/sales-agents/{agent_id}/report")
def admin_sales_agent_report(_admin: AdminUser, agent_id: str) -> dict[str, Any]:
    """Commission report — REPORT ONLY.

    Attributed accounts, what they REALLY paid (from the signature-verified
    Stripe webhook payloads recorded locally, net of real refunds) and
    ``commissionPct`` x that. It writes nothing, moves no money, creates no
    Stripe object and schedules no payout: paying an agent stays a deliberate
    act performed outside the product.
    """
    try:
        return sales_agents_repo.commission_report(agent_id)
    except sales_agents_repo.SalesAgentNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Sales agent not found"
        ) from exc


# --------------------------------------------------------------------------- #
# ADMIN-2.0 BE-2 — executive metrics (the one read the dashboard polls)
# --------------------------------------------------------------------------- #


@router.get("/metrics/executive")
def admin_executive_metrics(_admin: AdminUser) -> dict[str, Any]:
    """Every figure the executive dashboard renders, from one consistent read.

    Read-only. MRR / paid count / plan mix, signups per day, the
    signup->run->submission->paid funnel, LLM cost (USD) beside revenue (AUD)
    with NO exchange rate applied, run volume per day, and top referrers.
    Each block carries its own ``sampleSize`` + ``insufficientData`` so a figure
    drawn from three rows is labelled as such instead of being rendered as a
    confident trend.
    """
    return admin_metrics_repo.executive_metrics()
