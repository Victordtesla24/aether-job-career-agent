"""GET /applications/timeline — ApplicationStatusEvent swimlanes for the tracker.

Contract (SESSION TL-VIZ):
  * 401 without auth.
  * User-scoped: another user's applications/events never appear.
  * One swimlane per job (RT-004 DISTINCT ON jobId), same identity as GET /applications.
  * Events for the displayed application id only, oldest-first (at, seq).
  * Backfill genesis rows (fromStatus null, source backfill:current-status) are
    returned as-is — never invented prior stages.
  * Empty account: items=[] and range.start/end = null (no fake "today" axis).
"""
from __future__ import annotations

import json
import uuid

import pytest


def _uid() -> str:
    return uuid.uuid4().hex


def _seed_application(
    conn,
    user_id: str,
    *,
    app_status: str = "draft",
    title: str = "Staff Engineer",
    company: str = "Stripe",
) -> tuple[str, str]:
    job_id, resume_id, app_id = _uid(), _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (
                job_id,
                user_id,
                title,
                company,
                "Build things.",
                "seek",
                f"https://example.com/job/{job_id}",
                91.0,
            ),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "test"}), "hash-test"),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",NOW(),NOW())',
            (app_id, user_id, job_id, resume_id, app_status),
        )
    conn.commit()
    return app_id, job_id


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


class TestApplicationsTimeline:
    def test_requires_auth(self, client):
        assert client.get("/applications/timeline").status_code == 401

    def test_empty_account_has_null_range(self, client, auth_headers):
        data = client.get("/applications/timeline", headers=auth_headers).json()
        assert data["items"] == []
        assert data["range"] == {"start": None, "end": None}

    def test_returns_events_oldest_first_with_application(
        self, client, auth_headers, user_id, db_session
    ):
        from app.repositories.application_status_event import (
            BACKFILL_SOURCE,
            ensure_application_status_event_table,
            record_status_event,
        )

        ensure_application_status_event_table()
        app_id, _ = _seed_application(
            db_session, user_id, app_status="submitted", title="Senior Product Owner"
        )
        record_status_event(app_id, "submitted", "screening", "test:move")
        record_status_event(app_id, "screening", "interview", "test:move")

        data = client.get("/applications/timeline", headers=auth_headers).json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["application"]["id"] == app_id
        assert item["application"]["jobTitle"] == "Senior Product Owner"
        assert item["application"]["company"] == "Stripe"

        events = item["events"]
        assert len(events) >= 2
        ats = [e["at"] for e in events]
        assert ats == sorted(ats)
        assert events[-1]["toStatus"] == "interview"
        assert events[-1]["fromStatus"] == "screening"

        assert data["range"]["start"] is not None
        assert data["range"]["end"] is not None
        assert data["range"]["start"] <= data["range"]["end"]

        for e in events:
            if e["source"] == BACKFILL_SOURCE:
                assert e["fromStatus"] is None

    def test_scoped_to_current_user(self, client, auth_headers, user_id, db_session):
        from app.repositories.application_status_event import (
            ensure_application_status_event_table,
            record_status_event,
        )
        from app.repositories.user import UserRepository

        ensure_application_status_event_table()
        email = f"tl-foreign-{_uid()[:10]}@example.com"
        reg = client.post(
            "/auth/register",
            json={"email": email, "password": "Sup3rSecret"},
        )
        assert reg.status_code == 201
        foreign_user = UserRepository().get_by_email(email)
        assert foreign_user is not None
        foreign_id = foreign_user["id"]

        mine, _ = _seed_application(db_session, user_id, app_status="submitted")
        foreign_app, _ = _seed_application(
            db_session, foreign_id, app_status="offer", company="ForeignCo"
        )
        record_status_event(mine, "submitted", "screening", "test:mine")
        record_status_event(foreign_app, None, "offer", "test:foreign")

        data = client.get("/applications/timeline", headers=auth_headers).json()
        ids = [i["application"]["id"] for i in data["items"]]
        assert mine in ids
        assert foreign_app not in ids
        companies = [i["application"]["company"] for i in data["items"]]
        assert "ForeignCo" not in companies

    def test_one_lane_per_job_despite_letter_versions(
        self, client, auth_headers, user_id, db_session
    ):
        """RT-004: multiple Application rows for one job → one timeline lane."""
        import app.db as db_module
        from app.db import get_connection
        from app.repositories.application_status_event import (
            ensure_application_status_event_table,
            record_status_event,
        )

        # Historical letter-version duplicates require the unique-active index
        # off for this seed (same pattern as test_rt_004_application_card_dedup).
        index_name = getattr(
            db_module, "APPLICATION_UNIQUE_ACTIVE_INDEX", "Application_user_job_active_key"
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP INDEX IF EXISTS "{index_name}"')
            conn.commit()
        if hasattr(db_module, "_application_unique_active_index_ready"):
            db_module._application_unique_active_index_ready = False

        ensure_application_status_event_table()
        app_a, job_id = _seed_application(db_session, user_id, app_status="draft")
        resume_id, app_b = _uid(), _uid()
        with db_session.cursor() as cur:
            cur.execute(
                'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
                '"updatedAt") VALUES (%s,%s,2,%s,%s,NOW())',
                (resume_id, user_id, json.dumps({"summary": "v2"}), "hash-v2"),
            )
            cur.execute(
                'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
                '"createdAt","updatedAt") '
                'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",NOW(),NOW())',
                (app_b, user_id, job_id, resume_id, "submitted"),
            )
        db_session.commit()
        record_status_event(app_b, "draft", "submitted", "test:submit")

        data = client.get("/applications/timeline", headers=auth_headers).json()
        assert len(data["items"]) == 1
        assert data["items"][0]["application"]["id"] == app_b
        assert data["items"][0]["application"]["status"] == "submitted"
        for e in data["items"][0]["events"]:
            assert e["applicationId"] == app_b
        assert app_a != app_b
