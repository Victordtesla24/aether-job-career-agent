"""Health check utilities for the Aether API.

Kept intentionally tiny — this exists to anchor the test harness (P1-S00).
"""
from __future__ import annotations

from typing import TypedDict


class HealthStatus(TypedDict):
    status: str
    service: str
    version: str


def get_health(version: str = "0.0.0") -> HealthStatus:
    """Return a simple health payload for the API service."""
    return {"status": "ok", "service": "api", "version": version}
