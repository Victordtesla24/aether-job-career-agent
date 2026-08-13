"""Salary Intelligence Agent — own-corpus salary aggregation (wave-4A, ADR-AG-1)
plus the live Adzuna AU market benchmark that feeds Market vs. You (ADR D-0042).

HONEST SCOPE, part 1 — :class:`SalaryIntelligenceAgent` (own corpus). The only
pay data Aether holds about the CALLER is whatever each discovered posting
DISCLOSED (``Job.salaryMin`` / ``salaryMax`` / ``currency``, populated by the
discovery adapters). The agent aggregates exactly that, grouped by role family /
location / currency, and always reports how many postings disclosed anything at
all ("N of M disclosed").

HONEST SCOPE, part 2 — :func:`fetch_market_benchmark` (external market).
Aether now integrates ONE licensed external benchmark: the Adzuna AU API, the
same provider the discovery adapter already uses. It supplies, for a role +
location, the number of ads posted in the last 30 days and the mean advertised
salary across that matching set — both read verbatim from the provider's
response. Nothing is modelled, interpolated or extrapolated from it: Adzuna
publishes no percentiles, so none are derived, and no other market dimension
(interview conversion, application volume per candidate) has a provider at all,
so those stay honestly unavailable rather than being approximated from salary
data. Credentials absent, fixture mode, or ANY fetch failure ⇒ the benchmark is
``None`` and every surface reports "not connected"; a cache entry past its TTL
is evicted and refetched, and a failed refetch NEVER re-serves the stale numbers.

Three hard rules for the own-corpus aggregation, each enforced below:

* **Never impute.** A posting that discloses only a maximum contributes to the
  maximum statistics and leaves the minimum statistics genuinely empty. A missing
  bound is never derived from the other bound, from a sibling posting, or from a
  market average.
* **Never merge currencies.** Currency is part of the group key, so an AUD range
  and a USD range are never averaged together. An undisclosed currency is
  labelled ``unspecified`` rather than assumed to be the user's local currency.
* **Never guess a role family.** A title that matches none of the known family
  terms is grouped as ``unclassified`` with its real titles listed.

Deterministic and unmetered: no LLM call, so no spend and no plan-quota
reservation (absent from ``_LLM_TIER_BY_BACKEND``).
"""
from __future__ import annotations

import logging
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from app.repositories.job import JobRepository
from app.services.discovery.live_http import fetch_json
from app.services.discovery.query_builder import ROLE_FAMILY_TERMS, build_scout_query

logger = logging.getLogger(__name__)

#: Longest term first so "technical program manager" wins over "program manager".
_FAMILY_TERMS: tuple[str, ...] = tuple(
    sorted(ROLE_FAMILY_TERMS, key=len, reverse=True)
)

#: Label for a title that matches no known family term — an honest "not
#: classified", never a silent assignment to the nearest family.
UNCLASSIFIED = "unclassified"

#: Label for a field the posting did not disclose.
UNSPECIFIED = "unspecified"


def classify_role_family(title: str | None) -> str:
    """The role-family term ``title`` belongs to, or :data:`UNCLASSIFIED`.

    Uses the SAME vocabulary the scout query builder broadens searches with
    (``query_builder.ROLE_FAMILY_TERMS``), so discovery and this report never
    disagree about what counts as one family.
    """
    lowered = (title or "").lower()
    for term in _FAMILY_TERMS:
        if term in lowered:
            return term
    return UNCLASSIFIED


@dataclass
class BoundStats:
    """Statistics over ONE salary bound, across only the postings that actually
    disclosed that bound. All ``None`` when nothing disclosed it."""

    disclosed: int = 0
    low: int | None = None
    high: int | None = None
    median: float | None = None


def _bound_stats(values: list[int]) -> BoundStats:
    if not values:
        return BoundStats()
    return BoundStats(
        disclosed=len(values),
        low=min(values),
        high=max(values),
        median=float(statistics.median(values)),
    )


@dataclass
class SalaryGroup:
    roleFamily: str
    location: str
    currency: str
    postings: int
    disclosed: int
    titles: list[str]
    salaryMin: BoundStats
    salaryMax: BoundStats


