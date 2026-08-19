"""Live site apply cannot stamp transmittedAt without a Gmail receipt."""
from __future__ import annotations

import json

import pytest

from app.db import get_connection, new_id
from app.repositories.approval import ApprovalRepository
from app.services.apply_executor import ManualStepRequired, execute_site_application
from app.services.apply_receipt_inbox import (
    MANUAL_STEP_AWAITING_RECEIPT,
    MANUAL_STEP_RECEIPT_GMAIL_UNAVAILABLE,
    ReceiptMailboxUnavailable,
)


SIMPLE_FORM = """
<form class="ashby-application-form">
  <label>Name <input name="_systemfield_name" required></label>
  <label>Email <input name="_systemfield_email" type="email" required></label>
  <label>Resume <input name="_systemfield_resume" type="file" required></label>
  <button type="submit">Submit</button>
</form>
"""

PROFILE = {
    "name": "Jordan Blake",
    "email": "jordan.blake@example.com",
    "phone": "+61 400 000 000",
    "location": "Melbourne VIC",
}

LIVE_URL = "https://jobs.ashbyhq.com/acme/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/application"


@pytest.fixture()
def user_id(client, auth_headers) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "id" FROM "User" LIMIT 1')
            return cur.fetchone()[0]


def _seed(user_id: str) -> tuple[str, str, str]:
    job_id = new_id()
    resume_id = new_id()
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Staff Engineer", "Acme", "Melbourne VIC", False,
                    "Build things.", json.dumps([]), "ashby", LIVE_URL, 72.0,
                ),
            )
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
                   VALUES (%s,%s,1,%s,%s,%s,NOW())''',
                (resume_id, user_id, json.dumps({"raw_text": "Jordan Blake."}), "hash", job_id),
            )
            cur.execute(
                '''INSERT INTO "Application"
                   ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
                   VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
                (app_id, user_id, job_id, resume_id, "Dear Hiring Manager,"),
            )
        conn.commit()
    return job_id, resume_id, app_id


def _approve(user_id: str, app_id: str, job_id: str) -> str:
    """Approve a SITE-APPLY card using the SAME payload shape
    ``application_submission.queue_submission_approval`` actually writes
    (``kind: "submission"``, a channel in ``AUTOMATABLE_CHANNELS``, no
    ``recipient``) — the shape ``is_site_apply_payload`` checks for.

    ``ApprovalRepository._sync_application`` promotes ``Application.status``
    to ``submitted`` on approval UNLESS the payload matches
    ``is_site_apply_payload`` — a legacy ``{"kind": "site_apply"}`` payload
    does not match it, so approving one flips status to ``submitted``
    immediately, before the browser ever opens the employer's page. Using
    the real shape here is what keeps ``status`` at ``draft`` until
    ``apply_executor._record_site_transmission`` legitimately promotes it —
    exactly the U5d-2 guarantee this receipt gate depends on.
    """
    approval = ApprovalRepository().create(
        user_id,
        "application_submit",
        {
            "kind": "submission",
            "job_id": job_id,
            "application_id": app_id,
            "channel": "ashby",
            "apply_url": LIVE_URL,
        },
        application_id=app_id,
    )
    ApprovalRepository().approve(approval["id"], user_id)
    return approval["id"]


def _row(app_id: str) -> tuple:
    from app.db import (
        ensure_application_site_submitted_column,
        ensure_application_transmission_columns,
    )

    ensure_application_transmission_columns()
    ensure_application_site_submitted_column()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "transmittedAt", "transmissionRef", "manualStepReason", '
                '"siteSubmittedAt", "status"::text FROM "Application" WHERE "id" = %s',
                (app_id,),
            )
            return cur.fetchone()


def _live_submitter(**kwargs):
    return {
        "submitted": True,
        "confirmation": "Thanks for applying",
        "classification": "confirmed",
        "submitControl": {"clicked": True, "present": True, "enabled": True},
        "evidencePath": str(kwargs.get("evidence_dir") or "/tmp") + "/shot.png",
        "destination": LIVE_URL,
        "filled": ["_systemfield_name"],
        "unfilled": [],
        "unplannedFilled": [],
        "mode": "live",
        "plan": {"fields": [], "answerBankAudit": []},
        "submittedAt": 1_700_000_010.0,
    }


def test_live_confirmed_page_without_gmail_receipt_is_not_submitted(user_id, tmp_path):
    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _approve(user_id, app_id, job_id)

    with pytest.raises(ManualStepRequired) as exc:
        execute_site_application(
            user_id,
            app_id,
            approval_id,
            page_html=SIMPLE_FORM,
            channel="ashby",
            profile=PROFILE,
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            apply_url=LIVE_URL,
        submitter=_live_submitter,
        receipt_poller=lambda *_a, **_k: None,
        company="Acme",
        job_title="Staff Engineer",
    )
    assert exc.value.reason == MANUAL_STEP_AWAITING_RECEIPT
    transmitted_at, _ref, reason, site_at, status = _row(app_id)
    assert transmitted_at is None
    assert reason == MANUAL_STEP_AWAITING_RECEIPT
    assert site_at is not None
    assert status == "draft"


