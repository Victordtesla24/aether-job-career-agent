"""U5d-4 — the employer's own email verification code (fold-in, RUN-20260818T0223Z
SUB-011/lane/u5d4-fold).

CONTEXT: this capability was originally landed in 51016fee ("preserve u5d4
verification-code-loop work from removed worktree (MP-001)") on
``feat/u5d4-verification-code-loop``, whose dedicated test file was lost in the
same worktree-removal incident (D9/MP-001) the commit message documents. This
file RE-AUTHORS that coverage from the capability spec, against the CURRENT
(sub-005-R7 + SUB-011 hardened) shape of ``apply_executor.py`` — see
``docs/delivery/evidence/RUN-20260818T0223Z/SUB-011/05-u5d4-fold.md`` for the
capability map and the RED->GREEN record.

CONTRACT under test:

  Some ATS forms answer the submit click with an anti-bot gate: "enter the
  security code we just emailed you". The employer has NOT received the
  application until that code is typed, so:

  * with a ``user_id``, the code is read ONLY from THAT user's own connected
    Gmail (never generated, never guessed, no third-party OTP service) and
    typed into the gate the way a human would;
  * without a ``user_id`` (replay, or a direct call) the gate is an honest,
    immediate ``ManualStepRequired("verification_code_email")`` naming the
    employer — never an attempt to work around it;
  * a Gmail read failure (not connected / expired grant) is the SAME honest
    manual step, still naming the employer and the address the code went to;
  * the loop can NEVER create a path around CLI-SUB-005-R7's fail-closed
    submission guard: a click the guard blocks — the form's own first click,
    or U5d-4's own code-entry resubmit — refuses exactly as any other
    guard-blocked click does, and the verification-code machinery is never
    even reached if the FIRST click was blocked.

Fake pages follow the existing style (test_cli_sub005_fill_commit.py): real
Playwright against synthetic ``data:`` pages, live-mode code path, zero
network, zero real employer. The Gmail double follows the existing style
(test_mon002_gmail_403_backoff.py / test_email_center_career_inbox.py): a
plain stand-in class matching ``GmailService``'s own constructor and method
signatures, injected via ``monkeypatch.setattr("app.services.gmail_service.
GmailService", ...)`` or (for the direct unit test of the gate-resolution
helper) via its own ``gmail_factory`` parameter — never ``unittest.mock``.
"""
from __future__ import annotations

import base64
import time as time_module
from email.utils import formatdate
from typing import Any

import pytest

from app.services.apply_executor import ManualStepRequired

# ---------------------------------------------------------------------------
# Fakes / fixtures.
# ---------------------------------------------------------------------------


def _data_url(html: str) -> str:
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


def _name_plan_field() -> dict[str, Any]:
    return {
        "name": "name",
        "label": "Name",
        "kind": "text",
        "required": True,
        "scope": "",
        "value": "jordan.blake@example.com",
        "options": [],
    }


# A well-behaved form whose submit click reveals the SAME anti-bot gate every
# real ATS shows: the wording _VERIFICATION_GATE_TEXT matches, plus a real
# labelled code input _CODE_INPUT_SELECTOR matches. The "name" field doubles
# as the address the code went to (_planned_form_email reads it straight out
# of the plan) since it is filled with an email-shaped value.
_GATE_TRIGGER_FORM = """
<title>gate-trigger</title>
<form onsubmit='event.preventDefault();
    document.body.innerHTML = "<p>We just emailed you a verification code.</p>" +
      "<input id=\\"code\\" maxlength=\\"8\\" aria-label=\\"code\\">" +
      "<button type=\\"submit\\">Submit</button>";'>
  <label for="name">Name</label><input id="name" type="text">
  <button type="submit">Submit Application</button>
</form>
"""

# The gate rendered directly (no initial submit needed) — for the direct unit
# test of _resolve_verification_gate, which assumes the page is ALREADY
# showing the gate (exactly the state playwright_form_submitter hands it).
# Confirmation is shown ONLY when the exact code arrived, mirroring a real
# ATS's own server-side check, so a truthy confirmation PROVES the code that
# was READ FROM THE FAKE GMAIL is the one that got typed and accepted.
_GATE_ALREADY_SHOWING = """
<title>gate</title>
<p>We just emailed you a verification code.</p>
<input id="code" maxlength="8" aria-label="code">
<button type="submit" onclick="event.preventDefault();
    if (document.getElementById('code').value === 'AB12CD34') {
      document.body.innerHTML = '<h1>Thank you for applying</h1>';
    } else {
      document.body.innerHTML += '<p>Wrong code</p>';
    }">Submit</button>
"""

