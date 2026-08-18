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
from html import escape as _html_attr_escape
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

    def select_option(self, *, label: str, timeout: int | None = None) -> None:
        self._page.actions.append(("select_option", self._key, label))
        hook = self._spec.get("on_select_option")
        if hook:
            hook(label)

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


def test_commit_state_select_reads_the_committed_selected_option_text() -> None:
    """CLI-SUB-005-R2 (adversarial review, finding #5): the reviewer found
    ZERO ``kind == "select"`` coverage anywhere in this file's 22 tests.
    ``_commit_state``'s select branch reads ``el.selectedOptions[0].textContent``
    back — this pins both the match and the mismatch."""
    from app.services.apply_executor import _commit_state

    field = {"name": "work_auth", "label": "Work Authorization", "kind": "select",
              "required": True, "scope": ""}
    committed = _Page({'[id="work_auth"]': {"count": 1, "selected_text": "Yes"}})
    assert _commit_state(committed, field, "Yes", {})[0] is True
    wrong = _Page({'[id="work_auth"]': {"count": 1, "selected_text": "No"}})
    assert _commit_state(wrong, field, "Yes", {})[0] is False
    empty = _Page({'[id="work_auth"]': {"count": 1, "selected_text": ""}})
    assert _commit_state(empty, field, "Yes", {})[0] is False


def test_fill_and_verify_select_commits_via_select_option_and_reads_it_back() -> None:
    """The full ``_fill_value`` -> ``_commit_state`` select round trip: filling
    calls ``select_option(label=...)`` and only counts once the DOM reflects
    the chosen option — a widget that accepts the click without actually
    selecting anything must be reported unfilled, not claimed."""
    from app.services.apply_executor import _fill_and_verify

    state = {"selected": ""}
    page = _Page(
        {
            '[id="work_auth"]': {
                "count": 1,
                "selected_text": lambda: state["selected"],
                "on_select_option": lambda label: state.__setitem__("selected", label),
            }
        }
    )
    field = {"name": "work_auth", "label": "Work Authorization", "kind": "select",
              "required": True, "scope": ""}
    assert _fill_and_verify(page, field, "Yes", {}, verify=True) is True
    assert ("select_option", '[id="work_auth"]', "Yes") in page.actions

    # The widget accepts the select_option call but never actually commits
    # (selectedOptions stays empty) -- must be reported unfilled, never faked.
    inert_page = _Page({'[id="work_auth"]': {"count": 1, "selected_text": ""}})
    assert _fill_and_verify(inert_page, field, "Yes", {}, verify=True) is False


# ---------------------------------------------------------------------------
# 7. CLI-SUB-005-R2 (adversarial review FAIL, 08-adversarial-review.md):
#    build_form_fill_plan runs ONCE against a STATIC, unanswered page
#    snapshot, before the browser session that fills/submits ever opens. A
#    conditional/branching question -- first-class on Ashby+Greenhouse -- is
#    structurally invisible to that plan, and the fill loop + the pre-submit
#    gate used to iterate ONLY that fixed plan["fields"] list. Reproduced
#    against the REAL playwright_form_submitter (not a mock): a required
#    field revealed 400ms after load was never attempted, never verified,
#    and the executor reported submitted:true, commitVerified:true anyway.
# ---------------------------------------------------------------------------

# The LIVE page: Name (in the plan) + a SECOND required field, "Visa status
# explanation", that satisfies this repo's OWN Greenhouse required-field
# convention (aria-required="true", trailing "*") but is revealed 400ms
# after load -- simulating a conditional follow-up question the initial
# page-snapshot fetch (before any answers existed) could not have seen.
_CONDITIONAL_LIVE_FORM = """
<title>conditional-field</title>
<form onsubmit="event.preventDefault();
    if (document.getElementById('name').value === 'JordanBlake' &&
        document.getElementById('visa_explain') &&
        document.getElementById('visa_explain').value === 'No sponsorship required') {
      document.body.innerHTML = '<h1>Thank you for applying</h1>';
    } else {
      document.getElementById('err').textContent = 'Missing required field';
    }">
  <label for="name">Name*</label><input id="name" type="text" aria-required="true">
  <div id="conditional"></div>
  <button type="submit">Submit Application</button>
</form>
<div id="err"></div>
<script>
  setTimeout(() => {
    document.getElementById('conditional').innerHTML =
      '<label for="visa_explain">Visa status explanation*</label>' +
      '<input id="visa_explain" type="text" aria-required="true">';
  }, 400);
</script>
"""


def test_live_submitter_blocks_a_post_snapshot_conditional_field_with_no_answer(
    tmp_path,
) -> None:
    """THE ADVERSARIAL-REVIEW BREAK, ported: a required field that exists in
    the LIVE DOM at submit time but was absent from the plan's static
    pre-fill snapshot must BLOCK submission, honestly -- never a VERIFIED,
    CONFIRMED outcome over an untouched required field. This is the test
    that FAILED before this fix (it reproduced the reviewer's
    attack_stale_plan.py break against the real submitter)."""
    from app.services.apply_executor import playwright_form_submitter

    plan = {
        "fields": [
            # NOTE: no "visa_explain" entry -- exactly what build_form_fill_plan
            # would have produced from a pre-conditional-reveal snapshot.
            _name_plan_field(),
        ]
    }
    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r2-block",
            channel="greenhouse",
            page_html="",
            apply_url=_data_url(_CONDITIONAL_LIVE_FORM),
            plan=plan,
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},  # no stored answer for "Visa status explanation"
        )
    err = exc_info.value
    assert err.reason == "unplanned_required_field"
    assert err.question is not None and "Visa status explanation" in err.question


def test_live_submitter_answers_a_post_snapshot_conditional_field_from_the_answer_bank(
    tmp_path,
) -> None:
    """Guard against over-refusal: when the SAME post-snapshot conditional
    field CAN be answered (here: the answer bank), it is filled, verified,
    and the submission proceeds -- the confirmation only fires when the
    live DOM holds the EXACT committed value at submit time, so a truthy
    confirmation proves the resolved answer really crossed the submit
    boundary."""
    from app.services.answer_bank import (
        PROVENANCE_USER_ANSWERED,
        SENSITIVITY_FACTUAL,
        AnswerBankMatch,
    )
    from app.services.apply_executor import playwright_form_submitter

    match = AnswerBankMatch(
        item_id="bank-item-1",
        answer="No sponsorship required",
        confidence=0.97,
        method="test",
        question_as_seen="Visa status explanation",
        banked_question="Visa status explanation",
        sensitivity=SENSITIVITY_FACTUAL,
        provenance=PROVENANCE_USER_ANSWERED,
        per_application=False,
    )

    def answer_bank(field: dict[str, Any]) -> Any:
        return match if field["name"] == "visa_explain" else None

    plan = {"fields": [_name_plan_field()]}
    outcome = playwright_form_submitter(
        application_id="sub005r2-answered",
        channel="greenhouse",
        page_html="",
        apply_url=_data_url(_CONDITIONAL_LIVE_FORM),
        plan=plan,
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
        profile={},
        answer_bank=answer_bank,
    )
    assert outcome["submitted"] is True
    assert outcome["confirmation"] and "thank you" in str(outcome["confirmation"]).lower()
    assert "visa_explain" in outcome["filled"]
    assert "visa_explain" in outcome["unplannedFilled"]


