"""Job-alert email parser (W-ALERT) — the ONLY compliant AU market channel.

The candidate already receives automated job alerts from SEEK, Workforce
Australia, LinkedIn, Indeed and recruitment agencies. Those emails are HIS OWN
mail, in HIS OWN mailbox, delivered to him on purpose — reading them is
legitimate, and it is the only lawful way this product can see the Australian
market: scraping seek.com.au is refused under two binding rulings (ADR-P6-SEEK;
``discovery/adapter_registry`` keeps the Seek scraper out of the live registry).

This module is PURE: no I/O, no network, no database, no LLM. It takes the
headers and body parts of one message and returns the postings it could read
out of it. :mod:`app.agents.email_agent` (mode ``job_alerts``) is what actually
reads Gmail and persists the results through ``JobRepository.create``.

DISCIPLINE — every rule here exists to stop the parser inventing market data:

* A posting is emitted ONLY when a title, a company AND a real apply URL were
  all genuinely read out of the message. ``Job.company`` is NOT NULL, so a card
  that names no company is SKIPPED and counted, never back-filled with the
  sender's own brand or guessed out of a blurb.
* Click-tracking redirectors (``click.em.page.com/?qs=…``,
  ``email.s.seek.com.au/uni/ss/c/…``) are never accepted as a source URL: they
  are per-recipient, they expire, and they are not the listing's identity. Only
  a URL whose PATH identifies a job is taken.
* Alert-specific query parameters (``savedSearchID``, ``tracking``, ``utm_*``,
  ``alert_mode``…) are stripped, because the SAME job arrives in two different
  saved-search alerts with two different tokens — keeping them would defeat the
  ``(userId, sourceUrl)`` dedup and show one role twice.
* Salary text is kept VERBATIM and NEVER parsed into ``salaryMin``/``salaryMax``:
  real alerts mix "$1000p/d-$1150p/d", "$130 per hour", "AUD 290000 per annum"
  and "Competitive" in the same email, so a number here would be a fabrication.
* An alert email carries no job description. ``description`` is therefore the
  listing's own teaser line verbatim when the email has one, and otherwise the
  empty string — never synthesised prose.

Application-STATUS mail is explicitly not an alert: the same SEEK sender domain
also mails "the X job with Y has closed", and turning those into Job rows would
put dead listings on the board.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.services.discovery.base_adapter import JobRaw

# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

#: Platform key -> the ``Job.source`` value written for postings read out of
#: that platform's alert mail. Deliberately suffixed ``-alert`` and deliberately
#: DISTINCT from the scraper source keys: a row sourced from the candidate's own
#: inbox must never be presented as a live board fetch, and ``seek`` in
#: particular is compliance-gated out of the active feed
#: (``discovery/active_feed.prohibited_sources``) — reusing it would silently
#: hide every alert-sourced row.
ALERT_SOURCE_BY_PLATFORM: dict[str, str] = {
    "seek": "seek-alert",
    "linkedin": "linkedin-alert",
    "indeed": "indeed-alert",
    "workforceaustralia": "workforceaustralia-alert",
    "michaelpage": "michaelpage-alert",
    "generic": "email-alert",
}

#: Every source value this module can write — used by callers (and the UI) to
#: recognise inbox-sourced rows without hard-coding the list twice.
ALERT_SOURCES: frozenset[str] = frozenset(ALERT_SOURCE_BY_PLATFORM.values())

# ---------------------------------------------------------------------------
# Sender / subject recognition
# ---------------------------------------------------------------------------

#: Sender domain suffix -> platform. Matched on the SENDER's domain, so
#: ``jobmail@s.seek.com.au`` and ``noreply@mail.michaelpage.com.au`` both
#: resolve. Order matters only for readability; matching is by suffix.
_PLATFORM_BY_DOMAIN_SUFFIX: tuple[tuple[str, str], ...] = (
    ("seek.com.au", "seek"),
    ("seek.com", "seek"),
    ("linkedin.com", "linkedin"),
    ("indeed.com", "indeed"),
    ("indeed.com.au", "indeed"),
    ("workforceaustralia.gov.au", "workforceaustralia"),
    ("jobactive.gov.au", "workforceaustralia"),
    ("michaelpage.com.au", "michaelpage"),
)

#: Local-part fragments that mark a sender as an AUTOMATED mailer. Required for
#: the ``generic`` platform (an unknown domain only counts when the sender is
#: itself automated) and as a second gate on the known platforms.
_AUTOMATED_LOCAL_PARTS: tuple[str, ...] = (
    "jobalert", "job-alert", "jobmail", "jobsalert", "jobs-alert",
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "alert", "alerts", "notification", "notifications", "mailer",
)

#: Subject shapes that mark a message as a NEW-POSTINGS alert. Verified against
#: the real subjects in the operator's mailbox ("20 new jobs for enterprise
#: architect in Melbourne VIC 3000", "New jobs for: Information Technology :
#: Melbourne").
_ALERT_SUBJECT_RE = re.compile(
    r"\b\d+\s+new\s+jobs?\b"
    r"|\bnew\s+jobs?\b\s*(?::|\bfor\b|\bmatching\b|\bin\b|\bnear\b|\badded\b)"
    r"|\bjobs?\s+for\s+you\b"
    r"|\bjob\s+alerts?\b"
    r"|\bjobs?\s+matching\b"
    r"|\brecommended\s+(?:jobs|for\s+you)\b"
    r"|\bjobs?\s+you\s+may\b"
    r"|\blatest\b.{0,40}\bjobs\b",
    re.IGNORECASE,
)

#: Subject shapes that are NEVER a new-postings alert even from an alert sender:
#: application status, account/billing mail. Checked FIRST — SEEK mails "…has
#: closed" from the same domain as its job alerts, about roles that are shut.
_NOT_ALERT_SUBJECT_RE = re.compile(
    r"\bhas\s+closed\b"
    r"|\bjob\s+is\s+no\s+longer\b"
    r"|\byour\s+application\b"
    r"|\bapplication\s+(?:was|has|received|update)\b"
    r"|\bunsuccessful\b"
    r"|\binvoice\b|\bpayment\b|\breceipt\b|\bbilling\b"
    r"|\bpassword\b|\bsecurity\s+alert\b|\bverify\s+your\b",
    re.IGNORECASE,
)

_ADDRESS_RE = re.compile(r"<([^<>]+)>")


def _sender_address(from_header: str) -> str:
    raw = (from_header or "").strip()
    match = _ADDRESS_RE.search(raw)
    if match:
        raw = match.group(1)
    return raw.strip().strip('"').lower()


def detect_alert_platform(from_header: str, subject: str) -> str | None:
    """The alert platform this message came from, or ``None`` when it is not a
    job-alert email at all.

    Three independent gates, ALL of which must pass — recognition is
    deliberately conservative because a false positive writes junk into the
    candidate's real job board:

    1. the subject must not look like application-status / account mail;
    2. the subject must look like a new-postings alert;
    3. the sender must be an automated mailer, on a known job-platform domain
       or (for ``generic``) any domain with an automated local part.
    """
    subject = subject or ""
    if _NOT_ALERT_SUBJECT_RE.search(subject):
        return None
    if not _ALERT_SUBJECT_RE.search(subject):
        return None

    address = _sender_address(from_header)
    if "@" not in address:
        return None
    local, _, domain = address.partition("@")
    if not any(fragment in local for fragment in _AUTOMATED_LOCAL_PARTS):
        return None
    for suffix, platform in _PLATFORM_BY_DOMAIN_SUFFIX:
        if domain == suffix or domain.endswith("." + suffix):
            return platform
    return "generic"


# ---------------------------------------------------------------------------
# Extracted posting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlertPosting:
    """One posting read out of one alert email. Every field is verbatim."""

    title: str
    company: str
    source_url: str
    source: str
    location: str | None = None
    description: str = ""
    #: The listing's salary/teaser line exactly as the email printed it. NEVER
    #: converted to numbers — see the module docstring.
    salary_text: str | None = None
    #: Always ``None``. Present so callers can see, in the type, that the alert
    #: channel deliberately supplies no numeric salary.
    salary_min: int | None = None
    salary_max: int | None = None
    #: ISO date (``YYYY-MM-DD``) when the email stated one, else ``None``.
    posted_at: str | None = None
    remote: bool = False

    def to_job_raw(self) -> JobRaw:
        """The ``JobRaw`` the existing ``JobRepository.create`` path accepts, so
        sourceUrl normalisation, dedupHash, contentHash and ``lastSeenAt`` all
        apply exactly as they do for every board adapter."""
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "remote": self.remote,
            "description": self.description,
            "requirements": [],
            "source": self.source,
            "sourceUrl": self.source_url,
            "postedAt": self.posted_at,
            "salaryMin": None,
            "salaryMax": None,
            "currency": None,
        }


@dataclass
class ParsedAlert:
    """What one alert email yielded."""

    platform: str | None
    source: str | None
    postings: list[AlertPosting] = field(default_factory=list)
    #: Real job URLs found in the body (whether or not they became postings).
    job_urls_found: int = 0
    #: Job URLs deliberately DROPPED because a required field could not be read
    #: without inventing it.
    skipped: int = 0
    #: Plain-English account of what happened — surfaced in the agent run so a
    #: zero-posting alert is explained rather than silently empty.
    reason: str = ""


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------

#: Query params that identify the ALERT, not the job. Stripped so the same
#: listing arriving in two different saved-search alerts dedups to one row.
_ALERT_QUERY_PARAMS: frozenset[str] = frozenset(
    {
        # SEEK job alerts
        "savedsearchid", "tracking", "sitekey", "daterange",
        # Michael Page / Salesforce Marketing Cloud
        "alert_mode",
        # LinkedIn alert mail
        "refid", "trackingid", "trk", "trkemail", "lipi", "licu",
        "midtoken", "midsig", "eid",
        # Indeed / generic alert mail
        "jobalertid", "searchrequesttoken", "token", "from", "alid",
        # Ubiquitous campaign tracking
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "utm_id", "mc_cid", "mc_eid",
    }
)

#: Path shapes that identify a JOB. A click-tracking redirector has no such
#: path (``click.em.page.com/?qs=…`` is just ``/``), so this single rule keeps
#: per-recipient tracker URLs out of ``sourceUrl`` without an allow/deny list of
#: tracker hostnames.
_JOB_PATH_RE = re.compile(
    r"/jobs?/view/[\w%-]+"
    r"|/jobs?/\d+"
    r"|/job/[\w%-]{2,}"
    r"|/job-detail/"
    r"|/job-details/"
    r"|/jobs/details/"
    r"|/viewjob(?:\b|/)"
    r"|/jobs/[\w%-]+-\d{4,}",
    re.IGNORECASE,
)


def canonical_job_url(url: str) -> str | None:
    """The listing's stable identity URL, or ``None`` when ``url`` does not
    identify a job at all (a tracker, a footer link, an image).

    Keeps scheme/host/path verbatim (lower-cased host, no trailing slash) and
    drops only alert-tracking query parameters, so what remains is a URL the
    candidate can actually open.
    """
    if not url:
        return None
    url = _html.unescape(url.strip())
    if not url.lower().startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.hostname or not _JOB_PATH_RE.search(parsed.path or ""):
        return None
    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in _ALERT_QUERY_PARAMS
    ]
    path = (parsed.path or "").rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.hostname.lower(),
            path,
            "",
            urlencode(kept),
            "",
        )
    )


# ---------------------------------------------------------------------------
# SEEK
# ---------------------------------------------------------------------------

#: A SEEK job URL as it appears in the alert's text/plain part. SEEK's HTML part
#: routes every card through ``email.s.seek.com.au/uni/ss/c/…`` (per-recipient,
#: expiring), while the text/plain alternative carries the REAL
#: ``au.seek.com/job/<id>`` URL — so the text part is what we read.
#: The optional surrounding ``[ ]`` is part of the match on purpose: the
#: text/plain renderer wraps every link in brackets, and consuming them keeps
#: the stray ``[`` / ``]`` out of the paragraph blocks either side of the URL
#: (a leftover bracket would read as a one-line paragraph and shift the whole
#: title/company/location alignment by one).
_SEEK_JOB_URL_RE = re.compile(
    r"\[?(?P<url>https?://(?:[a-z0-9-]+\.)*seek\.com(?:\.au)?/job/\d+"
    r"[^\s\]\)<>\"']*)\]?",
    re.IGNORECASE,
)

#: Lines that are template chrome rather than listing content.
_SEEK_NOISE_LINE_RE = re.compile(r"^(?:logo|seek|apple store|google play)$", re.I)

#: A line that is only a bracketed URL / a bare URL (image + link markers the
#: text/plain renderer emits).
_URL_ONLY_LINE_RE = re.compile(r"^\[?https?://\S+$|^\[https?://[^\]]*\]$", re.I)

#: An Australian location line, e.g. "Melbourne VIC", "Clayton, Melbourne VIC",
#: "Sydney NSW 2000". Anchored end-to-end so the greeting line ("Based on your
#: saved search for enterprise architect in Melbourne VIC 3000, we've") can
#: never be mistaken for one.
_AU_LOCATION_RE = re.compile(
    r"^[A-Za-zÀ-ÿ'’./&\- ]+(?:,\s*[A-Za-zÀ-ÿ'’./&\- ]+)*\s+"
    r"(?:VIC|NSW|QLD|WA|SA|TAS|ACT|NT)(?:\s+\d{4})?$"
)
_GENERIC_LOCATION_RE = re.compile(
    r"^(?:remote|work from home|australia|anywhere)\b.*$", re.IGNORECASE
)

_SEEK_POSTED_ON_RE = re.compile(r"^Posted on\s+(\d{1,2}\s+\w{3,}\s+\d{4})$", re.I)

#: Max paragraphs allowed between the title/company paragraph and the location
#: paragraph (SEEK puts at most a badge or two there, each its own paragraph).
_SEEK_MAX_BADGE_PARAGRAPHS = 3


def _looks_like_location(line: str) -> bool:
    return bool(_AU_LOCATION_RE.match(line) or _GENERIC_LOCATION_RE.match(line))


def _parse_posted_on(line: str) -> str | None:
    match = _SEEK_POSTED_ON_RE.match(line)
    if not match:
        return None
    raw = match.group(1)
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _seek_paragraphs(block: str) -> list[list[str]]:
    """Blank-line-delimited paragraphs of ``block``, chrome removed.

    SEEK's text/plain alternative is strictly paragraph-structured, and that
    structure is what makes extraction deterministic rather than positional
    guesswork:

        logo                      <- chrome paragraph (dropped)
        [https://…/serpLogo]
                                  <- blank
        Solution Architect        <- title
        Talent                    <- company
                                  <- blank
        Strong applicant          <- optional badge paragraph
                                  <- blank
        Melbourne VIC             <- location (+ optional "Posted on …",
        $1000p/d-$1150p/d            + optional salary/teaser line)
                                  <- blank
        [https://au.seek.com/job/93696282?…]
    """
    paragraphs: list[list[str]] = []
    for chunk in re.split(r"\n\s*\n", block):
        lines = [line.strip() for line in chunk.splitlines()]
        lines = [
            line
            for line in lines
            if line
            and not _SEEK_NOISE_LINE_RE.match(line)
            and not _URL_ONLY_LINE_RE.match(line)
        ]
        if lines:
            paragraphs.append(lines)
    return paragraphs


def _parse_seek(text: str, source: str) -> ParsedAlert:
    result = ParsedAlert(platform="seek", source=source)
    previous_end = 0
    for match in _SEEK_JOB_URL_RE.finditer(text):
        block = text[previous_end : match.start()]
        previous_end = match.end()
        url = canonical_job_url(match.group("url"))
        if url is None:
            continue
        result.job_urls_found += 1

        paragraphs = _seek_paragraphs(block)
        if not paragraphs:
            result.skipped += 1
            continue
        tail = paragraphs[-1]
        # Walk back past the badge paragraphs to the title/company paragraph.
        headline: list[str] | None = None
        for paragraph in reversed(
            paragraphs[max(0, len(paragraphs) - 1 - _SEEK_MAX_BADGE_PARAGRAPHS) : -1]
        ):
            if len(paragraph) >= 2:
                headline = paragraph
                break
        if headline is None:
            # No paragraph carrying both a title and a company — refuse rather
            # than promote a single line to both fields.
            result.skipped += 1
            continue

        title, company = headline[0], headline[1]
        location: str | None = None
        posted_at: str | None = None
        teaser: list[str] = []
        for line in tail:
            iso = _parse_posted_on(line)
            if iso:
                posted_at = iso
                continue
            if location is None and _looks_like_location(line):
                location = line
                continue
            teaser.append(line)
        if not title.strip() or not company.strip():
            result.skipped += 1
            continue
        salary_text = teaser[0] if teaser else None
        result.postings.append(
            AlertPosting(
                title=title,
                company=company,
                source_url=url,
                source=source,
                location=location,
                description=" ".join(teaser).strip(),
                salary_text=salary_text,
                posted_at=posted_at,
                remote=bool(location and "remote" in location.lower()),
            )
        )
    if not result.postings:
        result.reason = (
            "No SEEK job cards could be read out of this alert — it carried "
            f"{result.job_urls_found} job link(s)."
        )
    return result


# ---------------------------------------------------------------------------
# Generic HTML-anchor extraction (LinkedIn / Indeed / Workforce Australia /
# recruitment agencies)
# ---------------------------------------------------------------------------

#: Both real href carriers in HTML mail: the ordinary anchor, and Outlook's
#: VML button (``<v:roundrect href=…>``), which is where Michael Page puts the
#: genuine michaelpage.com.au URL while the visible anchor points at its click
#: tracker.
_ANCHOR_RE = re.compile(
    r"<a\b[^>]*?\bhref\s*=\s*([\"'])(?P<url>.*?)\1[^>]*>(?P<label>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_VML_HREF_RE = re.compile(
    r"<v:roundrect\b[^>]*?\bhref\s*=\s*([\"'])(?P<url>.*?)\1",
    re.IGNORECASE | re.DOTALL,
)

_TAG_RE = re.compile(r"<[^>]+>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL
)

#: A "Company · Location" / "Company - Location" line — the one card shape from
#: which a company can be read WITHOUT guessing. Anything else is skipped.
_COMPANY_LOCATION_RE = re.compile(r"^(?P<company>[^·•|]{2,120}?)\s*[·•|]\s*(?P<location>.{2,120})$")

#: Anchor labels that are template chrome, never a job title.
_CHROME_LABELS = frozenset(
    {
        "view job", "view jobs", "apply", "apply now", "see job", "see jobs",
        "browse more jobs", "view all jobs", "view all matching jobs",
        "more jobs", "unsubscribe", "modify this job alert", "edit this alert",
        "view details", "read more", "learn more", "click here", "here",
    }
)


def _visible_text(html: str) -> list[str]:
    stripped = _SCRIPT_STYLE_RE.sub(" ", html)
    stripped = _COMMENT_RE.sub(" ", stripped)
    stripped = re.sub(r"<br\s*/?>|</(?:p|div|td|tr|li|h\d)>", "\n", stripped, flags=re.I)
    stripped = _TAG_RE.sub("\n", stripped)
    lines = [_html.unescape(line).strip() for line in stripped.splitlines()]
    return [re.sub(r"\s+", " ", line) for line in lines if line.strip()]


def _anchor_label(raw_label: str) -> str:
    text = _TAG_RE.sub(" ", raw_label or "")
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _parse_html_anchors(html: str, platform: str, source: str) -> ParsedAlert:
    """Read postings out of an HTML alert body via its real job anchors.

    Conservative by construction: a posting needs a job-shaped URL, a title
    (the anchor's own visible label) and a company read from an explicit
    ``Company · Location`` card line. Anything short of that is counted as
    skipped, with the reason reported — the alternative would be inventing an
    employer, and the whole product rests on not doing that.
    """
    result = ParsedAlert(platform=platform, source=source)
    lines = _visible_text(html)
    line_index: dict[str, int] = {}
    for index, line in enumerate(lines):
        line_index.setdefault(line.casefold(), index)

    candidates: dict[str, str] = {}  # canonical url -> anchor label
    for match in _ANCHOR_RE.finditer(html):
        url = canonical_job_url(match.group("url"))
        if url is None:
            continue
        label = _anchor_label(match.group("label"))
        if label.casefold() in _CHROME_LABELS:
            label = ""
        if url not in candidates or (label and not candidates[url]):
            candidates[url] = label
    for match in _VML_HREF_RE.finditer(html):
        url = canonical_job_url(match.group("url"))
        if url is not None:
            candidates.setdefault(url, "")

    missing_title = 0
    missing_company = 0
    for url, label in candidates.items():
        result.job_urls_found += 1
        if not label:
            missing_title += 1
            result.skipped += 1
            continue
        label_at = line_index.get(label.casefold())
        company: str | None = None
        location: str | None = None
        if label_at is not None:
            for following in lines[label_at + 1 : label_at + 4]:
                card = _COMPANY_LOCATION_RE.match(following)
                if card:
                    company = card.group("company").strip()
                    location = card.group("location").strip()
                    break
        if not company:
            missing_company += 1
            result.skipped += 1
            continue
        result.postings.append(
            AlertPosting(
                title=label,
                company=company,
                source_url=url,
                source=source,
                location=location,
                remote=bool(location and "remote" in location.lower()),
            )
        )

    if not result.postings:
        parts = []
        if missing_title:
            parts.append(f"{missing_title} link(s) carried no job title")
        if missing_company:
            parts.append(f"{missing_company} link(s) named no company")
        detail = "; ".join(parts) if parts else "no job links were present"
        result.reason = (
            f"No postings could be read from this {platform} alert without "
            f"inventing a field ({detail}). Nothing was fabricated."
        )
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_job_alert(
    *,
    from_header: str,
    subject: str,
    text: str | None = None,
    html: str | None = None,
) -> ParsedAlert:
    """Parse ONE message. Returns an empty :class:`ParsedAlert` (never raises)
    when the message is not a job alert or nothing could be read honestly."""
    platform = detect_alert_platform(from_header, subject)
    if platform is None:
        return ParsedAlert(
            platform=None,
            source=None,
            reason="Not a job-alert email.",
        )
    source = ALERT_SOURCE_BY_PLATFORM[platform]

    if platform == "seek":
        # SEEK's HTML routes every card through a per-recipient tracker; only
        # the text/plain alternative carries the real au.seek.com/job/<id> URL.
        if text and _SEEK_JOB_URL_RE.search(text):
            return _parse_seek(text, source)
        if html:
            return _parse_html_anchors(html, platform, source)
        return ParsedAlert(
            platform=platform,
            source=source,
            reason=(
                "This SEEK alert carried no readable job links — its plain-text "
                "part was empty and its HTML links only through a tracker."
            ),
        )

    if html:
        return _parse_html_anchors(html, platform, source)
    return ParsedAlert(
        platform=platform,
        source=source,
        reason=f"This {platform} alert carried no HTML body to read links from.",
    )


def postings_to_job_raws(postings: list[AlertPosting]) -> list[dict[str, Any]]:
    """Convenience for callers persisting through ``JobRepository.create``."""
    return [dict(posting.to_job_raw()) for posting in postings]
