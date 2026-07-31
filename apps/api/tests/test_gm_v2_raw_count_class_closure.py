"""GOLD-MASTER-V2 §15 — raw-count-vs-canonical-job divergence CLASS closure.

Commit ``ad0b3a0`` fixed ONE instance (``market_pulse()``'s "Interview
conversion" probability factor). This file proves + locks the fix for the
remaining sites in ``app/routers/analytics.py`` that still counted raw
``Application`` ROWS instead of DISTINCT jobs, for the sites where a per-job
count is the correct semantics for what the number tells the user:

  1. ``funnel()`` — screened / interviewed / offers. A stage count of
     opportunities: a user has one application to a job, not N (a job's
     re-tailored/re-drafted letter-version rows are not N separate
     opportunities).
  2. ``market_pulse()``'s ``app_week_rows`` -> "Your application velocity"
     trend indicator. The label narrows to "applications" — the SAME
     "applications pace" concept as the already-canonical "Applications /
     month" comparison computed via ``get_application_counts()`` elsewhere
     on the SAME ``market-pulse`` response; a job's draft churn must not
     inflate one "applications" figure on the page while the other, right
     next to it, stays honest.
  3. ``_dashboard()`` — interviews / offers. The SAME dashboard-summary card
     whose ``totalApplications`` figure is ALREADY canonical
     (``get_application_counts()["total"]``) — "interviews" and "offers" on
     that SAME card must not silently diverge from it by counting raw rows.

``market_pulse()``'s "Weekly Activity" heatmap (per-day ``COUNT(*)``) and its
"Application volume" probability factor denominator are deliberately LEFT
AS-IS — see ``uat/reports/evidence/gold-master-v2/waves/raw-count-class-
closure.md`` for the per-site justification (the heatmap reports raw
system-activity intensity, not an "applications"/"opportunities" figure, so
per-ROW counting is the correct semantics there).

Multiplicity here is real, LIVE production data, not a hypothetical: per
``app.db.ensure_application_unique_active_index``'s docstring (2026-07-29
probe), 2 (userId, jobId) pairs in production ALREADY violate the
one-active-Application-per-job invariant (21 extra rows total) because the
partial unique index enforcing it is only ever added lazily and SKIPS
creation when violations already exist — so a real user's job can carry more
than one row with an "active" (submitted/screening/interview/offer) status
today, not just multiple 'draft' letter-version rows. These tests seed that
exact shape.
"""
from __future__ import annotations

import pytest

from app.db import get_connection, new_id


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


@pytest.fixture(autouse=True)
def _no_active_index_leak():
    """Mirrors ``tests/test_rt_004_application_card_dedup.py``'s fixture of
    the same name/purpose: this file deliberately seeds MULTIPLE
    active-status ``Application`` rows for a single job via raw SQL
    (modeling the real, live production duplication cited in the module
    docstring above), which the partial UNIQUE index
    ``Application_user_job_active_key`` would otherwise reject once it has
    been lazily created in this shared ``aether_test`` schema by an earlier
    test in the session. Drop it (test-schema only) before AND after every
    test in this file so the seed stays possible regardless of execution
    order, without touching the real check-then-act guard other suites
    exercise on their own terms.
    """
    import app.db as db_module

    _index_name = getattr(
        db_module, "APPLICATION_UNIQUE_ACTIVE_INDEX", "Application_user_job_active_key"
    )

    def _reset() -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP INDEX IF EXISTS "{_index_name}"')
            conn.commit()
        if hasattr(db_module, "_application_unique_active_index_ready"):
            db_module._application_unique_active_index_ready = False

    _reset()
    yield
    _reset()


def _seed_resume(user_id: str) -> str:
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
        conn.commit()
    return resume_id


