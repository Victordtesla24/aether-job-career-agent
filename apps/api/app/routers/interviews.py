"""Interviews router — InterviewSchedule CRUD (P3).

Manages interview scheduling, tracking, and lifecycle tied to applications.
The ``InterviewSchedule`` table is created idempotently on first router use.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db import get_connection, new_id, rows_to_dicts
from app.middleware.auth import CurrentUser

router = APIRouter()

#: Valid InterviewSchedule.type values.
_INTERVIEW_TYPES = frozenset({"phone", "video", "onsite", "technical", "panel", "hr"})

#: Valid InterviewSchedule.status values.
_INTERVIEW_STATUSES = frozenset(
    {"scheduled", "confirmed", "completed", "cancelled", "rescheduled", "no_show"}
)

# ---------------------------------------------------------------------------
# Table bootstrap
# ---------------------------------------------------------------------------

_interview_tables_ready = False


def _ensure_interview_tables() -> None:
    """Idempotently create the ``InterviewSchedule`` table on first use.

    Survives concurrent callers via a transaction-scoped advisory lock,
    mirroring the pattern used in ``app.db.ensure_user_profile_columns``.
    """
    global _interview_tables_ready
    if _interview_tables_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_name = 'InterviewSchedule'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _interview_tables_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240713,))
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS "InterviewSchedule" (
                    "id"            text PRIMARY KEY,
                    "userId"        text NOT NULL,
                    "applicationId" text,
                    "type"          text NOT NULL DEFAULT 'video',
                    "status"        text NOT NULL DEFAULT 'scheduled',
                    "scheduledAt"   timestamptz NOT NULL,
                    "durationMinutes" integer DEFAULT 60,
                    "location"      text,
                    "meetingLink"   text,
                    "notes"         text,
                    "contactName"   text,
                    "contactEmail"  text,
                    "createdAt"     timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"     timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_interview_userId"'
                ' ON "InterviewSchedule" ("userId")'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_interview_applicationId"'
                ' ON "InterviewSchedule" ("applicationId")'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_interview_scheduledAt"'
                ' ON "InterviewSchedule" ("scheduledAt")'
            )
        conn.commit()
    _interview_tables_ready = True


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class InterviewCreate(BaseModel):
    """Payload for scheduling a new interview."""

    application_id: str | None = Field(default=None)
    type: str = Field(default="video")
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=15, le=480)
    location: str | None = Field(default=None, max_length=500)
    meeting_link: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=5000)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)


class InterviewUpdate(BaseModel):
    """Payload for updating an existing interview."""

    type: str | None = None
    status: str | None = None
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=480)
    location: str | None = Field(default=None, max_length=500)
    meeting_link: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=5000)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)


class InterviewResponse(BaseModel):
    """Canonical interview response shape."""

    id: str
    user_id: str
    application_id: str | None
    type: str
    status: str
    scheduled_at: datetime
    duration_minutes: int
    location: str | None
    meeting_link: str | None
    notes: str | None
    contact_name: str | None
    contact_email: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INTERVIEW_COLUMNS = (
    'i."id", i."userId", i."applicationId", i."type", i."status",'
    ' i."scheduledAt", i."durationMinutes", i."location", i."meetingLink",'
    ' i."notes", i."contactName", i."contactEmail", i."createdAt", i."updatedAt"'
)


def _row_to_response(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise raw DB column names into the InterviewResponse shape."""
    return {
        "id": row["id"],
        "user_id": row["userId"],
        "application_id": row["applicationId"],
        "type": row["type"],
        "status": row["status"],
        "scheduled_at": row["scheduledAt"],
        "duration_minutes": row["durationMinutes"],
        "location": row["location"],
        "meeting_link": row["meetingLink"],
        "notes": row["notes"],
        "contact_name": row["contactName"],
        "contact_email": row["contactEmail"],
        "created_at": row["createdAt"],
        "updated_at": row["updatedAt"],
    }


