"""Applications router — read access for the pipeline board (P2-S10)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db import get_connection, rows_to_dicts
from app.middleware.auth import CurrentUser

router = APIRouter()

_COLUMNS = (
    'a."id", a."userId", a."jobId", a."resumeId", a."status", a."coverLetter", '
    'a."createdAt", a."updatedAt", j."title" AS "jobTitle", j."company", '
    'j."sourceUrl" AS "applyUrl"'
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


class SubmitRequest(BaseModel):
    """Payload for marking an application as submitted on the company site."""

    applied_url: str | None = Field(default=None, max_length=2000)


@router.post("/{application_id}/submit")
def submit_application(
    application_id: str, body: SubmitRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Mark a draft application as submitted, recording the real apply URL.

    The user applies on the company site themselves (human-in-the-loop);
    this endpoint only tracks that it happened. Idempotent: re-submitting an
    already-submitted application is a no-op that returns the current row.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status", "answers" FROM "Application" '
                'WHERE "id" = %s AND "userId" = %s',
                (application_id, current_user["id"]),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
            if row[0] == "draft":
                cur.execute(
                    """
                    UPDATE "Application"
                    SET "status" = 'submitted'::"ApplicationStatus",
                        "answers" = COALESCE("answers", '{}'::jsonb) || %s::jsonb,
                        "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    """,
                    (
                        json.dumps(
                            {
                                "appliedUrl": body.applied_url,
                                "submittedAt": datetime.now(UTC).isoformat(),
                            }
                        ),
                        application_id,
                        current_user["id"],
                    ),
                )
                conn.commit()
    return get_application(application_id, current_user)
