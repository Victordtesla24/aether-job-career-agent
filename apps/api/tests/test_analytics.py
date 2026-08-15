"""P2-S10 — Analytics endpoint tests (funnel, periods, agent ROI)."""
from __future__ import annotations

import contextlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

import pytest
from conftest import seed_search_target

from app.db import get_connection, new_id


class _RecordingCursor:
    """Delegating psycopg2 cursor wrapper that records every SQL string —
    same idiom as ``test_mon001_board_sweep_bounded_read.py``'s
    ``_RecordingCursor``, reused here so MUST-FIX-2 (AX round-3 final
    re-review) can assert on the ACTUAL SQL text ``market_pulse()`` issues,
    rather than trusting a comment or evidence-doc claim that no raw
    ``NOW()`` remains."""

    def __init__(self, cursor: Any, sink: list[str]) -> None:
        self._cursor = cursor
        self._sink = sink

    def execute(self, query: Any, vars: Any = None) -> Any:  # noqa: A002
        self._sink.append(query if isinstance(query, str) else str(query))
        return self._cursor.execute(query, vars)

    def __enter__(self) -> "_RecordingCursor":
        self._cursor.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self._cursor.__exit__(*exc)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._cursor, item)


class _RecordingConnection:
    def __init__(self, conn: Any, sink: list[str]) -> None:
        self._conn = conn
        self._sink = sink

    def cursor(self, *args: Any, **kwargs: Any) -> _RecordingCursor:
        return _RecordingCursor(self._conn.cursor(*args, **kwargs), self._sink)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._conn, item)


@pytest.fixture()
def market_pulse_sql(monkeypatch) -> list[str]:
    """Records every SQL statement ``market_pulse()`` issues through its
    module-level ``get_connection`` import (MUST-FIX-2, AX round-3 final
    re-review). ``analytics.py`` imports ``get_connection`` directly into
    its own module namespace (unlike ``board_sweep``'s lazy per-call
    import), so patching that module attribute — not ``app.db``'s — is what
    the router's global name lookup actually resolves at call time."""
    import app.routers.analytics as analytics_module

    real_get_connection = analytics_module.get_connection
    sink: list[str] = []

    @contextlib.contextmanager
    def _recording():
        with real_get_connection() as conn:
            yield _RecordingConnection(conn, sink)

    monkeypatch.setattr(analytics_module, "get_connection", _recording)
    return sink


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_funnel(user_id: str, jobs: int, statuses: list[str], days_ago: int = 0) -> None:
    """Insert ``jobs`` jobs and one application per status, in a single txn."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            job_ids = []
            for i in range(jobs):
                jid = new_id()
                job_ids.append(jid)
                cur.execute(
                    '''
                    INSERT INTO "Job" ("id", "userId", "title", "company",
                        "description", "source", "sourceUrl", "atsScore",
                        "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        NOW() - make_interval(days => %s), NOW())
                    ''',
                    (jid, user_id, f"Job {i}", "Acme", "desc", "seek",
                     f"https://example.com/{jid}", 40 + i * 7 % 60, days_ago),
                )
            cur.execute(
                '''
                INSERT INTO "Resume" ("id", "userId", "sections", "formatHash", "updatedAt")
                VALUES (%s, %s, '{}', 'seedhash', NOW()) RETURNING "id"
                ''',
                (new_id(), user_id),
            )
            resume_id = cur.fetchone()[0]
            for i, app_status in enumerate(statuses):
                cur.execute(
                    '''
                    INSERT INTO "Application" ("id", "userId", "jobId", "resumeId",
                        "status", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s::"ApplicationStatus",
                        NOW() - make_interval(days => %s), NOW())
                    ''',
                    (new_id(), user_id, job_ids[i % len(job_ids)], resume_id,
                     app_status, days_ago),
                )
        conn.commit()


# ---------------------------------------------------------------------------
# Market vs. You / Adzuna live-benchmark test helpers (market-perf swarm,
# 2026-08-13, PLAN.md rulings R1-R11). I1 (postings row) and I2 (FE) are
# already LIVE in this worktree. The additions below are for I3 (BE
# completion, REVISION 2): the third "Advertised salary (mean)" comparison
# row, ``salaryTrend12m``/``salaryHistogram`` summary enrichment, and removal
# of the transitional global ``marketVsYou.marketDataConnected`` boolean (R5)
# — none of which ``salary_intelligence_agent``/``analytics.py`` implement
# yet at the time these tests are written. Every helper below still degrades
# gracefully (``getattr``/``raising=False``) so collection and every
# pre-existing test in this file keep working while I3 is absent.
# ---------------------------------------------------------------------------

_HONEST_NO_MARKET_SUMMARY = "No market data source connected — showing your own figures only."
_INTERVIEW_RATE_FOOTNOTE = "No external interview-conversion benchmark provider currently exists."

#: I3 fixture — a realistic 12-month Adzuna ``/history`` month-map (AUD mean
#: advertised salary per month). Tests derive their expected substrings FROM
#: this map (min/max), never hardcoding a disconnected number (R11).
_HISTORY_FIXTURE = {
    "month": {
        "2026-07": 105811.99,
        "2026-06": 108200.10,
        "2026-05": 102344.50,
        "2026-04": 99850.00,
        "2026-03": 101200.25,
        "2026-02": 97400.00,
        "2026-01": 103900.75,
        "2025-12": 106500.00,
        "2025-11": 104750.60,
        "2025-10": 100320.40,
        "2025-09": 98230.15,
        "2025-08": 105675.42,
    }
}

#: I3 fixture — a realistic Adzuna ``/histogram`` band-count map. The
#: "140000" band (count 51) is deliberately the argmax so the top-band
#: sentence test can derive its expectation from the fixture itself.
_HISTOGRAM_FIXTURE = {
    "histogram": {
        "60000": 4,
        "80000": 16,
        "100000": 18,
        "120000": 10,
        "140000": 51,
    }
}


def _market_comparisons_by_label(pulse: dict) -> dict[str, dict]:
    """Index ``marketVsYou.comparisons`` by label for readable assertions."""
    return {c["label"]: c for c in pulse["marketVsYou"]["comparisons"]}


def _route_by_endpoint(*, search=None, history=None, histogram=None):
    """Build a ``fetch_json`` stub that dispatches by which real Adzuna
    endpoint ``fetch_market_benchmark`` calls (R11 / BRIEF-A: ``/search``,
    ``/history``, ``/histogram``). Each of ``search``/``history``/
    ``histogram`` is either a dict payload to return or an ``Exception``
    instance to raise for that endpoint — lets a single test independently
    control the three calls one benchmark fetch makes.
    """

    def _fetch(url, timeout=10):
        if "/histogram" in url:
            target = histogram
        elif "/history" in url:
            target = history
        else:
            target = search
        if isinstance(target, Exception):
            raise target
        return target

    return _fetch


def _seed_salary_job(
    user_id: str,
    *,
    salary_min: int | None = None,
    salary_max: int | None = None,
    currency: str | None = "AUD",
    title: str = "Business Analyst",
    source: str = "seek",
) -> str:
    """Insert one ``Job`` row carrying (or honestly omitting) a disclosed
    salary range, for :func:`user_disclosed_salary_median` (R3) tests —
    extends ``_seed_funnel``'s single-job-insert pattern with the salary
    columns it does not touch.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            jid = new_id()
            cur.execute(
                '''
                INSERT INTO "Job" ("id", "userId", "title", "company",
                    "description", "source", "sourceUrl", "salaryMin", "salaryMax",
                    "currency", "createdAt", "updatedAt")
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ''',
                (jid, user_id, title, "Acme", "desc", source,
                 f"https://example.com/{jid}", salary_min, salary_max, currency),
            )
        conn.commit()
    return jid


