"""Adzuna AU licensed-aggregator adapter — REAL job discovery (GAP-P6-SRC-001).

Adzuna is a licensed job aggregator with explicit Australia support
(seek-tos-check.md Part 4, VERIFIED-WITH-SOURCE) — the ToS-compliant way to
reach AU listings that Seek scraping is prohibited from providing (ADR-P6-SEEK).

Auth is a free-tier ``app_id`` + ``app_key`` read from the environment
(``ADZUNA_APP_ID`` / ``ADZUNA_APP_KEY``) — never hardcoded. When the credentials
are ABSENT the adapter honestly degrades: ``_fetch_live`` raises
``NotImplementedError`` so the scout records the source as a benign ``skipped``
(surfaced in per-source status), and volume falls back to the keyless ATS +
public-API sources. It NEVER fabricates jobs to cover a missing key.

When the credentials ARE present the adapter paginates
``/v1/api/jobs/au/search/<page>`` to exhaustion (or a sane page cap), applies
the shared relevance filter, and keeps each posting's real ``redirect_url`` as
the apply URL — zero fabrication. A first-page fetch failure raises
``AdapterFetchError`` so a real outage is surfaced per-source rather than
swallowed as an empty-but-ok result (GAP-P6-SRC-002); a genuine empty result
stays a legitimate ``status=ok`` zero.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from app.services.discovery import relevance
from app.services.discovery.base_adapter import (
    AdapterFetchError,
    BaseAdapter,
    JobRaw,
    SourceQuotaError,
)
from app.services.discovery.live_http import fetch_json

logger = logging.getLogger(__name__)

_API_BASE = "https://api.adzuna.com/v1/api/jobs"
_REMOTE_MARKERS = ("remote", "work from home", "wfh", "hybrid", "anywhere")

# ---------------------------------------------------------------------------
# Shared scale guards (S-FIX-A / S-2) — one Adzuna key, N subscribers.
#
# The free-tier key allows 25 calls/min and 250 calls/DAY across the WHOLE
# deployment. Before this, every scout run (scheduled tick AND every manual
# Sync click) issued up to ``AETHER_ADZUNA_MAX_PAGES`` uncached live calls, so
# a single 30-minute cron could consume ~240/250 on its own and any second
# subscriber pushed the key over its limit — after which the adapter kept
# hammering the exhausted key with no cooldown (a plain ``AdapterFetchError``
# is not eligible for the scout's 6h block-backoff).
#
# Three module-level guards close that, deliberately mirroring the proven
# ``_BENCH_CACHE`` design in ``app/agents/salary_intelligence_agent.py`` (the
# 6h benchmark cache that exists for these same Adzuna limits):
#
# 1. ``_SEARCH_CACHE`` — response cache keyed by the NORMALIZED request
#    identity (country, what_or, where, results_per_page, max_days_old, page),
#    so two users whose searches normalize to the same query share one set of
#    API calls instead of each issuing their own burst.
# 2. ``_CALL_LEDGER`` — calls actually issued per UTC day, checked-and-reserved
#    under a lock BEFORE each request so concurrent scout runs cannot race past
#    the ceiling. At budget the adapter serves the cache (honestly stamped with
#    the original fetch time) and NEVER silently returns an empty result.
# 3. ``_BLOCKED_UNTIL`` — a cooldown deadline set from an HTTP 429's
#    ``Retry-After``, so a rate-limited key is left alone instead of being
#    re-probed by every subsequent run.
#
# When a guard trips and the cache holds NOTHING for that search, the adapter
# raises ``SourceQuotaError`` (a ``SourceBlockedError`` subclass), and the
# message says plainly that no cached listings exist — it never offers a cache
# it does not have. The subclass is what lets the UI show this as a TEMPORARY
# "market data paused (API quota), resets 00:00 UTC" state instead of RT-008's
# permanent "blocked by source" pill, while the scout's block-backoff (which
# should absolutely apply to an exhausted shared key) is unchanged.
# ---------------------------------------------------------------------------

#: Response-cache TTL. 4h is the honest middle for job listings: Adzuna's own
#: index is refreshed on a multi-hour cadence and a posting that appears at
#: 09:00 is still live at 13:00, so a shorter TTL buys freshness the upstream
#: data does not actually have — while 4h still refreshes each distinct search
#: up to 6x/day, well inside the window in which a candidate would act on a new
#: posting. It is also what makes the budget arithmetic work: 6 refreshes x 5
#: pages = 30 calls/day per distinct search shape, so the 250/day key supports
#: several distinct subscriber searches instead of one. Matches the intent of
#: the 6h ``_BENCH_CACHE`` TTL (benchmarks move slower than listings, hence 4h
#: rather than 6h here).
DEFAULT_CACHE_TTL_SECONDS = 4 * 60 * 60

#: Adzuna free-tier daily call ceiling, and the margin held back from it so the
#: separate salary-benchmark path (3 calls per cache miss) and any operator
#: probing still fit inside the real limit.
DEFAULT_DAILY_BUDGET = 250
DEFAULT_BUDGET_SAFETY_MARGIN = 25

#: Fallback cooldown when a 429 carries no usable ``Retry-After``.
DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 300.0

_STATE_LOCK = threading.Lock()
#: cache key -> (monotonic fetched-at, wall-clock ISO fetched-at, payload)
_SEARCH_CACHE: dict[tuple[Any, ...], tuple[float, str, dict[str, Any]]] = {}
#: "YYYY-MM-DD" (UTC) -> live calls issued that day
_CALL_LEDGER: dict[str, int] = {}
#: monotonic deadline set by a 429 Retry-After; None when not rate-limited
_BLOCKED_UNTIL: float | None = None


def reset_scale_state() -> None:
    """Drop the cache / ledger / cooldown (tests and operator recovery)."""
    global _BLOCKED_UNTIL
    with _STATE_LOCK:
        _SEARCH_CACHE.clear()
        _CALL_LEDGER.clear()
        _BLOCKED_UNTIL = None


def _today_key() -> str:
    """UTC calendar day — the unit Adzuna's daily quota resets on."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _daily_budget() -> int:
    """Callable ceiling for today = configured budget minus the safety margin."""
    budget = _int_env("AETHER_ADZUNA_DAILY_BUDGET", DEFAULT_DAILY_BUDGET)
    margin = _int_env("AETHER_ADZUNA_BUDGET_SAFETY_MARGIN", DEFAULT_BUDGET_SAFETY_MARGIN)
    return max(0, budget - max(0, margin))


