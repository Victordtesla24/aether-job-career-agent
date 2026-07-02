"""Jobs router (P2-S01 placeholder — fleshed out in P2-S02)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.middleware.auth import CurrentUser

router = APIRouter()


@router.get("")
def list_jobs(current_user: CurrentUser) -> list[dict[str, Any]]:
    """List the authenticated user's discovered jobs."""
    return []
