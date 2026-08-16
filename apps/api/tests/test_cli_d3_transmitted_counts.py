"""CLI-D3 (api half, audit wf_9a87f76f-eaa) — SUBMITTED MUST MEAN SENT.

Audit finding: analytics dashboards call 391 never-transmitted applications
"submitted/applied", while only rows carrying a real ``transmittedAt`` are
verified sends (CLI-QP already fixed ``quality_policy`` to the same rule).
This suite pins the ADDITIVE analytics contract:

* ``get_application_counts()`` additionally returns ``transmitted`` =
  ``COUNT(DISTINCT "jobId") FILTER (WHERE "transmittedAt" IS NOT NULL)``,
  under the same period clause as every existing key.
* Every payload that exposes a ``submitted``-derived figure through that
  helper — the funnel endpoint, the conversion endpoint, and market-pulse's
  "Applications / month" row — ALSO carries ``transmitted``.
* ``/analytics/conversion`` gains ``verified_interview_conversion_rate`` =
  rate(interviewed, transmitted) NEXT TO the legacy
  ``interview_conversion_rate`` (rate over left-draft "submitted"), which
  stays byte-identical for funnel continuity — the FE relabels it (Track D).

Honest semantics under test: ``submitted`` counts applications that left
draft — preparation; ``transmitted`` counts verified sends.

Seeding respects the real ``Application_user_job_active_key`` partial unique
index (at most ONE active-status row — submitted/screening/interview/offer —
per (user, job); drafts and terminal rejected/withdrawn rows are unlimited),
per WC-INTERVIEW-SEED-001.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db import get_connection, new_id

#: Mirrors ``app.db.APPLICATION_ACTIVE_STATUSES`` / the partial unique index.
_ACTIVE_STATUSES = ("submitted", "screening", "interview", "offer")


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_jobs(user_id: str, jobs: list[list[tuple[str, bool, int]]]) -> None:
    """One Job per entry; each entry is a list of Application row-specs
    ``(status, transmitted, days_ago)`` all attached to that SAME job — so a
    test can tell DISTINCT-job counting apart from raw row counting, for the
    ``transmitted`` key exactly as the RT-004 suites did for ``submitted``.

    ``transmitted=True`` stamps ``transmittedAt`` at the row's own
    ``createdAt`` instant (a verified send); ``False`` leaves it NULL — the
    audit's recorded-but-never-sent phantom. The Job's ``createdAt`` matches
    the OLDEST row so period-window tests move job and application together.
    """
    for rows in jobs:
        active = [s for s, _, _ in rows if s in _ACTIVE_STATUSES]
        assert len(active) <= 1, (
            f"seed {rows!r} puts {len(active)} active-status rows on one job — "
            f"violates Application_user_job_active_key (WC-INTERVIEW-SEED-001)"
        )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                INSERT INTO "Resume" ("id", "userId", "sections", "formatHash",
                    "createdAt", "updatedAt")
                VALUES (%s, %s, '[]'::jsonb, 'd3hash', NOW(), NOW()) RETURNING "id"
                ''',
                (new_id(), user_id),
            )
            resume_id = cur.fetchone()[0]
            for rows in jobs:
                jid = new_id()
                job_days_ago = max(days for _, _, days in rows)
                cur.execute(
                    '''
                    INSERT INTO "Job" ("id", "userId", "title", "company",
                        "description", "source", "sourceUrl", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s,
                        NOW() - make_interval(days => %s), NOW())
                    ''',
                    (jid, user_id, "D3 Job", "Acme", "desc", "seek",
                     f"https://example.com/{jid}", job_days_ago),
                )
                for status_val, transmitted, days_ago in rows:
                    cur.execute(
                        '''
                        INSERT INTO "Application" ("id", "userId", "jobId", "resumeId",
                            "status", "transmittedAt", "createdAt", "updatedAt")
                        VALUES (%s, %s, %s, %s, %s::"ApplicationStatus",
                            CASE WHEN %s THEN NOW() - make_interval(days => %s) END,
                            NOW() - make_interval(days => %s), NOW())
                        ''',
                        (new_id(), user_id, jid, resume_id, status_val,
                         transmitted, days_ago, days_ago),
                    )
        conn.commit()


class TestTransmittedCounts:
    def test_helper_gains_transmitted_and_keeps_legacy_keys_byte_identical(
        self, client, auth_headers, user_id
    ):
        """Unit seam: ``get_application_counts`` returns the new
        ``transmitted`` key (DISTINCT transmittedAt-bearing jobs) while
        ``total``/``submitted``/``interviewed`` keep their exact prior
        semantics — and the caller-supplied period clause (market-pulse's
        parameterized 30-day window) applies to ``transmitted`` identically.
        """
        from app.routers.analytics import get_application_counts

        _seed_jobs(
            user_id,
            [
                [("submitted", False, 0)],                # phantom, in window
                [("submitted", True, 0)],                 # verified send, in window
                [("submitted", True, 40)],                # verified send, 40d old
            ],
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                counts = get_application_counts(cur, user_id)
        # Legacy keys: byte-identical semantics (regression).
        assert counts["total"] == 3
        assert counts["submitted"] == 3
        assert counts["interviewed"] == 0
        # Additive key: only rows with a real transmittedAt.
        assert "transmitted" in counts, sorted(counts)
        assert counts["transmitted"] == 2

        now_utc = datetime.now(timezone.utc)
        with get_connection() as conn:
            with conn.cursor() as cur:
                windowed = get_application_counts(
                    cur,
                    user_id,
                    ' AND "createdAt" >= %s::timestamptz - INTERVAL \'30 days\'',
                    (now_utc,),
                )
        # The SAME period clause narrows transmitted and submitted alike.
        assert windowed["submitted"] == 2
        assert windowed["transmitted"] == 1

    def test_funnel_carries_transmitted_counting_only_verified_sends(
        self, client, auth_headers, user_id
    ):
        """The funnel payload gains ``transmitted`` — DISTINCT jobs with a
        real ``transmittedAt`` — while every existing field keeps its exact
        prior value (phantoms still count in ``applied``: funnel continuity).
        """
        _seed_jobs(
            user_id,
            [
                [("submitted", False, 0)],   # phantom "submitted" — never sent
                [("submitted", False, 0)],   # phantom "submitted" — never sent
                # One job, three rows: two draft letter-versions + the one
                # actually transmitted — must count ONCE everywhere (RT-004).
                [("draft", False, 0), ("draft", False, 0), ("submitted", True, 0)],
                # One job transmitted twice (sent, rejected, re-sent as a new
                # row) — still ONE transmitted job, not two.
                [("rejected", True, 0), ("interview", True, 0)],
            ],
        )
        data = client.get("/analytics/funnel?period=all", headers=auth_headers).json()
        assert "transmitted" in data, (
            f"funnel payload must carry the additive 'transmitted' count "
            f"(CLI-D3), got keys {sorted(data)}"
        )
        assert data["transmitted"] == 2  # the letter-version job + the re-sent job
        # Existing fields: byte-identical semantics (regression).
        assert data["jobs_found"] == 4
        assert data["applied"] == 4      # phantoms still count as left-draft
        assert data["screened"] == 1
        assert data["interviewed"] == 1
        assert data["offers"] == 0

    def test_funnel_transmitted_respects_the_same_period_clause(
        self, client, auth_headers, user_id
    ):
        _seed_jobs(
            user_id,
            [
                [("submitted", True, 40)],  # verified send, outside 30d window
                [("submitted", True, 0)],   # verified send, in window
            ],
        )
        month = client.get("/analytics/funnel?period=30d", headers=auth_headers).json()
        assert month["transmitted"] == 1
        assert month["applied"] == 1     # regression: window narrows both alike
        assert month["jobs_found"] == 1

        alltime = client.get("/analytics/funnel?period=all", headers=auth_headers).json()
        assert alltime["transmitted"] == 2
        assert alltime["applied"] == 2

    def test_conversion_gains_verified_rate_next_to_untouched_legacy_rate(
        self, client, auth_headers, user_id
    ):
        """5 left-draft jobs, 2 of them verifiably sent, 1 interviewed (a
        transmitted one): the legacy rate stays interviews/submitted = 20%
        byte-identical, and the NEW verified rate is interviews/transmitted
        = 50% — different numbers, so a swapped denominator cannot pass.
        """
        _seed_jobs(
            user_id,
            [
                [("interview", True, 0)],
                [("submitted", True, 0)],
                [("submitted", False, 0)],
                [("submitted", False, 0)],
                [("submitted", False, 0)],
            ],
        )
        data = client.get("/analytics/conversion?period=all", headers=auth_headers).json()
        assert "verified_interview_conversion_rate" in data, sorted(data)
        assert "transmitted" in data, sorted(data)
        assert data["transmitted"] == 2
        assert data["verified_interview_conversion_rate"] == pytest.approx(50.0)
        # Legacy fields: byte-identical semantics (regression).
        assert data["interview_conversion_rate"] == pytest.approx(20.0)
        assert data["interview_conversion_healthy"] is True
        assert data["found_to_applied"] == pytest.approx(100.0)

    def test_conversion_verified_rate_is_zero_when_nothing_ever_transmitted(
        self, client, auth_headers, user_id
    ):
        """The audit's exact live shape: every "submitted" row is a phantom
        (no ``transmittedAt`` anywhere). The legacy rate keeps reporting over
        preparation (20%) — unchanged, the FE relabels it — while the verified
        rate honestly reads 0.0 over a 0 verified denominator, never a copy of
        the legacy figure.
        """
        _seed_jobs(
            user_id,
            [
                [("interview", False, 0)],
                [("submitted", False, 0)],
                [("submitted", False, 0)],
                [("submitted", False, 0)],
                [("submitted", False, 0)],
            ],
        )
        data = client.get("/analytics/conversion?period=all", headers=auth_headers).json()
        assert data["transmitted"] == 0
        assert data["verified_interview_conversion_rate"] == 0.0
        # Legacy fields: byte-identical semantics (regression).
        assert data["interview_conversion_rate"] == pytest.approx(20.0)

    def test_market_pulse_applications_row_carries_transmitted_same_window(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """Market-pulse's "Applications / month" row (the one figure it
        derives from ``get_application_counts()["submitted"]``) also carries
        ``transmitted`` — verified sends inside the SAME rolling 30-day
        window — while ``you`` keeps counting left-draft preparation.
        """
        monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
        monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
        _seed_jobs(
            user_id,
            [
                [("submitted", False, 0)],  # phantom, in window
                [("submitted", False, 0)],  # phantom, in window
                [("submitted", True, 0)],   # verified send, in window
                [("submitted", True, 40)],  # verified send, OUTSIDE the window
            ],
        )
        pulse = client.get("/analytics/market-pulse", headers=auth_headers).json()
        row = next(
            c for c in pulse["marketVsYou"]["comparisons"]
            if c["label"] == "Applications / month"
        )
        assert "transmitted" in row, sorted(row)
        assert row["transmitted"] == 1  # only the in-window verified send
        # Regression: "you" stays the in-window left-draft count — 3, not 4
        # (window) and not 1 (never silently narrowed to transmitted).
        assert row["you"] == 3
