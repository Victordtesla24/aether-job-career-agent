"""JWT bearer-token dependency guarding protected routes (P2-S01)."""
from __future__ import annotations

from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.repositories.user import UserRepository
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


_SUSPENDED_ERROR = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Account suspended",
)

_ADMIN_ERROR = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Admin privileges required",
)


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict[str, Any]:
    """Resolve the authenticated user from a Bearer JWT, or raise 401.

    Also enforces account suspension (GAP-P6 §15): a suspended user gets a 403 on
    every authenticated route. ``isAdmin`` is projected onto the returned dict so
    ``get_admin_user`` can gate /admin/* without a second lookup.
    """
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise _CREDENTIALS_ERROR from None

    user_id = payload.get("userId") or payload.get("sub")
    if not user_id:
        raise _CREDENTIALS_ERROR

    user = UserRepository().get_auth_context(user_id)
    if user is None:
        raise _CREDENTIALS_ERROR
    if user.get("suspended"):
        raise _SUSPENDED_ERROR
    user["isAdmin"] = bool(user.get("isAdmin"))
    return user


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


def get_admin_user(current_user: CurrentUser) -> dict[str, Any]:
    """Admin-only dependency: 403 for any non-admin. Auth (401) is enforced by
    the ``get_current_user`` chain first, so an anonymous caller never sees 403.
    """
    if not current_user.get("isAdmin"):
        raise _ADMIN_ERROR
    return current_user


AdminUser = Annotated[dict[str, Any], Depends(get_admin_user)]