# CLI-SUB-005-R6/R7 mousedown-reveal shape (ported from
# test_cli_sub005_fill_commit.py's _MOUSEDOWN_REVEAL_FORM), COMBINED with a
# gate the onsubmit handler would show if — and only if — the guard failed to
# block the click. If the fold-in ever regresses into letting the
# verification-code loop run around an unresolved required field, this test
# would observe THAT (a verification_code_email outcome) instead of the guard
# reason, which is a stronger signal than merely "no exception at all".
_MOUSEDOWN_REVEAL_GATE_FORM = """
<title>mousedown-reveal-gate</title>
<form onsubmit='event.preventDefault();
    document.body.innerHTML = "<p>We just emailed you a verification code.</p>" +
      "<input id=\\"code\\" maxlength=\\"8\\" aria-label=\\"code\\">" +
      "<button type=\\"submit\\">Submit</button>";'>
  <div data-field-path="name">
    <label class="_required_abc123">Full name</label>
    <input id="name" name="name" type="text">
  </div>
  <button id="submit-btn" type="submit">Submit Application</button>
</form>
<script>
  document.getElementById('submit-btn').addEventListener('mousedown', function () {
    if (document.getElementById('late_reveal')) { return; }
    var input = document.createElement('input');
    input.type = 'text';
    input.id = 'late_reveal';
    // aria-required, not native `required` — see the identical comment in
    // test_cli_sub005_fill_commit.py's _MOUSEDOWN_REVEAL_FORM: a native
    // `required` empty field is blocked by the BROWSER'S OWN constraint
    // validation before 'submit' ever fires, masking the actual finding.
    input.setAttribute('aria-required', 'true');
    var label = document.createElement('label');
    label.setAttribute('for', 'late_reveal');
    label.textContent = 'Late reveal question';
    document.querySelector('form').appendChild(label);
    document.querySelector('form').appendChild(input);
  });
</script>
"""


class _FakeGmailService:
    """Stand-in for ``GmailService`` matching its own constructor shape
    (``__init__(self, user_id, account_id=None, creds_repo=None)``), per the
    house pattern in test_mon002_gmail_403_backoff.py / test_email_center_
    career_inbox.py. Returns ONE real-shaped code email, fresh as of
    construction time, containing a label-anchored code exactly like a real
    Greenhouse code mail (HTML body, tags between the label and the code).
    """

    def __init__(self, user_id: str, account_id: str | None = None, creds_repo: Any = None) -> None:
        self._user_id = user_id

    def list_message_headers(
        self, query: str | None = None, max_results: int = 10
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": "msg-u5d4-1",
                "from": "no-reply@greenhouse-mail.io",
                "subject": "Your Acme Corp verification code",
                "date": formatdate(time_module.time(), usegmt=True),
            }
        ]

    def get_message_bodies(self, message_id: str) -> dict[str, Any]:
        assert message_id == "msg-u5d4-1"
        # _extract_code_from_body's pattern 3 requires ONLY non-alphanumeric
        # characters between "...code" and the captured value (label-anchored,
        # no unrelated word like "is" allowed to sit in between) — exactly
        # like a real Greenhouse code mail's "verification code: XXXXXXXX".
        return {
            "text": "",
            "html": (
                "<div>Your <b>verification code</b>: "
                "<span>AB12CD34</span></div>"
            ),
        }


# ---------------------------------------------------------------------------
# 1. Happy path — the code is read from the user's OWN connected Gmail,
#    typed the way a human does, and the resubmit is what the confirmation
#    check actually verifies.
# ---------------------------------------------------------------------------


