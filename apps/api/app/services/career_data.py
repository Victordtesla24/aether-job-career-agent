"""Career-data consolidation service (GAP-P4-047 · ADR D-0031).

Ingests the user's real, publicly available career signal into a persisted
workspace store (``CareerProfile``) and assembles it into the evidence corpus
the resume-tailoring and cover-letter agents draw on. Three sources:

* **GitHub** — public REST API (``scrape_github_profile``): languages, top
  repos, README-style descriptions. Unauthenticated, rate-limited; failures
  surface as an explicit per-source error, never as silence.
* **Portfolio** — the user's portfolio site is fetched and parsed for real
  (title, meta description, schema.org ``Person`` data, visible text).
* **LinkedIn** — workspace-stored profile text only. LinkedIn exposes no
  general profile API to third-party apps (D-0031), so nothing is scraped;
  content enters the system only if the user pastes it. This is an honest,
  documented limitation, surfaced as an explicit "empty" state with guidance.

Design contract (§6): production code performs **real** network fetches; the
optional ``*_fetch`` callables exist solely so tests can inject deterministic
payloads without touching the network. No fabricated data is ever stored — a
source that cannot be ingested yields ``status='error'`` (or ``'empty'``) with
a human-readable explanation, and contributes nothing to the evidence corpus.
"""
from __future__ import annotations

import csv
import html as _html
import io
import json
import re
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser
from typing import Any, Callable, Optional

from app.repositories.career_profile import CAREER_SOURCES, CareerProfileRepository
from app.services.portfolio_scraper import scrape_github_profile

_USER_AGENT = "aether-career-data/1.0"
#: Hard cap on a LinkedIn "Download your data" export upload (B7) — the same
#: ceiling ``routers/resumes.py`` uses for résumé uploads.
MAX_LINKEDIN_EXPORT_BYTES = 10 * 1024 * 1024
#: The only files B7 reads out of a LinkedIn export zip. LinkedIn's export
#: bundles dozens of CSVs (ads, messages, connections, …) the candidate never
#: asked to share with a career-tailoring tool — everything else in the
#: archive is ignored, unopened.
LINKEDIN_EXPORT_FILES = ("Profile.csv", "Positions.csv", "Education.csv", "Skills.csv")
#: Chunk size used to stream-decompress each matched export CSV out of the
#: zip (B7 zip-bomb guard). Small and fixed so a hostile entry's stated
#: ``file_size`` metadata (attacker-controlled, never trusted) can't matter —
#: the running total below is measured from actual bytes read.
_LINKEDIN_EXPORT_READ_CHUNK_BYTES = 64 * 1024
_LINKEDIN_EXPORT_BASENAME_MAP = {name.lower(): name for name in LINKEDIN_EXPORT_FILES}
#: Cap the portfolio download so a hostile/huge page can't exhaust memory.
_MAX_HTML_BYTES = 2_000_000
#: Cap the extracted portfolio text folded into the evidence corpus.
_MAX_TEXT_CHARS = 4000
_WHITESPACE_RE = re.compile(r"\s+")
_LDJSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


# ---------------------------------------------------------------------------
# HTML → text
# ---------------------------------------------------------------------------


class _VisibleTextParser(HTMLParser):
    """Collect human-visible text, skipping ``script`` / ``style`` / ``noscript``."""

    _SKIP = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._chunks.append(stripped)

    @property
    def text(self) -> str:
        return _WHITESPACE_RE.sub(" ", " ".join(self._chunks)).strip()


def _visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return parser.text


def _extract_title(html: str) -> Optional[str]:
    match = _TITLE_RE.search(html)
    if not match:
        return None
    return _html.unescape(_WHITESPACE_RE.sub(" ", match.group(1)).strip()) or None


def _extract_meta_description(html: str) -> Optional[str]:
    match = _META_DESC_RE.search(html)
    return _html.unescape(match.group(1).strip()) if match else None


def _extract_person(html: str) -> Optional[dict[str, Any]]:
    """Pull a schema.org ``Person`` block from JSON-LD, if present."""
    for block in _LDJSON_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            if entry.get("@type") == "Person":
                works_for = entry.get("worksFor")
                if isinstance(works_for, dict):
                    works_for = works_for.get("name")
                same_as = entry.get("sameAs")
                if isinstance(same_as, str):
                    same_as = [same_as]
                return {
                    "name": entry.get("name"),
                    "jobTitle": entry.get("jobTitle"),
                    "worksFor": works_for,
                    "sameAs": same_as if isinstance(same_as, list) else None,
                }
    return None


