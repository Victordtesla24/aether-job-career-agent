"""U5d-2 — the per-card submit control + write-time truth markers (RED first).

USER MANDATE: every application card on ``/dashboard/applications`` gets a
channel-aware control, and **the click IS the user's approval for THAT
application**. This file pins the backend half of that contract:

* ``POST /applications/{id}/request-submission`` creates AND approves an
  ``application_submit`` ApprovalRequest through the EXISTING repository
  (``create`` → ``approve``) — it is not a new bypass, it transmits nothing,
  and its response says so;
* the EXISTING ``POST /approvals/{id}/execute`` is the ONLY place a real
  transmission can happen, and it now routes an automatable site channel into
  the U5 apply engine instead of falling into the "no submission payload"
  branch;
* ``ApprovalRepository.claim_execution`` remains the single-shot guard, owned
  end-to-end by exactly ONE layer per channel — a second claim must never be
  taken for the same execute (that would report "already executed" for a
  submission that never happened);
* the card's state comes from a single backend-computed ``submissionControl``
  block, so the FE cannot invent a state the row does not support;
* **write-time truth markers**: every path that records ``status='submitted'``
  WITHOUT transmission proof stamps ``submissionTruthState =
  'recorded_not_transmitted'`` AT WRITE TIME, and a real transmission stamps
  ``transmittedAt`` and NO recorded marker.

ABSOLUTE SAFETY: both real transmission entry points are monkeypatched to fail
loudly. No browser is started, no email is sent, no employer is contacted. The
one "successful" transmission asserted here is produced by an INJECTED stub
submitter — the existing U5 dependency-injection seam
(``apply_executor.execute_site_application(submitter=...)``).
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


@pytest.fixture(autouse=True)
def _no_real_transmission(monkeypatch):
    from app.services import application_submission, apply_executor

    def _forbidden_browser(**kwargs):  # pragma: no cover - must never run
        raise AssertionError(
            "playwright_form_submitter was reached — a REAL browser submission "
            "to a REAL employer was about to be attempted."
        )

    def _forbidden_email(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError(
            "transmit_application was reached — a REAL application email was "
            "about to be sent."
        )

    monkeypatch.setattr(apply_executor, "playwright_form_submitter", _forbidden_browser)
    monkeypatch.setattr(
        application_submission, "transmit_application", _forbidden_email
    )
    yield


ASHBY_URL = "https://jobs.ashbyhq.com/example-co/00000000-0000-4000-8000-000000000001"
#: SUB-011: Lever re-entered AUTOMATABLE_CHANNELS (dedicated parser + tests).
#: The two tests below that pin "an ASSISTED channel's card" now use
#: SmartRecruiters — still ASSISTED, no dedicated parser — instead.
SMARTRECRUITERS_URL = "https://jobs.smartrecruiters.com/example-co/4000000001"


def _seed_job(conn, user_id: str, *, source_url: str = ASHBY_URL,
              description: str = "No address published.") -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, "Finance Specialist", "Example Co", description,
             "lever", source_url, "ready", 90.0),
        )
    conn.commit()
    return job_id


def _seed_resume(conn, user_id: str, *, source_job_id: str | None) -> str:
    resume_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"sourceJobId","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,NOW())',
            (resume_id, user_id, 1, json.dumps({"raw_text": "cv"}), "h", source_job_id),
        )
    conn.commit()
    return resume_id


def _seed_application(conn, user_id: str, job_id: str, resume_id: str | None, *,
                      status: str = "draft",
                      cover_letter: str | None = "Dear team, I would love to help.") -> str:
    app_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,NOW(),NOW())',
            (app_id, user_id, job_id, resume_id, status, cover_letter),
        )
    conn.commit()
    return app_id


def _truth_row(conn, app_id: str) -> dict:
    from app.db import (
        ensure_application_manual_step_columns,
        ensure_application_submission_truth_columns,
        ensure_application_transmission_columns,
    )

    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    ensure_application_submission_truth_columns()
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "status","transmittedAt","transmissionRef","submissionTruthState",'
            '"submissionTruthAt","manualStepReason" FROM "Application" WHERE "id" = %s',
            (app_id,),
        )
        r = cur.fetchone()
    assert r is not None
    return {
        "status": r[0], "transmittedAt": r[1], "transmissionRef": r[2],
        "submissionTruthState": r[3], "submissionTruthAt": r[4],
        "manualStepReason": r[5],
    }


# ---------------------------------------------------------------------------
# 1 — the per-card control block the FE renders
# ---------------------------------------------------------------------------


class TestSubmissionControlBlock:
    def test_ready_automatable_card_offers_submit(self, db_session, user_id, client, auth_headers):
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        body = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        control = body["submissionControl"]
        assert control["state"] == "ready"
        assert control["action"] == "submit"
        assert control["channel"] == "ashby"
        assert "Submit application" == control["label"]
        assert control["missing"] == []

    def test_assisted_card_offers_the_direct_url_not_a_submit_button(
        self, db_session, user_id, client, auth_headers
    ):
        job_id = _seed_job(db_session, user_id, source_url=SMARTRECRUITERS_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        body = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        control = body["submissionControl"]
        assert control["state"] == "needs_your_click"
        assert control["action"] == "open_posting"
        assert control["label"] == "Ready to submit — open posting"
        assert control["applyUrl"] == SMARTRECRUITERS_URL

    def test_lever_card_now_offers_submit_not_the_direct_url(
        self, db_session, user_id, client, auth_headers
    ):
        """SUB-011: Lever re-entered AUTOMATABLE_CHANNELS, so its card is now
        the SAME "ready/submit" shape as Ashby/Greenhouse, not the ASSISTED
        "needs your click" shape asserted above for SmartRecruiters."""
        lever_url = "https://jobs.lever.co/example-co/00000000-0000-4000-8000-000000000002"
        job_id = _seed_job(db_session, user_id, source_url=lever_url)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        body = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        control = body["submissionControl"]
        assert control["state"] == "ready"
        assert control["action"] == "submit"
        assert control["channel"] == "lever"

    def test_email_channel_card_offers_send_application_email(
        self, db_session, user_id, client, auth_headers
    ):
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)
        from app.db import ensure_job_apply_contact_columns

        ensure_job_apply_contact_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Job" SET "applyEmail" = %s, "applyEmailSource" = %s WHERE "id" = %s',
                ("careers@example.com", "description", job_id),
            )
        db_session.commit()

        body = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        control = body["submissionControl"]
        assert control["channel"] == "email"
        assert control["action"] == "send_email"
        assert control["label"] == "Send application email"

    def test_missing_artifacts_say_what_is_missing_and_where_to_go(
        self, db_session, user_id, client, auth_headers
    ):
        job_id = _seed_job(db_session, user_id)
        base_resume = _seed_resume(db_session, user_id, source_job_id=None)
        app_id = _seed_application(
            db_session, user_id, job_id, base_resume, cover_letter=None
        )

        body = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        control = body["submissionControl"]
        assert control["state"] == "draft"
        assert control["action"] == "fix_artifacts"
        assert control["label"] == "Tailor resume first"
        assert set(control["missing"]) == {"tailoredResume", "coverLetter"}
        assert control["href"]

    def test_transmitted_card_is_the_only_one_that_says_submitted(
        self, db_session, user_id, client, auth_headers
    ):
        from app.db import ensure_application_transmission_columns

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )
        ensure_application_transmission_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "transmittedAt" = NOW(), '
                '"transmissionRef" = %s WHERE "id" = %s',
                ("evidence.png", app_id),
            )
        db_session.commit()

        body = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        control = body["submissionControl"]
        assert control["state"] == "submitted"
        assert control["action"] == "none"
        assert "Submitted" in control["label"]

    def test_a_submitted_row_without_proof_never_says_submitted(
        self, db_session, user_id, client, auth_headers
    ):
        """The 346-row production state. ``status='submitted'`` with no
        ``transmittedAt`` may NEVER render the proof-bound label."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )

        body = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        control = body["submissionControl"]
        assert control["state"] != "submitted"
        assert "Submitted ✓" not in control["label"]

    def test_expired_approval_card_asks_for_a_reconfirmation(
        self, db_session, user_id, client, auth_headers
    ):
        from app.db import ensure_application_manual_step_columns

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)
        ensure_application_manual_step_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "manualStepReason" = %s, '
                '"manualStepDetail" = %s, "manualStepAt" = NOW() WHERE "id" = %s',
                ("approval_expired", "You approved this 9 days ago.", app_id),
            )
        db_session.commit()

        body = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        control = body["submissionControl"]
        assert control["state"] == "expired_reconfirm"
        assert control["action"] == "reconfirm"

    def test_captcha_manual_step_surfaces_honestly(
        self, db_session, user_id, client, auth_headers
    ):
        from app.db import ensure_application_manual_step_columns

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)
        ensure_application_manual_step_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "manualStepReason" = %s, '
                '"manualStepDetail" = %s, "manualStepAt" = NOW() WHERE "id" = %s',
                ("captcha", "The form requires a CAPTCHA.", app_id),
            )
        db_session.commit()

        body = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        control = body["submissionControl"]
        assert control["state"] == "manual_step"
        assert control["action"] == "open_posting"
        assert "CAPTCHA" in control["detail"]

    def test_the_list_endpoint_carries_the_same_block(
        self, db_session, user_id, client, auth_headers
    ):
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        rows = client.get("/applications", headers=auth_headers).json()

        row = next(r for r in rows if r["id"] == app_id)
        assert row["submissionControl"]["state"] == "ready"