def test_resolve_unplanned_required_fields_bounds_an_endlessly_revealing_form() -> None:
    """The bounded re-scan loop terminates HONESTLY, not by looping forever.
    Every newly-revealed field in this synthetic form IS answerable and
    fillable (unlike the two tests above), so nothing here would ever stop
    the DOM from revealing yet another one on the next pass -- the only
    thing that can stop it is the pass bound itself."""
    from app.services.apply_executor import (
        _MAX_RESCAN_PASSES,
        ManualStepRequired,
        _resolve_unplanned_required_fields,
    )

    calls = {"n": 0}

    def growing_html() -> str:
        calls["n"] += 1
        fields = "".join(
            f'<label for="field_{i}">Field {i}*</label>'
            f'<input id="field_{i}" name="field_{i}">'
            for i in range(calls["n"])
        )
        return f"<form>{fields}</form>"

    total_fields = _MAX_RESCAN_PASSES + 5
    specs = {
        f'[id="field_{i}"]': {"count": 1, "value": "answered"} for i in range(total_fields)
    }
    page = _Page(specs)
    page.content = growing_html  # type: ignore[method-assign]
    profile = {"customAnswers": {f"field_{i}": "answered" for i in range(total_fields)}}

    with pytest.raises(ManualStepRequired) as exc_info:
        _resolve_unplanned_required_fields(
            page, "generic", [], {}, profile=profile, answer_bank=None,
        )
    assert exc_info.value.reason == "unplanned_required_field"
    # BOUNDED: the DOM was re-scanned a small, fixed number of times -- not
    # once per newly-revealed field forever.
    assert calls["n"] <= _MAX_RESCAN_PASSES + 2, (
        f"the re-scan loop must be bounded, not unbounded (scanned {calls['n']} times)"
    )


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


# ---------------------------------------------------------------------------
# 8. CLI-SUB-005-R3 (adversarial review FAIL,
#    RUN-20260818T0223Z/SUB-005-R2/08-adversarial-review-premerge.md): the
#    R2 fix ran _resolve_unplanned_required_fields ONCE, then the
#    pre-existing, unmodified _presubmit_required_commit_gate ONCE, in
#    sequence. The gate's OWN one-shot refill of a wiped required field is a
#    real fill/select_option Playwright action that can re-trigger the exact
#    JS reveal machinery a conditional question depends on -- and nothing
#    rescanned the DOM after that refill before Submit was clicked.
#    Reproduced live against the unmodified R2 code: submitted:true,
#    unplannedFilled:[] over a required 'explain' field that was never
#    attempted, never verified, sitting empty and visible in the DOM.
#
#    Ported here EXACTLY from the reviewer's own
#    adversarial/attack_gate_refill.py (same HTML, same plan, same résumé
#    upload timing) -- this is that attack script's scenario, captured as a
#    permanent regression test.
# ---------------------------------------------------------------------------

_GATE_REFILL_REVEALS_CONDITIONAL_FORM = """
<title>gate-refill-hole</title>
<form onsubmit="event.preventDefault();
    if (document.getElementById('name').value === 'JordanBlake' &&
        document.getElementById('sponsor').value === 'Yes') {
      document.body.innerHTML = '<h1>Thank you for applying</h1>';
    } else {
      document.getElementById('err').textContent = 'Missing required field';
    }">
  <label for="name">Name*</label><input id="name" type="text">
  <label for="sponsor">Sponsorship required?*</label>
  <select id="sponsor" onchange="onSponsorChange()">
    <option value="">--</option>
    <option value="Yes">Yes</option>
    <option value="No">No</option>
  </select>
  <div id="conditional"></div>
  <label for="resume">Resume</label><input id="resume" type="file">
  <button type="submit">Submit Application</button>
</form>
<div id="err"></div>
<script>
  function onSponsorChange() {
    var box = document.getElementById('conditional');
    if (document.getElementById('sponsor').value === 'Yes') {
      box.innerHTML =
        '<label for="explain">Explain*</label><input id="explain" type="text">';
    } else {
      box.innerHTML = '';
    }
  }
  let wiped = false;
  document.getElementById('resume').addEventListener('change', () => {
    if (!wiped) { wiped = true;
      setTimeout(() => {
        document.getElementById('name').value = '';
        document.getElementById('sponsor').value = '';
        onSponsorChange();
      }, 100); }
  });
</script>
"""


def _gate_refill_plan() -> dict[str, Any]:
    from app.services.apply_executor import RESUME_DOCUMENT

    return {
        "fields": [
            {"name": "name", "label": "Name", "kind": "text", "required": True,
             "scope": "", "value": "JordanBlake", "options": []},
            {"name": "sponsor", "label": "Sponsorship required?", "kind": "select",
             "required": True, "scope": "", "value": "Yes", "options": ["Yes", "No"]},
            {"name": "resume", "label": "Resume", "kind": "file", "required": True,
             "scope": "", "value": RESUME_DOCUMENT, "options": []},
        ]
    }


