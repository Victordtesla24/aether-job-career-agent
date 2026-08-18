"""Deterministic interview-prep briefing from the trail and the candidate's own data.

STAR answer sketches stay story-grounded in ``InterviewPrepAgent``. This module
assembles the rest of the brief — logistics, traps, company notes from the
user's own postings, interviewer names from the trail, questions to ask, and
conversion guidelines — WITHOUT calling an LLM and WITHOUT inventing employer
facts (no Crunchbase, no rebrand years, no interviewer CVs).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.db import get_connection, rows_to_dicts
from app.services.interview_thread_parser import (
    MELBOURNE,
    InterviewOffer,
    parse_interview_thread,
)

_TRUENERGY = re.compile(r"\btru[\s-]*energy\b", re.IGNORECASE)
_ENERGY_AU = re.compile(r"\benergy[\s-]*australia\b", re.IGNORECASE)
_ATO = re.compile(r"\bato\b", re.IGNORECASE)
_TENDER = re.compile(r"\b(tender|gentrack|tally)\b", re.IGNORECASE)
_FTC = re.compile(r"\b(12[\s-]*month|twelve[\s-]*month|\bftc\b|fixed[\s-]*term)\b", re.IGNORECASE)
_STAKEHOLDER = re.compile(
    r"\b(stakeholder|governance|project\s+management|steering)\b",
    re.IGNORECASE,
)

FORMAT_LABELS = {
    "phone": "Phone",
    "video": "Video",
    "onsite": "Face to face",
    "technical": "Technical",
    "panel": "Panel",
    "hr": "HR",
}

#: Shared ordering so Interview Prep and Interview Center resolve the SAME
#: interview-stage application (soonest upcoming scheduled interview first).
ACTIVE_INTERVIEW_ORDER = """
    ORDER BY
      CASE WHEN i."scheduledAt" IS NULL THEN 1 ELSE 0 END,
      CASE WHEN i."scheduledAt" >= now() THEN 0 ELSE 1 END,
      i."scheduledAt" ASC NULLS LAST,
      a."createdAt" DESC
"""

ACTIVE_INTERVIEW_FROM = """
    FROM "Application" a
    JOIN "Job" j ON a."jobId" = j.id
    LEFT JOIN LATERAL (
      SELECT iv."scheduledAt", iv."type", iv."location",
             iv."contactName", iv."contactEmail", iv."meetingLink",
             iv."durationMinutes", iv.notes
      FROM "InterviewSchedule" iv
      WHERE iv."applicationId" = a.id AND iv."userId" = a."userId"
        AND iv.status IN ('scheduled', 'confirmed', 'rescheduled')
      ORDER BY iv."scheduledAt" ASC
      LIMIT 1
    ) i ON true
    WHERE a."userId" = %s AND a.status = 'interview'