def test_live_receipt_mailbox_unavailable_is_not_submitted(user_id, tmp_path):
    """A revoked/missing Gmail grant is an honest obstacle, never a stamp.

    Waiting cannot fix a mailbox Aether has no grant to read, so the poller
    raises ``ReceiptMailboxUnavailable`` instead of returning ``None``. The
    row must land on ``receipt_gmail_unavailable`` — a DIFFERENT reason from
    the plain ``awaiting_receipt`` timeout — and ``transmittedAt`` must still
    be untouched.
    """
    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _approve(user_id, app_id, job_id)

    def _unavailable_poller(*_a, **_k):
        raise ReceiptMailboxUnavailable("Gmail is not connected")

    with pytest.raises(ManualStepRequired) as exc:
        execute_site_application(
            user_id,
            app_id,
            approval_id,
            page_html=SIMPLE_FORM,
            channel="ashby",
            profile=PROFILE,
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            apply_url=LIVE_URL,
            submitter=_live_submitter,
            receipt_poller=_unavailable_poller,
            company="Acme",
            job_title="Staff Engineer",
        )
    assert exc.value.reason == MANUAL_STEP_RECEIPT_GMAIL_UNAVAILABLE
    transmitted_at, _ref, reason, site_at, status = _row(app_id)
    assert transmitted_at is None
    assert reason == MANUAL_STEP_RECEIPT_GMAIL_UNAVAILABLE
    assert site_at is not None
    assert status == "draft"


def test_live_gmail_receipt_stamps_transmitted_at(user_id, tmp_path):
    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _approve(user_id, app_id, job_id)

    result = execute_site_application(
        user_id,
        app_id,
        approval_id,
        page_html=SIMPLE_FORM,
        channel="ashby",
        profile=PROFILE,
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
        apply_url=LIVE_URL,
        submitter=_live_submitter,
        receipt_poller=lambda *_a, **_k: {
            "messageId": "gmail-receipt-1",
            "from": "notifications@ashbyhq.com",
            "subject": "Thank you for applying to Staff Engineer at Acme",
        },
        company="Acme",
        job_title="Staff Engineer",
    )
    assert result["transmitted"] is True
    transmitted_at, ref, reason, _site_at, status = _row(app_id)
    assert transmitted_at is not None
    assert "gmail:gmail-receipt-1" in (ref or ""), (
        "transmissionRef must carry the literal gmail:<messageId> receipt "
        f"marker, not just the id — got {ref!r}"
    )
    assert reason is None
    assert status == "submitted"


def test_replay_without_a_receipt_poller_still_records_a_local_page(user_id, tmp_path):
    """Replay never opened an employer URL — the existing fixture contract stays."""
    from app.services.apply_executor import POST_SUBMIT_CONFIRMED

    def replay_submitter(**kwargs):
        return {
            "submitted": True,
            "confirmation": "Thanks for applying",
            "classification": POST_SUBMIT_CONFIRMED,
            "submitControl": {"clicked": True, "present": True, "enabled": True},
            "evidencePath": str(tmp_path / "replay.png"),
            "destination": "replay",
            "filled": ["_systemfield_name"],
            "unfilled": [],
            "unplannedFilled": [],
            "mode": "replay",
        }

    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _approve(user_id, app_id, job_id)
    result = execute_site_application(
        user_id,
        app_id,
        approval_id,
        page_html=SIMPLE_FORM,
        channel="ashby",
        profile=PROFILE,
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
        submitter=replay_submitter,
    )
    assert result["transmitted"] is True
    transmitted_at, _ref, reason, _site, status = _row(app_id)
    assert transmitted_at is not None
    assert reason is None
    assert status == "submitted"


def test_finish_pending_receipt_polls_gmail_and_does_not_open_a_browser(
    user_id, monkeypatch
):
    from app.db import ensure_application_site_submitted_column
    from app.services.apply_executor import finish_pending_receipt

    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _approve(user_id, app_id, job_id)
    ensure_application_site_submitted_column()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "siteSubmittedAt" = NOW(), '
                '"manualStepReason" = %s WHERE "id" = %s',
                (MANUAL_STEP_AWAITING_RECEIPT, app_id),
            )
        conn.commit()

    def _forbidden(*_a, **_k):
        raise AssertionError("browser must not reopen after the site submit")

    # fetch_apply_page lives on apply_executor (apply_sweep only ever
    # imports it locally, inside _attempt_transmission) — patching it there
    # is what actually guards against finish_pending_receipt reopening the
    # employer's page.
    monkeypatch.setattr(
        "app.services.apply_executor.fetch_apply_page", _forbidden
    )
    monkeypatch.setattr(
        "app.services.apply_executor.playwright_form_submitter", _forbidden
    )

    finish_pending_receipt(
        user_id,
        app_id,
        approval_id,
        company="Acme",
        job_title="Staff Engineer",
        receipt_poller=lambda *_a, **_k: {
            "messageId": "gmail-later",
            "from": "notifications@ashbyhq.com",
            "subject": "Thank you for applying to Staff Engineer at Acme",
        },
    )
    transmitted_at, ref, reason, _site, status = _row(app_id)
    assert transmitted_at is not None
    assert "gmail:gmail-later" in (ref or ""), (
        "transmissionRef must carry the literal gmail:<messageId> receipt "
        f"marker, not just the id — got {ref!r}"
    )
    assert reason is None
    assert status == "submitted"
