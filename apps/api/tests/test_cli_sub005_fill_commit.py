"""CLI-SUB-005 (Architect D8) — browser fills must COMMIT, or nothing is submitted.

THE FLAGSHIP BUG. Live evidence (uat/reports/evidence/agents-uplift/u5/
submissions/apply-c9a2e4321e25f91cb0629b4f0-*.png): Submit was clicked on a
Cohere/Ashby form with EVERY required field empty ("Missing entry for required
field: Name/Email/Resume/Location"). Pre-fix live instrumentation on the same
form family (evidence/w1/A/pre-fix/, 2026-08-16) reproduced the mechanism:

* ``_fill_value``'s combobox branch probes the popup with ZERO waiting; on a
  live async widget (Ashby Location geocodes) every probe misses, the count==0
  free-text fallback re-types the answer and returns ``input_value()==text`` →
  ``True`` — but the text is never React-committed and the widget wipes it on
  blur. The executor then clicked Submit with a required field empty.
* The page carries an "Autofill from resume" ``input[type=file]`` OUTSIDE every
  ``[data-field-path]`` block; the file-fill fallback (``[id=]``/``[name=]``)
  never checked its match was a file input inside the field's own scope, so a
  variant where the scoped probe misses gambles the résumé into the autofill
  box — whose upload re-renders the form and wipes already-typed fields.
* Nothing read anything back before ``_activate_submit``.

Contract pinned here (all live-mode, ``verify=True``):

1. ``_fill_value`` file branch: only a verified ``input[type=file]`` INSIDE the
   field's own scope is ever used; otherwise refuse (honest ``False``).
2. ``_commit_state`` reads the control's committed DOM truth (input.value /
   :checked / Ashby ``_active`` class / file chip / combobox display).
3. ``_fill_and_verify``: fill → read back → ONE retry on mismatch → honest
   ``False``. ``_run_fill_plan(verify=False)`` keeps the replay contract
   (trust the raw fill — a replayed page is JS-dead by construction and no
   employer can receive anything from it).
4. ``_presubmit_required_commit_gate``: before submit, every REQUIRED planned
   field is re-verified committed; wiped fields get ONE refill pass; anything
   still empty raises ``ManualStepRequired('form_fill_failed')`` carrying the
   exact field labels — Submit is NEVER clicked over an empty required field.

Fake pages follow the existing style (test_apply_combobox_fill.py); three
tests drive the real ``playwright_form_submitter`` against synthetic
``data:`` URLs in a real headless Chromium — live-mode code path, zero
network, zero real employer.
"""
from __future__ import annotations

import base64
from typing import Any

import pytest

from app.services.apply_executor import ManualStepRequired, _fill_value

# ---------------------------------------------------------------------------
# Fakes — selector-substring keyed, per the repo's existing fake-page style.
# ---------------------------------------------------------------------------


class _Locator:
    def __init__(self, page: "_Page", key: str, spec: dict[str, Any]) -> None:
        self._page = page
        self._key = key
        self._spec = spec

    def count(self) -> int:
        return int(self._spec.get("count", 1))

    @property
    def first(self) -> "_Locator":
        return self

    def nth(self, idx: int) -> "_Locator":
        return self

    def click(self, timeout: int | None = None) -> None:
        self._page.actions.append(("click", self._key))
        hook = self._spec.get("on_click")
        if hook:
            hook()

    def fill(self, value: str, timeout: int | None = None) -> None:
        self._page.actions.append(("fill", self._key, value))
        hook = self._spec.get("on_fill")
        if hook:
            hook(value)

    def set_input_files(self, path: str, timeout: int | None = None) -> None:
        self._page.actions.append(("set_input_files", self._key, path))
        hook = self._spec.get("on_set_files")
        if hook:
            hook(path)

    def input_value(self, timeout: int | None = None) -> str:
        getter = self._spec.get("value")
        return getter() if callable(getter) else str(getter or "")

    def inner_text(self, timeout: int | None = None) -> str:
        return str(self._spec.get("text") or "")

    def evaluate(self, expression: str, arg: Any = None) -> Any:
        # Minimal DOM oracle for the three read-back evaluations the executor
        # performs: is-file-input, closest(scope) containment, files[0].name.
        if "el.type === 'file'" in expression:
            return bool(self._spec.get("is_file", False))
        if "closest" in expression:
            return bool(self._spec.get("inside_scope", False))
        if "el.files" in expression:
            getter = self._spec.get("file0")
            return getter() if callable(getter) else str(getter or "")
        if "selectedOptions" in expression:
            getter = self._spec.get("selected_text")
            return getter() if callable(getter) else str(getter or "")
        if "aria-expanded" in expression:
            getter = self._spec.get("aria_expanded")
            return getter() if callable(getter) else str(getter or "")
        if "blur" in expression:
            self._page.actions.append(("blur", self._key))
            hook = self._spec.get("on_blur")
            if hook:
                hook()
            return None
        return self._spec.get("evaluate_default")


