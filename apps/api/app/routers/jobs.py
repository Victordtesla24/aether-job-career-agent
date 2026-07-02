"""Jobs router — list/detail/save/archive for the authenticated user (P2-S02)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.middleware.auth import CurrentUser
from app.repositories.job import VALID_STATUSES, JobRepository

router = APIRouter()


def _public(job: dict[str, Any]) -> dict[str, Any]:
    """Job rows are already safe to expose; kept as a single choke-point."""
    return job


@router.get("")
def list_jobs(
    current_user: CurrentUser,
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    saved: bool | None = Query(default=None),
    sort: str = Query(default="createdAt"),
) -> list[dict[str, Any]]:
    """List the authenticated user's discovered jobs, with optional filters."""
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status '{status}'")
    jobs = JobRepository().list_by_user(
        current_user["id"], status=status, source=source, saved=saved, sort=sort
    )
    return [_public(job) for job in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, current_user: CurrentUser) -> dict[str, Any]:
    job = JobRepository().get_by_id(job_id, current_user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _public(job)


@router.post("/{job_id}/save")
def toggle_save(job_id: str, current_user: CurrentUser) -> dict[str, Any]:
    job = JobRepository().toggle_saved(job_id, current_user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _public(job)


@router.delete("/{job_id}")
def archive_job(job_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Soft delete: jobs are archived, never destroyed."""
    repository = JobRepository()
    if repository.get_by_id(job_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job = repository.update_status(job_id, "archived")
    assert job is not None  # existence checked above
    return _public(job)
