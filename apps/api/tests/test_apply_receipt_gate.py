"""Live site apply cannot stamp transmittedAt without a Gmail receipt."""
from __future__ import annotations

import base64
import json

import pytest

from app.db import get_connection, new_id
from app.repositories.approval import ApprovalRepository
from app.services.apply_executor import (
    MANUAL_STEP_FORM_NOT_READY,
    RETRYABLE_MANUAL_REASONS,
    ManualStepRequired,
    execute_site_application,
    playwright_form_submitter,
)
from app.services.apply_form_grounding import build_form_llm_resolver
from app.services.apply_receipt_inbox import (
    MANUAL_STEP_AWAITING_RECEIPT,
    MANUAL_STEP_RECEIPT_GMAIL_UNAVAILABLE,
    ReceiptMailboxUnavailable,
)
from app.services.llm_client import QuotaExhaustedError


SIMPLE_FORM = """
<form class="ashby-application-form">
  <label>Name <input name="_systemfield_name" required></label>
  <label>Email <input name="_systemfield_email" type="email" required></label>
  <label>Resume <input name="_systemfield_resume" type="file" required></label>
  <button type="submit">Submit</button>
</form>
"""

#: SIMPLE_FORM plus ONE free-text employer question the profile/answer-bank
#: cannot resolve — the same shape as the ``apply_form`` prompt-class field
#: that hit the Anthropic 429 in the production incident this file's
#: ``test_live_apply_llm_429_is_retryable_not_unknown_required_question``
#: reproduces. "Notice period" is deliberately non-sensitive (unlike visa/
#: pronouns/criminal/gender) so the only reason it stays unanswered is the
#: LLM outage, never the sensitivity gate.
FORM_WITH_UNKNOWN_REQUIRED_QUESTION = (
    SIMPLE_FORM
    + """
<div data-field-path="notice_period">
  <label>What is your notice period?</label>
  <input name="notice_period_input" required>
</div>
"""
)

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


def test_live_apply_llm_429_is_retryable_not_unknown_required_question(
    user_id, tmp_path
):
    """Production regression, 2026-08-19T14:59Z, ``apply_sweep_user`` job
    ``882acebed50d406ea9c9078adb46e013``: the live completer behind
    ``apply_form_grounding.grounded_answer_from_model``/``_live_completer``
    hit an Anthropic HTTP 429 (``QuotaExhaustedError``, prompt class
    ``apply_form``). The sweep parked the application on
    ``unknown_required_question`` — a reason that is NOT in
    ``RETRYABLE_MANUAL_REASONS`` — for a question the candidate never
    actually needed to answer; the LLM being temporarily out of quota is not
    "the employer asked something we have no answer for".

    This is the site-apply path itself (``execute_site_application``, static
    pre-flight branch — ``page_html`` is non-empty, exactly like a captured
    DOM would be), not just the grounding module in isolation: the submitter
    must never even be reached, because the manual step has to come from the
    pre-flight plan build, before any browser opens.
    """

    def raising_completer(question: str, evidence: str):
        raise QuotaExhaustedError(
            "anthropic", reason="anthropic subscription quota exhausted"
        )

    llm_resolver = build_form_llm_resolver(
        user_id, PROFILE, company="Acme", completer=raising_completer
    )

    def _forbidden_submitter(**_kwargs):
        raise AssertionError(
            "the browser must never open once the static pre-flight plan "
            "has already raised a manual step"
        )

    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _approve(user_id, app_id, job_id)

    with pytest.raises(ManualStepRequired) as exc:
        execute_site_application(
            user_id,
            app_id,
            approval_id,
            page_html=FORM_WITH_UNKNOWN_REQUIRED_QUESTION,
            channel="ashby",
            profile=PROFILE,
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            apply_url=LIVE_URL,
            submitter=_forbidden_submitter,
            form_llm=llm_resolver,
            company="Acme",
            job_title="Staff Engineer",
        )
    assert exc.value.reason != "unknown_required_question", (
        "an LLM 429 outage must never be recorded as 'no stored answer for "
        f"this question' — got {exc.value.reason!r}"
    )
    assert exc.value.reason in RETRYABLE_MANUAL_REASONS
    assert exc.value.reason == MANUAL_STEP_FORM_NOT_READY
    transmitted_at, _ref, reason, _site_at, status = _row(app_id)
    assert transmitted_at is None
    assert reason == MANUAL_STEP_FORM_NOT_READY
    assert status == "draft"


