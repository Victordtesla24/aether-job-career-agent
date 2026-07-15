"""Seek.com.au discovery adapter (P2-S02) — LIVE via Firecrawl API.

Scrapes real job listings from seek.com.au using the Abacus.AI Firecrawl
service. Requires ABACUS_API_KEY and FIRECRAWL_API_URL environment variables
(auto-discovered from VM metadata if running on Abacus SuperComputer).
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from html import unescape
from typing import Any
from urllib.parse import quote

from app.services.discovery import relevance
from app.services.discovery.base_adapter import AdapterFetchError, BaseAdapter, JobRaw

logger = logging.getLogger(__name__)

_REMOTE_MARKERS = ("remote", "work from home", "wfh", "hybrid")


def _get_abacus_credentials() -> tuple[str | None, str | None]:
    """Get Firecrawl credentials from env or VM metadata."""
    api_key = os.environ.get("ABACUS_API_KEY")
    firecrawl_url = os.environ.get("FIRECRAWL_API_URL")

    if api_key and firecrawl_url:
        return api_key, firecrawl_url

    # Try VM metadata (Abacus SuperComputer)
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-abacus-vm-metadata-token-ttl-seconds": "300"},
        )
        with urllib.request.urlopen(token_req, timeout=2) as resp:
            token = resp.read().decode()

        data_req = urllib.request.Request(
            "http://169.254.169.254/latest/user-data",
            headers={"X-abacus-vm-metadata-token": token},
        )
        with urllib.request.urlopen(data_req, timeout=5) as resp:
            user_data = json.loads(resp.read().decode())
            return user_data.get("abacus_api_key"), user_data.get("firecrawl_api_url")
    except Exception:
        return None, None


def _scrape_seek_page(api_key: str, firecrawl_url: str, search_url: str) -> dict:
    """Use Firecrawl to scrape a Seek search results page (raw HTML).

    The rendered search page embeds every result in a ``window.SEEK_REDUX_DATA``
    island, so a single search-page scrape yields the full job list — far more
    reliable than scraping each job detail page (Seek blocks direct
    ``/job/<id>`` fetches with an interstitial error page).
    """
    import httpx

    response = httpx.post(
        f"{firecrawl_url}/v1/scrape",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"url": search_url, "formats": ["rawHtml"]},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _extract_search_results(html: str) -> list[dict[str, Any]]:
    """Extract job records from a Seek search page's ``SEEK_REDUX_DATA`` island.

    Returns the de-duplicated (by job id) list of result records — each a dict
    with ``id``/``title``/``advertiser``/``locations``/``teaser``/
    ``bulletPoints``/``listingDate``/``workArrangements``. Returns ``[]`` when
    the data island is absent (e.g. Seek served an interstitial/error page) so
    the caller can distinguish "blocked" from "genuinely zero results".
    """
    marker = html.find("window.SEEK_REDUX_DATA")
    if marker == -1:
        return []
    try:
        start = html.index("{", marker)
        blob, _ = json.JSONDecoder().raw_decode(html[start:])
    except (ValueError, json.JSONDecodeError):
        return []

    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if (
                node.get("id")
                and node.get("title")
                and isinstance(node.get("advertiser"), dict)
                and "locations" in node
            ):
                job_id = str(node["id"])
                if job_id not in seen:
                    seen.add(job_id)
                    records.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(blob.get("results", blob))
    return records


def _search_record_to_item(record: dict[str, Any]) -> dict[str, Any]:
    """Map a SEEK search Redux record into the shape ``_parse`` consumes."""
    locations = record.get("locations") or []
    location = ", ".join(
        str((loc or {}).get("label", "")) for loc in locations if (loc or {}).get("label")
    )
    advertiser = record.get("advertiser") or {}
    company = str(advertiser.get("description") or record.get("companyName") or "")
    return {
        "title": str(record.get("title") or ""),
        "company": company,
        "location": location,
        "description": str(record.get("teaser") or ""),
        "requirements": [b for b in (record.get("bulletPoints") or []) if b],
        "sourceUrl": f"https://www.seek.com.au/job/{record.get('id')}",
        "postedAt": record.get("listingDate"),
        "workArrangements": record.get("workArrangements"),
    }


def _apollo_field(record: dict[str, Any], name: str) -> Any:
    """Read a field from a SEEK Apollo cache record.

    Apollo persists parameterized fields under keys like
    ``name({"locale":"en-AU"})`` — match on the bare name or that prefix.
    """
    for key, value in record.items():
        if key == name or key.startswith(name + "("):
            return value
    return None


def _parse_job_from_html(raw_html: str, job_url: str) -> dict[str, Any] | None:
    """Extract structured job data from SEEK's embedded Apollo GraphQL state.

    Job detail pages ship ``window.SEEK_APOLLO_DATA`` with the canonical
    advertiser name, location label, posting timestamp, and ad HTML — far more
    reliable than heuristics over the rendered markdown.
    """
    marker = raw_html.find("window.SEEK_APOLLO_DATA")
    if marker == -1:
        return None
    try:
        start = raw_html.index("{", marker)
        blob, _ = json.JSONDecoder().raw_decode(raw_html[start:])
    except (ValueError, json.JSONDecodeError):
        return None

    root = blob.get("ROOT_QUERY", {})
    details = next(
        (v for k, v in root.items() if k.startswith("jobDetails") and isinstance(v, dict)),
        None,
    )
    job = (details or {}).get("job")
    if not isinstance(job, dict):
        return None

    title = job.get("title") or ""
    if not title:
        return None

    company = _apollo_field(job.get("advertiser") or {}, "name") or ""
    location = _apollo_field(job.get("location") or {}, "label") or ""
    posted_at = (job.get("listedAt") or {}).get("dateTimeUtc")
    salary_min, salary_max = _parse_salary_label((job.get("salary") or {}).get("label") or "")

    content = _apollo_field(job, "content2") or ""
    requirements = [
        req
        for req in (
            re.sub(r"<[^>]+>", " ", li).strip()
            for li in re.findall(r"<li[^>]*>(.*?)</li>", content, re.S)
        )
        if len(req) > 10
    ][:10]
    description = unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content))).strip()
    if not description:
        description = job.get("abstract") or ""

    return {
        "title": unescape(title).strip(),
        "company": unescape(company).strip() or "Unknown",
        "location": unescape(location).strip() or "Melbourne, VIC",
        "description": description[:2000],
        "requirements": requirements,
        "sourceUrl": job_url,
        "postedAt": posted_at,
        "salaryMin": salary_min,
        "salaryMax": salary_max,
        "currency": "AUD" if salary_min is not None else None,
    }


def _parse_salary_label(label: str) -> tuple[int | None, int | None]:
    """Yearly salary band from a SEEK salary label, e.g.
    ``"$140,000 – $150,000 per year plus super"`` → ``(140000, 150000)``.

    Daily/hourly rates are not annualized — only per-year figures persist.
    """
    if not label or not re.search(r"year|annum|p\.?a\b", label, re.I):
        return None, None
    matches = re.findall(r"\$?\s*([\d]{2,3}(?:,\d{3})+|\d{5,7})", label)
    numbers = [int(n.replace(",", "")) for n in matches]
    numbers = [n for n in numbers if 30_000 <= n <= 1_000_000]
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def _strip_markdown_links(line: str) -> str:
    """Replace markdown links/images with their label text."""
    return re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line).strip()


def _parse_job_from_markdown(markdown: str, job_url: str) -> dict[str, Any] | None:
    """Extract structured job data from markdown content."""
    lines = markdown.split("\n")
    title = ""
    company = ""
    location = ""
    description_parts: list[str] = []
    requirements: list[str] = []

    for i, line in enumerate(lines):
        line = _strip_markdown_links(line.strip())
        if not line:
            continue

        # Title is usually in h1 or first prominent heading
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif "at " in line.lower() and not company:
            # Pattern: "Title at Company" or "Company"
            parts = line.split(" at ", 1)
            if len(parts) == 2 and len(parts[1].strip()) <= 60:
                company = parts[1].strip()
        elif any(loc in line.lower() for loc in (
            "melbourne", "victoria", "vic", "sydney", "brisbane"
        )):
            if not location and len(line) <= 60:
                location = line

        # Collect description lines
        if len(description_parts) < 10 and len(line) > 30:
            description_parts.append(line)

        # Requirements often in bullet points
        if line.startswith("- ") or line.startswith("* "):
            req = line[2:].strip()
            if len(req) > 10 and len(requirements) < 10:
                requirements.append(req)

    if not title:
        return None

    return {
        "title": title,
        "company": company or "Unknown",
        "location": location or "Melbourne, VIC",
        "description": " ".join(description_parts[:5]),
        "requirements": requirements,
        "sourceUrl": job_url,
    }


class SeekAdapter(BaseAdapter):
    """Live Seek.com.au adapter using Firecrawl for scraping."""

    source = "seek"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        """Fetch real jobs from Seek using Firecrawl, paginating result pages.

        Walks Seek's paginated search (``?page=N``) accumulating unique job
        URLs until a page yields no new jobs, a sane page/job cap is hit
        (``AETHER_SEEK_MAX_PAGES`` / ``AETHER_SEEK_MAX_JOBS``, default 10 / 100),
        or the search is exhausted — replacing the old hard 20-job cap.

        A first-page scrape failure (e.g. a Firecrawl 408/500) raises
        :class:`AdapterFetchError` so the scout surfaces it as a real per-source
        error rather than swallowing it as a benign skip (GAP-SRC-002). Missing
        credentials remain a ``NotImplementedError`` (no live mode available).
        """
        api_key, firecrawl_url = _get_abacus_credentials()

        if not api_key or not firecrawl_url:
            raise NotImplementedError(
                "Seek live mode requires ABACUS_API_KEY and FIRECRAWL_API_URL "
                "(or running on Abacus SuperComputer with VM metadata access)"
            )

        # Build the search URL. The keyword/where query form is used rather
        # than the ``/<slug>-jobs/in-<slug>`` path form: the latter redirects to
        # au.seek.com and scrapes an error page (a root cause of discovery being
        # stuck at persisted=0). Pagination is ``&page=N`` on this query URL.
        base_url = (
            f"https://www.seek.com.au/jobs?keywords={quote(query)}&where={quote(location)}"
        )

        max_pages = int(os.environ.get("AETHER_SEEK_MAX_PAGES", "10"))
        max_jobs = int(os.environ.get("AETHER_SEEK_MAX_JOBS", "100"))

        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for page in range(1, max_pages + 1):
            page_url = base_url if page == 1 else f"{base_url}&page={page}"
            logger.info("seek: fetching %s", page_url)
            try:
                result = _scrape_seek_page(api_key, firecrawl_url, page_url)
            except Exception as exc:
                if page == 1:
                    logger.warning("seek: search scrape failed: %s", exc)
                    raise AdapterFetchError(f"Seek search scrape failed: {exc}") from exc
                logger.warning("seek: page %d scrape failed: %s", page, exc)
                break
            if not result.get("success"):
                if page == 1:
                    raise AdapterFetchError(f"Seek search returned failure: {result}")
                break

            html = result.get("data", {}).get("rawHtml", "") or ""
            if "SEEK_REDUX_DATA" not in html and "SEEK_APOLLO_DATA" not in html:
                # No data island → Seek served an interstitial/error page.
                # Surface it honestly on the first page rather than persisting
                # the error-page text as a bogus job (GAP-SRC-002).
                if page == 1:
                    raise AdapterFetchError(
                        "Seek search page not reachable (no data island; likely blocked)"
                    )
                break

            page_records = _extract_search_results(html)
            new_on_page = 0
            for record in page_records:
                job_id = str(record.get("id") or "")
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                records.append(record)
                new_on_page += 1
            # A page with a data island but no new jobs means results are
            # exhausted (page 1 with zero results is an honest empty run).
            if new_on_page == 0 or len(records) >= max_jobs:
                break

        records = records[:max_jobs]
        logger.info("seek: parsed %d jobs across search pages", len(records))
        return {"data": [_search_record_to_item(record) for record in records]}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        """Parse job data into JobRaw records, then apply the shared relevance
        filter (GAP-SRC-001).

        Accepts both the live-scrape shape (``company``/``description``/
        ``sourceUrl``) and the Seek API fixture shape (``advertiser``/
        ``teaser``/``shareLink``).

        Seek's own ``keywords=`` search is fuzzy relevance-ranked, not an
        exact filter — broadening the query to the full target-role family
        (GAP-SRC-001) means Seek can surface loosely-matching noise. Every
        other live adapter already runs its parsed jobs through
        ``relevance.filter_relevant`` before returning; Seek was the one
        outlier relying solely on the upstream search to be on-target. This
        brings it in line so only on-target, AU-applicable roles reach the UI
        regardless of how broad the query is.
        """
        jobs: list[JobRaw] = []
        for item in payload.get("data", []):
            location_str = str(item.get("location") or "")
            arrangement = str((item.get("workArrangements") or {}).get("displayText", ""))
            remote = any(
                m in f"{location_str} {arrangement}".lower() for m in _REMOTE_MARKERS
            )

            jobs.append(
                JobRaw(
                    title=item.get("title", ""),
                    company=item.get("company")
                    or (item.get("advertiser") or {}).get("description", ""),
                    location=location_str or None,
                    remote=remote,
                    description=item.get("description") or item.get("teaser", ""),
                    requirements=item.get("requirements")
                    or [b for b in item.get("bulletPoints", []) if b],
                    source=self.source,
                    sourceUrl=item.get("sourceUrl") or item.get("shareLink", ""),
                    postedAt=item.get("postedAt") or item.get("listingDate"),
                )
            )
        return relevance.filter_relevant(jobs)
