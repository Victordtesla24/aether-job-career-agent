"""P2-S10 — Analytics endpoint tests (funnel, periods, agent ROI)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pytest
from conftest import seed_search_target

from app.db import get_connection, new_id


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

    def test_source_donut_colors_are_unique(self, client, auth_headers, user_id):
        """An unmapped source must not receive a fallback color already
        claimed by a mapped source (seek=#FF6B35 was duplicated at palette
        index 1, merging adjacent donut segments)."""
        _seed_funnel(user_id, jobs=3, statuses=["submitted"])  # 3 seek jobs
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "Job" ("id", "userId", "title", "company",
                        "description", "source", "sourceUrl", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ''',
                    (new_id(), user_id, "Unmapped board role", "Acme",
                     "desc", "customboard", "https://example.com/custom"),
                )
            conn.commit()
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        sources = pulse["sources"]
        labels = {s["label"].lower() for s in sources}
        assert {"seek", "customboard"} <= labels
        colors = [s["color"] for s in sources]
        assert len(colors) == len(set(colors)), f"duplicate donut colors: {colors}"

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
