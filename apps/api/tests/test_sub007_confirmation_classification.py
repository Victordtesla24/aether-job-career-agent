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
    POST_SUBMIT_CONFIRMED,
    POST_SUBMIT_REJECTED,
    POST_SUBMIT_UNCONFIRMED,
    POST_SUBMIT_UNKNOWN,
    ManualStepRequired,
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
    page = open_page(_DISABLED_SUBMIT_FORM)
    outcome = classify_post_submit(page, page.url, before_probe=_before())
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
# 4. The honesty floor at the RECORDING site: `transmittedAt` is stamped in
#    exactly one place, and an unconfirmed ending may never reach it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "classification,expected_reason",
    [
        (POST_SUBMIT_UNCONFIRMED, "submitted_unconfirmed"),
        (POST_SUBMIT_REJECTED, "form_rejected"),
        (POST_SUBMIT_UNKNOWN, "no_confirmation"),
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
    with an unconfirmed classification and have the row stamped as sent."""
    from test_u5b_apply_executor import (  # same tests dir — one seeded fixture set
        ASHBY_HTML,
        FULL_PROFILE_ASHBY,
        _make_approval,
        _seed,
    )

    from app.db import get_connection
    from app.services.apply_executor import ManualStepRequired, execute_site_application

    user_id = test_user_id
    job_id, _resume_id, app_id = _seed(user_id)
    approval_id = _make_approval(user_id, app_id, job_id, status="approved")

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
        )
    assert exc_info.value.reason == expected_reason

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "transmittedAt", "manualStepReason" FROM "Application" '
                'WHERE "id" = %s',
                (app_id,),
            )
            transmitted_at, manual_reason = cur.fetchone()
    assert transmitted_at is None, "an unconfirmed ending must never read as transmitted"
    assert manual_reason == expected_reason
