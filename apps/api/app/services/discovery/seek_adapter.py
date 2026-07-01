"""Seek.com.au source adapter (P2-S02).

Parses Seek's search-results markup, keyed on the ``data-automation`` hooks the
site emits (``normalJob`` / ``jobTitle`` / ``jobCompany`` / ``jobLocation`` /
``jobShortDescription``). The canonical ``sourceUrl`` is rebuilt from the job id
so re-discovering the same posting yields a stable, dedupe-friendly URL.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

from app.services.discovery.base_adapter import BaseAdapter, JobRaw

_JOB_ID_RE = re.compile(r"/job/(\d+)")


class SeekAdapter(BaseAdapter):
    """Adapter for https://www.seek.com.au job search."""

    source = "seek"
    base_url = "https://www.seek.com.au"

    def _build_search_url(self, query: str, location: str) -> str:
        query_slug = quote(query.strip().replace(" ", "-"))
        location_slug = quote(location.strip().replace(" ", "-"))
        return f"{self.base_url}/{query_slug}-jobs/in-{location_slug}"

    def parse(self, html: str) -> list[JobRaw]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[JobRaw] = []
        for card in soup.select('article[data-automation="normalJob"]'):
            title_el = card.select_one('[data-automation="jobTitle"]')
            company_el = card.select_one('[data-automation="jobCompany"]')
            location_el = card.select_one('[data-automation="jobLocation"]')
            desc_el = card.select_one('[data-automation="jobShortDescription"]')

            title = self._clean(title_el.get_text() if title_el else "")
            source_url = self._canonical_url(title_el)
            if not title or not source_url:
                # Skip malformed cards rather than persist junk.
                continue

            location = self._clean(location_el.get_text() if location_el else "")
            description = self._clean(desc_el.get_text() if desc_el else "")
            time_el = card.select_one("time[datetime]")
            posted_at = self._attr_str(time_el.get("datetime")) if time_el else None

            jobs.append(
                JobRaw(
                    title=title,
                    company=self._clean(company_el.get_text() if company_el else ""),
                    location=location,
                    remote=self._is_remote(location, description),
                    description=description,
                    requirements=[],
                    source=self.source,
                    sourceUrl=source_url,
                    postedAt=posted_at,
                )
            )
        return jobs

    def _canonical_url(self, title_el) -> Optional[str]:
        """Build ``https://www.seek.com.au/job/<id>`` from the title link."""
        if not title_el:
            return None
        href = self._attr_str(title_el.get("href")) or ""
        match = _JOB_ID_RE.search(href)
        if not match:
            return None
        return f"{self.base_url}/job/{match.group(1)}"