@dataclass
class SalaryIntelligenceReport:
    postings: int = 0
    disclosed: int = 0
    disclosureRate: float | None = None
    currencies: dict[str, int] = field(default_factory=dict)
    groups: list[SalaryGroup] = field(default_factory=list)
    method: str = (
        "Disclosed ranges only — no imputation of a missing bound, no external "
        "benchmark, and currencies are never merged."
    )
    message: str = ""


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class SalaryIntelligenceAgent:
    """Aggregates disclosed salary ranges across the caller's own postings."""

    def __init__(self, jobs: JobRepository | None = None) -> None:
        self._jobs = jobs or JobRepository()

    def run(self, user_id: str) -> SalaryIntelligenceReport:
        postings = self._jobs.list_by_user(user_id)
        report = SalaryIntelligenceReport(postings=len(postings))
        if not postings:
            report.message = (
                "No discovered postings yet — run Job Discovery first, then this "
                "report has real disclosed ranges to aggregate."
            )
            return report

        buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
        for job in postings:
            currency = (job.get("currency") or "").strip().upper() or UNSPECIFIED
            location = (job.get("location") or "").strip() or UNSPECIFIED
            family = classify_role_family(job.get("title"))
            report.currencies[currency] = report.currencies.get(currency, 0) + 1

            bucket = buckets.setdefault(
                (family, location, currency),
                {"postings": 0, "disclosed": 0, "titles": set(), "mins": [], "maxes": []},
            )
            bucket["postings"] += 1
            title = (job.get("title") or "").strip()
            if title:
                bucket["titles"].add(title)
            low = _int_or_none(job.get("salaryMin"))
            high = _int_or_none(job.get("salaryMax"))
            if low is not None:
                bucket["mins"].append(low)
            if high is not None:
                bucket["maxes"].append(high)
            if low is not None or high is not None:
                bucket["disclosed"] += 1
                report.disclosed += 1

        report.disclosureRate = round(report.disclosed / report.postings, 3)
        report.groups = sorted(
            (
                SalaryGroup(
                    roleFamily=family,
                    location=location,
                    currency=currency,
                    postings=data["postings"],
                    disclosed=data["disclosed"],
                    titles=sorted(data["titles"]),
                    salaryMin=_bound_stats(data["mins"]),
                    salaryMax=_bound_stats(data["maxes"]),
                )
                for (family, location, currency), data in buckets.items()
            ),
            key=lambda g: (-g.postings, g.roleFamily, g.location, g.currency),
        )
        report.message = self._message(report)
        return report

    @staticmethod
    def _message(report: SalaryIntelligenceReport) -> str:
        head = (
            f"{report.disclosed} of {report.postings} discovered postings "
            "disclosed a salary range"
        )
        if report.disclosed == 0:
            return (
                f"{head} — there is nothing to aggregate, and no range is "
                "estimated in its place."
            )
        return (
            f"{head}, aggregated across {len(report.groups)} role-family / "
            "location / currency group(s). Undisclosed bounds are left empty, "
            "never imputed."
        )


# ---------------------------------------------------------------------------
# Live external market benchmark — Adzuna AU (ADR D-0042)
#
# The ONLY external market data source in the product. Everything below reads
# the provider's own response fields verbatim; nothing is modelled from them.
# ---------------------------------------------------------------------------

#: Same licensed API the discovery adapter uses (``adzuna_adapter._API_BASE``).
_ADZUNA_API_BASE = "https://api.adzuna.com/v1/api/jobs"

#: Adzuna's published ToS defaults are 25 calls/minute and 250/day, so the
#: benchmark is cached and NEVER fetched per user request. Six hours is the
#: hard ceiling: a "market data as of" label older than that would misdescribe
#: a job market that moves daily.
_BENCH_TTL_DEFAULT_SECONDS = 21600
_BENCH_TTL_MIN_SECONDS = 60
_BENCH_TTL_MAX_SECONDS = 21600

#: The posting-count window. ``count`` under ``max_days_old=30`` is exactly
#: "ads posted in the last 30 days" — a real per-month market-activity figure,
#: not a rate derived from anything.
_BENCH_MAX_DAYS_OLD = 30

#: Every benchmark call carries an explicit hard timeout: this runs inside a
#: user-facing request, so a hung provider must degrade to honest-unavailable
#: quickly rather than hold the request open.
_BENCH_HTTP_TIMEOUT_SECONDS = 10

#: (role, location) -> (``time.monotonic()`` at fetch, benchmark). Module-level
#: on purpose: the whole point is to serve many requests from one upstream
#: call. ``monotonic`` (never wall-clock) so a clock adjustment can neither
#: resurrect an expired entry nor expire a fresh one.
_BENCH_CACHE: dict[tuple[str, str], tuple[float, "MarketBenchmark"]] = {}


@dataclass(frozen=True)
class MarketBenchmark:
    """One provider response, as received — no derived or imputed fields.

    ``postingsLast30d`` is Adzuna's top-level ``count`` for the role+location
    search restricted to the last 30 days; ``meanAdvertisedSalary`` is that
    same response's top-level ``mean`` (AUD, across the full matching set, not
    a page sample). Either is ``None`` when the provider omitted it — never
    zero, never a stand-in. ``dataAsOf`` is the instant the fetch actually
    happened, so a cached row keeps reporting its ORIGINAL fetch time.
    """

    role: str
    location: str
    postingsLast30d: int | None
    meanAdvertisedSalary: float | None
    dataAsOf: str
    source: str = "adzuna"


