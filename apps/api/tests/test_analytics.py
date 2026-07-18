"""P2-S10 — Analytics endpoint tests (funnel, periods, agent ROI)."""
from __future__ import annotations

import pytest

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
        """Market-pulse probability must include a genuinely measured 0%
        interview conversion (applications exist, none interviewed) instead of
        silently dropping it — dropping inflated the headline score."""
        _seed_funnel(user_id, jobs=3, statuses=["submitted", "submitted", "submitted"])
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        factors = {f["label"]: f["value"] for f in pulse["probability"]["factors"]}
        assert factors["Interview conversion"] == 0
        measured = [
            factors["Application volume"],
            factors["Market demand"],
            factors["Interview conversion"],  # 3 applications → measured zero
        ]
        if factors["Skill match"]:
            measured.append(factors["Skill match"])
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

    def test_market_vs_you_does_not_fabricate_market_benchmark(
        self, client, auth_headers, user_id
    ):
        """GAP-P4-060: _MARKET_APPS_PER_MONTH / _MARKET_INTERVIEW_RATE were
        hardcoded constants presented as real market data with no actual
        external source — must honestly report the source is not connected."""
        _seed_funnel(user_id, jobs=3, statuses=["submitted"])
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        mvy = pulse["marketVsYou"]
        assert mvy["marketDataConnected"] is False
        for c in mvy["comparisons"]:
            assert c["market"] is None
        assert "no market data source connected" in mvy["summary"].lower()

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
