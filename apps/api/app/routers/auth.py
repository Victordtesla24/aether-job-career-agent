"""Auth router — register + login with bcrypt hashing and JWT (P2-S01)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, field_validator

from app.db import ensure_user_profile_columns, get_connection, rows_to_dicts
from app.middleware.auth import CurrentUser
from app.rate_limit import (
    guard_login_attempt,
    guard_register_attempt,
    record_login_failure,
    reset_login_failures,
)
from app.repositories.user import (
    DuplicateEmailError,
    UserRepository,
    validate_password_policy,
)
from app.security import create_access_token, hash_password, verify_password

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
    guard_login_attempt(request, body.email)
    user = UserRepository().get_by_username_or_email(body.email)
    # Constant-shaped failure: never reveal whether the identifier exists. Any
    # failed attempt (unknown identifier, no hash, or wrong password) counts
    # toward this identifier's lockout.
    if (
        user is None
        or not user.get("passwordHash")
        or not verify_password(body.password, user["passwordHash"])
    ):
        record_login_failure(request, body.email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    # A successful login clears the counter so a legit user is never locked out
    # by their own earlier typos.
    reset_login_failures(request, body.email)
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
    }