def test_resolve_verification_gate_reads_code_from_users_own_gmail_and_resubmits(
    tmp_path,
) -> None:
    from playwright.sync_api import sync_playwright

    from app.services.apply_executor import _resolve_verification_gate

    with sync_playwright() as runner:
        browser = runner.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        try:
            page = browser.new_page()
            page.set_content(_GATE_ALREADY_SHOWING, wait_until="domcontentloaded")
            result = _resolve_verification_gate(
                page,
                application_id="u5d4-happy",
                evidence_dir=str(tmp_path),
                since_epoch=time_module.time() - 5,
                user_id="u5d4-test-user",
                company="Acme Corp",
                form_email="jordan.blake@example.com",
                gmail_factory=_FakeGmailService,
                interval_seconds=0.01,
                timeout_seconds=2,
            )
            assert result["gateDetected"] is True
            assert result["codeSource"] == "connected_gmail"
            assert result["codeLength"] == 8
            assert result["resubmitted"] is True
            assert result["from"] == "no-reply@greenhouse-mail.io"
            # PROOF the code the fake Gmail returned is the code that was
            # actually typed and accepted — the page's own onclick handler
            # only shows this text for the exact value "AB12CD34".
            assert "thank you" in page.inner_text("body").lower()
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# 2. Without a user_id, the gate is an honest, immediate manual step — never
#    an attempt to work around it.
# ---------------------------------------------------------------------------


def test_live_submitter_gate_without_user_id_is_an_honest_manual_step(tmp_path) -> None:
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="u5d4-no-user",
            channel="generic",
            page_html="",
            apply_url=_data_url(_GATE_TRIGGER_FORM),
            plan={"fields": [_name_plan_field()]},
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            user_id=None,
            company="Acme Corp",
        )
    err = exc_info.value
    assert err.reason == "verification_code_email"
    assert "Acme Corp" in err.message
    assert "had no connected mailbox" in err.message
    assert "NOT accepted" in err.message


# ---------------------------------------------------------------------------
# 3. A Gmail read failure (no connected account — the real GmailService,
#    real DB lookup, zero mocks) is the same honest manual step, naming the
#    employer and the address the code was sent to.
# ---------------------------------------------------------------------------


def test_live_submitter_gate_with_unconnected_gmail_names_the_employer(tmp_path) -> None:
    from app.services.apply_executor import playwright_form_submitter

    # A real-shaped user id with NO row in GmailAccount: the REAL GmailService
    # (no gmail_factory override — playwright_form_submitter does not expose
    # one, by design: production always uses the real service) raises
    # GmailNotConnectedError from its own DB-backed credential lookup, which
    # _poll_verification_code converts into the honest manual step.
    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="u5d4-no-gmail",
            channel="generic",
            page_html="",
            apply_url=_data_url(_GATE_TRIGGER_FORM),
            plan={"fields": [_name_plan_field()]},
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            user_id="00000000-u5d4-0000-0000-000000000001",
            company="Acme Corp",
        )
    err = exc_info.value
    assert err.reason == "verification_code_email"
    assert "Acme Corp" in err.message
    assert "could not read your connected Gmail" in err.message
    assert "jordan.blake@example.com" in err.message
    assert "NOT accepted" in err.message


# ---------------------------------------------------------------------------
# 4. THE DECISIVE INVARIANT: the verification-code loop can never create a
#    path around CLI-SUB-005-R7's fail-closed submission guard. A required
#    field revealed at the exact instant of the FORM'S OWN first submit click
#    must still refuse via the guard's own reason — the gate-detection /
#    Gmail-code machinery must never even be reached.
# ---------------------------------------------------------------------------


def test_verification_gate_never_bypasses_the_r7_submission_guard(tmp_path) -> None:
    from app.services.apply_executor import playwright_form_submitter

    plan = {
        "fields": [
            {
                "name": "name",
                "label": "Full name",
                "kind": "text",
                "required": True,
                "scope": '[data-field-path="name"]',
                "value": "Jordan Blake",
                "options": [],
            }
        ]
    }
    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="u5d4-guard-first-click",
            channel="ashby",
            page_html="",
            apply_url=_data_url(_MOUSEDOWN_REVEAL_GATE_FORM),
            plan=plan,
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},
            answer_bank=None,
            # A user_id IS supplied, deliberately: if the guard ever failed
            # to preempt the gate check, this user_id would make the loop
            # attempt a REAL Gmail read next — proving the guard, not a
            # missing user_id, is what stops this.
            user_id="u5d4-test-user",
            company="Acme Corp",
        )
    err = exc_info.value
    # The R7 guard's own reason — NOT the verification-code loop's. If this
    # ever regresses to "verification_code_email", the loop ran on a click
    # the guard should have blocked outright.
    assert err.reason == "unplanned_required_field"
    assert err.question is not None and "late reveal" in err.question.lower()


