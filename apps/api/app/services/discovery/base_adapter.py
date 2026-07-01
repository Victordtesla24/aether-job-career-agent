"""Base class + shared types for job-board source adapters (P2-S02).

An adapter turns a job-board search-results page into a list of :class:`JobRaw`
dicts. The base class owns the fetch/parse split so concrete adapters only
implement (a) how to build the search URL and (b) how to parse the HTML.

Fixture replay
--------------
Passing ``fixture=<raw HTML>`` makes the adapter parse that markup instead of
performing live HTTP. Tests use recorded/representative fixtures (live capture
is blocked from CI — see ``tests/fixtures/http/*/search.html``) so parsing runs
through the exact same code path as production.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, TypedDict

import httpx

# A browser-like UA reduces trivial bot rejection on the live sites. Adapters
# still degrade gracefully (empty list) when a site blocks or changes markup.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "en-AU,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class JobRaw(TypedDict):
    """A normalized job posting emitted by an adapter (pre-persistence)."""

    title: str
    company: str
    location: str
    remote: bool
    description: str
    requirements: list[str]
    source: str
    sourceUrl: str
    postedAt: Optional[str]


class BaseAdapter(ABC):
    """Abstract job-board adapter.

    Subclasses set ``source``/``base_url`` and implement ``_build_search_url``
    and ``parse``. ``fetch`` orchestrates fetch-then-parse.
    """

    #: Canonical source key persisted on ``Job.source`` (e.g. ``"seek"``).
    source: str = ""
    #: Origin used to absolutize relative links.
    base_url: str = ""

    def __init__(self, fixture: Optional[str] = None, *, timeout: float = 15.0) -> None:
        self._fixture = fixture
        self._timeout = timeout

    def fetch(self, query: str, location: str) -> list[JobRaw]:
        """Return parsed jobs for ``query``/``location``."""
        html = self._get_html(query, location)
        return self.parse(html)

    def _get_html(self, query: str, location: str) -> str:
        """Return fixture HTML in test mode, else fetch the live search page."""
        if self._fixture is not None:
            return self._fixture
        url = self._build_search_url(query, location)
        resp = httpx.get(
            url,
            headers=_DEFAULT_HEADERS,
            timeout=self._timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text

    @abstractmethod
    def _build_search_url(self, query: str, location: str) -> str:
        """Build the live search-results URL for the given query/location."""

    @abstractmethod
    def parse(self, html: str) -> list[JobRaw]:
        """Parse a search-results page into :class:`JobRaw` items."""

    # -- shared parsing helpers ------------------------------------------------

    @staticmethod
    def _clean(text: Optional[str]) -> str:
        """Collapse whitespace and trim; ``None`` becomes empty string."""
        if not text:
            return ""
        return " ".join(text.split()).strip()

    @staticmethod
    def _attr_str(value: object) -> Optional[str]:
        """Normalize a BeautifulSoup attribute value to ``str | None``.

        Multi-valued attributes come back as a list; single-valued ones as a
        string. This collapses both to a single string (or ``None``).
        """
        if value is None:
            return None
        if isinstance(value, list):
            return str(value[0]) if value else None
        return str(value)

    @staticmethod
    def _is_remote(*parts: str) -> bool:
        """Heuristic: any field mentioning 'remote' flags a remote role."""
        blob = " ".join(parts).lower()
        return "remote" in blob or "work from home" in blob