"""


def empty_briefing() -> dict[str, Any]:
    return {
        "logistics": [],
        "traps": [],
        "companyNotes": [],
        "interviewerNotes": [],
        "questionsToAsk": [],
        "guidelines": [],
        "closing": [],
        "documentMarkdown": "",
    }


def detect_prep_traps(
    *,
    resume_text: str,
    thread_text: str,
    unanswered_questions: list[str] | tuple[str, ...],
    job_text: str,
) -> list[dict[str, str]]:
    """Surface evidenced conflicts. Never invent a date or a rebrand story."""
    traps: list[dict[str, str]] = []
    resume_l = resume_text or ""
    hay = f"{resume_text}\n{thread_text}\n{job_text}"
    for question in unanswered_questions:
        q = str(question or "").strip()
        if q:
            traps.append(
                {
                    "title": "Unanswered question in the email trail",
                    "detail": q,
                }
            )
    if _TRUENERGY.search(resume_l) and _ENERGY_AU.search(hay):
        traps.append(
            {
                "title": "Employer name on the CV",
                "detail": (
                    "Your résumé names TruEnergy and the evidence also names "
                    "EnergyAustralia. Be ready with the legal name you will use, "
                    "the division, and who you reported to. Do not guess a "
                    "rebrand year unless it is written in your own materials."
                ),
            }
        )
    elif _TRUENERGY.search(resume_l):
        traps.append(
            {
                "title": "Employer name on the CV",
                "detail": (
                    "Your résumé names TruEnergy. Confirm the legal entity you "
                    "will name in the interview — the interviewer may know the "
                    "brand history."
                ),
            }
        )
    if _ATO.search(resume_l) and any(_ATO.search(q or "") for q in unanswered_questions):
        traps.append(
            {
                "title": "Availability vs current role",
                "detail": (
                    "The recruiter asked when you finished with the ATO and the "
                    "trail shows no reply. Have a one-sentence answer ready: "
                    "current status and the date you can start."
                ),
            }
        )
    return traps


def default_guidelines(offer: InterviewOffer) -> list[str]:
    lines: list[str] = []
    if offer.interview_type == "onsite":
        place = offer.location or "the address in the invite"
        lines.append(
            f"This is face to face at {place}. Plan the route and arrive ten "
            "minutes early. Take a printed résumé and a notebook."
        )
    elif offer.interview_type == "phone":
        lines.append(
            "This is a phone interview. Be somewhere quiet with signal. Have "
            "this brief and your résumé open, and a pen to write names."
        )
    elif offer.interview_type == "video":
        lines.append(
            "This is a video interview. Check camera, microphone and the "
            "meeting link before the start time. Have this brief beside you, "
            "not on the shared screen."
        )
    if offer.scheduled_at is not None:
        local = offer.scheduled_at.astimezone(MELBOURNE)
        lines.append(
            "Be ready at "
            + local.strftime("%A %-d %B %Y, %-I:%M %p")
            + " Melbourne time."
        )
    if offer.unanswered_questions:
        lines.append(
            "Answer outstanding recruiter questions before or at the start of "
            "the interview. They are already in the trail: "
            + " ".join(offer.unanswered_questions)
        )
    if offer.contact_name:
        lines.append(
            f"Use {offer.contact_name}'s name. Do not invent their background."
        )
    lines.append(
        "Ask where the process goes next, and whether anything in your "
        "background they want expanded."
    )
    return lines


def default_questions_to_ask(*, thread_text: str, job_text: str) -> list[str]:
    hay = f"{thread_text}\n{job_text}"
    qs: list[str] = []
    if _TENDER.search(hay):
        qs.append(
            "Where has the tender actually got to — still going to market, or a shortlist?"
        )
        qs.append(
            "How much of the decision rests on migration and cutover versus functional fit?"
        )
    if _FTC.search(hay):
        qs.append(
            "The contract is twelve months — what does done look like at month twelve?"
        )
    if _STAKEHOLDER.search(hay):
        qs.append(
            "Who are the senior stakeholders on this piece of work, and how is governance run day to day?"
        )
    qs.append(
        "Is there anything in my background you would like me to expand on?"
    )
    return _dedupe(qs)


def default_closing(offer: InterviewOffer) -> list[str]:
    who = offer.contact_name or "the interviewer"
    return [
        f"Close by thanking {who} and restating interest in the role as written.",
        "Send a short thank-you the same day naming one thing you actually discussed.",
    ]


def company_notes_from_report(report: Any, company: str | None) -> list[str]:
    """Only facts the Company Research agent derived from the user's own jobs."""
    name = (getattr(report, "company", None) or company or "").strip()
    postings = int(getattr(report, "postings", 0) or 0)
    if postings <= 0:
        if name:
            return [
                f"No discovered postings of yours name {name}, so there is no "
                "in-app company brief beyond the job and the email trail. This "
                "product does not fetch live web, Crunchbase or news."
            ]
        return [
            "No company research is available from your own postings, and this "
            "product does not fetch live web sources."
        ]
    notes = [
        f"{name}: {postings} posting(s) of yours mention this employer "
        "(synthesised from your Job rows, not from the public web)."
    ]
    roles = [str(r) for r in (getattr(report, "roles", None) or []) if str(r).strip()]
    if roles:
        notes.append("Roles on file: " + ", ".join(roles[:8]) + ".")
    locations = [
        str(loc) for loc in (getattr(report, "locations", None) or []) if str(loc).strip()
    ]
    if locations:
        notes.append("Locations on file: " + ", ".join(locations[:8]) + ".")
    if getattr(report, "lowConfidence", False):
        notes.append(
            "Low confidence: this rests on a single posting of yours."
        )
    sources = [str(s) for s in (getattr(report, "sources", None) or []) if str(s).strip()]
    if sources:
        notes.append("Boards on file: " + ", ".join(sources[:8]) + ".")
    return notes


