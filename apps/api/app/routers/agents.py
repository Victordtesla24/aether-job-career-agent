"""Agents router — trigger agent runs (P2-S02)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.agents.scout_agent import ScoutAgent
from app.middleware.auth import CurrentUser

router = APIRouter()


class ScoutRunRequest(BaseModel):
    query: str = Field(min_length=1)
    location: str = Field(min_length=1)


@router.post("/scout/run", status_code=status.HTTP_202_ACCEPTED)
def run_scout(body: ScoutRunRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Kick off a scout discovery run for the authenticated user.

    Runs synchronously for now (fixture-mode adapters are fast); the 202
    contract lets this move to a background queue without a client change.
    """
    result = ScoutAgent().run(current_user["id"], body.query, body.location)
    return {"status": "accepted", "persisted": result.persisted, "errors": result.errors}
