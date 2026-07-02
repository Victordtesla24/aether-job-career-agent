"""Applications router — read access for the pipeline board (P2-S10)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.db import get_connection, rows_to_dicts
from app.middleware.auth import CurrentUser

router = APIRouter()

_COLUMNS = (
    'a."id", a."userId", a."jobId", a."resumeId", a."status", a."coverLetter", '
    'a."createdAt", a."updatedAt", j."title" AS "jobTitle", j."company"'
)


@router.get("")
def list_applications(
    current_user: CurrentUser, app_status: str | None = None
) -> list[dict[str, Any]]:
    clauses = ['a."userId" = %s']
    params: list[Any] = [current_user["id"]]
    if app_status is not None:
        clauses.append('a."status" = %s::"ApplicationStatus"')
        params.append(app_status)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "Application" a '
                'JOIN "Job" j ON j."id" = a."jobId" '
                f'WHERE {" AND ".join(clauses)} ORDER BY a."createdAt" DESC',
                params,
            )
            return rows_to_dicts(cur)


@router.get("/{application_id}")
def get_application(application_id: str, current_user: CurrentUser) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "Application" a '
                'JOIN "Job" j ON j."id" = a."jobId" '
                'WHERE a."id" = %s AND a."userId" = %s',
                (application_id, current_user["id"]),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return rows[0]
