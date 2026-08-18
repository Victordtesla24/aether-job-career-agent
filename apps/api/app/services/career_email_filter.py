"""Deterministic career-inbox filter for the Email Command Center.

The Email Center is a job-search product. Personal mail (tenancy hearings,
social, receipts) must never occupy the recruiter inbox, and interview
calendar invites must never be dropped because 25 unrelated threads were
newer. Classification here is regex + sender-domain evidence — no LLM, no
guessed facts.

Keep vs hide is conservative on KEEP: a single career signal is enough.
Hide wins only when there is no career signal, or a personal-institution
signal is present without a career signal (a VCAT hearing that happens to
land next to a calendar invite is still personal).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

#: Gmail search used by inbox sync + email-agent triage. Calendar invites
#: often skip the Primary tab (Updates / Calendar), so this query does NOT
#: require ``in:inbox``. ``has:calendar`` / ``filename:ics`` catch meeting
#: invites; the subject/from clauses catch recruiter and job-search mail.
CAREER_GMAIL_QUERY = (
    "newer_than:45d "
    "(has:calendar OR filename:ics "
    "OR from:calendar-notification@google.com "
    "OR from:(linkedin.com OR indeed.com OR seek.com OR seek.com.au "
    "OR greenhouse.io OR lever.co OR ashbyhq.com OR icims.com "
    "OR smartrecruiters.com OR myworkday.com OR workday.com "
    "OR taleo.net OR successfactors.com OR workablemail.com "
    "OR greenhouse-mail.com OR jobs.lever.co OR robertwalters.com "
    "OR robertwalters.com.au) "
    "OR subject:(interview OR interviewer OR recruiter OR recruiting "
    "OR hiring OR \"job offer\" OR \"phone screen\" OR \"talent acquisition\" "
    "OR \"job alert\" OR \"new jobs\" OR \"are you interested\" "
    "OR \"daily rate\" OR \"job application\"))"
)

# Bare "job" / "career" / "application" / "opportunity" / "role" match product
# names (aether-job-career-agent GitHub mail) and court "applications". Keep
# collocations that actually mean job-search mail.
_CAREER_SIGNAL = re.compile(
    r"("
    r"\binterview(?:er|ing|s)?\b|"
    r"\brecruiter\b|\brecruiting\b|\bhiring\b|\bheadhunt|"
    r"\btalent(?:\s+acquisition)?\b|\bstaffing\b|"
    r"\bjob[\s-]*(?:alert|offer|search|application|opening)s?\b|"
    r"\b(?:new|matching)\s+jobs\b|"
    r"\bjobs\b|"
    r"\bvacanc(?:y|ies)\b|"
    r"\bphone\s*screen\b|\bscreening\s+call\b|"
    r"\bface[\s-]*to[\s-]*face\b|\bin[\s-]*person\b|"
    r"your application (?:for|was|has been)|"
    r"application was successfully submitted|"
    r"\bapplicant\b|\bcandidacy\b|\bshortlist\b|"
    r"\b(?:cv|r[eé]sum[eé])\b|"
    r"\bare you (?:open|interested)\b|"
    r"\bopen to a chat\b|"
    r"\bdaily rate\b|"
    r"\b(?:the|this|a)\s+role\b|"
    r"greenhouse|lever\.co|workday|ashby|icims|linkedin|"
    r"\bindeed\b|\bseek\.com"
    r")",
    re.IGNORECASE,
)

_INTERVIEW_INVITE = re.compile(
    r"\b("
    r"interview|phone\s*screen|screening\s+call|hiring\s+manager|"
    r"meet(?:ing)?\s+invite|calendar\s+invite|"
    r"invitation:\s*interview|interview\s+with|"
    r"face[\s-]*to[\s-]*face|in[\s-]*person"
    r")\b",
    re.IGNORECASE,
)

_PERSONAL_SIGNAL = re.compile(
    r"\b("
    r"tenanc(?:y|ies)|residential\s+tenanc|hearing\s+reminder|"
    r"vcat|tribunal|court\s+listing|"
    r"newsletter|receipt|invoice\s+#|order\s+confirmation|"
    r"password\s+reset|verify\s+your\s+email|netflix|spotify|"
    r"facebook|instagram|twitter|whatsapp"
    r")\b",
    re.IGNORECASE,
)

#: Courts / tribunals win over a coincidental "application"/"interview" token.
_STRONG_PERSONAL = re.compile(
    r"\b("
    r"tenanc(?:y|ies)|residential\s+tenanc|hearing\s+reminder|"
    r"vcat|tribunal|court\s+listing"
    r")\b",
    re.IGNORECASE,
)

_PERSONAL_DOMAINS = frozenset(
    {
        "courts.vic.gov.au",
        "mail.courts.vic.gov.au",
        "facebookmail.com",
        "facebook.com",
        "twitter.com",
        "instagram.com",
        "netflix.com",
        "spotify.com",
        "amazon.com",
        "paypal.com",
    }
)

_CAREER_DOMAINS = (
    "linkedin.com",
    "indeed.com",
    "seek.com",
    "seek.com.au",
    "greenhouse.io",
    "greenhouse-mail.com",
    "lever.co",
    "ashbyhq.com",
    "icims.com",
    "smartrecruiters.com",
    "myworkday.com",
    "workday.com",
    "taleo.net",
    "successfactors.com",
    "workablemail.com",
    "jobs.workablemail.com",
    "robertwalters.com",
    "robertwalters.com.au",
)

#: Developer tooling and consumer marketing — never the career inbox, even
#: when a subject happens to contain "job", "career", or "interview ingest".
_NOISE_DOMAINS = frozenset(
    {
        "github.com",
        "users.noreply.github.com",
        "gitlab.com",
        "bitbucket.org",
        "vercel.com",
        "netlify.com",
        "cursor.com",
        "e.wemoney.com.au",
        "wemoney.com.au",
    }
)

_NOISE_LOCAL_PARTS = frozenset(
    {
        "customersolutions",
        "customer-solutions",
        "customersuccess",
    }
)

_AUTO_SENDER = re.compile(
    r"(noreply|no-reply|jobalerts|job-alert|notifications?|mailer-daemon|"
    r"calendar-notification)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CareerMailVerdict:
    keep: bool
    category: str
    reason: str
    is_interview_invite: bool = False


def _domain(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1]


def _haystack(*parts: Any) -> str:
    return " ".join(str(p or "") for p in parts)


def _is_career_domain(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in _CAREER_DOMAINS)


def _is_noise_sender(sender_email: str, sender: str = "") -> bool:
    email = (sender_email or "").strip().lower()
    domain = _domain(email)
    if domain in _NOISE_DOMAINS or any(domain.endswith("." + d) for d in _NOISE_DOMAINS):
        return True
    local = email.split("@", 1)[0] if "@" in email else ""
    if local in _NOISE_LOCAL_PARTS:
        return True
    blob = f"{sender} {email}".lower()
    if "cursor[bot]" in blob or "github-actions" in blob:
        return True
    return False


def classify_career_email(
    *,
    subject: str = "",
    sender: str = "",
    sender_email: str = "",
    body: str = "",
    label_ids: Optional[Iterable[str]] = None,
    has_calendar_invite: bool = False,
    is_local_draft: bool = False,
) -> CareerMailVerdict:
    """Return whether this thread belongs on the Email Center career inbox."""
    if is_local_draft:
        return CareerMailVerdict(
            keep=True,
            category="all",
            reason="local draft — never auto-hidden",
        )

    if _is_noise_sender(sender_email, sender):
        return CareerMailVerdict(
            keep=False,
            category="personal",
            reason="developer tooling / marketing — not career mail",
        )

    text = _haystack(subject, sender, sender_email, body)
    domain = _domain(sender_email)
    if domain in _PERSONAL_DOMAINS or bool(_STRONG_PERSONAL.search(text)):
        return CareerMailVerdict(
            keep=False,
            category="personal",
            reason="personal / non-career mail",
        )

    career = bool(_CAREER_SIGNAL.search(text)) or _is_career_domain(domain)
    personal = bool(_PERSONAL_SIGNAL.search(text))
    interview = bool(_INTERVIEW_INVITE.search(text)) or (
        has_calendar_invite and career
    )

    if interview:
        return CareerMailVerdict(
            keep=True,
            category="priority",
            reason="interview / meeting invite",
            is_interview_invite=True,
        )

    if has_calendar_invite and career:
        return CareerMailVerdict(
            keep=True,
            category="priority",
            reason="calendar invite with career signal",
            is_interview_invite=True,
        )

    if personal and not career:
        return CareerMailVerdict(
            keep=False,
            category="personal",
            reason="personal / non-career mail",
        )

    if not career:
        return CareerMailVerdict(
            keep=False,
            category="personal",
            reason="no career/job-search signal",
        )

    if _AUTO_SENDER.search(sender_email) or _AUTO_SENDER.search(sender):
        return CareerMailVerdict(
            keep=True,
            category="auto",
            reason="automated job-search / alert mail",
        )

    _ = label_ids  # reserved: Gmail CATEGORY_* labels are hints, not authority
    return CareerMailVerdict(
        keep=True,
        category="all",
        reason="career/job-search signal",
    )


def thread_is_local_draft(thread: dict[str, Any]) -> bool:
    return not thread.get("gmailThreadId") and not thread.get("gmailMessageId")


def classify_thread(
    thread: dict[str, Any], latest: dict[str, Any] | None = None
) -> CareerMailVerdict:
    """Classify a stored EmailThread from the FULL trail, not only the latest body.

    A confirmation that drops the word "interview" ("face to face tomorrow at
    Docklands") is still an invite when an earlier message arranged the
    interview. Latest-only classification dropped those threads from ingest.
    """
    msgs = thread.get("messages") or []
    if not isinstance(msgs, list):
        msgs = []
    latest = latest or {}
    if not latest and msgs:
        latest = msgs[-1] if isinstance(msgs[-1], dict) else {}
    bodies: list[str] = []
    has_cal = bool(latest.get("hasCalendarInvite"))
    for msg in msgs:
        if not isinstance(msg, dict):
            continue
        bodies.append(str(msg.get("body") or ""))
        if msg.get("hasCalendarInvite"):
            has_cal = True
    labels = thread.get("labels") or latest.get("labelIds") or []
    has_cal = has_cal or "CALENDAR" in {str(x).upper() for x in (labels or [])}
    return classify_career_email(
        subject=str(thread.get("subject") or ""),
        sender=str(latest.get("from") or thread.get("contact_name") or ""),
        sender_email=str(
            latest.get("fromEmail")
            or thread.get("contact_email")
            or latest.get("from")
            or ""
        ),
        body="\n".join(bodies) if bodies else str(latest.get("body") or ""),
        label_ids=labels,
        has_calendar_invite=has_cal,
        is_local_draft=thread_is_local_draft(thread),
    )


def should_auto_draft_reply(
    verdict: CareerMailVerdict,
    *,
    sender: str = "",
    sender_email: str = "",
) -> bool:
    """True only for human recruiter / hiring-manager threads.

    Never auto-draft job alerts, calendar-notification robots, GitHub, or
    other noise — those are not counterparties a candidate replies to.
    Auto-draft is review-only; this helper never authorises a send.
    """
    if not verdict.keep or verdict.category == "auto":
        return False
    if _is_noise_sender(sender_email, sender):
        return False
    if _AUTO_SENDER.search(sender_email or "") or _AUTO_SENDER.search(sender or ""):
        return False
    return verdict.is_interview_invite or verdict.category in {
        "priority",
        "followup",
        "all",
    }