def parse_portfolio_html(html: str, url: str = "") -> dict[str, Any]:
    """Normalize a portfolio page into structured, evidence-usable content."""
    text = _visible_text(html)
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS].rstrip() + " …"
    return {
        "url": url,
        "title": _extract_title(html),
        "description": _extract_meta_description(html),
        "person": _extract_person(html),
        "text": text,
    }


# ---------------------------------------------------------------------------
# Summaries (flattened text folded into the tailoring / cover-letter corpus)
# ---------------------------------------------------------------------------


def summarize_github(profile: dict[str, Any]) -> str:
    """Readable GitHub evidence: identity, counts, languages, notable repos."""
    lines: list[str] = []
    ident = profile.get("name") or profile.get("username") or "GitHub user"
    username = profile.get("username")
    header = f"GitHub profile: {ident}"
    if username and username != ident:
        header += f" (@{username})"
    header += (
        f" — {int(profile.get('public_repos', 0) or 0)} public repos, "
        f"{int(profile.get('total_stars', 0) or 0)} total stars."
    )
    lines.append(header)
    if profile.get("bio"):
        lines.append(str(profile["bio"]))
    langs = profile.get("top_languages") or []
    if langs:
        lines.append("Top languages: " + ", ".join(str(x) for x in langs) + ".")
    repos = profile.get("top_repos") or []
    if repos:
        lines.append("Notable repositories:")
        for repo in repos:
            name = repo.get("name", "")
            lang = repo.get("language")
            stars = int(repo.get("stars", 0) or 0)
            desc = (repo.get("description") or "").strip()
            meta = ", ".join(p for p in (lang, f"{stars} stars" if stars else "") if p)
            entry = f"- {name}"
            if meta:
                entry += f" ({meta})"
            if desc:
                entry += f": {desc}"
            lines.append(entry)
    return "\n".join(lines).strip()


def summarize_portfolio(parsed: dict[str, Any]) -> str:
    """Readable portfolio evidence from parsed page content."""
    lines: list[str] = []
    if parsed.get("title"):
        lines.append(f"Portfolio: {parsed['title']}")
    if parsed.get("description"):
        lines.append(str(parsed["description"]))
    person = parsed.get("person") or {}
    if person.get("name"):
        who = person["name"]
        role = person.get("jobTitle")
        org = person.get("worksFor")
        if role and org and org.lower() not in role.lower():
            lines.append(f"{who} — {role} at {org}.")
        elif role:
            lines.append(f"{who} — {role}.")
    if parsed.get("text"):
        lines.append(str(parsed["text"]))
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Real fetchers (production path)
# ---------------------------------------------------------------------------


def _fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
        charset = response.headers.get_content_charset() or "utf-8"
        raw = response.read(_MAX_HTML_BYTES)
    return raw.decode(charset, errors="replace")


