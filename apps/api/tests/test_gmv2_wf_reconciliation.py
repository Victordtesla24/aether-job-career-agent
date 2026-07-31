"""GOLD-MASTER-V2 §8 — ML-APP-003 (HIGH): stage counts do not reconcile.

CONFIRMED LIVE (orchestrator ground truth, this run): the board's "In Review"
column shows 0, the Applied tab shows a generic "applied" badge, and the
Sankey funnel says "Screened: 2" — three different answers about the SAME 2
real screening-stage rows.

Root cause traced in code this run:
  - ``GET /applications`` (app/routers/applications.py:list_applications, the
    board's data source) EXCLUDES any application whose parent Job.status is
    IN ('applied', 'archived') unless ``?include_applied=true`` is passed.
  - ``GET /applications/funnel/sankey`` (same file, funnel_sankey) computes its
    "screened" node as ``COUNT(DISTINCT jobId) FILTER (WHERE status IN
    ('screening','interview','offer'))`` straight off ``Application.status``,
    with NO Job.status filter at all.
  - ``POST /jobs/{id}/apply`` flips the parent Job.status to 'applied' the
    moment an application is created/promoted to 'submitted' — it does NOT
    advance again when the application is later moved deeper into the
    pipeline (screening/interview/offer) via ``POST /applications/{id}/move``,
    which only ever touches ``Application.status``.
  - Net effect: an application that reached "screening" via the ordinary
    apply-then-advance flow has Job.status='applied' forever after, so it is
    INVISIBLE to the default board query while the funnel keeps counting it.

This test reproduces the defect through the app's OWN public endpoints (apply,
then move) — not by hand-crafting inconsistent DB state — and asserts
reconciliation at the API/service seam that produces the numbers, per the
brief ("not by scraping UI").
"""
from __future__ import annotations

import json
import uuid

from app.db import get_connection, new_id


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


def _make_job(user_id: str) -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Staff Engineer", "Canva", "Sydney NSW", False,
                    "Build delivery platforms.", json.dumps([]), "seek",
                    f"https://example.com/{job_id}", 88.0,
                ),
            )
        conn.commit()
    return job_id


def _make_resume(user_id: str, *, source_job_id: str) -> str:
    resume_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
                   VALUES (%s,%s,1,%s,%s,%s,NOW())''',
                (resume_id, user_id, json.dumps({"raw_text": "Experienced engineer"}),
                 "hash", source_job_id),
            )
        conn.commit()
    return resume_id


def _make_draft_with_cover_letter(user_id: str, job_id: str, resume_id: str) -> str:
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


class TestStageCountReconciliation:
    def test_board_and_funnel_agree_on_screening_stage_count(
        self, client, auth_headers, test_user_id
    ):
        # Reach "screening" via the REAL public API: apply (creates the
        # Application, flips Job.status -> 'applied'), then move the
        # resulting application on into review (Application.status ->
        # 'screening'; the move endpoint deliberately never touches
        # Job.status).
        job_id = _make_job(test_user_id)
        resume_id = _make_resume(test_user_id, source_job_id=job_id)
        _make_draft_with_cover_letter(test_user_id, job_id, resume_id)

        applied = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert applied.status_code == 200, applied.text
        application_id = applied.json()["applicationId"]

        moved = client.post(
            f"/applications/{application_id}/move",
            headers=auth_headers,
            json={"to_stage": "in-review"},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["status"] == "screening"

        # Seam 1: the board's data source (what the "In Review" column counts).
        board_rows = client.get("/applications", headers=auth_headers).json()
        board_screening_count = sum(1 for r in board_rows if r["status"] == "screening")

        # Seam 2: the Sankey funnel's "screened" node.
        sankey = client.get("/applications/funnel/sankey", headers=auth_headers).json()
        sankey_screened = next(s["value"] for s in sankey["stages"] if s["key"] == "screened")

        assert board_screening_count == sankey_screened, (
            "ML-APP-003: GET /applications (board) and GET /applications/"
            "funnel/sankey (funnel) disagree on the screening-stage count for "
            f"the identical underlying data — board={board_screening_count}, "
            f"sankey={sankey_screened}. The board's default query hides this "
            "row because its parent Job.status is 'applied' (set by the "
            "earlier apply call and never advanced again); the funnel counts "
            "purely off Application.status with no Job.status filter."
        )

    def test_applied_tab_and_funnel_agree_on_screening_stage_count(
        self, client, auth_headers, test_user_id
    ):
        """Same scenario, but via the ``include_applied=true`` (Applied tab)
        listing — included as a second seam so the finding isn't attributable
        to one specific query flag."""
        job_id = _make_job(test_user_id)
        resume_id = _make_resume(test_user_id, source_job_id=job_id)
        _make_draft_with_cover_letter(test_user_id, job_id, resume_id)

        applied = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert applied.status_code == 200, applied.text
        application_id = applied.json()["applicationId"]
        client.post(
            f"/applications/{application_id}/move",
            headers=auth_headers,
            json={"to_stage": "in-review"},
        )

        applied_tab_rows = client.get(
            "/applications?include_applied=true", headers=auth_headers
        ).json()
        applied_tab_screening_count = sum(
            1 for r in applied_tab_rows if r["status"] == "screening"
        )

        sankey = client.get("/applications/funnel/sankey", headers=auth_headers).json()
        sankey_screened = next(s["value"] for s in sankey["stages"] if s["key"] == "screened")

        assert applied_tab_screening_count == sankey_screened, (
            "ML-APP-003: the Applied tab shows the application at its real "
            f"'screening' status (count={applied_tab_screening_count}) but "
            f"under a job-status filter that only exists because apply() set "
            "Job.status='applied' — this diverges from the funnel "
            f"(screened={sankey_screened}) whenever this count isn't 1:1, and "
            "the SAME row is presented as a generic 'applied' card there "
            "instead of its true pipeline stage."
        )
