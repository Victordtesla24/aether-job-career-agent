"""Live apply: wait for the real form, click Apply, press Ashby's Submit.

Production evidence (Xero Engineering Manager - Data, Ashby,
``c4b45905451434f02b9f3a76d``, 2026-08-18T16:22Z): the executor navigated,
slept ~2s, screenshotted "Fetching application form", and recorded
``submit_control_not_found``. The form's submit control is
``button.ashby-application-form-submit-button`` with no ``type="submit"``.
A later sweep never retried because ``manualStepReason`` is treated as
terminal. These tests pin the opposite: wait until the form exists, find
Ashby's button, retry a "button not found" miss, and keep a submitted-but-
not-transmitted card eligible.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Iterator

import pytest

from app.db import (
    ensure_application_manual_step_columns,
    ensure_application_transmission_columns,
    new_id,
)
from app.repositories.approval import ApprovalRepository
from app.services.apply_executor import (
    ApplyExecutorTransportError,
    _activate_submit,
    playwright_form_submitter,
)
from app.workers.apply_sweep import pending_transmissions, users_with_pending_transmissions


def _data_url(html: str) -> str:
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


@pytest.fixture
def open_page() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as runner:
        browser = runner.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:

            def _open(html: str) -> Any:
                page = browser.new_page()
                page.route("**/*", lambda route: route.abort())
                page.set_content(html, wait_until="domcontentloaded")
                return page

            yield _open
        finally:
            browser.close()


_ASHBY_SUBMIT_NO_TYPE = """
<title>Xero</title>
<form class="ashby-application-form">
  <label for="email">Email</label>
  <input id="email" name="email" type="email">
  <button class="ashby-application-form-submit-button">Submit Application</button>
</form>
"""

_DELAYED_ASHBY_FORM = """
<title>Xero</title>
<p id="status">Fetching application form</p>
<div id="root"></div>
<script>
setTimeout(function () {
  var status = document.getElementById("status");
  if (status) status.remove();
  document.getElementById("root").innerHTML =
    '<form class="ashby-application-form">' +
    '<label for="email">Email</label>' +
    '<input id="email" name="email" type="email">' +
    '<button class="ashby-application-form-submit-button">Submit Application</button>' +
    "</form>";
  var btn = document.querySelector(".ashby-application-form-submit-button");
  btn.addEventListener("click", function (event) {
    event.preventDefault();
    document.body.innerHTML =
      "<p>Thank you for submitting your application to Xero.</p>";
  });
}, 3500);
</script>
"""

_APPLY_CTA_THEN_FORM = """
<title>Careers</title>
<button id="apply" type="button">Apply for this job</button>
<div id="root"></div>
<script>
document.getElementById("apply").addEventListener("click", function () {
  this.remove();
  document.getElementById("root").innerHTML =
    '<form>' +
    '<label for="email">Email</label>' +
    '<input id="email" name="email" type="email">' +
    '<button type="submit">Submit Application</button>' +
    "</form>";
  document.querySelector("form").addEventListener("submit", function (event) {
    event.preventDefault();
    document.body.innerHTML =
      "<p>Thank you for submitting your application to Acme.</p>";
  });
});
</script>
"""


def _email_plan() -> dict[str, Any]:
    return {
        "fields": [
            {
                "name": "email",
                "label": "Email",
                "kind": "email",
                "required": True,
                "scope": "",
                "value": "sarkar.vikram@gmail.com",
                "options": [],
            }
        ]
    }


def _submit(html: str, tmp_path: Any, application_id: str) -> dict[str, Any]:
    return playwright_form_submitter(
        application_id=application_id,
        channel="ashby",
        page_html="",
        apply_url=_data_url(html),
        plan=_email_plan(),
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
        profile={"email": "sarkar.vikram@gmail.com"},
    )


def test_ashby_submit_button_without_type_submit_is_clicked(open_page: Any) -> None:
    """Ashby's live control has no type=submit; CSS button[type=submit] misses it."""
    page = open_page(_ASHBY_SUBMIT_NO_TYPE)
    activation = _activate_submit(page)
    assert activation.clicked is True
    assert activation.present is True
    assert activation.enabled is True
    assert activation.selector is not None
    assert "ashby-application-form-submit-button" in activation.selector


def test_delayed_fetching_form_is_waited_for_then_submitted(tmp_path: Any) -> None:
    """The Xero failure mode: spinner for >2s, then a real Ashby form."""
    outcome = _submit(_DELAYED_ASHBY_FORM, tmp_path, "live-wait-xero")
    assert outcome["submitted"] is True
    assert outcome.get("confirmation")
    assert "thank you" in (outcome.get("confirmation") or "").lower()


def test_apply_for_this_job_cta_is_clicked_before_fill(tmp_path: Any) -> None:
    """A human clicks Apply for this job; Aether must too, then submit."""
    outcome = _submit(_APPLY_CTA_THEN_FORM, tmp_path, "live-cta-apply")
    assert outcome["submitted"] is True
    assert outcome.get("confirmation")