def _data_url(html: str) -> str:
    """Serve a fixture ATS page as a synthetic ``data:`` URL — the same
    fixture-serving convention ``test_cli_sub005_fill_commit.py`` uses to
    drive the real ``playwright_form_submitter`` in a headless Chromium:
    zero network egress, never a real employer.
    """
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


def test_live_apply_llm_429_is_retryable_not_unknown_required_question_live_rebuild(
    tmp_path,
):
    """Independent-reviewer FAIL (wave ``liveapply429live``, 2026-08-19): the
    sibling test above,
    ``test_live_apply_llm_429_is_retryable_not_unknown_required_question``,
    only drives ``execute_site_application``'s STATIC pre-flight branch —
    reached only when ``page_html`` is non-empty (a captured DOM). Production
    ``apply_sweep_user`` ALWAYS calls ``execute_site_application`` with
    ``page_html=""`` (see that function's own docstring: "Production,
    2026-08-19T14:59Z, apply_sweep_user job
    882acebed50d406ea9c9078adb46e013"), which skips the static branch
    entirely — its one real Playwright session builds the plan itself from
    the LIVE DOM after a single ``page.goto`` (``rebuild_plan=live`` in
    ``execute_site_application``, which forwards straight into
    ``playwright_form_submitter``'s own ``rebuild_plan`` branch). That branch
    was never exercised by the static-only sibling test.

    This drives THAT branch directly — the exact call site production takes
    — with the SAME 429-raising completer and the SAME notice-period
    question the profile/answer-bank cannot resolve, but through
    ``playwright_form_submitter`` itself with ``page_html=""`` and
    ``rebuild_plan=True``, against the SAME ``FORM_WITH_UNKNOWN_REQUIRED_
    QUESTION`` fixture served as a synthetic ``data:`` URL (a real headless
    Chromium, zero network, zero real employer — the same convention as
    ``test_cli_sub005_fill_commit.py``'s ``_data_url`` fixtures).

    ``build_form_fill_plan`` (which raises the ``QuotaExhaustedError`` ->
    ``ManualStepRequired`` translation) is called for the live rebuild
    strictly after ``page.goto``/``wait_for_application_form`` and strictly
    BEFORE any fill or submit logic runs — ``_run_fill_plan``/
    ``_activate_submit`` sit much further down the same function, after the
    hCaptcha check, after the fill/verify loop, after the pre-submit
    convergence gate. A ``ManualStepRequired`` raised this early is therefore
    a structural guarantee the submit control was never reached, let alone
    clicked as a successful send — not merely an assertion about a return
    value the function never gets to produce. As a second, independent
    signal of the same thing: nothing here ever calls ``page.screenshot``
    (every screenshot in this function belongs to a LATER branch — hCaptcha,
    a blocked required field, a blocked submission, a post-submit
    classification), so no confirmation evidence file exists afterwards
    either.
    """

    def raising_completer(question: str, evidence: str):
        raise QuotaExhaustedError(
            "anthropic", reason="anthropic subscription quota exhausted"
        )

    llm_resolver = build_form_llm_resolver(
        "live-rebuild-user", PROFILE, company="Acme", completer=raising_completer
    )

    with pytest.raises(ManualStepRequired) as exc:
        playwright_form_submitter(
            application_id="live-429-rebuild",
            channel="ashby",
            page_html="",
            apply_url=_data_url(FORM_WITH_UNKNOWN_REQUIRED_QUESTION),
            plan={"fields": []},
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile=PROFILE,
            rebuild_plan=True,
            form_llm=llm_resolver,
        )
    err = exc.value
    assert err.reason != "unknown_required_question", (
        "an LLM 429 outage hit during the LIVE DOM rebuild must never be "
        f"recorded as 'no stored answer for this question' — got {err.reason!r}"
    )
    assert err.reason in RETRYABLE_MANUAL_REASONS
    assert err.reason == MANUAL_STEP_FORM_NOT_READY
    # No submit-adjacent evidence was ever produced — the raise happened
    # before any code path that would screenshot the page.
    assert list(tmp_path.glob("*")) == []


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
