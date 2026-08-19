"""SUB-007 — post-submit classification must tell three outcomes apart.

LEDGER GAP (verbatim): *"confirmation-detection: distinguish 'submitted-but-
unconfirmed' from 'form rejected'; broaden ``_CONFIRMATION_TEXT``; probe
disabled-submit state."*

Before this suite, every live submit that produced no recognised confirmation
phrase ended in ONE reason — ``no_confirmation`` — whether the site had
silently REJECTED the form (validation errors on screen, submit still armed)
or had genuinely TAKEN it and simply worded its thank-you page in a way the
narrow phrase list did not know. Those are different facts, they need
different words on the card, and only one of them is worth the user's time
re-typing the form.

What is pinned here:

1. ``_submit_state_probe`` reads the form's own state — submit control
   present/enabled, visible validation errors and error markers, whether a
   form is still on the page — and runs BEFORE the click as well as after, so
   the classification compares two states instead of guessing from one.
2. ``classify_post_submit`` returns exactly one of
   ``confirmed`` / ``submitted_unconfirmed`` / ``rejected`` / ``unknown``,
   each carrying its own manual-step reason code and its own honest sentence.
   The honesty floor is absolute: nothing but ``confirmed`` may ever be
   recorded as transmitted, and an unconfirmed outcome is NEVER upgraded.
3. ``_CONFIRMATION_TEXT`` recognises the phrasings real ATSs actually ship
   (Greenhouse / Lever / Workday / Ashby / Workable / SmartRecruiters /
   iCIMS / Taleo), and still refuses the near-misses that appear on a form
   page BEFORE anything is submitted.
4. End-to-end through the real ``playwright_form_submitter`` in a real
   headless Chromium against synthetic ``data:`` pages — live code path, zero
   network, zero real employer.
"""
from __future__ import annotations

import base64
from typing import Any, Iterator

import pytest

from app.services.apply_executor import (
    _CONFIRMATION_TEXT,
    MANUAL_STEP_SUBMIT_CONTROL_DISABLED,
    MANUAL_STEP_SUBMIT_CONTROL_NOT_FOUND,
    POST_SUBMIT_CONFIRMED,
    POST_SUBMIT_REJECTED,
    POST_SUBMIT_UNCONFIRMED,
    POST_SUBMIT_UNKNOWN,
    ManualStepRequired,
    _activate_submit,
    _submit_state_probe,
    classify_post_submit,
)

# ---------------------------------------------------------------------------
# 1. Broadened phrase list — every addition carries its own fixture.
# ---------------------------------------------------------------------------

#: (ATS the phrasing was taken from, the page text it shows once it HAS the
#: application). Nothing here is invented copy: these are the shapes ATS
#: confirmation screens use.
_ATS_CONFIRMATION_FIXTURES: tuple[tuple[str, str], ...] = (
    ("greenhouse", "Thanks for applying! We will review your application."),
    ("greenhouse", "Your application was submitted successfully."),
    ("lever", "Thank you for applying. Your application has been received."),
    ("workday", "You have successfully submitted your application."),
    ("workday", "Application submitted"),
    ("ashby", "Thank you for submitting your application to Acme."),
    ("ashby", "Application received"),
    ("workable", "We have received your application."),
    ("workable", "Your application is under review."),
    ("smartrecruiters", "Your application has been sent."),
    ("smartrecruiters", "Thank you for your application."),
    ("icims", "Your submission has been received."),
    ("taleo", "Thank you for taking the time to apply."),
    ("bamboohr", "Application complete"),
    ("recruitee", "We received your application and will be in touch."),
    ("jazzhr", "Your application is complete."),
    ("generic", "Submitted successfully"),
    ("generic", "We have your application."),
    # Round-2 additions — each one a phrasing the list did NOT recognise, and
    # each one wording a site only uses once it HAS the application.
    ("bullhorn", "Thank you for submitting your resume."),
    ("bullhorn", "We have received your resume."),
    ("icims", "Thank you for completing our application."),
    ("zoho", "Your profile has been submitted."),
    ("freshteam", "Your candidacy has been received."),
    ("taleo", "Your application is on file."),
    ("smartrecruiters", "Your application is now with our hiring team."),
    ("breezy", "We're reviewing your application."),
    ("teamtailor", "We have received your details."),
)

#: Text that must NEVER count as proof. Every one of these can sit on a form
#: page BEFORE anything is submitted (or on the rejection the site shows
#: instead of taking the application), so matching one would turn a failed
#: attempt into a fabricated "applied".
_NOT_CONFIRMATION_FIXTURES: tuple[str, ...] = (
    "Applications received after 5pm will be considered the next business day.",
    "Your application will be submitted once every required field is complete.",
    "Application not submitted — please correct the errors below.",
    "Thank you for your interest in careers at Acme.",
    "Submit your application below.",
    "Your application was not received. Please try again.",
    # Round-2 near-misses for the widened phrases above.
    "We have not received your application yet.",
    "Please submit your resume to continue.",
    "We will review your application once it is submitted.",
    "Upload your resume and we will review your application.",
    "Your profile is incomplete — finish it before submitting.",
)


