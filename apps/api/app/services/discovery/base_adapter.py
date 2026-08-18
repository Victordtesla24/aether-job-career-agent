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


class SourceBlockedError(AdapterFetchError):
    """The source PERMANENTLY denies automated access from this server (RT-008).

    A subclass of :class:`AdapterFetchError` (so existing ``except
    AdapterFetchError`` handling still catches it), raised ONLY by an adapter
    that has determined its source structurally blocks this deployment — e.g.
    Wellfound's public listings return HTTP 403 on every request. The scout
    records this as a disclosed ``status="blocked"`` (calm "unavailable" pill),
    NOT a red ``status="error"`` re-alarming on every sync, and it is excluded
    from the run's ``errors`` list. This is deliberately narrow: a plain
    ``AdapterFetchError`` (incl. an ATS provider that 403s across all its
    boards — a genuine, actionable outage) stays an honest ``error``
    (GAP-SRC-002). Blocked-ness is asserted by the ADAPTER, never inferred from
    an error string in the scout.
    """


class SourceQuotaError(SourceBlockedError):
    """The source is TEMPORARILY paused because a shared API quota ran out.

    A subclass of :class:`SourceBlockedError` so every existing handler — the
    scout's ``except SourceBlockedError`` branch, its server-wide block backoff
    (which is exactly the right behaviour here: re-probing an exhausted key
    from every user's run is the same hammering the backoff exists to stop) —
    keeps working unchanged.

    It exists because the two conditions mean OPPOSITE things to the user.
    ``SourceBlockedError`` is structural and permanent ("this board refuses
    this server"), so the UI renders a flat "unavailable (blocked by source)"
    pill and deliberately suppresses the reason: nothing the user does changes
    it. A quota pause is temporary and self-healing — the Adzuna key's daily
    allowance resets at 00:00 UTC — and the honest message says exactly when
    market data resumes, so the Jobs screen renders it as "market data paused
    (API quota)" WITH that message (S-FIX-A/S-2). The frontend keys off the
    class name the scout stringifies onto the source row
    (``f"{type(exc).__name__}: {exc}"``), so the distinction stays a TYPE
    decision made by the adapter, never a string sniff.
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
    #: SUB-009 — set by the scout's ingest loop (never by an adapter) when
    #: ``sourceUrl`` is an Adzuna click-tracking redirector that has been
    #: followed once to its real destination. See
    #: ``app.services.apply_channel_resolver.resolve_ingest_redirect``.
    resolvedApplyUrl: NotRequired[str | None]
    resolvedApplyUrlSource: NotRequired[str | None]


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
            # Fixture mode with NO fixture for this source used to fall through
            # to ``_fetch_live`` — a silent fallback that made the test suite
            # issue real third-party HTTP calls while ``main.py`` was printing
            # "adapters will serve canned HTTP fixtures instead of making live
            # calls" (§REC-05) and this module's own docstring promised "no
            # network I/O". A newly registered adapter therefore joined the
            # suite live and nondeterministic, with nothing to notice it.
            # Fixture mode is now absolute: a missing fixture is a loud,
            # named failure, never a live call.
            raise AdapterFetchError(
                f"fixture mode is active (AETHER_DISCOVERY_FIXTURE_DIR={fixture_dir}) "
                f"but source '{self.source}' has no recorded payload at {path}. "
                "Record one (or pass fixture=) — refusing to make a live HTTP "
                "call while fixture mode is configured."
            )
        return self._fetch_live(query, location)

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        raise NotImplementedError(
            f"Live HTTP discovery for '{self.source}' is not implemented yet; "
            "run in fixture mode (pass fixture= or set AETHER_DISCOVERY_FIXTURE_DIR)."
        )