def test_fetching_shell_times_out_as_form_not_ready(open_page: Any) -> None:
    """An empty SPA shell is a retryable transport miss, not a terminal 'no button'."""
    from app.services.apply_executor import wait_for_application_form

    page = open_page("<title>empty</title><p>Fetching application form</p>")
    with pytest.raises(ApplyExecutorTransportError) as exc_info:
        wait_for_application_form(page, live=True, timeout_ms=1500)
    assert exc_info.value.reason == "form_not_ready"


def _seed_approved_site_apply(conn, user_id: str, *, auto_apply: bool = True) -> str:
    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    job_id = new_id()
    resume_id = new_id()
    app_id = new_id()
    with conn.cursor() as cur:
        if auto_apply:
            cur.execute(
                'UPDATE "User" SET "agentConfig" = %s WHERE "id" = %s',
                (json.dumps({"autoApply": True, "approvalGate": True, "matchThreshold": 60}), user_id),
            )
        cur.execute(
            '''INSERT INTO "Job"
               ("id","userId","title","company","location","remote","description",
                "requirements","source","sourceUrl","fitScore","updatedAt")
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
            (
                job_id, user_id, "Engineering Manager - Data", "Xero", "Sydney NSW",
                False, "Build things.", json.dumps([]), "ashby",
                f"https://jobs.ashbyhq.com/xero/{job_id}/application",
                64.46,
            ),
        )
        cur.execute(
            '''INSERT INTO "Resume"
               ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
               VALUES (%s,%s,1,%s,%s,%s,NOW())''',
            (resume_id, user_id, json.dumps({"raw_text": "cv"}), "hash", job_id),
        )
        cur.execute(
            '''INSERT INTO "Application"
               ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
               VALUES (%s,%s,%s,%s,'submitted'::"ApplicationStatus",%s,NOW(),NOW())''',
            (app_id, user_id, job_id, resume_id, "Dear Xero,"),
        )
    conn.commit()
    approval = ApprovalRepository().create(
        user_id,
        "application_submit",
        {"kind": "site_apply", "job_id": job_id, "application_id": app_id},
        application_id=app_id,
    )
    ApprovalRepository().approve(approval["id"], user_id)
    return app_id


def test_submit_control_not_found_stays_in_the_sweep_queue(db_session, user_id) -> None:
    """The Xero card was excluded forever after one miss. It must be retried."""
    app_id = _seed_approved_site_apply(db_session, user_id)
    with db_session.cursor() as cur:
        cur.execute(
            '''UPDATE "Application"
               SET "manualStepReason" = %s, "manualStepDetail" = %s, "manualStepAt" = NOW()
               WHERE "id" = %s''',
            (
                "submit_control_not_found",
                "Could not find the form's submit control.",
                app_id,
            ),
        )
    db_session.commit()

    queued = pending_transmissions(user_id)
    assert any(row["applicationId"] == app_id for row in queued), (
        "a submit_control_not_found miss must remain sweep-eligible — it is "
        "a failed click, not a finished application"
    )
    assert user_id in users_with_pending_transmissions()


def test_unknown_required_question_is_not_silently_retried(db_session, user_id) -> None:
    """A real unanswered question stays terminal until the user answers it."""
    app_id = _seed_approved_site_apply(db_session, user_id)
    with db_session.cursor() as cur:
        cur.execute(
            '''UPDATE "Application"
               SET "manualStepReason" = %s, "manualStepAt" = NOW()
               WHERE "id" = %s''',
            ("unknown_required_question", app_id),
        )
    db_session.commit()
    queued = pending_transmissions(user_id)
    assert all(row["applicationId"] != app_id for row in queued)


def test_submission_agent_selects_submitted_not_transmitted(db_session, user_id) -> None:
    """Tracker 'Submitted' with no transmittedAt is still this agent's job."""
    from app.agents.submission_agent import SubmissionAgent

    app_id = _seed_approved_site_apply(db_session, user_id)
    with db_session.cursor() as cur:
        cur.execute(
            '''UPDATE "Application"
               SET "manualStepReason" = %s, "manualStepAt" = NOW()
               WHERE "id" = %s''',
            ("submit_control_not_found", app_id),
        )
    db_session.commit()

    result = SubmissionAgent().run(user_id)
    assert result.applicationId == app_id
    assert result.reason != "nothing_ready"
    assert result.reason != "already_recorded"
    assert result.transmitted is False
    assert "Submitted your application" not in result.message
    assert result.submissionState in {"awaiting_approval", "manual_step_required"}
    if result.submissionState == "manual_step_required":
        pytest.fail(
            "submitted-not-transmitted with a retryable miss must be re-queued "
            "for the sweep, not reported as a finished manual step"
        )
    assert result.submissionState == "awaiting_approval"
    assert result.approvalId