def test_live_submitter_never_submits_over_a_field_the_gate_refill_reveals(
    tmp_path,
) -> None:
    """THE R2->R3 ADVERSARIAL-REVIEW BREAK, ported exactly from
    adversarial/attack_gate_refill.py: the gate's own refill of a wiped
    'sponsor' select re-reveals the required 'explain' field, and nothing
    unanswerable may ever cross the submit boundary. On the unfixed R2 branch
    this raised nothing and returned submitted:true, unplannedFilled:[] --
    this is that exact break, captured as a permanent regression test."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r3-gatehole",
            channel="generic",
            page_html="",
            apply_url=_data_url(_GATE_REFILL_REVEALS_CONDITIONAL_FORM),
            plan=_gate_refill_plan(),
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},  # no stored answer for "Explain" — must not be guessed
            answer_bank=None,
        )
    err = exc_info.value
    assert err.reason == "unplanned_required_field"
    assert err.question is not None and "Explain" in err.question


def test_live_submitter_converges_and_submits_when_gate_refill_reveal_is_answerable(
    tmp_path,
) -> None:
    """Guard against over-refusal: the SAME gate-refill-revealed 'explain'
    field, when it CAN be answered (here: the answer bank), is filled,
    verified, and the submission proceeds — proving the fixed-point loop
    converges (rescans again after the gate's own refill) instead of either
    submitting blind or refusing a legitimately answerable form."""
    from app.services.answer_bank import (
        PROVENANCE_USER_ANSWERED,
        SENSITIVITY_FACTUAL,
        AnswerBankMatch,
    )
    from app.services.apply_executor import playwright_form_submitter

    match = AnswerBankMatch(
        item_id="bank-item-2",
        answer="Sponsorship not required",
        confidence=0.95,
        method="test",
        question_as_seen="Explain",
        banked_question="Explain",
        sensitivity=SENSITIVITY_FACTUAL,
        provenance=PROVENANCE_USER_ANSWERED,
        per_application=False,
    )

    def answer_bank(field: dict[str, Any]) -> Any:
        return match if field["name"] == "explain" else None

    outcome = playwright_form_submitter(
        application_id="sub005r3-gatehole-answered",
        channel="generic",
        page_html="",
        apply_url=_data_url(_GATE_REFILL_REVEALS_CONDITIONAL_FORM),
        plan=_gate_refill_plan(),
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
        profile={},
        answer_bank=answer_bank,
    )
    assert outcome["submitted"] is True
    assert outcome["confirmation"] and "thank you" in str(outcome["confirmation"]).lower()
    assert "explain" in outcome["filled"]
    assert "explain" in outcome["unplannedFilled"]


# ---------------------------------------------------------------------------
# 9. CLI-SUB-005-R4 (adversarial re-review FAIL,
#    RUN-20260818T0223Z/SUB-005-R3/08-adversarial-rereview.md, finding #1):
#    R3's ledger only tracked a required field's NAME being new, or a
#    PLANNED field's OWN frozen `required` flag going uncommitted — neither
#    signal notices an already-known, already-OPTIONAL field turning
#    required LIVE (no new node, same name, same plan entry, just a
#    live DOM mutation the ledger never re-checks). Reproduced live against
#    the unmodified R3 code: submitted:true, unplannedFilled:[] over a
#    required 'explain' field that was already in the plan as optional and
#    unanswered, and was never attempted, never verified, never raised as a
#    manual step once it turned required.
#
#    Ported here from the reviewer's own
#    adversarial/attack2_required_toggle_escapes_ledger.py (same HTML, same
#    plan — 'explain' pre-seeded as an OPTIONAL, unanswered planned field,
#    exactly what build_form_fill_plan would have produced for it in the
#    original static snapshot) — this is that attack script's scenario,
#    captured as a permanent regression test.
# ---------------------------------------------------------------------------

_REQUIRED_TOGGLE_ESCAPES_LEDGER_FORM = """
<title>required-toggle-ledger-escape</title>
<form onsubmit="event.preventDefault();
    if (document.getElementById('name').value === 'JordanBlake' &&
        document.getElementById('sponsor').value === 'Yes') {
      document.body.innerHTML = '<h1>Thank you for applying</h1>';
    } else {
      document.getElementById('err').textContent = 'Missing required field';
    }">
  <label for="name">Name*</label><input id="name" type="text">
  <label for="sponsor">Sponsorship required?*</label>
  <select id="sponsor" onchange="onSponsorChange()">
    <option value="">--</option>
    <option value="Yes">Yes</option>
    <option value="No">No</option>
  </select>
  <label id="explain_label" for="explain">Explain</label>
  <input id="explain" type="text">
  <button type="submit">Submit Application</button>
</form>
<div id="err"></div>
<script>
  function onSponsorChange() {
    var el = document.getElementById('explain');
    var lbl = document.getElementById('explain_label');
    if (document.getElementById('sponsor').value === 'Yes') {
      // aria-required (not the native `required` attribute) -- exactly
      // what a React-driven ATS form uses for a custom-validated field, and
      // deliberately does NOT trigger the browser's native constraint
      // validation, so this isolates the app-level convergence logic
      // instead of being caught by an unrelated browser backstop.
      el.setAttribute('aria-required', 'true');
      lbl.textContent = 'Explain*';
    } else {
      el.removeAttribute('aria-required');
      lbl.textContent = 'Explain';
    }
  }
</script>
"""


def _required_toggle_plan() -> dict[str, Any]:
    # 'explain' is present in the DOM from page load, NOT required, and was
    # already scanned into the plan (value=None, required=False) -- exactly
    # what build_form_fill_plan would have produced for an optional,
    # unanswered field it saw in the static snapshot. It is therefore
    # already a KNOWN planned field before _converge_presubmit_state ever
    # runs -- the precise precondition the R3 ledger was blind to.
    return {
        "fields": [
            {"name": "name", "label": "Name", "kind": "text", "required": True,
             "scope": "", "value": "JordanBlake", "options": []},
            {"name": "sponsor", "label": "Sponsorship required?", "kind": "select",
             "required": True, "scope": "", "value": "Yes", "options": ["Yes", "No"]},
            {"name": "explain", "label": "Explain", "kind": "text",
             "required": False, "scope": "", "value": None, "options": []},
        ]
    }


def test_live_submitter_never_submits_over_a_known_field_that_turns_required_live(
    tmp_path,
) -> None:
    """THE R3->R4 ADVERSARIAL-REVIEW BREAK, ported exactly from
    adversarial/attack2_required_toggle_escapes_ledger.py: an already-KNOWN,
    already-OPTIONAL planned field ('explain') turns required live via a
    sibling field's onchange, and nothing unanswerable may ever cross the
    submit boundary. On the unfixed R3 branch this raised nothing and
    returned submitted:true, unplannedFilled:[] -- this is that exact break,
    captured as a permanent regression test."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r4-toggleescape",
            channel="generic",
            page_html="",
            apply_url=_data_url(_REQUIRED_TOGGLE_ESCAPES_LEDGER_FORM),
            plan=_required_toggle_plan(),
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},  # no stored answer for "Explain" — must not be guessed
            answer_bank=None,
        )
    err = exc_info.value
    assert err.reason == "unplanned_required_field"
    assert err.question is not None and "Explain" in err.question


def test_live_submitter_converges_and_submits_when_the_toggled_field_is_answerable(
    tmp_path,
) -> None:
    """Guard against over-refusal: the SAME toggled-required 'explain'
    field, when it CAN be answered (here: the answer bank), is filled,
    verified, and the submission proceeds — proving the total-re-derivation
    loop resolves a known-but-now-required field exactly like any other
    newly discovered one, instead of either submitting blind or refusing a
    legitimately answerable form."""
    from app.services.answer_bank import (
        PROVENANCE_USER_ANSWERED,
        SENSITIVITY_FACTUAL,
        AnswerBankMatch,
    )
    from app.services.apply_executor import playwright_form_submitter

    match = AnswerBankMatch(
        item_id="bank-item-3",
        answer="Sponsorship not required",
        confidence=0.95,
        method="test",
        question_as_seen="Explain",
        banked_question="Explain",
        sensitivity=SENSITIVITY_FACTUAL,
        provenance=PROVENANCE_USER_ANSWERED,
        per_application=False,
    )

    def answer_bank(field: dict[str, Any]) -> Any:
        return match if field["name"] == "explain" else None

    outcome = playwright_form_submitter(
        application_id="sub005r4-toggleescape-answered",
        channel="generic",
        page_html="",
        apply_url=_data_url(_REQUIRED_TOGGLE_ESCAPES_LEDGER_FORM),
        plan=_required_toggle_plan(),
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
        profile={},
        answer_bank=answer_bank,
    )
    assert outcome["submitted"] is True
    assert outcome["confirmation"] and "thank you" in str(outcome["confirmation"]).lower()
    assert "explain" in outcome["filled"]
    assert "explain" in outcome["unplannedFilled"]


def test_converge_presubmit_state_bounds_an_endlessly_revealing_form() -> None:
    """The fixed-point loop terminates HONESTLY, not by looping forever: a
    synthetic DOM that reveals one more answerable required field every
    single pass can never reach a nothing-changed iteration, so the only
    thing that can stop it is the resolving-pass bound itself — mirroring
    test_resolve_unplanned_required_fields_bounds_an_endlessly_revealing_form
    for the merged loop. Imports :data:`_MAX_CONVERGENCE_PASSES` directly
    rather than hard-coding it, so this ALSO proves CLI-SUB-005-R4's raised
    bound (4 -> 6, RUN-20260818T0223Z/SUB-005-R3/08-adversarial-rereview.md)
    is still a genuine, enforced cap — an unbounded/adversarial form is
    refused honestly at the new bound too, never accepted."""
    from app.services.apply_executor import (
        _MAX_CONVERGENCE_PASSES,
        ManualStepRequired,
        _converge_presubmit_state,
    )

    calls = {"n": 0}

    def growing_html() -> str:
        calls["n"] += 1
        fields = "".join(
            f'<label for="field_{i}">Field {i}*</label>'
            f'<input id="field_{i}" name="field_{i}">'
            for i in range(calls["n"])
        )
        return f"<form>{fields}</form>"

    total_fields = _MAX_CONVERGENCE_PASSES + 5
    specs = {
        f'[id="field_{i}"]': {"count": 1, "value": "answered"} for i in range(total_fields)
    }
    page = _Page(specs)
    page.content = growing_html  # type: ignore[method-assign]
    profile = {"customAnswers": {f"field_{i}": "answered" for i in range(total_fields)}}

    with pytest.raises(ManualStepRequired) as exc_info:
        _converge_presubmit_state(
            page, "generic", [], {}, profile=profile, answer_bank=None,
        )
    assert exc_info.value.reason == "unplanned_required_field"
    # BOUNDED: the merged loop ran a small, fixed number of top-level passes
    # -- not once per newly-revealed field forever.
    assert calls["n"] <= _MAX_CONVERGENCE_PASSES + 1, (
        f"the convergence loop must be bounded, not unbounded (scanned {calls['n']} times)"
    )


