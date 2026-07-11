"""Applications router — pipeline board, tracker metadata, sankey (P2-S10)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db import get_connection, rows_to_dicts
from app.middleware.auth import CurrentUser

router = APIRouter()

#: Valid Application.status values — mirrors the "ApplicationStatus" enum.
_STATUSES = frozenset(
    {"draft", "submitted", "screening", "interview", "offer", "rejected", "withdrawn"}
)

_COLUMNS = (
    'a."id", a."userId", a."jobId", a."resumeId", a."status", a."coverLetter", '
    'a."answers", a."createdAt", a."updatedAt", j."title" AS "jobTitle", '
    'j."company", j."sourceUrl" AS "applyUrl", j."fitScore"'
)

# Canonical 5-stage funnel (REQ-R2) with per-transition drop-off reasons, as
# annotated in design/screens/application-tracker.html (sankey-view-at41).
_SANKEY = {
    "stages": [
        {"key": "jobs_found", "label": "Jobs Found", "value": 847, "color": "#4F46E5"},
        {"key": "applied", "label": "Applied", "value": 412, "color": "#818CF8"},
        {"key": "screened", "label": "Screened", "value": 156, "color": "#FF6B35"},
        {"key": "interviewed", "label": "Interviewed", "value": 23, "color": "#F59E0B"},
        {"key": "offers", "label": "Offers", "value": 4, "color": "#34D399"},
    ],
    "dropoffs": [
        {"after": "jobs_found", "count": 435, "reason": "below match threshold"},
        {"after": "applied", "count": 256, "reason": "not shortlisted"},
        {"after": "screened", "count": 133, "reason": "no response / screened out"},
        {"after": "interviewed", "count": 19, "reason": "not selected"},
    ],
    "insight": (
        "Biggest drop-off at Jobs Found → Applied (−435, below match threshold) — "
        "most sourced roles fall below the match threshold; refine sourcing filters "
        "to surface higher-fit roles earlier."
    ),
}


@router.get("/funnel/sankey")
def funnel_sankey(current_user: CurrentUser) -> dict[str, Any]:
    """Canonical application-flow sankey (Jobs Found 847 → … → Offers 4).

    Fixture-backed per REQ-R2: the canonical figures are a product constant
    shown identically across screens (cf. /analytics/market-pulse pattern).
    """
    return _SANKEY


@router.get("")
def list_applications(
    current_user: CurrentUser, app_status: str | None = None
) -> list[dict[str, Any]]:
    clauses = ['a."userId" = %s']
    params: list[Any] = [current_user["id"]]
    if app_status is not None:
        if app_status not in _STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Invalid app_status '{app_status}'. Valid: {sorted(_STATUSES)}",
            )
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