def interviewer_notes(offer: InterviewOffer) -> list[str]:
    notes: list[str] = []
    if offer.contact_name:
        line = f"Contact: {offer.contact_name}"
        if offer.contact_email:
            line += f" ({offer.contact_email})"
        notes.append(line)
    emails = offer.interviewer_emails or ()
    for idx, name in enumerate(offer.interviewer_names):
        if not name or name == offer.contact_name:
            continue
        extra = ""
        if idx < len(emails) and emails[idx]:
            extra = f" ({emails[idx]})"
        notes.append(f"Also named in the trail: {name}{extra}")
    if not notes:
        notes.append(
            "No interviewer identity was evidenced in the trail beyond the sender."
        )
    notes.append(
        "Do not invent education, tenure or personality for anyone named here."
    )
    return notes


def logistics_lines(offer: InterviewOffer, *, job_title: str, company: str) -> list[str]:
    lines: list[str] = []
    if job_title or company:
        bits = [p for p in (job_title, company) if p]
        lines.append(" · ".join(bits))
    label = FORMAT_LABELS.get(offer.interview_type, offer.interview_type)
    if offer.scheduled_at is not None:
        local = offer.scheduled_at.astimezone(MELBOURNE)
        lines.append(
            f"{label} — {local.strftime('%A %-d %B %Y, %-I:%M %p')} Melbourne time"
        )
    else:
        lines.append(label)
    if offer.location:
        lines.append(f"Place: {offer.location}")
    if offer.meeting_link:
        lines.append(f"Link: {offer.meeting_link}")
    if offer.duration_minutes:
        lines.append(f"Duration: {offer.duration_minutes} minutes")
    lines.extend(offer.logistics)
    return lines