def _run_terminating_chain(total_fields: int) -> tuple[list[str], int]:
    """Drive :func:`_converge_presubmit_state` against a synthetic DOM that
    reveals exactly ``total_fields`` required fields, one newly-discoverable
    field per ``page.content()`` call, then STOPS growing. Returns
    ``(resolved_names, schema_call_count)``."""
    from app.services.apply_executor import _converge_presubmit_state

    calls = {"n": 0}

    def terminating_html() -> str:
        calls["n"] += 1
        n_fields = min(calls["n"], total_fields)
        fields = "".join(
            f'<label for="field_{i}">Field {i}*</label>'
            f'<input id="field_{i}" name="field_{i}">'
            for i in range(n_fields)
        )
        return f"<form>{fields}</form>"

    specs = {
        f'[id="field_{i}"]': {"count": 1, "value": "answered"}
        for i in range(total_fields)
    }
    page = _Page(specs)
    page.content = terminating_html  # type: ignore[method-assign]
    profile = {
        "customAnswers": {f"field_{i}": "answered" for i in range(total_fields)}
    }

    resolved = _converge_presubmit_state(
        page, "generic", [], {}, profile=profile, answer_bank=None,
    )
    return resolved, calls["n"]


def test_converge_presubmit_state_accepts_a_depth_four_chain() -> None:
    """CLI-SUB-005-R4 (adversarial re-review FAIL,
    RUN-20260818T0223Z/SUB-005-R3/08-adversarial-rereview.md, finding #2): a
    4-deep legitimately-terminating chain was WRONGLY REFUSED on R3, because
    R3's bound (also 4) counted the confirming "did anything change?" pass
    INSIDE the same budget as the resolving passes, leaving no room for the
    pass that proves a 4-deep chain is actually finished — the R2 off-by-one,
    reproduced one bound deeper instead of eliminated
    (``adversarial/attack4b_depth_sweep.py``: depth=4 REFUSED on R3). R4's
    decoupled loop (the confirming re-derivation is never counted against the
    resolving-pass bound) must accept this exact depth."""
    resolved, calls = _run_terminating_chain(4)
    assert set(resolved) == {"field_0", "field_1", "field_2", "field_3"}
    # 4 resolving passes (one field discovered per pass) + exactly ONE free,
    # uncounted confirming pass that sees the chain has stopped growing.
    assert calls == 5


def test_converge_presubmit_state_accepts_a_chain_that_terminates_exactly_at_the_bound() -> None:
    """A legitimately-terminating conditional chain that needs every
    resolving pass :data:`_MAX_CONVERGENCE_PASSES` (6, post-R4) allows must
    NOT be refused just because it took that many passes to resolve — this is
    the R4 bound's own version of the R2 off-by-one class
    (08-adversarial-review-premerge.md section 3; re-broken one bound deeper
    by R3, per RUN-20260818T0223Z/SUB-005-R3/08-adversarial-rereview.md
    finding #2). R4's loop structure decouples resolving passes from the
    confirming pass entirely (see :func:`_converge_presubmit_state`), so
    raising the bound is no longer the only thing standing between a valid
    depth-N chain and an off-by-one refusal — this pins that a chain exactly
    as deep as the bound itself still converges cleanly."""
    from app.services.apply_executor import _MAX_CONVERGENCE_PASSES

    resolved, calls = _run_terminating_chain(_MAX_CONVERGENCE_PASSES)
    assert set(resolved) == {f"field_{i}" for i in range(_MAX_CONVERGENCE_PASSES)}
    # _MAX_CONVERGENCE_PASSES resolving passes (one field discovered per
    # pass) + exactly ONE free, uncounted confirming pass — never refused for
    # simply needing the full resolving budget.
    assert calls == _MAX_CONVERGENCE_PASSES + 1


def test_converge_presubmit_state_refuses_a_chain_one_deeper_than_the_bound() -> None:
    """The bound is still a REAL bound after R4's decoupling — a chain one
    resolving pass deeper than :data:`_MAX_CONVERGENCE_PASSES` can allow must
    still be refused honestly, never accepted by an off-by-one in the OTHER
    direction."""
    from app.services.apply_executor import _MAX_CONVERGENCE_PASSES

    with pytest.raises(ManualStepRequired) as exc_info:
        _run_terminating_chain(_MAX_CONVERGENCE_PASSES + 1)
    assert exc_info.value.reason == "unplanned_required_field"


# ---------------------------------------------------------------------------
# 10. CLI-SUB-005-R5 (adversarial FAIL,
#     RUN-20260818T0223Z/SUB-005-R4/08-adversarial-final.md): a required
#     field living ONLY inside an <iframe> was structurally invisible to
#     _uncommitted_live_required_fields on every pass, because its only
#     input is parse_form_schema(page.content()) — a single top-level
#     document. R5 closes this two ways per
#     05-decision-memos/SUB-005-and-COV-3-rulings.md: (a) extend the
#     re-derivation across every reachable Playwright frame
#     (_converge_presubmit_state), and (b) a CONSERVATIVE REFUSE-BACKSTOP
#     (_verify_no_unverifiable_form_surface) that refuses over ANY
#     form-shaped control no parser call anywhere can classify, or any
#     frame that cannot even be read — making soundness independent of
#     parser vocabulary. Ported here from the reviewer's own
#     adversarial/attack5_iframe_live_reveal.py (identical outer form, same
#     plan — "name" is the only planned field, exactly what
#     build_form_fill_plan would have produced from the static snapshot
#     before the iframe widget populated).
# ---------------------------------------------------------------------------

_IFRAME_OUTER_TEMPLATE = """
<title>iframe-embedded-widget</title>
<form onsubmit="event.preventDefault();
    document.body.innerHTML = '<h1>Thank you for applying</h1>';">
  <div data-field-path="name">
    <label class="_required_abc123">Full name</label>
    <input id="name" name="name" type="text">
  </div>
  <iframe id="survey-widget" srcdoc="{inner}"></iframe>
  <button type="submit">Submit Application</button>
</form>
"""

# The iframe's OWN document: a required Ashby-shaped question that starts
# OPTIONAL and is flipped required by a script inside the SAME iframe
# document once its own onload fires — the exact "live requiredness toggle"
# class R4 was built to catch, just one document boundary deeper. No
# standard-profile analogue and no answer bank match — genuinely
# unanswerable, so the only honest outcome is a refusal.
_IFRAME_INNER_REQUIRED_UNANSWERABLE = """
<div data-field-path="consent_survey">
  <label>Diversity survey</label>
  <input id="consent_survey" name="consent_survey" type="text">
</div>
<script>
  document.getElementById('consent_survey')
    .closest('[data-field-path]')
    .querySelector('label')
    .className = '_required_abc123';
</script>
"""

