"""Password hashing (bcrypt) and JWT signing/verification helpers (P2-S01)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

#: Access tokens are valid for 24 hours.
TOKEN_TTL = timedelta(hours=24)
JWT_ALGORITHM = "HS256"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_jwt_secret() -> str:
    """JWT signing secret — ``JWT_SECRET`` wins, falling back to NextAuth's."""
    secret = os.environ.get("JWT_SECRET") or os.environ.get("NEXTAUTH_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET / NEXTAUTH_SECRET is not configured")
    return secret


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except ValueError:
        # Malformed/legacy hash — treat as a failed verification, not a 500.
        return False


def create_access_token(user_id: str, email: str) -> str:
    """Sign a JWT carrying userId/email with iat + 24h exp claims."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "userId": user_id,
        "email": email,
        "iat": now,
        "exp": now + TOKEN_TTL,
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode + verify a JWT; raises ``jwt.PyJWTError`` on any failure."""
    return jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
