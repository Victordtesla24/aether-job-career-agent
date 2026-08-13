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
location, four things read VERBATIM from three of the provider's real
endpoints: the number of ads posted in the last 30 days and the mean advertised
salary across that matching set (``/search``), the average advertised salary per
month for the last 12 months (``/history``), and the count of live ads per
advertised-salary band (``/histogram``). Nothing is modelled, interpolated or
extrapolated from any of them: Adzuna publishes no percentiles, so none are
derived — in particular no percentile or median is ever interpolated from the
histogram's bands — and no other market dimension (interview conversion,
application volume per candidate) has a provider at all, so those stay honestly
unavailable rather than being approximated from salary data. The two endpoints'
scopes differ from ``/search``'s and must be reported as they really are:
``/history`` is not filtered by role at all (it is every advertised role in the
country or state), and both are keyed by Adzuna's location hierarchy rather than
by the free-text place the user typed. Credentials absent, fixture mode, or a
``/search`` failure ⇒ the benchmark is ``None`` and every surface reports "not
connected"; a ``/history`` or ``/histogram`` failure leaves only ITS field
``None`` and keeps the ``/search`` figures the call already earned. A cache
entry past its TTL is evicted and refetched, and a failed refetch NEVER
re-serves the stale numbers.

HONEST SCOPE, part 3 — :func:`user_disclosed_salary_median` (own corpus, one
number). The caller's own side of the advertised-salary comparison: the median
of what their OWN saved postings disclosed, under the same three rules as part
one. Nothing is imputed for a posting that disclosed nothing, and a caller with
no disclosures gets ``None`` — never a zero, and never the market's figure.

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
import re
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

#: How long a FAILED attempt is remembered (negative cache / backoff window).
#: Without it a sustained provider outage would defeat the cache entirely —
#: every request for that key would evict nothing, find nothing, and issue
#: another live call, walking straight into the 25/min rate limit. What is
#: cached is the ABSENCE of data (an honest "not connected"), never numbers,
#: so this window is kept far shorter than the success TTL and the benchmark
#: reappears within a minute of the provider recovering.
_BENCH_FAILURE_TTL_SECONDS = 60

#: The posting-count window. ``count`` under ``max_days_old=30`` is exactly
#: "ads posted in the last 30 days" — a real per-month market-activity figure,
#: not a rate derived from anything.
_BENCH_MAX_DAYS_OLD = 30

#: ``/history`` and ``/histogram`` are keyed by Adzuna's LOCATION HIERARCHY, not
#: by free text, and ``location0`` must be the country's FULL NAME — it is NOT
#: interchangeable with the two-letter country segment in the ``/search`` path
#: (``/jobs/au/...``). Live-verified 2026-08-13 against the real API:
#: ``location0=Australia`` → HTTP 200 with a ``month`` map, ``location0=AU`` →
#: HTTP 400 (an HTML error page from the provider's edge, before the API is
#: reached at all). Evidence: ``uat/reports/evidence/market-perf/discovery/``
#: ``01-history-au-victoria`` vs ``01a-history-au-victoria``.
_ADZUNA_COUNTRY = "Australia"

#: Months of advertised-salary history requested per call. Live-verified as an
#: accepted parameter on 2026-08-13 (HTTP 200, 12 months, 2025-08..2026-07):
#: ``uat/reports/evidence/models-live/market-perf-I3/``
#: ``PROBE-history-months-param-20260813T092544Z.txt``. It is sent explicitly
#: rather than relying on the endpoint's default, which is undocumented and
#: could change silently; the surface reports the number of months it actually
#: received either way.
_BENCH_HISTORY_MONTHS = 12

