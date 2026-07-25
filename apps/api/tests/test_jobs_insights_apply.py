"""AGT-JOBS — tests for GET /jobs/{id}/insights and POST /jobs/{id}/apply.

These cover the two endpoints added for the Job Discovery detail panel and the
submit-confirmation gate. Insights are ATS-derived (deterministic); apply
creates an Application and advances the job to ``applied`` idempotently.

FEAT-SUBMISSION-GATE: apply now enforces tailored resume + cover letter before
submission. TestApplyGate exercises the new 422 rejection paths.
"""
from __future__ import annotations

import json

import pytest

from app.db import get_connection, new_id


@pytest.fixture()
def user_id(client, auth_headers, db_session) -> str:
    with db_session.cursor() as cur:
        cur.execute('SELECT "id" FROM "User" LIMIT 1')
        return cur.fetchone()[0]


def _make_job(user_id: str, **over) -> str:
    job_id = new_id()
    fields = {
        "title": "Senior Delivery Lead",
        "company": "Canva",
        "location": "Sydney NSW",
        "remote": False,
        "description": "Lead cross-functional delivery of the platform program "
        "with agile program management, governance and cloud delivery.",
        "requirements": json.dumps([]),
        "source": "seek",
        "sourceUrl": f"https://example.com/{job_id}",
        "fitScore": 82.0,
        "atsScore": 82.0,
    }
    fields.update(over)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","atsScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (job_id, user_id, fields["title"], fields["company"], fields["location"],
                 fields["remote"], fields["description"], fields["requirements"],
                 fields["source"], fields["sourceUrl"], fields["fitScore"], fields["atsScore"]),
            )
        conn.commit()
    return job_id


