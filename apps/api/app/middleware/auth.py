"""Authentication middleware (P2-S01).

Provides the ``get_current_user`` FastAPI dependency: it extracts the Bearer
token from the ``Authorization`` header, verifies its signature/expiry, and
resolves the authenticated user. Routes protect themselves by declaring
``current_user: CurrentUser = Depends(get_current_user)``.

A missing/invalid/expired token yields ``401 Unauthorized`` (with the standard
``WWW-Authenticate: Bearer`` challenge) rather than leaking why.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from psycopg2.extensions import connection as PgConnection

from app.db import get_db
from app.repositories.user import UserRepository
from app.security.tokens import TokenError, decode_access_token


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated principal derived from a verified JWT."""

    id: str
    email: str


_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    authorization: str | None = Header(default=None),
    conn: PgConnection = Depends(get_db),
) -> CurrentUser:
    """Resolve the current user from the Bearer token, or raise 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _UNAUTHORIZED

    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_access_token(token)
    except TokenError:
        raise _UNAUTHORIZED

    user_id = claims.get("userId")
    email = claims.get("email")
    if not user_id or not email:
        raise _UNAUTHORIZED

    # Confirm the user still exists (tokens outlive deleted accounts).
    user = UserRepository(conn).get_by_id(user_id)
    if user is None:
        raise _UNAUTHORIZED

    return CurrentUser(id=user.id, email=user.email)