# ---------------------------------------------------------------------------
# 2 — the click IS the approval, and it transmits nothing by itself
# ---------------------------------------------------------------------------


class TestRequestSubmissionEndpoint:
    def test_click_creates_and_approves_an_approval_and_sends_nothing(
        self, db_session, user_id, client, auth_headers
    ):
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        response = client.post(
            f"/applications/{app_id}/request-submission", headers=auth_headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["transmitted"] is False
        assert body["approvalId"]
        assert body["channel"] == "ashby"
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "status","executedAt","applicationId","payload" '
                'FROM "ApprovalRequest" WHERE "id" = %s',
                (body["approvalId"],),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "approved", "the click IS the approval"
        assert row[1] is None, "approving must never execute"
        assert row[2] == app_id
        assert row[3]["channel"] == "ashby"
        assert _truth_row(db_session, app_id)["transmittedAt"] is None

    def test_assisted_channel_is_refused_not_silently_approved(
        self, db_session, user_id, client, auth_headers
    ):
        job_id = _seed_job(db_session, user_id, source_url=SMARTRECRUITERS_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        response = client.post(
            f"/applications/{app_id}/request-submission", headers=auth_headers
        )

        assert response.status_code == 409, response.text
        assert "smartrecruiters" in response.text.lower() or "click" in response.text.lower()

    def test_missing_artifacts_are_refused_with_the_reason(
        self, db_session, user_id, client, auth_headers
    ):
        job_id = _seed_job(db_session, user_id)
        base_resume = _seed_resume(db_session, user_id, source_job_id=None)
        app_id = _seed_application(db_session, user_id, job_id, base_resume)

        response = client.post(
            f"/applications/{app_id}/request-submission", headers=auth_headers
        )

        assert response.status_code == 422, response.text
        assert "tailor" in response.text.lower()

    def test_another_users_application_is_not_found(
        self, db_session, user_id, client, auth_headers
    ):
        response = client.post(
            f"/applications/{_uid()}/request-submission", headers=auth_headers
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 3 — the EXISTING execute endpoint drives the U5 engine
# ---------------------------------------------------------------------------


class TestExecuteRoutesToTheApplyEngine:
    def _approve(self, client, auth_headers, app_id: str) -> str:
        response = client.post(
            f"/applications/{app_id}/request-submission", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        return response.json()["approvalId"]

    def test_execute_reaches_the_site_engine_and_proves_the_transmission(
        self, db_session, user_id, client, auth_headers, monkeypatch
    ):
        """DRY RUN through the REAL chain with an INJECTED submitter. The
        browser seam never runs; the proof is read back off the row."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)
        approval_id = self._approve(client, auth_headers, app_id)

        from app.services import apply_executor
        from app.workers import apply_sweep

        monkeypatch.setattr(
            apply_sweep, "fetch_apply_page", lambda url: "<form></form>", raising=False
        )
        monkeypatch.setattr(
            apply_executor, "fetch_apply_page", lambda url: "<form></form>"
        )
        monkeypatch.setattr(
            apply_executor, "build_form_fill_plan",
            # Mirrors the real seam's signature and RETURN SHAPE (U5d-3 added
            # the optional Answer Bank resolver and the audit list), so this
            # stub cannot drift into testing a contract production never has.
            lambda html, *, channel, profile, answer_bank=None: {
                "fields": [], "unanswerable_required": [], "answerBankAudit": [],
            },
        )
        monkeypatch.setattr(apply_sweep, "_render_resume_pdf", lambda uid, app: b"%PDF-")

        real_execute = apply_executor.execute_site_application

        def _dry_run_execute(*args, **kwargs):
            kwargs["submitter"] = lambda **kw: {
                "submitted": True,
                "mode": "dry-run-stub",
                "destination": ASHBY_URL,
                "evidencePath": "/tmp/u5d2-dry-run-evidence.png",
                "confirmation": "stubbed confirmation — nothing was sent",
                "filled": [],
                "unfilled": [],
            }
            return real_execute(*args, **kwargs)

        monkeypatch.setattr(apply_executor, "execute_site_application", _dry_run_execute)
        monkeypatch.setattr(
            apply_sweep, "execute_site_application", _dry_run_execute, raising=False
        )

        response = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["transmitted"] is True
        row = _truth_row(db_session, app_id)
        assert row["transmittedAt"] is not None
        assert row["transmissionRef"] == "/tmp/u5d2-dry-run-evidence.png"
        assert row["status"] == "submitted"
        # WRITE-TIME TRUTH MARKER: a proven transmission carries NO
        # recorded-not-transmitted marker.
        assert row["submissionTruthState"] != "recorded_not_transmitted"
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "executedAt","executionCompletedAt" FROM "ApprovalRequest" '
                'WHERE "id" = %s',
                (approval_id,),
            )
            approval = cur.fetchone()
        assert approval[0] is not None, "the claim must be stamped"
        assert approval[1] is not None, "the completion must be proven"

    def test_execute_takes_the_execution_claim_exactly_once(
        self, db_session, user_id, client, auth_headers, monkeypatch
    ):
        """The site path's claim is owned END-TO-END by
        ``execute_site_application``. A second claim taken by the router would
        make the executor's own claim fail and report "already executed" for a
        submission that never happened."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)
        approval_id = self._approve(client, auth_headers, app_id)

        from app.repositories import approval as approval_module

        claims: list[str] = []
        real_claim = approval_module.ApprovalRepository.claim_execution

        def _counting_claim(self, aid, uid):
            claims.append(aid)
            return real_claim(self, aid, uid)

        monkeypatch.setattr(
            approval_module.ApprovalRepository, "claim_execution", _counting_claim
        )

        from app.services import apply_executor
        from app.workers import apply_sweep

        monkeypatch.setattr(apply_executor, "fetch_apply_page", lambda url: "<form></form>")
        monkeypatch.setattr(
            apply_executor, "build_form_fill_plan",
            # Mirrors the real seam's signature and RETURN SHAPE (U5d-3 added
            # the optional Answer Bank resolver and the audit list), so this
            # stub cannot drift into testing a contract production never has.
            lambda html, *, channel, profile, answer_bank=None: {
                "fields": [], "unanswerable_required": [], "answerBankAudit": [],
            },
        )
        monkeypatch.setattr(apply_sweep, "_render_resume_pdf", lambda uid, app: b"%PDF-")
        real_execute = apply_executor.execute_site_application

        def _dry_run_execute(*args, **kwargs):
            kwargs["submitter"] = lambda **kw: {
                "submitted": True, "mode": "dry-run-stub", "destination": ASHBY_URL,
                "evidencePath": "/tmp/u5d2-claim.png", "filled": [], "unfilled": [],
            }
            return real_execute(*args, **kwargs)

        monkeypatch.setattr(apply_executor, "execute_site_application", _dry_run_execute)

        response = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert claims.count(approval_id) == 1, (
            f"claim_execution ran {claims.count(approval_id)}x for one execute"
        )

    def test_transport_failure_is_a_502_not_an_unhandled_500(
        self, db_session, user_id, client, auth_headers, monkeypatch
    ):
        """F5-006 (Fable 5 adversarial review): a browser/transport failure
        (e.g. the Playwright binary missing, or the site unreachable) raised
        ``ApplyExecutorTransportError`` straight through the router as a raw
        500. It is an expected operational condition — the honest answer is a
        502 carrying the "nothing was submitted" message."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)
        approval_id = self._approve(client, auth_headers, app_id)

        from app.services.apply_executor import ApplyExecutorTransportError
        from app.workers import apply_sweep

        def _transport_down(uid, application_id, aid):
            raise ApplyExecutorTransportError(
                "browser_failed",
                "Could not open the application page (Error) — nothing was "
                "submitted.",
            )

        monkeypatch.setattr(apply_sweep, "_attempt_transmission", _transport_down)

        response = client.post(
            f"/approvals/{approval_id}/execute", headers=auth_headers
        )

        assert response.status_code == 502, response.text
        assert "nothing was submitted" in response.json()["detail"]
        # And the row was NOT marked transmitted.
        row = _truth_row(db_session, app_id)
        assert row["transmittedAt"] is None

    def test_manual_step_outcome_is_reported_honestly_not_as_a_submission(
        self, db_session, user_id, client, auth_headers, monkeypatch
    ):
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)
        approval_id = self._approve(client, auth_headers, app_id)

        from app.services import apply_executor
        from app.workers import apply_sweep

        monkeypatch.setattr(apply_sweep, "_render_resume_pdf", lambda uid, app: b"%PDF-")
        monkeypatch.setattr(apply_executor, "fetch_apply_page", lambda url: "<html/>")

        def _blocked(html, *, channel, profile, answer_bank=None):
            raise apply_executor.ManualStepRequired(
                "captcha", "This form is protected by a CAPTCHA."
            )

        monkeypatch.setattr(apply_executor, "build_form_fill_plan", _blocked)

        response = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["transmitted"] is False
        assert body["reason"] == "captcha"
        row = _truth_row(db_session, app_id)
        assert row["transmittedAt"] is None
        assert row["manualStepReason"] == "captcha"
        assert row["status"] == "draft"

    def test_an_unapproved_application_cannot_be_executed(
        self, db_session, user_id, client, auth_headers
    ):
        from app.repositories.approval import ApprovalRepository

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)
        pending = ApprovalRepository().create(
            user_id,
            "application_submit",
            {"kind": "submission", "channel": "ashby", "job_id": job_id,
             "application_id": app_id, "apply_url": ASHBY_URL},
            application_id=app_id,
        )

        response = client.post(f"/approvals/{pending['id']}/execute", headers=auth_headers)

        assert response.status_code in (403, 409), response.text
        assert _truth_row(db_session, app_id)["transmittedAt"] is None


# ---------------------------------------------------------------------------
# 4 — write-time truth markers (pass-2 residual)
# ---------------------------------------------------------------------------


class TestWriteTimeTruthMarkers:
    def test_bookkeeping_submit_stamps_recorded_not_transmitted(
        self, db_session, user_id, client, auth_headers
    ):
        """``POST /applications/{id}/submit`` records the USER's own act of
        applying elsewhere. It transmits nothing, so the row must say so AT
        WRITE TIME — not only after a later census sweep."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        response = client.post(
            f"/applications/{app_id}/submit",
            json={"applied_url": "https://careers.example.com/apply"},
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text
        row = _truth_row(db_session, app_id)
        assert row["status"] == "submitted"
        assert row["transmittedAt"] is None
        assert row["submissionTruthState"] == "recorded_not_transmitted"
        assert row["submissionTruthAt"] is not None
        assert response.json()["submissionTruthState"] == "recorded_not_transmitted"

    def test_jobs_apply_bookkeeping_stamps_the_same_marker(
        self, db_session, user_id, client, auth_headers
    ):
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        response = client.post(f"/jobs/{job_id}/apply", json={}, headers=auth_headers)

        assert response.status_code in (200, 201), response.text
        row = _truth_row(db_session, app_id)
        assert row["status"] == "submitted"
        assert row["transmittedAt"] is None
        assert row["submissionTruthState"] == "recorded_not_transmitted"

    def test_the_marker_is_never_stamped_over_transmission_proof(
        self, db_session, user_id
    ):
        """The marker writer must be a one-way door: it can only ever say
        "no proof", and never overwrite a row that HAS proof."""
        from app.db import ensure_application_transmission_columns
        from app.services.submission_truth import mark_recorded_not_transmitted

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )
        ensure_application_transmission_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "transmittedAt" = NOW() WHERE "id" = %s',
                (app_id,),
            )
        db_session.commit()

        stamped = mark_recorded_not_transmitted(user_id, app_id)

        assert stamped is False
        assert _truth_row(db_session, app_id)["submissionTruthState"] is None

    def test_the_marker_is_idempotent(self, db_session, user_id):
        from app.services.submission_truth import mark_recorded_not_transmitted

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )

        assert mark_recorded_not_transmitted(user_id, app_id) is True
        first = _truth_row(db_session, app_id)["submissionTruthAt"]
        assert mark_recorded_not_transmitted(user_id, app_id) is False
        assert _truth_row(db_session, app_id)["submissionTruthAt"] == first

    def test_the_census_predicate_becomes_self_evident(self, db_session, user_id):
        """A marked row is no longer an unexplained false positive: the U5d
        census predicate (``submissionTruthState IS NULL``) stops matching it,
        so "claimed submitted, unexplained" trends to zero for new writes."""
        from app.services.submission_truth import count_unverified_submissions

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )
        assert count_unverified_submissions(user_id) == 1

        from app.services.submission_truth import mark_recorded_not_transmitted

        mark_recorded_not_transmitted(user_id, app_id)

        assert count_unverified_submissions(user_id) == 0
