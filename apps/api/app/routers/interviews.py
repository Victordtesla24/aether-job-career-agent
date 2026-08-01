"""Interviews router — InterviewSchedule CRUD (P3) + real Google Calendar write.

Manages interview scheduling, tracking, and lifecycle tied to applications.
The ``InterviewSchedule`` table is created idempotently on first router use.

W-CAL (ADR-CALENDAR-V4): scheduling an interview now also writes a REAL Google
Calendar event carrying the role, the company, the time and a link back to the
job. Three rules govern that write, and they are the point of the feature:

* The interview row is created either way. The calendar is an ADDITION to the
  user's record of the interview, not a precondition for it — a user who never
  connected Google must still be able to track interviews.
* The outcome is REPORTED, never assumed. Every response carries a ``calendar``
  block whose ``status`` is one of ``created`` / ``not_connected`` /
  ``scope_missing`` / ``needs_reauth`` / ``failed``, with the actionable message
  that goes with it. An ``event_id`` is present ONLY when Google returned one.
* Nothing is ever claimed that did not happen. There is no code path here that
  reports a created event without Google's own event id behind it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db import get_connection, new_id, rows_to_dicts
from app.middleware.auth import CurrentUser

router = APIRouter()

logger = logging.getLogger(__name__)

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

    W-CAL: the additive calendar columns are migrated by
    :func:`_ensure_interview_calendar_columns`, which is invoked AFTER this
    function's connection is released (it checks out its own) — on both the
    fast path and the create path, so an existing table still gets them.
    """
    global _interview_tables_ready
    if _interview_tables_ready:
        return
    already_exists = False
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_name = 'InterviewSchedule'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            row = cur.fetchone()
            already_exists = bool(row and row[0] == 1)
        if not already_exists:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240713,))
                cur.execute(
                    """
                CREATE TABLE IF NOT EXISTS "InterviewSchedule" (
                    "id"            text PRIMARY KEY,
                    "userId"        text NOT NULL,
                    "applicationId" text NOT NULL,
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
    _ensure_interview_calendar_columns()


_interview_calendar_columns_ready = False


def _ensure_interview_calendar_columns() -> None:
    """Additive, idempotent DDL for the W-CAL calendar-linkage columns.

    Strictly ``ADD COLUMN IF NOT EXISTS`` (ADR-TR-1 lazy idempotent DDL): the
    previous release, which never selects these columns, keeps working against
    the migrated table, so this is a safe forward-only change. They exist so the
    interview ROW itself carries the proof of what happened on the calendar —
    a response-only field would leave "was this on my calendar?" unanswerable
    on the next page load.
    """
    global _interview_calendar_columns_ready
    if _interview_calendar_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240719,))
            cur.execute(
                'ALTER TABLE "InterviewSchedule"'
                ' ADD COLUMN IF NOT EXISTS "calendarEventId" text'
            )
            cur.execute(
                'ALTER TABLE "InterviewSchedule"'
                ' ADD COLUMN IF NOT EXISTS "calendarHtmlLink" text'
            )
            cur.execute(
                'ALTER TABLE "InterviewSchedule"'
                ' ADD COLUMN IF NOT EXISTS "calendarSyncStatus" text'
            )
            cur.execute(
                'ALTER TABLE "InterviewSchedule"'
                ' ADD COLUMN IF NOT EXISTS "calendarSyncedAt" timestamptz'
            )
        conn.commit()
    _interview_calendar_columns_ready = True


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class InterviewCreate(BaseModel):
    """Payload for scheduling a new interview."""

    # Required: the DB column (InterviewSchedule.applicationId) is NOT NULL.
    # There is no documented "interview without an application" flow (Interview
    # Center itself is deferred, D-0032) so the contract is enforced here —
    # a missing value must 422, never reach the INSERT and crash as a 500.
    application_id: str = Field(min_length=1)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INTERVIEW_COLUMNS = (
    'i."id", i."userId", i."applicationId", i."type", i."status",'
    ' i."scheduledAt", i."durationMinutes", i."location", i."meetingLink",'
    ' i."notes", i."contactName", i."contactEmail", i."createdAt", i."updatedAt",'
    ' i."calendarEventId", i."calendarHtmlLink", i."calendarSyncStatus",'
    ' i."calendarSyncedAt"'
)


def _row_to_response(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise raw DB column names into the interview wire shape."""
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
        # W-CAL: the stored proof of what really happened on Google Calendar.
        # ``calendar_event_id`` is non-null ONLY when Google returned an id.
        "calendar_event_id": row.get("calendarEventId"),
        "calendar_html_link": row.get("calendarHtmlLink"),
        "calendar_sync_status": row.get("calendarSyncStatus"),
        "calendar_synced_at": row.get("calendarSyncedAt"),
    }


# ---------------------------------------------------------------------------
# W-CAL — Google Calendar event creation
# ---------------------------------------------------------------------------


