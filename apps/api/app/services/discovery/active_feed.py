"""Active-feed liveness + freshness + fingerprint dedupe (GAP-P6-DATA-001).

The Job Discovery screen must only surface jobs a paying user can actually act
on. probe-13 found 10/10 sampled dashboard cards were Seek URLs returning HTTP
403 (dead + ToS-prohibited). This module filters the persisted rows at display
time WITHOUT deleting history:

1. **Dead/prohibited source** — rows from a compliance-gated / known-dead source
   (Seek by default, overridable via ``AETHER_PROHIBITED_JOB_SOURCES``) are
   excluded from the active feed. Combined with SeekAdapter being out of the
   live registry (ADR-P6-SEEK), no new Seek rows arrive and historical ones
   stop being presented as live.
2. **Freshness** — a row whose posting date is older than the freshness window
   (30 days, overridable via ``AETHER_JOB_FRESHNESS_DAYS``) is STALE and hidden
   from the active feed. History is retained in the DB and reachable via the
   ``include_stale`` escape hatch. An unknown/unparseable date is NOT treated as
   stale — staleness is never fabricated.
3. **Fingerprint dedupe** — the same role cross-posted to two boards
   (``hash(normalise(company) + normalise(title) + normalise(location))``) is
   shown once. Rows are assumed newest-first, so the freshest survives. Because
   dedupe only ever removes rows (each already has a unique externalUrl per the
   ``(userId, sourceUrl)`` upsert), the feed always has 0 duplicate externalUrl.

Pure functions, no I/O — unit-testable without a DB.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

_DEFAULT_FRESHNESS_DAYS = 30
_DEFAULT_PROHIBITED_SOURCES = frozenset({"seek"})
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
#: Date fields consulted, in priority order, as the freshness signal.
_DATE_FIELDS = ("postedAt", "updatedAt", "createdAt")


def prohibited_sources() -> set[str]:
    """Sources excluded from the active feed (dead / ToS-non-compliant)."""
    raw = os.environ.get("AETHER_PROHIBITED_JOB_SOURCES")
    if raw is None:
        return set(_DEFAULT_PROHIBITED_SOURCES)
    return {token.strip().lower() for token in raw.split(",") if token.strip()}


def freshness_days() -> int:
    try:
        return int(os.environ.get("AETHER_JOB_FRESHNESS_DAYS", _DEFAULT_FRESHNESS_DAYS))
    except (TypeError, ValueError):
        return _DEFAULT_FRESHNESS_DAYS


def _normalise(value: Any) -> str:
    return _NON_ALNUM_RE.sub(" ", str(value or "").lower()).strip()


def job_fingerprint(company: Any, title: Any, location: Any) -> str:
    """Stable fingerprint of ``normalise(company)+normalise(title)+normalise(location)``."""
    key = "|".join(_normalise(part) for part in (company, title, location))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _as_naive_utc(value: Any) -> datetime | None:
    """Coerce a stored date (naive/aware datetime or ISO string) to naive-UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _effective_date(job: dict[str, Any]) -> datetime | None:
    for field in _DATE_FIELDS:
        parsed = _as_naive_utc(job.get(field))
        if parsed is not None:
            return parsed
    return None


def is_stale(
    job: dict[str, Any], *, now: datetime | None = None, max_age_days: int | None = None
) -> bool:
    """True when the job's freshness date is older than the window.

    An unknown/unparseable date returns ``False`` — staleness is never
    fabricated from a missing signal.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    window = freshness_days() if max_age_days is None else max_age_days
    effective = _effective_date(job)
    if effective is None:
        return False
    return effective < now - timedelta(days=window)


def active_feed(
    jobs: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    max_age_days: int | None = None,
) -> list[dict[str, Any]]:
    """Filter a job list to the live, fresh, de-duplicated active feed."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    prohibited = prohibited_sources()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for job in jobs:
        if str(job.get("source") or "").lower() in prohibited:
            continue
        if is_stale(job, now=now, max_age_days=max_age_days):
            continue
        fingerprint = job_fingerprint(
            job.get("company"), job.get("title"), job.get("location")
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append(job)
    return out