def _seed_job_with_rows(user_id: str, resume_id: str, statuses: list[str]) -> str:
    """Insert one Job, plus one Application row per entry in ``statuses``,
    ALL on that same job — the real letter-version-history shape (multiple
    draft/re-tailored rows, or — per the live production evidence cited
    above — multiple simultaneous "active"-status rows)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            jid = new_id()
            cur.execute(
                '''
                INSERT INTO "Job" ("id", "userId", "title", "company", "description",
                    "source", "sourceUrl", "createdAt", "updatedAt")
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ''',
                (jid, user_id, "Job", "Acme", "desc", "seek", f"https://example.com/{jid}"),
            )
            for st in statuses:
                cur.execute(
                    '''
                    INSERT INTO "Application" ("id", "userId", "jobId", "resumeId",
                        "status", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s::"ApplicationStatus", NOW(), NOW())
                    ''',
                    (new_id(), user_id, jid, resume_id, st),
                )
        conn.commit()
    return jid


class TestFunnelScreenedInterviewedOffersCountJobsNotRows:
    def test_funnel_screened_interviewed_offers_are_distinct_job_counts(
        self, client, auth_headers, user_id
    ):
        """One job with TWO 'offer'-status Application rows (the real, live
        production shape — see module docstring) must count as ONE screened,
        ONE interviewed and ONE offer opportunity — not two of each."""
        resume_id = _seed_resume(user_id)
        _seed_job_with_rows(user_id, resume_id, ["offer", "offer"])
        for _ in range(4):
            _seed_job_with_rows(user_id, resume_id, ["submitted"])

        data = client.get("/analytics/funnel?period=all", headers=auth_headers).json()
        assert data["jobs_found"] == 5, data
        assert data["applied"] == 5, data  # all 5 jobs are non-draft

        # Before the fix: COUNT(*) FILTER(...) at analytics.py:117-129 counts
        # BOTH 'offer' rows on the multi-row job -> screened=2, interviewed=2,
        # offers=2 (raw rows), not the 1 real opportunity they represent.
        assert data["screened"] == 1, data
        assert data["interviewed"] == 1, data
        assert data["offers"] == 1, data


class TestMarketPulseApplicationVelocityCountsJobsNotRows:
    def test_application_velocity_trend_counts_distinct_jobs_per_week(
        self, client, auth_headers, user_id
    ):
        """One job with THREE 'draft' letter-version rows created in the SAME
        week must contribute ONE to that week's "Your application velocity"
        point, not three — the SAME "applications pace" concept as the
        already-canonical "Applications / month" figure on this SAME
        market-pulse response (``get_application_counts()``-derived), which a
        job's re-tailored draft churn must not inflate."""
        resume_id = _seed_resume(user_id)
        _seed_job_with_rows(user_id, resume_id, ["draft", "draft", "draft"])
        for _ in range(4):
            _seed_job_with_rows(user_id, resume_id, ["submitted"])

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        velocity = next(
            t for t in pulse["trendIndicators"] if t["label"] == "Your application velocity"
        )
        # All 5 jobs' rows were created "now" -> a single populated week
        # bucket (app_week_rows is not zero-filled). Before the fix:
        # analytics.py:439-446's COUNT(*) counts all 3+4=7 rows in that
        # bucket. After: COUNT(DISTINCT "jobId") counts the 5 real jobs.
        assert velocity["series"][-1] == 5, velocity


class TestDashboardInterviewsOffersCountJobsNotRows:
    def test_dashboard_interviews_and_offers_are_distinct_job_counts(
        self, client, auth_headers, user_id
    ):
        """The SAME dashboard-summary card already shows a canonical,
        DISTINCT-jobId ``totalApplications`` figure — ``interviews`` and
        ``offers`` on that SAME card must not silently diverge from it by
        counting raw Application rows instead."""
        resume_id = _seed_resume(user_id)
        _seed_job_with_rows(user_id, resume_id, ["offer", "offer"])
        for _ in range(4):
            _seed_job_with_rows(user_id, resume_id, ["submitted"])

        data = client.get("/analytics/dashboard", headers=auth_headers).json()
        assert data["totalApplications"] == 5, data
        # Before the fix: analytics.py:665-678's raw COUNT(*) counts both
        # 'offer' rows on the multi-row job -> interviews=2, offers=2.
        assert data["interviews"] == 1, data
        assert data["offers"] == 1, data
