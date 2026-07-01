"""Password hashing and policy (P2-S01).

Hashing uses ``passlib`` with the bcrypt scheme — passwords are never stored or
logged in plaintext. The password policy (``min 8 chars, at least 1 digit``) is
extracted here as a shared validator so both the register endpoint and any
future password-change flow enforce it identically (P2-S01 REFACTOR step).
"""
from __future__ import annotations

import re

from passlib.context import CryptContext

# bcrypt is the industry-standard adaptive hash; ``deprecated="auto"`` lets us
# transparently upgrade the work factor later without breaking existing hashes.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

#: Minimum acceptable password length.
MIN_PASSWORD_LENGTH = 8

_DIGIT_RE = re.compile(r"\d")


class PasswordPolicyError(ValueError):
    """Raised when a candidate password violates the password policy."""


def validate_password_policy(password: str) -> None:
    """Validate ``password`` against the policy, raising on violation.

    Policy: at least ``MIN_PASSWORD_LENGTH`` characters and at least one digit.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
        )
    if not _DIGIT_RE.search(password):
        raise PasswordPolicyError("Password must contain at least one digit")


def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password``."""
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Return ``True`` iff ``plain`` matches the bcrypt ``hashed`` value."""
    return _pwd_context.verify(plain, hashed)