#: Full state names Adzuna accepts as ``location1``, and the spellings a user's
#: own location string may name them with. Matched on WORD BOUNDARIES only,
#: never as bare substrings, so "Sale" is not read as "SA" nor "Wagga" as "WA".
#: Longest phrase first so "New South Wales" cannot be shadowed by a shorter
#: overlapping name. A location naming no state (a bare city, e.g. "Melbourne")
#: yields ``None`` and the call stays NATIONAL: the state a city sits in is not
#: derived here, because a surface citing the result states the scope it asked
#: for, and asking nationally is honest where guessing would not be.
_ADZUNA_STATE_PHRASES: tuple[tuple[str, str], ...] = (
    ("australian capital territory", "Australian Capital Territory"),
    ("new south wales", "New South Wales"),
    ("northern territory", "Northern Territory"),
    ("western australia", "Western Australia"),
    ("south australia", "South Australia"),
    ("queensland", "Queensland"),
    ("tasmania", "Tasmania"),
    ("victoria", "Victoria"),
)
_ADZUNA_STATE_ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    ("act", "Australian Capital Territory"),
    ("nsw", "New South Wales"),
    ("nt", "Northern Territory"),
    ("qld", "Queensland"),
    ("sa", "South Australia"),
    ("tas", "Tasmania"),
    ("vic", "Victoria"),
    ("wa", "Western Australia"),
)

#: Every benchmark call carries an explicit hard timeout: this runs inside a
#: user-facing request, so a hung provider must degrade to honest-unavailable
#: quickly rather than hold the request open.
_BENCH_HTTP_TIMEOUT_SECONDS = 10

#: (role, location) -> (``time.monotonic()`` at the attempt, benchmark — or
#: ``None`` when that attempt FAILED, held only for
#: :data:`_BENCH_FAILURE_TTL_SECONDS`). Module-level on purpose: the whole
#: point is to serve many requests from one upstream call. ``monotonic``
#: (never wall-clock) so a clock adjustment can neither resurrect an expired
#: entry nor expire a fresh one.
_BENCH_CACHE: dict[tuple[str, str], tuple[float, "MarketBenchmark | None"]] = {}


@dataclass(frozen=True)
class MarketBenchmark:
    """One provider response, as received — no derived or imputed fields.

    ``postingsLast30d`` is Adzuna's top-level ``count`` for the role+location
    search restricted to the last 30 days; ``meanAdvertisedSalary`` is that
    same response's top-level ``mean`` (AUD, across the full matching set, not
    a page sample). Either is ``None`` when the provider omitted it — never
    zero, never a stand-in. ``dataAsOf`` is the instant the fetch actually
    happened, so a cached row keeps reporting its ORIGINAL fetch time.

    ``salaryTrend12m`` maps each of the last 12 months (``"YYYY-MM"``) to the
    AVERAGE ADVERTISED SALARY that month, and — this is a property of the
    provider's endpoint, not a choice made here — covers EVERY advertised role
    in the country or state, not this caller's target role. Any surface citing
    it must say so. ``salaryHistogram`` maps an advertised-salary band (the
    provider's own key) to the number of live ads for the target role in it; it
    is a count per band and nothing more, so no percentile, median or
    distribution parameter is ever interpolated from it. Each is ``None`` when
    its own call failed or returned nothing — the ``/search`` figures above
    stand on their own either way.
    """

    role: str
    location: str
    postingsLast30d: int | None
    meanAdvertisedSalary: float | None
    salaryTrend12m: dict[str, float] | None
    salaryHistogram: dict[str, int] | None
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


def _adzuna_state(location: str) -> str | None:
    """The Adzuna ``location1`` state ``location`` names, or ``None``.

    ``None`` means "this location names no state", and the caller then asks
    Adzuna nationally rather than picking a state for the user. Matching is on
    word boundaries so an abbreviation can only match when it stands alone.
    """
    lowered = (location or "").casefold()
    if not lowered:
        return None
    for phrase, full_name in _ADZUNA_STATE_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return full_name
    tokens = set(re.findall(r"[a-z]+", lowered))
    for abbreviation, full_name in _ADZUNA_STATE_ABBREVIATIONS:
        if abbreviation in tokens:
            return full_name
    return None


def benchmark_region_label(location: str) -> str:
    """The region the ``/history`` and ``/histogram`` calls for ``location``
    ACTUALLY cover — the state it names, or the whole country when it names
    none. Exposed because a surface quoting those figures has to state the
    scope that was really asked for, which is not always the place the user
    typed (a city is asked for nationally, see :data:`_ADZUNA_STATE_PHRASES`).
    """
    return _adzuna_state(location) or _ADZUNA_COUNTRY


def _location_hierarchy_params(location: str) -> dict[str, Any]:
    """``location0``/``location1`` for the hierarchy-keyed endpoints."""
    params: dict[str, Any] = {"location0": _ADZUNA_COUNTRY}
    state = _adzuna_state(location)
    if state:
        params["location1"] = state
    return params


