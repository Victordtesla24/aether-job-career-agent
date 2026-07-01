"""Request/response models for the auth endpoints (P2-S01)."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    """Payload for ``POST /auth/register``."""

    email: EmailStr
    password: str


class RegisterResponse(BaseModel):
    """Response for a successful registration — never includes the hash."""

    id: str
    email: EmailStr


class LoginRequest(BaseModel):
    """Payload for ``POST /auth/login``."""

    email: EmailStr
    password: str


class UserPublic(BaseModel):
    """The safe, hash-free public view of a user."""

    id: str
    email: EmailStr


class LoginResponse(BaseModel):
    """Response for a successful login.

    Carries the signed session JWT plus the public user identity so the web
    layer can establish a NextAuth session without decoding the token or ever
    seeing the password hash.
    """

    access_token: str
    token_type: str = "bearer"
    user: UserPublic
