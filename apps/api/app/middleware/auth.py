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


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict[str, Any]:
    """Resolve the authenticated user from a Bearer JWT, or raise 401."""
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise _CREDENTIALS_ERROR from None

    user_id = payload.get("userId") or payload.get("sub")
    if not user_id:
        raise _CREDENTIALS_ERROR

    user = UserRepository().get_by_id(user_id)
    if user is None:
        raise _CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
