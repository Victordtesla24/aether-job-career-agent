"""Indeed.com.au source adapter (P2-S02).

Parses Indeed's search-results cards (``job_seen_beacon``). The canonical
``sourceUrl`` is rebuilt as ``/viewjob?jk=<id>`` from the result's ``jk`` param
so postings dedupe across runs regardless of tracking parameters.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs, quote_plus, urlsplit

from bs4 import BeautifulSoup

from app.services.discovery.base_adapter import BaseAdapter, JobRaw


class IndeedAdapter(BaseAdapter):
    """Adapter for https://au.indeed.com job search."""

    source = "indeed"
    base_url = "https://au.indeed.com"

    def _build_search_url(self, query: str, location: str) -> str:
        return (
            f"{self.base_url}/jobs"
            f"?q={quote_plus(query.strip())}"
            f"&l={quote_plus(location.strip())}"
        )

    def parse(self, html: str) -> list[JobRaw]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[JobRaw] = []
        for card in soup.select("div.job_seen_beacon"):
            link_el = card.select_one("h2.jobTitle a")
            title_span = card.select_one("h2.jobTitle a span[title]")
            company_el = card.select_one('[data-testid="company-name"]')
            location_el = card.select_one('[data-testid="text-location"]')
            snippet_el = card.select_one(".job-snippet")

            title_attr = self._attr_str(title_span.get("title")) if title_span else None
            title = self._clean(
                title_attr or (title_span.get_text() if title_span else "")
            )
            source_url = self._canonical_url(link_el)
            if not title or not source_url:
                continue

            location = self._clean(location_el.get_text() if location_el else "")
            requirements = [
                self._clean(li.get_text())
                for li in (snippet_el.select("li") if snippet_el else [])
                if self._clean(li.get_text())
            ]
            description = self._clean(snippet_el.get_text() if snippet_el else "")

            jobs.append(
                JobRaw(
                    title=title,
                    company=self._clean(company_el.get_text() if company_el else ""),
                    location=location,
                    remote=self._is_remote(location, description),
                    description=description,
                    requirements=requirements,
                    source=self.source,
                    sourceUrl=source_url,
                    postedAt=None,
                )
            )
        return jobs

    def _canonical_url(self, link_el) -> Optional[str]:
        """Build ``https://au.indeed.com/viewjob?jk=<id>`` from the result link."""
        if not link_el:
            return None
        href = self._attr_str(link_el.get("href")) or ""
        query = parse_qs(urlsplit(href).query)
        jk = query.get("jk", [None])[0]
        if not jk:
            return None
        return f"{self.base_url}/viewjob?jk={jk}"