@pytest.mark.parametrize("ats,text", _ATS_CONFIRMATION_FIXTURES)
def test_confirmation_text_recognises_real_ats_phrasings(ats: str, text: str) -> None:
    assert _CONFIRMATION_TEXT.search(text), f"{ats} confirmation not recognised: {text!r}"


@pytest.mark.parametrize("text", _NOT_CONFIRMATION_FIXTURES)
def test_confirmation_text_refuses_pre_submit_and_failure_copy(text: str) -> None:
    match = _CONFIRMATION_TEXT.search(text)
    assert match is None, f"fabricated proof from {text!r} (matched {match!r})"


# ---------------------------------------------------------------------------
# 2. Real headless Chromium over synthetic HTML fixtures.
# ---------------------------------------------------------------------------


def _data_url(html: str) -> str:
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


@pytest.fixture
def open_page() -> Iterator[Any]:
    """Factory: synthetic HTML → a live page in a real headless Chromium.

    Function-scoped on purpose: Playwright's SYNC api refuses a second
    ``sync_playwright()`` while one is open on the same thread, and the
    end-to-end tests below drive ``playwright_form_submitter``, which opens its
    own. A module-scoped browser here would poison those with a bare
    ``Error``.
    """
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


_ARMED_FORM = """
<title>form</title>
<form id="f">
  <label for="name">Name</label><input id="name" type="text">
  <button type="submit">Submit Application</button>
</form>
"""

_DISABLED_SUBMIT_FORM = """
<title>form</title>
<form id="f">
  <label for="name">Name</label><input id="name" type="text">
  <button type="submit" disabled>Submitting…</button>
</form>
"""

_REJECTED_FORM = """
<title>form</title>
<form id="f">
  <label for="name">Name</label>
  <input id="name" type="text" aria-invalid="true">
  <p role="alert">This field is required</p>
  <button type="submit">Submit Application</button>
</form>
"""

_ACCEPTED_SILENT_PAGE = """
<title>done</title>
<main><h1>Acme Careers</h1><p>Your details are with our recruiting team.</p></main>
"""

_CONFIRMED_PAGE = """
<title>done</title>
<main><h1>Thanks for applying!</h1><p>We will review your application.</p></main>
"""


def test_probe_reads_an_armed_submit_control(open_page: Any) -> None:
    probe = _submit_state_probe(open_page(_ARMED_FORM))
    assert probe["submitPresent"] is True
    assert probe["submitEnabled"] is True
    assert probe["formPresent"] is True
    assert probe["errors"] == []
    assert probe["markers"] == []


def test_probe_reads_a_disabled_submit_control(open_page: Any) -> None:
    """The ledger's 'probe disabled-submit state' — a greyed-out submit is a
    fact about acceptance, not something to infer from silence."""
    probe = _submit_state_probe(open_page(_DISABLED_SUBMIT_FORM))
    assert probe["submitPresent"] is True
    assert probe["submitEnabled"] is False


def test_probe_reads_visible_validation_errors(open_page: Any) -> None:
    probe = _submit_state_probe(open_page(_REJECTED_FORM))
    assert any("required" in err.lower() for err in probe["errors"]), probe
    assert probe["markers"], probe
    assert probe["submitEnabled"] is True


def _make_site_apply_approval(user_id: str, app_id: str, job_id: str) -> str:
    """A genuine U5d-2 SITE-APPLY approval — ``kind="submission"`` + an
    automatable ``channel``, no ``recipient`` — matching
    ``application_submission.is_site_apply_payload`` exactly, unlike
    ``test_u5b_apply_executor._make_approval``'s legacy ``kind="site_apply"``
    payload.

    That legacy shape does NOT satisfy ``is_site_apply_payload`` (it checks
    for ``kind == "submission"``), so ``ApprovalRepository._sync_application``
    treats it as a pre-U5d-2 email card and promotes ``Application.status`` to
    ``"submitted"`` on the ``approve()`` call ALONE — before
    ``execute_site_application`` ever runs. That is a real, pre-existing
    artefact of the shared fixture (nothing this suite is pinning), and it
    would make every ``status != "submitted"`` assertion below fail for the
    WRONG reason. Using the real payload shape here means those assertions
    exercise ``execute_site_application``'s own honesty floor instead.
    """
    from app.repositories.approval import ApprovalRepository

    approval = ApprovalRepository().create(
        user_id,
        "application_submit",
        {
            "kind": "submission",
            "job_id": job_id,
            "application_id": app_id,
            "channel": "ashby",
            "apply_url": "https://jobs.example.invalid/apply",
        },
        application_id=app_id,
    )
    ApprovalRepository().approve(approval["id"], user_id)
    return approval["id"]


