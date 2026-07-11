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

from app.services.discovery.base_adapter import BaseAdapter, JobRaw

logger = logging.getLogger(__name__)

_REMOTE_MARKERS = ("remote", "work from home", "wfh", "hybrid")

# Target roles for Vikram Sarkar's job search
_TARGET_ROLES = [
    "business analyst",
    "senior business analyst",
    "principal business analyst",
    "product owner",
    "senior product owner",
    "technical delivery manager",
    "delivery manager",
    "technical lead",
    "program manager",
]


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
    """Use Firecrawl to scrape a Seek search results page."""
    import httpx

    response = httpx.post(
        f"{firecrawl_url}/v1/scrape",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"url": search_url, "formats": ["markdown", "links"]},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _scrape_job_detail(api_key: str, firecrawl_url: str, job_url: str) -> dict:
    """Use Firecrawl to scrape a single job detail page."""
    import httpx

    response = httpx.post(
        f"{firecrawl_url}/v1/scrape",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"url": job_url, "formats": ["markdown", "rawHtml"]},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


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
        """Fetch real jobs from Seek using Firecrawl."""
        api_key, firecrawl_url = _get_abacus_credentials()

        if not api_key or not firecrawl_url:
            raise NotImplementedError(
                "Seek live mode requires ABACUS_API_KEY and FIRECRAWL_API_URL "
                "(or running on Abacus SuperComputer with VM metadata access)"
            )

        # Build search URL - Seek uses slug format
        query_slug = query.lower().replace(" ", "-")
        location_slug = location.replace(", ", "-").replace(" ", "-")
        search_url = f"https://www.seek.com.au/{query_slug}-jobs/in-{location_slug}"

        logger.info("seek: fetching %s", search_url)

        try:
            result = _scrape_seek_page(api_key, firecrawl_url, search_url)
        except Exception as exc:
            logger.warning("seek: scrape failed: %s", exc)
            raise NotImplementedError(f"Seek scrape failed: {exc}") from exc

        if not result.get("success"):
            raise NotImplementedError(f"Seek scrape returned failure: {result}")

        data = result.get("data", {})
        links = data.get("links", [])

        # Extract unique job URLs
        job_urls = set()
        for link in links:
            if "/job/" in link:
                # Clean up URL - remove tracking params
                clean_url = re.sub(r"[?#].*", "", link)
                # Normalize to seek.com.au
                clean_url = clean_url.replace("au.seek.com", "www.seek.com.au")
                if clean_url not in job_urls:
                    job_urls.add(clean_url)

        logger.info("seek: found %d unique job URLs", len(job_urls))

        # Scrape first N job details (limit to avoid rate limits)
        jobs_data = []
        max_jobs = int(os.environ.get("AETHER_SEEK_MAX_JOBS", "20"))

        for job_url in list(job_urls)[:max_jobs]:
            try:
                detail_result = _scrape_job_detail(api_key, firecrawl_url, job_url)
                if detail_result.get("success"):
                    data = detail_result.get("data", {})
                    job_info = _parse_job_from_html(data.get("rawHtml", ""), job_url)
                    if not job_info:
                        job_info = _parse_job_from_markdown(data.get("markdown", ""), job_url)
                    if job_info:
                        jobs_data.append(job_info)
                        logger.info("seek: scraped job: %s", job_info.get("title", "")[:50])
            except Exception as exc:
                logger.warning("seek: failed to scrape %s: %s", job_url, exc)
                continue

        return {"data": jobs_data}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        """Parse job data into JobRaw records.

        Accepts both the live-scrape shape (``company``/``description``/
        ``sourceUrl``) and the Seek API fixture shape (``advertiser``/
        ``teaser``/``shareLink``).
        """
        jobs: list[JobRaw] = []
        for item in payload.get("data", []):
            location_str = str(item.get("location") or "")
            arrangement = str((item.get("workArrangements") or {}).get("displayText", ""))
            remote = any(
                m in f"{location_str} {arrangement}".lower() for m in _REMOTE_MARKERS
            )

            # Live scrapes carry numeric bands from ``_parse_job_from_html``;
            # fixtures expose a raw ``salary`` label to parse as a fallback.
            salary_min = item.get("salaryMin")
            salary_max = item.get("salaryMax")
            if salary_min is None and salary_max is None:
                salary_min, salary_max = _parse_salary_label(str(item.get("salary") or ""))
            currency = item.get("currency") or ("AUD" if salary_min is not None else None)

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
                    salaryMin=salary_min,
                    salaryMax=salary_max,
                    currency=currency,
                )
            )
        return jobs