def _enable_live_adzuna(monkeypatch, fetch_fn, *, ttl_seconds: int | None = None):
    """Point the salary-intelligence agent's Adzuna fetch at ``fetch_fn``.

    Sets real-looking credentials, monkeypatches ``fetch_json`` — the
    module's imported reference, the established idiom this codebase's live
    discovery adapters use — and lifts the pytest-wide fixture-gate
    (``AETHER_DISCOVERY_FIXTURE_DIR``, R9) for this one test so the "live"
    code path is actually exercised deterministically, exactly the way
    ``test_fixture_mode_never_makes_live_calls.py``'s
    ``test_live_mode_is_untouched_when_fixture_mode_is_off`` does for the
    discovery adapters. No real network call is ever made — ``fetch_fn``
    fully replaces ``live_http.fetch_json`` for the duration of the test.
    """
    from app.agents import salary_intelligence_agent as sia

    monkeypatch.setenv("ADZUNA_APP_ID", "test-adzuna-app-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-adzuna-app-key")
    monkeypatch.delenv("AETHER_DISCOVERY_FIXTURE_DIR", raising=False)
    if ttl_seconds is not None:
        monkeypatch.setenv("AETHER_ADZUNA_BENCH_TTL_SECONDS", str(ttl_seconds))
    monkeypatch.setattr(sia, "fetch_json", fetch_fn, raising=False)
    return sia


def _assert_fresh_aware_iso8601(value: str, *, max_age_seconds: int = 21600) -> None:
    """R8: ``dataAsOf`` must be an ISO-8601 string with a UTC offset whose age
    (now - dataAsOf) is between 0 and the cache TTL — never in the future,
    never older than the cache is allowed to serve.
    """
    assert isinstance(value, str) and value, value
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, f"dataAsOf must be timezone-aware: {value!r}"
    age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    assert 0 <= age <= max_age_seconds, f"dataAsOf {value!r} is {age}s old (max {max_age_seconds}s)"


@pytest.fixture(autouse=True)
def _clear_market_benchmark_cache():
    """The Adzuna market-benchmark cache (R7, ``_BENCH_CACHE``) is a
    MODULE-LEVEL dict that outlives any single ``client``/app instance —
    without this, one test's cached fetch (keyed by role+location) could
    leak into a later test that happens to reuse the same key. No-op until
    the cache exists (feature absent pre-implementation).
    """
    from app.agents import salary_intelligence_agent as sia

    cache = getattr(sia, "_BENCH_CACHE", None)
    if cache is not None:
        cache.clear()
    yield
    cache = getattr(sia, "_BENCH_CACHE", None)
    if cache is not None:
        cache.clear()


