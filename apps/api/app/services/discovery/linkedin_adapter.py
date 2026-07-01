"""LinkedIn Jobs source adapter (P2-S02).

Parses LinkedIn's unauthenticated guest jobs-search markup (the
``/jobs-guest/jobs/api/seeMoreJobPostings/search`` card list). No API key is
required. The canonical ``sourceUrl`` strips tracking query params so the same
posting dedupes across runs.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote_plus, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.services.discovery.base_adapter import BaseAdapter, JobRaw


class LinkedInAdapter(BaseAdapter):
    """Adapter for LinkedIn's guest jobs search."""

    source = "linkedin"
    base_url = "https://www.linkedin.com"
    search_endpoint = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    )

    def _build_search_url(self, query: str, location: str) -> str:
        return (
            f"{self.search_endpoint}"
            f"?keywords={quote_plus(query.strip())}"
            f"&location={quote_plus(location.strip())}"
        )

    def parse(self, html: str) -> list[JobRaw]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[JobRaw] = []
        for card in soup.select("div.base-card"):
            title_el = card.select_one(".base-search-card__title")
            company_el = card.select_one(".base-search-card__subtitle")
            location_el = card.select_one(".job-search-card__location")
            link_el = card.select_one("a.base-card__full-link")

            title = self._clean(title_el.get_text() if title_el else "")
            source_url = self._canonical_url(link_el)
            if not title or not source_url:
                continue

            location = self._clean(location_el.get_text() if location_el else "")
            time_el = card.select_one("time[datetime]")
            posted_at = self._attr_str(time_el.get("datetime")) if time_el else None

            jobs.append(
                JobRaw(
                    title=title,
                    company=self._clean(company_el.get_text() if company_el else ""),
                    location=location,
                    remote=self._is_remote(location, title),
                    description="",
                    requirements=[],
                    source=self.source,
                    sourceUrl=source_url,
                    postedAt=posted_at,
                )
            )
        return jobs

    def _canonical_url(self, link_el) -> Optional[str]:
        """Return the job link with tracking query/fragment stripped."""
        if not link_el:
            return None
        href = self._attr_str(link_el.get("href")) or ""
        if not href.startswith("http"):
            return None
        parts = urlsplit(href)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