def budget_snapshot() -> dict[str, Any]:
    """Honest, readable view of today's Adzuna call budget (ops + tests)."""
    day = _today_key()
    budget = _daily_budget()
    with _STATE_LOCK:
        used = _CALL_LEDGER.get(day, 0)
    return {
        "date": day,
        "used": used,
        "budget": budget,
        "remaining": max(0, budget - used),
        "exhausted": used >= budget,
    }


def _reserve_call() -> bool:
    """Reserve ONE live call against today's budget. False when at the ceiling.

    Check-and-increment happen under the same lock so two concurrent scout runs
    cannot both see the last slot. A reserved call is never refunded on
    failure: Adzuna counts the request whatever it answers, so refunding would
    let a failing key be hammered for free.
    """
    day = _today_key()
    budget = _daily_budget()
    with _STATE_LOCK:
        used = _CALL_LEDGER.get(day, 0)
        if used >= budget:
            return False
        _CALL_LEDGER[day] = used + 1
        # Bound the ledger: only today's (and any in-flight yesterday) key matters.
        for stale in [k for k in _CALL_LEDGER if k < day]:
            _CALL_LEDGER.pop(stale, None)
        return True


def _cooldown_remaining() -> float:
    """Seconds left on an active 429 cooldown (0.0 when not rate-limited)."""
    global _BLOCKED_UNTIL
    with _STATE_LOCK:
        if _BLOCKED_UNTIL is None:
            return 0.0
        remaining = _BLOCKED_UNTIL - time.monotonic()
        if remaining <= 0:
            _BLOCKED_UNTIL = None
            return 0.0
        return remaining


