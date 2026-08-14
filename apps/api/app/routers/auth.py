"""Auth router — register + login with bcrypt hashing and JWT (P2-S01)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, field_validator

from app.db import ensure_user_profile_columns, get_connection, rows_to_dicts
from app.middleware.auth import CurrentUser
from app.rate_limit import (
    guard_forgot_password_attempt,
    guard_login_attempt,
    guard_register_attempt,
    guard_reset_password_attempt,
    record_login_failure,
    record_reset_password_failure,
    reset_login_failures,
    reset_reset_password_failures,
)
from app.repositories.user import (
    DuplicateEmailError,
    UserRepository,
    validate_password_policy,
)
from app.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    # Optional display name for the new account (the /signup form submits it).
    # Persisted on the User row so self-registered users don't get a blank
    # profile name; absent/blank values leave ``name`` NULL.
    name: str | None = None

    @field_validator("password")
    @classmethod
    def _enforce_policy(cls, value: str) -> str:
        problems = validate_password_policy(value)
        if problems:
            raise ValueError("; ".join(problems))
        return value

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class LoginRequest(BaseModel):
    # Identifier — an email OR a username. Kept named ``email`` for backward
    # compatibility with the existing frontend/tests, and deliberately a plain
    # ``str`` (not ``EmailStr``) so a bare username like "admin" validates.
    email: str
    password: str


class UserResponse(BaseModel):
    """Public user shape — deliberately excludes any credential material."""

    id: str
    email: str
    createdAt: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    userId: str
    email: str


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(request: Request, body: RegisterRequest) -> UserResponse:
    # Public-registration gate (§15 admin settings): when an admin has turned
    # signup off, self-service registration is refused. Checked before the rate
    # limiter so a disabled signup returns a clean 403.
    from app.repositories.admin import signup_enabled

    if not signup_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is currently disabled",
        )
    # Rate-limit keyed on the normalized submitted email (never client IP):
    # caps re-registration spam on one address. Runs after Pydantic validation,
    # so a malformed/weak-password request 422s without consuming budget.
    guard_register_attempt(request, body.email)
    try:
        user = UserRepository().create(
            body.email, hash_password(body.password), name=body.name
        )
    except DuplicateEmailError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from None
    return UserResponse(id=user["id"], email=user["email"], createdAt=user["createdAt"])


@router.post(
    "/login",
    response_model=TokenResponse,
)
def login(request: Request, body: LoginRequest) -> TokenResponse:
    # ``email`` is an identifier: an email address OR a username. The failed-
    # login limiter is keyed on the normalized identifier (never client IP):
    # too many failures for one account -> 429 before we even check the
    # password. Different identifiers are independent.
    from app.repositories.admin import (
        EMAIL_VERIFICATION_KEY,
        get_setting,
        weak_operator_credential_refused,
    )

    # INC-B-002 / FE-D-002: mirrors the ``signupEnabled`` gate above
    # (register()) EXACTLY — a plain, unconditional platform-level toggle
    # checked before anything else, same shape (403, explicit detail),
    # same position (before the rate limiter). No per-user "verified"
    # column or verification flow exists anywhere in this schema, so ON
    # means every account is permanently unverified by construction: this
    # is a deliberate stopgap kill-switch on login, not a nuanced per-user
    # check, until a real verification flow exists. Previously the flag
    # was persisted by POST /admin/settings but never read here — inert.
    if bool(get_setting(EMAIL_VERIFICATION_KEY, False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Email verification is currently required by the operator "
                "and no account can satisfy it yet — login is temporarily "
                "disabled. Contact support."
            ),
        )

    guard_login_attempt(request, body.email)
    user = UserRepository().get_by_username_or_email(body.email)
    # Constant-shaped failure: never reveal whether the identifier exists. Any
    # failed attempt (unknown identifier, no hash, wrong password, or a
    # refused weak operator credential) counts toward this identifier's
    # lockout and returns the SAME 401 body — no user-enumeration signal.
    #
    # BLOCKER-001: the last clause is the fail-closed half of the degraded
    # admin-credential handling. It is evaluated only after the password has
    # already verified, so it refuses exactly those weak operator credentials
    # that WOULD otherwise have authenticated. See
    # ``admin.weak_operator_credential_refused`` for its (deliberately narrow)
    # scope and why it must not key on the password value alone.
    if (
        user is None
        or not user.get("passwordHash")
        or not verify_password(body.password, user["passwordHash"])
        or weak_operator_credential_refused(body.email, body.password)
    ):
        record_login_failure(request, body.email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    # A successful login clears the counter so a legit user is never locked out
    # by their own earlier typos.
    reset_login_failures(request, body.email)
    # Stamp last-login for the admin user list (§15). Best-effort: an additive
    # column write must never fail an otherwise-valid login.
    try:
        UserRepository().touch_last_login(user["id"])
    except Exception:  # noqa: BLE001
        pass
    token = create_access_token(user["id"], user["email"])
    return TokenResponse(access_token=token, userId=user["id"], email=user["email"])


@router.get("/me")
def me(current_user: CurrentUser) -> dict[str, Any]:
    """Return the authenticated user's profile."""
    uid = current_user["id"]
    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id, email, name, "targetRole", "location" FROM "User" WHERE id = %s',
                (uid,),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    u = rows[0]
    return {
        "id": u["id"],
        "email": u["email"],
        "name": u.get("name") or "",
        "targetRole": u.get("targetRole") or "",
        "location": u.get("location") or "",
        # Surface the privilege flag so the frontend can gate the /admin UI
        # (resolved live from the row by the auth dependency).
        "isAdmin": bool(current_user.get("isAdmin")),
    }


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    # Always ``True``: the request was accepted (anti-enumeration — this
    # response shape is IDENTICAL whether or not an account exists for the
    # submitted email). ``emailSendingEnabled`` is the one honest signal
    # returned: ``False`` means no outbound-email provider is configured
    # today, so no email was ever attempted for ANY address — the frontend
    # renders that plainly rather than claiming a link was sent.
    #
    # ``deliveryDegraded`` (MF-3): a provider CAN be configured and still be
    # failing (bad credentials, provider outage, unverified sending domain).
    # This reflects ``email_sender.delivery_degraded()`` — a process-level,
    # deployment-wide "did the most recent attempted send succeed" flag, NOT
    # a per-request/per-address result. It is safe against anti-enumeration
    # for that exact reason: every request (known address or not) reads the
    # same shared value at response time, so it never reveals whether THIS
    # request's address actually triggered a send attempt.
    ok: bool = True
    emailSendingEnabled: bool
    deliveryDegraded: bool = False


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def _enforce_policy(cls, value: str) -> str:
        problems = validate_password_policy(value)
        if problems:
            raise ValueError("; ".join(problems))
        return value


