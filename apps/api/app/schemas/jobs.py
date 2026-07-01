"""Request/response models for the job + Scout endpoints (P2-S02)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ScoutRunRequest(BaseModel):
    """Payload for ``POST /agents/scout/run``."""

    query: str = Field(min_length=1, description="Role/keywords to search for.")
    location: str = Field(min_length=1, description="Location to search within.")


class ScoutRunResponse(BaseModel):
    """Acknowledgement returned when a Scout run is accepted (HTTP 202)."""

    accepted: bool = True
    discovered: int
    persisted: int
    errors: list[str] = []


class JobOut(BaseModel):
    """Serialized job posting (camelCase, mirroring the ``Job`` row/TS type)."""

    id: str
    title: str
    company: str
    location: Optional[str] = None
    remote: bool
    description: str
    requirements: list[str] = []
    source: str
    sourceUrl: Optional[str] = None
    status: str
    fitScore: Optional[float] = None
    atsScore: Optional[float] = None
    saved: bool
    createdAt: str