def _make_resume(user_id: str, *, source_job_id: str | None = None) -> str:
    """Create a resume row. When source_job_id is set, it is a tailored resume."""
    resume_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
                   VALUES (%s,%s,1,%s,%s,%s,NOW())''',
                (resume_id, user_id,
                 json.dumps({"raw_text": "Experienced delivery lead with agile expertise"}),
                 "hash", source_job_id),
            )
        conn.commit()
    return resume_id


def _prep_gate_requirements(user_id: str, job_id: str) -> str:
    """Seed a tailored resume + draft Application with cover letter so the
    apply submission gate passes. Returns the draft application id."""
    resume_id = _make_resume(user_id, source_job_id=job_id)
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Application"
                   ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
                   VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
                (app_id, user_id, job_id, resume_id,
                 "Dear Hiring Manager,\n\nI am excited to apply..."),
            )
        conn.commit()
    return app_id


class TestInsights:
    def test_insights_shape_is_deterministic(self, client, auth_headers, user_id):
        job_id = _make_job(user_id)
        r1 = client.get(f"/jobs/{job_id}/insights", headers=auth_headers)
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert body["jobId"] == job_id
        assert len(body["dimensions"]) == 10
        labels = {d["label"] for d in body["dimensions"]}
        assert {"Technical Skills", "Salary Fit", "Location Match", "North Star Align"} <= labels
        for d in body["dimensions"]:
            assert 0 <= d["score"] <= 100
        assert isinstance(body["riskSignals"], list)
        assert isinstance(body["skillsMatched"], int)
        assert body["isAustralia"] is True  # Sydney NSW
        # deterministic: same request → same payload
        r2 = client.get(f"/jobs/{job_id}/insights", headers=auth_headers)
        assert r2.json() == body

    def test_no_salary_produces_risk_flag(self, client, auth_headers, user_id):
        job_id = _make_job(user_id)
        body = client.get(f"/jobs/{job_id}/insights", headers=auth_headers).json()
        assert any(r["label"] == "No salary listed" for r in body["riskSignals"])

    def test_international_location_classification(self, client, auth_headers, user_id):
        job_id = _make_job(user_id, location="Remote — Americas", remote=True)
        body = client.get(f"/jobs/{job_id}/insights", headers=auth_headers).json()
        assert body["isAustralia"] is False
        loc_dim = next(d for d in body["dimensions"] if d["label"] == "Location Match")
        assert loc_dim["score"] == 100  # remote → full location match

    def test_insights_404_for_unknown_job(self, client, auth_headers):
        r = client.get("/jobs/does-not-exist/insights", headers=auth_headers)
        assert r.status_code == 404


class TestApply:
    def test_apply_creates_application_and_advances_status(self, client, auth_headers, user_id):
        job_id = _make_job(user_id)
        _prep_gate_requirements(user_id, job_id)
        r = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["job"]["status"] == "applied"
        assert body["applicationId"]
        # Application row exists
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT "status" FROM "Application" WHERE "jobId" = %s', (job_id,))
                rows = cur.fetchall()
        assert len(rows) >= 1

    def test_apply_is_idempotent(self, client, auth_headers, user_id):
        job_id = _make_job(user_id)
        _prep_gate_requirements(user_id, job_id)
        first = client.post(f"/jobs/{job_id}/apply", headers=auth_headers).json()
        second = client.post(f"/jobs/{job_id}/apply", headers=auth_headers).json()
        assert first["applicationId"] == second["applicationId"]
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT count(*) FROM "Application" WHERE "jobId" = %s', (job_id,))
                assert cur.fetchone()[0] >= 1

    def test_apply_without_resume_returns_422(self, client, auth_headers, user_id):
        job_id = _make_job(user_id)  # no resume seeded
        r = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert r.status_code == 422

    def test_apply_404_for_unknown_job(self, client, auth_headers):
        r = client.post("/jobs/nope/apply", headers=auth_headers)
        assert r.status_code == 404


class TestApplyGate:
    """FEAT-SUBMISSION-GATE: tailored resume + cover letter enforcement."""

    def test_apply_without_tailored_resume_returns_422(self, client, auth_headers, user_id):
        """Apply rejects when no tailored resume exists."""
        job_id = _make_job(user_id)
        _make_resume(user_id)  # base resume only, not tailored to this job
        r = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert r.status_code == 422
        assert "tailored resume" in r.json()["detail"].lower()

    def test_apply_without_cover_letter_returns_422(self, client, auth_headers, user_id):
        """Apply rejects when tailored resume exists but no cover letter."""
        job_id = _make_job(user_id)
        _make_resume(user_id, source_job_id=job_id)
        r = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert r.status_code == 422
        assert "cover letter" in r.json()["detail"].lower()

    def test_apply_with_both_succeeds(self, client, auth_headers, user_id):
        """Apply passes the gate with both tailored resume and cover letter."""
        job_id = _make_job(user_id)
        _prep_gate_requirements(user_id, job_id)
        r = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["job"]["status"] == "applied"

    def test_apply_draft_from_pipeline_satisfies_gate(self, client, auth_headers, user_id):
        """A DRAFT Application with cover letter from the autopilot satisfies gate."""
        job_id = _make_job(user_id)
        app_id = _prep_gate_requirements(user_id, job_id)
        r = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert r.status_code == 200, r.text
        # The draft is promoted to submitted
        detail = client.get(f"/applications/{app_id}", headers=auth_headers).json()
        assert detail["status"] == "submitted"

    def test_apply_neither_missing_returns_resume_error_first(
        self, client, auth_headers, user_id
    ):
        """When both are missing, tailored-resume error comes first (fail early)."""
        job_id = _make_job(user_id)
        r = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert r.status_code == 422
        assert "tailored resume" in r.json()["detail"].lower()

    def test_apply_cover_without_tailored_still_rejects(
        self, client, auth_headers, user_id
    ):
        """Cover letter without tailored resume — tailored check fires first."""
        job_id = _make_job(user_id)
        base = _make_resume(user_id)  # base only, not tailored
        app_id = new_id()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''INSERT INTO "Application"
                       ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
                       VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
                    (app_id, user_id, job_id, base,
                     "Dear Hiring Manager,\n\nI am excited..."),
                )
            conn.commit()
        r = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert r.status_code == 422
        assert "tailored resume" in r.json()["detail"].lower()