def _job_context(application_id: str, user_id: str) -> dict[str, Any]:
    """Role, company and job URL behind an application (all real, or None)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT j."title", j."company", j."sourceUrl"'
                ' FROM "Application" a JOIN "Job" j ON j."id" = a."jobId"'
                ' WHERE a."id" = %s AND a."userId" = %s',
                (application_id, user_id),
            )
            row = cur.fetchone()
    if not row:
        return {"title": None, "company": None, "url": None}
    return {"title": row[0], "company": row[1], "url": row[2]}


def _event_summary(context: dict[str, Any], interview_type: str) -> str:
    """Event title built ONLY from recorded facts. Degrades to the interview
    type rather than inventing a role or a company name."""
    role = (context.get("title") or "").strip()
    company = (context.get("company") or "").strip()
    if role and company:
        return f"Interview — {role} @ {company}"
    if role:
        return f"Interview — {role}"
    if company:
        return f"Interview — {company}"
    return f"Interview ({interview_type})"


def _event_description(context: dict[str, Any], body: "InterviewCreate") -> str:
    lines = [f"{body.type.capitalize()} interview scheduled via Aether."]
    if context.get("company"):
        lines.append(f"Company: {context['company']}")
    if context.get("title"):
        lines.append(f"Role: {context['title']}")
    if body.contact_name or body.contact_email:
        contact = " ".join(
            part for part in (body.contact_name, body.contact_email) if part
        )
        lines.append(f"Contact: {contact}")
    if body.meeting_link:
        lines.append(f"Meeting link: {body.meeting_link}")
    if context.get("url"):
        lines.append(f"Job: {context['url']}")
    if body.notes:
        lines.append("")
        lines.append(body.notes)
    return "\n".join(lines)


def _write_calendar_event(
    user_id: str, body: "InterviewCreate", context: dict[str, Any]
) -> dict[str, Any]:
    """Attempt the real Calendar write and report EXACTLY what happened.

    Never raises into the request: an interview must still be recorded when the
    calendar leg fails. Never reports ``created`` without Google's own event
    id. The three grant failures keep their distinct, actionable copy so the
    user is told what to do rather than that "something went wrong".
    """
    from app.services.calendar_service import (
        STATUS_NEEDS_REAUTH,
        STATUS_NOT_CONNECTED,
        STATUS_SCOPE_MISSING,
        CalendarAuthError,
        CalendarError,
        CalendarNotConnectedError,
        CalendarScopeNotGrantedError,
        GoogleCalendarService,
    )

    def _refused(status_key: str, message: str) -> dict[str, Any]:
        return {
            "status": status_key,
            "event_id": None,
            "html_link": None,
            "message": message,
        }

    try:
        created = GoogleCalendarService(user_id).create_event(
            summary=_event_summary(context, body.type),
            start=body.scheduled_at,
            duration_minutes=body.duration_minutes,
            description=_event_description(context, body),
            location=body.location or body.meeting_link,
        )
    except CalendarNotConnectedError as exc:
        return _refused(STATUS_NOT_CONNECTED, str(exc))
    except CalendarScopeNotGrantedError as exc:
        return _refused(STATUS_SCOPE_MISSING, str(exc))
    except CalendarAuthError as exc:
        return _refused(STATUS_NEEDS_REAUTH, str(exc))
    except CalendarError as exc:
        logger.warning(
            "Calendar event write failed for user=%s: %s", user_id, exc
        )
        return _refused("failed", str(exc))

    event_id = created.get("id")
    if not event_id:
        # Google answered without an id — we cannot prove an event exists, so we
        # do not claim one does.
        return _refused(
            "failed",
            "Google Calendar accepted the request but returned no event id, so "
            "the event could not be confirmed. Check your calendar before "
            "relying on it.",
        )
    return {
        "status": "created",
        "event_id": event_id,
        "html_link": created.get("htmlLink"),
        "message": "Added to your Google Calendar.",
    }


def _persist_calendar_result(interview_id: str, result: dict[str, Any]) -> None:
    """Record the calendar outcome on the interview row itself."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "InterviewSchedule" SET "calendarEventId" = %s,'
                ' "calendarHtmlLink" = %s, "calendarSyncStatus" = %s,'
                ' "calendarSyncedAt" = %s, "updatedAt" = now() WHERE "id" = %s',
                (
                    result.get("event_id"),
                    result.get("html_link"),
                    result.get("status"),
                    datetime.now(timezone.utc) if result.get("event_id") else None,
                    interview_id,
                ),
            )
        conn.commit()


def _verify_application_ref(application_id: str, user_id: str) -> None:
    """Ensure the interview references an ``Application`` owned by the user.

    MV-interview-center-004: without this referential check ``POST /interviews``
    accepted any arbitrary string as ``application_id`` and created an orphaned
    row (201). An interview must point at a real application the caller owns; a
    missing or foreign reference is a 404 (scoping by ``userId`` also avoids
    leaking whether another user's application exists).
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT 1 FROM "Application" WHERE "id" = %s AND "userId" = %s',
                (application_id, user_id),
            )
            found = cur.fetchone()
    if not found:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Referenced application not found",
        )


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

    # Referential integrity: the interview must attach to a real application the
    # caller owns (MV-interview-center-004). Rejects orphan-row creation.
    _verify_application_ref(body.application_id, uid)

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

    # W-CAL: the real Google Calendar write. It runs AFTER the row exists so a
    # calendar problem can never lose the interview the user just scheduled,
    # and its outcome is reported verbatim — an honest refusal here is a
    # first-class result, not an error to be swallowed.
    calendar_result = _write_calendar_event(uid, body, _job_context(body.application_id, uid))
    _persist_calendar_result(interview_id, calendar_result)

    row = _get_or_404(interview_id, uid)
    return {**_row_to_response(row), "calendar": calendar_result}


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