# The SAME class of iframe-embedded, live-only required field, but one the
# profile CAN answer — via the kind="email" fallback _answer_for already
# uses for any field whose control is type="email", regardless of its name.
_IFRAME_INNER_REQUIRED_ANSWERABLE = """
<div data-field-path="confirm_email">
  <label class="_required_abc123">Confirm your email</label>
  <input id="confirm_email" name="confirm_email" type="email">
</div>
"""


def _iframe_form(inner_html: str) -> str:
    # The inner document's own markup is full of double-quoted attributes
    # (id="...", data-field-path="...") which would otherwise prematurely
    # terminate the OUTER srcdoc="..." attribute at the first one — HTML
    # entity-escape it exactly the way a browser expects an attribute VALUE
    # to be escaped, so the real inner document survives intact.
    return _IFRAME_OUTER_TEMPLATE.format(inner=_html_attr_escape(inner_html, quote=True))


def _name_only_plan() -> dict[str, Any]:
    return {
        "fields": [
            {
                "name": "name",
                "label": "Full name",
                "kind": "text",
                "required": True,
                "scope": '[data-field-path="name"]',
                "value": "Jordan Blake",
                "options": [],
            },
        ]
    }


def test_live_submitter_never_submits_over_an_unanswerable_iframe_required_field(
    tmp_path,
) -> None:
    """THE R4->R5 ADVERSARIAL-REVIEW BREAK, ported exactly from
    adversarial/attack5_iframe_live_reveal.py: on the unfixed R4 branch this
    returned submitted:true, confirmation:"Thank you for applying",
    unplannedFilled:[] — the iframe field was never attempted, never
    verified, never raised as a manual step, because page.content() cannot
    see inside an <iframe srcdoc> at all. With no profile/answer-bank able
    to answer "Diversity survey", the R5 per-frame convergence must resolve
    or refuse it — never guess, never submit."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r5-iframe-unanswerable",
            channel="ashby",
            page_html="",
            apply_url=_data_url(_iframe_form(_IFRAME_INNER_REQUIRED_UNANSWERABLE)),
            plan=_name_only_plan(),
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},
            answer_bank=None,
        )
    err = exc_info.value
    assert err.reason == "unplanned_required_field"
    assert err.question is not None and "Diversity survey" in err.question


def test_live_submitter_resolves_and_submits_an_answerable_iframe_required_field(
    tmp_path,
) -> None:
    """Guard against over-refusal: the SAME class of iframe-embedded,
    live-only required field, when it CAN genuinely be answered, is
    discovered by the per-frame re-derivation, filled and verified INSIDE
    the iframe's own document (never the top page), and the submission
    proceeds — proving the R5 frame extension resolves a legitimately
    answerable iframe field exactly like any other newly discovered one,
    instead of either submitting blind or refusing a form that could
    genuinely be completed."""
    from app.services.apply_executor import playwright_form_submitter

    outcome = playwright_form_submitter(
        application_id="sub005r5-iframe-answerable",
        channel="ashby",
        page_html="",
        apply_url=_data_url(_iframe_form(_IFRAME_INNER_REQUIRED_ANSWERABLE)),
        plan=_name_only_plan(),
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
        profile={"email": "jordan@example.com"},
        answer_bank=None,
    )
    assert outcome["submitted"] is True
    assert outcome["confirmation"] and "thank you" in str(outcome["confirmation"]).lower()
    assert "confirm_email" in outcome["filled"]
    assert "confirm_email" in outcome["unplannedFilled"]


_UNCLASSIFIABLE_CONTROL_FORM = """
<title>unclassifiable-widget</title>
<form onsubmit="event.preventDefault();
    document.body.innerHTML = '<h1>Thank you for applying</h1>';">
  <div data-field-path="name">
    <label class="_required_abc123">Full name</label>
    <input id="name" name="name" type="text">
  </div>
  <div role="combobox" aria-expanded="false" class="team-picker">Pick a team</div>
  <button type="submit">Submit Application</button>
</form>
"""


def test_unclassifiable_custom_control_refuses_via_backstop(tmp_path) -> None:
    """SUB-005-R5 CONSERVATIVE REFUSE-BACKSTOP: a custom ARIA widget
    (``role="combobox"``) with NO underlying ``<input>``/``<select>``/
    ``<textarea>`` and no ``[data-field-path]``/``id``/``name`` any channel
    parser could ever key off of — exactly the class
    RUN-20260818T0223Z/SUB-005-R4/08-adversarial-final.md named as a
    SEPARATE, unverified instance of the same root cause as the iframe
    finding ("parser vocabulary is the ceiling on what the safety net can
    ever see"). No parser call ever turns this into a field entry at all —
    not top-document convergence, not frame convergence, since it is never
    required by ANY parser's own rules (it cannot be, because it is never a
    field to that parser). Only the backstop's raw structural census can
    ever see it — and it must refuse on the mere unclassifiable presence:
    unknown ⇒ manual refusal, never unknown ⇒ submit."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r5-unclassifiable-control",
            channel="ashby",
            page_html="",
            apply_url=_data_url(_UNCLASSIFIABLE_CONTROL_FORM),
            plan=_name_only_plan(),
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},
            answer_bank=None,
        )
    err = exc_info.value
    assert err.reason == "unverifiable_form_surface"
    assert err.question is not None and "combobox" in err.question.lower()


# ---------------------------------------------------------------------------
# 11. CLI-SUB-005-R6 (ROOT-CAUSE fix, RUN-20260818T0223Z/SUB-005-R5/08-
#     adversarial-final.md, attacks #6 and #7 — both closed the R2->R5 series
#     was ultimately FAILed on, per 05-decision-memos/SUB-005-and-COV-3-
#     rulings.md "SUB-005 R6 ruling"):
#
#     Attack #6 — a required control living entirely inside an OPEN shadow
#     root, on a bare custom-element host with no `role`/`contenteditable` of
#     its own. `page.content()` (and therefore BeautifulSoup/
#     `parse_form_schema`) serializes ONLY the light DOM — an open shadow
#     root's content is structurally ABSENT from that string, not merely
#     unparsed, so R5's entire census (both the total-re-derivation loop and
#     its own conservative backstop) was blind to it no matter how many times
#     it re-ran. Ported here exactly like the reviewer's own
#     adversarial/attack6_shadow_dom_custom_element.py construction.
#
#     Attack #7 — a required control appended to the live DOM inside a
#     `mousedown` listener on the SUBMIT control itself: strictly after
#     `_verify_no_unverifiable_form_surface` returns clean, strictly before
#     the click's default action (the actual form submission) fires — a
#     deterministic DOM-event-ordering gap (mousedown always precedes click
#     for the same physical click), not a race the page has to win by luck.
#     Ported here exactly like adversarial/attack7_reveal_on_submit_click.py.
#
#     R6 closes BOTH at the root: a LIVE, shadow-DOM-piercing composed-tree
#     census (`_composed_live_census`, evaluated via Playwright's own
#     `evaluate()` inside the page's live JS context, never a serialized
#     string) replaces the string-based census as the required-and-
#     uncommitted source of truth, AND a capture-phase submission guard
#     (`_install_submission_guard`) re-runs that SAME census at the literal
#     instant a submit/click event fires and cancels the submission outright
#     if anything required is still uncommitted THEN — closing the check-
#     then-act window by construction rather than by adding another check.
# ---------------------------------------------------------------------------

