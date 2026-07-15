"""Adapter contract for job-board discovery sources (P2-S02).

Adapters normalize wildly different source payloads into the ``JobRaw``
shape. Two modes:

- **fixture mode** (``fixture=`` dict passed in, or loaded from
  ``AETHER_DISCOVERY_FIXTURE_DIR``): parse a recorded payload — used in tests
  and offline development. No network I/O.
- **live mode**: fetch from the real source over httpx. Deliberately not
  implemented yet (job boards need per-source scraping/API agreements); live
  calls raise so we never silently ship fake data as real.
"""
from __future__ import annotations

import abc
import json
import os
from pathlib import Path
from typing import Any, NotRequired, TypedDict


class AdapterFetchError(RuntimeError):
    """A live adapter fetch failed (network/HTTP/parse error).

    Distinct from :class:`NotImplementedError`, which means the source has *no
    live mode at all* (a legacy fixture-only source). The scout treats the two
    differently: a ``NotImplementedError`` is a benign skip, while an
    ``AdapterFetchError`` (or any other exception) is a REAL failure that must
    be surfaced per-source rather than swallowed (GAP-SRC-002).
    """


class JobRaw(TypedDict):
    """Normalized job posting as produced by every adapter."""

    title: str
    company: str
    location: str | None
    remote: bool
    description: str
    requirements: list[str]
    source: str
    sourceUrl: str
    postedAt: str | None
    salaryMin: NotRequired[int | None]
    salaryMax: NotRequired[int | None]
    currency: NotRequired[str | None]


class BaseAdapter(abc.ABC):
    """Abstract job-board adapter."""

    #: Source key, e.g. ``"seek"``. Set by subclasses.
    source: str = ""

    def __init__(self, fixture: dict[str, Any] | None = None) -> None:
        self._fixture = fixture

    # -- public API ---------------------------------------------------------

    def fetch(self, query: str, location: str) -> list[JobRaw]:
        """Return normalized jobs for a query/location pair."""
        payload = self._resolve_payload(query, location)
        jobs = self._parse(payload)
        return [job for job in jobs if job["title"].strip() and job["company"].strip()]

    # -- hooks for subclasses ------------------------------------------------

    @abc.abstractmethod
    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        """Translate a raw source payload into ``JobRaw`` records."""

    # -- internals -----------------------------------------------------------

    def _resolve_payload(self, query: str, location: str) -> dict[str, Any]:
        if self._fixture is not None:
            return self._fixture
        fixture_dir = os.environ.get("AETHER_DISCOVERY_FIXTURE_DIR")
        if fixture_dir:
            path = Path(fixture_dir) / self.source / "jobs.json"
            if path.exists():
                return json.loads(path.read_text())
        return self._fetch_live(query, location)

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        raise NotImplementedError(
            f"Live HTTP discovery for '{self.source}' is not implemented yet; "
            "run in fixture mode (pass fixture= or set AETHER_DISCOVERY_FIXTURE_DIR)."
        )
