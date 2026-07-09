"""Relevance filtering for live job discovery (D11).

The user targets Senior Technical Delivery Lead / Product Owner / Lead
Business Analyst roles from Melbourne, Australia. Live sources return
hundreds of postings worldwide; this module keeps only postings that are

1. a **target role** (delivery/program/project management, product
   owner/manager, business analysis, agile leadership), and
2. **applicable from Australia** — an AU location, or a remote role that is
   not explicitly restricted to another region.

Pure functions, no I/O — unit-testable without HTTP.
"""
from __future__ import annotations

import html
import re

from app.services.discovery.base_adapter import JobRaw

#: Titles that match Vikram's target roles. Deliberately NOT engineering-only.
TARGET_ROLE_RE = re.compile(
    r"delivery\s+(?:lead|manager|director)"
    r"|head\s+of\s+delivery"
    r"|program(?:me)?\s+manager"
    r"|project\s+manager"
    r"|product\s+owner"
    r"|product\s+manager"
    r"|business\s+analyst"
    r"|scrum\s+master"
    r"|agile\s+(?:coach|delivery)"
    r"|iteration\s+manager"
    r"|transformation\s+(?:lead|manager)"
    r"|technical\s+program"
    r"|engagement\s+manager"
    r"|implementation\s+(?:lead|manager)",
    re.IGNORECASE,
)

#: Substrings that mark an Australia/NZ/APAC-friendly location.
_AU_SUBSTRINGS = (
    "australia",
    "melbourne",
    "sydney",
    "brisbane",
    "perth",
    "adelaide",
    "canberra",
    "hobart",
    "new zealand",
    "auckland",
    "wellington",
    "apac",
    "asia-pacific",
    "asia pacific",
    "oceania",
    "anz",
)
#: Short AU tokens matched on word boundaries (avoid false hits inside words).
_AU_TOKEN_RE = re.compile(r"\b(au|aus|nsw|vic|qld)\b", re.IGNORECASE)

#: Locations explicitly restricted to a non-APAC region — not applicable
#: from Melbourne even when "remote".
_BLOCKED_RE = re.compile(
    r"\b(us|usa|u\.s\.?a?\.?|united states|america[sn]?|amer|canada|toronto|vancouver"
    r"|sf|san francisco|ny|nyc|new york|sea|seattle|chicago|atlanta|austin|boston"
    r"|uk|united kingdom|london|ireland|dublin|europe|european|emea|germany|berlin"
    r"|france|paris|poland|spain|portugal|netherlands|israel|tel aviv"
    r"|latam|latin america|mexico|brazil|argentina"
    r"|india|bengaluru|bangalore|mumbai|delhi|pakistan"
    r"|japan|tokyo|singapore|philippines|china|hong kong|korea"
    r"|africa|middle east|dubai|cst|est|pst|edt|pdt)\b",
    re.IGNORECASE,
)

_REMOTE_RE = re.compile(r"\b(remote|worldwide|anywhere|global|distributed)\b", re.IGNORECASE)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def is_target_role(title: str) -> bool:
    """True when the posting title matches one of the target role families."""
    return bool(TARGET_ROLE_RE.search(title or ""))


def location_score(location: str | None, remote: bool = False) -> int:
    """Rank a location for a Melbourne-based candidate.

    2 → Australia/NZ/APAC location; 1 → remote and not region-restricted;
    0 → not applicable (onsite elsewhere, or remote locked to another region).
    """
    loc = (location or "").strip()
    lowered = loc.lower()
    if any(marker in lowered for marker in _AU_SUBSTRINGS) or _AU_TOKEN_RE.search(loc):
        return 2
    is_remote = remote or bool(_REMOTE_RE.search(lowered)) or loc == ""
    if is_remote and not _BLOCKED_RE.search(loc):
        return 1
    return 0


def is_relevant(job: JobRaw) -> bool:
    """Target role AND applicable location.

    Region locks sometimes live in the *title* (e.g. "Engagement Manager -
    EMEA" with location "Remote"); those are not applicable from Melbourne
    unless the location itself is an AU/APAC one.
    """
    title = job.get("title", "")
    if not is_target_role(title):
        return False
    score = location_score(job.get("location"), bool(job.get("remote")))
    if score == 1 and _BLOCKED_RE.search(title):
        return False
    return score > 0


def filter_relevant(jobs: list[JobRaw]) -> list[JobRaw]:
    """Keep relevant postings, AU locations first."""
    kept = [job for job in jobs if is_relevant(job)]
    kept.sort(
        key=lambda j: location_score(j.get("location"), bool(j.get("remote"))),
        reverse=True,
    )
    return kept


def snippet(text: str | None, limit: int = 500) -> str:
    """Strip HTML tags/entities and collapse whitespace into a short snippet."""
    plain = _WS_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(text or ""))).strip()
    return plain[:limit].rstrip()