class _Page:
    """Selector substrings → locator specs; unknown selectors count 0."""

    def __init__(self, specs: dict[str, dict[str, Any]]) -> None:
        self._specs = specs
        self.actions: list[tuple[Any, ...]] = []
        self.waited_ms = 0

    def locator(self, selector: str) -> _Locator:
        for key, spec in self._specs.items():
            if key in selector:
                return _Locator(self, key, spec)
        return _Locator(self, selector, {"count": 0})

    def wait_for_timeout(self, ms: int) -> None:
        self.waited_ms += ms


# ---------------------------------------------------------------------------
# 1. File-input scoping: never gamble on an out-of-scope input (the Ashby
#    "Autofill from resume" box). RED against the pre-fix executor, which
#    fell back to [id=]/[name=] with no scope/type check.
# ---------------------------------------------------------------------------

_RESUME_FIELD = {
    "name": "_systemfield_resume",
    "label": "Resume",
    "kind": "file",
    "required": True,
    "scope": '[data-field-path="_systemfield_resume"]',
}
_DOCS = {"__aether_resume_pdf__": "/tmp/aether-test/resume-abc.pdf"}


def test_file_fill_refuses_the_only_file_input_when_it_is_outside_the_scope() -> None:
    # Scoped probe misses; [id=...] matches a REAL file input that lives
    # OUTSIDE the field's own container — Ashby's autofill-from-resume box.
    page = _Page(
        {
            '[data-field-path="_systemfield_resume"] input[type=file]': {"count": 0},
            '[id="_systemfield_resume"]': {
                "count": 1,
                "is_file": True,
                "inside_scope": False,  # closest(scope) === null
            },
        }
    )
    assert _fill_value(page, _RESUME_FIELD, "__aether_resume_pdf__", _DOCS) is False
    assert not any(a[0] == "set_input_files" for a in page.actions), (
        "the resume must NEVER be uploaded into a file input outside the "
        "field's own scope (that is the autofill box that wipes the form)"
    )


def test_file_fill_refuses_a_non_file_element_matched_by_id() -> None:
    page = _Page(
        {
            '[data-field-path="_systemfield_resume"] input[type=file]': {"count": 0},
            '[id="_systemfield_resume"]': {"count": 1, "is_file": False, "inside_scope": True},
        }
    )
    assert _fill_value(page, _RESUME_FIELD, "__aether_resume_pdf__", _DOCS) is False
    assert not any(a[0] == "set_input_files" for a in page.actions)


def test_file_fill_uses_the_scoped_verified_input() -> None:
    state = {"file0": ""}
    page = _Page(
        {
            '[data-field-path="_systemfield_resume"] input[type=file]': {
                "count": 1,
                "is_file": True,
                "inside_scope": True,
                "file0": lambda: state["file0"],
                "on_set_files": lambda path: state.__setitem__("file0", "resume-abc.pdf"),
            },
        }
    )
    assert _fill_value(page, _RESUME_FIELD, "__aether_resume_pdf__", _DOCS) is True
    assert ("set_input_files", '[data-field-path="_systemfield_resume"] input[type=file]',
            "/tmp/aether-test/resume-abc.pdf") in page.actions


