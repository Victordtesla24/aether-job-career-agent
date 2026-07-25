"""Tests for DELETE /jobs/clear-pipeline — full pipeline wipe with re-discovery.

Validates:
  (a) Clearing wipes all Job + Application rows for the user
  (b) Does NOT touch another user's rows
  (c) Missing/false ``confirm`` returns 422 and touches nothing
  (d) After clearing, re-inserting a job with the SAME sourceUrl succeeds
      (fresh row, not silently rejected as duplicate)
  (e) Audit row is written correctly (action ``pipeline.clear_all``)
"""
from __future__ import annotations

import json
import uuid

import pytest


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


def _seed_job(db_session, user_id: str, *, source_url: str | None = None) -> str:
    """Insert a job row directly and return its id."""
    job_id = _uid()
    url = source_url or f"https://example.com/job/{job_id}"
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,'Test Role','TestCorp','Desc','lever',%s,"
            "'discovered'::\"JobStatus\",80.0,NOW(),NOW())",
            (job_id, user_id, url),
        )
    db_session.commit()
    return job_id


def _seed_application(
    db_session,
    user_id: str,
    job_id: str,
    *,
    status: str = "submitted",
) -> str:
    """Insert an application row (with a minimal Resume) and return its id."""
    app_id = _uid()
    resume_id = _uid()
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "test"}), "h"),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"createdAt","updatedAt") VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",'
            "NOW(),NOW())",
            (app_id, user_id, job_id, resume_id, status),
        )
    db_session.commit()
    return app_id


def _register_user(client) -> dict[str, str]:
    """Register + login a second user; return auth headers."""
    email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    creds = {"email": email, "password": "Str0ngPass1"}
    r = client.post("/auth/register", json=creds)
    if r.status_code == 409:
        r = client.post("/auth/login", json=creds)
    else:
        assert r.status_code == 201, r.text
        r = client.post("/auth/login", json=creds)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestClearPipeline:
    """Clear-pipeline endpoint contract."""

    def test_confirm_false_returns_422_and_touches_nothing(
        self, client, auth_headers, test_user_id, db_session
    ):
        """Missing or false confirm must 422 and leave data untouched."""
        job_id = _seed_job(db_session, test_user_id)
        _seed_application(db_session, test_user_id, job_id)

        # confirm=false
        resp = client.request(
            "DELETE",
            "/jobs/clear-pipeline",
            json={"confirm": False},
            headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "confirm must be true" in resp.json()["detail"]

        # No confirm field at all
        resp = client.request(
            "DELETE",
            "/jobs/clear-pipeline",
            json={},
            headers=auth_headers,
        )
        # Pydantic defaults confirm to False, so 422
        assert resp.status_code == 422, resp.text

        # Verify data still exists
        resp2 = client.get("/jobs", headers=auth_headers)
        assert resp2.status_code == 200
        assert len(resp2.json()) >= 1, "Jobs should not have been deleted"

    def test_confirm_true_wipes_all_jobs_and_applications(
        self, client, auth_headers, test_user_id, db_session
    ):
        """Full wipe removes every Job + Application for the user."""
        job_a = _seed_job(db_session, test_user_id)
        job_b = _seed_job(db_session, test_user_id)
        _seed_application(db_session, test_user_id, job_a, status="submitted")
        _seed_application(db_session, test_user_id, job_a, status="draft")
        _seed_application(db_session, test_user_id, job_b, status="screening")

        resp = client.request(
            "DELETE",
            "/jobs/clear-pipeline",
            json={"confirm": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["jobsDeleted"] == 2
        assert body["applicationsDeleted"] == 3

        # Jobs list returns empty
        jobs = client.get("/jobs", headers=auth_headers).json()
        assert jobs == []

        # Applications list returns empty
        apps = client.get("/applications", headers=auth_headers).json()
        assert apps == []

    def test_does_not_touch_other_users_rows(
        self, client, auth_headers, test_user_id, db_session
    ):
        """Clearing user A must leave user B's pipeline intact."""
        # Seed for user A (the auth_headers user)
        job_a = _seed_job(db_session, test_user_id)
        _seed_application(db_session, test_user_id, job_a)

        # Register+login a second user B
        other_headers = _register_user(client)
        me = client.get("/auth/me", headers=other_headers)
        other_uid = me.json()["id"]

        # Seed for user B
        job_b = _seed_job(db_session, other_uid)
        _seed_application(db_session, other_uid, job_b)

        # Clear user A's pipeline
        resp = client.request(
            "DELETE",
            "/jobs/clear-pipeline",
            json={"confirm": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # User A's pipeline is empty
        assert client.get("/jobs", headers=auth_headers).json() == []

        # User B's pipeline is intact
        other_jobs = client.get("/jobs", headers=other_headers).json()
        assert len(other_jobs) == 1
        assert other_jobs[0]["id"] == job_b

    def test_reinsert_same_sourceurl_succeeds_after_clear(
        self, client, auth_headers, test_user_id, db_session
    ):
        """After clearing, inserting a job with the SAME sourceUrl succeeds
        as a fresh row — the unique constraint no longer matches because
        the original row was permanently deleted (no soft-delete/tombstone)."""
        shared_url = "https://example.com/shared-job/abc123"

        # Seed a job with this sourceUrl
        job_id = _seed_job(db_session, test_user_id, source_url=shared_url)
        _seed_application(db_session, test_user_id, job_id)

        # Clear everything
        resp = client.request(
            "DELETE",
            "/jobs/clear-pipeline",
            json={"confirm": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["jobsDeleted"] == 1

        # Verify pipeline is empty
        assert client.get("/jobs", headers=auth_headers).json() == []

        # Now insert a new job with the SAME sourceUrl. This simulates
        # a re-discovery run. It must succeed as a fresh insert, not be
        # silently rejected/upserted as a duplicate of the deleted row.
        new_job_id = _seed_job(db_session, test_user_id, source_url=shared_url)

        # Verify it appears fresh (new id)
        assert new_job_id != job_id, "Should be a fresh row with a new id"

        # Verify via API
        jobs = client.get("/jobs", headers=auth_headers).json()
        assert len(jobs) == 1
        assert jobs[0]["id"] == new_job_id
        assert jobs[0]["sourceUrl"] == shared_url

    def test_audit_row_written_correctly(
        self, client, auth_headers, test_user_id, db_session
    ):
        """After clearing, the AdminAuditLog has a pipeline.clear_all row."""
        job_a = _seed_job(db_session, test_user_id)
        job_b = _seed_job(db_session, test_user_id)
        _seed_application(db_session, test_user_id, job_a)
        _seed_application(db_session, test_user_id, job_b)

        resp = client.request(
            "DELETE",
            "/jobs/clear-pipeline",
            json={"confirm": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # Check the audit log
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "id","action","targetType","targetId","detailJson","actorUserId" '
                'FROM "AdminAuditLog" '
                'WHERE "action" = %s AND "actorUserId" = %s '
                "ORDER BY \"createdAt\" DESC LIMIT 1",
                ("pipeline.clear_all", test_user_id),
            )
            row = cur.fetchone()
            assert row is not None, "Audit row should exist"

            audit_id, action, target_type, target_id, detail_json, actor = row
            assert action == "pipeline.clear_all"
            assert target_type == "user"
            assert target_id == test_user_id
            assert actor == test_user_id

            detail = detail_json if isinstance(detail_json, dict) else json.loads(detail_json)
            assert detail["jobsDeleted"] == 2
            assert detail["applicationsDeleted"] == 2
