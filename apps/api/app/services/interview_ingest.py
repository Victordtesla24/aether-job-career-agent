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
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    from app.services.interview_thread_parser import parse_interview_thread

    hay = _norm(" ".join((subject, sender_name, sender_email, body)))
    domain = _sender_domain(sender_email)
    offer = parse_interview_thread(
        [{"body": body, "from": sender_name, "fromEmail": sender_email}],
        subject=subject,
    )
    parsed_company = _norm(offer.company or "")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.status, j.company, j.title, j.description, j.source
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
        if parsed_company and len(parsed_company) >= 3:
            job_hay = _norm(
                " ".join(
                    (
                        str(row.get("company") or ""),
                        str(row.get("title") or ""),
                        str(row.get("description") or ""),
                    )
                )
            )
            if parsed_company in job_hay:
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


_ALLOWED_TYPES = frozenset({"phone", "video", "onsite", "technical", "panel", "hr"})


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
    interview_type: str = "video",
    location: str | None = None,
    notes: str | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
    allow_create: bool = False,
) -> IngestResult:
    """Create/reuse an InterviewSchedule and promote the matched application.

    When ``calendar_event_id`` already exists the row is UPDATED with any
    newly evidenced time/format/location — a trail that moves a phone screen
    to a face-to-face meeting must not keep the first guess.
    """
    from app.routers.interviews import _ensure_interview_tables

    _ensure_interview_tables()
    itype = interview_type if interview_type in _ALLOWED_TYPES else "video"
    who_name = (contact_name or sender_name or "").strip() or None
    who_email = (contact_email or sender_email or "").strip() or None
    note = (notes or subject or "").strip() or None

    existing = _existing_by_calendar_event(user_id, calendar_event_id or "")
    if existing:
        _refresh_interview_row(
            user_id,
            existing["id"],
            scheduled_at=scheduled_at,
            interview_type=itype,
            location=location,
            meeting_link=meeting_link,
            duration_minutes=duration_minutes,
            notes=note,
            contact_name=who_name,
            contact_email=who_email,
        )
        promote_application_to_interview(user_id, existing["applicationId"])
        _align_email_sourced_job(
            user_id, existing["applicationId"], subject=subject, body=body
        )
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
    if matched is None and allow_create:
        matched = _create_application_from_evidence(
            user_id,
            subject=subject,
            body=body,
            location=location,
            source_url=(
                f"gmail://thread/{calendar_event_id}"
                if calendar_event_id
                else None
            ),
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
                    "scheduledAt", "durationMinutes", "location", "meetingLink",
                    "notes", "contactName", "contactEmail",
                    "calendarEventId", "calendarSyncStatus", "calendarSyncedAt"
                ) VALUES (
                    %s, %s, %s, %s, 'scheduled',
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, now()
                )
                """,
                (
                    interview_id,
                    user_id,
                    app_id,
                    itype,
                    when,
                    duration_minutes,
                    location,
                    meeting_link,
                    note,
                    who_name,
                    who_email,
                    calendar_event_id,
                    "ingested" if calendar_event_id else None,
                ),
            )
        conn.commit()

    promoted = promote_application_to_interview(user_id, app_id)
    if not promoted and str(matched.get("status") or "") in _ALREADY_INTERVIEW:
        promoted = True
    _align_email_sourced_job(user_id, app_id, subject=subject, body=body)
    return IngestResult(
        promoted=promoted,
        application_id=app_id,
        interview_id=interview_id,
        reason="matched application",
    )


def ingest_calendar_events(user_id: str, events: list[dict[str, Any]]) -> list[IngestResult]:
    """Ingest a batch of Google Calendar events."""
    results: list[IngestResult] = []
    for event in events:
        if not is_career_calendar_event(event):
            continue
        start = _event_start(event)
        organizer = event.get("organizer") or {}
        description = str(event.get("description") or "")
        from app.services.interview_thread_parser import parse_interview_thread

        offer = parse_interview_thread(
            [
                {
                    "from": str(organizer.get("displayName") or ""),
                    "fromEmail": str(organizer.get("email") or ""),
                    "body": description,
                    "createdAt": start,
                }
            ],
            subject=str(event.get("summary") or ""),
        )
        result = ingest_interview_invite(
            user_id,
            subject=str(event.get("summary") or "Interview"),
            sender_name=str(organizer.get("displayName") or ""),
            sender_email=str(organizer.get("email") or ""),
            body=description,
            scheduled_at=start or offer.scheduled_at,
            calendar_event_id=str(event.get("id") or "") or None,
            meeting_link=str(event.get("hangoutLink") or event.get("htmlLink") or "")
            or offer.meeting_link,
            interview_type=offer.interview_type if offer.is_interview else "video",
            location=offer.location,
            notes=str(event.get("summary") or "") or None,
        )
        results.append(result)
    return results


def ingest_inbound_for_user(
    user_id: str,
    threads: list[dict[str, Any]] | None = None,
    *,
    force_calendar: bool = False,
) -> list[IngestResult]:
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
    from app.services.interview_thread_parser import parse_interview_thread

    now_mono = time.monotonic()
    with _cal_ingest_lock:
        last = _cal_ingest_at.get(user_id, 0.0)
        run_calendar = force_calendar or (now_mono - last) >= _CAL_INGEST_TTL_SECONDS
        if run_calendar:
            _cal_ingest_at[user_id] = now_mono

    results: list[IngestResult] = []
    if run_calendar:
        try:
            now = datetime.now(timezone.utc)
            events = GoogleCalendarService(user_id).list_events(
                time_min=now - timedelta(days=7),
                time_max=now + timedelta(days=60),
            )
            results.extend(ingest_calendar_events(user_id, events))
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
        offer = parse_interview_thread(
            msgs if isinstance(msgs, list) else [],
            subject=str(t.get("subject") or ""),
        )
        if not verdict.is_interview_invite and not offer.is_interview:
            continue
        scheduled = offer.scheduled_at
        if scheduled is None:
            stamp = t.get("lastMessageAt")
            if isinstance(stamp, datetime):
                scheduled = stamp
            else:
                raw = latest.get("createdAt") or t.get("createdAt")
                if isinstance(raw, datetime):
                    scheduled = raw
                else:
                    scheduled = _event_start({"start": {"dateTime": raw}})
        notes = "\n".join(
            [*offer.logistics, *offer.unanswered_questions]
        ) or str(t.get("subject") or "")
        try:
            result = ingest_interview_invite(
                user_id,
                subject=str(t.get("subject") or ""),
                sender_name=str(latest.get("from") or ""),
                sender_email=str(latest.get("fromEmail") or ""),
                body=offer.haystack or str(latest.get("body") or ""),
                scheduled_at=scheduled,
                calendar_event_id=(
                    f"gmail:{t.get('gmailThreadId')}" if t.get("gmailThreadId") else None
                ),
                meeting_link=offer.meeting_link,
                duration_minutes=offer.duration_minutes,
                interview_type=offer.interview_type if offer.is_interview else "video",
                location=offer.location,
                notes=notes,
                contact_name=offer.contact_name,
                contact_email=offer.contact_email,
                allow_create=True,
            )
            results.append(result)
            if result.application_id and t.get("id"):
                _link_thread_application(
                    user_id, str(t["id"]), result.application_id
                )
        except Exception:  # noqa: BLE001
            logger.warning(
                "interview ingest failed for thread=%s user=%s",
                t.get("id"),
                user_id,
                exc_info=True,
            )
    return results


_mailbox_ingest_fp: dict[str, tuple[int, str, str]] = {}
_mailbox_ingest_lock = threading.Lock()


def _mailbox_fingerprint(threads: list[dict[str, Any]]) -> tuple[int, str, str]:
    if not threads:
        return (0, "", "")
    latest = max(str(t.get("lastMessageAt") or t.get("createdAt") or "") for t in threads)
    newest_id = max(str(t.get("id") or "") for t in threads)
    return (len(threads), latest, newest_id)


def ingest_stored_mailbox(user_id: str) -> list[IngestResult]:
    """Ingest EmailThread rows already on disk. Used by Interview Center GET.

    Does not call Gmail. Calendar listing still respects the existing TTL
    inside ``ingest_inbound_for_user``. Skips when the stored mailbox has
    not changed since the last successful ingest for this user, so a
    realtime poll does not re-parse two hundred threads — and so a GET
    that ran against an empty mailbox does not hide a thread inserted
    moments later.
    """
    try:
        threads = _load_career_threads(user_id)
        fingerprint = _mailbox_fingerprint(threads)
        with _mailbox_ingest_lock:
            if _mailbox_ingest_fp.get(user_id) == fingerprint:
                return []
        results = ingest_inbound_for_user(user_id, threads, force_calendar=False)
        with _mailbox_ingest_lock:
            _mailbox_ingest_fp[user_id] = fingerprint
        return results
    except Exception:  # noqa: BLE001 — Interview Center GET must still list
        logger.warning(
            "stored mailbox interview ingest failed user=%s", user_id, exc_info=True
        )
        return []


def _load_career_threads(user_id: str) -> list[dict[str, Any]]:
    from app.services.gmail_service import (
        ensure_email_thread_agent_columns,
        ensure_email_thread_gmail_columns,
        ensure_email_thread_last_message_column,
    )

    ensure_email_thread_last_message_column()
    ensure_email_thread_agent_columns()
    ensure_email_thread_gmail_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id, subject, messages, classification,'
                ' "gmailThreadId", "gmailMessageId", labels,'
                ' "gmailAccountId", "lastMessageAt", "createdAt",'
                ' "draftReply" FROM "EmailThread"'
                ' WHERE "userId" = %s'
                " AND COALESCE(classification, '') <> 'personal'"
                ' ORDER BY COALESCE("lastMessageAt", "createdAt") DESC LIMIT 200',
                (user_id,),
            )
            return rows_to_dicts(cur)


def _align_email_sourced_job(
    user_id: str,
    application_id: str,
    *,
    subject: str,
    body: str,
) -> None:
    """Correct an email-created Job when the parser now has a better employer."""
    from app.services.interview_thread_parser import parse_interview_thread

    offer = parse_interview_thread(
        [{"body": body, "from": "", "fromEmail": ""}],
        subject=subject,
    )
    company = (offer.company or "").strip()
    title = (offer.title or "").strip()
    if len(company) < 3:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE "Job" j SET
                    company = %s,
                    title = CASE WHEN %s <> '' THEN %s ELSE j.title END,
                    location = COALESCE(%s, j.location),
                    "updatedAt" = now()
                FROM "Application" a
                WHERE a.id = %s AND a."userId" = %s
                  AND j.id = a."jobId" AND j.source = 'email'
                """,
                (
                    company,
                    title if len(title) >= 6 else "",
                    title if len(title) >= 6 else "",
                    offer.location,
                    application_id,
                    user_id,
                ),
            )
        conn.commit()


