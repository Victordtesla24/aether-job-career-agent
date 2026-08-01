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
2. **Liveness (freshness)** — a row the sourcing pipeline has NOT seen at its
   source within the confirmation window (30 days, overridable via
   ``AETHER_JOB_FRESHNESS_DAYS``) is STALE and hidden from the active feed.
   History is retained in the DB and reachable via the ``include_stale``
   escape hatch. An unknown/unparseable date is NOT treated as stale —
   staleness is never fabricated.

   BLOCKER-006 (2026-08-01) corrected what "stale" measures. This predicate
   used to read ``postedAt`` — the date the role was first advertised — as a
   proxy for "this listing is dead". That proxy is invalid for the ATS-native
   boards this product sources from, because those APIs publish ONLY roles
   that are still open:

     * ``api.ashbyhq.com/posting-api/job-board/harvey`` returned 360 open
       postings with ``publishedAt`` reaching back to 2025-09-12;
     * ``api.lever.co/v0/postings/plenti`` returned, on the day of the fix,
       the exact posting whose persisted ``postedAt`` was 36 days old.

   Result in production: all 18 of a paying user's actionable ``ready`` rows
   had ``postedAt`` 36-187 days old and every one had been re-confirmed on its
   board by the sweep less than a minute earlier — and the feed was empty.
   Posting age is now recorded and DISPLAYED (see ``annotate_listing_age``)
   but never suppresses; suppression is driven by the sighting recorded in
   ``Job."lastSeenAt"`` (``JobRepository.create``, the single path every
   adapter result flows through). A listing whose source has stopped
   returning it — the genuine dead-link case this filter was built for — is
   still hidden, now on evidence rather than on a proxy.
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
#: Fields consulted, in priority order, as the LIVENESS signal — "when did we
#: last have evidence this listing was still published at its source".
#:
#: ``postedAt`` is deliberately absent (BLOCKER-006): it is the date the role
#: was first advertised, which says nothing about whether it is still open.
#: See the module docstring for the production evidence.
#:
#: * ``lastSeenAt`` — the real signal, stamped by ``JobRepository.create`` on
#:   every sweep that re-finds the listing.
#: * ``updatedAt`` / ``createdAt`` — honest fallbacks for rows persisted
#:   before ``lastSeenAt`` existed (it is added with no backfill, so those
#:   read NULL). Both are lower bounds on when the system last had contact
#:   with the row, and both are superseded the first time the sweep
#:   re-confirms the listing. ``updatedAt`` is also bumped by user actions,
#:   which is exactly why it is a fallback and not the primary signal.
_LIVENESS_FIELDS = ("lastSeenAt", "updatedAt", "createdAt")


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


def _liveness_date(job: dict[str, Any]) -> datetime | None:
    """When we last had evidence this listing was still published at source."""
    for field in _LIVENESS_FIELDS:
        parsed = _as_naive_utc(job.get(field))
        if parsed is not None:
            return parsed
    return None


def is_stale(
    job: dict[str, Any], *, now: datetime | None = None, max_age_days: int | None = None
) -> bool:
    """True when the listing has not been confirmed at its source recently.

    NOT a function of the posting date: an ATS board only publishes roles that
    are still open, so a role first advertised months ago and returned by that
    board minutes ago is live and applicable (BLOCKER-006). What makes a
    listing unusable is the source no longer carrying it.

    An unknown/unparseable date returns ``False`` — staleness is never
    fabricated from a missing signal.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    window = freshness_days() if max_age_days is None else max_age_days
    effective = _liveness_date(job)
    if effective is None:
        return False
    return effective < now - timedelta(days=window)


def posted_age_days(
    job: dict[str, Any], *, now: datetime | None = None
) -> int | None:
    """Whole days since the role was advertised, or ``None`` when unknown.

    ``None`` is returned rather than a substitute (the discovery date was the
    previous stand-in on the job card, which showed a 187-day-old listing as
    "11 days ago"). An unknown age must read as unknown.
    """
    posted = _as_naive_utc(job.get("postedAt"))
    if posted is None:
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0, (now - posted).days)


def annotate_listing_age(
    job: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Return ``job`` plus the two facts the UI needs to be honest about age.

    * ``postedAgeDays``   -- real age of the advertisement, or ``None``.
    * ``lastConfirmedAt`` -- when the sourcing pipeline last saw this listing
      at its source, or ``None`` when no sighting is on record.

    Showing a months-old listing without its age would trade one dishonesty
    (an empty feed that hides live roles) for another (an old role presented
    as new). Both facts are read off persisted columns — nothing is inferred.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        **job,
        "postedAgeDays": posted_age_days(job, now=now),
        "lastConfirmedAt": _liveness_date(job),
    }


#: Job statuses that are excluded from the active feed — these jobs have been
#: acted on and live in the Application Tracker's applied/archived views instead.
_TERMINAL_JOB_STATUSES = frozenset({"applied", "archived"})


def active_feed(
    jobs: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    max_age_days: int | None = None,
) -> list[dict[str, Any]]:
    """Filter a job list to the live, confirmed, de-duplicated active feed.

    Excludes jobs with terminal statuses (applied, archived) — those live in
    the Application Tracker's separate applied/archived views, not on the
    active pipeline board.

    Every surviving row is annotated with its honest listing age
    (:func:`annotate_listing_age`), so a role that is live but was advertised
    months ago can be shown as what it is rather than hidden or misdated.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    prohibited = prohibited_sources()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for job in jobs:
        if str(job.get("source") or "").lower() in prohibited:
            continue
        if str(job.get("status") or "").lower() in _TERMINAL_JOB_STATUSES:
            continue
        if is_stale(job, now=now, max_age_days=max_age_days):
            continue
        fingerprint = job_fingerprint(
            job.get("company"), job.get("title"), job.get("location")
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append(annotate_listing_age(job, now=now))
    return out
