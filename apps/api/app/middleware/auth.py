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

#: Slack for the O-4 passwordChangedAt/iat comparison in ``get_current_user``
#: — see the comment at that check for why this must be > 0.
_IAT_GRACE_SECONDS = 1.0


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
    # O-4: a password reset (POST /auth/reset-password) stamps
    # passwordChangedAt and must invalidate every token minted before it —
    # the only "invalidate sessions" mechanism available without a
    # server-side session store, since a JWT is otherwise verified purely by
    # signature + expiry. A token whose ``iat`` predates the stamp is
    # rejected exactly like any other invalid credential (401), forcing a
    # fresh /login with the new password. NULL (never reset) skips the
    # check entirely, so no pre-existing session is affected.
    #
    # _IAT_GRACE_SECONDS: PyJWT encodes "iat" as a whole-second Unix
    # timestamp (fractional seconds truncated), while ``passwordChangedAt``
    # is a microsecond-precision Postgres ``now()``. Without slack, a login
    # that happens in the SAME wall-clock second as the reset (an entirely
    # normal sequence: reset -> immediately sign in again) can mint a token
    # whose truncated ``iat`` reads up to ~1s *earlier* than the stamp,
    # tripping this check and 401ing a session that is legitimately newer
    # than the reset. One second of slack absorbs exactly that truncation
    # error; the (already tiny) cost is that a token minted in the ~1s
    # immediately before the reset could remain valid for up to 1 extra
    # second — negligible next to the 24h token TTL.
    changed_at = user.get("passwordChangedAt")
    if changed_at is not None:
        iat = payload.get("iat")
        if iat is None or float(iat) < (changed_at.timestamp() - _IAT_GRACE_SECONDS):
            raise _CREDENTIALS_ERROR
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
