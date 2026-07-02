"""Auth router — register + login with bcrypt hashing and JWT (P2-S01)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator

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

    @field_validator("password")
    @classmethod
    def _enforce_policy(cls, value: str) -> str:
        problems = validate_password_policy(value)
        if problems:
            raise ValueError("; ".join(problems))
        return value


class LoginRequest(BaseModel):
    email: EmailStr
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


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest) -> UserResponse:
    try:
        user = UserRepository().create(body.email, hash_password(body.password))
    except DuplicateEmailError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from None
    return UserResponse(id=user["id"], email=user["email"], createdAt=user["createdAt"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest) -> TokenResponse:
    user = UserRepository().get_by_email(body.email)
    # Constant-shaped failure: never reveal whether the email exists.
    if user is None or not user.get("passwordHash"):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(body.password, user["passwordHash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user["id"], user["email"])
    return TokenResponse(access_token=token, userId=user["id"], email=user["email"])
