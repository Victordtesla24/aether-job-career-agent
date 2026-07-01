"""Authentication endpoints — register and login (P2-S01).

``POST /auth/register`` creates a user with a bcrypt-hashed password and returns
its public identity (never the hash). ``POST /auth/login`` verifies credentials
and returns a signed session JWT that protected routes accept.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2.extensions import connection as PgConnection

from app.db import get_db
from app.repositories.user import UserRepository
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserPublic,
)
from app.security.passwords import (
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.security.tokens import create_access_token

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest, conn: PgConnection = Depends(get_db)
) -> RegisterResponse:
    """Register a new user. Rejects weak passwords and duplicate emails."""
    try:
        validate_password_policy(payload.password)
    except PasswordPolicyError as exc:
        # 422 Unprocessable Content — the numeric literal is used directly to
        # stay valid across the supported FastAPI/Starlette range (the named
        # constant was renamed and the old alias is deprecated).
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    repo = UserRepository(conn)
    email = payload.email.strip().lower()
    if repo.get_by_email(email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    user = repo.create(email=email, password_hash=hash_password(payload.password))
    return RegisterResponse(id=user.id, email=user.email)


@router.post("/auth/login", response_model=LoginResponse)
def login(
    payload: LoginRequest, conn: PgConnection = Depends(get_db)
) -> LoginResponse:
    """Verify credentials and return a signed session JWT."""
    repo = UserRepository(conn)
    email = payload.email.strip().lower()
    user = repo.get_by_email(email)

    # Uniform failure for unknown user OR bad password (no user enumeration).
    if user is None or not user.password_hash or not verify_password(
        payload.password, user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(user_id=user.id, email=user.email)
    return LoginResponse(
        access_token=token, user=UserPublic(id=user.id, email=user.email)
    )