def _before(**overrides: Any) -> dict[str, Any]:
    """A pre-click probe of a clean, armed form."""
    state: dict[str, Any] = {
        "submitPresent": True,
        "submitEnabled": True,
        "formPresent": True,
        "errors": [],
        "markers": [],
        "confirmationText": None,
    }
    state.update(overrides)
    return state


def _clicked_activation() -> Any:
    """The activation record of a submit control that WAS clicked.

    Round-2 review: ``classify_post_submit`` may only read a post-click page as
    "the site accepted it" when a click actually happened. Every classification
    test that describes an outcome AFTER a click therefore states that fact
    explicitly instead of leaving it implied.
    """
    from app.services.apply_executor import SubmitActivation

    return SubmitActivation(
        clicked=True,
        present=True,
        enabled=True,
        selector='button[type="submit"]',
        failure=None,
    )


def test_classify_confirmed_when_the_site_says_it_has_the_application(
    open_page: Any,
) -> None:
    page = open_page(_CONFIRMED_PAGE)
    outcome = classify_post_submit(page, page.url, before_probe=_before())
    assert outcome.classification == POST_SUBMIT_CONFIRMED
    assert outcome.reason is None
    assert outcome.confirmation and "applying" in outcome.confirmation.lower()


def test_classify_rejected_when_the_form_is_intact_with_visible_errors(
    open_page: Any,
) -> None:
    page = open_page(_REJECTED_FORM)
    outcome = classify_post_submit(page, page.url, before_probe=_before())
    assert outcome.classification == POST_SUBMIT_REJECTED
    assert outcome.reason == "form_rejected"
    assert outcome.confirmation is None
    # The employer's OWN words are carried through, not a generic guess.
    assert "required" in outcome.detail.lower()


def test_classify_submitted_unconfirmed_when_the_form_is_gone_without_a_phrase(
    open_page: Any,
) -> None:
    page = open_page(_ACCEPTED_SILENT_PAGE)
    outcome = classify_post_submit(page, page.url, before_probe=_before())
    assert outcome.classification == POST_SUBMIT_UNCONFIRMED
    assert outcome.reason == "submitted_unconfirmed"
    assert outcome.confirmation is None
    # HONESTY FLOOR: an unconfirmed outcome never talks like a receipt.
    lowered = outcome.detail.lower()
    assert "no confirmation" in lowered or "did not confirm" in lowered


def test_classify_submitted_unconfirmed_when_submit_went_from_armed_to_disabled(
    open_page: Any,
) -> None:
    """An armed button that the CLICK greyed out is the classic "sending…"
    shape, so it reads as acceptance — but ONLY because the click happened.
    The activation record is what says so; see
    ``test_live_armed_to_disabled_submit_is_submitted_unconfirmed_end_to_end``
    for the same shape driven through the real submitter."""
    page = open_page(_DISABLED_SUBMIT_FORM)
    outcome = classify_post_submit(
        page,
        page.url,
        before_probe=_before(),
        activation=_clicked_activation(),
    )
    assert outcome.classification == POST_SUBMIT_UNCONFIRMED
    assert outcome.reason == "submitted_unconfirmed"


def test_classify_unknown_when_nothing_on_the_page_moved(open_page: Any) -> None:
    """No errors, no confirmation, form still armed: Aether knows nothing —
    and says exactly that instead of inventing either verdict."""
    page = open_page(_ARMED_FORM)
    outcome = classify_post_submit(page, page.url, before_probe=_before())
    assert outcome.classification == POST_SUBMIT_UNKNOWN
    assert outcome.reason == "no_confirmation"
    assert outcome.confirmation is None


def test_standing_alert_chrome_is_not_read_as_a_rejection(open_page: Any) -> None:
    """A cookie banner in a `role="alert"` is not a refused form. Only text
    that reads like validation (or a marker the click brought up) may be
    reported back to the user as "the site rejected this"."""
    html = """
    <title>form</title>
    <div role="alert">We use cookies to improve your experience.</div>
    <form id="f"><input id="name" type="text">
    <button type="submit">Submit Application</button></form>
    """
    page = open_page(html)
    standing = _submit_state_probe(page)
    assert standing["markers"] == ['[role="alert"]']
    outcome = classify_post_submit(page, page.url, before_probe=standing)
    assert outcome.classification == POST_SUBMIT_UNKNOWN
    assert outcome.reason == "no_confirmation"


