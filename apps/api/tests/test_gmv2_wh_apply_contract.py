"""GOLD-MASTER-V2 §10 — W-H, Jobs-screen Apply (GOV-010).

Ground truth (this run): ``POST /jobs/{id}/apply`` exists and works; the
pre-apply confirmation modal, bulk apply and "View on source" all verified
working live. The gap per orchestrator ruling GOV-010 is that NO per-card
Apply button exists on the Jobs screen (frontend — apps/web/**, owned by
another agent, NOT tested here). This file pins the BACKEND contract that
button (and the existing bulk-apply loop) already depends on:
  1. atomic Application-create + Job-status-advance, with an honest failure
     leaving the job unmarked;
  2. owner scoping;
  3. idempotency respecting the partial unique index
     (``Application_user_job_active_key``);
  4. honest per-job outcomes when applying to a BATCH of jobs (the pattern
     the Jobs screen's existing "Bulk Apply" button already uses — N
     sequential ``POST /jobs/{id}/apply`` calls, per
     apps/web/src/app/dashboard/jobs/page.tsx — there is no dedicated
     "/jobs/bulk-apply" backend endpoint).

Several of these assertions may already pass against current code — per the
brief, that is a valid finding to report honestly, not something to force
into failing.
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
        "description": "Lead cross-functional delivery of the platform program.",
        "requirements": json.dumps([]),
        "source": "seek",
        "sourceUrl": f"https://example.com/{job_id}",
        "fitScore": 82.0,
    }
    fields.update(over)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (job_id, user_id, fields["title"], fields["company"], fields["location"],
                 fields["remote"], fields["description"], fields["requirements"],
                 fields["source"], fields["sourceUrl"], fields["fitScore"]),
            )
        conn.commit()
    return job_id


def _make_resume(user_id: str, *, source_job_id: str | None = None) -> str:
    resume_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
                   VALUES (%s,%s,1,%s,%s,%s,NOW())''',
                (resume_id, user_id,
                 json.dumps({"raw_text": "Experienced delivery lead"}),
                 "hash", source_job_id),
            )
        conn.commit()
    return resume_id


def _make_eligible_job(user_id: str) -> str:
    """A job that satisfies the apply gate: tailored resume + draft
    Application carrying a non-empty cover letter."""
    job_id = _make_job(user_id)
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
    return job_id


def _job_status(job_id: str) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "status" FROM "Job" WHERE "id" = %s', (job_id,))
            return cur.fetchone()[0]


def _application_count_for_job(job_id: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "Application" WHERE "jobId" = %s', (job_id,))
            return cur.fetchone()[0]


class TestApplyIsAtomic:
    def test_success_creates_application_and_advances_job_together(
        self, client, auth_headers, user_id
    ):
        job_id = _make_eligible_job(user_id)
        resp = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["job"]["status"] == "applied"
        assert body["applicationId"]
        assert _application_count_for_job(job_id) == 1
        assert _job_status(job_id) == "applied"

    def test_gate_failure_leaves_job_not_applied_and_creates_no_application(
        self, client, auth_headers, user_id
    ):
        job_id = _make_job(user_id)  # no tailored resume, no cover letter
        before_status = _job_status(job_id)
        resp = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert resp.status_code == 422, resp.text
        assert _job_status(job_id) == before_status, (
            "a failed apply must NOT mark the job applied (no optimistic "
            f"success); job status changed to {_job_status(job_id)!r}"
        )
        assert _application_count_for_job(job_id) == 0, (
            "a failed apply must not leave a partial Application row behind"
        )

    def test_cover_letter_gate_failure_leaves_job_not_applied(
        self, client, auth_headers, user_id
    ):
        job_id = _make_job(user_id)
        _make_resume(user_id, source_job_id=job_id)  # tailored, but no cover letter
        resp = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert resp.status_code == 422, resp.text
        assert _job_status(job_id) != "applied"
        assert _application_count_for_job(job_id) == 0


class TestApplyOwnerScoped:
    def test_foreign_job_is_404_not_silent_success(self, client, auth_headers):
        other = {"email": "wh-contract-other@example.com", "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=other).status_code == 201
        other_token = client.post("/auth/login", json=other).json()["access_token"]
        other_headers = {"Authorization": f"Bearer {other_token}"}
        other_me = client.get("/auth/me", headers=other_headers).json()

        foreign_job = _make_eligible_job(other_me["id"])
        resp = client.post(f"/jobs/{foreign_job}/apply", headers=auth_headers)
        assert resp.status_code == 404, (
            f"applying to another user's job must be an honest 404, never a "
            f"silent success; got {resp.status_code} {resp.text}"
        )
        assert _job_status(foreign_job) != "applied"


class TestApplyIdempotent:
    def test_applying_twice_does_not_duplicate_the_application(
        self, client, auth_headers, user_id
    ):
        job_id = _make_eligible_job(user_id)
        first = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        second = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["applicationId"] == second.json()["applicationId"]
        assert _application_count_for_job(job_id) == 1, (
            "a duplicate active Application would violate the partial unique "
            "index Application_user_job_active_key"
        )


class TestBulkApplyHonestPerJobOutcomes:
    """The Jobs screen's existing "Bulk Apply" button (jd09-jd11,
    apps/web/src/app/dashboard/jobs/page.tsx ~line 605) has NO dedicated
    backend endpoint — it loops over this same POST /jobs/{id}/apply per
    selected job. These tests pin the backend contract that makes an honest
    (non-manufactured-success) frontend report possible: each call must
    succeed/fail strictly per-job with no cross-job side effects."""

    def test_partial_batch_success_is_reported_honestly_per_job(
        self, client, auth_headers, user_id
    ):
        eligible_a = _make_eligible_job(user_id)
        ineligible_b = _make_job(user_id)  # no tailored resume — will 422
        eligible_c = _make_eligible_job(user_id)

        batch = [eligible_a, ineligible_b, eligible_c]
        outcomes = {
            job_id: client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
            for job_id in batch
        }

        assert outcomes[eligible_a].status_code == 200, outcomes[eligible_a].text
        assert outcomes[ineligible_b].status_code == 422, outcomes[ineligible_b].text
        assert outcomes[eligible_c].status_code == 200, outcomes[eligible_c].text

        # The batch must not be reported as a total success: the failing
        # job's status code alone is enough for an honest caller to know it
        # failed, and its state proves nothing silently succeeded for it.
        assert _job_status(eligible_a) == "applied"
        assert _job_status(eligible_c) == "applied"
        assert _job_status(ineligible_b) != "applied", (
            "a failure elsewhere in the batch must not mask (or a batch-level "
            "success must not paper over) this job's own failed apply"
        )
        assert _application_count_for_job(ineligible_b) == 0

    def test_one_job_failing_does_not_affect_another_jobs_success(
        self, client, auth_headers, user_id
    ):
        """Order sensitivity check: fail BEFORE the eligible job in the
        batch, to rule out any shared-transaction / early-return bug that
        could make a later success silently absorb an earlier failure."""
        ineligible_first = _make_job(user_id)
        eligible_second = _make_eligible_job(user_id)

        first_resp = client.post(f"/jobs/{ineligible_first}/apply", headers=auth_headers)
        second_resp = client.post(f"/jobs/{eligible_second}/apply", headers=auth_headers)

        assert first_resp.status_code == 422
        assert second_resp.status_code == 200, second_resp.text
        assert _job_status(eligible_second) == "applied"
        assert _application_count_for_job(ineligible_first) == 0