def _start_cooldown(seconds: float) -> None:
    global _BLOCKED_UNTIL
    with _STATE_LOCK:
        deadline = time.monotonic() + max(1.0, seconds)
        if _BLOCKED_UNTIL is None or deadline > _BLOCKED_UNTIL:
            _BLOCKED_UNTIL = deadline


def _cache_key(
    country: str,
    what_or: str,
    where: str,
    results_per_page: int,
    max_days_old: int,
    page: int,
) -> tuple[Any, ...]:
    """Normalized request identity — case/whitespace variants share one entry."""
    return (
        country.strip().lower(),
        " ".join(what_or.split()).lower(),
        " ".join(where.split()).lower(),
        results_per_page,
        max_days_old,
        page,
    )


def _cache_get(
    key: tuple[Any, ...], *, allow_stale: bool = False
) -> tuple[dict[str, Any], str] | None:
    """Cached payload + its ORIGINAL fetch time, or None.

    ``allow_stale`` is the budget-exhausted path: an entry past its TTL is
    still real data that was really fetched, and serving it with its true
    ``dataAsOf`` is honest where returning nothing would be a silent lie.
    """
    ttl = float(_int_env("AETHER_ADZUNA_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS))
    with _STATE_LOCK:
        entry = _SEARCH_CACHE.get(key)
        if entry is None:
            return None
        fetched_at, fetched_iso, payload = entry
        if allow_stale or (time.monotonic() - fetched_at) < ttl:
            return payload, fetched_iso
        # A TTL-expired entry is a MISS but is NOT dropped: it is still real
        # data that was really fetched, and it is exactly what the
        # budget-exhausted / rate-limited path serves (with its true
        # ``dataAsOf``) instead of returning a silent empty result. Retention
        # and size are bounded in ``_cache_put`` instead.
        return None


def _cache_put(key: tuple[Any, ...], payload: dict[str, Any]) -> str:
    fetched_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    with _STATE_LOCK:
        _SEARCH_CACHE[key] = (time.monotonic(), fetched_iso, payload)
        _prune_cache_locked()
    return fetched_iso


#: How long an expired entry is KEPT as stale-serve material. Past a day it is
#: no longer honest fallback for "today's" listings — the quota has reset by
#: then, so a fresh call is available again.
_CACHE_RETENTION_SECONDS = 24 * 60 * 60
#: Hard ceiling on distinct cached search shapes, so many subscribers with many
#: distinct searches cannot grow this map without bound in a long-lived worker.
_CACHE_MAX_ENTRIES = 512


def _prune_cache_locked() -> None:
    """Bound the cache. Caller MUST hold ``_STATE_LOCK``."""
    now = time.monotonic()
    for key, (fetched_at, _iso, _payload) in list(_SEARCH_CACHE.items()):
        if now - fetched_at > _CACHE_RETENTION_SECONDS:
            _SEARCH_CACHE.pop(key, None)
    overflow = len(_SEARCH_CACHE) - _CACHE_MAX_ENTRIES
    if overflow > 0:
        for key, _entry in sorted(_SEARCH_CACHE.items(), key=lambda kv: kv[1][0])[
            :overflow
        ]:
            _SEARCH_CACHE.pop(key, None)


def _rate_limit_retry_after(exc: BaseException) -> float | None:
    """Retry-After seconds when ``exc`` is an HTTP 429, else None."""
    code = getattr(exc, "code", None)
    if code != 429:
        return None
    headers = getattr(exc, "headers", None)
    raw = None
    if headers is not None:
        try:
            raw = headers.get("Retry-After")
        except Exception:  # noqa: BLE001 — malformed header object, treat as absent
            raw = None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS


def _credentials() -> tuple[str | None, str | None]:
    """Adzuna app_id/app_key from the environment (os.environ only)."""
    return (
        (os.environ.get("ADZUNA_APP_ID") or "").strip() or None,
        (os.environ.get("ADZUNA_APP_KEY") or "").strip() or None,
    )


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class AdzunaAdapter(BaseAdapter):
    """Live adapter over the licensed Adzuna AU search API."""

    source = "adzuna"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        app_id, app_key = _credentials()
        if not app_id or not app_key:
            # Honest degrade: no live mode without licensed credentials. The
            # scout treats this as a benign skip (never fabricated data).
            raise NotImplementedError(
                "Adzuna AU live mode requires ADZUNA_APP_ID and ADZUNA_APP_KEY "
                "(free-tier developer credentials); absent — source skipped, "
                "volume relies on the keyless ATS + public-API sources."
            )

        country = (os.environ.get("AETHER_ADZUNA_COUNTRY", "au") or "au").strip().lower()
        results_per_page = _int_env("AETHER_ADZUNA_RESULTS_PER_PAGE", 50)
        max_pages = _int_env("AETHER_ADZUNA_MAX_PAGES", 5)
        max_days_old = _int_env("AETHER_ADZUNA_MAX_DAYS_OLD", 30)
        max_jobs = _int_env("AETHER_ADZUNA_MAX_JOBS", 200)

        # OR-search across the whole target-role family so a broadened scout
        # query (GAP-SRC-001) is honoured rather than AND-ing every term.
        what_or = " ".join(term.strip() for term in query.split(",") if term.strip())
        where = location or "Australia"

        results: list[dict[str, Any]] = []
        # Oldest fetch time contributing to this result — the honest dataAsOf
        # when any page came from cache.
        data_as_of: str | None = None
        served_from_cache = 0
        live_calls = 0
        for page in range(1, max_pages + 1):
            key = _cache_key(
                country, what_or, where, results_per_page, max_days_old, page
            )
            cached = _cache_get(key)
            if cached is not None:
                payload, fetched_iso = cached
                served_from_cache += 1
            else:
                # Not cached: this page needs a live call, which must clear both
                # scale guards first (429 cooldown, then today's budget).
                cooldown = _cooldown_remaining()
                # The CAUSE only — never a claim about what is being served.
                # Whether cached listings exist for this exact search is not
                # known until the lookup below, and the two outcomes get
                # different sentences (S-FIX-A round 2): promising "cached
                # listings are still served" in the branch that has none is
                # exactly the kind of reassuring fiction this product refuses.
                blocked_cause: str | None = None
                if cooldown > 0:
                    blocked_cause = (
                        "Adzuna is rate-limiting this key; cooling off for "
                        f"{int(cooldown)}s before the next call."
                    )
                elif not _reserve_call():
                    snapshot = budget_snapshot()
                    blocked_cause = (
                        "Adzuna daily API quota reached "
                        f"({snapshot['used']}/{snapshot['budget']} calls on "
                        f"{snapshot['date']}); it resets at 00:00 UTC."
                    )
                if blocked_cause is not None:
                    # NEVER a silent empty result: fall back to whatever real
                    # data we already hold for this exact search, stale or not,
                    # keeping its ORIGINAL fetch time.
                    stale = _cache_get(key, allow_stale=True)
                    if stale is not None:
                        payload, fetched_iso = stale
                        served_from_cache += 1
                        logger.warning(
                            "adzuna: %s Market data refresh is paused until "
                            "then — cached listings are still served. "
                            "Serving cached page %d (dataAsOf=%s)",
                            blocked_cause, page, fetched_iso,
                        )
                    elif page == 1:
                        # Nothing real to serve, so the message must NOT offer
                        # the cache as consolation. SourceQuotaError (not a
                        # plain AdapterFetchError, and not a bare
                        # SourceBlockedError) so the scout applies its block
                        # backoff instead of re-probing an exhausted key on
                        # every tick, while the Jobs screen can tell this
                        # TEMPORARY, self-healing pause apart from a source
                        # that structurally refuses us (RT-008) and show this
                        # message instead of a flat "blocked by source" pill.
                        message = (
                            f"{blocked_cause} No cached listings for this "
                            "search yet."
                        )
                        logger.warning("adzuna: %s", message)
                        raise SourceQuotaError(message)
                    else:
                        logger.warning(
                            "adzuna: %s stopping after page %d", blocked_cause, page - 1
                        )
                        break
                else:
                    url = (
                        f"{_API_BASE}/{country}/search/{page}"
                        f"?app_id={quote_plus(app_id)}&app_key={quote_plus(app_key)}"
                        f"&results_per_page={results_per_page}"
                        f"&what_or={quote_plus(what_or)}"
                        f"&where={quote_plus(where)}"
                        f"&max_days_old={max_days_old}"
                        "&sort_by=date&content-type=application/json"
                    )
                    try:
                        payload = fetch_json(url)
                    except Exception as exc:  # noqa: BLE001 — surface honestly
                        retry_after = _rate_limit_retry_after(exc)
                        if retry_after is not None:
                            _start_cooldown(retry_after)
                            cause = (
                                "Adzuna rate limit reached (HTTP 429); backing off "
                                f"for {int(retry_after)}s before the next call."
                            )
                            stale = _cache_get(key, allow_stale=True)
                            if stale is not None:
                                payload, fetched_iso = stale
                                served_from_cache += 1
                                logger.warning(
                                    "adzuna: %s Cached listings are still "
                                    "served meanwhile (dataAsOf=%s)",
                                    cause, fetched_iso,
                                )
                            elif page == 1:
                                # Same honesty split as the budget path: no
                                # cache here, so no promise of one.
                                message = (
                                    f"{cause} No cached listings for this "
                                    "search yet."
                                )
                                logger.warning("adzuna: %s", message)
                                raise SourceQuotaError(message) from exc
                            else:
                                logger.warning(
                                    "adzuna: %s stopping after page %d",
                                    cause, page - 1,
                                )
                                break
                        elif page == 1:
                            logger.warning("adzuna: search failed on page 1: %s", exc)
                            raise AdapterFetchError(
                                f"Adzuna AU search failed: {type(exc).__name__}: {exc}"
                            ) from exc
                        else:
                            logger.warning("adzuna: page %d failed: %s", page, exc)
                            break
                    else:
                        if not isinstance(payload, dict):
                            payload = {"results": []}
                        fetched_iso = _cache_put(key, payload)
                        live_calls += 1
            if data_as_of is None or fetched_iso < data_as_of:
                data_as_of = fetched_iso
            batch = payload.get("results", []) if isinstance(payload, dict) else []
            results.extend(batch)
            # Exhausted (short page) or hit the sane job cap.
            if len(batch) < results_per_page or len(results) >= max_jobs:
                break
        logger.info(
            "adzuna: %d results (live calls=%d, cached pages=%d, dataAsOf=%s, "
            "budget=%s)",
            len(results), live_calls, served_from_cache, data_as_of,
            budget_snapshot(),
        )
        return {
            "results": results[:max_jobs],
            # Provenance for callers/logs; ``_parse`` reads only ``results``.
            "dataAsOf": data_as_of,
            "servedFromCache": served_from_cache > 0,
        }

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for item in payload.get("results", []):
            apply_url = str(item.get("redirect_url") or "")
            if not apply_url:
                continue
            company = str((item.get("company") or {}).get("display_name") or "")
            location = str((item.get("location") or {}).get("display_name") or "")
            title = str(item.get("title") or "")
            remote = any(
                m in f"{title} {location}".lower() for m in _REMOTE_MARKERS
            )
            salary_min = item.get("salary_min")
            salary_max = item.get("salary_max")
            jobs.append(
                JobRaw(
                    title=title,
                    company=company,
                    location=location or None,
                    remote=remote,
                    description=relevance.snippet(
                        item.get("description"), limit=relevance.DESCRIPTION_STORAGE_LIMIT
                    ),
                    requirements=[],
                    source=self.source,
                    sourceUrl=apply_url,
                    postedAt=str(item.get("created") or "") or None,
                    salaryMin=int(salary_min) if salary_min is not None else None,
                    salaryMax=int(salary_max) if salary_max is not None else None,
                    currency="AUD" if (salary_min is not None or salary_max is not None) else None,
                )
            )
        return relevance.filter_applicable(jobs)