def _github_error(username: str, exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return f"GitHub user '{username}' was not found (HTTP 404)."
        if exc.code in (403, 429):
            return (
                "GitHub API rate limit reached for unauthenticated requests. "
                "Try the refresh again in a little while."
            )
        return f"GitHub API returned HTTP {exc.code}."
    if isinstance(exc, urllib.error.URLError):
        return f"Could not reach the GitHub API: {exc.reason}."
    return f"GitHub ingestion failed: {exc}"


def _portfolio_error(url: str, exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"Portfolio site returned HTTP {exc.code} for {url}."
    if isinstance(exc, urllib.error.URLError):
        return f"Could not reach the portfolio site {url}: {exc.reason}."
    return f"Portfolio ingestion failed: {exc}"


# ---------------------------------------------------------------------------
# Per-source ingestion
# ---------------------------------------------------------------------------


def ingest_github(
    username: Optional[str],
    *,
    fetch: Optional[Callable[[str], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Ingest a public GitHub profile. ``fetch`` (tests) returns the
    ``{profile, repos}`` payload; production hits the live API."""
    if not username or not username.strip():
        return {
            "source": "github",
            "status": "empty",
            "url": None,
            "content": None,
            "summary": None,
            "error": (
                "No GitHub username configured. Add your GitHub username in "
                "Career Data settings to include your public repos in tailoring."
            ),
        }
    username = username.strip()
    fallback_url = f"https://github.com/{username}"
    try:
        fixture = fetch(username) if fetch is not None else None
        profile = scrape_github_profile(username, fixture=fixture)
    except Exception as exc:  # noqa: BLE001 — surfaced honestly as an error state
        return {
            "source": "github",
            "status": "error",
            "url": fallback_url,
            "content": None,
            "summary": None,
            "error": _github_error(username, exc),
        }
    summary = summarize_github(profile)
    return {
        "source": "github",
        "status": "ok",
        "url": profile.get("profile_url") or fallback_url,
        "content": dict(profile),
        "summary": summary,
        "error": None,
    }


def ingest_portfolio(
    url: Optional[str],
    *,
    fetch: Optional[Callable[[str], str]] = None,
) -> dict[str, Any]:
    """Fetch + parse a portfolio site. ``fetch`` (tests) returns HTML;
    production downloads it for real."""
    if not url or not url.strip():
        return {
            "source": "portfolio",
            "status": "empty",
            "url": None,
            "content": None,
            "summary": None,
            "error": (
                "No portfolio URL configured. Add your portfolio URL in Career "
                "Data settings to include it in tailoring."
            ),
        }
    url = url.strip()
    try:
        html = fetch(url) if fetch is not None else _fetch_html(url)
    except Exception as exc:  # noqa: BLE001 — surfaced honestly as an error state
        return {
            "source": "portfolio",
            "status": "error",
            "url": url,
            "content": None,
            "summary": None,
            "error": _portfolio_error(url, exc),
        }
    parsed = parse_portfolio_html(html, url)
    summary = summarize_portfolio(parsed)
    if not summary.strip():
        return {
            "source": "portfolio",
            "status": "empty",
            "url": url,
            "content": parsed,
            "summary": None,
            "error": "Portfolio page returned no extractable text content.",
        }
    return {
        "source": "portfolio",
        "status": "ok",
        "url": url,
        "content": parsed,
        "summary": summary,
        "error": None,
    }


def ingest_linkedin(summary_text: Optional[str]) -> dict[str, Any]:
    """LinkedIn is workspace-paste-only (D-0031) — no scraping ever occurs."""
    text = (summary_text or "").strip()
    if not text:
        return {
            "source": "linkedin",
            "status": "empty",
            "url": None,
            "content": None,
            "summary": None,
            "error": (
                "LinkedIn has no public profile API available to this app "
                "(ADR D-0031). Paste your LinkedIn summary in Career Data "
                "settings to include it in tailoring."
            ),
        }
    return {
        "source": "linkedin",
        "status": "ok",
        "url": None,
        "content": {"summary": text, "source": "workspace-paste"},
        "summary": f"LinkedIn summary (provided by the candidate):\n{text}",
        "error": None,
    }


# ---------------------------------------------------------------------------
# LinkedIn data-export upload (B7) — compliant, upload-based, NEVER scraped.
#
# LinkedIn's official "Download your data" export is a zip of CSVs. This is a
# second *input* path only — it makes no network call of any kind (no
# ``urllib``/``requests``/``httpx``, nothing touches linkedin.com) and it
# produces the exact same free-text shape the candidate-paste path produces,
# then hands that text to the SAME ``ingest_linkedin`` above. There is
# deliberately no second ingestion pipeline: everything downstream (storage
# shape, corpus assembly, empty/error semantics) is inherited for free.
# ---------------------------------------------------------------------------


def _parse_csv_rows(text: str) -> list[dict[str, str]]:
    """Rows of one export CSV, or ``[]`` for an absent/blank file."""
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    return [{k: (v or "") for k, v in row.items() if k} for row in reader]


def normalize_linkedin_export(csv_texts: dict[str, str]) -> tuple[str, dict[str, int]]:
    """Turn LinkedIn export CSVs into the same free-text shape a candidate
    would type into the paste box, plus an honest per-section ingested count.

    ``csv_texts`` maps a subset of :data:`LINKEDIN_EXPORT_FILES` to decoded
    CSV text; a missing key means "not present in this export/upload" and is
    never an error — a partial export (e.g. only ``Positions.csv``) still
    normalizes whatever sections it has.
    """
    counts = {"profile": 0, "positions": 0, "education": 0, "skills": 0}
    lines: list[str] = []

    profile_rows = _parse_csv_rows(csv_texts.get("Profile.csv", ""))
    if profile_rows:
        row = profile_rows[0]
        name = " ".join(
            p for p in (row.get("First Name", "").strip(), row.get("Last Name", "").strip()) if p
        )
        headline = row.get("Headline", "").strip()
        summary = row.get("Summary", "").strip()
        header = f"{name} — {headline}" if name and headline else (name or headline)
        if header:
            lines.append(header)
            counts["profile"] = 1
        if summary:
            lines.append(summary)
            counts["profile"] = 1

    position_rows = [
        r for r in _parse_csv_rows(csv_texts.get("Positions.csv", "")) if any(r.values())
    ]
    if position_rows:
        lines += ["", "Experience:"]
        for row in position_rows:
            title = row.get("Title", "").strip()
            company = row.get("Company Name", "").strip()
            head = " at ".join(p for p in (title, company) if p)
            started = row.get("Started On", "").strip()
            finished = row.get("Finished On", "").strip()
            span = " – ".join(p for p in (started, finished) if p)
            entry = f"- {head}" if head else "-"
            if span:
                entry += f" ({span})"
            desc = row.get("Description", "").strip()
            if desc:
                entry += f": {desc}"
            lines.append(entry)
        counts["positions"] = len(position_rows)

    education_rows = [
        r for r in _parse_csv_rows(csv_texts.get("Education.csv", "")) if any(r.values())
    ]
    if education_rows:
        lines += ["", "Education:"]
        for row in education_rows:
            degree = row.get("Degree Name", "").strip()
            field = row.get("Field Of Study", "").strip()
            head = f"{degree}, {field}" if degree and field else (degree or field)
            entry = f"- {head}" if head else "-"
            school = row.get("School Name", "").strip()
            if school:
                entry += f" — {school}"
            start = row.get("Start Date", "").strip()
            end = row.get("End Date", "").strip()
            span = " – ".join(p for p in (start, end) if p)
            if span:
                entry += f" ({span})"
            lines.append(entry)
        counts["education"] = len(education_rows)

    skill_names = [
        row.get("Name", "").strip()
        for row in _parse_csv_rows(csv_texts.get("Skills.csv", ""))
        if row.get("Name", "").strip()
    ]
    if skill_names:
        lines += ["", "Skills: " + ", ".join(skill_names) + "."]
        counts["skills"] = len(skill_names)

    return "\n".join(lines).strip(), counts


def ingest_linkedin_export(csv_texts: dict[str, str]) -> dict[str, Any]:
    """Ingest a parsed LinkedIn data-export (B7).

    Normalizes ``csv_texts`` into the paste-equivalent text and feeds it to
    the SAME :func:`ingest_linkedin` the candidate-paste path uses — no
    second ingest pipeline. Adds ``ingestedCounts`` so the caller can report
    honestly which sections actually contributed (a partial export, e.g. only
    ``Positions.csv``, still ingests — see B7 test 3).
    """
    text, counts = normalize_linkedin_export(csv_texts)
    result = dict(ingest_linkedin(text))
    result["ingestedCounts"] = counts
    if result["status"] == "empty":
        result["error"] = (
            "None of the uploaded file(s) contained usable LinkedIn export "
            "data. Expected one or more of: " + ", ".join(LINKEDIN_EXPORT_FILES) + "."
        )
    return result


def parse_linkedin_export_zip(data: bytes) -> dict[str, str]:
    """Extract ONLY the four known LinkedIn export CSVs out of a zip archive.

    Every other entry — other CSVs, media, LinkedIn's nested export folder —
    is skipped unread. Matches on basename (case-insensitive) so the export's
    usual top-level folder doesn't matter. Raises ``zipfile.BadZipFile`` for a
    payload that isn't actually a zip, OR for a matched entry whose
    decompressed size exceeds ``MAX_LINKEDIN_EXPORT_BYTES`` (a zip-bomb
    guard: DEFLATE lets a compressed payload well under the raw-upload cap
    explode to hundreds of MB on read, so each entry is streamed in bounded
    chunks with a running total rather than read whole — ``info.file_size``
    is attacker-controlled metadata and is never trusted for this decision).
    Either case, the caller (the upload router) turns it into an honest 422.
    Pure in-memory parsing — no filesystem, no network.
    """
    found: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            basename = info.filename.rsplit("/", 1)[-1]
            canonical = _LINKEDIN_EXPORT_BASENAME_MAP.get(basename.lower())
            if canonical is None or canonical in found:
                continue
            chunks: list[bytes] = []
            total_bytes = 0
            with archive.open(info) as member:
                while True:
                    chunk = member.read(_LINKEDIN_EXPORT_READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > MAX_LINKEDIN_EXPORT_BYTES:
                        raise zipfile.BadZipFile(
                            f"{canonical} export entry too large when "
                            "decompressed (exceeds "
                            f"{MAX_LINKEDIN_EXPORT_BYTES // (1024 * 1024)}MB)."
                        )
                    chunks.append(chunk)
            found[canonical] = b"".join(chunks).decode("utf-8", errors="replace")
    return found


# ---------------------------------------------------------------------------
# Orchestration + persistence
# ---------------------------------------------------------------------------


def _stored_github_username(existing: dict[str, dict[str, Any]]) -> Optional[str]:
    row = existing.get("github") or {}
    content = row.get("content")
    if isinstance(content, dict) and content.get("username"):
        return str(content["username"])
    match = re.search(r"github\.com/([^/?#]+)", row.get("url") or "")
    return match.group(1) if match else None


def _stored_linkedin_text(existing: dict[str, dict[str, Any]]) -> Optional[str]:
    row = existing.get("linkedin") or {}
    content = row.get("content")
    if isinstance(content, dict):
        return content.get("summary")
    return None


def refresh_career_data(
    user_id: str,
    *,
    github_username: Optional[str] = None,
    portfolio_url: Optional[str] = None,
    linkedin_summary: Optional[str] = None,
    repo: Optional[CareerProfileRepository] = None,
    github_fetch: Optional[Callable[[str], dict[str, Any]]] = None,
    portfolio_fetch: Optional[Callable[[str], str]] = None,
) -> dict[str, dict[str, Any]]:
    """Ingest all three sources and persist the results.

    A ``None`` input means "reuse the previously stored value for this source"
    so a bare refresh re-syncs what the user already configured; an explicit
    empty string clears the source. Every source is persisted with its real
    status/error — nothing is fabricated.
    """
    repo = repo or CareerProfileRepository()
    existing = {row["source"]: row for row in repo.list_by_user(user_id)}

    gh_user = (
        github_username
        if github_username is not None
        else _stored_github_username(existing)
    )
    pf_url = (
        portfolio_url
        if portfolio_url is not None
        else (existing.get("portfolio") or {}).get("url")
    )
    li_text = (
        linkedin_summary
        if linkedin_summary is not None
        else _stored_linkedin_text(existing)
    )

    results: dict[str, dict[str, Any]] = {}
    for result in (
        ingest_github(gh_user, fetch=github_fetch),
        ingest_portfolio(pf_url, fetch=portfolio_fetch),
        ingest_linkedin(li_text),
    ):
        saved = repo.upsert(
            user_id,
            result["source"],
            status=result["status"],
            url=result["url"],
            content=result["content"],
            summary=result["summary"],
            error=result["error"],
        )
        results[result["source"]] = {**result, "syncedAt": saved.get("syncedAt")}
    return results


def build_career_corpus(
    user_id: str, repo: Optional[CareerProfileRepository] = None
) -> str:
    """Flattened, ok-only career evidence in a stable source order.

    Returns ``""`` when the user has ingested nothing — keeping the tailoring
    and cover-letter guards behaving exactly as before for users who have not
    configured career data.
    """
    repo = repo or CareerProfileRepository()
    by_source = {row["source"]: row for row in repo.list_by_user(user_id)}
    parts: list[str] = []
    for source in CAREER_SOURCES:
        row = by_source.get(source)
        if row and row.get("status") == "ok" and row.get("summary"):
            parts.append(str(row["summary"]))
    return "\n\n".join(parts)