_SHADOW_DOM_CUSTOM_ELEMENT_FORM = """
<title>shadow-dom-widget</title>
<form onsubmit="event.preventDefault();
    var xc = document.querySelector('x-legal-consent');
    var shadowInput = xc && xc.shadowRoot ? xc.shadowRoot.querySelector('input') : null;
    var consentValue = shadowInput ? shadowInput.value : '';
    if (document.getElementById('name').value === 'Jordan Blake' &&
        consentValue === 'I agree') {
      document.body.innerHTML = '<h1>Thank you for applying</h1>';
    } else {
      document.body.innerHTML = '<p>Missing entry for required field: consent</p>';
    }">
  <div data-field-path="name">
    <label class="_required_abc123">Full name</label>
    <input id="name" name="name" type="text">
  </div>
  <x-legal-consent></x-legal-consent>
  <button type="submit">Submit Application</button>
</form>
<script>
  class LegalConsent extends HTMLElement {
    connectedCallback() {
      const shadow = this.attachShadow({mode: 'open'});
      // Not a native HTML5 `required` attribute on purpose: this codebase's
      // own ATS-shaped forms (Ashby/Greenhouse) signal requiredness via
      // aria-required/CSS-class convention, never native browser constraint
      // validation, which would intercept the submit event before either
      // R5's or R6's own JS-level checks ever ran and mask the actual
      // finding under test.
      shadow.innerHTML =
        '<label>I agree to the background-check policy (required)</label>' +
        '<input type="text" aria-required="true">';
    }
  }
  customElements.define('x-legal-consent', LegalConsent);
</script>
"""


def test_live_submitter_never_submits_over_an_unanswerable_shadow_dom_required_field(
    tmp_path,
) -> None:
    """THE R5->R6 ADVERSARIAL-REVIEW BREAK, ported exactly from
    adversarial/attack6_shadow_dom_custom_element.py: on the unfixed R5
    branch this returned submitted:true, confirmation:"Thank you for
    applying", filled:["name"], unfilled:[] — the shadow-DOM field was never
    seen by ANY census (page.content() cannot serialize an open shadow
    root's content at all), never attempted, never verified, never raised as
    a manual step. With no profile/answer-bank able to answer "I agree to
    the background-check policy", the R6 live composed census must resolve
    or refuse it — never guess, never submit silently over it."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r6-shadow-unanswerable",
            channel="ashby",
            page_html="",
            apply_url=_data_url(_SHADOW_DOM_CUSTOM_ELEMENT_FORM),
            plan=_name_only_plan(),
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},
            answer_bank=None,
        )
    err = exc_info.value
    assert err.reason == "unplanned_required_field"
    assert err.question is not None and "background-check" in err.question.lower()


def test_live_submitter_resolves_and_submits_an_answerable_shadow_dom_required_field(
    tmp_path,
) -> None:
    """Guard against over-refusal: the SAME shadow-DOM-hosted required
    control, when it CAN genuinely be answered (here: the answer bank,
    matched by the label the live composed census read straight out of the
    shadow root), is discovered by the R6 live census, filled and verified
    via a shadow-DOM-piercing Playwright locator (never assembled from an
    id/name this anonymous control never had), and the submission proceeds —
    proving the fix RESOLVES a legitimately answerable shadow control exactly
    like any other newly discovered field, instead of either submitting
    blind or refusing a form that could genuinely be completed."""
    from app.services.answer_bank import (
        PROVENANCE_USER_ANSWERED,
        SENSITIVITY_FACTUAL,
        AnswerBankMatch,
    )
    from app.services.apply_executor import playwright_form_submitter

    match = AnswerBankMatch(
        item_id="bank-item-shadow-1",
        answer="I agree",
        confidence=0.97,
        method="test",
        question_as_seen="I agree to the background-check policy (required)",
        banked_question="background check consent",
        sensitivity=SENSITIVITY_FACTUAL,
        provenance=PROVENANCE_USER_ANSWERED,
        per_application=False,
    )

    def answer_bank(field: dict[str, Any]) -> Any:
        if "background-check" in str(field.get("label") or "").lower():
            return match
        return None

    outcome = playwright_form_submitter(
        application_id="sub005r6-shadow-answered",
        channel="ashby",
        page_html="",
        apply_url=_data_url(_SHADOW_DOM_CUSTOM_ELEMENT_FORM),
        plan=_name_only_plan(),
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
        profile={},
        answer_bank=answer_bank,
    )
    assert outcome["submitted"] is True
    assert outcome["confirmation"] and "thank you" in str(outcome["confirmation"]).lower()
    assert any(name.startswith("__aether_live_census_") for name in outcome["filled"])
    assert any(
        name.startswith("__aether_live_census_") for name in outcome["unplannedFilled"]
    )


_MOUSEDOWN_REVEAL_FORM = """
<title>mousedown-reveal</title>
<form onsubmit="event.preventDefault();
    document.body.innerHTML = '<h1>Thank you for applying</h1>';">
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
    // aria-required, not the native HTML5 `required` attribute: a native
    // `required` empty field is blocked by the BROWSER'S OWN constraint
    // validation before the 'submit' event ever fires at all, which would
    // mask the actual finding under test (this codebase's own ATS-shaped
    // forms signal requiredness via aria-required/CSS-class convention,
    // never native browser validation, exactly like the real Ashby/
    // Greenhouse pages this mirrors).
    input.setAttribute('aria-required', 'true');
    var label = document.createElement('label');
    label.setAttribute('for', 'late_reveal');
    label.textContent = 'Late reveal question';
    // Appended AFTER the button — never before it — so Playwright's own
    // click actionability/stability check has no visible layout shift under
    // the pointer to react to (an earlier construction using insertBefore
    // produced a different, uninteresting no_confirmation failure purely
    // from the click missing the button, per the reviewer's own note).
    document.querySelector('form').appendChild(label);
    document.querySelector('form').appendChild(input);
  });
</script>
"""


def test_live_submitter_never_submits_over_a_field_revealed_at_mousedown_on_submit(
    tmp_path,
) -> None:
    """THE R5->R6 ADVERSARIAL-REVIEW BREAK, ported exactly from
    adversarial/attack7_reveal_on_submit_click.py: a required field appended
    to the DOM inside a `mousedown` handler on the submit button itself —
    strictly AFTER _verify_no_unverifiable_form_surface returns clean,
    strictly BEFORE the click's default action (the actual submission)
    fires — must never let that submission complete. On the unfixed R5
    branch this returned submitted:true, confirmation:"Thank you for
    applying" over the empty, unattempted, unverified late_reveal field. The
    R6 capture-phase submission guard must cancel the submission itself, in
    the browser, at the instant it would fire — never a Python-side re-check
    with its own gap for the SAME race to reopen in."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r6-mousedown-reveal",
            channel="ashby",
            page_html="",
            apply_url=_data_url(_MOUSEDOWN_REVEAL_FORM),
            plan=_name_only_plan(),
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},
            answer_bank=None,
        )
    err = exc_info.value
    assert err.reason == "unplanned_required_field"
    assert err.question is not None and "late reveal" in err.question.lower()