def _adzuna_credentials() -> tuple[str | None, str | None]:
    """Adzuna app_id/app_key from the environment (``os.environ`` only)."""
    return (
        (os.environ.get("ADZUNA_APP_ID") or "").strip() or None,
        (os.environ.get("ADZUNA_APP_KEY") or "").strip() or None,
    )


def _bench_ttl_seconds() -> int:
    """Benchmark cache TTL, clamped to [60s, 6h]. An unparseable or
    out-of-range override falls back into the range rather than disabling the
    cache (which would breach the provider's rate limits) or extending it past
    the point where "as of" stops being true."""
    raw = (os.environ.get("AETHER_ADZUNA_BENCH_TTL_SECONDS") or "").strip()
    try:
        ttl = int(raw) if raw else _BENCH_TTL_DEFAULT_SECONDS
    except ValueError:
        ttl = _BENCH_TTL_DEFAULT_SECONDS
    return max(_BENCH_TTL_MIN_SECONDS, min(_BENCH_TTL_MAX_SECONDS, ttl))


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def benchmark_query_terms(role: str) -> list[str]:
    """The exact titles the benchmark OR-searches for ``role``.

    The caller's whole target-role family, exactly as the discovery adapter
    broadens it (GAP-SRC-001), so the benchmark measures the same market this
    user's scout actually searches. Exposed because a surface reporting the
    resulting count MUST be able to say how wide the search really was: for a
    role outside the recognised families this is the single title the user
    typed, for one inside a family it is the whole family.
    """
    return [term.strip() for term in build_scout_query(role).split(",") if term.strip()]


def _fetch_search_counts(
    app_id: str, app_key: str, role: str, location: str
) -> tuple[int | None, float | None] | None:
    """``(count, mean)`` from one Adzuna ``/search`` call, or ``None`` if the
    call failed. A failure is logged with the REAL error — never swallowed,
    never replaced with a placeholder figure."""
    what_or = " ".join(benchmark_query_terms(role))
    url = f"{_ADZUNA_API_BASE}/au/search/1?" + urlencode(
        {
            "app_id": app_id,
            "app_key": app_key,
            "what_or": what_or,
            "where": location,
            "results_per_page": 1,
            "max_days_old": _BENCH_MAX_DAYS_OLD,
            "content-type": "application/json",
        }
    )
    try:
        payload = fetch_json(url, timeout=_BENCH_HTTP_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — surface a real outage honestly
        logger.warning(
            "adzuna market benchmark: search failed for role=%r location=%r: %s: %s",
            role,
            location,
            type(exc).__name__,
            exc,
        )
        return None
    if not isinstance(payload, dict):
        logger.warning(
            "adzuna market benchmark: search returned %s, expected a JSON object "
            "(role=%r location=%r)",
            type(payload).__name__,
            role,
            location,
        )
        return None
    return _int_or_none(payload.get("count")), _float_or_none(payload.get("mean"))


def fetch_market_benchmark(role: str, location: str) -> MarketBenchmark | None:
    """The live Adzuna AU benchmark for ``role`` in ``location``, or ``None``.

    ``None`` is the honest "no external market data" answer and is returned —
    without any network call — when the caller has no target role or location,
    when the licensed credentials are absent, or when fixture mode is active
    (``AETHER_DISCOVERY_FIXTURE_DIR``, the gate the test suite sets so no test
    can reach the live provider). It is ALSO the answer whenever the fetch
    itself fails, including a refetch that fails after a cached entry expired:
    stale numbers are never re-served behind a fresh-looking "as of" label.
    """
    role_q = (role or "").strip()
    location_q = (location or "").strip()
    if not role_q or not location_q:
        # F-02: no substitution. Without the user's OWN target there is no
        # honest market to compare them against.
        return None

    app_id, app_key = _adzuna_credentials()
    if not app_id or not app_key:
        return None

    if (os.environ.get("AETHER_DISCOVERY_FIXTURE_DIR") or "").strip():
        return None

    cache_key = (role_q.casefold(), location_q.casefold())
    ttl = _bench_ttl_seconds()
    cached = _BENCH_CACHE.get(cache_key)
    if cached is not None:
        fetched_at, benchmark = cached
        if time.monotonic() - fetched_at < ttl:
            return benchmark
        # Expired: evict FIRST, so a failing refetch below cannot fall back
        # onto the stale entry by any path.
        _BENCH_CACHE.pop(cache_key, None)

    counts = _fetch_search_counts(app_id, app_key, role_q, location_q)
    if counts is None:
        return None
    postings, mean_salary = counts

    fresh = MarketBenchmark(
        role=role_q,
        location=location_q,
        postingsLast30d=postings,
        meanAdvertisedSalary=mean_salary,
        # Millisecond precision: two fetches of the same key are separated by a
        # whole request cycle, and second-resolution stamps would collide and
        # make a genuine refetch indistinguishable from a cache hit.
        dataAsOf=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    )
    _BENCH_CACHE[cache_key] = (time.monotonic(), fresh)
    return fresh