def test_a_bare_navigation_without_a_phrase_is_not_proof(open_page: Any) -> None:
    """The pre-SUB-007 code returned ``"navigated to <url>"`` AS the proof, so
    any post-click redirect — a login wall, an error screen, the careers home
    page — was recorded as a confirmed transmission. Movement now means only
    that the form was accepted: honest ``submitted_unconfirmed``."""
    page = open_page(_ARMED_FORM)
    outcome = classify_post_submit(
        page, "https://boards.example.invalid/apply", before_probe=_before()
    )
    assert outcome.classification == POST_SUBMIT_UNCONFIRMED
    assert outcome.reason == "submitted_unconfirmed"
    assert outcome.confirmation is None
    assert "no confirmation" in outcome.detail.lower()


def test_a_confirmation_phrase_after_navigation_is_proof_and_names_both_facts(
    open_page: Any,
) -> None:
    """A navigation that lands on a page whose words DO confirm receipt is a
    receipt — and the evidence quotes the phrase, not just the URL."""
    page = open_page(_CONFIRMED_PAGE)
    outcome = classify_post_submit(
        page, "https://boards.example.invalid/apply", before_probe=_before()
    )
    assert outcome.classification == POST_SUBMIT_CONFIRMED
    assert outcome.confirmation is not None
    assert "applying" in outcome.confirmation.lower()
    assert not outcome.confirmation.lower().startswith("navigated to")


def test_a_confirmation_phrase_already_on_the_form_page_is_not_proof(
    open_page: Any,
) -> None:
    """Plenty of forms head themselves 'Thank you for applying to Acme'. Text
    that was there BEFORE the click proves nothing about after it."""
    html = """
    <title>form</title>
    <h1>Thanks for applying! Complete the form below.</h1>
    <form id="f"><input id="name" type="text">
    <button type="submit">Submit Application</button></form>
    """
    page = open_page(html)
    outcome = classify_post_submit(
        page,
        page.url,
        before_probe=_before(confirmationText="Thanks for applying"),
    )
    assert outcome.classification == POST_SUBMIT_UNKNOWN
    assert outcome.confirmation is None


# ---------------------------------------------------------------------------
# 3. End-to-end through the real submitter — synthetic forms only.
# ---------------------------------------------------------------------------

_E2E_REJECTING_FORM = """
<title>reject</title>
<form onsubmit="event.preventDefault();
    document.getElementById('err').setAttribute('role','alert');
    document.getElementById('err').textContent =
      'Missing entry for required field: Phone number';">
  <label for="name">Name</label><input id="name" type="text">
  <button type="submit">Submit Application</button>
</form>
<div id="err"></div>
"""

_E2E_SILENT_ACCEPT_FORM = """
<title>silent</title>
<form onsubmit="event.preventDefault();
    document.body.innerHTML = '<main><p>Your details are with our team.</p></main>';">
  <label for="name">Name</label><input id="name" type="text">
  <button type="submit">Submit Application</button>
</form>
"""

_E2E_BROADENED_CONFIRMATION_FORM = """
<title>ok</title>
<form onsubmit="event.preventDefault();
    document.body.innerHTML = '<h1>Thanks for applying!</h1>';">
  <label for="name">Name</label><input id="name" type="text">
  <button type="submit">Submit Application</button>
</form>
"""


def _name_plan_field() -> dict[str, Any]:
    return {
        "name": "name",
        "label": "Name",
        "kind": "text",
        "required": True,
        "scope": "",
        "value": "JordanBlake",
        "options": [],
    }


def _submit(html: str, tmp_path: Any, application_id: str) -> dict[str, Any]:
    from app.services.apply_executor import playwright_form_submitter

    return playwright_form_submitter(
        application_id=application_id,
        channel="generic",
        page_html="",
        apply_url=_data_url(html),
        plan={"fields": [_name_plan_field()]},
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
    )


def test_live_rejected_form_is_recorded_as_a_rejection_not_a_silent_submit(
    tmp_path: Any,
) -> None:
    with pytest.raises(ManualStepRequired) as exc_info:
        _submit(_E2E_REJECTING_FORM, tmp_path, "sub007reject")
    err = exc_info.value
    assert err.reason == "form_rejected"
    assert "Phone number" in err.message
    assert "received" not in err.message.lower().split("nothing")[0]


def test_live_silent_acceptance_is_recorded_as_submitted_unconfirmed(
    tmp_path: Any,
) -> None:
    with pytest.raises(ManualStepRequired) as exc_info:
        _submit(_E2E_SILENT_ACCEPT_FORM, tmp_path, "sub007silent")
    err = exc_info.value
    assert err.reason == "submitted_unconfirmed"
    # NEVER upgraded: the row this writes is a manual step, not a transmission.
    assert "not" in err.message.lower()


def test_live_broadened_confirmation_phrase_now_counts_as_proof(
    tmp_path: Any,
) -> None:
    outcome = _submit(_E2E_BROADENED_CONFIRMATION_FORM, tmp_path, "sub007ok")
    assert outcome["submitted"] is True
    assert outcome["classification"] == POST_SUBMIT_CONFIRMED
    assert outcome["confirmation"] and "applying" in str(outcome["confirmation"]).lower()


