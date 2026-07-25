"""RT-009 / RT-010 — apply-flow board + tailored-resume truth.

RT-009: applying to a job that already has a pipeline/autopilot-created DRAFT
Application reused that draft's id but LEFT it at ``draft`` while flipping
``Job.status`` to ``applied``. Board result: the job card vanished (applied is
unmapped) but the still-``draft`` Application lingered forever in the "Ready to
Apply" column — the applied job never flushed out of the pipeline.

RT-010: the Jobs screen must know a job already has a tailored résumé so it
never shows the "untailored" step-1 state (or bulk "current, untailored"
warning) for a job the user (or the agents) already tailored. The job payload
now carries ``tailoredResumeId``.
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


def _seed_job(conn, user_id: str, *, status: str = "ready") -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, "Staff Engineer", "Canva", "Build.", "lever",
             f"https://example.com/job/{job_id}", status, 90.0),
        )
    conn.commit()
    return job_id


def _seed_resume(conn, user_id: str, *, source_job_id: str | None, version: int) -> str:
    resume_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"sourceJobId","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,NOW())',
            (resume_id, user_id, version, json.dumps({"raw_text": "cv"}), "h",
             source_job_id),
        )
    conn.commit()
    return resume_id


def _seed_draft_app(
    conn, user_id: str, job_id: str, resume_id: str, *, cover_letter: str | None = None
) -> str:
    app_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,'draft'::\"ApplicationStatus\",%s,NOW(),NOW())",
            (app_id, user_id, job_id, resume_id, cover_letter),
        )
    conn.commit()
    return app_id


def _submit(client, app_id: str, auth_headers):
    return client.post(
        f"/applications/{app_id}/submit",
        json={"applied_url": "https://example.com/apply"},
        headers=auth_headers,
    )


class TestSubmissionValidationGate:
    def test_apply_rejects_when_no_tailored_resume(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        _seed_resume(db_session, user_id, source_job_id=None, version=1)

        response = client.post(f"/jobs/{job}/apply", headers=auth_headers)

        assert response.status_code == 422
        assert "tailored resume" in response.json()["detail"].lower()

    def test_apply_rejects_when_no_cover_letter(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        _seed_resume(db_session, user_id, source_job_id=job, version=1)

        response = client.post(f"/jobs/{job}/apply", headers=auth_headers)

        assert response.status_code == 422
        assert "cover letter" in response.json()["detail"].lower()

    def test_apply_accepts_tailored_resume_and_cover_letter(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        tailored = _seed_resume(db_session, user_id, source_job_id=job, version=1)
        draft = _seed_draft_app(
            db_session, user_id, job, tailored, cover_letter="Dear hiring team"
        )

        response = client.post(f"/jobs/{job}/apply", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert response.json()["applicationId"] == draft

    def test_submit_rejects_draft_without_cover_letter(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        tailored = _seed_resume(db_session, user_id, source_job_id=job, version=1)
        draft = _seed_draft_app(db_session, user_id, job, tailored)

        response = _submit(client, draft, auth_headers)

        assert response.status_code == 422
        assert "cover letter" in response.json()["detail"].lower()

    def test_submit_rejects_draft_with_base_resume(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        base = _seed_resume(db_session, user_id, source_job_id=None, version=1)
        draft = _seed_draft_app(
            db_session, user_id, job, base, cover_letter="Dear hiring team"
        )

        response = _submit(client, draft, auth_headers)

        assert response.status_code == 422
        assert "not tailored" in response.json()["detail"].lower()

    def test_submit_accepts_prepared_draft(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        tailored = _seed_resume(db_session, user_id, source_job_id=job, version=1)
        draft = _seed_draft_app(
            db_session, user_id, job, tailored, cover_letter="Dear hiring team"
        )

        response = _submit(client, draft, auth_headers)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "submitted"




class TestApplyFlushesBoard:
    def test_apply_promotes_existing_draft_to_submitted(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id, status="ready")
        tailored = _seed_resume(db_session, user_id, source_job_id=job, version=1)
        draft = _seed_draft_app(
            db_session, user_id, job, tailored, cover_letter="Dear hiring team"
        )
        resp = client.post(f"/jobs/{job}/apply", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        # The reused application is now SUBMITTED, not a lingering draft.
        with db_session.cursor() as cur:
            cur.execute('SELECT "status" FROM "Application" WHERE "id" = %s', (draft,))
            assert cur.fetchone()[0] == "submitted"
        # And the board shows it in Submitted, never "Ready to Apply".
        cards = client.get("/applications?include_applied=true", headers=auth_headers).json()
        job_cards = [c for c in cards if c["jobId"] == job]
        assert len(job_cards) == 1
        assert job_cards[0]["status"] == "submitted"

    def test_applied_job_leaves_the_pipeline_job_columns(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id, status="ready")
        tailored = _seed_resume(db_session, user_id, source_job_id=job, version=1)
        _seed_draft_app(
            db_session, user_id, job, tailored, cover_letter="Dear hiring team"
        )
        client.post(f"/jobs/{job}/apply", headers=auth_headers)
        after = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        status = next(j["status"] for j in after if j["id"] == job)
        assert status == "applied"

    def test_apply_is_idempotent_no_second_card(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id, status="ready")
        tailored = _seed_resume(db_session, user_id, source_job_id=job, version=1)
        _seed_draft_app(
            db_session, user_id, job, tailored, cover_letter="Dear hiring team"
        )
        client.post(f"/jobs/{job}/apply", headers=auth_headers)
        client.post(f"/jobs/{job}/apply", headers=auth_headers)
        cards = client.get("/applications?include_applied=true", headers=auth_headers).json()
        assert len([c for c in cards if c["jobId"] == job]) == 1


class TestTailoredResumeTruth:
    def test_job_payload_exposes_tailored_resume_id(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        tailored = _seed_resume(db_session, user_id, source_job_id=job, version=2)
        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(j for j in rows if j["id"] == job)
        assert row["tailoredResumeId"] == tailored

    def test_untailored_job_has_null_tailored_resume_id(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        _seed_resume(db_session, user_id, source_job_id=None, version=1)  # base only
        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(j for j in rows if j["id"] == job)
        assert row["tailoredResumeId"] is None

    def test_latest_tailored_version_wins(
        self, db_session, user_id, client, auth_headers
    ):
        job = _seed_job(db_session, user_id)
        _seed_resume(db_session, user_id, source_job_id=job, version=2)
        newest = _seed_resume(db_session, user_id, source_job_id=job, version=5)
        rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        row = next(j for j in rows if j["id"] == job)
        assert row["tailoredResumeId"] == newest