def test_resolve_verification_gate_resubmit_is_also_guard_checked(tmp_path) -> None:
    """The code-entry resubmit inside _resolve_verification_gate is read back
    through the SAME guard as the form's own first click — not merely
    inherited by being unreachable, but actively re-checked after its own
    click, exactly like CLI-SUB-005-R6/R7 demand for every submit attempt.

    RUN-20260818T0223Z/SUB-011 adversarial review (P0,
    06-u5d4-adversarial-review.md): the ORIGINAL version of this test
    manually called _install_submission_guard(page) itself before invoking
    _resolve_verification_gate, which masked the finding — production never
    makes that call from anywhere except _resolve_verification_gate's own
    (now-added) re-install at its top. This version deliberately does NOT
    install the guard itself: the ONLY thing that can arm it here is
    _resolve_verification_gate's own production code."""
    from playwright.sync_api import sync_playwright

    from app.services.apply_executor import _resolve_verification_gate

    # The code box accepts ANY code and, on "submit", reveals a brand-new
    # required field via a mousedown handler on the resubmit button itself —
    # the SAME mechanism CLI-SUB-005-R6/R7 close for the form's first click,
    # here on the SECOND (code-entry) click _resolve_verification_gate makes.
    gate_with_resubmit_reveal = """
<title>gate-resubmit-reveal</title>
<p>We just emailed you a verification code.</p>
<input id="code" maxlength="8" aria-label="code">
<button id="resubmit-btn" type="submit" onclick="event.preventDefault();
    document.body.innerHTML = '<h1>Thank you for applying</h1>';">Submit</button>
<script>
  document.getElementById('resubmit-btn').addEventListener('mousedown', function () {
    if (document.getElementById('late_reveal')) { return; }
    var input = document.createElement('input');
    input.type = 'text';
    input.id = 'late_reveal';
    input.setAttribute('aria-required', 'true');
    input.setAttribute('data-aether-live-field', 'true');
    document.body.appendChild(input);
  });
</script>
"""

    with sync_playwright() as runner:
        browser = runner.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        try:
            page = browser.new_page()
            page.set_content(gate_with_resubmit_reveal, wait_until="domcontentloaded")
            # Deliberately NO manual guard install here (see the docstring
            # above) — _resolve_verification_gate must arm it itself.
            with pytest.raises(ManualStepRequired) as exc_info:
                _resolve_verification_gate(
                    page,
                    application_id="u5d4-resubmit-guard",
                    evidence_dir=str(tmp_path),
                    since_epoch=time_module.time() - 5,
                    user_id="u5d4-test-user",
                    company="Acme Corp",
                    form_email="jordan.blake@example.com",
                    gmail_factory=_FakeGmailService,
                    interval_seconds=0.01,
                    timeout_seconds=2,
                )
            err = exc_info.value
            # The guard's own reason for a census that could not (safely) run
            # is "unverifiable_form_surface"; for an ordinary revealed
            # required field it is "unplanned_required_field" — either is
            # proof the resubmit was guard-checked, never a silent success.
            assert err.reason in ("unplanned_required_field", "unverifiable_form_surface")
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# 5. RUN-20260818T0223Z/SUB-011 adversarial review, P0
#    (06-u5d4-adversarial-review.md): _install_submission_guard arms the R6/
#    R7 guard via a ONE-SHOT evaluate() call (event listeners on that
#    document) — not page.add_init_script, which is what this file uses
#    elsewhere specifically because it survives navigation
#    (_CLOSED_SHADOW_MARKER_INIT_JS). A standard multi-page (non-SPA) ATS
#    that reaches its verification-code gate via a REAL top-level navigation
#    (window.location.href, not an in-place innerHTML swap) therefore lands
#    on a document with NO guard armed at all — exactly the shape every
#    other test in this file's section 4 does NOT cover, because all of them
#    construct the gate via event.preventDefault() + innerHTML on the SAME
#    document. This section reproduces the reviewer's own proof shape: two
#    pages, the gate on page 2, a required field revealed via mousedown on
#    page 2's OWN resubmit button — the identical CLI-SUB-005-R6/R7 attack,
#    relocated across a real navigation.
# ---------------------------------------------------------------------------