# ---------------------------------------------------------------------------
# 3b. The DISABLED submit control, end to end (round-2 review).
#
# The ledger's "probe disabled-submit state" is not satisfied by a probe whose
# reading nothing acts on. Before this section:
#
#   * ``_activate_submit`` clicked without ever asking ``is_enabled()``, so on
#     a present-but-DISABLED control Playwright's click timed out, the bare
#     ``except Exception: continue`` swallowed the timeout and the function
#     returned ``False`` — indistinguishable from "this form has no submit
#     button at all";
#   * classification was gated on that ``False``, so the PostSubmitOutcome
#     (whose before-probe had correctly read ``submitEnabled=False``) was
#     computed and then thrown away; and
#   * the recording site reported the greyed-out button as
#     ``submit_control_not_found`` — telling the user Aether could not FIND a
#     button that was sitting right there, disabled.
#
# Every test below drives the real code path against a synthetic form.
# ---------------------------------------------------------------------------


class _SpyLocator:
    """A locator that records ``click()`` calls and otherwise defers."""

    def __init__(self, real: Any, selector: str, clicks: list[str]) -> None:
        self._real = real
        self._selector = selector
        self._clicks = clicks

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    @property
    def first(self) -> "_SpyLocator":
        return _SpyLocator(self._real.first, self._selector, self._clicks)

    def click(self, **kwargs: Any) -> Any:
        self._clicks.append(self._selector)
        return self._real.click(**kwargs)


class _ClickSpyPage:
    """A real page that records which selectors were actually clicked."""

    def __init__(self, page: Any) -> None:
        self._page = page
        self.clicks: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._page, name)

    def locator(self, selector: str) -> _SpyLocator:
        return _SpyLocator(self._page.locator(selector), selector, self.clicks)


_NO_SUBMIT_CONTROL_FORM = """
<title>form</title>
<form id="f"><label for="name">Name</label><input id="name" type="text"></form>
"""


def test_activate_submit_probes_the_disabled_state_instead_of_clicking_it(
    open_page: Any,
) -> None:
    """The ledger's probe, at the one place it changes behaviour: a disabled
    control is READ as disabled and never clicked, so no click timeout can
    launder "the button is greyed out" into "there is no button"."""
    page = _ClickSpyPage(open_page(_DISABLED_SUBMIT_FORM))
    activation = _activate_submit(page)
    assert activation.clicked is False
    assert activation.present is True, "the control is right there in the DOM"
    assert activation.enabled is False
    assert activation.failure == MANUAL_STEP_SUBMIT_CONTROL_DISABLED
    assert page.clicks == [], "a disabled control must never be clicked at all"


def test_activate_submit_reports_a_missing_control_as_absent_not_disabled(
    open_page: Any,
) -> None:
    activation = _activate_submit(open_page(_NO_SUBMIT_CONTROL_FORM))
    assert activation.clicked is False
    assert activation.present is False
    assert activation.failure == MANUAL_STEP_SUBMIT_CONTROL_NOT_FOUND


def test_activate_submit_clicks_an_armed_control(open_page: Any) -> None:
    page = _ClickSpyPage(open_page(_ARMED_FORM))
    activation = _activate_submit(page)
    assert activation.clicked is True
    assert (activation.present, activation.enabled) == (True, True)
    assert activation.failure is None
    assert page.clicks, "an armed control is still clicked"


def test_classify_calls_a_never_clicked_disabled_control_a_rejection(
    open_page: Any,
) -> None:
    """No click happened, so nothing reached the employer — and the outcome
    must say the form REFUSED to arm, not that Aether knows nothing."""
    page = open_page(_DISABLED_SUBMIT_FORM)
    activation = _activate_submit(page)
    outcome = classify_post_submit(
        page, page.url, before_probe=_submit_state_probe(page), activation=activation
    )
    assert outcome.classification == POST_SUBMIT_REJECTED
    assert outcome.reason == MANUAL_STEP_SUBMIT_CONTROL_DISABLED
    assert outcome.confirmation is None
    lowered = outcome.detail.lower()
    assert "disabled" in lowered or "greyed" in lowered
    assert "nothing was submitted" in lowered


def test_classify_never_reads_an_unclicked_form_as_submitted_unconfirmed(
    open_page: Any,
) -> None:
    """A form with no submit control at all has an "accepted" SHAPE by every
    DOM signal (no submit button on the page) — but nothing was clicked, so
    calling it ``submitted_unconfirmed`` would be a fabricated attempt."""
    page = open_page(_NO_SUBMIT_CONTROL_FORM)
    activation = _activate_submit(page)
    outcome = classify_post_submit(
        page, page.url, before_probe=_submit_state_probe(page), activation=activation
    )
    assert outcome.classification == POST_SUBMIT_UNKNOWN
    assert outcome.reason == MANUAL_STEP_SUBMIT_CONTROL_NOT_FOUND
    assert outcome.confirmation is None