# ---------------------------------------------------------------------------
# 2. _commit_state — the DOM truth reader.
# ---------------------------------------------------------------------------


def test_commit_state_text_matches_only_the_committed_dom_value() -> None:
    from app.services.apply_executor import _commit_state

    field = {"name": "_systemfield_name", "kind": "text", "required": True, "scope": ""}
    committed = _Page({'[id="_systemfield_name"]': {"count": 1, "value": "Jordan Blake"}})
    assert _commit_state(committed, field, "Jordan Blake", {})[0] is True
    wiped = _Page({'[id="_systemfield_name"]': {"count": 1, "value": ""}})
    assert _commit_state(wiped, field, "Jordan Blake", {})[0] is False


def test_commit_state_choice_accepts_ashby_active_class_signal() -> None:
    # Live ground truth (evidence/w1/A/pre-fix): Ashby yes/no buttons commit
    # via a CSS class `_active_…` on the chosen button — checked/aria stay 0.
    from app.services.apply_executor import _commit_state

    field = {
        "name": "43acfb4b-5f91-40a6-a5b1-9faa0aa40645",
        "kind": "checkbox",
        "required": True,
        "scope": '[data-field-path="43acfb4b-5f91-40a6-a5b1-9faa0aa40645"]',
    }
    active = _Page({'[class*="_active"]': {"count": 1}})
    assert _commit_state(active, field, "No", {})[0] is True
    inert = _Page({})
    assert _commit_state(inert, field, "No", {})[0] is False


def test_commit_state_file_accepts_the_filename_chip_when_input_is_replaced() -> None:
    # Live ground truth: Greenhouse job-boards REMOVES the input[type=file]
    # node once the upload lands; the file-name chip is the only DOM evidence.
    from app.services.apply_executor import _commit_state

    field = {"name": "resume", "kind": "file", "required": True, "scope": ""}
    chip = _Page({'text="resume-abc.pdf"': {"count": 1}})
    assert _commit_state(chip, field, "__aether_resume_pdf__", _DOCS)[0] is True
    bare = _Page({})
    assert _commit_state(bare, field, "__aether_resume_pdf__", _DOCS)[0] is False


def test_commit_state_combobox_requires_display_text_and_closed_popup() -> None:
    from app.services.apply_executor import _commit_state

    field = {"name": "_systemfield_location", "kind": "combobox", "required": True, "scope": ""}
    committed = _Page(
        {'[id="_systemfield_location"]': {"count": 1, "value": "Toronto, Ontario, Canada",
                                          "aria_expanded": "false"}}
    )
    assert _commit_state(committed, field, "Toronto", {})[0] is True
    # The flagship live state: typed text still sitting in an OPEN popup is
    # not a committed answer (Ashby wipes it on blur).
    typed_only = _Page(
        {'[id="_systemfield_location"]': {"count": 1, "value": "Toronto", "aria_expanded": "true"}}
    )
    assert _commit_state(typed_only, field, "Toronto", {})[0] is False
    wiped = _Page(
        {'[id="_systemfield_location"]': {"count": 1, "value": "", "aria_expanded": "false"}}
    )
    assert _commit_state(wiped, field, "Toronto", {})[0] is False


# ---------------------------------------------------------------------------
# 3. _fill_and_verify — read back after every fill, retry ONCE, never claim.
# ---------------------------------------------------------------------------


def _text_field(name: str = "_systemfield_name", *, required: bool = True) -> dict[str, Any]:
    return {"name": name, "label": "Name", "kind": "text", "required": required,
            "scope": "", "value": "Jordan Blake"}


