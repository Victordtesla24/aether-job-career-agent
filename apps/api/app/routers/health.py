"""Health check router (P1-S09).

Exposes an unauthenticated ``GET /health`` liveness probe returning the
canonical payload consumed by load balancers, uptime checks, and CI smoke
tests: ``{"status": "ok", "version": "<API_VERSION>"}``.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import SettingsDep

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Shape of the /health payload."""

    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
def health(settings: SettingsDep) -> HealthResponse:
    """Liveness probe. Always returns ``ok`` with the current API version."""
    return HealthResponse(status="ok", version=settings.api_version)