_E2E_DISABLED_SUBMIT_FORM = """
<title>blocked</title>
<form>
  <label for="name">Name</label><input id="name" type="text">
  <button type="submit" disabled>Submit Application</button>
</form>
"""

_E2E_DISABLED_SUBMIT_WITH_ERROR_FORM = """
<title>blocked</title>
<form>
  <label for="name">Name</label><input id="name" type="text">
  <p role="alert">Please complete every required field before submitting.</p>
  <button type="submit" disabled>Submit Application</button>
</form>
"""

_E2E_ARMED_THEN_DISABLED_FORM = """
<title>sending</title>
<form onsubmit="event.preventDefault();
    document.querySelector('button').disabled = true;
    document.querySelector('button').textContent = 'Sending…';">
  <label for="name">Name</label><input id="name" type="text">
  <button type="submit">Submit Application</button>
</form>
"""


def test_live_disabled_submit_is_a_blocked_form_not_a_missing_control(
    tmp_path: Any,
) -> None:
    """The exact live reproduction the round-2 review recorded: a synthetic
    form whose only control is ``<button type="submit" disabled>`` used to come
    back ``{'submitted': False, 'classification': 'unknown'}`` and be reported
    as ``submit_control_not_found``."""
    with pytest.raises(ManualStepRequired) as exc_info:
        _submit(_E2E_DISABLED_SUBMIT_FORM, tmp_path, "sub007disabled")
    err = exc_info.value
    assert err.reason == MANUAL_STEP_SUBMIT_CONTROL_DISABLED
    assert err.reason != MANUAL_STEP_SUBMIT_CONTROL_NOT_FOUND
    lowered = err.message.lower()
    assert "disabled" in lowered or "greyed" in lowered
    # It must NOT claim the button was missing, and must NOT read as a send.
    assert "could not find" not in lowered
    assert "nothing was submitted" in lowered


def test_live_disabled_submit_quotes_the_forms_own_blocking_message(
    tmp_path: Any,
) -> None:
    with pytest.raises(ManualStepRequired) as exc_info:
        _submit(_E2E_DISABLED_SUBMIT_WITH_ERROR_FORM, tmp_path, "sub007disablederr")
    err = exc_info.value
    assert err.reason == MANUAL_STEP_SUBMIT_CONTROL_DISABLED
    assert "required field" in err.message.lower()


def test_live_armed_to_disabled_submit_is_submitted_unconfirmed_end_to_end(
    tmp_path: Any,
) -> None:
    """The armed→disabled acceptance shape, driven through the REAL
    ``_activate_submit``/``playwright_form_submitter`` path rather than a
    hand-built before-probe: the click lands, the button greys out, no
    confirmation wording appears — honest ``submitted_unconfirmed``."""
    with pytest.raises(ManualStepRequired) as exc_info:
        _submit(_E2E_ARMED_THEN_DISABLED_FORM, tmp_path, "sub007arming")
    err = exc_info.value
    assert err.reason == "submitted_unconfirmed"
    assert "will not" in err.message.lower() or "not claim" in err.message.lower()


# ---------------------------------------------------------------------------
# 4. The honesty floor at the RECORDING site: `transmittedAt` is stamped in
#    exactly one place, and an unconfirmed ending may never reach it.
# ---------------------------------------------------------------------------