def test_fill_and_verify_reports_an_uncommitted_fill_as_unfilled() -> None:
    from app.services.apply_executor import _fill_and_verify

    # fill() is accepted but the DOM never retains the value (React wipe).
    page = _Page({'[id="_systemfield_name"]': {"count": 1, "value": ""}})
    field = _text_field()
    assert _fill_and_verify(page, field, "Jordan Blake", {}, verify=True) is False
    fills = [a for a in page.actions if a[0] == "fill"]
    assert len(fills) == 2, "exactly one retry after the first read-back mismatch"


def test_fill_and_verify_retry_succeeds_when_the_second_fill_commits() -> None:
    from app.services.apply_executor import _fill_and_verify

    state: dict[str, Any] = {"attempts": 0, "value": ""}

    def on_fill(value: str) -> None:
        state["attempts"] = int(state["attempts"]) + 1
        state["value"] = value if int(state["attempts"]) >= 2 else ""

    page = _Page(
        {'[id="_systemfield_name"]': {"count": 1, "value": lambda: state["value"],
                                      "on_fill": on_fill}}
    )
    assert _fill_and_verify(page, _text_field(), "Jordan Blake", {}, verify=True) is True
    assert state["attempts"] == 2


def test_fill_and_verify_does_not_retry_a_committed_fill() -> None:
    from app.services.apply_executor import _fill_and_verify

    state = {"value": ""}
    page = _Page(
        {'[id="_systemfield_name"]': {"count": 1, "value": lambda: state["value"],
                                      "on_fill": lambda v: state.__setitem__("value", v)}}
    )
    assert _fill_and_verify(page, _text_field(), "Jordan Blake", {}, verify=True) is True
    assert len([a for a in page.actions if a[0] == "fill"]) == 1


def test_run_fill_plan_verify_false_keeps_the_replay_contract() -> None:
    # Replay pages are JS-dead captures (network+scripts blocked); no employer
    # can receive anything from one, and React widgets can never mirror state
    # there — so replay trusts the raw fill exactly as before this fix.
    from app.services.apply_executor import _run_fill_plan

    page = _Page({'[id="_systemfield_name"]': {"count": 1, "value": ""}})
    filled, unfilled, blocked = _run_fill_plan(page, [_text_field()], {}, verify=False)
    assert filled == ["_systemfield_name"]
    assert unfilled == [] and blocked == []


def test_run_fill_plan_verify_true_blocks_an_uncommitted_required_field() -> None:
    from app.services.apply_executor import _run_fill_plan

    page = _Page({'[id="_systemfield_name"]': {"count": 1, "value": ""}})
    filled, unfilled, blocked = _run_fill_plan(page, [_text_field()], {}, verify=True)
    assert filled == []
    assert unfilled == ["_systemfield_name"]
    assert blocked == ["Name"]


# ---------------------------------------------------------------------------
# 4. The pre-submit gate — no empty application is ever fired at an employer.
# ---------------------------------------------------------------------------


def test_presubmit_gate_passes_when_every_required_field_is_committed() -> None:
    from app.services.apply_executor import _presubmit_required_commit_gate

    page = _Page({'[id="_systemfield_name"]': {"count": 1, "value": "Jordan Blake"}})
    _presubmit_required_commit_gate(page, [_text_field()], {})  # must not raise


def test_presubmit_gate_refills_a_wiped_field_once_then_passes() -> None:
    from app.services.apply_executor import _presubmit_required_commit_gate

    # The Ashby autofill scenario: the field WAS committed, a re-render wiped
    # it; the gate's single refill pass restores it.
    state = {"value": ""}
    page = _Page(
        {'[id="_systemfield_name"]': {"count": 1, "value": lambda: state["value"],
                                      "on_fill": lambda v: state.__setitem__("value", v)}}
    )
    _presubmit_required_commit_gate(page, [_text_field()], {})  # must not raise
    assert state["value"] == "Jordan Blake"


def test_presubmit_gate_refuses_with_exact_labels_when_refill_cannot_commit() -> None:
    from app.services.apply_executor import _presubmit_required_commit_gate

    page = _Page({'[id="_systemfield_name"]': {"count": 1, "value": ""}})
    with pytest.raises(ManualStepRequired) as exc_info:
        _presubmit_required_commit_gate(page, [_text_field()], {})
    err = exc_info.value
    assert err.reason == "form_fill_failed"
    assert err.question is not None and "Name" in err.question