class TestAnalytics:
    def test_funnel_aggregates_match_seeded_data(self, client, auth_headers, user_id):
        _seed_funnel(
            user_id,
            jobs=8,
            statuses=["submitted", "submitted", "screening", "interview", "offer", "draft"],
        )
        data = client.get("/analytics/funnel?period=all", headers=auth_headers).json()
        assert data["jobs_found"] == 8
        assert data["applied"] == 5      # everything except draft
        assert data["screened"] == 3     # screening + interview + offer
        assert data["interviewed"] == 2  # interview + offer
        assert data["offers"] == 1

    def test_time_period_filter_works(self, client, auth_headers, user_id):
        _seed_funnel(user_id, jobs=3, statuses=["submitted"], days_ago=0)
        _seed_funnel(user_id, jobs=2, statuses=["submitted"], days_ago=40)

        for period, expected_jobs in (("7d", 3), ("30d", 3), ("90d", 5), ("all", 5)):
            data = client.get(
                f"/analytics/funnel?period={period}", headers=auth_headers
            ).json()
            assert data["jobs_found"] == expected_jobs, period

        bad = client.get("/analytics/funnel?period=1y", headers=auth_headers)
        assert bad.status_code == 422

    def test_agent_roi_includes_cost_and_time(self, client, auth_headers):
        run = client.post(
            "/agents/scout/run",
            json={"query": "python", "location": "Sydney"},
            headers=auth_headers,
        )
        assert run.status_code == 202
        roi = client.get("/analytics/agent-roi", headers=auth_headers).json()
        assert roi["total_runs"] >= 1
        assert isinstance(roi["total_cost_usd"], float)
        assert roi["avg_duration_ms"] >= 0

    def test_ats_distribution_histogram(self, client, auth_headers, user_id):
        _seed_funnel(user_id, jobs=5, statuses=["draft"])
        dist = client.get("/analytics/ats-distribution", headers=auth_headers).json()
        assert len(dist["buckets"]) == 10
        assert dist["total"] == 5

    def test_probability_counts_measured_zero_conversion(self, client, auth_headers, user_id):
        """Market-pulse progress index must include a genuinely measured 0%
        interview conversion (applications exist, none interviewed) instead of
        silently dropping it — dropping inflated the headline score.

        Updated for F-04: the self-referential "Market demand" factor is gone,
        and a factor is now MEASURED iff its basis has rows (these jobs carry
        no fitScore, so "Skill match" is not measured and is excluded rather
        than counted as a zero). The assertion below therefore derives the
        expected mean from the wire's own `measured` flags — same guarantee,
        no hardcoded factor list to drift.
        """
        _seed_funnel(user_id, jobs=3, statuses=["submitted", "submitted", "submitted"])
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        factors = {f["label"]: f for f in pulse["probability"]["factors"]}
        # 3 applications, none interviewed → a REAL zero, not an absence.
        assert factors["Interview conversion"]["measured"] is True
        assert factors["Interview conversion"]["value"] == 0

        measured = [f["value"] for f in pulse["probability"]["factors"] if f["measured"]]
        assert 0 in measured, measured  # the measured zero is still in the mean
        assert pulse["probability"]["score"] == round(sum(measured) / len(measured))

    def _seed_source(self, user_id, source, title="Board role"):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "Job" ("id", "userId", "title", "company",
                        "description", "source", "sourceUrl", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ''',
                    (new_id(), user_id, title, "Acme",
                     "desc", source, f"https://example.com/{source}/{new_id()}"),
                )
            conn.commit()

    def test_source_donut_colors_are_unique(self, client, auth_headers, user_id):
        """No two NAMED donut segments may share a colour — differently
        labelled segments in one hue read as a single slice. R-VIZ assigns
        CHART_PALETTE by rank, so the reserved overflow tone #8C8A82 is the
        only colour a donut may repeat (see the overflow case below)."""
        _seed_funnel(user_id, jobs=3, statuses=["submitted"])  # 3 seek jobs
        self._seed_source(user_id, "customboard", title="Unmapped board role")
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        sources = pulse["sources"]
        labels = {s["label"].lower() for s in sources}
        assert {"seek", "customboard"} <= labels
        colors = [s["color"] for s in sources]
        assert len(colors) == len(set(colors)), f"duplicate donut colors: {colors}"
        # Rank order walks CHART_PALETTE from the top, never cycling.
        assert colors[0] == "#AE8E32"

    def test_source_donut_overflow_shares_only_the_reserved_other_tone(
        self, client, auth_headers, user_id
    ):
        """R-VIZ: top-4 hues + Other (#8C8A82), never a fifth hue. With more
        sources than palette steps, the first four are distinct and every
        overflow source collapses onto the ONE reserved neutral — it must
        never wrap back onto CHART_PALETTE[0]."""
        _seed_funnel(user_id, jobs=5, statuses=["submitted"])  # 5 seek jobs
        for extra, count in (
            ("linkedin", 4), ("indeed", 3), ("glassdoor", 2),
            ("customboard", 1), ("referral", 1),
        ):
            for _ in range(count):
                self._seed_source(user_id, extra)
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        colors = [s["color"] for s in pulse["sources"]]
        assert colors[:4] == ["#AE8E32", "#4F74B5", "#C16F7B", "#439FC8"], colors
        overflow = colors[4:]
        assert overflow, "expected at least one overflow slice"
        assert set(overflow) == {"#8C8A82"}, colors

    def test_conversion_rates(self, client, auth_headers, user_id):
        _seed_funnel(user_id, jobs=4, statuses=["submitted", "offer"])
        conv = client.get("/analytics/conversion", headers=auth_headers).json()
        assert conv["found_to_applied"] == 50.0  # 2 of 4

    def test_sources_donut_label_is_not_mislabeled_as_applications(
        self, client, auth_headers, user_id
    ):
        """GAP-P4-058: the donut's center number is a Job-source count
        (sourcesTotal), not an applications count — it must carry an honest
        label, never the static/misleading word 'applications'."""
        _seed_funnel(user_id, jobs=5, statuses=["submitted"])  # 5 jobs, 1 application
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        assert pulse["sourcesTotal"] == 5
        assert "sourcesLabel" in pulse
        assert pulse["sourcesLabel"] != "applications"
        assert "application" not in pulse["sourcesLabel"].lower()

    def test_avg_runs_per_week_divides_by_12_week_window(
        self, client, auth_headers, user_id
    ):
        """GAP-P4-059: all AgentRun rows land in a single calendar week, so
        weeks_active must not collapse to len(agent_series)==1 — the label
        says 'last 12 wks' so the divisor must be the fixed 12-week window."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                for _ in range(6):
                    cur.execute(
                        '''
                        INSERT INTO "AgentRun" ("id", "userId", "agentName", "status",
                            "costUsd", "startedAt", "completedAt", "createdAt")
                        VALUES (%s, %s, 'scout', 'completed', 0, NOW(), NOW(), NOW())
                        ''',
                        (new_id(), user_id),
                    )
            conn.commit()
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        rows = {r["label"]: r["delta"] for r in pulse["recruiterTrends"]["rows"]}
        assert rows["Agent runs (last 12 wks)"] == "6 total"
        # 6/12 = 0.5, not 6/1 = 6.0 (the divisor-collapse bug).
        assert rows["Avg runs / week"].startswith("0.5")
        assert len(pulse["recruiterTrends"]["series"]) == 12

    def test_market_vs_you_missing_credentials_reports_exact_prior_honest_state(
        self, client, auth_headers, monkeypatch
    ):
        """R10 (was ``test_market_vs_you_does_not_fabricate_market_benchmark``
        / GAP-P4-060, which locked the OLD single global-boolean contract that
        R5 removes). Absent Adzuna credentials must reproduce the EXACT prior
        honest state for EVERY row (market=None, connected=False,
        dataAsOf=None) and the exact prior summary string — and must make
        ZERO fetch attempts, proven by a fetch stub that fails the test
        outright if it is ever invoked.

        R5 (I3): the global ``marketVsYou.marketDataConnected`` boolean is
        REMOVED from the payload entirely — the key must be ABSENT, not
        merely ``False``, so a client can never mistake "flag not sent" for
        "flag says disconnected".
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        from app.agents import salary_intelligence_agent as sia

        def _must_not_be_called(url, timeout=10):
            raise AssertionError(
                "fetch_json must not be called when Adzuna credentials are absent (R10)"
            )

        monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
        monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
        monkeypatch.setattr(sia, "fetch_json", _must_not_be_called, raising=False)

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()

        mvy = pulse["marketVsYou"]
        assert "marketDataConnected" not in mvy, mvy
        for c in mvy["comparisons"]:
            assert c["market"] is None, c
            assert c["connected"] is False, c
            assert c["dataAsOf"] is None, c
        assert mvy["summary"] == _HONEST_NO_MARKET_SUMMARY

    def test_market_vs_you_live_success_reports_real_adzuna_postings(
        self, client, auth_headers, monkeypatch
    ):
        """I1: a real Adzuna ``/search`` response must flow through honestly
        — row 1's market side becomes the live 30-day posting count, its
        ``connected``/``dataAsOf``/``marketNote`` are populated, and the
        interview row NEVER gets a market number (R4, permanent).

        R5 (I3): there is no global ``marketVsYou.marketDataConnected``
        boolean any more — every consumer derives connectedness from the
        rows themselves, so the key must be ABSENT from the payload even
        while real data is flowing.
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        payload = {
            "count": 107,
            "mean": 147924.58,
            "results": [{"title": "Business Analyst", "id": "5664847200"}],
        }
        _enable_live_adzuna(monkeypatch, lambda url, timeout=10: payload)

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        mvy = pulse["marketVsYou"]
        comparisons = _market_comparisons_by_label(pulse)

        postings_row = comparisons["Applications / month"]
        assert postings_row["market"] == 107
        assert postings_row["connected"] is True
        _assert_fresh_aware_iso8601(postings_row["dataAsOf"])
        assert postings_row.get("marketNote"), "row1 must state what the market number is (R2)"

        # Interview-rate invariance (R4): never populated from Adzuna data,
        # even when the rest of the panel is genuinely connected.
        interview_row = comparisons["Interview rate"]
        assert interview_row["market"] is None
        assert interview_row["connected"] is False
        assert interview_row["footnote"] == _INTERVIEW_RATE_FOOTNOTE

        # R5: the transitional global flag is GONE for good in I3 — absent,
        # not False, regardless of how many rows are really connected.
        assert "marketDataConnected" not in mvy, mvy

        assert "Adzuna" in mvy["summary"]
        assert "107" in mvy["summary"]

    def test_market_vs_you_probability_market_evidence_flag_stays_decoupled(
        self, client, auth_headers, monkeypatch
    ):
        """R5: ``probability.marketDataConnected`` reports whether the
        PROBABILITY model has market evidence to reason from — a flat
        ``False`` — independently of whether Market vs. You's own Adzuna
        benchmark is really connected. I3 renames the backing server
        constant (``_MARKET_DATA_SOURCE_CONNECTED`` ->
        ``_PROBABILITY_USES_MARKET_EVIDENCE``); this test locks the
        BEHAVIOUR, not the identifier, so the rename cannot silently flip it.
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        payload = {"count": 107, "mean": 147924.58, "results": []}
        _enable_live_adzuna(monkeypatch, lambda url, timeout=10: payload)

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        postings_row = _market_comparisons_by_label(pulse)["Applications / month"]
        assert postings_row["connected"] is True, "benchmark must be genuinely live for this test"
        assert pulse["probability"]["marketDataConnected"] is False

    def test_market_vs_you_salary_row_reports_mean_market_and_disclosed_you_median(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """R3 (I3): the new "Advertised salary (mean)" row's market side is
        the live Adzuna ``/search`` ``mean`` (rounded to the nearest dollar,
        unit "A$"), and its ``you`` side is the MEDIAN of the caller's OWN
        disclosed salary bounds — preferring each job's disclosed max, and
        falling back to its min only when that job disclosed no max at all.
        Never imputed, never borrowed from the market side.
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        _seed_salary_job(user_id, salary_min=100000, salary_max=120000)  # -> 120000
        _seed_salary_job(user_id, salary_min=130000, salary_max=150000)  # -> 150000
        _seed_salary_job(user_id, salary_min=90000, salary_max=None)     # no max -> 90000

        payload = {"count": 107, "mean": 147924.58, "results": []}
        _enable_live_adzuna(monkeypatch, lambda url, timeout=10: payload)

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        salary_row = _market_comparisons_by_label(pulse)["Advertised salary (mean)"]

        assert salary_row["market"] == round(147924.58) == 147925
        assert salary_row["unit"] == "A$"
        assert salary_row["connected"] is True
        _assert_fresh_aware_iso8601(salary_row["dataAsOf"])

        # Per-row bound preference over [120000, 150000, 90000] -> median 120000.
        assert salary_row["you"] == 120000, salary_row

    def test_market_vs_you_salary_row_you_is_none_without_disclosed_salaries(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """R3 (I3): a caller with zero disclosed salary bounds gets an
        honest ``you: None`` on the salary row — never a fabricated or
        imputed figure — plus a footnote explaining why, even while the
        market side stays genuinely connected.
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        # A saved job exists but discloses no salary at all — must not read as 0.
        _seed_salary_job(user_id, salary_min=None, salary_max=None)

        payload = {"count": 107, "mean": 147924.58, "results": []}
        _enable_live_adzuna(monkeypatch, lambda url, timeout=10: payload)

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        salary_row = _market_comparisons_by_label(pulse)["Advertised salary (mean)"]

        assert salary_row["connected"] is True, "market side is still real even with no disclosures"
        assert salary_row["you"] is None, salary_row
        footnote = (salary_row.get("footnote") or "").lower()
        assert "disclosed salary" in footnote, salary_row
        assert "yet" in footnote, salary_row

    def test_market_vs_you_salary_row_you_never_merges_an_unverified_currency(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """Module rule 2 (never merge currencies), enforced on the ONE number
        this row prints beside an AUD market mean.

        A row counts only when its currency is POSITIVELY established as AUD.
        An explicit ``AUD`` establishes it. An EMPTY currency column
        establishes it only together with the row's source: the AU-only feeds
        (adzuna/seek) advertise nothing but AUD and write the column only
        alongside a disclosed minimum, so their max-only rows are real AUD
        disclosures — while an empty column on any other source is
        ``unspecified``, and assuming AUD there would average a foreign figure
        into the caller's own median.
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        _seed_salary_job(user_id, salary_min=100000, salary_max=100000)  # AUD -> 100000
        # AU feed, max only: currency column empty, but the ad was priced in AUD.
        _seed_salary_job(user_id, salary_min=None, salary_max=140000, currency=None)
        # Excluded: an explicitly foreign range.
        _seed_salary_job(
            user_id, salary_min=300000, salary_max=300000, currency="USD"
        )
        # Excluded: blank currency from a source that is not AU-only.
        _seed_salary_job(
            user_id, salary_min=None, salary_max=400000, currency=None, source="remotive"
        )

        payload = {"count": 107, "mean": 147924.58, "results": []}
        _enable_live_adzuna(monkeypatch, lambda url, timeout=10: payload)

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        salary_row = _market_comparisons_by_label(pulse)["Advertised salary (mean)"]

        # median([100000, 140000]) — either exclusion leaking in moves this.
        assert salary_row["you"] == 120000, salary_row

    def test_market_vs_you_salary_row_you_is_none_when_no_currency_is_verified(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """A caller whose only disclosures are in an unverified currency gets
        the honest ``None`` — never a figure built by assuming those rows were
        AUD because AUD is the surface's local currency.
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        _seed_salary_job(
            user_id, salary_min=300000, salary_max=300000, currency="USD"
        )
        _seed_salary_job(
            user_id, salary_min=None, salary_max=400000, currency=None, source="remotive"
        )

        payload = {"count": 107, "mean": 147924.58, "results": []}
        _enable_live_adzuna(monkeypatch, lambda url, timeout=10: payload)

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        salary_row = _market_comparisons_by_label(pulse)["Advertised salary (mean)"]

        assert salary_row["you"] is None, salary_row
        assert salary_row["connected"] is True, "market side is unaffected"

    def test_market_vs_you_live_failure_falls_back_to_honest_unavailable(
        self, client, auth_headers, monkeypatch, caplog
    ):
        """R11: an Adzuna ``/search`` failure must make the WHOLE benchmark
        unavailable (never a half-populated row), the summary must fall back
        to the EXACT pre-feature honest string, and the real error must be
        logged — never swallowed silently.
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )

        def _raise(url, timeout=10):
            raise RuntimeError("ADZUNA_TEST_INJECTED_FAILURE: HTTP 503 Service Unavailable")

        _enable_live_adzuna(monkeypatch, _raise)

        caplog.set_level(logging.WARNING)
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()

        mvy = pulse["marketVsYou"]
        assert "marketDataConnected" not in mvy, mvy
        comparisons = _market_comparisons_by_label(pulse)
        for label in ("Applications / month", "Interview rate", "Advertised salary (mean)"):
            row = comparisons[label]
            assert row["market"] is None, label
            assert row["connected"] is False, label

        assert mvy["summary"] == _HONEST_NO_MARKET_SUMMARY

        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "ADZUNA_TEST_INJECTED_FAILURE" in logged, logged

    def test_market_vs_you_data_as_of_is_fresh_tz_aware_iso8601(
        self, client, auth_headers, monkeypatch
    ):
        """R8: ``dataAsOf`` parses with ``datetime.fromisoformat``, carries
        timezone info, and its age is within the cache TTL (never in the
        future, never stale beyond what the cache may serve)."""
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        payload = {"count": 107, "mean": 147924.58, "results": []}
        _enable_live_adzuna(monkeypatch, lambda url, timeout=10: payload)

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        row = _market_comparisons_by_label(pulse)["Applications / month"]
        assert row["connected"] is True
        _assert_fresh_aware_iso8601(row["dataAsOf"])

    def test_market_vs_you_ttl_cache_never_serves_stale_after_failed_refetch(
        self, client, auth_headers, monkeypatch
    ):
        """R7: within the TTL, a second request must reuse the cached
        benchmark (no second fetch, identical ``dataAsOf``). Once the TTL
        elapses the entry is evicted and refetched. If THAT refetch fails,
        the row must go honestly unavailable — R7 explicitly forbids ever
        re-serving the old (now stale) cached numbers on a failed refetch.

        ``time.monotonic`` is patched as ``real_monotonic() + offset`` (never
        frozen, never non-monotonic) so the underlying async test-client
        machinery keeps working correctly while the TTL clock is fast-
        forwarded deterministically.
        """
        seed_search_target(client, auth_headers, target_role="Data Analyst", location="Perth")

        real_monotonic = time.monotonic
        fake_offset = {"delta": 0.0}
        monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + fake_offset["delta"])

        calls = {"n": 0}

        def _ok_fetch(url, timeout=10):
            # I3 adds a ``/history`` and ``/histogram`` call to every genuine
            # benchmark refresh alongside ``/search`` (R11, BRIEF-A) — count
            # only the ``/search`` hit so "calls['n']" keeps meaning "number
            # of real fetch CYCLES", the thing this test's TTL assertions are
            # actually about, regardless of how many endpoints one cycle hits.
            if "/search/" in url:
                calls["n"] += 1
                return {"count": 50 + calls["n"], "mean": 100000.0, "results": []}
            if "/history" in url:
                return {"month": {}}
            if "/histogram" in url:
                return {"histogram": {}}
            return {}

        sia = _enable_live_adzuna(monkeypatch, _ok_fetch, ttl_seconds=300)

        pulse1 = client.get("/analytics/market-pulse", headers=auth_headers).json()
        row1 = _market_comparisons_by_label(pulse1)["Applications / month"]
        assert row1["connected"] is True
        assert calls["n"] == 1
        first_market, first_data_as_of = row1["market"], row1["dataAsOf"]

        # Still within the 300s TTL: must reuse the cache, not refetch.
        fake_offset["delta"] += 60
        pulse2 = client.get("/analytics/market-pulse", headers=auth_headers).json()
        row2 = _market_comparisons_by_label(pulse2)["Applications / month"]
        assert calls["n"] == 1, "a call inside the TTL must not trigger a refetch"
        assert row2["market"] == first_market
        assert row2["dataAsOf"] == first_data_as_of, "cached rows keep the original fetch time (R8)"

        # Past the TTL: the entry is evicted and a real refetch happens.
        fake_offset["delta"] += 301
        pulse3 = client.get("/analytics/market-pulse", headers=auth_headers).json()
        row3 = _market_comparisons_by_label(pulse3)["Applications / month"]
        assert calls["n"] == 2, "an expired entry must be evicted and refetched"
        assert row3["market"] != first_market
        assert row3["dataAsOf"] != first_data_as_of

        # Expire again, but this time the refetch itself fails — must go
        # honestly unavailable, NEVER silently re-serve the stale numbers.
        fake_offset["delta"] += 301

        def _failing_fetch(url, timeout=10):
            calls["n"] += 1
            raise RuntimeError("ADZUNA_TEST_INJECTED_FAILURE: HTTP 500")

        monkeypatch.setattr(sia, "fetch_json", _failing_fetch, raising=False)
        pulse4 = client.get("/analytics/market-pulse", headers=auth_headers).json()
        row4 = _market_comparisons_by_label(pulse4)["Applications / month"]
        assert calls["n"] == 3
        assert row4["market"] is None, "a failed refetch must not re-serve stale numbers (R7)"
        assert row4["connected"] is False

    def test_market_vs_you_summary_enriches_with_real_12mo_trend_and_top_histogram_band(
        self, client, auth_headers, monkeypatch
    ):
        """I3 / R11: when the Adzuna ``/history`` and ``/histogram`` calls
        both succeed, the summary gains a 12-month salary-range sentence and
        a top-band sentence — both DERIVED from the real fixture data below,
        never a fabricated or hardcoded-disconnected number. Expected
        substrings are computed FROM the fixture (min/max, argmax band), so
        this test fails honestly if the real values ever stop appearing.
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        search_payload = {"count": 107, "mean": 147924.58, "results": []}
        fetch = _route_by_endpoint(
            search=search_payload, history=_HISTORY_FIXTURE, histogram=_HISTOGRAM_FIXTURE
        )
        _enable_live_adzuna(monkeypatch, fetch)

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        summary = pulse["marketVsYou"]["summary"]

        month_values = _HISTORY_FIXTURE["month"].values()
        expected_min = round(min(month_values))
        expected_max = round(max(month_values))
        bands = _HISTOGRAM_FIXTURE["histogram"]
        top_band_key = max(bands, key=lambda k: bands[k])
        top_band_count = bands[top_band_key]

        # Tolerate thousands-separator formatting ("97,400") without caring
        # which style the sentence uses — only the REAL digits are pinned.
        normalized = summary.replace(",", "")
        assert "all advertised roles" in summary, summary
        assert str(expected_min) in normalized, (expected_min, summary)
        assert str(expected_max) in normalized, (expected_max, summary)
        assert top_band_key in normalized, (top_band_key, summary)
        assert str(top_band_count) in normalized, (top_band_count, summary)

    def test_market_vs_you_history_and_histogram_failures_stay_partial_not_total(
        self, client, auth_headers, monkeypatch, caplog
    ):
        """R11 partial-failure honesty: a failing ``/history`` AND a failing
        ``/histogram`` call must NOT take down what the successful
        ``/search`` call already earned — the postings and salary rows stay
        genuinely connected, only the trend/band sentences drop out of the
        summary, and BOTH real errors are logged (never swallowed).
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        search_payload = {"count": 107, "mean": 147924.58, "results": []}
        history_error = RuntimeError("ADZUNA_TEST_INJECTED_HISTORY_FAILURE: HTTP 503")
        histogram_error = RuntimeError("ADZUNA_TEST_INJECTED_HISTOGRAM_FAILURE: HTTP 503")
        fetch = _route_by_endpoint(
            search=search_payload, history=history_error, histogram=histogram_error
        )
        _enable_live_adzuna(monkeypatch, fetch)

        caplog.set_level(logging.WARNING)
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        comparisons = _market_comparisons_by_label(pulse)

        assert comparisons["Applications / month"]["connected"] is True
        assert comparisons["Advertised salary (mean)"]["connected"] is True

        summary = pulse["marketVsYou"]["summary"]
        assert "Adzuna" in summary, summary
        assert "107" in summary, summary
        assert "all advertised roles" not in summary, "trend sentence must drop out, not fabricate"

        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "ADZUNA_TEST_INJECTED_HISTORY_FAILURE" in logged, logged
        assert "ADZUNA_TEST_INJECTED_HISTOGRAM_FAILURE" in logged, logged

    def test_applications_total_consistent_across_dashboard_funnel_market_pulse(
        self, client, auth_headers, user_id
    ):
        """Data-consistency ruling (MV-dashboard-001, MV-mobile-dashboard-
        005/006, MV-analytics-004/005/006, MV-application-tracker-002): the
        canonical "applications" total (every Application row, any status)
        must be identical everywhere it's shown unqualified, and every
        "submitted"-labelled figure (funnel "applied", Market Pulse
        "Applications / month") must count exactly the non-draft subset —
        never a fourth, divergent count.

        Before the fix, the dashboard-summary card counted ALL statuses, the
        funnel's "Applied" excluded drafts, and Market Pulse's rolling
        monthly figure ALSO counted all statuses within a 30-day window —
        so a monthly figure could exceed the all-time submitted total
        (MV-mobile-dashboard-005 observed "you 14" vs funnel "Applied 7").
        """
        # 3 drafts (never submitted) + 4 applications that left draft, all
        # created "now" so the last-30-days window captures every row.
        _seed_funnel(
            user_id,
            jobs=7,
            statuses=[
                "draft", "draft", "draft",
                "submitted", "screening", "interview", "offer",
            ],
        )
        total = 7
        submitted = 4  # everything except the 3 drafts

        dashboard = client.get("/analytics/dashboard", headers=auth_headers).json()
        assert dashboard["totalApplications"] == total

        funnel = client.get("/analytics/funnel?period=all", headers=auth_headers).json()
        assert funnel["applied"] == submitted

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        you_apps_month = next(
            c["you"]
            for c in pulse["marketVsYou"]["comparisons"]
            if c["label"] == "Applications / month"
        )
        # All seeded rows fall inside the 30-day window, so the monthly
        # submitted count must equal the all-time submitted count — and must
        # NOT silently include the 3 drafts (which would make it 7, not 4).
        assert you_apps_month == submitted
        assert you_apps_month == funnel["applied"]
        assert you_apps_month != total

    # -----------------------------------------------------------------
    # MON-batch-AX (2026-08-13 U-AX audit, MON-013..016) — failing tests
    # written BEFORE the fix. Each reproduces a live, evidenced defect in
    # uat/reports/evidence/market-perf/MONITORING-LEDGER.md.
    # -----------------------------------------------------------------

    def test_market_vs_you_summary_omits_band_sentence_when_histogram_all_zero(
        self, client, auth_headers, monkeypatch
    ):
        """MON-013: Adzuna's live ``/histogram`` can return every band at
        count 0 (verified live 2026-08-13,
        adzuna_histogram_raw_20260813T130212Z.json:
        {"20000":0,"80000":0,"100000":0,"60000":0,"140000":0,"40000":0,
        "120000":0}). ``_market_summary``'s ``if bands:`` truthy check still
        passes on a non-empty all-zero dict, so
        ``max(bands, key=lambda b: bands[b])`` picks an arbitrary tied band
        and prints the self-contradicting live sentence "Most live ads for
        your target role (0) advertise the A$80,000 band." Expected: when
        every band's count is 0, the band sentence must be omitted entirely
        (honest empty state) — the non-zero-histogram case (this file's
        ``test_market_vs_you_summary_enriches_with_real_12mo_trend_and_top_
        histogram_band``) must keep printing the sentence unchanged.
        """
        seed_search_target(
            client, auth_headers, target_role="Business Analyst", location="Melbourne"
        )
        search_payload = {"count": 107, "mean": 147924.58, "results": []}
        all_zero_histogram = {
            "histogram": {
                "20000": 0, "40000": 0, "60000": 0, "80000": 0,
                "100000": 0, "120000": 0, "140000": 0,
            }
        }
        fetch = _route_by_endpoint(search=search_payload, histogram=all_zero_histogram)
        _enable_live_adzuna(monkeypatch, fetch)

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        summary = pulse["marketVsYou"]["summary"]

        # The postings sentence (unaffected data) must still be present...
        assert "107" in summary, summary
        # ...but the self-contradicting "(0) advertise the ... band" clause
        # must be gone entirely when every band tied at zero.
        assert "advertise the" not in summary, summary
        assert "band" not in summary, summary

    def test_source_donut_percentages_normalize_to_sources_total_with_other_slice(
        self, client, auth_headers, user_id
    ):
        """MON-014: the Jobs-by-Source donut's percentages must be computed
        against ``sourcesTotal`` (the true ``COUNT(*)`` shown in the same
        chart's center text), not the top-5-source subtotal — normalizing to
        the truncated subtotal silently drops every long-tail source from
        the percentage math while still counting it in the displayed total
        (live audit: top-5=7,626 of sourcesTotal=7,801 -> the displayed
        Adzuna 77% was really 75.72% of sourcesTotal, and 175 long-tail jobs
        (2.24%) vanished from the math entirely). This fixture reproduces
        the same shape at small scale: top-5 counts [60,20,10,5,3] (=98) plus
        a 2-job long tail, sourcesTotal=100 -> the top-5 percentages must
        equal their own raw counts (60/20/10/5/3, not the top-5-subtotal-
        normalized 61/21/10/5/3) and an honest "Other" slice (~2%) must
        appear so the full donut (top-5 + Other) sums to 100.
        """
        counts = {
            "srca": 60, "srcb": 20, "srcc": 10, "srcd": 5, "srce": 3,
            "srcf": 1, "srcg": 1,
        }
        with get_connection() as conn:
            with conn.cursor() as cur:
                for source, n in counts.items():
                    for i in range(n):
                        jid = new_id()
                        cur.execute(
                            '''
                            INSERT INTO "Job" ("id", "userId", "title", "company",
                                "description", "source", "sourceUrl", "createdAt", "updatedAt")
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                            ''',
                            (jid, user_id, f"{source} job {i}", "Acme", "desc", source,
                             f"https://example.com/{jid}"),
                        )
            conn.commit()

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        assert pulse["sourcesTotal"] == 100

        by_label = {s["label"].lower(): s["value"] for s in pulse["sources"]}
        # These 5 must be normalized against sourcesTotal=100 — at this
        # fixture's round numbers, each source's own count IS its honest
        # percentage.
        assert by_label.get("srca") == 60, by_label
        assert by_label.get("srcb") == 20, by_label
        assert by_label.get("srcc") == 10, by_label
        assert by_label.get("srcd") == 5, by_label
        assert by_label.get("srce") == 3, by_label

        # The 2 long-tail sources (srcf, srcg = 2% of sourcesTotal) must not
        # vanish from the percentage math: an honest "Other" slice must
        # appear, and the whole donut (top-5 + Other) must sum to 100.
        assert "other" in by_label, pulse["sources"]
        assert by_label["other"] == 2, by_label
        assert sum(by_label.values()) == 100, by_label

    def test_activity_heatmap_buckets_by_australia_melbourne_not_utc(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """MON-015: the activity heatmap buckets ``Application`` rows by
        ``DATE("createdAt")`` in the DB's UTC-naive storage — a UTC calendar
        day — even though the page is explicitly AU/Melbourne-branded
        (MarketPulse.tsx caption "hiring & recruitment trends · AU").
        Melbourne is UTC+10 in August (no DST). Live audit evidence: 144 of
        512 (28%) of this user's applications created at UTC hour>=14 land
        on the WRONG Melbourne calendar day. This test pins the audit's own
        boundary example: an application created at 2026-08-12T15:30:00Z is
        UTC-day Aug 12 but Melbourne-day Aug 13 (15:30 + 10h = 01:30 next
        day). The "now" anchor is frozen well clear of the affected date so
        the grid position is unambiguous regardless of which anchor
        timezone the fix eventually uses.
        """
        import app.routers.analytics as analytics_module

        class _FixedNow(analytics_module.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)

        monkeypatch.setattr(analytics_module, "datetime", _FixedNow)

        with get_connection() as conn:
            with conn.cursor() as cur:
                jid = new_id()
                cur.execute(
                    '''
                    INSERT INTO "Job" ("id", "userId", "title", "company",
                        "description", "source", "sourceUrl", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ''',
                    (jid, user_id, "Boundary Job", "Acme", "desc", "seek",
                     f"https://example.com/{jid}"),
                )
                cur.execute(
                    '''
                    INSERT INTO "Resume" ("id", "userId", "sections", "formatHash", "updatedAt")
                    VALUES (%s, %s, '{}', 'seedhash', NOW()) RETURNING "id"
                    ''',
                    (new_id(), user_id),
                )
                resume_id = cur.fetchone()[0]
                cur.execute(
                    '''
                    INSERT INTO "Application" ("id", "userId", "jobId", "resumeId",
                        "status", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, 'submitted'::"ApplicationStatus",
                        '2026-08-12T15:30:00+00:00'::timestamptz, NOW())
                    ''',
                    (new_id(), user_id, jid, resume_id),
                )
            conn.commit()

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        heatmap = pulse["activityHeatmap"]
        flat = [cell for row in heatmap for cell in row]
        # Frozen "now" = 2026-08-20T12:00:00Z. Melbourne-day (Aug 13) is 7
        # days before that anchor -> flat index 27 (row 3, col 6). UTC-day
        # (Aug 12) is 8 days before -> flat index 26 (row 3, col 5). Only 1
        # application was seeded, so exactly one non-zero cell must exist.
        assert flat[27] == 4, (
            "the application must land on Melbourne-local Aug 13 "
            f"(flat index 27), got heatmap={heatmap}"
        )
        assert flat[26] == 0, (
            "the application must NOT be counted on UTC-day Aug 12 "
            f"(flat index 26), got heatmap={heatmap}"
        )
        assert sum(flat) == 4, f"exactly one seeded application, got heatmap={heatmap}"

    def test_activity_heatmap_buckets_by_aedt_not_a_fixed_utc10_offset(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """AX-REV-03: the sibling test above only pins an AEST (August,
        UTC+10) boundary and its own docstring states "Melbourne is UTC+10
        in August (no DST)" — so it would keep passing unchanged even if the
        implementation were later replaced with a fixed ``+10`` offset
        instead of a real ``Australia/Melbourne`` zone conversion. This test
        pins an AEDT (UTC+11, daylight-saving) boundary instead: an
        application created at 2026-10-15T13:30:00Z is, at the correct
        Australia/Melbourne offset, local 2026-10-16T00:30 (+11:00) —
        Melbourne-day Oct 16. A fixed +10 offset would compute
        2026-10-15T23:30 instead — still Oct 15, one day EARLIER — so this
        case genuinely distinguishes a real zone conversion from a
        hardcoded-offset stand-in (independently verified live via
        Postgres tzdata: 2026-10-15 13:30Z -> Melbourne 2026-10-16 AEDT+11).
        The heatmap's own SQL has no upper bound on ``createdAt`` — only a
        lower bound of ``>= %s::timestamptz - INTERVAL '35 days'`` bound to
        the single frozen ``now_utc`` anchor (R-02/R-05: derived from the
        ``analytics_module.datetime`` monkeypatched above), NOT Postgres's
        own wall-clock ``NOW()`` (MUST-FIX-3, AX round-3 final re-review —
        this sentence previously described the pre-R-02 raw-``NOW()``
        implementation, which R-02 already replaced; the conclusion below
        was still true, but for the wrong reason). Because the lower bound
        is pinned to the frozen anchor rather than the real wall clock, a
        same-year future date positioned relative to that anchor is a valid,
        deterministic fixture regardless of the real wall-clock date this
        suite runs on.
        """
        import app.routers.analytics as analytics_module

        class _FixedNow(analytics_module.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)

        monkeypatch.setattr(analytics_module, "datetime", _FixedNow)

        with get_connection() as conn:
            with conn.cursor() as cur:
                jid = new_id()
                cur.execute(
                    '''
                    INSERT INTO "Job" ("id", "userId", "title", "company",
                        "description", "source", "sourceUrl", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ''',
                    (jid, user_id, "AEDT Boundary Job", "Acme", "desc", "seek",
                     f"https://example.com/{jid}"),
                )
                cur.execute(
                    '''
                    INSERT INTO "Resume" ("id", "userId", "sections", "formatHash", "updatedAt")
                    VALUES (%s, %s, '{}', 'seedhash', NOW()) RETURNING "id"
                    ''',
                    (new_id(), user_id),
                )
                resume_id = cur.fetchone()[0]
                cur.execute(
                    '''
                    INSERT INTO "Application" ("id", "userId", "jobId", "resumeId",
                        "status", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, 'submitted'::"ApplicationStatus",
                        '2026-10-15T13:30:00+00:00'::timestamptz, NOW())
                    ''',
                    (new_id(), user_id, jid, resume_id),
                )
            conn.commit()

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        heatmap = pulse["activityHeatmap"]
        flat = [cell for row in heatmap for cell in row]
        # Frozen "now" = 2026-10-20T12:00:00Z -> Melbourne-local (AEDT+11)
        # 2026-10-20T23:00, so "today" = Oct 20. Correct Melbourne-day
        # (Oct 16) is 4 days before that anchor -> flat index 30. A fixed
        # +10 implementation would instead land the row on Oct 15 (5 days
        # before) -> flat index 29.
        assert flat[30] == 4, (
            "the application must land on the AEDT-correct Melbourne-local "
            f"Oct 16 (flat index 30), got heatmap={heatmap}"
        )
        assert flat[29] == 0, (
            "the application must NOT land on the fixed-+10 Oct 15 "
            f"(flat index 29), got heatmap={heatmap}"
        )
        assert sum(flat) == 4, f"exactly one seeded application, got heatmap={heatmap}"

    def test_market_pulse_declares_the_bucketing_timezone(self, client, auth_headers):
        """MON-015 (part 2): the heatmap/weekly-trend day-and-week
        boundaries are computed in some timezone, but the response discloses
        none today — a reader has no way to tell which calendar the
        boundaries use, on a page explicitly branded AU/Melbourne
        (MarketPulse.tsx captions "hiring & recruitment trends · AU" /
        "Weekly Activity"). Expect an explicit, honest timezone label on the
        wire once the buckets are fixed to Australia/Melbourne.
        """
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        assert pulse.get("timezone") == "Australia/Melbourne", pulse.get("timezone")

    def test_trend_indicator_delta_compares_last_vs_prior_period_not_first_vs_last(
        self, client, auth_headers, user_id
    ):
        """MON-016: ``_pct_delta()``'s own docstring says it compares "the
        first non-zero to last" point of the WHOLE lookback window, but the
        FE tooltip (MarketPulse.tsx:148) claims "percentage change vs. the
        prior period" — i.e. the LAST COMPLETE period vs the one immediately
        before it. Live prod evidence (2026-08-13 U-AX audit,
        api_market-pulse_20260813T130014Z.json) showed a SIGN REVERSAL:
        "Your application velocity" series [44,43,290,103] displayed
        "+134%"/"up" (first=44 vs last=103) while the true week-over-week
        change (290 -> 103) was -64.5%/down.

        AX-REV-01 (2026-08-13 re-audit of that fix): the LAST bucket of any
        weekly series is always the current, still-in-progress Melbourne
        week — never a complete period — so it must be EXCLUDED from the
        comparison, not treated as "the last period". This fixture seeds
        weekly distinct-jobId application counts [2, 2, 10, 1] at weeks_ago
        [3, 2, 1, 0]: the true last-COMPLETE-vs-prior-COMPLETE comparison is
        weeks_ago=1 (10) vs weeks_ago=2 (2) -> a +400% RISE. A comparison
        that (like the original MON-016 fix) still treats the in-progress
        current week (weeks_ago=0, count=1) as the "last period" would
        instead compute 10 -> 1, a spurious -90% DROP purely because the
        current week hasn't finished yet — the exact sign-flip AX-REV-01
        was opened for.
        """
        weeks_ago_counts = [(3, 2), (2, 2), (1, 10), (0, 1)]  # (weeks_ago, distinct jobs)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "Resume" ("id", "userId", "sections", "formatHash", "updatedAt")
                    VALUES (%s, %s, '{}', 'seedhash', NOW()) RETURNING "id"
                    ''',
                    (new_id(), user_id),
                )
                resume_id = cur.fetchone()[0]
                for weeks_ago, count in weeks_ago_counts:
                    for i in range(count):
                        jid = new_id()
                        cur.execute(
                            '''
                            INSERT INTO "Job" ("id", "userId", "title", "company",
                                "description", "source", "sourceUrl", "createdAt", "updatedAt")
                            VALUES (%s, %s, %s, %s, %s, %s, %s,
                                NOW() - make_interval(weeks => %s), NOW())
                            ''',
                            (jid, user_id, f"Job wk{weeks_ago}-{i}", "Acme", "desc", "seek",
                             f"https://example.com/{jid}", weeks_ago),
                        )
                        cur.execute(
                            '''
                            INSERT INTO "Application" ("id", "userId", "jobId", "resumeId",
                                "status", "createdAt", "updatedAt")
                            VALUES (%s, %s, %s, %s, 'submitted'::"ApplicationStatus",
                                NOW() - make_interval(weeks => %s), NOW())
                            ''',
                            (new_id(), user_id, jid, resume_id, weeks_ago),
                        )
            conn.commit()

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        indicators = {t["label"]: t for t in pulse["trendIndicators"]}
        velocity = indicators["Your application velocity"]
        # AX-REV-02: the series is zero-filled to the fixed 12-week grid
        # (oldest -> newest); the trailing entry (weeks_ago=0, "this week
        # so far") is real, honestly-reported data — it is just excluded
        # from the delta comparison below, not from the series itself.
        assert velocity["series"] == [0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 10, 1], velocity["series"]

        # True last-COMPLETE-vs-prior-COMPLETE (weeks_ago=1 vs weeks_ago=2):
        # 2 -> 10 is a RISE. Comparing weeks_ago=1 against the still-
        # in-progress weeks_ago=0 (10 -> 1) would instead show a spurious
        # -90% DROP — the exact sign-flip AX-REV-01 was opened for.
        assert velocity["direction"] == "up", velocity
        assert velocity["delta"] == "+400%", velocity["delta"]
        assert velocity["deltaKind"] == "percent", velocity

    def _seed_fit_scored_jobs(self, user_id: str, weeks_ago: int, scores: list[float]) -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for i, score in enumerate(scores):
                    jid = new_id()
                    cur.execute(
                        '''
                        INSERT INTO "Job" ("id", "userId", "title", "company",
                            "description", "source", "sourceUrl", "fitScore",
                            "createdAt", "updatedAt")
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                            NOW() - make_interval(weeks => %s), NOW())
                        ''',
                        (jid, user_id, f"Fit job wk{weeks_ago}-{i}", "Acme", "desc", "seek",
                         f"https://example.com/{jid}", score, weeks_ago),
                    )
            conn.commit()

    def test_avg_fit_score_series_preserves_null_gaps_not_fabricated_zero(
        self, client, auth_headers, user_id
    ):
        """R-01 (AX re-review round 2, RULING-B): the AVERAGE fit-score
        trend series must NOT zero-fill an unscored week — that fabricates
        "your average fit score was 0.00" for a week where nothing was ever
        measured, the exact honesty class MON-013 was opened for. Only
        weeks_ago=3 and weeks_ago=1 have any scored jobs; weeks_ago=2 (a gap
        in the MIDDLE) and weeks_ago=0 (the current, still-in-progress week)
        must both be ``null`` on the wire, never ``0``. The delta must skip
        the null gap at weeks_ago=2 and compare the two most recent COMPLETE
        weeks that actually have data (weeks_ago=1 vs weeks_ago=3), per
        RULING-B — not silently span the gap as if it were adjacent, and
        never treat the still-in-progress weeks_ago=0 as data.
        """
        self._seed_fit_scored_jobs(user_id, weeks_ago=3, scores=[40.0, 40.0])  # avg 40
        self._seed_fit_scored_jobs(user_id, weeks_ago=1, scores=[80.0, 80.0])  # avg 80

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        indicators = {t["label"]: t for t in pulse["trendIndicators"]}
        fit = indicators["Avg job fit score"]

        series = fit["series"]
        assert len(series) == 12, series
        # weeks_ago=0 -> index 11 (current, in-progress, unscored -> null).
        assert series[11] is None, series
        # weeks_ago=1 -> index 10 (scored, avg 80).
        assert series[10] == 80.0, series
        # weeks_ago=2 -> index 9 (unscored gap in the MIDDLE -> null, not 0).
        assert series[9] is None, series
        # weeks_ago=3 -> index 8 (scored, avg 40).
        assert series[8] == 40.0, series

        # Delta skips the null gap: 40 -> 80 is a genuine +100% rise, not a
        # fabricated 0-based or gap-spanning number.
        assert fit["deltaKind"] == "percent", fit
        assert fit["delta"] == "+100%", fit["delta"]
        assert fit["direction"] == "up", fit

    def test_avg_fit_score_delta_reports_insufficient_data_not_fabricated_percent(
        self, client, auth_headers, user_id
    ):
        """R-01 (AX re-review round 2, RULING-B/RULING-C): with only ONE
        complete week ever having scored jobs (and the still-in-progress
        current week excluded per RULING-A), there are not two complete
        weeks WITH data to compare — the delta must be the honest
        "insufficient-data" state, never a percentage computed against a
        fabricated 0 (the OLD zero-filled bug would have reported this as a
        spurious -100% "fell to zero").
        """
        self._seed_fit_scored_jobs(user_id, weeks_ago=5, scores=[55.0])

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        indicators = {t["label"]: t for t in pulse["trendIndicators"]}
        fit = indicators["Avg job fit score"]

        series = fit["series"]
        assert series.count(55.0) == 1, series
        # Every other week (including the current, in-progress one) is a
        # real absence — null, never a fabricated 0.
        assert all(v is None or v == 55.0 for v in series), series

        assert fit["deltaKind"] == "insufficient-data", fit
        assert fit["delta"] == "insufficient data", fit["delta"]
        assert fit["direction"] == "flat", fit
        assert "%" not in fit["delta"]

    def test_weekly_trend_delta_new_activity_from_zero_base_carries_new_kind(
        self, client, auth_headers, user_id
    ):
        """R-04/RULING-C: a genuine zero-base rise (last COMPLETE week has
        activity, the COMPLETE week before it has none) must carry
        ``deltaKind == "new"`` — never ``"percent"`` — so the FE can never
        route a fabricated-magnitude-free label through percent styling.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "Resume" ("id", "userId", "sections", "formatHash", "updatedAt")
                    VALUES (%s, %s, '{}', 'seedhash', NOW()) RETURNING "id"
                    ''',
                    (new_id(), user_id),
                )
                resume_id = cur.fetchone()[0]
                # weeks_ago=1 (the last COMPLETE week) has 3 distinct-job
                # applications; weeks_ago=2 (the one before it) has none.
                for i in range(3):
                    jid = new_id()
                    cur.execute(
                        '''
                        INSERT INTO "Job" ("id", "userId", "title", "company",
                            "description", "source", "sourceUrl", "createdAt", "updatedAt")
                        VALUES (%s, %s, %s, %s, %s, %s, %s,
                            NOW() - make_interval(weeks => 1), NOW())
                        ''',
                        (jid, user_id, f"New activity job {i}", "Acme", "desc", "seek",
                         f"https://example.com/{jid}"),
                    )
                    cur.execute(
                        '''
                        INSERT INTO "Application" ("id", "userId", "jobId", "resumeId",
                            "status", "createdAt", "updatedAt")
                        VALUES (%s, %s, %s, %s, 'submitted'::"ApplicationStatus",
                            NOW() - make_interval(weeks => 1), NOW())
                        ''',
                        (new_id(), user_id, jid, resume_id),
                    )
            conn.commit()

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        indicators = {t["label"]: t for t in pulse["trendIndicators"]}
        velocity = indicators["Your application velocity"]
        assert velocity["series"][-2] == 3, velocity["series"]
        assert velocity["series"][-3] == 0, velocity["series"]
        assert velocity["deltaKind"] == "new", velocity
        assert velocity["delta"] == "new activity", velocity["delta"]
        assert velocity["direction"] == "up", velocity

    def test_weekly_bucket_dst_spring_forward_flips_week_via_real_endpoint(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """R-02 (AX re-review round 2): the prior DST-transition test never
        called ``client.get`` at all — it opened a raw DB connection and
        asserted on Postgres tzdata directly, so it would still pass
        unchanged even if the router's own bucketing were rewritten to a
        hardcoded ``+10`` offset (exactly the failure mode AX-REV-03 was
        opened to forbid). This version seeds a REAL ``AgentRun`` row at the
        exact 2026 Australia/Melbourne spring-forward instant (AEST 02:00 ->
        AEDT 03:00 on 2026-10-04, independently verified live via Postgres
        tzdata) and asserts on ``pulse["recruiterTrends"]["series"]`` from a
        real ``client.get`` call through the router.

        RULING-D: the Python clock and the SQL time filter are anchored to
        the SAME frozen instant — this router now derives every ``NOW()``-
        equivalent SQL parameter from the module's ``datetime.now(UTC)``
        (see analytics.py's ``now_utc``, R-02/R-05 fix), so freezing
        ``analytics_module.datetime`` here pins BOTH sides consistently
        instead of leaving the SQL-side window keyed to the real wall clock.

        2026-10-11T13:30:00Z is, at the correct AEDT (+11) offset, Melbourne
        local 2026-10-12T00:30 — the first minute of the week starting
        Monday 2026-10-12. A fixed +10 offset would instead compute
        2026-10-11T23:30 (still Sunday) -> the week starting Monday
        2026-10-05, ONE WEEK EARLIER. With "now" frozen at
        2026-10-20T12:00:00Z (independently verified live: the 12-week grid
        anchored there runs 2026-08-03 .. 2026-10-19), the correct bucket is
        grid index 10 (2026-10-12) and the fixed-+10 bucket would instead be
        index 9 (2026-10-05) — the two implementations disagree about which
        index gets the count, so this genuinely distinguishes a real
        DST-aware zone conversion from a hardcoded-offset stand-in.
        """
        import app.routers.analytics as analytics_module

        class _FixedNow(analytics_module.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)

        monkeypatch.setattr(analytics_module, "datetime", _FixedNow)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "AgentRun" ("id", "userId", "agentName", "status",
                        "costUsd", "startedAt", "completedAt", "createdAt")
                    VALUES (%s, %s, 'scout', 'completed', 0,
                        '2026-10-11T13:30:00+00:00'::timestamptz, NOW(), NOW())
                    ''',
                    (new_id(), user_id),
                )
            conn.commit()

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        series = pulse["recruiterTrends"]["series"]
        assert len(series) == 12, series
        assert series[10] == 1, (
            "the AgentRun must land on the DST-correct Melbourne week "
            f"starting 2026-10-12 (grid index 10), got series={series}"
        )
        assert series[9] == 0, (
            "the AgentRun must NOT land on the fixed-+10 week starting "
            f"2026-10-05 (grid index 9), got series={series}"
        )
        assert series[11] == 0, f"the current in-progress week must stay 0, got series={series}"
        assert sum(series) == 1, f"exactly one seeded AgentRun, got series={series}"

    def test_recruiter_trends_rows_carry_delta_kind_and_direction(
        self, client, auth_headers, user_id
    ):
        """MUST-FIX-1 (AX round-3 final re-review, RULING-A/C extended to
        this sibling card): ``recruiterTrends.rows`` previously carried only
        ``label``/``delta`` — the FE painted every row's delta unconditionally
        green regardless of sign or kind. Both rows must now expose the SAME
        deltaKind/direction contract trendIndicators already carries, so the
        FE can branch honestly instead of hardcoding a color.

        Seeds 2 AgentRun rows two COMPLETE weeks ago and 6 one COMPLETE week
        ago (the current, in-progress week stays empty) -> the real
        last-COMPLETE-vs-prior-COMPLETE comparison is 2 -> 6, a genuine
        +200% rise, which the wire rows must expose structurally, not only
        bake into a pre-formatted string. The "Agent runs (last 12 wks)" row
        is a plain cumulative total, not a comparison at all — it must carry
        the neutral "total" kind, never "percent".
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                for _ in range(2):
                    cur.execute(
                        '''
                        INSERT INTO "AgentRun" ("id", "userId", "agentName", "status",
                            "costUsd", "startedAt", "completedAt", "createdAt")
                        VALUES (%s, %s, 'scout', 'completed', 0,
                            NOW() - make_interval(weeks => 2), NOW(), NOW())
                        ''',
                        (new_id(), user_id),
                    )
                for _ in range(6):
                    cur.execute(
                        '''
                        INSERT INTO "AgentRun" ("id", "userId", "agentName", "status",
                            "costUsd", "startedAt", "completedAt", "createdAt")
                        VALUES (%s, %s, 'scout', 'completed', 0,
                            NOW() - make_interval(weeks => 1), NOW(), NOW())
                        ''',
                        (new_id(), user_id),
                    )
            conn.commit()

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        rows = {r["label"]: r for r in pulse["recruiterTrends"]["rows"]}

        total_row = rows["Agent runs (last 12 wks)"]
        assert total_row["deltaKind"] == "total", total_row
        assert total_row["direction"] == "flat", total_row

        avg_row = rows["Avg runs / week"]
        assert avg_row["deltaKind"] == "percent", avg_row
        assert avg_row["direction"] == "up", avg_row
        assert avg_row["delta"].endswith("+200%"), avg_row

    def test_market_pulse_sql_never_calls_postgres_now_directly(
        self, client, auth_headers, market_pulse_sql
    ):
        """MUST-FIX-2 (AX round-3 final re-review): every day/week boundary
        market_pulse() computes must derive from the single frozen
        ``now_utc`` Python anchor, bound via ``%s::timestamptz`` — never
        Postgres's own ``NOW()``. This closes the residual instance the
        prior round's evidence claimed fixed but was not: the
        ``get_application_counts()`` call behind "Applications / month"
        still issued a raw ``NOW() - INTERVAL '30 days'`` literal, a SECOND
        independent clock a frozen-clock test could not pin. Asserts on the
        ACTUAL recorded SQL text of a real request, not on a code comment.
        """
        resp = client.get("/analytics/market-pulse", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert market_pulse_sql, "no SQL was recorded — fixture not wired to the router's connection"
        offenders = [stmt for stmt in market_pulse_sql if "NOW()" in stmt.upper()]
        assert offenders == [], f"raw NOW() found in market_pulse SQL: {offenders}"