#: Round-3 review (2026-08-19, REVIEWER-FAIL): prompt.md §0 makes the
#: candidate's own Gmail the ONLY stamp gate after a real Submit click on a
#: LIVE ``apply_url``. A page phrase is not a send, and neither is a page
#: phrase's ABSENCE a reason to skip the inbox: ``POST_SUBMIT_UNCONFIRMED``
#: and ``POST_SUBMIT_UNKNOWN`` both mean "a click happened, no confirmation
#: wording appeared" and both must go on to poll Gmail on a live URL, exactly
#: like ``POST_SUBMIT_CONFIRMED`` does. Only ``POST_SUBMIT_REJECTED`` — the
#: employer's OWN validation errors — is decided before Gmail is ever touched,
#: because a rejected form has nothing for the inbox to confirm.
#:
#: Every row below uses the SAME empty poller (``lambda *a, **k: None``) so a
#: single fixed behaviour proves BOTH facts at once: REJECTED must reach
#: ``form_rejected`` withOUT ever depending on what the poller says, and
#: UNCONFIRMED/UNKNOWN must reach ``awaiting_receipt`` (the poll ran, found
#: nothing) rather than the pre-receipt-gate ``submitted_unconfirmed`` /
#: ``no_confirmation`` reasons this test pinned before the gate existed. If a
#: future change makes REJECTED reach the poller too, its result (``None``)
#: would flip the reason to ``awaiting_receipt`` and this row would go red —
#: that IS the regression detector the reviewer asked for.
@pytest.mark.parametrize(
    "classification,expected_reason",
    [
        (POST_SUBMIT_REJECTED, "form_rejected"),
        (POST_SUBMIT_UNCONFIRMED, "awaiting_receipt"),
        (POST_SUBMIT_UNKNOWN, "awaiting_receipt"),
    ],
)
def test_an_unconfirmed_outcome_is_never_recorded_as_a_transmission(
    client: Any,
    auth_headers: Any,
    test_user_id: str,
    tmp_path: Any,
    classification: str,
    expected_reason: str,
) -> None:
    """Defence in depth for the ledger's honesty floor. The submitter already
    raises on every non-confirmed ending; this pins that the recording site
    refuses one too, so no future submitter can hand back "submitted: true"
    with an unconfirmed classification and have the row stamped as sent.

    ``receipt_poller`` is injected and always returns ``None`` so this test
    never touches a real inbox — the empty poller is the fixture, not a
    default the production code happens to fall back to.
    """
    from test_u5b_apply_executor import (  # same tests dir — one seeded fixture set
        ASHBY_HTML,
        FULL_PROFILE_ASHBY,
        _seed,
    )

    from app.db import get_connection
    from app.services.apply_executor import ManualStepRequired, execute_site_application

    user_id = test_user_id
    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _make_site_apply_approval(user_id, app_id, job_id)

    def _lying_submitter(**_kwargs: Any) -> dict[str, Any]:
        return {
            "submitted": True,
            "confirmation": None,
            "classification": classification,
            "evidencePath": str(tmp_path / "shot.png"),
            "destination": "https://jobs.example.invalid/apply",
            "filled": [],
            "unfilled": [],
            "mode": "live",
        }

    with pytest.raises(ManualStepRequired) as exc_info:
        execute_site_application(
            user_id,
            app_id,
            approval_id,
            page_html=ASHBY_HTML,
            channel="ashby",
            profile=FULL_PROFILE_ASHBY,
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            apply_url="https://jobs.example.invalid/apply",
            submitter=_lying_submitter,
            receipt_poller=lambda *a, **k: None,
        )
    assert exc_info.value.reason == expected_reason

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "transmittedAt", "manualStepReason", "status" FROM "Application" '
                'WHERE "id" = %s',
                (app_id,),
            )
            transmitted_at, manual_reason, status = cur.fetchone()
    assert transmitted_at is None, "an unconfirmed ending must never read as transmitted"
    assert manual_reason == expected_reason
    assert status != "submitted", "a manual step must never be recorded as a claimed send"


def test_a_rejected_form_is_not_saved_by_a_coincidental_gmail_hit(
    client: Any,
    auth_headers: Any,
    test_user_id: str,
    tmp_path: Any,
) -> None:
    """prompt.md §0: REJECTED is not a send. A message sitting in the
    candidate's Gmail — even one that would otherwise look exactly like a
    matching ATS receipt — proves nothing about a form the employer's OWN
    validation refused. The poller here returns a receipt precisely to prove
    it is never consulted for this classification."""
    from test_u5b_apply_executor import (  # same tests dir — one seeded fixture set
        ASHBY_HTML,
        FULL_PROFILE_ASHBY,
        _seed,
    )

    from app.db import get_connection
    from app.services.apply_executor import ManualStepRequired, execute_site_application

    user_id = test_user_id
    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _make_site_apply_approval(user_id, app_id, job_id)

    def _lying_submitter(**_kwargs: Any) -> dict[str, Any]:
        return {
            "submitted": True,
            "confirmation": None,
            "classification": POST_SUBMIT_REJECTED,
            "evidencePath": str(tmp_path / "shot.png"),
            "destination": "https://jobs.example.invalid/apply",
            "filled": [],
            "unfilled": [],
            "mode": "live",
        }

    def _receipt_poller_finds_a_message(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "messageId": "coincidental-hit",
            "from": "notifications@ashbyhq.com",
            "subject": "Thank you for applying",
        }

    with pytest.raises(ManualStepRequired) as exc_info:
        execute_site_application(
            user_id,
            app_id,
            approval_id,
            page_html=ASHBY_HTML,
            channel="ashby",
            profile=FULL_PROFILE_ASHBY,
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            apply_url="https://jobs.example.invalid/apply",
            submitter=_lying_submitter,
            receipt_poller=_receipt_poller_finds_a_message,
        )
    assert exc_info.value.reason == "form_rejected"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "transmittedAt", "manualStepReason", "status" FROM "Application" '
                'WHERE "id" = %s',
                (app_id,),
            )
            transmitted_at, manual_reason, status = cur.fetchone()
    assert transmitted_at is None, "employer rejection is never overridden by a mailbox hit"
    assert manual_reason == "form_rejected"
    assert status != "submitted"