def assemble_document(
    *,
    job_title: str,
    company: str,
    offer: InterviewOffer,
    traps: list[dict[str, str]],
    company_notes: list[str],
    interviewer: list[str],
    questions_to_ask: list[str],
    guidelines: list[str],
    closing: list[str],
    career_summary: str,
) -> str:
    """A printable brief in the spirit of a logistics + traps + Q pack.

    Facts only from the arguments. Career summary is the user's own corpus.
    """
    parts: list[str] = [
        f"# Interview preparation — {job_title or 'Role'} at {company or 'the employer'}",
        "",
        "Grounded in your résumé, Story Bank, connected career sources, the "
        "job posting, and the email trail. Company notes come from your own "
        "discovered postings. Nothing here is live web research.",
        "",
        "## Logistics",
        *("- " + line for line in logistics_lines(offer, job_title=job_title, company=company)),
        "",
        "## Traps to avoid",
    ]
    if traps:
        for trap in traps:
            parts.append(f"- **{trap['title']}.** {trap['detail']}")
    else:
        parts.append("- None evidenced in the trail or your résumé.")
    parts.extend(["", "## Company (from your own postings)"])
    parts.extend("- " + n for n in company_notes)
    parts.extend(["", "## Interviewer"])
    parts.extend("- " + n for n in interviewer)
    if career_summary.strip():
        parts.extend(
            [
                "",
                "## Your connected career sources (excerpt)",
                career_summary.strip()[:2000],
            ]
        )
    parts.extend(["", "## Questions to ask"])
    parts.extend("- " + q for q in questions_to_ask)
    parts.extend(["", "## Guidelines"])
    parts.extend("- " + g for g in guidelines)
    parts.extend(["", "## Close"])
    parts.extend("- " + c for c in closing)
    return "\n".join(parts).strip() + "\n"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = re.sub(r"\s+", " ", item.strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def offer_from_schedule_row(row: dict[str, Any] | None) -> InterviewOffer:
    if not row:
        return InterviewOffer(is_interview=False)
    when = row.get("scheduledAt")
    if isinstance(when, datetime) and when.tzinfo is None:
        when = when.replace(tzinfo=MELBOURNE)
    itype = str(row.get("type") or "video")
    return InterviewOffer(
        is_interview=True,
        scheduled_at=when if isinstance(when, datetime) else None,
        interview_type=itype if itype in FORMAT_LABELS else "video",
        location=(str(row["location"]) if row.get("location") else None),
        meeting_link=(str(row["meetingLink"]) if row.get("meetingLink") else None),
        duration_minutes=int(row.get("durationMinutes") or 60),
        contact_name=(str(row["contactName"]) if row.get("contactName") else None),
        contact_email=(str(row["contactEmail"]) if row.get("contactEmail") else None),
        logistics=tuple(
            p for p in (str(row.get("notes") or "").splitlines()) if p.strip()
        ),
    )


def merge_offers(schedule: InterviewOffer, trail: InterviewOffer) -> InterviewOffer:
    """Trail wins on format/time/place when it actually stated them."""
    if not trail.is_interview and not schedule.is_interview:
        return trail
    if not trail.is_interview:
        return schedule
    if not schedule.is_interview:
        return trail
    return InterviewOffer(
        is_interview=True,
        company=trail.company or schedule.company,
        title=trail.title or schedule.title,
        scheduled_at=trail.scheduled_at or schedule.scheduled_at,
        interview_type=(
            trail.interview_type
            if trail.is_interview
            else schedule.interview_type
        ),
        location=trail.location or schedule.location,
        meeting_link=trail.meeting_link or schedule.meeting_link,
        duration_minutes=trail.duration_minutes or schedule.duration_minutes,
        contact_name=trail.contact_name or schedule.contact_name,
        contact_email=trail.contact_email or schedule.contact_email,
        interviewer_names=trail.interviewer_names or schedule.interviewer_names,
        interviewer_emails=trail.interviewer_emails or schedule.interviewer_emails,
        unanswered_questions=trail.unanswered_questions,
        logistics=trail.logistics or schedule.logistics,
        haystack=trail.haystack or schedule.haystack,
    )


@dataclass
class PrepContext:
    resume_text: str = ""
    career_corpus: str = ""
    career_source_count: int = 0
    thread_text: str = ""
    offer: InterviewOffer = field(default_factory=lambda: InterviewOffer(is_interview=False))
    company_report: Any = None
    briefing: dict[str, Any] = field(default_factory=empty_briefing)


def load_prep_context(
    user_id: str,
    job: dict[str, Any],
    *,
    job_text: str,
) -> PrepContext:
    """Load résumé, career corpus, email trail, schedule, company synthesis."""
    from app.repositories.career_profile import CareerProfileRepository
    from app.routers.interviews import _ensure_interview_tables
    from app.services.career_data import build_career_corpus
    from app.services.resume_grounding import resolve_user_resume_text

    _ensure_interview_tables()
    resume_text = resolve_user_resume_text(user_id, allow_operator_fallback=False) or ""
    career_repo = CareerProfileRepository()
    career_corpus = build_career_corpus(user_id, career_repo)
    career_source_count = sum(
        1
        for row in career_repo.list_by_user(user_id)
        if row.get("status") == "ok" and row.get("summary")
    )

    job_id = str(job.get("id") or "")
    company = str(job.get("company") or "")
    threads = _load_job_threads(user_id, job_id)
    thread_text = "\n\n".join(
        f"{t.get('subject') or ''}\n{t.get('haystack') or ''}" for t in threads
    )
    trail_offer = InterviewOffer(is_interview=False, haystack=thread_text)
    for t in threads:
        parsed = parse_interview_thread(
            t.get("messages") if isinstance(t.get("messages"), list) else [],
            subject=str(t.get("subject") or ""),
        )
        if parsed.is_interview:
            trail_offer = parsed
            break
        if parsed.haystack:
            trail_offer = InterviewOffer(
                is_interview=False,
                haystack=parsed.haystack,
                unanswered_questions=parsed.unanswered_questions,
            )

    schedule_row = _load_schedule_for_job(user_id, job_id)
    offer = merge_offers(offer_from_schedule_row(schedule_row), trail_offer)
    if not offer.company:
        offer = replace(offer, company=company or offer.company)
    if not offer.title:
        offer = replace(offer, title=str(job.get("title") or "") or offer.title)

    report = None
    try:
        from app.agents.company_research_agent import CompanyResearchAgent

        report = CompanyResearchAgent().run(user_id, company=company, narrative=False)
    except Exception:  # noqa: BLE001 — briefing must still assemble
        report = None

    traps = detect_prep_traps(
        resume_text=resume_text,
        thread_text=thread_text,
        unanswered_questions=offer.unanswered_questions,
        job_text=job_text,
    )
    questions = default_questions_to_ask(thread_text=thread_text, job_text=job_text)
    guidelines = default_guidelines(offer) if offer.is_interview else []
    closing = default_closing(offer) if offer.is_interview else []
    company_notes = company_notes_from_report(report, company)
    interviewer = interviewer_notes(offer)
    briefing = {
        "logistics": logistics_lines(
            offer,
            job_title=str(job.get("title") or ""),
            company=company,
        ),
        "traps": traps,
        "companyNotes": company_notes,
        "interviewerNotes": interviewer,
        "questionsToAsk": questions,
        "guidelines": guidelines,
        "closing": closing,
        "documentMarkdown": assemble_document(
            job_title=str(job.get("title") or ""),
            company=company,
            offer=offer,
            traps=traps,
            company_notes=company_notes,
            interviewer=interviewer,
            questions_to_ask=questions,
            guidelines=guidelines,
            closing=closing,
            career_summary=career_corpus,
        ),
    }
    return PrepContext(
        resume_text=resume_text,
        career_corpus=career_corpus,
        career_source_count=career_source_count,
        thread_text=thread_text,
        offer=offer,
        company_report=report,
        briefing=briefing,
    )


def _load_job_threads(user_id: str, job_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT et.subject, et.messages
                FROM "EmailThread" et
                JOIN "Application" a ON a.id = et."applicationId"
                WHERE et."userId" = %s AND a."jobId" = %s
                ORDER BY COALESCE(et."lastMessageAt", et."updatedAt") DESC
                """,
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
    out: list[dict[str, Any]] = []
    for row in rows:
        messages = row.get("messages") or []
        if not isinstance(messages, list):
            messages = []
        out.append(
            {
                "subject": row.get("subject") or "",
                "messages": messages,
                "haystack": "\n".join(
                    str(m.get("body") or "")
                    for m in messages
                    if isinstance(m, dict)
                ),
            }
        )
    return out


def _load_schedule_for_job(user_id: str, job_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT i."type", i."scheduledAt", i."location", i."meetingLink",
                       i."contactName", i."contactEmail", i."durationMinutes",
                       i.notes
                FROM "InterviewSchedule" i
                JOIN "Application" a ON a.id = i."applicationId"
                WHERE a."userId" = %s AND a."jobId" = %s
                  AND i.status IN ('scheduled', 'confirmed', 'rescheduled')
                ORDER BY i."scheduledAt" ASC
                LIMIT 1
                """,
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None
