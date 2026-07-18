"""Interview scheduling router tests.

GAP-P4-040 regression — ``POST /interviews`` must never 500:
    ``application_id`` was once optional in the request schema while the
    ``InterviewSchedule.applicationId`` DB column is (and remains) NOT NULL.
    Omitting it crashed the INSERT with a NotNullViolation -> HTTP 500. It is
    now a required field, so a missing value is a clean 422.

MV-interview-center-004 — referential integrity on create:
    ``POST /interviews`` previously accepted *any* string as ``application_id``
    and created an orphaned row (201). An interview must now reference a real
    ``Application`` owned by the caller; a missing or foreign reference is a 404.
"""
from __future__ import annotations

import json
import uuid


def _uid() -> str:
    return uuid.uuid4().hex


def _seed_application(conn, user_id: str, *, app_status: str = "interview") -> str:
    """Insert Job + Resume + Application for ``user_id``; return the app id."""
    job_id, resume_id, app_id = _uid(), _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (job_id, user_id, "Staff Engineer", "Stripe", "Build things.", "seek",
             f"https://example.com/job/{job_id}", 91.0),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "test"}), "hash-test"),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"answers","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,NOW(),NOW())',
            (app_id, user_id, job_id, resume_id, app_status, None),
        )
    conn.commit()
    return app_id


def test_create_interview_without_application_id_returns_422_not_500(
    client, auth_headers
):
    """Omitting application_id must be a clean 422, never a 500 (GAP-P4-040)."""
    resp = client.post(
        "/interviews",
        json={
            "type": "video",
            "scheduled_at": "2026-08-01T15:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.status_code != 500


def test_create_interview_with_real_application_succeeds(
    client, auth_headers, db_session, test_user_id
):
    """The documented-good path works: a real owned application -> 201 persisted."""
    app_id = _seed_application(db_session, test_user_id)
    resp = client.post(
        "/interviews",
        json={
            "application_id": app_id,
            "type": "video",
            "scheduled_at": "2026-08-01T15:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["application_id"] == app_id
    assert body["status"] == "scheduled"

    # Round-trips into the list scoped to the user.
    listed = client.get("/interviews", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert any(row["id"] == body["id"] for row in listed.json())


def test_create_interview_with_nonexistent_application_returns_404(
    client, auth_headers
):
    """MV-interview-center-004: a bogus application_id must be rejected, not 201."""
    resp = client.post(
        "/interviews",
        json={
            "application_id": "does-not-exist-anywhere",
            "type": "video",
            "scheduled_at": "2026-08-01T15:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text
    assert resp.status_code != 201

    # And no orphan row leaked into the caller's list.
    listed = client.get("/interviews", headers=auth_headers)
    assert listed.json() == []


def test_create_interview_with_foreign_application_returns_404(
    client, auth_headers, db_session
):
    """An application owned by *another* user is not a valid reference (404)."""
    other = client.post(
        "/auth/register",
        json={"email": f"other-{_uid()[:8]}@example.com", "password": "Sup3rSecret"},
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]
    foreign_app = _seed_application(db_session, other_id)

    resp = client.post(
        "/interviews",
        json={
            "application_id": foreign_app,
            "type": "video",
            "scheduled_at": "2026-08-01T15:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text
