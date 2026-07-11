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
        json={"url": job_url, "formats": ["markdown"]},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _parse_job_from_markdown(markdown: str, job_url: str) -> dict[str, Any] | None:
    """Extract structured job data from markdown content."""
    lines = markdown.split("\n")
    title = ""
    company = ""
    location = ""
    description_parts: list[str] = []
    requirements: list[str] = []

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        # Title is usually in h1 or first prominent heading
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif "at " in line.lower() and not company:
            # Pattern: "Title at Company" or "Company"
            parts = line.split(" at ", 1)
            if len(parts) == 2:
                company = parts[1].strip()
        elif any(loc in line.lower() for loc in (
            "melbourne", "victoria", "vic", "sydney", "brisbane"
        )):
            if not location:
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
                    md = detail_result.get("data", {}).get("markdown", "")
                    job_info = _parse_job_from_markdown(md, job_url)
                    if job_info:
                        jobs_data.append(job_info)
                        logger.info("seek: scraped job: %s", job_info.get("title", "")[:50])
            except Exception as exc:
                logger.warning("seek: failed to scrape %s: %s", job_url, exc)
                continue

        return {"data": jobs_data}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        """Parse scraped job data into JobRaw records."""
        jobs: list[JobRaw] = []
        for item in payload.get("data", []):
            location_str = str(item.get("location") or "")
            remote = any(m in location_str.lower() for m in _REMOTE_MARKERS)

            jobs.append(
                JobRaw(
                    title=item.get("title", ""),
                    company=item.get("company", ""),
                    location=location_str or None,
                    remote=remote,
                    description=item.get("description", ""),
                    requirements=item.get("requirements", []),
                    source=self.source,
                    sourceUrl=item.get("sourceUrl", ""),
                    postedAt=item.get("postedAt"),
                )
            )
        return jobs
