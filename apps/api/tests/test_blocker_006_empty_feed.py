"""BLOCKER-006 — a paying user's job feed is empty while 52 real jobs exist.

RED first (this commit). Production evidence, 2026-08-01 (read-only SELECT on
the ``aether`` schema):

    52 Job rows: 18 ``ready``, 30 ``applied``, 4 ``archived``
    every ``ready`` row's ``postedAt`` is 36-187 days old
    every ``ready`` row's ``updatedAt`` is < 60 seconds old (the 30-min
      discovery sweep re-confirmed all of them from the live board)
    GET /jobs -> []

The active feed's freshness predicate uses the POSTING DATE
(``active_feed._DATE_FIELDS = ("postedAt", "updatedAt", "createdAt")``,
consulted first-non-null) as a proxy for "this listing is dead". That proxy is
invalid for the ATS-native sources this product actually sources from:

* ``https://api.ashbyhq.com/posting-api/job-board/harvey`` returns 360
  CURRENTLY-OPEN postings whose ``publishedAt`` reaches back to 2025-09-12.
* ``https://api.lever.co/v0/postings/plenti`` returns, today, the exact
  posting whose persisted ``postedAt`` is 2026-06-26 (36 days old).

An ATS board API only publishes roles that are still open, so posting age
carries no information about whether the user can still apply. The honest
liveness signal is "was this listing still present at its source the last time
we looked", which the sourcing pipeline already establishes on every sweep.

These tests pin the corrected contract:
  1. an old-but-still-confirmed listing STAYS in the active feed;
  2. a recently-posted listing that has NOT been re-confirmed is SUPPRESSED
     (so this is a change of predicate, not a widened window);
  3. every feed row carries its real posting age so the UI can never present a
     187-day-old listing as if it were fresh, and never fabricates an age it
     does not have.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest


def _row(**over):
    """A minimal active-feed row; overridable field by field."""
    base = {
        "source": "ashby",
        "status": "ready",
        "company": f"Co{uuid.uuid4().hex[:6]}",
        "title": "Delivery Manager",
        "location": "Melbourne, VIC",
        "sourceUrl": f"https://ashby.example/{uuid.uuid4().hex[:8]}",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 1. The predicate itself — liveness, not posting age.
# ---------------------------------------------------------------------------
class TestListingLivenessPredicate:
    def test_old_posting_still_confirmed_live_is_not_stale(self):
        """The production case: posted 187d ago, re-confirmed 1 minute ago."""
        from app.services.discovery.active_feed import is_stale

        now = datetime(2026, 8, 1, 21, 30)
        job = _row(
            postedAt=now - timedelta(days=187),
            lastSeenAt=now - timedelta(minutes=1),
            updatedAt=now - timedelta(minutes=1),
            createdAt=now - timedelta(days=11),
        )
        assert is_stale(job, now=now) is False, (
            "a listing the sourcing sweep re-confirmed on its board a minute "
            "ago is live and applicable, however long ago it was first posted"
        )

    def test_listing_not_reconfirmed_since_window_is_stale(self):
        """Fresh posting date, but the board has not shown it for 60 days."""
        from app.services.discovery.active_feed import is_stale

        now = datetime(2026, 8, 1, 21, 30)
        job = _row(
            postedAt=now - timedelta(days=2),
            lastSeenAt=now - timedelta(days=60),
            updatedAt=now - timedelta(days=60),
            createdAt=now - timedelta(days=61),
        )
        assert is_stale(job, now=now) is True, (
            "a recent posting date must NOT keep a listing in the feed once "
            "the source has stopped returning it — that is the dead-link case "
            "the filter exists for"
        )

    def test_unknown_liveness_signal_is_never_stale(self):
        from app.services.discovery.active_feed import is_stale

        now = datetime(2026, 8, 1)
        job = _row(postedAt=None, lastSeenAt=None, updatedAt=None, createdAt=None)
        assert is_stale(job, now=now) is False

    def test_posting_age_alone_never_suppresses(self):
        """No posting date at all + confirmed live => in the feed."""
        from app.services.discovery.active_feed import is_stale

        now = datetime(2026, 8, 1)
        job = _row(postedAt=None, lastSeenAt=now - timedelta(hours=2))
        assert is_stale(job, now=now) is False


# ---------------------------------------------------------------------------
# 2. active_feed() — the blocker, plus the guards that must NOT regress.
# ---------------------------------------------------------------------------
class TestActiveFeedKeepsLiveListings:
    def test_live_old_ats_listings_are_returned(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 8, 1, 21, 30)
        rows = [
            _row(source="ashby", title="Staff Product Manager, Onboarding",
                 postedAt=now - timedelta(days=37),
                 lastSeenAt=now - timedelta(seconds=40)),
            _row(source="lever", title="Product Manager, Credit Automation",
                 postedAt=now - timedelta(days=36),
                 lastSeenAt=now - timedelta(seconds=44)),
            _row(source="ashby", title="GTM Technology Product Owner",
                 postedAt=now - timedelta(days=187),
                 lastSeenAt=now - timedelta(seconds=40)),
        ]
        feed = active_feed(rows, now=now)
        assert len(feed) == 3, (
            "all three are open roles their boards returned seconds ago — an "
            "empty feed here is the BLOCKER-006 production defect"
        )

    def test_unconfirmed_listing_is_still_suppressed(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 8, 1)
        rows = [
            _row(title="Live Role", postedAt=now - timedelta(days=90),
                 lastSeenAt=now - timedelta(minutes=5)),
            _row(title="Vanished Role", postedAt=now - timedelta(days=3),
                 lastSeenAt=now - timedelta(days=45)),
        ]
        feed = active_feed(rows, now=now)
        assert [j["title"] for j in feed] == ["Live Role"]

    def test_prohibited_source_still_excluded(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 8, 1)
        rows = [
            _row(source="seek", title="Program Manager",
                 lastSeenAt=now - timedelta(minutes=1)),
            _row(source="greenhouse", title="Delivery Manager",
                 lastSeenAt=now - timedelta(minutes=1)),
        ]
        feed = active_feed(rows, now=now)
        assert [j["source"] for j in feed] == ["greenhouse"]

    def test_fingerprint_dedupe_still_applies(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 8, 1)
        rows = [
            _row(source="greenhouse", company="Acme", title="Delivery Manager",
                 sourceUrl="https://gh/a", lastSeenAt=now - timedelta(minutes=1)),
            _row(source="lever", company="Acme", title="Delivery Manager",
                 sourceUrl="https://lever/a", lastSeenAt=now - timedelta(minutes=1)),
        ]
        feed = active_feed(rows, now=now)
        assert len(feed) == 1

    def test_terminal_statuses_still_excluded(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 8, 1)
        rows = [
            _row(status="applied", lastSeenAt=now - timedelta(minutes=1)),
            _row(status="archived", lastSeenAt=now - timedelta(minutes=1)),
            _row(status="ready", lastSeenAt=now - timedelta(minutes=1)),
        ]
        feed = active_feed(rows, now=now)
        assert [j["status"] for j in feed] == ["ready"]


# ---------------------------------------------------------------------------
# 3. Honest age — never present an old listing as fresh, never invent an age.
# ---------------------------------------------------------------------------
class TestHonestListingAge:
    def test_feed_rows_carry_real_posting_age(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 8, 1, 12, 0)
        rows = [_row(postedAt=now - timedelta(days=42, hours=3),
                     lastSeenAt=now - timedelta(minutes=2))]
        feed = active_feed(rows, now=now)
        assert feed[0]["postedAgeDays"] == 42, (
            "the UI must be able to say 'Posted 42 days ago' — hiding the age "
            "of a 42-day-old listing is the dishonest alternative to hiding "
            "the listing itself"
        )

    def test_unknown_posting_date_yields_null_age_not_a_guess(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 8, 1)
        rows = [_row(postedAt=None, createdAt=now - timedelta(days=11),
                     lastSeenAt=now - timedelta(minutes=2))]
        feed = active_feed(rows, now=now)
        assert feed[0]["postedAgeDays"] is None, (
            "an unknown posting date must stay unknown — never substituted "
            "with the discovery date, which is what the job card used to show"
        )

    def test_feed_rows_carry_last_confirmed_timestamp(self):
        from app.services.discovery.active_feed import active_feed

        now = datetime(2026, 8, 1, 12, 0)
        seen = now - timedelta(minutes=7)
        feed = active_feed([_row(postedAt=now - timedelta(days=90),
                                 lastSeenAt=seen)], now=now)
        assert feed[0]["lastConfirmedAt"] == seen


# ---------------------------------------------------------------------------
# 4. End-to-end at the router, against the real DB — the reported symptom.
# ---------------------------------------------------------------------------
class TestJobsEndpointBlocker006:
    def _insert(self, client, headers, *, title, source="ashby",
                posted_days_ago=None, last_seen_days_ago=0, company=None,
                status="ready"):
        from app.db import get_connection
        from app.repositories.job import JobRepository

        me = client.get("/auth/me", headers=headers).json()
        posted = (
            None if posted_days_ago is None
            else (datetime.utcnow() - timedelta(days=posted_days_ago)).isoformat()
        )
        row = JobRepository().create(me["id"], {
            "title": title,
            "company": company or f"Co{uuid.uuid4().hex[:6]}",
            "location": "Melbourne, VIC",
            "remote": False,
            "description": "Lead delivery across teams.",
            "requirements": [],
            "source": source,
            "sourceUrl": f"https://{source}.example/{uuid.uuid4().hex[:8]}",
            "postedAt": posted,
        })
        # Age the liveness signal without touching the posting date.
        if last_seen_days_ago:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        'UPDATE "Job" SET "lastSeenAt" = NOW() - (INTERVAL '
                        "'1 day' * %s), \"updatedAt\" = NOW() - (INTERVAL "
                        "'1 day' * %s) WHERE \"id\" = %s",
                        (last_seen_days_ago, last_seen_days_ago, row["id"]),
                    )
                conn.commit()
        if status != "ready":
            JobRepository().update_status(row["id"], status)
        return row

    def test_ready_jobs_with_old_posting_dates_are_returned(
        self, client, auth_headers
    ):
        """The exact production shape: every ready row posted 36-187d ago."""
        for days in (36, 37, 65, 120, 187):
            self._insert(client, auth_headers,
                         title=f"Product Manager {days}", posted_days_ago=days)

        feed = client.get("/jobs", headers=auth_headers)
        assert feed.status_code == 200
        rows = feed.json()
        assert len(rows) == 5, (
            f"BLOCKER-006: a paying user with 5 live, board-confirmed roles "
            f"saw {len(rows)} of them"
        )

    def test_feed_rows_expose_their_real_posting_age(self, client, auth_headers):
        self._insert(client, auth_headers, title="Aged Role", posted_days_ago=42)
        rows = client.get("/jobs", headers=auth_headers).json()
        assert len(rows) == 1
        assert rows[0]["postedAgeDays"] == 42

    def test_listing_the_source_stopped_returning_is_hidden_but_kept(
        self, client, auth_headers
    ):
        self._insert(client, auth_headers, title="Still Listed",
                     posted_days_ago=120)
        self._insert(client, auth_headers, title="Vanished",
                     posted_days_ago=3, last_seen_days_ago=45)

        default = {j["title"] for j in client.get(
            "/jobs", headers=auth_headers).json()}
        assert default == {"Still Listed"}

        full = {j["title"] for j in client.get(
            "/jobs?include_stale=true", headers=auth_headers).json()}
        assert {"Still Listed", "Vanished"} <= full, "history is never deleted"

    def test_camel_case_includeStale_is_accepted(self, client, auth_headers):
        """``?includeStale=true`` silently did nothing and cost a misdiagnosis.

        Every other field on this API is camelCase (``sourceUrl``,
        ``postedAt``, ``fitScore``), so a caller reaching for ``includeStale``
        got a 200 with a filtered body and no hint the flag was ignored.
        """
        self._insert(client, auth_headers, title="Vanished",
                     posted_days_ago=3, last_seen_days_ago=45)
        snake = client.get("/jobs?include_stale=true", headers=auth_headers)
        camel = client.get("/jobs?includeStale=true", headers=auth_headers)
        assert camel.status_code == 200
        assert {j["title"] for j in camel.json()} == {
            j["title"] for j in snake.json()
        }
        assert "Vanished" in {j["title"] for j in camel.json()}


# ---------------------------------------------------------------------------
# 5. The sourcing pipeline must record the liveness signal it already knows.
# ---------------------------------------------------------------------------
class TestSweepRecordsLiveness:
    def test_create_stamps_last_seen_at(self, client, auth_headers):
        from app.repositories.job import JobRepository

        me = client.get("/auth/me", headers=auth_headers).json()
        raw = {
            "title": "Business Analyst", "company": "Brighte",
            "location": "Sydney, NSW", "remote": False,
            "description": "Analyse.", "requirements": [], "source": "lever",
            "sourceUrl": f"https://lever.example/{uuid.uuid4().hex[:8]}",
            "postedAt": (datetime.utcnow() - timedelta(days=140)).isoformat(),
        }
        JobRepository().create(me["id"], raw)
        first = client.get("/jobs", headers=auth_headers).json()[0]
        assert first["lastSeenAt"] is not None

        # Re-sweeping the SAME sourceUrl must refresh the liveness stamp.
        from app.db import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "Job" SET "lastSeenAt" = NOW() - INTERVAL '
                    "'10 days' WHERE \"id\" = %s",
                    (first["id"],),
                )
            conn.commit()
        JobRepository().create(me["id"], raw)
        again = client.get("/jobs", headers=auth_headers).json()[0]
        assert again["postedAgeDays"] == 140, "posting date must NOT be bumped"
        stamped = again["lastSeenAt"]
        if isinstance(stamped, str):
            stamped = datetime.fromisoformat(stamped.replace("Z", "+00:00"))
        if stamped.tzinfo is not None:
            stamped = stamped.replace(tzinfo=None)
        assert stamped > datetime.utcnow() - timedelta(minutes=5), (
            "the re-sweep re-confirmed the listing is still on the board — "
            "that is the only signal that keeps it in the active feed"
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