class ResetPasswordResponse(BaseModel):
    ok: bool = True


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
)
def forgot_password(request: Request, body: ForgotPasswordRequest) -> ForgotPasswordResponse:
    """O-4 — start a password reset. Always 200; never reveals account existence.

    Rate-limited per submitted email (every accepted call counts, matching
    ``guard_register_attempt``'s shape — an anti-enumeration response must not
    let a caller distinguish "known" from "unknown" by rate either).

    When a real, password-having account matches the email, a single-use
    hashed token is minted and an email is attempted via
    ``app.services.email_sender`` (SMTP or a Resend-style HTTPS API —
    whichever is configured). When NEITHER provider is configured, the token
    is still minted (so turning on a provider later works retroactively for
    any link the operator might have relayed manually) but no send is
    attempted; either way the response's ``emailSendingEnabled`` flag tells
    the frontend the honest truth instead of claiming a link was sent when it
    was not.

    ``deliveryDegraded`` (MF-3) additionally reports whether the most recent
    ATTEMPTED send in this process actually succeeded — a configured
    provider can still be failing (bad credentials, outage, unverified
    domain), and that must not be reported to the visitor as a successful
    send just because ``emailSendingEnabled`` is true.
    """
    from app.repositories.admin import password_is_env_managed
    from app.services import email_sender
    from app.services.password_reset import build_reset_email_body, create_reset_token
    from app.services.stripe_gateway import app_base_url

    guard_forgot_password_attempt(request, body.email)

    email_enabled = email_sender.is_configured()
    user = UserRepository().get_by_email(body.email)
    if user is not None and user.get("passwordHash"):
        if password_is_env_managed(user.get("email")):
            # §14.7: the link will be REFUSED at completion (the environment
            # owns this password). The response stays byte-identical — softening
            # it here would turn this route into an account-enumeration oracle
            # for the operator address — but the operator gets a log line
            # instead of a silent dead end. Value-free: no address, no hash.
            logger.info(
                "forgot-password: userId=%s is the env-managed admin identity; "
                "the reset link will be refused at completion because "
                "AETHER_ADMIN_PASSWORD_HASH is re-applied on every restart",
                user["id"],
            )
        raw_token = create_reset_token(user["id"])
        if email_enabled:
            reset_url = f"{app_base_url()}/reset-password?token={raw_token}"
            sent = email_sender.send_email(
                user["email"],
                "Reset your Aether password",
                build_reset_email_body(reset_url),
            )
            if not sent:
                logger.info(
                    "forgot-password: provider configured but send failed for "
                    "userId=%s — operator should verify provider credentials "
                    "(see docs/delivery/EMAIL-SETUP.md)",
                    user["id"],
                )
        else:
            logger.info(
                "forgot-password: no outbound email provider configured — a "
                "reset token was minted for userId=%s but NOT delivered. See "
                "docs/delivery/EMAIL-SETUP.md to enable self-service reset.",
                user["id"],
            )
    else:
        logger.info(
            "forgot-password: requested for an address with no local "
            "password account (anti-enumeration 200; no token minted)"
        )
    return ForgotPasswordResponse(
        emailSendingEnabled=email_enabled,
        deliveryDegraded=email_sender.delivery_degraded(),
    )


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
)
def reset_password(request: Request, body: ResetPasswordRequest) -> ResetPasswordResponse:
    """O-4 — complete a password reset with a single-use token.

    Rate-limited per submitted token (only failures count, mirroring
    ``guard_login_attempt``'s shape). A rejected token — unknown, expired, or
    already used — is a generic 400 that reveals nothing about WHY it failed.
    On success, ``UserRepository.set_password`` stamps ``passwordChangedAt``,
    which rejects session tokens minted before it (see
    ``app.middleware.auth.get_current_user``) — the caller must sign in again
    with the new password. Sessions minted inside the last
    ``_IAT_GRACE_SECONDS`` before the stamp are the documented exception: the
    slack that stops an immediate post-reset login from 401ing itself also
    spares them. ``POST /admin/users/{id}/password``, whose whole purpose is a
    lockout, waits that window out first; the self-service path deliberately
    does not, because the person resetting IS the account holder.

    §14.7: an identity whose password is managed by server configuration
    (``AETHER_ADMIN_PASSWORD_HASH``, re-applied by ``apply_admin_rotation`` on
    every boot) is REFUSED with a 409 naming the mechanism and the remedy.
    Accepting it would show a success screen for a password the next restart
    silently reverts — the account holder would then be locked out with nothing
    anywhere explaining why. The token is consumed first either way, so a link
    that can never complete does not stay live.
    """
    from app.repositories.admin import (
        ENV_MANAGED_PASSWORD_MESSAGE,
        password_is_env_managed,
    )
    from app.services.password_reset import consume_reset_token

    guard_reset_password_attempt(request, body.token)
    user_id = consume_reset_token(body.token)
    if user_id is None:
        record_reset_password_failure(request, body.token)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Request a new one.",
        )
    reset_reset_password_failures(request, body.token)
    user = UserRepository().get_by_id(user_id)
    if password_is_env_managed(user.get("email") if user else None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ENV_MANAGED_PASSWORD_MESSAGE,
        )
    UserRepository().set_password(user_id, hash_password(body.password))
    return ResetPasswordResponse()
