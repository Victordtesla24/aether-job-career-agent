"""Turn evidenced interview invites into InterviewSchedule + Application.status.

Analytics ``interview_conversion_rate`` counts Application rows whose status
is ``interview`` or ``offer``. An inbound calendar invite that never updates
that status leaves conversion stale even when the candidate has a real
interview on the calendar.

This module is the single ingest path:

* It never invents an application. No match → no InterviewSchedule row.
* It never downgrades offer/rejected/withdrawn.
* It is idempotent on ``calendarEventId`` when one is supplied.
* Matching is evidence-grounded: company, role title, or sender domain vs
  the job's company name must appear in the invite.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Any, Optional

from app.db import get_connection, new_id, rows_to_dicts
from app.services.career_email_filter import classify_career_email

logger = logging.getLogger(__name__)

_PROMOTE_FROM = frozenset({"submitted", "screening"})
_ALREADY_INTERVIEW = frozenset({"interview", "offer"})

#: Inbox polling is 30s; do not list Google Calendar on every detail fetch or
#: overlapping poll. Agent cron still calls ingest directly after sync.
_CAL_INGEST_TTL_SECONDS = 30
_cal_ingest_at: dict[str, float] = {}
_cal_ingest_lock = threading.Lock()

_INTERVIEW_EVENT = re.compile(
    r"\b(interview|phone\s*screen|screening\s+call|hiring\s+manager|"
    r"talent\s+acquisition|recruiter)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IngestResult:
    promoted: bool
    application_id: Optional[str] = None
    interview_id: Optional[str] = None
    reason: str = ""


def is_career_calendar_event(event: dict[str, Any]) -> bool:
    """True when a Google Calendar event is an evidenced career interview."""
    organizer = event.get("organizer") or {}
    verdict = classify_career_email(
        subject=str(event.get("summary") or ""),
        sender=str(organizer.get("displayName") or ""),
        sender_email=str(organizer.get("email") or ""),
        body=str(event.get("description") or ""),
        has_calendar_invite=True,
    )
    if not verdict.keep:
        return False
    hay = " ".join(
        str(event.get(k) or "")
        for k in ("summary", "description", "location")
    )
    return bool(_INTERVIEW_EVENT.search(hay) or verdict.is_interview_invite)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _sender_domain(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1]


def _company_matches(company: str, hay: str, domain: str) -> bool:
    company_n = _norm(company)
    if len(company_n) < 3:
        return False
    if company_n in hay:
        return True
    slug = re.sub(r"[^a-z0-9]", "", company_n)
    if len(slug) >= 3 and (domain == f"{slug}.com" or domain.startswith(slug + ".")):
        return True
    return False


def _find_matching_application(
    user_id: str,
    *,
    subject: str,
    sender_email: str,
    sender_name: str,
    body: str,
) -> dict[str, Any] | None:
    hay = _norm(" ".join((subject, sender_name, sender_email, body)))
    domain = _sender_domain(sender_email)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.status, j.company, j.title
                FROM "Application" a
                JOIN "Job" j ON j.id = a."jobId"
                WHERE a."userId" = %s
                  AND a.status IN ('submitted', 'screening', 'interview', 'offer')
                ORDER BY a."updatedAt" DESC
                """,
                (user_id,),
            )
            rows = rows_to_dicts(cur)
    for row in rows:
        company = str(row.get("company") or "")
        title = str(row.get("title") or "")
        if _company_matches(company, hay, domain):
            return row
        title_n = _norm(title)
        if len(title_n) >= 8 and title_n in hay:
            return row
    return None


def _existing_by_calendar_event(user_id: str, calendar_event_id: str) -> dict[str, Any] | None:
    if not calendar_event_id:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id, "applicationId" FROM "InterviewSchedule"'
                ' WHERE "userId" = %s AND "calendarEventId" = %s',
                (user_id, calendar_event_id),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def promote_application_to_interview(user_id: str, application_id: str) -> bool:
    """Set Application.status to interview when the current status allows it.

    Returns True when a row was actually updated. Never overwrites offer /
    rejected / withdrawn / draft.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET status = %s::"ApplicationStatus",'
                ' "updatedAt" = now()'
                ' WHERE id = %s AND "userId" = %s AND status::text = ANY(%s)',
                ("interview", application_id, user_id, list(_PROMOTE_FROM)),
            )
            updated = cur.rowcount
        conn.commit()
    return updated > 0


def ingest_interview_invite(
    user_id: str,
    *,
    subject: str,
    sender_name: str = "",
    sender_email: str = "",
    body: str = "",
    scheduled_at: datetime | None = None,
    calendar_event_id: str | None = None,
    meeting_link: str | None = None,
    duration_minutes: int = 60,
) -> IngestResult:
    """Create/reuse an InterviewSchedule and promote the matched application."""
    from app.routers.interviews import _ensure_interview_tables

    _ensure_interview_tables()

    existing = _existing_by_calendar_event(user_id, calendar_event_id or "")
    if existing:
        promote_application_to_interview(user_id, existing["applicationId"])
        return IngestResult(
            promoted=True,
            application_id=existing["applicationId"],
            interview_id=existing["id"],
            reason="already ingested",
        )

    matched = _find_matching_application(
        user_id,
        subject=subject,
        sender_email=sender_email,
        sender_name=sender_name,
        body=body,
    )
    if matched is None:
        return IngestResult(
            promoted=False,
            reason="no matching submitted/screening application",
        )

    app_id = str(matched["id"])
    when = scheduled_at or datetime.now(timezone.utc)
    interview_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "InterviewSchedule" (
                    "id", "userId", "applicationId", "type", "status",
                    "scheduledAt", "durationMinutes", "meetingLink",
                    "notes", "contactName", "contactEmail",
                    "calendarEventId", "calendarSyncStatus", "calendarSyncedAt"
                ) VALUES (
                    %s, %s, %s, 'video', 'scheduled',
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, now()
                )
                """,
                (
                    interview_id,
                    user_id,
                    app_id,
                    when,
                    duration_minutes,
                    meeting_link,
                    subject,
                    sender_name or None,
                    sender_email or None,
                    calendar_event_id,
                    "ingested" if calendar_event_id else None,
                ),
            )
        conn.commit()

    promoted = promote_application_to_interview(user_id, app_id)
    if not promoted and str(matched.get("status") or "") in _ALREADY_INTERVIEW:
        promoted = True
    return IngestResult(
        promoted=promoted,
        application_id=app_id,
        interview_id=interview_id,
        reason="matched application",
    )