def _refresh_interview_row(
    user_id: str,
    interview_id: str,
    *,
    scheduled_at: datetime | None,
    interview_type: str,
    location: str | None,
    meeting_link: str | None,
    duration_minutes: int,
    notes: str | None,
    contact_name: str | None,
    contact_email: str | None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE "InterviewSchedule" SET
                    "type" = %s,
                    "scheduledAt" = COALESCE(%s, "scheduledAt"),
                    "durationMinutes" = %s,
                    "location" = COALESCE(%s, "location"),
                    "meetingLink" = COALESCE(%s, "meetingLink"),
                    "notes" = COALESCE(%s, "notes"),
                    "contactName" = COALESCE(%s, "contactName"),
                    "contactEmail" = COALESCE(%s, "contactEmail"),
                    "updatedAt" = now()
                WHERE id = %s AND "userId" = %s
                """,
                (
                    interview_type,
                    scheduled_at,
                    duration_minutes,
                    location,
                    meeting_link,
                    notes,
                    contact_name,
                    contact_email,
                    interview_id,
                    user_id,
                ),
            )
        conn.commit()


def _create_application_from_evidence(
    user_id: str,
    *,
    subject: str,
    body: str,
    location: str | None,
    source_url: str | None,
) -> dict[str, Any] | None:
    """Open a Job + interview-stage Application from evidenced trail facts.

    Requires both a company and a role title in the trail, plus a real résumé
    to attach. Never invents either field.
    """
    from app.repositories.job import JobRepository
    from app.repositories.resume import ResumeRepository
    from app.services.interview_thread_parser import parse_interview_thread

    offer = parse_interview_thread(
        [{"body": body, "from": "", "fromEmail": ""}],
        subject=subject,
    )
    company = (offer.company or "").strip()
    title = (offer.title or "").strip()
    if len(company) < 3 or len(title) < 6:
        return None
    resumes = ResumeRepository().list_by_user(user_id)
    if not resumes:
        return None
    resume_id = str(resumes[0]["id"])
    job = JobRepository().create(
        user_id,
        {
            "title": title,
            "company": company,
            "location": location or offer.location,
            "remote": False,
            "description": (body or subject)[:8000],
            "requirements": [],
            "source": "email",
            "sourceUrl": source_url or f"email://{new_id()}",
            "postedAt": None,
        },
    )
    job_id = str(job["id"])
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id, status FROM "Application" '
                'WHERE "userId" = %s AND "jobId" = %s '
                "ORDER BY \"updatedAt\" DESC LIMIT 1",
                (user_id, job_id),
            )
            existing = rows_to_dicts(cur)
        if existing:
            return existing[0]
        app_id = new_id()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "Application"
                    ("id", "userId", "jobId", "resumeId", "status",
                     "createdAt", "updatedAt")
                VALUES (%s, %s, %s, %s, 'interview'::"ApplicationStatus",
                        now(), now())
                """,
                (app_id, user_id, job_id, resume_id),
            )
        conn.commit()
    return {"id": app_id, "status": "interview"}


def _link_thread_application(user_id: str, thread_id: str, application_id: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "EmailThread" SET "applicationId" = %s'
                ' WHERE id = %s AND "userId" = %s',
                (application_id, thread_id, user_id),
            )
        conn.commit()


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
