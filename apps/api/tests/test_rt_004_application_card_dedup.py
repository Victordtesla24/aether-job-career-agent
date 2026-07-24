"""RT-004 — one board card per job, however many letter versions exist.

Live evidence (2026-07-24): the Applications board showed ELEVEN cards for the
SAME Plenti job (9 Submitted, 1 In Review, 1 Ready). Every cover-letter
draft/refine inserts a new Application row (the studio's version history), the
board deduped per-job ONLY for status='draft', and each manual submit/move
promotion turned another letter-version into its own permanent duplicate card
— inflating the funnel/dashboard counts with it.

Contract locked here:
- GET /applications returns ONE ACTIVE card per job (most-advanced status
  wins: offer > interview > screening > submitted > draft; ties → newest);
- closed rows (rejected/withdrawn) are deduped per job too, and may coexist
  with an active re-application card;
- promoting a draft (submit or move) 409s when the job ALREADY has an active
  non-draft application — no new duplicate cards can ever be minted;
- funnel + canonical counts count DISTINCT JOBS, not letter-version rows.
"""
from __future__ import annotations

import json
import uuid

import pytest


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(conn, user_id: str) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,'Senior PM','Plenti','Own the roadmap.','lever',"
            "%s,'screening'::\"JobStatus\",88.0,NOW(),NOW())",
            (job_id, user_id, f"https://example.com/job/{job_id}"),
        )
    conn.commit()
    return job_id


def _add_app(
    conn, user_id: str, job_id: str, *, status: str, age_minutes: int = 0
) -> str:
    app_id, resume_id = _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "t"}), "h"),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"createdAt","updatedAt") VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",'
            "NOW() - make_interval(mins => %s), NOW())",
            (app_id, user_id, job_id, resume_id, status, age_minutes),
        )
    conn.commit()
    return app_id


def _cards_for_job(client, auth_headers, job_id: str) -> list[dict]:
    rows = client.get("/applications", headers=auth_headers).json()
    return [r for r in rows if r["jobId"] == job_id]


class TestOneActiveCardPerJob:
    def test_most_advanced_status_wins_over_recency(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        _add_app(db_session, user_id, job, status="submitted", age_minutes=1)
        older_screening = _add_app(
            db_session, user_id, job, status="screening", age_minutes=30
        )
        _add_app(db_session, user_id, job, status="submitted", age_minutes=5)
        cards = _cards_for_job(client, auth_headers, job)
        assert len(cards) == 1
        assert cards[0]["id"] == older_screening
        assert cards[0]["status"] == "screening"

    def test_draft_versions_still_collapse_to_newest(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        _add_app(db_session, user_id, job, status="draft", age_minutes=30)
        newest = _add_app(db_session, user_id, job, status="draft", age_minutes=1)
        cards = _cards_for_job(client, auth_headers, job)
        assert [c["id"] for c in cards] == [newest]

    def test_closed_and_active_cards_coexist_deduped(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        _add_app(db_session, user_id, job, status="rejected", age_minutes=60)
        newest_rejected = _add_app(
            db_session, user_id, job, status="rejected", age_minutes=10
        )
        active_draft = _add_app(db_session, user_id, job, status="draft", age_minutes=1)
        cards = _cards_for_job(client, auth_headers, job)
        assert {c["id"] for c in cards} == {newest_rejected, active_draft}


class TestPromotionGuards:
    def test_submit_conflicts_when_job_already_applied(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        _add_app(db_session, user_id, job, status="submitted", age_minutes=10)
        draft = _add_app(db_session, user_id, job, status="draft", age_minutes=1)
        resp = client.post(
            f"/applications/{draft}/submit", json={}, headers=auth_headers
        )
        assert resp.status_code == 409, resp.text
        # The draft is untouched — still the letter-version history.
        with db_session.cursor() as cur:
            cur.execute('SELECT "status" FROM "Application" WHERE "id" = %s', (draft,))
            assert cur.fetchone()[0] == "draft"

    def test_move_draft_conflicts_when_job_already_applied(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        _add_app(db_session, user_id, job, status="screening", age_minutes=10)
        draft = _add_app(db_session, user_id, job, status="draft", age_minutes=1)
        resp = client.post(
            f"/applications/{draft}/move",
            json={"to_stage": "submitted"},
            headers=auth_headers,
        )
        assert resp.status_code == 409, resp.text

    def test_moving_the_active_card_between_stages_still_works(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        active = _add_app(db_session, user_id, job, status="submitted", age_minutes=10)
        resp = client.post(
            f"/applications/{active}/move",
            json={"to_stage": "in-review"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "screening"

    def test_promoting_the_only_draft_still_works(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        draft = _add_app(db_session, user_id, job, status="draft", age_minutes=1)
        resp = client.post(
            f"/applications/{draft}/submit", json={}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "submitted"


class TestCountsCountJobsNotRows:
    def test_funnel_sankey_counts_distinct_jobs(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        for age in (50, 40, 30):
            _add_app(db_session, user_id, job, status="submitted", age_minutes=age)
        _add_app(db_session, user_id, job, status="screening", age_minutes=5)
        sankey = client.get("/applications/funnel/sankey", headers=auth_headers).json()
        stages = {s["key"]: s["value"] for s in sankey["stages"]}
        assert stages["applied"] == 1
        assert stages["screened"] == 1
        assert stages["interviewed"] == 0

    def test_canonical_counts_are_per_job(self, db_session, user_id):
        from app.db import get_connection
        from app.routers.analytics import get_application_counts

        job_a = _seed_job(db_session, user_id)
        job_b = _seed_job(db_session, user_id)
        for age in (40, 30):
            _add_app(db_session, user_id, job_a, status="submitted", age_minutes=age)
        _add_app(db_session, user_id, job_a, status="draft", age_minutes=5)
        _add_app(db_session, user_id, job_b, status="draft", age_minutes=5)
        with get_connection() as conn:
            with conn.cursor() as cur:
                counts = get_application_counts(cur, user_id)
        # job_a was actually sent (submitted); job_b only drafted.
        assert counts == {"total": 2, "submitted": 1}