def test_presubmit_gate_ignores_optional_and_unplanned_fields() -> None:
    from app.services.apply_executor import _presubmit_required_commit_gate

    optional = _text_field("nickname", required=False)
    unplanned = {"name": "extra", "label": "Extra", "kind": "text", "required": True,
                 "scope": "", "value": None}
    page = _Page({'[id="nickname"]': {"count": 1, "value": ""}})
    _presubmit_required_commit_gate(page, [optional, unplanned], {})  # must not raise


# ---------------------------------------------------------------------------
# 5. Combobox: the async-popup lie (the flagship Location mechanism).
# ---------------------------------------------------------------------------

_COMBO_FIELD = {"name": "_systemfield_location", "kind": "combobox", "required": True,
                "scope": ""}


def test_combobox_waits_for_the_async_popup_then_clicks_the_option() -> None:
    # Live Ashby Location: the popup populates asynchronously. The fill must
    # WAIT for it and CLICK the matching option — not conclude "no options"
    # from an instant probe and fall through to raw typing.
    page = _Page({'[id="_systemfield_location"]': {"count": 1, "value": "Toronto"}})
    ticks = {"n": 0}
    real_wait = page.wait_for_timeout

    def wait(ms: int) -> None:
        real_wait(ms)
        ticks["n"] += 1
        if ticks["n"] >= 1:  # popup has now populated
            page._specs['[role="option"]:has-text'] = {"count": 1}
            page._specs['[role="option"], [class*="select__option"]'] = {"count": 1}

    page.wait_for_timeout = wait  # type: ignore[method-assign]
    assert _fill_value(page, _COMBO_FIELD, "Toronto", {}) is True
    assert ("click", '[role="option"]:has-text') in page.actions, (
        "the popup option must actually be clicked once it renders — raw "
        "typed text is not a committed combobox answer"
    )


def test_combobox_free_text_fallback_must_survive_blur_to_count_as_filled() -> None:
    # The flagship lie: options never render, the fallback re-types the answer
    # and the widget wipes it on blur — that is NOT a fill.
    state = {"value": ""}
    page = _Page(
        {
            '[id="_systemfield_location"]': {
                "count": 1,
                "value": lambda: state["value"],
                "on_fill": lambda v: state.__setitem__("value", v),
                "on_blur": lambda: state.__setitem__("value", ""),  # React wipe
            }
        }
    )
    assert _fill_value(page, _COMBO_FIELD, "Toronto", {}) is False


def test_combobox_free_text_fallback_that_survives_blur_still_fills() -> None:
    # A genuine free-text combobox (or an inert replay DOM) keeps the text
    # through blur — that remains an honest fill.
    state = {"value": ""}
    page = _Page(
        {
            '[id="_systemfield_location"]': {
                "count": 1,
                "value": lambda: state["value"],
                "on_fill": lambda v: state.__setitem__("value", v),
            }
        }
    )
    assert _fill_value(page, _COMBO_FIELD, "Toronto", {}) is True


# ---------------------------------------------------------------------------
# 6. Live-mode end-to-end in a REAL headless Chromium against synthetic
#    ``data:`` pages — live code path, zero network, zero real employer.
# ---------------------------------------------------------------------------


def _data_url(html: str) -> str:
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


_WIPING_FORM = """
<title>wipe</title>
<form>
  <label for="name">Name</label><input id="name" type="text">
  <button type="submit" onclick="return false;">Submit Application</button>
</form>
<script>
  const n = document.getElementById('name');
  n.addEventListener('input', () => setTimeout(() => { n.value = ''; }, 30));
</script>
"""