def _fetch_json_object(url: str, what: str, role: str, location: str) -> dict[str, Any] | None:
    """One benchmark GET, or ``None`` with the REAL failure logged.

    ``what`` names the endpoint in the log line so an operator reading a
    warning knows which of the three calls degraded and how — the message
    carries the provider's own error, never a sanitised placeholder.
    """
    try:
        payload = fetch_json(url, timeout=_BENCH_HTTP_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — surface a real outage honestly
        logger.warning(
            "adzuna market benchmark: %s failed for role=%r location=%r: %s: %s",
            what,
            role,
            location,
            type(exc).__name__,
            exc,
        )
        return None
    if not isinstance(payload, dict):
        logger.warning(
            "adzuna market benchmark: %s returned %s, expected a JSON object "
            "(role=%r location=%r)",
            what,
            type(payload).__name__,
            role,
            location,
        )
        return None
    return payload


def _fetch_salary_history(
    app_id: str, app_key: str, role: str, location: str
) -> dict[str, float] | None:
    """Month -> average advertised salary for the last 12 months, or ``None``.

    ACROSS ALL ADVERTISED ROLES in the country or state: Adzuna's ``/history``
    takes no role parameter at all, so this is deliberately NOT filtered to the
    caller's target role and must never be presented as if it were. A failure
    here is logged and returns ``None``; it does not invalidate the ``/search``
    figures (R11 partial honesty).
    """
    params: dict[str, Any] = {"app_id": app_id, "app_key": app_key}
    params.update(_location_hierarchy_params(location))
    params["months"] = _BENCH_HISTORY_MONTHS
    payload = _fetch_json_object(
        f"{_ADZUNA_API_BASE}/au/history?" + urlencode(params), "history", role, location
    )
    if payload is None:
        return None
    months = payload.get("month")
    if not isinstance(months, dict):
        logger.warning(
            "adzuna market benchmark: history response carried no 'month' map "
            "(role=%r location=%r)",
            role,
            location,
        )
        return None
    trend = {
        str(month): value
        for month, raw in months.items()
        if (value := _float_or_none(raw)) is not None
    }
    return trend or None


def _fetch_salary_histogram(
    app_id: str, app_key: str, role: str, location: str
) -> dict[str, int] | None:
    """Advertised-salary band -> live-ad count for ``role``, or ``None``.

    ``what`` is the caller's PRIMARY role term (``/histogram`` takes a single
    phrase, not the OR-list ``/search`` accepts), so this is narrower than the
    posting count and is reported as being about the target role. Counts are
    the provider's own; no band is split, merged or interpolated. A failure is
    logged and returns ``None`` without touching the ``/search`` figures.
    """
    terms = benchmark_query_terms(role)
    params: dict[str, Any] = {
        "app_id": app_id,
        "app_key": app_key,
        "what": terms[0] if terms else role,
    }
    params.update(_location_hierarchy_params(location))
    payload = _fetch_json_object(
        f"{_ADZUNA_API_BASE}/au/histogram?" + urlencode(params), "histogram", role, location
    )
    if payload is None:
        return None
    bands = payload.get("histogram")
    if not isinstance(bands, dict):
        logger.warning(
            "adzuna market benchmark: histogram response carried no 'histogram' "
            "map (role=%r location=%r)",
            role,
            location,
        )
        return None
    counts = {
        str(band): value
        for band, raw in bands.items()
        if (value := _int_or_none(raw)) is not None
    }
    return counts or None


def user_disclosed_salary_median(user_id: str) -> int | None:
    """Median of the salary figures ``user_id``'s OWN saved postings disclosed,
    or ``None`` when none of them disclosed anything.

    The caller's side of the advertised-salary comparison, and it obeys the
    module's three rules. ONE figure is taken per posting — its disclosed
    maximum, falling back to its minimum ONLY when that posting disclosed no
    maximum at all — because a posting that named a range is one advertised
    job, not two data points, and the top of the range is the figure its
    advertiser competed on. Nothing is imputed: a posting that disclosed
    neither bound contributes nothing (it is NOT a zero), and a caller with no
    disclosures at all gets ``None``, never the market's number in place of
    their own.

    Currency: rows are kept when they say ``AUD`` and when they say nothing,
    and dropped otherwise, so a USD range can never be averaged into a figure
    the surface prints beside an AUD market mean. Blank is kept rather than
    dropped on the evidence of the adapters that write these rows: the AU
    sources set ``currency`` only alongside a disclosed MINIMUM
    (``seek_adapter``: ``"AUD" if salary_min is not None else None``), so an
    AU posting that advertised only a maximum arrives with the column empty —
    dropping it would silently discard real AUD disclosures.
    """
    values: list[int] = []
    for job in JobRepository().list_by_user(user_id):
        currency = (job.get("currency") or "").strip().upper()
        if currency and currency != "AUD":
            continue
        disclosed = _int_or_none(job.get("salaryMax"))
        if disclosed is None:
            disclosed = _int_or_none(job.get("salaryMin"))
        if disclosed is not None:
            values.append(disclosed)
    if not values:
        return None
    return round(statistics.median(values))


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
    payload = _fetch_json_object(url, "search", role, location)
    if payload is None:
        return None
    return _int_or_none(payload.get("count")), _float_or_none(payload.get("mean"))


def fetch_market_benchmark(role: str, location: str) -> MarketBenchmark | None:
    """The live Adzuna AU benchmark for ``role`` in ``location``, or ``None``.

    ``None`` is the honest "no external market data" answer and is returned —
    without any network call — when the caller has no target role or location,
    when the licensed credentials are absent, or when fixture mode is active
    (``AETHER_DISCOVERY_FIXTURE_DIR``, the gate the test suite sets so no test
    can reach the live provider). It is ALSO the answer whenever the ``/search``
    fetch itself fails, including a refetch that fails after a cached entry
    expired: stale numbers are never re-served behind a fresh-looking "as of"
    label. The two enrichment calls are weaker: a ``/history`` or ``/histogram``
    failure nulls only its own field and leaves the ``/search`` figures intact,
    because discarding data the provider really did return would be its own
    kind of dishonesty.
    A failure is itself cached for a short backoff window
    (:data:`_BENCH_FAILURE_TTL_SECONDS`) — the absence of data, never numbers
    — so a sustained outage cannot turn every request back into a live call.
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
        # A cached FAILURE is backoff, not data: it expires far sooner than a
        # cached benchmark, so a recovered provider is picked up within the
        # minute instead of waiting out the full data TTL.
        entry_ttl = ttl if benchmark is not None else min(_BENCH_FAILURE_TTL_SECONDS, ttl)
        if time.monotonic() - fetched_at < entry_ttl:
            return benchmark
        # Expired: evict FIRST, so a failing refetch below cannot fall back
        # onto the stale entry by any path.
        _BENCH_CACHE.pop(cache_key, None)

    counts = _fetch_search_counts(app_id, app_key, role_q, location_q)
    if counts is None:
        # Remember the FAILURE (never the previous numbers — the expired entry
        # was already evicted above) so the next requests during an outage back
        # off instead of each issuing their own live call.
        _BENCH_CACHE[cache_key] = (time.monotonic(), None)
        return None
    postings, mean_salary = counts

    # PARTIAL HONESTY (R11): these two enrich the summary but neither is what
    # the panel's rows are built from, so a failure in either one degrades ITS
    # OWN field to ``None`` — logged, never swallowed — while the ``/search``
    # figures above stay exactly as the provider reported them. Both run on
    # every genuine refresh, so all three fields carry the same ``dataAsOf``.
    trend = _fetch_salary_history(app_id, app_key, role_q, location_q)
    histogram = _fetch_salary_histogram(app_id, app_key, role_q, location_q)

    fresh = MarketBenchmark(
        role=role_q,
        location=location_q,
        postingsLast30d=postings,
        meanAdvertisedSalary=mean_salary,
        salaryTrend12m=trend,
        salaryHistogram=histogram,
        # Millisecond precision: two fetches of the same key are separated by a
        # whole request cycle, and second-resolution stamps would collide and
        # make a genuine refetch indistinguishable from a cache hit.
        dataAsOf=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    )
    _BENCH_CACHE[cache_key] = (time.monotonic(), fresh)
    return fresh
