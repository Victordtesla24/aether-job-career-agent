"""U5b — apply-executor service contract for Ashby + Greenhouse (failing
tests, written before implementation).

Fixtures (see ``fixtures/apply_pages/README.md`` for full provenance):

  - ``ashby_application_real.html`` -- REAL rendered DOM (Playwright,
    2026-08-13) of https://jobs.ashbyhq.com/xero/<uuid>/application, a
    live production posting whose URL shape matches 102/512 stored
    Applications (the scout's domain histogram). Confirmed real fields:
    ``_systemfield_name``/``_systemfield_email``/``_systemfield_resume``
    (required), a required ``tel`` field labeled "Phone Number", a
    REQUIRED custom Yes/No question labeled "Flexible Working" (field id
    ``f640164d-eb74-4d28-9138-34363365f514``) that has no standard-profile
    analogue, and a ``g-recaptcha-response`` widget.
  - ``greenhouse_embed_application_real.html`` -- REAL rendered DOM of
    https://boards.greenhouse.io/embed/job_app?for=databricks&token=...,
    matching the 99/512 Greenhouse-embedded channel. Confirmed real fields:
    ``first_name``/``last_name``/``email``/``phone``/``resume`` (required),
    a REQUIRED select question_36740801002 "Are you legally authorized to
    work in the country in which you are applying?" (no standard-profile
    analogue in the minimal test profile used below), optional EEO fields
    (aria-required="false"), and a ``g-recaptcha-response`` widget.
  - ``captcha_challenge_synthetic.html`` / ``login_wall_synthetic.html`` --
    explicitly SYNTHETIC (see README) minimal reproductions of documented
    reCAPTCHA-v2-challenge and login-gate DOM shapes, used ONLY to pin the
    executor's *detection* contract.

WHAT DOES NOT EXIST YET (confirmed by grep, 2026-08-13): no
``apps/api/app/services/apply_executor.py``, no ``ManualStepRequired``, no
``Application.manualStepReason``/``manualStepDetail``/``manualStepAt``
columns. Every test below is expected to fail with ImportError or a
missing-column error until U5b is implemented.

CONTRACT under test:

  ``detect_blocking_state(html: str) -> str | None``
    Returns ``"captcha"``, ``"login_wall"``, or ``None``.

  ``build_form_fill_plan(html: str, *, channel: str, profile: dict) -> dict``
    Parses the REAL field schema out of ``html`` and returns
    ``{"fields": [...], "unanswerable_required": [{"name","label"}]}``.
    Raises ``ManualStepRequired`` (reason="captcha"/"login_wall") BEFORE
    attempting to build a plan if ``detect_blocking_state`` is not None.

  ``execute_site_application(user_id, application_id, approval_id, *,
  page_html, channel, profile, resume_pdf_bytes, cover_letter_text,
  evidence_dir) -> dict``
    1. Loads the ``ApprovalRequest`` for ``approval_id``/``user_id``.
       Missing -> ``ApplyExecutorGuardError(reason="approval_not_found",
       http_status=404)``. Not ``status == "approved"`` ->
       ``ApplyExecutorGuardError(reason="not_approved", http_status=409)``.
    2. Atomically claims execution via the EXISTING
       ``ApprovalRepository.claim_execution`` (reused, not reimplemented) --
       a lost claim -> ``ApplyExecutorGuardError(reason="already_executed",
       http_status=409)``.
    3. ``build_form_fill_plan`` -- any REQUIRED field with no answer in
       ``profile`` raises ``ManualStepRequired`` with the REAL question
       label attached; a CAPTCHA/login-wall raises ``ManualStepRequired``
       too. Either way this function persists the reason + question text
       onto the ``Application`` row (``manualStepReason``,
       ``manualStepDetail``, ``manualStepAt``) and releases the execution
       claim (a fixed profile / a retried attempt must not find the
       approval permanently burnt) before re-raising.
    4. On success: stamps ``Application.transmittedAt``,
       ``transmissionChannel`` (= ``channel``), and a ``transmissionRef``
       carrying the evidence screenshot path; calls
       ``ApprovalRepository.complete_execution``; returns a summary dict
       including ``"evidencePath"``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db import get_connection, new_id
from app.repositories.approval import ApprovalRepository

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "apply_pages"


def _read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


ASHBY_HTML = _read_fixture("ashby_application_real.html")
GREENHOUSE_HTML = _read_fixture("greenhouse_embed_application_real.html")
CAPTCHA_HTML = _read_fixture("captcha_challenge_synthetic.html")
LOGIN_WALL_HTML = _read_fixture("login_wall_synthetic.html")

#: A profile that answers every STANDARD field (name/email/phone) but
#: deliberately carries nothing that could answer either fixture's
#: employer-specific required custom question ("Flexible Working" on Ashby;
#: work-authorization on Greenhouse) -- this is what makes those two
#: questions genuinely UNKNOWN rather than merely unmapped.
MINIMAL_PROFILE = {
    "name": "Jordan Blake",
    "email": "jordan.blake@example.com",
    "phone": "+61 400 000 000",
    "location": "Sydney NSW",
}

#: Same profile, PLUS explicit answers for the two fixtures' real required
#: custom questions, keyed by the REAL field id/name captured in the
#: fixture -- used for the success-path tests.
FULL_PROFILE_ASHBY = {
    **MINIMAL_PROFILE,
    "customAnswers": {"f640164d-eb74-4d28-9138-34363365f514": "Yes"},
}
FULL_PROFILE_GREENHOUSE = {
    **MINIMAL_PROFILE,
    "customAnswers": {"question_36740801002": "Yes"},
}


@pytest.fixture()
def user_id(client, auth_headers) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "id" FROM "User" LIMIT 1')
            return cur.fetchone()[0]


def _make_job(user_id: str, *, source: str = "ashby") -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Senior Engineer", "Xero", "Sydney NSW", False,
                    "Build things.", json.dumps([]), source,
                    f"https://jobs.ashbyhq.com/xero/{job_id}/application", 78.0,
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
                (resume_id, user_id, json.dumps({"raw_text": "Jordan Blake."}), "hash", source_job_id),
            )
        conn.commit()
    return resume_id


def _make_application(user_id: str, job_id: str, resume_id: str) -> str:
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Application"
                   ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
                   VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
                (app_id, user_id, job_id, resume_id, "Dear Hiring Manager,\n\nExcited to apply.\n\nJordan"),
            )
        conn.commit()
    return app_id


def _seed(user_id: str, *, source: str = "ashby") -> tuple[str, str, str]:
    job_id = _make_job(user_id, source=source)
    resume_id = _make_resume(user_id, source_job_id=job_id)
    app_id = _make_application(user_id, job_id, resume_id)
    return job_id, resume_id, app_id


def _make_approval(user_id: str, app_id: str, job_id: str, *, status: str = "pending") -> str:
    approval = ApprovalRepository().create(
        user_id,
        "application_submit",
        {"kind": "site_apply", "job_id": job_id, "application_id": app_id},
        application_id=app_id,
    )
    if status == "approved":
        ApprovalRepository().approve(approval["id"], user_id)
    elif status == "rejected":
        ApprovalRepository().reject(approval["id"], user_id)
    return approval["id"]


# ---------------------------------------------------------------------------
# 1. Blocking-state detection (CAPTCHA / login-wall).
# ---------------------------------------------------------------------------


class TestBlockingStateDetection:
    def test_captcha_challenge_is_detected(self):
        from app.services.apply_executor import detect_blocking_state

        assert detect_blocking_state(CAPTCHA_HTML) == "captcha"

    def test_login_wall_is_detected(self):
        from app.services.apply_executor import detect_blocking_state

        assert detect_blocking_state(LOGIN_WALL_HTML) == "login_wall"

    def test_normal_ashby_form_is_not_flagged_as_blocking(self):
        """The real Ashby fixture DOES mount an invisible g-recaptcha widget
        (routine anti-spam, present on almost every modern form) -- that
        must NOT by itself trip the blocking-state detector, only an actual
        triggered CHALLENGE (a visible challenge iframe) should."""
        from app.services.apply_executor import detect_blocking_state

        assert detect_blocking_state(ASHBY_HTML) is None

    def test_normal_greenhouse_form_is_not_flagged_as_blocking(self):
        from app.services.apply_executor import detect_blocking_state

        assert detect_blocking_state(GREENHOUSE_HTML) is None


# ---------------------------------------------------------------------------
# 2. Form-fill plan built from the REAL field schema.
# ---------------------------------------------------------------------------


class TestFormFillPlanFromRealSchema:
    def test_ashby_plan_finds_the_real_required_system_fields(self):
        from app.services.apply_executor import build_form_fill_plan

        plan = build_form_fill_plan(ASHBY_HTML, channel="ashby", profile=FULL_PROFILE_ASHBY)
        names = {f["name"] for f in plan["fields"] if f["required"]}
        assert "_systemfield_name" in names
        assert "_systemfield_email" in names
        assert "_systemfield_resume" in names

    def test_ashby_unknown_required_question_raises_manual_step_with_real_label(self):
        """The real fixture's REQUIRED custom question is labeled "Flexible
        Working" (field id f640164d-...) -- an employer-specific question no
        generic profile can honestly answer. MINIMAL_PROFILE carries no
        answer for it, so this MUST raise rather than fabricate a Yes/No."""
        from app.services.apply_executor import ManualStepRequired, build_form_fill_plan

        with pytest.raises(ManualStepRequired) as exc_info:
            build_form_fill_plan(ASHBY_HTML, channel="ashby", profile=MINIMAL_PROFILE)
        err = exc_info.value
        assert err.reason == "unknown_required_question"
        assert err.question is not None and "Flexible Working" in err.question

    def test_ashby_plan_succeeds_when_the_custom_question_is_answered(self):
        from app.services.apply_executor import build_form_fill_plan

        plan = build_form_fill_plan(ASHBY_HTML, channel="ashby", profile=FULL_PROFILE_ASHBY)
        assert plan["unanswerable_required"] == []

    def test_greenhouse_plan_finds_the_real_required_fields(self):
        from app.services.apply_executor import build_form_fill_plan

        plan = build_form_fill_plan(
            GREENHOUSE_HTML, channel="greenhouse", profile=FULL_PROFILE_GREENHOUSE
        )
        names = {f["name"] for f in plan["fields"] if f["required"]}
        assert {"first_name", "last_name", "email", "phone", "resume"} <= names

    def test_greenhouse_unknown_required_question_raises_manual_step_with_real_label(self):
        """The real fixture's REQUIRED select question_36740801002 is
        labeled "Are you legally authorized to work in the country in which
        you are applying?" -- MINIMAL_PROFILE has no work-authorization
        field, so this MUST raise rather than guess."""
        from app.services.apply_executor import ManualStepRequired, build_form_fill_plan

        with pytest.raises(ManualStepRequired) as exc_info:
            build_form_fill_plan(GREENHOUSE_HTML, channel="greenhouse", profile=MINIMAL_PROFILE)
        err = exc_info.value
        assert err.reason == "unknown_required_question"
        assert err.question is not None and "legally authorized to work" in err.question

    def test_greenhouse_optional_eeo_fields_never_block_the_plan(self):
        """gender/veteran_status/disability_status are real, confirmed
        aria-required="false" in the fixture -- a plan must never treat a
        voluntary self-ID field as a submission blocker."""
        from app.services.apply_executor import build_form_fill_plan

        plan = build_form_fill_plan(
            GREENHOUSE_HTML, channel="greenhouse", profile=FULL_PROFILE_GREENHOUSE
        )
        blocked_names = {f["name"] for f in plan["unanswerable_required"]}
        assert "gender" not in blocked_names
        assert "veteran_status" not in blocked_names
        assert "disability_status" not in blocked_names

    def test_blocking_html_raises_before_building_any_plan(self):
        from app.services.apply_executor import ManualStepRequired, build_form_fill_plan

        with pytest.raises(ManualStepRequired) as exc_info:
            build_form_fill_plan(CAPTCHA_HTML, channel="generic", profile=FULL_PROFILE_ASHBY)
        assert exc_info.value.reason == "captcha"

        with pytest.raises(ManualStepRequired) as exc_info:
            build_form_fill_plan(LOGIN_WALL_HTML, channel="generic", profile=FULL_PROFILE_ASHBY)
        assert exc_info.value.reason == "login_wall"


# ---------------------------------------------------------------------------
# 3. GATE — the executor refuses to run without an approved ApprovalRequest.
# ---------------------------------------------------------------------------


class TestExecutorApprovalGate:
    def test_refuses_without_any_approval(self, client, auth_headers, user_id):
        from app.services.apply_executor import ApplyExecutorGuardError, execute_site_application

        job_id, resume_id, app_id = _seed(user_id)
        with pytest.raises(ApplyExecutorGuardError) as exc_info:
            execute_site_application(
                user_id, app_id, "nonexistent-approval-id",
                page_html=ASHBY_HTML, channel="ashby", profile=FULL_PROFILE_ASHBY,
                resume_pdf_bytes=b"%PDF-1.4 fake", cover_letter_text="Dear Hiring Manager,",
                evidence_dir="/tmp/aether-apply-evidence-test",
            )
        assert exc_info.value.http_status == 404

    def test_refuses_a_still_pending_approval(self, client, auth_headers, user_id):
        """The core gate assertion: an ApprovalRequest that exists but has
        NOT been moved to 'approved' must not let a real transmission
        attempt proceed -- 409, guard, no side effect."""
        from app.services.apply_executor import ApplyExecutorGuardError, execute_site_application

        job_id, resume_id, app_id = _seed(user_id)
        approval_id = _make_approval(user_id, app_id, job_id, status="pending")

        with pytest.raises(ApplyExecutorGuardError) as exc_info:
            execute_site_application(
                user_id, app_id, approval_id,
                page_html=ASHBY_HTML, channel="ashby", profile=FULL_PROFILE_ASHBY,
                resume_pdf_bytes=b"%PDF-1.4 fake", cover_letter_text="Dear Hiring Manager,",
                evidence_dir="/tmp/aether-apply-evidence-test",
            )
        assert exc_info.value.reason == "not_approved"
        assert exc_info.value.http_status == 409

        # No side effect: the application must still read completely untouched.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "transmittedAt", "status" FROM "Application" WHERE "id" = %s',
                    (app_id,),
                )
                transmitted_at, status_ = cur.fetchone()
        assert transmitted_at is None
        assert status_ == "draft"

    def test_refuses_a_rejected_approval(self, client, auth_headers, user_id):
        from app.services.apply_executor import ApplyExecutorGuardError, execute_site_application

        job_id, resume_id, app_id = _seed(user_id)
        approval_id = _make_approval(user_id, app_id, job_id, status="rejected")

        with pytest.raises(ApplyExecutorGuardError) as exc_info:
            execute_site_application(
                user_id, app_id, approval_id,
                page_html=ASHBY_HTML, channel="ashby", profile=FULL_PROFILE_ASHBY,
                resume_pdf_bytes=b"%PDF-1.4 fake", cover_letter_text="Dear Hiring Manager,",
                evidence_dir="/tmp/aether-apply-evidence-test",
            )
        assert exc_info.value.reason == "not_approved"
        assert exc_info.value.http_status == 409

    def test_already_executed_approval_refuses_a_second_run(self, client, auth_headers, user_id):
        """Mirrors the EXISTING W-SUB double-submit guard
        (ApprovalRepository.claim_execution) -- reused here, not
        reimplemented, so a second attempt on an already-claimed approval
        gets an honest 409 and sends nothing a second time."""
        from app.services.apply_executor import ApplyExecutorGuardError, execute_site_application

        job_id, resume_id, app_id = _seed(user_id)
        approval_id = _make_approval(user_id, app_id, job_id, status="approved")
        assert ApprovalRepository().claim_execution(approval_id, user_id) is True

        with pytest.raises(ApplyExecutorGuardError) as exc_info:
            execute_site_application(
                user_id, app_id, approval_id,
                page_html=ASHBY_HTML, channel="ashby", profile=FULL_PROFILE_ASHBY,
                resume_pdf_bytes=b"%PDF-1.4 fake", cover_letter_text="Dear Hiring Manager,",
                evidence_dir="/tmp/aether-apply-evidence-test",
            )
        assert exc_info.value.reason == "already_executed"
        assert exc_info.value.http_status == 409


# ---------------------------------------------------------------------------
# 4. Manual-step outcome: reason + real question text PERSISTED on the row.
# ---------------------------------------------------------------------------


class TestManualStepPersistence:
    def test_unknown_required_question_persists_the_real_question_text(
        self, client, auth_headers, user_id, tmp_path
    ):
        from app.services.apply_executor import ManualStepRequired, execute_site_application

        job_id, resume_id, app_id = _seed(user_id)
        approval_id = _make_approval(user_id, app_id, job_id, status="approved")

        with pytest.raises(ManualStepRequired):
            execute_site_application(
                user_id, app_id, approval_id,
                page_html=ASHBY_HTML, channel="ashby", profile=MINIMAL_PROFILE,
                resume_pdf_bytes=b"%PDF-1.4 fake", cover_letter_text="Dear Hiring Manager,",
                evidence_dir=str(tmp_path),
            )

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "manualStepReason", "manualStepDetail", "transmittedAt" '
                    'FROM "Application" WHERE "id" = %s',
                    (app_id,),
                )
                reason, detail, transmitted_at = cur.fetchone()
        assert reason == "unknown_required_question"
        assert detail is not None and "Flexible Working" in detail
        assert transmitted_at is None, "a manual-step outcome must never also read as transmitted"

    def test_manual_step_releases_the_execution_claim_for_a_retry(
        self, client, auth_headers, user_id, tmp_path
    ):
        """A profile fix (the user answers the unknown question) must be
        retryable -- the manual-step path must NOT permanently burn the
        approval the way a successful send would."""
        from app.services.apply_executor import ManualStepRequired, execute_site_application

        job_id, resume_id, app_id = _seed(user_id)
        approval_id = _make_approval(user_id, app_id, job_id, status="approved")

        with pytest.raises(ManualStepRequired):
            execute_site_application(
                user_id, app_id, approval_id,
                page_html=ASHBY_HTML, channel="ashby", profile=MINIMAL_PROFILE,
                resume_pdf_bytes=b"%PDF-1.4 fake", cover_letter_text="Dear Hiring Manager,",
                evidence_dir=str(tmp_path),
            )

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT "executedAt" FROM "ApprovalRequest" WHERE "id" = %s', (approval_id,))
                assert cur.fetchone()[0] is None, "manual-step must release the claim, not leave it stamped"

    def test_captcha_persists_as_a_manual_step_not_a_failure(
        self, client, auth_headers, user_id, tmp_path
    ):
        from app.services.apply_executor import ManualStepRequired, execute_site_application

        job_id, resume_id, app_id = _seed(user_id)
        approval_id = _make_approval(user_id, app_id, job_id, status="approved")

        with pytest.raises(ManualStepRequired):
            execute_site_application(
                user_id, app_id, approval_id,
                page_html=CAPTCHA_HTML, channel="generic", profile=FULL_PROFILE_ASHBY,
                resume_pdf_bytes=b"%PDF-1.4 fake", cover_letter_text="Dear Hiring Manager,",
                evidence_dir=str(tmp_path),
            )

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT "manualStepReason" FROM "Application" WHERE "id" = %s', (app_id,))
                assert cur.fetchone()[0] == "captcha"


# ---------------------------------------------------------------------------
# 5. Success path: transmittedAt / transmissionChannel + evidence path.
# ---------------------------------------------------------------------------


class TestSuccessfulTransmission:
    def test_success_writes_transmission_and_evidence(self, client, auth_headers, user_id, tmp_path):
        from app.services.apply_executor import execute_site_application

        job_id, resume_id, app_id = _seed(user_id)
        approval_id = _make_approval(user_id, app_id, job_id, status="approved")

        result = execute_site_application(
            user_id, app_id, approval_id,
            page_html=ASHBY_HTML, channel="ashby", profile=FULL_PROFILE_ASHBY,
            resume_pdf_bytes=b"%PDF-1.4 fake", cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
        )
        assert result["transmitted"] is True
        assert result["evidencePath"]

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "transmittedAt", "transmissionChannel", "transmissionRef", "status" '
                    'FROM "Application" WHERE "id" = %s',
                    (app_id,),
                )
                transmitted_at, channel, ref, status_ = cur.fetchone()
        assert transmitted_at is not None
        assert channel == "ashby"
        assert ref  # evidence path or confirmation reference, non-empty
        assert status_ == "submitted"

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT "executedAt", "executionCompletedAt" FROM "ApprovalRequest" WHERE "id" = %s', (approval_id,))
                executed_at, completed_at = cur.fetchone()
        assert executed_at is not None
        assert completed_at is not None, "CRITICAL-4 pattern: a real send must stamp completion, not just a claim"

    def test_success_never_re_executes_on_a_second_call(self, client, auth_headers, user_id, tmp_path):
        """No-double-submission — a second execute for the SAME approval
        after a completed send must refuse (409), matching the existing
        W-SUB claim_execution contract."""
        from app.services.apply_executor import ApplyExecutorGuardError, execute_site_application

        job_id, resume_id, app_id = _seed(user_id)
        approval_id = _make_approval(user_id, app_id, job_id, status="approved")

        execute_site_application(
            user_id, app_id, approval_id,
            page_html=ASHBY_HTML, channel="ashby", profile=FULL_PROFILE_ASHBY,
            resume_pdf_bytes=b"%PDF-1.4 fake", cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
        )
        with pytest.raises(ApplyExecutorGuardError) as exc_info:
            execute_site_application(
                user_id, app_id, approval_id,
                page_html=ASHBY_HTML, channel="ashby", profile=FULL_PROFILE_ASHBY,
                resume_pdf_bytes=b"%PDF-1.4 fake", cover_letter_text="Dear Hiring Manager,",
                evidence_dir=str(tmp_path),
            )
        assert exc_info.value.reason == "already_executed"
