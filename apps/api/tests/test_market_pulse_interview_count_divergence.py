"""GOLD-MASTER-V2 §15 — GAP-market-pulse-interview-count-divergence.

``GET /analytics/market-pulse``'s "Interview conversion" probability factor
(``app/routers/analytics.py``, the ``market_pulse`` endpoint) computed its
``interviews`` / ``total_apps`` figures from a raw ``COUNT(*) FROM
"Application"`` query instead of the canonical ``get_application_counts()``
helper (DISTINCT ``jobId``) that every other cumulative "applications" figure
on the platform must derive from (see that function's own docstring —
data-consistency ruling MV-dashboard-001 et al., and its ``interviewed``
paragraph, which already flagged this exact market-pulse divergence as
"known ... out of scope" before this fix).

Because one job can carry many ``Application`` rows (draft/re-tailored
cover-letter versions building up to the one that is actually promoted —
live evidence this run: a real job had NINE letter-version rows), a raw
``COUNT(*)`` denominator/numerator inflates against the true, per-job
figure and disagrees with every other canonical count on the same
dashboard page (``apps/web/src/app/dashboard/analytics/page.tsx`` renders
both the canonical conversion rate AND ``<MarketPulse />`` together, so a
user can see two different interview figures side by side).

This test seeds a data set with exactly that shape (one job with two extra
'draft' letter-version rows plus the row that reached 'interview', alongside
four single-row 'submitted'-only jobs) and asserts Market Pulse's "Interview
conversion" factor agrees with the canonical, DISTINCT-jobId
``get_application_counts()`` computation for the same data — not the
inflated raw-row count.
"""
from __future__ import annotations

import pytest

from app.db import get_connection, new_id
from app.routers.analytics import get_application_counts

#: Mirrors ``app.db.APPLICATION_ACTIVE_STATUSES``. At most one Application
#: row per job may sit in one of these statuses (partial UNIQUE index
#: ``Application_user_job_active_key``) — non-final letter-version rows on
#: the same job must be 'draft'.
_ACTIVE_STATUSES = ("submitted", "screening", "interview", "offer")


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_application_rows(user_id: str, jobs_and_statuses: list[list[str]]) -> None:
    """Seed one Job per ``statuses`` list, with one Application row PER
    status in that list, all on the SAME job — simulating multiple
    draft/re-tailored cover-letter versions of one submitted application."""
    for statuses in jobs_and_statuses:
        active = [s for s in statuses if s in _ACTIVE_STATUSES]
        assert len(active) <= 1, (
            f"seed {statuses!r} puts {len(active)} active-status rows "
            f"({active!r}) on ONE job — violates the real "
            f"Application_user_job_active_key partial unique index."
        )
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
            for statuses in jobs_and_statuses:
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


class TestMarketPulseInterviewCountDivergence:
    def test_market_pulse_interview_conversion_matches_canonical_distinct_job_count(
        self, client, auth_headers, user_id
    ):
        # 1 job with 3 Application rows (2 draft letter-versions + the row
        # that reached 'interview') + 4 single-row 'submitted' jobs.
        # Distinct jobs = 5, interviewed jobs = 1 -> canonical rate = 20%.
        # Raw COUNT(*) rows = 7, raw interview rows = 1 -> buggy rate =
        # round(1/7*100) = 14% -- a DIFFERENT number for the SAME data set.
        _seed_application_rows(
            user_id,
            [
                ["draft", "draft", "interview"],
                ["submitted"],
                ["submitted"],
                ["submitted"],
                ["submitted"],
            ],
        )

        # Canonical figure: the SAME helper every other cumulative
        # "applications" surface on the platform derives from.
        with get_connection() as conn:
            with conn.cursor() as cur:
                counts = get_application_counts(cur, user_id)
        assert counts["total"] == 5, counts
        assert counts["interviewed"] == 1, counts
        canonical_interview_rate = round(counts["interviewed"] / counts["total"] * 100)
        assert canonical_interview_rate == 20, canonical_interview_rate

        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        factors = {f["label"]: f["value"] for f in pulse["probability"]["factors"]}

        # This is the assertion that fails before the fix: the raw COUNT(*)
        # query at analytics.py:362-372 computes round(1/7*100) == 14, not
        # the canonical round(1/5*100) == 20.
        assert factors["Interview conversion"] == canonical_interview_rate, (
            f"Market Pulse 'Interview conversion' factor "
            f"({factors['Interview conversion']}) diverges from the "
            f"canonical get_application_counts()-derived figure "
            f"({canonical_interview_rate}) for the SAME data set — raw "
            f"COUNT(*) inflates/deflates against jobs with multiple "
            f"Application (letter-version) rows."
        )

        # The "Market vs you" panel's "Interview rate" comparison reuses the
        # exact same interview_rate variable — must agree too.
        mvy_rate = next(
            c["you"]
            for c in pulse["marketVsYou"]["comparisons"]
            if c["label"] == "Interview rate"
        )
        assert mvy_rate == canonical_interview_rate, mvy_rate