def ingest_calendar_events(user_id: str, events: list[dict[str, Any]]) -> int:
    """Ingest a batch of Google Calendar events. Returns rows newly created."""
    created = 0
    for event in events:
        if not is_career_calendar_event(event):
            continue
        start = _event_start(event)
        organizer = event.get("organizer") or {}
        result = ingest_interview_invite(
            user_id,
            subject=str(event.get("summary") or "Interview"),
            sender_name=str(organizer.get("displayName") or ""),
            sender_email=str(organizer.get("email") or ""),
            body=str(event.get("description") or ""),
            scheduled_at=start,
            calendar_event_id=str(event.get("id") or "") or None,
            meeting_link=str(event.get("hangoutLink") or event.get("htmlLink") or "")
            or None,
        )
        if result.interview_id and result.reason == "matched application":
            created += 1
    return created


def ingest_inbound_for_user(
    user_id: str,
    threads: list[dict[str, Any]] | None = None,
    *,
    force_calendar: bool = False,
) -> None:
    """Best-effort calendar + Gmail interview ingest. Never raises to callers.

    Calendar listing is the load-bearing path for meeting invites that Gmail's
    Primary-tab window previously dropped. Thread ingest covers ICS / calendar
    notification mail that *did* land in EmailThread.
    """
    from app.services.calendar_service import (
        CalendarAuthError,
        CalendarError,
        CalendarNotConnectedError,
        CalendarScopeNotGrantedError,
        GoogleCalendarService,
    )
    from app.services.career_email_filter import classify_thread

    now_mono = time.monotonic()
    with _cal_ingest_lock:
        last = _cal_ingest_at.get(user_id, 0.0)
        run_calendar = force_calendar or (now_mono - last) >= _CAL_INGEST_TTL_SECONDS
        if run_calendar:
            _cal_ingest_at[user_id] = now_mono

    if run_calendar:
        try:
            now = datetime.now(timezone.utc)
            events = GoogleCalendarService(user_id).list_events(
                time_min=now - timedelta(days=7),
                time_max=now + timedelta(days=60),
            )
            ingest_calendar_events(user_id, events)
        except (
            CalendarNotConnectedError,
            CalendarScopeNotGrantedError,
            CalendarAuthError,
            CalendarError,
        ):
            pass
        except Exception:  # noqa: BLE001 — ingest must never 500 the inbox / agent
            logger.warning(
                "inbound calendar ingest failed for user=%s", user_id, exc_info=True
            )

    for t in threads or []:
        msgs = t.get("messages") or []
        latest = msgs[-1] if isinstance(msgs, list) and msgs else {}
        if not isinstance(latest, dict):
            latest = {}
        verdict = classify_thread(t, latest)
        if not verdict.is_interview_invite:
            continue
        stamp = t.get("lastMessageAt")
        if isinstance(stamp, datetime):
            scheduled = stamp
        else:
            raw = latest.get("createdAt") or t.get("createdAt")
            if isinstance(raw, datetime):
                scheduled = raw
            else:
                scheduled = _event_start({"start": {"dateTime": raw}})
        try:
            ingest_interview_invite(
                user_id,
                subject=str(t.get("subject") or ""),
                sender_name=str(latest.get("from") or ""),
                sender_email=str(latest.get("fromEmail") or ""),
                body=str(latest.get("body") or ""),
                scheduled_at=scheduled,
                calendar_event_id=(
                    f"gmail:{t.get('gmailThreadId')}" if t.get("gmailThreadId") else None
                ),
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "interview ingest failed for thread=%s user=%s",
                t.get("id"),
                user_id,
                exc_info=True,
            )


def _event_start(event: dict[str, Any]) -> datetime | None:
    start = event.get("start") or {}
    raw = start.get("dateTime") or start.get("date")
    if not raw:
        return None
    text = str(raw)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
