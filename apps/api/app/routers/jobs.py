"""Job + Scout endpoints (P2-S02).

Exposes the authenticated job listing/detail, save-toggle and soft-delete, plus
the Scout trigger that discovers and persists jobs across the source adapters.

The Scout run executes synchronously in-process (no task broker is provisioned
in this environment) but still returns **202 Accepted** to preserve the async
contract the clients and later slices depend on. Adapter selection is injected
via :func:`get_scout_adapters` so tests can bind fixture-backed adapters.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2.extensions import connection as PgConnection

from app.db import get_db
from app.middleware.auth import CurrentUser, get_current_user
from app.repositories.job import Job, JobRepository
from app.schemas.jobs import JobOut, ScoutRunRequest, ScoutRunResponse
from app.services.discovery.adapter_registry import build_adapters
from app.services.discovery.base_adapter import BaseAdapter
from app.services.discovery.scout import run_scout

router = APIRouter(tags=["jobs"])


def get_scout_adapters() -> list[BaseAdapter]:
    """Provide the live source adapters the Scout agent queries.

    Overridden in tests to return fixture-backed adapters (see
    ``tests/conftest.py``) so no live HTTP occurs.
    """
    return build_adapters()


def _serialize(job: Job) -> JobOut:
    """Map a :class:`Job` (snake_case) to the camelCase API model."""
    return JobOut(
        id=job.id,
        title=job.title,
        company=job.company,
        location=job.location,
        remote=job.remote,
        description=job.description,
        requirements=job.requirements,
        source=job.source,
        sourceUrl=job.source_url,
        status=job.status,
        fitScore=job.fit_score,
        atsScore=job.ats_score,
        saved=job.saved,
        createdAt=job.created_at.isoformat(),
    )


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    status: Optional[str] = None,
    source: Optional[str] = None,
    saved: Optional[bool] = None,
    current_user: CurrentUser = Depends(get_current_user),
    conn: PgConnection = Depends(get_db),
) -> list[JobOut]:
    """List the authenticated user's jobs with optional filters."""
    jobs = JobRepository(conn).list_by_user(
        current_user.id, status=status, source=source, saved=saved
    )
    return [_serialize(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    conn: PgConnection = Depends(get_db),
) -> JobOut:
    """Return a single job owned by the authenticated user."""
    job = JobRepository(conn).get_by_id(job_id, current_user.id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _serialize(job)


@router.post("/jobs/{job_id}/save", response_model=JobOut)
def toggle_save_job(
    job_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    conn: PgConnection = Depends(get_db),
) -> JobOut:
    """Toggle the ``saved`` flag on a job."""
    repo = JobRepository(conn)
    job = repo.get_by_id(job_id, current_user.id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    updated = repo.set_saved(job_id, current_user.id, not job.saved)
    return _serialize(updated)


@router.delete("/jobs/{job_id}", response_model=JobOut)
def archive_job(
    job_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    conn: PgConnection = Depends(get_db),
) -> JobOut:
    """Soft-delete a job by setting its status to ``archived``."""
    repo = JobRepository(conn)
    job = repo.get_by_id(job_id, current_user.id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    archived = repo.update_status(job_id, "archived")
    return _serialize(archived)


@router.post(
    "/agents/scout/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ScoutRunResponse,
)
def run_scout_agent(
    payload: ScoutRunRequest,
    current_user: CurrentUser = Depends(get_current_user),
    conn: PgConnection = Depends(get_db),
    adapters: list[BaseAdapter] = Depends(get_scout_adapters),
) -> ScoutRunResponse:
    """Discover and persist jobs for the authenticated user (HTTP 202)."""
    result = run_scout(
        conn,
        user_id=current_user.id,
        query=payload.query,
        location=payload.location,
        adapters=adapters,
    )
    return ScoutRunResponse(
        discovered=result.discovered,
        persisted=result.persisted,
        errors=result.errors,
    )