# Confirmation is shown ONLY when the exact planned value arrived at submit
# time, mimicking a real ATS's required-field validation — so a truthy
# ``confirmation`` in the outcome PROVES the committed value crossed the
# submit boundary (a hash-based probe is unusable: data: URLs never surface
# fragment changes in page.url).
_HONEST_FORM = """
<title>ok</title>
<form onsubmit="event.preventDefault();
    if (document.getElementById('name').value === 'JordanBlake') {
      document.body.innerHTML = '<h1>Thank you for applying</h1>';
    } else {
      document.getElementById('err').textContent =
        'Missing entry for required field: Name';
    }">
  <label for="name">Name</label><input id="name" type="text">
  <button type="submit">Submit Application</button>
</form>
<div id="err"></div>
"""

_AUTOFILL_WIPE_FORM = """
<title>autofill</title>
<form onsubmit="event.preventDefault();
    if (document.getElementById('name').value === 'JordanBlake') {
      document.body.innerHTML = '<h1>Thank you for applying</h1>';
    } else {
      document.getElementById('err').textContent =
        'Missing entry for required field: Name';
    }">
  <label for="name">Name</label><input id="name" type="text">
  <label for="resume">Resume</label><input id="resume" type="file">
  <button type="submit">Submit Application</button>
</form>
<div id="err"></div>
<script>
  let wiped = false;
  document.getElementById('resume').addEventListener('change', () => {
    if (!wiped) { wiped = true;
      setTimeout(() => { document.getElementById('name').value = ''; }, 100); }
  });
</script>
"""


def _name_plan_field() -> dict[str, Any]:
    return {"name": "name", "label": "Name", "kind": "text", "required": True,
            "scope": "", "value": "JordanBlake", "options": []}


def test_live_submitter_never_submits_a_form_that_wipes_the_fill(tmp_path) -> None:
    """THE FLAGSHIP ASSERTION: a required fill the DOM did not keep must end in
    ManualStepRequired('form_fill_failed') — Submit is never clicked over an
    empty required field, and no 'submitted' outcome is ever returned."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005wipe",
            channel="generic",
            page_html="",
            apply_url=_data_url(_WIPING_FORM),
            plan={"fields": [_name_plan_field()]},
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
        )
    err = exc_info.value
    assert err.reason == "form_fill_failed"
    assert err.question is not None and "Name" in err.question


def test_live_submitter_submits_a_wellbehaved_form_with_confirmation(tmp_path) -> None:
    """Guard against over-refusal: commits that DO land still submit."""
    from app.services.apply_executor import playwright_form_submitter

    outcome = playwright_form_submitter(
        application_id="sub005ok",
        channel="generic",
        page_html="",
        apply_url=_data_url(_HONEST_FORM),
        plan={"fields": [_name_plan_field()]},
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
    )
    assert outcome["submitted"] is True
    assert outcome["unfilled"] == []
    # The page only confirms when the exact committed value arrived — this is
    # the proof the fill was real, not just that a button got clicked.
    assert outcome["confirmation"] and "thank you" in str(outcome["confirmation"]).lower()


def test_live_submitter_refills_a_field_wiped_by_a_file_upload(tmp_path) -> None:
    """The Ashby autofill-from-resume scenario end-to-end: the résumé upload
    re-render wipes an earlier committed field; the pre-submit gate detects it,
    refills it, and only then submits — the employer receives the real value."""
    from app.services.apply_executor import RESUME_DOCUMENT, playwright_form_submitter

    plan = {
        "fields": [
            _name_plan_field(),
            {"name": "resume", "label": "Resume", "kind": "file", "required": True,
             "scope": "", "value": RESUME_DOCUMENT, "options": []},
        ]
    }
    outcome = playwright_form_submitter(
        application_id="sub005refill",
        channel="generic",
        page_html="",
        apply_url=_data_url(_AUTOFILL_WIPE_FORM),
        plan=plan,
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
    )
    assert outcome["submitted"] is True
    # The page only confirms when the exact Name value was present at submit
    # time: the wiped field must have been REFILLED before the click — an
    # empty value here is exactly the flagship empty-application bug.
    assert outcome["confirmation"] and "thank you" in str(outcome["confirmation"]).lower()