def test_a_matching_gmail_receipt_after_an_unconfirmed_click_is_prompt_md_success(
    client: Any,
    auth_headers: Any,
    test_user_id: str,
    tmp_path: Any,
) -> None:
    """The ONE shape prompt.md §0 calls SUCCESS: a real Submit click, no
    confirmation phrase on the page, and THEN a matching ATS receipt lands in
    the candidate's own connected Gmail. This pins the contract the
    parametrized test above no longer exercises on its own — a receipt that
    DOES arrive must still stamp ``transmittedAt`` with a ``gmail:``-tagged
    ``transmissionRef``. If this already passes on the current WIP, it still
    belongs here: it is the positive half of the honesty floor, not just the
    negative half."""
    from test_u5b_apply_executor import (  # same tests dir — one seeded fixture set
        ASHBY_HTML,
        FULL_PROFILE_ASHBY,
        _seed,
    )

    from app.db import get_connection
    from app.services.apply_executor import execute_site_application

    user_id = test_user_id
    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _make_site_apply_approval(user_id, app_id, job_id)

    def _lying_submitter(**_kwargs: Any) -> dict[str, Any]:
        return {
            "submitted": True,
            "confirmation": None,
            "classification": POST_SUBMIT_UNCONFIRMED,
            "evidencePath": str(tmp_path / "shot.png"),
            "destination": "https://jobs.example.invalid/apply",
            "filled": [],
            "unfilled": [],
            "mode": "live",
        }

    def _receipt_poller_finds_the_ats_receipt(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "messageId": "gmail-ok",
            "from": "notifications@ashbyhq.com",
            "subject": "Thank you for applying",
        }

    result = execute_site_application(
        user_id,
        app_id,
        approval_id,
        page_html=ASHBY_HTML,
        channel="ashby",
        profile=FULL_PROFILE_ASHBY,
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
        apply_url="https://jobs.example.invalid/apply",
        submitter=_lying_submitter,
        receipt_poller=_receipt_poller_finds_the_ats_receipt,
    )
    assert result["transmitted"] is True

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "transmittedAt", "transmissionRef", "status" FROM "Application" '
                'WHERE "id" = %s',
                (app_id,),
            )
            transmitted_at, transmission_ref, status = cur.fetchone()
    assert transmitted_at is not None, "a matching post-click receipt IS a transmission"
    assert "gmail:gmail-ok" in str(transmission_ref)
    assert status == "submitted"


def test_a_disabled_control_is_recorded_as_disabled_not_as_a_missing_button(
    client: Any,
    auth_headers: Any,
    test_user_id: str,
    tmp_path: Any,
) -> None:
    """Defence in depth at the RECORDING site (round-2 review). The submitter
    already raises ``submit_control_disabled`` for a greyed-out button, but the
    ``not outcome["submitted"]`` branch here used to hard-code
    ``submit_control_not_found`` for EVERY unsubmitted outcome — so any
    submitter reporting a present-but-disabled control still told the user
    Aether could not find a button that exists."""
    from test_u5b_apply_executor import (  # same tests dir — one seeded fixture set
        ASHBY_HTML,
        FULL_PROFILE_ASHBY,
        _make_approval,
        _seed,
    )

    from app.db import get_connection
    from app.services.apply_executor import execute_site_application

    user_id = test_user_id
    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _make_approval(user_id, app_id, job_id, status="approved")

    def _disabled_control_submitter(**_kwargs: Any) -> dict[str, Any]:
        return {
            "submitted": False,
            "confirmation": None,
            "classification": POST_SUBMIT_REJECTED,
            "submitControl": {
                "present": True,
                "enabled": False,
                "clicked": False,
                "selector": 'button[type="submit"]',
                "failure": MANUAL_STEP_SUBMIT_CONTROL_DISABLED,
            },
            "evidencePath": str(tmp_path / "shot.png"),
            "destination": "https://jobs.example.invalid/apply",
            "filled": [],
            "unfilled": [],
            "mode": "live",
        }

    with pytest.raises(ManualStepRequired) as exc_info:
        execute_site_application(
            user_id,
            app_id,
            approval_id,
            page_html=ASHBY_HTML,
            channel="ashby",
            profile=FULL_PROFILE_ASHBY,
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            apply_url="https://jobs.example.invalid/apply",
            submitter=_disabled_control_submitter,
        )
    assert exc_info.value.reason == MANUAL_STEP_SUBMIT_CONTROL_DISABLED
    assert "could not find" not in exc_info.value.message.lower()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "transmittedAt", "manualStepReason" FROM "Application" '
                'WHERE "id" = %s',
                (app_id,),
            )
            transmitted_at, manual_reason = cur.fetchone()
    assert transmitted_at is None
    assert manual_reason == MANUAL_STEP_SUBMIT_CONTROL_DISABLED