def test_live_submitter_still_submits_a_well_behaved_form_with_the_guard_installed(
    tmp_path,
) -> None:
    """Guard against over-refusal at the architecture level: installing the
    R6 capture-phase submission guard on every application (not merely the
    exotic ones under test) must never block an ordinary, fully-answered
    submission — the SAME assertion as
    test_live_submitter_submits_a_wellbehaved_form_with_confirmation, now
    with the guard active, proving it is a silent no-op for a clean form."""
    from app.services.apply_executor import playwright_form_submitter

    outcome = playwright_form_submitter(
        application_id="sub005r6-guard-no-overrefusal",
        channel="generic",
        page_html="",
        apply_url=_data_url(_HONEST_FORM),
        plan={"fields": [_name_plan_field()]},
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
    )
    assert outcome["submitted"] is True
    assert outcome["confirmation"] and "thank you" in str(outcome["confirmation"]).lower()


# ---------------------------------------------------------------------------
# 12. CLI-SUB-005-R7 (FAIL CLOSED + bubble-phase, RUN-20260818T0223Z/SUB-005-
#     R6/08-adversarial-final.md attacks A/B/C2/F, per 05-decision-memos/
#     SUB-005-and-COV-3-rulings.md "SUB-005 R6 outcome + R7 ruling"):
#
#     Attacks B and F are REAL correctness defects (fail-open): R6's
#     _install_submission_guard/_composed_live_census each swallowed ANY
#     exception from their evaluate() call and proceeded as if nothing were
#     wrong. R7 fails closed at both boundaries — an exception now raises
#     ManualStepRequired rather than being treated as "zero findings"/"guard
#     not needed". This also converts attack C2 (a closed shadow root with
#     ZERO external light-DOM signal — a genuine browser-platform read
#     limit) into a safe refusal, via an attachShadow-interception marker
#     that gives the host's own EXISTENCE (never its content) an honest
#     signal the pre-existing _unclassifiable_controls backstop can flag.
#
#     Attack A is a structural ceiling, not a correctness defect: a required
#     control created strictly INSIDE the form's own TARGET-phase 'onsubmit'
#     handler is invisible to a CAPTURE-phase-only guard by DOM spec. A new
#     BUBBLE-phase 'submit' listener (fires AFTER the target's own handler)
#     narrows this — a field the handler reveals and LEAVES IN THE DOM is
#     now caught (test 12e). What it cannot close, and does not claim to: a
#     handler that reveals the field and, in that SAME synchronous
#     execution, fires an outbound request and/or removes the field again
#     before returning (test 12f, the honestly-recorded residual).
# ---------------------------------------------------------------------------

_GUARD_INSTALL_EXCEPTION_FORM = """
<title>mousedown-reveal-plus-addeventlistener-poison</title>
<script>
  // Poison ONLY document.addEventListener (an own-property override shadows
  // the inherited EventTarget.prototype method for calls made specifically
  // as `document.addEventListener(...)` -- exactly the calls R6/R7's own
  // guard-install JS makes). Element-level addEventListener (used below for
  // the submit button's own mousedown listener) is untouched.
  document.addEventListener = function () {
    throw new Error('hostile page: document.addEventListener is unavailable');
  };
</script>
<form onsubmit="event.preventDefault();
    document.body.innerHTML = '<h1>Thank you for applying</h1>';">
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
    input.setAttribute('aria-required', 'true');
    var label = document.createElement('label');
    label.setAttribute('for', 'late_reveal');
    label.textContent = 'Late reveal question';
    document.querySelector('form').appendChild(label);
    document.querySelector('form').appendChild(input);
  });
</script>
"""


def test_live_submitter_refuses_when_the_guards_own_installation_throws(
    tmp_path,
) -> None:
    """THE R6->R7 ADVERSARIAL-REVIEW BREAK (attack B), ported exactly from
    adversarial/attackB_guard_install_exception.py: document.
    addEventListener poisoned as an OWN property (an unaffected Element-
    level addEventListener still lets the page's own mousedown listener
    register normally) makes _install_submission_guard's own
    document.addEventListener(...) calls throw, uncaught inside the page's
    JS. On the unfixed R6 branch the bare `except Exception: pass` swallowed
    this and the mousedown-revealed required field (attack #7's exact
    construction) was submitted over, empty, unverified. R7 fails closed: an
    exception during the guard's own installation must now refuse rather
    than proceed with an unguarded click."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r7-guard-install-exception",
            channel="ashby",
            page_html="",
            apply_url=_data_url(_GUARD_INSTALL_EXCEPTION_FORM),
            plan=_name_only_plan(),
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},
            answer_bank=None,
        )
    err = exc_info.value
    assert err.reason == "guard_install_failed"


_CENSUS_THROWS_FORM = """
<title>shadow-dom-census-throws</title>
<script>
  // Poison Element.prototype.getAttribute to throw the FIRST time it is
  // asked for the census's own marker attribute -- reached only after the
  // required-and-uncommitted classification logic has already run for that
  // node, so this targets the census's own bookkeeping write, not merely a
  // required-check read.
  const _origGetAttribute = Element.prototype.getAttribute;
  Element.prototype.getAttribute = function (name) {
    if (name === 'data-aether-live-field') {
      throw new Error('hostile page: getAttribute is unavailable for this name');
    }
    return _origGetAttribute.call(this, name);
  };
</script>
<form onsubmit="event.preventDefault();
    document.body.innerHTML = '<h1>Thank you for applying</h1>';">
  <div data-field-path="name">
    <label class="_required_abc123">Full name</label>
    <input id="name" name="name" type="text">
  </div>
  <x-legal-consent></x-legal-consent>
  <button type="submit">Submit Application</button>
</form>
<script>
  class LegalConsent extends HTMLElement {
    connectedCallback() {
      const shadow = this.attachShadow({mode: 'open'});
      shadow.innerHTML =
        '<label>I agree to the background-check policy (required)</label>' +
        '<input type="text" aria-required="true">';
    }
  }
  customElements.define('x-legal-consent', LegalConsent);
</script>
"""


def test_live_submitter_refuses_when_the_composed_census_itself_throws(
    tmp_path,
) -> None:
    """THE R6->R7 ADVERSARIAL-REVIEW BREAK (attack F), ported exactly from
    adversarial/attackF_composed_census_throws.py: Element.prototype.
    getAttribute poisoned to throw specifically for the census's own marker
    attribute name against attack #6's exact open-shadow-DOM construction.
    window.__aetherComposedCensus() itself throws (not merely the per-node
    walk() helper, which already guards its own querySelectorAll call). On
    the unfixed R6 branch the bare `except Exception: return []` swallowed
    this and silently reported zero results, reverting the shadow-DOM field
    to fully invisible again at both the convergence AND click-time census
    calls. R7 fails closed: an exception from the census must now refuse
    rather than be treated as 'nothing found'."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r7-census-throws",
            channel="ashby",
            page_html="",
            apply_url=_data_url(_CENSUS_THROWS_FORM),
            plan=_name_only_plan(),
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},
            answer_bank=None,
        )
    err = exc_info.value
    assert err.reason == "census_unavailable"


_CLOSED_SHADOW_NO_SIGNAL_FORM = """
<title>closed-shadow-unconditional-success</title>
<form onsubmit="event.preventDefault();
    document.body.innerHTML = '<h1>Thank you for applying</h1>';">
  <div data-field-path="name">
    <label class="_required_abc123">Full name</label>
    <input id="name" name="name" type="text">
  </div>
  <x-closed-consent></x-closed-consent>
  <button type="submit">Submit Application</button>
</form>
<script>
  class ClosedConsent extends HTMLElement {
    connectedCallback() {
      const shadow = this.attachShadow({mode: 'closed'});
      shadow.innerHTML =
        '<label>I agree to the background-check policy (required)</label>' +
        '<input type="text" aria-required="true">';
    }
  }
  customElements.define('x-closed-consent', ClosedConsent);
</script>
"""