# Page 2: the gate, reached by navigation rather than an innerHTML swap. Its
# OWN resubmit button reveals a brand-new required field via mousedown —
# nothing here differs from _MOUSEDOWN_REVEAL_GATE_FORM's mechanism except
# that this document was never present when playwright_form_submitter armed
# the guard on page 1.
_NAV_GATE_PAGE2 = """
<title>gate-page2</title>
<p>We just emailed you a verification code.</p>
<input id="code" maxlength="8" aria-label="code">
<button id="resubmit-btn" type="submit" onclick="event.preventDefault();
    document.body.innerHTML = '<h1>Thank you for applying</h1>';">Submit</button>
<script>
  document.getElementById('resubmit-btn').addEventListener('mousedown', function () {
    if (document.getElementById('late_reveal')) { return; }
    var input = document.createElement('input');
    input.type = 'text';
    input.id = 'late_reveal';
    input.setAttribute('aria-required', 'true');
    input.setAttribute('data-aether-live-field', 'true');
    document.body.appendChild(input);
  });
</script>
"""


def _nav_trigger_page1(page2_url: str) -> str:
    """Page 1: a well-behaved form whose submit performs a REAL top-level
    navigation to ``page2_url`` (``window.location.href =``), never an
    in-place DOM mutation on the same document — the exact distinction the
    P0 finding turns on. ``event.preventDefault()`` stops the browser's own
    default form-submit navigation so the ONLY navigation that happens is
    the deliberate one below, keeping the test's own timing deterministic.
    """
    return (
        "\n<title>nav-trigger</title>\n"
        "<form onsubmit='event.preventDefault(); "
        f'window.location.href = "{page2_url}";\'>\n'
        '  <label for="name">Name</label><input id="name" type="text">\n'
        '  <button type="submit">Submit Application</button>\n'
        "</form>\n"
    )


def test_verification_gate_reached_via_real_navigation_resubmit_still_guarded(
    tmp_path, monkeypatch
) -> None:
    """THE P0 REGRESSION, ported exactly from the adversarial reviewer's own
    proof shape: a required field revealed at the instant of the code-entry
    RESUBMIT, on a document reached by a REAL top-level navigation (not an
    innerHTML swap), must still refuse via the R6/R7 guard's own reason —
    never `no_confirmation` (guard silently absent, refusal only for an
    unrelated later reason) and never a silent submitted:true success.

    Real ``file://`` pages, not this file's usual ``_data_url`` — Chromium
    refuses a script-initiated TOP-LEVEL navigation to a ``data:`` URL
    outright (a security restriction, confirmed directly: ``window.location.
    href = "data:..."`` from a ``data:`` page is a silent no-op, `page.url`
    stays on page 1). ``file://`` has no such restriction and is the exact
    scheme the adversarial reviewer's own reproduction used.
    """
    from app.services.apply_executor import ManualStepRequired, playwright_form_submitter

    monkeypatch.setattr("app.services.gmail_service.GmailService", _FakeGmailService)

    page2_path = tmp_path / "u5d4-nav-page2.html"
    page2_path.write_text(_NAV_GATE_PAGE2)
    page2_url = "file://" + str(page2_path)
    page1_path = tmp_path / "u5d4-nav-page1.html"
    page1_path.write_text(_nav_trigger_page1(page2_url))
    page1_url = "file://" + str(page1_path)

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="u5d4-nav-guard",
            channel="generic",
            page_html="",
            apply_url=page1_url,
            plan={"fields": [_name_plan_field()]},
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path / "evidence"),
            user_id="u5d4-test-user",
            company="Acme Corp",
        )
    err = exc_info.value
    # The R6/R7 guard's own reason for the field the mousedown handler
    # revealed on page 2 — proof the guard was re-armed on the POST-
    # navigation document and caught the resubmit. `no_confirmation` (the
    # reviewer's reproduced failure mode: the resubmit went through
    # completely unguarded and only failed later, for an unrelated reason)
    # or any outcome reporting `submitted: True` would both be regressions.
    assert err.reason in ("unplanned_required_field", "unverifiable_form_surface")
    assert err.reason != "no_confirmation"
