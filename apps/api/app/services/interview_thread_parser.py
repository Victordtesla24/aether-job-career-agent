"""Deterministic interview-offer parser for a full email trail.

Email Center ingest used to treat the latest message stamp as the interview
time and to hard-code ``video``. Recruiter threads routinely contradict both:
a phone screen is moved to a face-to-face meeting; "tomorrow at 10:00am" is
relative to the message that said it, not to the Gmail sync clock.

This module reads the WHOLE trail. Later messages override earlier ones when
they actually state a new format, place or clock time. It never invents a
company, role, or timestamp that the text does not contain, and it never
calls an LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

MELBOURNE = ZoneInfo("Australia/Melbourne")

_INTERVIEW_SIGNAL = re.compile(
    r"\b("
    r"interview|phone\s*screen|screening\s+call|"
    r"face[\s-]*to[\s-]*face|in[\s-]*person|on[\s-]*site|"
    r"hiring\s+manager|meet(?:ing)?\s+invite|"
    r"(?:i(?:'|’)ll|he(?:'|’)ll|she(?:'|’)ll|we(?:'|’)ll)\s+call\s+you|"
    r"call\s+you\s+on"
    r")\b",
    re.IGNORECASE,
)

_PHONE_SIGNAL = re.compile(
    r"\b(phone\s*interview|phone\s*screen|screening\s+call|"
    r"(?:i(?:'|’)ll|he(?:'|’)ll|she(?:'|’)ll|adan|they)\s+call(?:s|ing)?\s+you|"
    r"call\s+you\s+on)\b",
    re.IGNORECASE,
)
_ONSITE_SIGNAL = re.compile(
    r"\b(face[\s-]*to[\s-]*face|in[\s-]*person|on[\s-]*site|"
    r"at\s+our\s+\w+\s+office|at\s+the\s+\w+\s+office)\b",
    re.IGNORECASE,
)
_VIDEO_SIGNAL = re.compile(
    r"\b(zoom|google\s+meet|microsoft\s+teams|video\s+interview|"
    r"virtual\s+interview|teams\s+link)\b",
    re.IGNORECASE,
)
_INSTEAD_OF_PHONE = re.compile(
    r"\b(instead\s+of|rather\s+than)\s+a\s+phone\b",
    re.IGNORECASE,
)

_MEET_LINK = re.compile(
    r"https?://(?:meet\.google\.com|zoom\.us|teams\.microsoft\.com)"
    r"[^\s<>\]\)]+",
    re.IGNORECASE,
)
_TIME = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b",
    re.IGNORECASE,
)
_TOMORROW = re.compile(r"\btomorrow\b", re.IGNORECASE)
_TODAY = re.compile(r"\btoday\b", re.IGNORECASE)
_THIS_MORNING = re.compile(r"\bthis\s+morning\b", re.IGNORECASE)

_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_ABSOLUTE_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+("
    + "|".join(_MONTHS)
    + r")(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# Do not require ``\b`` before ``@``: a space and ``@`` are both non-word,
# so ``Project Manager @ Next Business Energy`` never matched (live miss).
_AT_COMPANY = re.compile(
    r"(?:@|\bat)\s+([A-Z][A-Za-z0-9&'-]+(?:\s+[A-Z][A-Za-z0-9&'-]+){0,4})\b"
)
_WITH_COMPANY = re.compile(
    r"\bwith\s+([A-Z][A-Za-z0-9&'-]+(?:\s+[A-Z][A-Za-z0-9&'-]+){1,4})\b"
)
_PAREN_ROLE = re.compile(
    r"\(([A-Za-z][A-Za-z0-9][^@\n]{3,80}?)\s*@"
)
_ROLE = re.compile(
    r"(?:the\s+role\s+is|role:|interview\s+for)\s+"
    r"([^,\n]{6,120})",
    re.IGNORECASE,
)
_CONSUMER_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "icloud.com",
        "me.com",
        "msn.com",
    }
)
_LOCATION_OFFICE = re.compile(
    r"\bat\s+our\s+([A-Za-z][A-Za-z\s-]{2,40}\s+office)\b",
    re.IGNORECASE,
)
_LOCATION_NAMED = re.compile(
    r"\b(Docklands|Southbank|CBD|Melbourne\s+CBD|Sydney\s+CBD|"
    r"Barangaroo|Parramatta|Canberra|Brisbane\s+CBD)\b",
    re.IGNORECASE,
)
_NAME_WITH_TITLE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+),\s+"
    r"(?:Group\s+Technical\s+Lead|Technical\s+Lead|Hiring\s+Manager|"
    r"Head\s+of\s+[A-Za-z& ]+|Consultant|Recruiter|Talent\s+Acquisition)\b"
)
_EMAIL = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
_QUESTION = re.compile(r"([A-Z][^?]{8,180}\?)")
_DURATION = re.compile(
    r"\b(\d{1,3})\s*(?:minute|min)s?\b|\b(?:an|one)\s+hour\b",
    re.IGNORECASE,
)

_RECRUITER_DOMAINS = (
    "robertwalters.com",
    "robertwalters.com.au",
    "hays.com",
    "hays.com.au",
    "michaelpage.com",
    "michaelpage.com.au",
    "seek.com",
    "seek.com.au",
    "linkedin.com",
    "indeed.com",
    "talentinternational.com",
)
_RECRUITER_NAMES = (
    "robert walters",
    "hays",
    "michael page",
    "seek",
    "indeed",
    "linkedin",
)

_OWN_ROLES = frozenset({"reply", "draft"})


@dataclass(frozen=True)
class InterviewOffer:
    """Facts evidenced in an email trail. Empty fields were not in the text."""

    is_interview: bool
    company: str | None = None
    title: str | None = None
    scheduled_at: datetime | None = None
    interview_type: str = "video"
    location: str | None = None
    meeting_link: str | None = None
    duration_minutes: int = 60
    contact_name: str | None = None
    contact_email: str | None = None
    interviewer_names: tuple[str, ...] = ()
    interviewer_emails: tuple[str, ...] = ()
    unanswered_questions: tuple[str, ...] = ()
    logistics: tuple[str, ...] = ()
    haystack: str = ""


def thread_haystack(
    messages: Iterable[dict[str, Any]] | None,
    *,
    subject: str = "",
) -> str:
    """Subject plus every message body, oldest to newest."""
    parts = [subject or ""]
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        parts.append(str(msg.get("body") or ""))
        parts.append(str(msg.get("from") or ""))
        parts.append(str(msg.get("fromEmail") or ""))
    return "\n".join(p for p in parts if p)


def parse_interview_thread(
    messages: list[dict[str, Any]] | None,
    *,
    subject: str = "",
    now: datetime | None = None,
) -> InterviewOffer:
    """Parse one Gmail-normalised thread into an evidenced interview offer."""
    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    hay = thread_haystack(msgs, subject=subject)
    if not _INTERVIEW_SIGNAL.search(hay) and not _MEET_LINK.search(hay):
        return InterviewOffer(is_interview=False, haystack=hay)

    company: str | None = None
    title: str | None = None
    when: datetime | None = None
    itype: str | None = None
    location: str | None = None
    meeting_link: str | None = None
    duration = 60
    names: list[str] = []
    emails: list[str] = []
    questions: list[str] = []
    logistics: list[str] = []

    for msg in msgs:
        body = str(msg.get("body") or "")
        blob = f"{subject}\n{body}"
        stamp = _message_stamp(msg, now)
        extracted_when = _resolve_when(blob, stamp)
        if extracted_when is not None:
            when = extracted_when
        detected_type = _detect_type(blob)
        if detected_type:
            itype = detected_type
        loc = _detect_location(blob)
        if loc:
            location = loc
        link = _first(_MEET_LINK.findall(body))
        if link:
            meeting_link = link.rstrip(".,);")
            if itype is None:
                itype = "video"
        dur = _detect_duration(blob)
        if dur:
            duration = dur
        for name in _names_from_message(msg):
            _add_unique(names, name)
        for email in _emails_from_message(msg):
            _add_unique(emails, email.lower())
        if msg.get("role") not in _OWN_ROLES:
            for q in _QUESTION.findall(body):
                cleaned = re.sub(r"\s+", " ", q).strip()
                if cleaned and not _is_quoted_question(cleaned):
                    _add_unique(questions, cleaned)
        co = _detect_company(
            blob,
            emails + [str(msg.get("fromEmail") or "")],
            subject=subject,
        )
        if co:
            company = co
        role = _detect_title(blob, company)
        if role:
            title = role

    contact_email = _prefer_employer_email(emails)
    contact_name = _name_for_email(msgs, contact_email) or (names[-1] if names else None)
    if contact_name:
        _add_unique(names, contact_name)

    if when:
        local = when.astimezone(MELBOURNE)
        logistics.append(
            f"{_type_label(itype or 'video')} · "
            f"{local.strftime('%-I:%M%p, %A %-d %B %Y').replace('AM', 'am').replace('PM', 'pm')} "
            f"(Melbourne)"
        )
    if location:
        logistics.append(f"Location: {location}")
    if meeting_link:
        logistics.append(f"Link: {meeting_link}")
    if contact_name or contact_email:
        logistics.append(
            "Interviewer: "
            + " · ".join(p for p in (contact_name, contact_email) if p)
        )

    return InterviewOffer(
        is_interview=True,
        company=company,
        title=title,
        scheduled_at=when,
        interview_type=itype or ("video" if meeting_link else "video"),
        location=location,
        meeting_link=meeting_link,
        duration_minutes=duration,
        contact_name=contact_name,
        contact_email=contact_email,
        interviewer_names=tuple(names),
        interviewer_emails=tuple(emails),
        unanswered_questions=tuple(questions),
        logistics=tuple(logistics),
        haystack=hay,
    )


def _type_label(itype: str) -> str:
    return {
        "phone": "Phone interview",
        "onsite": "Face-to-face interview",
        "video": "Video interview",
        "technical": "Technical interview",
        "panel": "Panel interview",
        "hr": "HR interview",
    }.get(itype, "Interview")


def _message_stamp(msg: dict[str, Any], now: datetime | None) -> datetime:
    raw = msg.get("createdAt") or msg.get("date") or now
    if isinstance(raw, datetime):
        stamp = raw
    elif isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            stamp = datetime.fromisoformat(text)
        except ValueError:
            stamp = now or datetime.now(tz=MELBOURNE)
    else:
        stamp = now or datetime.now(tz=MELBOURNE)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=MELBOURNE)
    return stamp.astimezone(MELBOURNE)


def _clock(text: str) -> tuple[int, int] | None:
    match = _TIME.search(text or "")
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = re.sub(r"[.\s]", "", match.group(3).lower())
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _resolve_when(text: str, stamp: datetime) -> datetime | None:
    clock = _clock(text)
    day = None
    abs_match = _ABSOLUTE_DATE.search(text or "")
    if abs_match:
        d = int(abs_match.group(1))
        month = _MONTHS[abs_match.group(2).lower()]
        year = int(abs_match.group(3) or stamp.year)
        try:
            day = datetime(year, month, d, tzinfo=MELBOURNE).date()
        except ValueError:
            day = None
    elif _TOMORROW.search(text or ""):
        day = (stamp + timedelta(days=1)).date()
    elif _TODAY.search(text or "") or _THIS_MORNING.search(text or ""):
        day = stamp.date()
    else:
        for name, idx in _WEEKDAYS.items():
            if re.search(rf"\b{name}\b", text or "", re.IGNORECASE):
                delta = (idx - stamp.weekday()) % 7
                day = (stamp + timedelta(days=delta)).date()
                break
    if day is None:
        return None
    hour, minute = clock if clock else (None, None)
    if hour is None:
        return None
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MELBOURNE)


def _detect_type(text: str) -> str | None:
    if _ONSITE_SIGNAL.search(text) or _INSTEAD_OF_PHONE.search(text) and _ONSITE_SIGNAL.search(text):
        return "onsite"
    if _INSTEAD_OF_PHONE.search(text) and re.search(r"face|in[\s-]*person|office", text, re.I):
        return "onsite"
    if _VIDEO_SIGNAL.search(text) or _MEET_LINK.search(text):
        return "video"
    if _PHONE_SIGNAL.search(text):
        return "phone"
    return None


def _detect_location(text: str) -> str | None:
    office = _LOCATION_OFFICE.search(text or "")
    if office:
        return re.sub(r"\s+", " ", office.group(1)).strip()
    named = _LOCATION_NAMED.search(text or "")
    if named:
        return named.group(1)
    return None


def _detect_duration(text: str) -> int | None:
    match = _DURATION.search(text or "")
    if not match:
        return None
    if match.group(1):
        return max(15, min(480, int(match.group(1))))
    return 60


def _is_recruiter_company(name: str) -> bool:
    low = name.strip().lower()
    return any(frag == low or frag in low for frag in _RECRUITER_NAMES)


def _is_recruiter_domain(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    return any(domain == d or domain.endswith("." + d) for d in _RECRUITER_DOMAINS)


def _clean_company_name(raw: str) -> str | None:
    name = re.sub(r"\s+", " ", (raw or "")).strip(" .,")
    if not name or name[0].isdigit():
        return None
    if name.lower() in {"google meet", "microsoft teams"}:
        return None
    if _is_recruiter_company(name):
        return None
    return name


def _company_rank(name: str, subject: str) -> tuple[bool, int, int]:
    in_subject = name.lower() in (subject or "").lower()
    return (in_subject, len(name.split()), len(name))


def _detect_company(
    text: str, emails: list[str], *, subject: str = ""
) -> str | None:
    found: list[str] = []
    for pattern in (_AT_COMPANY, _WITH_COMPANY):
        for match in pattern.finditer(text or ""):
            name = _clean_company_name(match.group(1))
            if name:
                found.append(name)
    if not found:
        for email in emails:
            if not email or "@" not in email or _is_recruiter_domain(email):
                continue
            domain = email.rsplit("@", 1)[-1].lower()
            slug = domain.split(".")[0]
            compact = re.sub(r"[^a-z0-9]", "", (text or "").lower())
            if slug and slug in compact:
                recovered = _recover_company_from_slug(text, slug)
                if recovered:
                    return recovered
        return None
    for email in emails:
        if not email or "@" not in email or _is_recruiter_domain(email):
            continue
        slug = email.rsplit("@", 1)[-1].split(".")[0].lower()
        for name in found:
            if re.sub(r"[^a-z0-9]", "", name.lower()) == re.sub(
                r"[^a-z0-9]", "", slug
            ):
                return name
    return max(found, key=lambda name: _company_rank(name, subject))


def _recover_company_from_slug(text: str, slug: str) -> str | None:
    for match in _AT_COMPANY.finditer(text or ""):
        name = re.sub(r"\s+", " ", match.group(1)).strip(" .,")
        if re.sub(r"[^a-z0-9]", "", name.lower()) == re.sub(r"[^a-z0-9]", "", slug):
            return name
    return None


def _detect_title(text: str, company: str | None) -> str | None:
    title = None
    match = _ROLE.search(text or "")
    if match:
        title = match.group(1)
    else:
        paren = _PAREN_ROLE.search(text or "")
        if paren:
            title = paren.group(1)
    if not title:
        return None
    title = re.sub(r"\s+", " ", title).strip(" .")
    title = re.sub(r"^(?:the|an|a)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+position with\s+.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+[—–-]\s*$", "", title).strip()
    if company and title.lower() == company.lower():
        return None
    if len(title) < 6:
        return None
    return title


def _names_from_message(msg: dict[str, Any]) -> list[str]:
    names: list[str] = []
    header = str(msg.get("from") or "").strip()
    if header and "@" not in header and len(header.split()) <= 5:
        names.append(header)
    for match in _NAME_WITH_TITLE.finditer(str(msg.get("body") or "")):
        names.append(match.group(1).strip())
    return names


def _emails_from_message(msg: dict[str, Any]) -> list[str]:
    emails: list[str] = []
    header = str(msg.get("fromEmail") or "").strip()
    if header and "@" in header:
        emails.append(header)
    emails.extend(_EMAIL.findall(str(msg.get("body") or "")))
    return emails


def _is_consumer_email(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    return domain in _CONSUMER_EMAIL_DOMAINS


def _prefer_employer_email(emails: list[str]) -> str | None:
    cleaned = [e.strip() for e in emails if e and "@" in e]
    if not cleaned:
        return None
    professional = [e for e in cleaned if not _is_consumer_email(e)]
    pool = professional or cleaned
    for email in reversed(pool):
        if not _is_recruiter_domain(email) and not _is_consumer_email(email):
            return email
    for email in reversed(pool):
        if _is_recruiter_domain(email):
            return email
    return pool[-1]


def _name_for_email(messages: list[dict[str, Any]], email: str | None) -> str | None:
    if not email:
        return None
    for msg in reversed(messages):
        if str(msg.get("fromEmail") or "").strip().lower() == email.lower():
            name = str(msg.get("from") or "").strip()
            if name and "@" not in name:
                return name
    return None


def _is_quoted_question(text: str) -> bool:
    return text.lstrip().startswith(">")


def _add_unique(bucket: list[str], value: str) -> None:
    key = value.strip().lower()
    if not key:
        return
    if any(existing.lower() == key for existing in bucket):
        return
    bucket.append(value.strip())


def _first(values: list[str]) -> str | None:
    return values[0] if values else None
