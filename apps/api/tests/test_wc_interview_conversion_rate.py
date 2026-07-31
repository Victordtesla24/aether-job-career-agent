"""GOLD-MASTER-V2 §5.4 (gate G-C) — failing tests for ``interview_conversion_rate``
(§5.3.5): interviews booked / applications submitted, computed from real DB
data, exposed for the Analytics screen with a >=1:5 (20%) "green"/healthy
threshold.

CURRENT STATE (measured this run): ``GET /analytics/conversion``
(``apps/api/app/routers/analytics.py``) computes ``found_to_applied``,
``applied_to_screened``, ``screened_to_interview`` (denominator = screened,
NOT applied/submitted) and ``interview_to_offer`` — there is no
interviewed-over-submitted ratio anywhere on that endpoint. A DIFFERENT
"Interview conversion" figure already exists, buried inside ``GET
/analytics/market-pulse``'s probability factors (``interview_rate =
interviews / total_apps * 100``, around line 493 of that router) — but its
denominator, ``f_total``, is ``COUNT(*) FROM "Application"`` (every raw row,
drafts and duplicate cover-letter-version rows included), NOT the canonical
"submitted" count (``get_application_counts()``'s DISTINCT-jobId, non-draft
subset) that the SAME router's own docstring says every "applications" figure
on the platform must use (the data-consistency ruling cited at the top of
``get_application_counts``). Production evidence cited in this run's brief:
0 interviews / 72 submitted = 0.00%.

ASSUMED contract (test-author defines it; not yet implemented):
``GET /analytics/conversion`` gains two fields:

    "interview_conversion_rate": float    # interviews / submitted * 100
    "interview_conversion_healthy": bool  # rate >= 20.0  (>= 1:5)
"""
from __future__ import annotations

import pytest

from app.db import get_connection, new_id


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_application_rows(user_id: str, jobs_and_statuses: list[list[str]]) -> None:
    """Seed one Job per ``statuses`` list, with one Application row PER status
    in that list, all on the SAME job (simulating multiple tailored/cover-
    letter draft versions of one submitted application) — lets a test tell a
    correct DISTINCT-job "submitted" denominator apart from a naive raw-row
    ``COUNT(*)`` (the bug already reproduced live in market-pulse's own
    "Interview conversion" factor, see module docstring)."""
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


class TestInterviewConversionRate:
    def test_interview_conversion_rate_is_a_real_computation_not_a_placeholder(
        self, client, auth_headers, user_id
    ):
        # 5 jobs each submitted once, exactly 1 reaches interview -> 1/5 = 20%.
        _seed_application_rows(
            user_id,
            [
                ["interview"],
                ["submitted"],
                ["submitted"],
                ["submitted"],
                ["submitted"],
            ],
        )
        data = client.get("/analytics/conversion?period=all", headers=auth_headers).json()
        assert "interview_conversion_rate" in data, sorted(data.keys())
        assert data["interview_conversion_rate"] == pytest.approx(20.0)

    def test_interview_conversion_rate_denominator_is_distinct_submitted_jobs(
        self, client, auth_headers, user_id
    ):
        """A job with THREE Application rows (e.g. re-tailored/re-drafted
        cover-letter versions of the one submitted application) must count as
        ONE submitted application, not three — matching
        ``get_application_counts`` (the canonical, DISTINCT-jobId source
        every other "applications" figure on the platform uses). A naive
        ``COUNT(*) FROM "Application"`` denominator (the exact bug already
        reproduced live in market-pulse's "Interview conversion" factor)
        would silently misreport this rate."""
        _seed_application_rows(
            user_id,
            [
                ["submitted", "submitted", "interview"],  # 1 job, 3 rows, 1 interview
                ["submitted"],
                ["submitted"],
                ["submitted"],
                ["submitted"],
            ],
        )
        data = client.get("/analytics/conversion?period=all", headers=auth_headers).json()
        # 5 DISTINCT submitted jobs, 1 interviewed -> 20%, NOT 1/7 (raw rows) = 14.3%.
        assert data["interview_conversion_rate"] == pytest.approx(20.0), data

    def test_interview_conversion_rate_zero_when_no_interviews_yet(
        self, client, auth_headers, user_id
    ):
        """Matches the production floor cited in this run's brief: 0
        interviews / 72 submitted = 0.00% — a genuinely MEASURED zero, never
        dropped, hidden, or replaced with a placeholder."""
        _seed_application_rows(user_id, [["submitted"] for _ in range(6)])
        data = client.get("/analytics/conversion?period=all", headers=auth_headers).json()
        assert data["interview_conversion_rate"] == 0.0
        assert data["interview_conversion_healthy"] is False

    def test_interview_conversion_rate_green_threshold_is_one_in_five(
        self, client, auth_headers, user_id
    ):
        # Exactly the >=1:5 boundary (20%) must read healthy=True.
        _seed_application_rows(
            user_id,
            [["interview"]] + [["submitted"] for _ in range(4)],
        )
        data = client.get("/analytics/conversion?period=all", headers=auth_headers).json()
        assert data["interview_conversion_rate"] == pytest.approx(20.0)
        assert data["interview_conversion_healthy"] is True

        # One more submitted-only job drops the rate to 1/6 ~= 16.7%, below
        # the boundary -> must flip to unhealthy.
        _seed_application_rows(user_id, [["submitted"]])
        data2 = client.get("/analytics/conversion?period=all", headers=auth_headers).json()
        assert data2["interview_conversion_rate"] < 20.0
        assert data2["interview_conversion_healthy"] is False
