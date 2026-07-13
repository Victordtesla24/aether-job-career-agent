"""AGT-APPS — Application Tracker router tests (list/detail/submit/sankey)."""
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
    answers: dict | None = None,
    fit_score: float | None = 91.0,
) -> tuple[str, str]:
    """Insert Job + Resume + Application for ``user_id``; return (app_id, job_id)."""
    job_id, resume_id, app_id = _uid(), _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (job_id, user_id, "Staff Engineer", "Stripe", "Build things.", "seek",
             f"https://example.com/job/{job_id}", fit_score),
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
            (app_id, user_id, job_id, resume_id, app_status,
             json.dumps(answers) if answers is not None else None),
        )
    conn.commit()
    return app_id, job_id


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


class TestListApplications:
    def test_requires_auth(self, client):
        assert client.get("/applications").status_code == 401

    def test_returns_answers_and_fit_score(self, client, auth_headers, user_id, db_session):
        answers = {"interviewRound": 2, "interviewDate": "2026-07-03"}
        app_id, _ = _seed_application(
            db_session, user_id, app_status="interview", answers=answers, fit_score=92.0
        )
        rows = client.get("/applications", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == app_id)
        assert row["answers"] == answers
        assert row["fitScore"] == 92.0
        assert row["jobTitle"] == "Staff Engineer"
        assert row["company"] == "Stripe"

    def test_status_filter(self, client, auth_headers, user_id, db_session):
        _seed_application(db_session, user_id, app_status="draft")
        offer_id, _ = _seed_application(db_session, user_id, app_status="offer")
        rows = client.get(
            "/applications?app_status=offer", headers=auth_headers
        ).json()
        assert [r["id"] for r in rows] == [offer_id]

    def test_invalid_status_is_422_not_500(self, client, auth_headers):
        resp = client.get("/applications?app_status=bogus", headers=auth_headers)
        assert resp.status_code == 422
        assert "Invalid app_status" in resp.json()["detail"]

    def test_scoped_to_current_user(self, client, auth_headers, user_id, db_session):
        other = client.post(
            "/auth/register",
            json={"email": "other-user@example.com", "password": "Sup3rSecret"},
        )
        assert other.status_code == 201
        from app.repositories.user import UserRepository

        other_id = UserRepository().get_by_email("other-user@example.com")["id"]
        foreign_app, _ = _seed_application(db_session, other_id, app_status="offer")
        rows = client.get("/applications", headers=auth_headers).json()
        assert foreign_app not in [r["id"] for r in rows]
        # Detail access to the foreign row is a 404, not a leak.
        detail = client.get(f"/applications/{foreign_app}", headers=auth_headers)
        assert detail.status_code == 404


class TestDetailAndSubmit:
    def test_detail_unknown_404(self, client, auth_headers):
        assert client.get("/applications/nope", headers=auth_headers).status_code == 404

    def test_submit_moves_draft_and_is_idempotent(
        self, client, auth_headers, user_id, db_session
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status="draft")
        resp = client.post(
            f"/applications/{app_id}/submit",
            headers=auth_headers,
            json={"applied_url": "https://jobs.example.com/apply/1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "submitted"
        assert body["answers"]["appliedUrl"] == "https://jobs.example.com/apply/1"
        assert body["answers"]["submittedAt"]
        # Idempotent re-submit: no-op, same status, answers unchanged.
        again = client.post(
            f"/applications/{app_id}/submit", headers=auth_headers, json={}
        )
        assert again.status_code == 200
        assert again.json()["status"] == "submitted"
        assert again.json()["answers"]["appliedUrl"] == "https://jobs.example.com/apply/1"

    def test_submit_url_too_long_422(self, client, auth_headers, user_id, db_session):
        app_id, _ = _seed_application(db_session, user_id, app_status="draft")
        resp = client.post(
            f"/applications/{app_id}/submit",
            headers=auth_headers,
            json={"applied_url": "x" * 2001},
        )
        assert resp.status_code == 422


class TestFunnelSankey:
    def test_requires_auth(self, client):
        assert client.get("/applications/funnel/sankey").status_code == 401

    def test_canonical_labels_and_structure(self, client, auth_headers):
        data = client.get("/applications/funnel/sankey", headers=auth_headers).json()
        assert [s["label"] for s in data["stages"]] == [
            "Jobs Found", "Applied", "Screened", "Interviewed", "Offers",
        ]
        assert [s["key"] for s in data["stages"]] == [
            "jobs_found", "applied", "screened", "interviewed", "offers",
        ]
        # Values are computed from live DB — just verify they're non-negative
        for s in data["stages"]:
            assert isinstance(s["value"], int) and s["value"] >= 0
        assert len(data["dropoffs"]) == 4
        assert isinstance(data["insight"], str)
        assert data["dropoffs"][0]["reason"] == "below match threshold"
