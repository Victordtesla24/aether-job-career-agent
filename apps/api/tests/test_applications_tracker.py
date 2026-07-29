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
    tailored: bool = False,
    cover_letter: str | None = None,
) -> tuple[str, str]:
    """Insert Job + Resume + Application for ``user_id``; return (app_id, job_id).

    ``tailored`` links the seeded Resume to the seeded Job (``sourceJobId``) and
    ``cover_letter`` stores a letter on the Application — together they satisfy
    the FEAT-SUBMISSION-GATE preconditions (14e30c5) that
    ``POST /applications/{id}/submit`` enforces on a draft.
    """
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
            '"sourceJobId","updatedAt") VALUES (%s,%s,1,%s,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "test"}), "hash-test",
             job_id if tailored else None),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"answers","coverLetter","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,%s,NOW(),NOW())',
            (app_id, user_id, job_id, resume_id, app_status,
             json.dumps(answers) if answers is not None else None, cover_letter),
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
        # FEAT-SUBMISSION-GATE (14e30c5): a draft is only submittable once a
        # job-tailored resume and a cover letter exist. The invariant under test
        # here is unchanged — draft -> submitted records the real apply URL and
        # a repeat submit is a no-op — it is now exercised through a compliant
        # draft instead of a bare one.
        app_id, _ = _seed_application(
            db_session,
            user_id,
            app_status="draft",
            tailored=True,
            cover_letter="Dear Hiring Manager,\n\nI am excited to apply.",
        )
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

    def test_submit_rejects_when_no_tailored_resume_for_job(
        self, client, auth_headers, user_id, db_session
    ):
        """ml-adjudication-review-verdict.json niceToHave #2: this exact
        FEAT-SUBMISSION-GATE negative path — a cover letter exists but no
        Resume row is tailored (sourceJobId) for this job — was previously
        covered only indirectly via test_rt_009_010_apply_wiring.py's
        test_submit_rejects_draft_with_base_resume. Adding it directly here
        so the file that owns the endpoint also owns its full gate contract.
        """
        app_id, _ = _seed_application(
            db_session,
            user_id,
            app_status="draft",
            tailored=False,
            cover_letter="Dear Hiring Manager,\n\nI am excited to apply.",
        )
        resp = client.post(
            f"/applications/{app_id}/submit", headers=auth_headers, json={}
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "not tailored" in detail.lower()
        assert "tailor your resume" in detail.lower()

    def test_submit_double_submit_race_second_caller_takes_idempotent_path(
        self, client, auth_headers, user_id, db_session, monkeypatch
    ):
        """Reviewer niceToHave #3 (ml-adjudication-review-verdict.json): the
        promoting UPDATE had no ``status = 'draft'`` guard, so two concurrent
        submits that both read the row as 'draft' before either committed
        could both attempt to promote it — the second racer's UPDATE ran
        unconditionally and would silently overwrite the first racer's
        already-committed answers/resumeId (a double-promote), rather than a
        true compare-and-swap.

        Simulates the race deterministically (no thread-timing flakiness) by
        injecting a concurrent commit at the exact DB seam between this
        request's initial draft-check SELECT and its own promoting UPDATE.
        ``datetime.now(UTC)`` is the ONLY use of that name in
        submit_application, and it is evaluated immediately before the
        guarded UPDATE's parameters are built — hooking it lets "the other
        racer" flip the row to submitted, with ITS OWN answers, right
        between this request's read and its write.
        """
        app_id, job_id = _seed_application(
            db_session,
            user_id,
            app_status="draft",
            tailored=True,
            cover_letter="Dear Hiring Manager,\n\nI am excited to apply.",
        )
        with db_session.cursor() as cur:
            cur.execute('SELECT "id" FROM "Resume" WHERE "sourceJobId" = %s', (job_id,))
            tailored_resume_id = cur.fetchone()[0]

        import app.routers.applications as applications_module

        fired = {"done": False}

        class _RaceInjectingDatetime(applications_module.datetime):
            @classmethod
            def now(cls, tz=None):
                if not fired["done"]:
                    fired["done"] = True
                    with db_session.cursor() as race_cur:
                        race_cur.execute(
                            """
                            UPDATE "Application"
                            SET "status" = 'submitted'::"ApplicationStatus",
                                "resumeId" = %s,
                                "answers" = COALESCE("answers", '{}'::jsonb) || %s::jsonb,
                                "updatedAt" = NOW()
                            WHERE "id" = %s AND "userId" = %s
                              AND "status" = 'draft'::"ApplicationStatus"
                            """,
                            (
                                tailored_resume_id,
                                json.dumps(
                                    {
                                        "appliedUrl": "https://race-winner.example.com/apply",
                                        "submittedAt": "2026-01-01T00:00:00+00:00",
                                    }
                                ),
                                app_id,
                                user_id,
                            ),
                        )
                    db_session.commit()
                return super().now(tz)

        monkeypatch.setattr(applications_module, "datetime", _RaceInjectingDatetime)

        resp = client.post(
            f"/applications/{app_id}/submit",
            headers=auth_headers,
            json={"applied_url": "https://race-loser.example.com/apply"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "submitted"
        # The guarded UPDATE affected 0 rows for THIS call (the row was
        # already flipped by the "concurrent" racer) — it must fall through
        # to the idempotent success path and surface the WINNER's committed
        # answers, never clobber them with its own.
        assert body["answers"]["appliedUrl"] == "https://race-winner.example.com/apply"
        assert body["resumeId"] == tailored_resume_id

        with db_session.cursor() as cur:
            cur.execute('SELECT "status" FROM "Application" WHERE "id" = %s', (app_id,))
            assert cur.fetchone()[0] == "submitted"


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

    def test_aging_pipeline_never_produces_a_negative_dropoff(
        self, client, auth_headers, user_id, db_session
    ):
        """MV-application-tracker-006: reproduces the reviewer's live finding
        against be7b240 — 3 applications sitting at 'interview' and 1 at
        'offer', with NONE currently at exact status 'screening'. The prior
        stage-EXCLUSIVE model (status == 'screening' exactly) returned
        screened=0, interviewed=3, so the "screened -> interviewed" dropoff
        came back as 0 - 3 = -3, which SankeyFlow.tsx rendered as the broken
        literal "−-3 · no response / screened out".

        The CUMULATIVE model fixes this: "screened" counts status IN
        (screening, interview, offer), so an application already at
        'interview' is still counted as having passed through "screened" —
        every stage is >= the next, so every dropoff is >= 0. "Applied" is
        also now the canonical non-draft count from get_application_counts(),
        consistent with /analytics/funnel's "applied" rather than a
        divergent per-exact-status bucket.
        """
        _seed_application(db_session, user_id, app_status="interview")
        _seed_application(db_session, user_id, app_status="interview")
        _seed_application(db_session, user_id, app_status="interview")
        _seed_application(db_session, user_id, app_status="offer")

        sankey = client.get("/applications/funnel/sankey", headers=auth_headers).json()
        values = {s["key"]: s["value"] for s in sankey["stages"]}
        assert values["applied"] == 4  # all 4 are non-draft
        assert values["screened"] == 4  # interview/offer both count as "reached screened"
        assert values["interviewed"] == 4
        assert values["offers"] == 1

        for dropoff in sankey["dropoffs"]:
            assert dropoff["count"] >= 0, dropoff

        funnel = client.get("/analytics/funnel?period=all", headers=auth_headers).json()
        # The Sankey's "applied" now agrees with the funnel's "applied" —
        # both are the canonical cumulative non-draft count.
        assert sankey["stages"][1]["value"] == funnel["applied"] == 4
