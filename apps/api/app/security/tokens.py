"""Session JWT signing and verification (P2-S01).

The API issues its own stateless session tokens on ``/auth/login`` and verifies
them in the auth middleware. Tokens are HMAC-SHA256 signed with
``NEXTAUTH_SECRET`` (shared with the web layer) and carry ``userId``, ``email``,
``iat`` and a 24-hour ``exp`` — matching the contract in the Phase 2 spec.

SECURITY: the signing secret is read from settings and is never logged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import get_settings

#: HMAC-SHA256 — the default NextAuth algorithm for symmetric secrets, so the
#: web and API layers agree on token format.
ALGORITHM = "HS256"

#: Access-token lifetime in hours.
ACCESS_TOKEN_EXPIRE_HOURS = 24


class TokenError(Exception):
    """Raised when a token cannot be decoded or has expired/been tampered with."""


def create_access_token(user_id: str, email: str) -> str:
    """Sign and return a session JWT for the given user."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "userId": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)).timestamp()),
    }
    return jwt.encode(claims, settings.nextauth_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Verify and decode a session JWT, returning its claims.

    Raises :class:`TokenError` on any signature/expiry/format problem.
    """
    settings = get_settings()
    try:
        return jwt.decode(token, settings.nextauth_secret, algorithms=[ALGORITHM])
    except JWTError as exc:  # invalid signature, expired, malformed, ...
        raise TokenError(str(exc)) from exc