def _get_or_404(
    interview_id: str, user_id: str
) -> dict[str, Any]:
    """Fetch a single interview row scoped to the user, or raise 404."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_INTERVIEW_COLUMNS} FROM "InterviewSchedule" i'
                ' WHERE i."id" = %s AND i."userId" = %s',
                (interview_id, user_id),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Interview not found")
    return rows[0]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_interviews(
    current_user: CurrentUser,
    application_id: str | None = None,
    app_status: str | None = None,
    upcoming_only: bool = False,
) -> list[dict[str, Any]]:
    """List interviews for the current user.

    Filters: ``?application_id=``, ``?app_status=scheduled|completed|…``,
    ``?upcoming_only=true``.
    """
    _ensure_interview_tables()
    uid = current_user["id"]
    clauses = ['i."userId" = %s']
    params: list[Any] = [uid]

    if application_id is not None:
        clauses.append('i."applicationId" = %s')
        params.append(application_id)
    if app_status is not None:
        if app_status not in _INTERVIEW_STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Invalid status '{app_status}'. Valid: {sorted(_INTERVIEW_STATUSES)}",
            )
        clauses.append('i."status" = %s')
        params.append(app_status)
    if upcoming_only:
        clauses.append('i."scheduledAt" >= now()')
        clauses.append("i.\"status\" NOT IN ('cancelled', 'no_show')")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_INTERVIEW_COLUMNS} FROM "InterviewSchedule" i'
                f' WHERE {" AND ".join(clauses)}'
                ' ORDER BY i."scheduledAt" ASC',
                params,
            )
            rows = rows_to_dicts(cur)
    return [_row_to_response(r) for r in rows]


@router.get("/{interview_id}")
def get_interview(
    interview_id: str, current_user: CurrentUser
) -> dict[str, Any]:
    """Get a single interview by id."""
    _ensure_interview_tables()
    row = _get_or_404(interview_id, current_user["id"])
    return _row_to_response(row)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_interview(
    body: InterviewCreate, current_user: CurrentUser
) -> dict[str, Any]:
    """Schedule a new interview."""
    _ensure_interview_tables()
    uid = current_user["id"]

    if body.type not in _INTERVIEW_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid type '{body.type}'. Valid: {sorted(_INTERVIEW_TYPES)}",
        )

    interview_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "InterviewSchedule" (
                    "id", "userId", "applicationId", "type", "status",
                    "scheduledAt", "durationMinutes", "location",
                    "meetingLink", "notes", "contactName", "contactEmail"
                ) VALUES (
                    %s, %s, %s, %s, 'scheduled',
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    interview_id,
                    uid,
                    body.application_id,
                    body.type,
                    body.scheduled_at,
                    body.duration_minutes,
                    body.location,
                    body.meeting_link,
                    body.notes,
                    body.contact_name,
                    body.contact_email,
                ),
            )
        conn.commit()
    row = _get_or_404(interview_id, uid)
    return _row_to_response(row)


@router.patch("/{interview_id}")
def update_interview(
    interview_id: str, body: InterviewUpdate, current_user: CurrentUser
) -> dict[str, Any]:
    """Update interview fields. Only supplied fields are changed."""
    _ensure_interview_tables()
    uid = current_user["id"]

    # Verify ownership first.
    _get_or_404(interview_id, uid)

    if body.type is not None and body.type not in _INTERVIEW_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid type '{body.type}'. Valid: {sorted(_INTERVIEW_TYPES)}",
        )
    if body.status is not None and body.status not in _INTERVIEW_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid status '{body.status}'. Valid: {sorted(_INTERVIEW_STATUSES)}",
        )

    sets: list[str] = []
    params: list[Any] = []

    if body.type is not None:
        sets.append('"type" = %s')
        params.append(body.type)
    if body.status is not None:
        sets.append('"status" = %s')
        params.append(body.status)
    if body.scheduled_at is not None:
        sets.append('"scheduledAt" = %s')
        params.append(body.scheduled_at)
    if body.duration_minutes is not None:
        sets.append('"durationMinutes" = %s')
        params.append(body.duration_minutes)
    if body.location is not None:
        sets.append('"location" = %s')
        params.append(body.location)
    if body.meeting_link is not None:
        sets.append('"meetingLink" = %s')
        params.append(body.meeting_link)
    if body.notes is not None:
        sets.append('"notes" = %s')
        params.append(body.notes)
    if body.contact_name is not None:
        sets.append('"contactName" = %s')
        params.append(body.contact_name)
    if body.contact_email is not None:
        sets.append('"contactEmail" = %s')
        params.append(body.contact_email)

    if sets:
        sets.append('"updatedAt" = now()')
        params.extend([interview_id, uid])
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'UPDATE "InterviewSchedule" SET {", ".join(sets)}'
                    ' WHERE "id" = %s AND "userId" = %s',
                    params,
                )
            conn.commit()

    row = _get_or_404(interview_id, uid)
    return _row_to_response(row)


@router.delete("/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interview(interview_id: str, current_user: CurrentUser) -> None:
    """Delete an interview."""
    _ensure_interview_tables()
    uid = current_user["id"]
    _get_or_404(interview_id, uid)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM "InterviewSchedule" WHERE "id" = %s AND "userId" = %s',
                (interview_id, uid),
            )
        conn.commit()


@router.post("/{interview_id}/complete")
def complete_interview(
    interview_id: str, current_user: CurrentUser
) -> dict[str, Any]:
    """Mark an interview as completed."""
    _ensure_interview_tables()
    uid = current_user["id"]
    _get_or_404(interview_id, uid)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "InterviewSchedule" SET "status" = %s, "updatedAt" = now()'
                ' WHERE "id" = %s AND "userId" = %s',
                ("completed", interview_id, uid),
            )
        conn.commit()
    row = _get_or_404(interview_id, uid)
    return _row_to_response(row)


@router.post("/{interview_id}/cancel")
def cancel_interview(
    interview_id: str, current_user: CurrentUser
) -> dict[str, Any]:
    """Cancel an interview."""
    _ensure_interview_tables()
    uid = current_user["id"]
    _get_or_404(interview_id, uid)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "InterviewSchedule" SET "status" = %s, "updatedAt" = now()'
                ' WHERE "id" = %s AND "userId" = %s',
                ("cancelled", interview_id, uid),
            )
        conn.commit()
    row = _get_or_404(interview_id, uid)
    return _row_to_response(row)