def test_live_submitter_refuses_a_closed_shadow_root_with_zero_external_signal(
    tmp_path,
) -> None:
    """THE R6->R7 ADVERSARIAL-REVIEW BREAK (attack C2), ported exactly from
    adversarial/attackC2_closed_shadow_unconditional_success.py: a required
    control living entirely inside a CLOSED shadow root, on a host with no
    role/aria-required/contenteditable of its own, is genuinely unreadable
    by ANY web API — element.shadowRoot returns null for every external
    accessor, including this codebase's own composed census. On the unfixed
    R6 branch this returned submitted:true, confirmation:"Thank you for
    applying", filled:["name"] — the closed-shadow field was never seen,
    never attempted, never verified. R7's attachShadow-interception marker
    (installed via page.add_init_script, armed before ANY page script runs)
    gives the host's own EXISTENCE — never its content, which stays
    genuinely unreadable, a real browser-platform limit — an honest, page-
    JS-independent signal for the pre-existing _unclassifiable_controls
    backstop to flag, so the submission refuses rather than guesses."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r7-closed-shadow-no-signal",
            channel="ashby",
            page_html="",
            apply_url=_data_url(_CLOSED_SHADOW_NO_SIGNAL_FORM),
            plan=_name_only_plan(),
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},
            answer_bank=None,
        )
    err = exc_info.value
    assert err.reason == "unverifiable_form_surface"
    assert err.question is not None and "closed shadow" in err.question.lower()


_SUBMIT_HANDLER_REVEAL_NATIVE_FORM = """
<title>submit-handler-reveal-native</title>
<form onsubmit="
    if (!document.getElementById('late_in_submit')) {
      var label = document.createElement('label');
      label.setAttribute('for', 'late_in_submit');
      label.textContent = 'Consent (revealed inside the submit handler)';
      var input = document.createElement('input');
      input.type = 'text';
      input.id = 'late_in_submit';
      input.setAttribute('aria-required', 'true');
      document.querySelector('form').appendChild(label);
      document.querySelector('form').appendChild(input);
    }">
  <div data-field-path="name">
    <label class="_required_abc123">Full name</label>
    <input id="name" name="name" type="text">
  </div>
  <button id="submit-btn" type="submit">Submit Application</button>
</form>
"""


def test_live_submitter_never_submits_over_a_field_revealed_inside_the_forms_own_submit_handler(
    tmp_path,
) -> None:
    """CLI-SUB-005-R7 bubble-phase closure of attack A for a genuinely
    NATIVE submit: the form's own 'onsubmit' handler reveals a brand-new
    required field and does NOT call preventDefault() itself, relying on the
    browser's own native default action (or, here, on Aether's own guard) to
    decide whether the submission proceeds — deliberately distinct from
    _SUBMIT_HANDLER_REVEAL_SYNC_FETCH_FORM below, which fakes success and
    destroys the field within the SAME synchronous handler. R6's capture-
    phase-only guard runs BEFORE the event ever reaches the target (DOM
    spec), so it cannot see this field; R7's new BUBBLE-phase 'submit'
    listener runs AFTER the target's own handler completes, sees the field
    still present in the DOM, and cancels the submission itself — the exact
    case 05-decision-memos/SUB-005-and-COV-3-rulings.md's R7 ruling names as
    the one attack-A construction the bubble-phase check DOES close."""
    from app.services.apply_executor import playwright_form_submitter

    with pytest.raises(ManualStepRequired) as exc_info:
        playwright_form_submitter(
            application_id="sub005r7-submit-handler-reveal-native",
            channel="ashby",
            page_html="",
            apply_url=_data_url(_SUBMIT_HANDLER_REVEAL_NATIVE_FORM),
            plan=_name_only_plan(),
            resume_pdf_bytes=b"%PDF-1.4 fake",
            cover_letter_text="Dear Hiring Manager,",
            evidence_dir=str(tmp_path),
            profile={},
            answer_bank=None,
        )
    err = exc_info.value
    assert err.reason == "unplanned_required_field"
    assert err.question is not None and "consent" in err.question.lower()


_SUBMIT_HANDLER_REVEAL_SYNC_FETCH_FORM = """
<title>submit-handler-reveal-synchronous-fetch</title>
<form onsubmit="event.preventDefault();
    if (!document.getElementById('late_in_submit')) {
      var label = document.createElement('label');
      label.setAttribute('for', 'late_in_submit');
      label.textContent = 'Consent (revealed inside the submit handler)';
      var input = document.createElement('input');
      input.type = 'text';
      input.id = 'late_in_submit';
      input.setAttribute('aria-required', 'true');
      document.querySelector('form').appendChild(label);
      document.querySelector('form').appendChild(input);
    }
    // A synchronous-style outbound submission fired INSIDE the same target-
    // phase handler that revealed the field (a self-contained data: URL
    // target -- zero real network egress -- purely to prove the ORDERING
    // property deterministically in a sandboxed test) followed by an
    // OPTIMISTIC success DOM replacement, both synchronous, both complete
    // (destroying the just-created field along with the rest of the form)
    // before ANY subsequent listener -- capture OR bubble -- gets a chance
    // to run.
    fetch('data:text/plain,submitted');
    document.body.innerHTML = '<h1>Thank you for applying</h1>';">
  <div data-field-path="name">
    <label class="_required_abc123">Full name</label>
    <input id="name" name="name" type="text">
  </div>
  <button id="submit-btn" type="submit">Submit Application</button>
</form>
"""


def test_live_submitter_records_the_honest_synchronous_submission_ceiling_for_attack_a(
    tmp_path,
) -> None:
    """CLI-SUB-005-R7 — the irreducible residual, recorded HONESTLY rather
    than claimed closed: a required field revealed inside the form's own
    'onsubmit' handler, where that SAME synchronous handler also fires an
    outbound request and replaces the DOM (destroying the field) before
    returning, is invisible to R7's new bubble-phase check too — bubble
    phase runs AFTER the target handler has ALREADY completed, by which
    point the field no longer exists to be seen, and the "success" DOM state
    is already showing. This is the ABSOLUTE stop
    05-decision-memos/SUB-005-and-COV-3-rulings.md's R7 ruling names: "if it
    still finds a silent submit, it can only be the pure attack-A ceiling
    (field created at the submit instant), which is irreducible for any
    pre-submit guard" — no client-side event-listener ordering can guarantee
    seeing, or undoing, a same-handler side effect that completes before
    control ever returns to the browser's own event-dispatch machinery. This
    test asserts the HONEST limit — the field is genuinely unfilled and the
    outcome genuinely reports submitted — never a false green pretending
    this is closed. PH0-PAUSE-1 (auto-apply OFF) is the production guarantee
    against this residual, not this code path."""
    from app.services.apply_executor import playwright_form_submitter

    outcome = playwright_form_submitter(
        application_id="sub005r7-submit-handler-reveal-sync-fetch",
        channel="ashby",
        page_html="",
        apply_url=_data_url(_SUBMIT_HANDLER_REVEAL_SYNC_FETCH_FORM),
        plan=_name_only_plan(),
        resume_pdf_bytes=b"%PDF-1.4 fake",
        cover_letter_text="Dear Hiring Manager,",
        evidence_dir=str(tmp_path),
        profile={},
        answer_bank=None,
    )
    assert outcome["submitted"] is True
    assert outcome["confirmation"] and "thank you" in str(outcome["confirmation"]).lower()
    assert "late_in_submit" not in outcome["filled"]
