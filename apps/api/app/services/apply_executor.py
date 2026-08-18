"""U5b — the apply-executor: applying on the employer's own site, honestly.

U-PLAN "U5 MANDATE SHARPENED" (user, 2026-08-13): *"if there is no email
address on the JD then the submission agent must apply on the company website
using the tailored resume, the cover letter and google forms etc... exactly
like a human user would. No application must remain in 'prepared only'
status."*

What "exactly like a human user would" means here, and what it deliberately
does NOT mean:

* A REAL browser (headless Chromium via Playwright) loads the employer's real
  application form, fills it with the user's OWN stored profile data and
  attaches the tailored résumé PDF + cover letter generated for THAT job, then
  activates the form's own submit control and screenshots the result. There is
  no HTTP-level forgery of a form post and no synthetic "confirmation".
* It NEVER invents an answer. The field schema is parsed out of the real page;
  every REQUIRED field is answered from stored data or not at all. A required
  question with no stored answer — "Flexible Working", "Are you legally
  authorized to work in the country in which you are applying?" — raises
  :class:`ManualStepRequired` carrying the employer's VERBATIM question text,
  which is persisted on the ``Application`` row so the user sees the actual
  words they must answer. That is the honest terminal state the NO-PREPARED-ONLY
  invariant accepts in place of a transmission.
* It NEVER defeats a challenge. A triggered CAPTCHA or a login wall is
  detected BEFORE any plan is built and becomes the same kind of honest manual
  step. Nothing here solves, bypasses or proxies around a human check.
* It NEVER sends without an approved gate. Execution is refused unless the
  caller's own ``ApprovalRequest(type='application_submit')`` is ``approved``,
  and the single-shot ``executedAt`` claim is taken through the EXISTING
  :meth:`ApprovalRepository.claim_execution` (the CRITICAL-4 machinery the
  W-SUB email path already uses) so one approval can never produce two real
  submissions.

Seek is out of scope by ruling, not by omission: ``docs/delivery/ADR-SEEK-V3.md``
(REFUSED, un-superseded) means a ``seek-manual`` application never reaches this
module — see :data:`app.services.apply_channel_resolver.AUTOMATABLE_CHANNELS`.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from app.db import (
    ensure_application_manual_step_columns,
    ensure_application_transmission_columns,
    get_connection,
)

logger = logging.getLogger(__name__)

#: Sentinel values a plan carries instead of real bytes: the submitter turns
#: them into the actual uploads at fill time.
RESUME_DOCUMENT = "__aether_resume_pdf__"
COVER_LETTER_DOCUMENT = "__aether_cover_letter__"

#: Field names (lower-cased) that map to a standard piece of profile data.
#: Anything NOT in here and not answered by ``profile["customAnswers"]`` is an
#: employer-specific question, and an unanswered REQUIRED one is a manual step.
_STANDARD_FIELDS: dict[str, str] = {
    "_systemfield_name": "name",
    "name": "name",
    "full_name": "name",
    "fullname": "name",
    "first_name": "first_name",
    "firstname": "first_name",
    "given_name": "first_name",
    "last_name": "last_name",
    "lastname": "last_name",
    "family_name": "last_name",
    "preferred_name": "preferred_name",
    "preferred_first_name": "preferred_name",
    "_systemfield_email": "email",
    "email": "email",
    "email_address": "email",
    "_systemfield_phone": "phone",
    "phone": "phone",
    "phone_number": "phone",
    "mobile": "phone",
    "_systemfield_location": "location",
    "location": "location",
    "city": "location",
    "country": "country",
    "_systemfield_resume": "resume",
    "resume": "resume",
    "cv": "resume",
    "_systemfield_coverletter": "cover_letter",
    "cover_letter": "cover_letter",
    "coverletter": "cover_letter",
    "_systemfield_linkedin": "linkedin",
    "linkedin": "linkedin",
    "linkedin_url": "linkedin",
    "website": "website",
}

#: Label-normalised fallback for the SAME standard identity fields, used when a
#: form keys its inputs by an opaque machine name (Ashby uses a UUID like
#: ``39ebb162-1514-…`` whose ``name`` matches nothing in ``_STANDARD_FIELDS``)
#: but shows a human LABEL ("LinkedIn", "Preferred First Name"). Strictly a
#: whitelist of UNAMBIGUOUS standard identity labels — never an employer's
#: free-text question — so the guarantee in :func:`_answer_for` (never guess an
#: answer from words that merely look similar) is preserved. Verified gap: the
#: profile HELD a LinkedIn URL and preferred name, but the plan raised
#: ``unknown_required_question`` because only the UUID name was consulted.
_LABEL_STANDARD_FIELDS: dict[str, str] = {
    "name": "name",
    "full name": "name",
    "legal name": "name",
    "full legal name": "name",
    "first name": "first_name",
    "given name": "first_name",
    "given names": "first_name",
    "preferred first name": "preferred_name",
    "preferred name": "preferred_name",
    "last name": "last_name",
    "surname": "last_name",
    "family name": "last_name",
    "preferred last name": "last_name",
    "email": "email",
    "email address": "email",
    "e mail": "email",
    "phone": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "mobile number": "phone",
    "mobile phone": "phone",
    "contact number": "phone",
    "telephone": "phone",
    "location": "location",
    "city": "location",
    "current location": "location",
    "current city": "location",
    "country": "country",
    "linkedin": "linkedin",
    "linkedin profile": "linkedin",
    "linkedin url": "linkedin",
    "linkedin profile url": "linkedin",
    "website": "website",
    "personal website": "website",
    "portfolio": "website",
    "portfolio url": "website",
    "resume": "resume",
    "cv": "resume",
    "resume/cv": "resume",
    "resume / cv": "resume",
    "cover letter": "cover_letter",
}


def _normalize_field_label(raw: Any) -> str:
    """Lower, drop parentheticals/required markers/punctuation, collapse spaces.

    ``"LinkedIn Profile URL *"`` → ``"linkedin profile url"``; ``"Resume/CV"`` →
    ``"resume/cv"`` (the slash is kept because it is meaningful in that label)."""
    text = str(raw or "").lower()
    text = re.sub(r"\(.*?\)", " ", text)  # "(optional)", "(if applicable)"
    text = text.replace("*", " ")
    text = re.sub(r"[^a-z0-9/ ]+", " ", text)  # keep the resume/cv slash
    return re.sub(r"\s+", " ", text).strip()


class ManualStepRequired(Exception):
    """A human has to finish this one — and here is exactly why.

    ``reason`` is a machine code (``unknown_required_question``, ``captcha``,
    ``captcha_challenge`` — a MOUNTED hCaptcha widget the submitter refuses
    to click past, distinct from ``captcha``'s TRIGGERED-challenge detection
    in :func:`detect_blocking_state` — ``login_wall``,
    ``no_automatable_channel``, …). ``question`` carries the
    employer's VERBATIM question text when the obstacle is an unanswerable
    required field, so the UI shows the user the real words rather than a
    paraphrase. This is an honest ACTIONABLE outcome, not a failure: it
    satisfies the NO-PREPARED-ONLY invariant precisely because it leaves the
    row in a state the user can act on.
    """

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        question: str | None = None,
        fields: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.question = question
        self.fields = fields or []


class ApplyExecutorGuardError(Exception):
    """The approval gate (or the single-shot claim) refused this execution.

    ``http_status`` is what a router answers with: 404 for an approval that
    does not exist, 409 for one that is not approved or was already executed.
    Raised BEFORE any browser work, so a refusal has zero side effects.
    """

    def __init__(self, reason: str, message: str, *, http_status: int = 409) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.http_status = http_status


class ApplyExecutorTransportError(Exception):
    """The browser could not complete the attempt. NOTHING was submitted.

    Distinct from :class:`ManualStepRequired` (a real obstacle on the page) —
    this is our side failing, so the execution claim is released and the sweep
    can retry the application on its next pass.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


# ---------------------------------------------------------------------------
# Blocking-state detection (CAPTCHA / login wall).
# ---------------------------------------------------------------------------

#: A MOUNTED reCAPTCHA widget is not a challenge — nearly every modern form
#: mounts one invisibly (the real Ashby and Greenhouse captures both do). Only
#: a TRIGGERED challenge blocks, and it is recognisable by the challenge frame
#: or the image-select panel Google renders for it.
_CAPTCHA_CHALLENGE_MARKERS = (
    "rc-imageselect",
    "rc-audiochallenge",
    "h-captcha-challenge",
)
_CAPTCHA_FRAME_TITLE = re.compile(r"(recaptcha|hcaptcha)\s+challenge", re.I)


def _soup(html: str) -> Any:
    from bs4 import BeautifulSoup

    return BeautifulSoup(html or "", "html.parser")


def detect_blocking_state(html: str) -> str | None:
    """``"captcha"``, ``"login_wall"`` or ``None`` — what stops a human bot.

    Deliberately conservative in BOTH directions: it must not cry CAPTCHA at
    every page that merely mounts reCAPTCHA (that would make the executor
    useless), and it must not walk past a real gate (that would make it
    dishonest about what it did).
    """
    soup = _soup(html)
    for marker in _CAPTCHA_CHALLENGE_MARKERS:
        if soup.find(id=marker) is not None or soup.find(class_=marker) is not None:
            return "captcha"
    for frame in soup.find_all("iframe"):
        title = str(frame.get("title") or "")
        if _CAPTCHA_FRAME_TITLE.search(title):
            return "captcha"
    # A password field has no business on a job-application form: its presence
    # means the page is asking for an ACCOUNT before it will take the
    # application. We do not create accounts on the user's behalf.
    if soup.find("input", attrs={"type": "password"}) is not None:
        return "login_wall"
    return None


# ---------------------------------------------------------------------------
# Field-schema parsing — the REAL schema, off the REAL page.
# ---------------------------------------------------------------------------


def _text(node: Any) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _label_text(raw: str) -> str:
    """A label without its required-marker asterisk.

    Strips the ASCII ``*`` every other dialect here uses AND Lever's own
    U+2731 HEAVY ASTERISK ``✱`` (confirmed on real captured Lever pages,
    SUB-011 scout evidence) -- a plain ``\\s*\\*\\s*$`` regex leaves that
    character on every required label a Lever manual step shows the user.
    """
    return re.sub(r"\s*[*✱]\s*$", "", (raw or "").strip()).strip()


def _classes(node: Any) -> list[str]:
    value = node.get("class") if node is not None else None
    if isinstance(value, str):
        return value.split()
    return list(value or [])


def _kind_for(control: Any) -> str:
    tag = control.name.lower()
    if tag == "textarea":
        return "textarea"
    if tag == "select":
        return "select"
    control_type = str(control.get("type") or "text").lower()
    if control_type in {"radio", "checkbox", "file", "email", "tel", "number", "url", "date"}:
        return control_type
    if "select__input" in _classes(control) or str(control.get("role") or "") == "combobox":
        return "combobox"
    return "text"


def _ashby_options(node: Any) -> list[str]:
    """Option labels of an Ashby choice question (radio/checkbox/yes-no)."""
    options: list[str] = []
    for label in node.find_all("label"):
        target = str(label.get("for") or "")
        if "labeled-radio" in target or "labeled-checkbox" in target:
            options.append(_text(label))
    for button in node.find_all("button"):
        if any(cls.startswith("_option") for cls in _classes(button)):
            options.append(_text(button))
    return [option for option in options if option]


def _parse_ashby(soup: Any) -> list[dict[str, Any]]:
    """Ashby renders one ``[data-field-path]`` block per question.

    The block's ``data-field-path`` IS the field id the customAnswers map is
    keyed by (``_systemfield_name`` for system fields, a UUID for employer
    questions), and requiredness is carried by the ``_required_*`` CSS class
    on the question's own label — the same marker that renders the asterisk a
    human applicant sees.
    """
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in soup.select("[data-field-path]"):
        name = str(node.get("data-field-path") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        label_el = node.find("label")
        controls = [
            control
            for control in node.find_all(["input", "select", "textarea"])
            if str(control.get("name") or "") != "g-recaptcha-response"
        ]
        required = bool(
            label_el is not None
            and any(cls.startswith("_required") for cls in _classes(label_el))
        )
        required = required or any(control.has_attr("required") for control in controls)
        kinds = [_kind_for(control) for control in controls]
        kind = _dominant_kind(kinds)
        fields.append(
            {
                "name": name,
                "label": _label_text(_text(label_el)),
                "kind": kind,
                "required": required,
                "options": _ashby_options(node),
                "scope": f'[data-field-path="{name}"]',
            }
        )
    return fields


def _dominant_kind(kinds: Iterable[str]) -> str:
    ordered = list(kinds)
    for preferred in ("file", "radio", "checkbox", "select", "combobox", "textarea"):
        if preferred in ordered:
            return preferred
    for kind in ordered:
        if kind not in {"hidden", "search"}:
            return kind
    return "text"


def _ancestor_group(control: Any) -> Any:
    parent = control.parent
    while parent is not None and getattr(parent, "name", None):
        if str(parent.get("role") or "") == "group" and parent.get("aria-labelledby"):
            return parent
        parent = parent.parent
    return None


def _parse_greenhouse(soup: Any) -> list[dict[str, Any]]:
    """Greenhouse's embed exposes a machine-readable schema.

    ``aria-required`` on the control (or on the ``role="group"`` wrapper that
    owns a file upload), a ``required`` attribute on grouped checkboxes, and a
    trailing ``*`` on the visible label all mean the same thing to a human
    applicant, so all three are honoured. Voluntary self-ID fields
    (``gender``/``veteran_status``/``disability_status``) carry
    ``aria-required="false"`` and are therefore never blockers.
    """
    label_map: dict[str, str] = {}
    for label in soup.find_all("label"):
        target = str(label.get("for") or "")
        if target:
            label_map.setdefault(target, _text(label))
    fields: dict[str, dict[str, Any]] = {}
    for control in soup.find_all(["input", "select", "textarea"]):
        control_type = str(control.get("type") or "").lower()
        if control_type == "hidden" or str(control.get("aria-hidden") or "") == "true":
            continue
        if control_type == "search":
            continue
        raw_name = str(control.get("name") or "")
        control_id = str(control.get("id") or "")
        if raw_name == "g-recaptcha-response" or control_id.startswith("iti-"):
            continue
        group = _ancestor_group(control)
        group_label_el = (
            soup.find(id=str(group.get("aria-labelledby"))) if group is not None else None
        )
        # Grouped checkboxes (``question_123[]``) are ONE question with many
        # options — keyed by the shared name so an answer answers the group.
        if control_type == "checkbox" and raw_name.endswith("[]"):
            name = raw_name
        else:
            name = control_id or raw_name
        if not name:
            continue
        raw_label = label_map.get(control_id) or str(control.get("aria-label") or "")
        if control_type == "checkbox" and raw_name.endswith("[]"):
            raw_label = _text(group_label_el) or str(control.get("description") or "") or raw_label
        elif group_label_el is not None and not raw_label:
            raw_label = _text(group_label_el)
        elif group_label_el is not None and control_type == "file":
            raw_label = _text(group_label_el)
        required = (
            control.has_attr("required")
            or str(control.get("aria-required") or "").lower() == "true"
            or (group is not None and str(group.get("aria-required") or "").lower() == "true")
            or raw_label.strip().endswith("*")
        )
        entry = fields.get(name)
        option = (
            label_map.get(control_id)
            if control_type in {"radio", "checkbox"} and label_map.get(control_id)
            else None
        )
        if entry is None:
            entry = {
                "name": name,
                "label": _label_text(raw_label),
                "kind": _kind_for(control),
                "required": required,
                "options": [],
                "scope": None,
            }
            fields[name] = entry
        entry["required"] = entry["required"] or required
        if option:
            entry["options"].append(option)
    return list(fields.values())


def _lever_options(node: Any, primary: Any) -> list[str]:
    """Option labels of a Lever radio/checkbox question (survey or consent).

    Every option shares the question's control ``name`` (Lever's own DOM has
    no other grouping marker); the human-readable text is each option's own
    ``.application-answer-alternative`` span, falling back to the control's
    raw ``value`` for a shape that omits one."""
    control_type = str(primary.get("type") or "").lower()
    if control_type not in {"radio", "checkbox"}:
        return []
    name = str(primary.get("name") or "")
    if not name:
        return []
    options: list[str] = []
    for control in node.find_all("input", attrs={"name": name}):
        if str(control.get("type") or "").lower() not in {"radio", "checkbox"}:
            continue
        label_el = control.find_parent("label")
        alt = label_el.find(class_="application-answer-alternative") if label_el is not None else None
        text = _text(alt) if alt is not None else ""
        if not text:
            text = str(control.get("value") or "")
        if text and text not in options:
            options.append(text)
    return options


def _parse_lever(soup: Any) -> list[dict[str, Any]]:
    """Lever renders one ``li.application-question`` block per question
    (SUB-011 scout evidence, two real captured ``/apply`` pages).

    System fields (``name``/``email``/``phone``/``location``/…) wrap a
    single named control in a ``<label>``; radio/checkbox survey questions
    (``surveysResponses[<surveyId>][responses][field<N>]``) and employer
    custom "card" questions (``cards[<cardId>][field0]``) instead wrap a
    plain ``<div>`` -- Lever's own DOM, not something worth normalising
    away, so both shapes are read the same way: the block's own
    ``.application-label`` (its nested ``.text`` div where present, so a
    sibling ``.description`` paragraph — e.g. "Select all that apply" — is
    never folded into the question text) names the question, and its
    ``.application-field`` holds the control(s).

    A block can hold MORE than one control for one visible question: the
    structured-location autocomplete pairs a visible ``location`` text input
    with a hidden ``selectedLocation`` one, and the marketing-consent
    checkbox pairs a visible checkbox with an unchecked-by-default hidden
    decoy input of the SAME name (Lever's own "unchecked = 0" pattern) --
    the first VISIBLE control is always the one dedup keys on and answers
    are typed into, matching what a human applicant actually sees.

    Requiredness has NO single tell here: the ``name``/``email`` system
    fields and the employer's own card questions all carry a real
    ``required`` HTML attribute, but the résumé question -- confirmed
    required on the real capture -- carries NONE; only its label's
    ``<span class="required">✱</span>`` (see :func:`_label_text`) says so.
    Both signals are therefore trusted, exactly like the Greenhouse parser
    trusts ``aria-required`` alongside a trailing ``*``.
    """
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in soup.select("li.application-question"):
        controls = [
            control
            for control in node.find_all(["input", "select", "textarea"])
            if str(control.get("name") or "") != "g-recaptcha-response"
        ]
        if not controls:
            continue
        visible = [c for c in controls if str(c.get("type") or "").lower() != "hidden"]
        primary = visible[0] if visible else controls[0]
        name = str(primary.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        label_el = node.find(class_="application-label")
        text_el = label_el.find(class_="text") if label_el is not None else None
        raw_label = _text(text_el if text_el is not None else label_el)
        field_el = node.find(class_="application-field")
        required = (
            (label_el is not None and label_el.find("span", class_="required") is not None)
            or any(control.has_attr("required") for control in controls)
            or any(str(control.get("aria-required") or "").lower() == "true" for control in controls)
            or (field_el is not None and "required-field" in _classes(field_el))
        )
        fields.append(
            {
                "name": name,
                "label": _label_text(raw_label),
                "kind": _kind_for(primary),
                "required": required,
                "options": _lever_options(node, primary),
                "scope": None,
            }
        )
    return fields


def _parse_generic(soup: Any) -> list[dict[str, Any]]:
    """Best-effort schema for an employer's own form (incl. Google Forms).

    Only machine-readable requiredness is trusted here: with no known ATS
    convention to lean on, guessing which unmarked field is mandatory would be
    inventing facts about someone else's form.
    """
    label_map: dict[str, str] = {}
    for label in soup.find_all("label"):
        target = str(label.get("for") or "")
        if target:
            label_map.setdefault(target, _text(label))
    fields: dict[str, dict[str, Any]] = {}
    for control in soup.find_all(["input", "select", "textarea"]):
        control_type = str(control.get("type") or "").lower()
        if control_type in {"hidden", "submit", "button", "search"}:
            continue
        raw_name = str(control.get("name") or "")
        control_id = str(control.get("id") or "")
        if raw_name == "g-recaptcha-response":
            continue
        name = control_id or raw_name
        if not name:
            continue
        raw_label = (
            label_map.get(control_id)
            or str(control.get("aria-label") or "")
            or str(control.get("placeholder") or "")
        )
        required = (
            control.has_attr("required")
            or str(control.get("aria-required") or "").lower() == "true"
            or raw_label.strip().endswith("*")
        )
        entry = fields.setdefault(
            name,
            {
                "name": name,
                "label": _label_text(raw_label),
                "kind": _kind_for(control),
                "required": False,
                "options": [],
                "scope": None,
            },
        )
        entry["required"] = entry["required"] or required
    return list(fields.values())


def parse_form_schema(html: str, *, channel: str) -> list[dict[str, Any]]:
    """The real field schema of an application page, per ATS dialect.

    The ``_parse_generic`` fallback below is NOT a submission path any more:
    ORCHESTRATOR RULING U5-F3 (2026-08-14) removed every channel that lacked a
    dedicated parser from
    :data:`app.services.apply_channel_resolver.AUTOMATABLE_CHANNELS`. SUB-011
    (Track-2 U5c) built the dedicated Lever dialect parser and its own
    fixture-backed tests, so ``lever`` re-entered that set legitimately — the
    sweep now calls this with ``ashby``, ``greenhouse`` or ``lever``.
    ``smartrecruiters`` and ``generic`` still have none, so they still fall
    through here; the fallback stays because it is a legitimate schema READER
    (and the seam any future dedicated dialect is built against). It is
    ``AUTOMATABLE_CHANNELS`` — pinned by ``tests/test_u5_invariant_sweep.py`` —
    that decides what may be clicked, not this dispatch.
    """
    soup = _soup(html)
    if channel == "ashby":
        return _parse_ashby(soup)
    if channel == "greenhouse":
        return _parse_greenhouse(soup)
    if channel == "lever":
        return _parse_lever(soup)
    return _parse_generic(soup)


# ---------------------------------------------------------------------------
# Answering — stored facts only.
# ---------------------------------------------------------------------------


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in (full_name or "").split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _standard_answer(key: str, profile: dict[str, Any]) -> Any:
    full_name = str(profile.get("name") or "").strip()
    first, last = _split_name(full_name)
    values: dict[str, Any] = {
        "name": full_name,
        "first_name": str(profile.get("firstName") or first),
        "last_name": str(profile.get("lastName") or last),
        "preferred_name": str(profile.get("preferredName") or profile.get("firstName") or first),
        "email": str(profile.get("email") or ""),
        "phone": str(profile.get("phone") or ""),
        "location": str(profile.get("location") or ""),
        "country": str(profile.get("country") or ""),
        "linkedin": str(profile.get("linkedin") or ""),
        "website": str(profile.get("website") or ""),
        "resume": RESUME_DOCUMENT,
        "cover_letter": COVER_LETTER_DOCUMENT,
    }
    value = values.get(key)
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _custom_answer(field: dict[str, Any], profile: dict[str, Any]) -> Any:
    answers = profile.get("customAnswers")
    if not isinstance(answers, dict):
        return None
    name = str(field["name"])
    for key in (name, name.removesuffix("[]"), name.split("_")[-1]):
        if key and key in answers:
            value = answers[key]
            return value if str(value).strip() else None
    return None


def _answer_for(field: dict[str, Any], profile: dict[str, Any]) -> Any:
    """The stored answer for one field, or ``None`` — never a guess.

    Resolution order: an explicit per-question answer the user recorded, then
    the standard profile mapping by field name, then the two input TYPES whose
    meaning is unambiguous in HTML itself (``type="tel"`` is a phone number,
    ``type="email"`` is an email address). Nothing else is inferred: mapping an
    employer's free-text question onto a profile value because the words looked
    similar is how a bot ends up writing something the applicant never said.
    """
    explicit = _custom_answer(field, profile)
    if explicit is not None:
        return explicit
    key = _STANDARD_FIELDS.get(str(field["name"]).lower())
    if not key:
        # Fallback: an opaque machine name (Ashby UUID) but a human LABEL that
        # names a standard identity field. Whitelist-only, so a free-text
        # employer question never resolves here.
        key = _LABEL_STANDARD_FIELDS.get(_normalize_field_label(field.get("label")))
    if key:
        return _standard_answer(key, profile)
    kind = field.get("kind")
    if kind == "tel":
        return _standard_answer("phone", profile)
    if kind == "email":
        return _standard_answer("email", profile)
    if kind == "file":
        label = str(field.get("label") or "").lower()
        if "resume" in label or "cv" in label:
            return RESUME_DOCUMENT
        if "cover" in label:
            return COVER_LETTER_DOCUMENT
    return None


def build_form_fill_plan(
    html: str,
    *,
    channel: str,
    profile: dict[str, Any],
    answer_bank: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """The exact set of values that will be typed into the employer's form.

    Raises :class:`ManualStepRequired` when the page is gated (CAPTCHA / login
    wall — checked FIRST, before any plan exists) or when a REQUIRED field has
    no honest answer, carrying the employer's verbatim question text.

    ``unanswerable_required`` is part of the returned shape for callers that
    want to introspect a successful plan; on a successful return it is empty by
    construction, because an unanswerable required field raises instead.

    ``answer_bank`` (U5d-3, ADR-SUB-AUTON-1 Pillar 1) is an optional
    ``field -> AnswerBankMatch | None`` callable — see
    :func:`app.services.answer_bank.build_resolver`. It is consulted ONLY for
    questions the user's own profile could not answer, and only ever returns an
    answer the USER wrote: the bank stores verbatim answers and the matcher
    refuses anything below its confidence threshold, anything stale, anything
    out of scope and every sensitive/legal class. Omitting it reproduces the
    pre-U5d-3 behaviour exactly, which is what makes this additive.

    Every bank answer that lands in the plan also lands in
    ``answerBankAudit`` — ``{answerBankItemId, matchConfidence, matchMethod,
    questionAsSeen, bankedQuestion, fieldName, perApplication}`` — because ADR
    honesty floor 3 requires every auto-answer to be auditable, and an answer
    typed into an employer's form with no record of WHY would not be.
    """
    blocking = detect_blocking_state(html)
    if blocking == "captcha":
        raise ManualStepRequired(
            "captcha",
            (
                "This application page is showing a CAPTCHA challenge. Aether "
                "does not solve or bypass human checks — open the posting and "
                "complete the application yourself."
            ),
        )
    if blocking == "login_wall":
        raise ManualStepRequired(
            "login_wall",
            (
                "This application page requires an account before it will "
                "accept an application. Aether does not create accounts on "
                "your behalf — sign in and apply there."
            ),
        )
    from app.services.answer_bank import classify_sensitivity, question_text_for_field

    schema = parse_form_schema(html, channel=channel)
    plan_fields: list[dict[str, Any]] = []
    unanswerable: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for field in schema:
        answer = _answer_for(field, profile)
        match = None
        if answer is None and answer_bank is not None:
            # The bank is a FALLBACK, never an override: a value the user's own
            # profile already supplies (their email, their phone) is theirs by
            # a shorter route, and a banked row must never talk over it.
            match = answer_bank(field)
            if match is not None:
                answer = match.answer
        entry = dict(field)
        entry["value"] = answer
        plan_fields.append(entry)
        if match is not None:
            audit.append(
                {
                    "answerBankItemId": match.item_id,
                    "matchConfidence": match.confidence,
                    "matchMethod": match.method,
                    "questionAsSeen": match.question_as_seen,
                    "bankedQuestion": match.banked_question,
                    "fieldName": str(field["name"]),
                    "perApplication": match.per_application,
                }
            )
        if answer is None and field.get("required"):
            asked = question_text_for_field(field)
            unanswerable.append(
                {
                    "name": field["name"],
                    "label": field.get("label") or field["name"],
                    # U5d-3 Pillar 4a: the STRUCTURE the card needs to render a
                    # real input for this question instead of a link away.
                    "kind": field.get("kind") or "text",
                    "required": True,
                    "options": list(field.get("options") or []),
                    "sensitivity": classify_sensitivity(asked),
                }
            )
    if unanswerable:
        questions = "; ".join(item["label"] or item["name"] for item in unanswerable)
        raise ManualStepRequired(
            "unknown_required_question",
            (
                "This application asks a required question Aether has no "
                "stored answer for, and it will not invent one. Answer it "
                f"once and the application can be sent: {questions}"
            ),
            question=questions,
            fields=unanswerable,
        )
    return {
        "fields": plan_fields,
        "unanswerable_required": unanswerable,
        "answerBankAudit": audit,
    }


# ---------------------------------------------------------------------------
# The Answer Bank seam (U5d-3, ADR-SUB-AUTON-1 Pillar 1).
# ---------------------------------------------------------------------------


def build_answer_bank_resolver(
    user_id: str, profile: dict[str, Any], *, company: str | None = None
) -> Callable[[dict[str, Any]], Any]:
    """The bank + this application's own answers, as a resolver for the plan.

    Kept OUT of :func:`build_form_fill_plan` on purpose: the plan builder stays
    pure and offline (it is the module's most heavily tested function), and the
    single database read the bank needs happens here, once per execution.

    A bank that cannot be read is not an error and is never a reason to invent
    an answer: the failure is logged and an EMPTY resolver is returned, so the
    attempt falls back to the pre-U5d-3 behaviour — profile answers only, and
    an honest manual step for anything else.
    """
    from app.services.answer_bank import build_resolver

    screening = profile.get("screeningAnswers")
    try:
        from app.repositories.answer_bank import AnswerBankRepository

        items = AnswerBankRepository().list_for_user(user_id)
    except Exception as exc:  # noqa: BLE001 — a bank outage must not fabricate
        logger.warning(
            "answer bank unreadable for user %s (%s) — falling back to "
            "profile-only answers",
            user_id,
            type(exc).__name__,
        )
        items = []
    return build_resolver(items, screening_answers=screening, company=company)


def record_answer_bank_usage(
    user_id: str,
    application_id: str,
    plan: dict[str, Any],
    *,
    job_id: str | None = None,
) -> int:
    """Write one ``AnswerBankUsage`` row per auto-answer in ``plan``.

    Returns how many were recorded. Entries for answers the user typed for THIS
    application are skipped: they have no bank item behind them, so there is no
    item to attribute a use to — recording one would invent a provenance.

    Best-effort by design. An audit-write failure must never abort a submission
    the user approved, so it is logged loudly and the attempt continues; the
    alternative (refusing to submit because the audit table hiccuped) would be
    a worse outcome for the user and no more honest.
    """
    audit = plan.get("answerBankAudit") or []
    if not audit:
        return 0
    try:
        from app.repositories.answer_bank import AnswerBankRepository

        repo = AnswerBankRepository()
        recorded = 0
        for entry in audit:
            item_id = str(entry.get("answerBankItemId") or "")
            if not item_id or entry.get("perApplication"):
                continue
            repo.record_usage(
                user_id,
                item_id,
                application_id=application_id,
                job_id=job_id,
                question_as_seen=str(entry.get("questionAsSeen") or ""),
                confidence=float(entry.get("matchConfidence") or 0.0),
                method=str(entry.get("matchMethod") or ""),
            )
            recorded += 1
        return recorded
    except Exception as exc:  # noqa: BLE001 — an audit outage is not a refusal
        logger.warning(
            "answer-bank usage audit failed for application %s (%s)",
            application_id,
            type(exc).__name__,
        )
        return 0


# ---------------------------------------------------------------------------
# Row-level recording.
# ---------------------------------------------------------------------------


def record_manual_step(
    user_id: str,
    application_id: str,
    reason: str,
    detail: str | None,
    *,
    questions: list[dict[str, Any]] | None = None,
) -> None:
    """Persist the honest, actionable outcome on the ``Application`` row.

    Never touches ``transmittedAt``: a manual step means nothing was sent, and
    the two states must stay mutually exclusive so the board can never show a
    blocked application as submitted.

    ``questions`` (U5d-3 Pillar 4a) is the STRUCTURE of the unanswered
    questions, exactly as parsed off the employer's page, so the card can
    render a real input for each instead of sending the user to the site. It
    is written as ``NULL`` for every manual step that is not a question — a
    CAPTCHA has nothing to type — and the previous value is always overwritten
    (including to NULL), so a later CAPTCHA can never leave an earlier
    attempt's questions on the row for the card to render stale.
    """
    from app.db import ensure_application_manual_step_question_column

    ensure_application_manual_step_columns()
    ensure_application_manual_step_question_column()
    payload = json.dumps(questions) if questions else None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                UPDATE "Application"
                SET "manualStepReason" = %s,
                    "manualStepDetail" = %s,
                    "manualStepQuestions" = %s::jsonb,
                    "manualStepAt" = NOW(),
                    "updatedAt" = NOW()
                WHERE "id" = %s AND "userId" = %s
                ''',
                (reason, detail, payload, application_id, user_id),
            )
        conn.commit()


def _record_site_transmission(
    user_id: str,
    application_id: str,
    *,
    destination: str,
    channel: str,
    ref: str,
) -> None:
    """Stamp the transmission facts for a WEB-FORM submission.

    Mirrors ``application_submission.record_transmission`` (the W-SUB email
    path) — same columns, same conditional stage advance that never regresses
    an application the user already moved past ``draft`` — and additionally
    clears any manual-step residue, because a completed submission supersedes
    the obstacle that blocked an earlier attempt.

    U5d-2: it also clears a ``recorded_not_transmitted`` truth marker. That
    marker means "recorded with no transmission evidence", and this statement
    is the moment that stops being true. It is cleared ONLY for that exact
    value — the retrospective ``recorded_transmission_unverified`` backfill
    state is left alone, because a pre-fix row that later gains a real
    transmission still has an unverifiable history behind it.
    """
    from app.db import (
        ensure_application_manual_step_question_column,
        ensure_application_submission_truth_columns,
    )
    from app.services.submission_truth import STATE_RECORDED_NOT_TRANSMITTED

    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    ensure_application_manual_step_question_column()
    ensure_application_submission_truth_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                UPDATE "Application"
                SET "transmittedAt" = NOW(),
                    "transmittedTo" = %s,
                    "transmissionChannel" = %s,
                    "transmissionRef" = %s,
                    "manualStepReason" = NULL,
                    "manualStepDetail" = NULL,
                    "manualStepQuestions" = NULL,
                    "manualStepAt" = NULL,
                    "submissionTruthState" = CASE
                        WHEN "submissionTruthState" = %s THEN NULL
                        ELSE "submissionTruthState" END,
                    "submissionTruthAt" = CASE
                        WHEN "submissionTruthState" = %s THEN NULL
                        ELSE "submissionTruthAt" END,
                    "status" = CASE
                        WHEN "status" = 'draft'::"ApplicationStatus"
                            THEN 'submitted'::"ApplicationStatus"
                        ELSE "status" END,
                    "updatedAt" = NOW()
                WHERE "id" = %s AND "userId" = %s
                ''',
                (
                    destination, channel, ref,
                    STATE_RECORDED_NOT_TRANSMITTED, STATE_RECORDED_NOT_TRANSMITTED,
                    application_id, user_id,
                ),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# The browser layer.
# ---------------------------------------------------------------------------


def browser_nice_value() -> int:
    """Niceness applied to the Chromium process tree (default 10).

    This VM has 2 CPUs and runs the API, the worker and the web build on them.
    A browser started at normal priority by a background sweep is exactly the
    kind of neighbour that makes an interactive request time out, so the
    browser runs de-prioritised. ``AETHER_APPLY_BROWSER_NICE`` tunes it.
    """
    raw = (os.environ.get("AETHER_APPLY_BROWSER_NICE") or "").strip()
    try:
        return max(0, min(19, int(raw))) if raw else 10
    except ValueError:
        return 10


def _descendant_pids(root_pid: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        closing = stat.rfind(")")
        if closing == -1:
            continue
        parts = stat[closing + 2 :].split()
        if len(parts) < 2:
            continue
        try:
            children.setdefault(int(parts[1]), []).append(int(entry.name))
        except ValueError:
            continue
    found: list[int] = []
    queue = [root_pid]
    while queue:
        current = queue.pop()
        for child in children.get(current, []):
            if child not in found:
                found.append(child)
                queue.append(child)
    return found


def _renice_browser_tree() -> None:
    """Best-effort de-prioritisation; never fatal, never blocking."""
    value = browser_nice_value()
    if not value:
        return
    try:
        for pid in _descendant_pids(os.getpid()):
            try:
                if os.getpriority(os.PRIO_PROCESS, pid) < value:
                    os.setpriority(os.PRIO_PROCESS, pid, value)
            except OSError:
                continue
    except OSError as exc:  # noqa: BLE001 — priority is an optimisation, not a contract
        logger.debug("could not renice browser tree: %s", exc)


_SUBMIT_TEXT = re.compile(r"\b(submit|send)\b.*\b(application|apply)\b|\bsubmit\b", re.I)


def _evidence_path(evidence_dir: str, application_id: str, suffix: str) -> Path:
    directory = Path(evidence_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return directory / f"apply-{application_id}-{stamp}-{suffix}"


#: Per-action browser timeout (ms). Deliberately short: every action here
#: targets an element we already located in the parsed DOM, so a slow action
#: means the element is not interactable, not that it needs more time — and a
#: form with twenty fields must not spend a minute discovering that.
_ACTION_TIMEOUT_MS = 1500

# CLI-SUB-005 (Architect D8) read-back verification timing. Grounded in the
# 2026-08-16 live instrumentation (evidence/w1/A/pre-fix/): React ATS widgets
# mirror state asynchronously, an Ashby résumé upload can trigger a whole-form
# re-render, and Ashby's Location popup takes up to ~2s to geocode.
_VERIFY_SETTLE_MS = 250  # settle before reading a fill back
_VERIFY_SETTLE_FILE_MS = 1500  # file uploads may re-render the form
_PRESUBMIT_SETTLE_MS = 500  # settle before the pre-submit commit gate
_COMBOBOX_POPUP_POLLS = 10  # x 250ms — bounded wait for an async popup

# CLI-SUB-005-R2 (adversarial review FAIL, 08-adversarial-review.md): bounded
# re-scans of the LIVE DOM for a required field the plan's static snapshot
# never saw. A refill pass can itself reveal a FURTHER conditional (a chain
# of branching questions), so this is never unbounded — after this many
# passes still finding something new, the honest answer is a manual step,
# not another loop iteration.
_MAX_RESCAN_PASSES = 3

# CLI-SUB-005-R4 (adversarial re-review FAIL,
# RUN-20260818T0223Z/SUB-005-R3/08-adversarial-rereview.md, finding #2): R3's
# loop counted its confirming "did anything change?" pass INSIDE the SAME
# bounded counter as the resolving passes themselves, so a chain needing
# exactly _MAX_CONVERGENCE_PASSES resolving passes had no budget left for the
# pass that PROVES it is done — the R2 off-by-one moved from depth 3 to depth
# 4 instead of being eliminated. R4 (:func:`_converge_presubmit_state`)
# decouples the two counts structurally: the "did anything change?"
# re-derivation always runs one extra, UNCOUNTED time after the last
# resolving pass (it is what detects convergence, not a separate check spent
# from the same budget), so this bound now means "resolving passes before
# giving up honestly", never "total loop iterations including the proof that
# it's done". Raised to 6 to give a legitimately deep conditional chain real
# headroom without ever letting a genuinely unbounded one loop forever.
_MAX_CONVERGENCE_PASSES = 6

# CLI-SUB-005-R5 (adversarial FAIL,
# RUN-20260818T0223Z/SUB-005-R4/08-adversarial-final.md): a required field
# living only inside an <iframe> was invisible to every pass of
# _uncommitted_live_required_fields, because that function's only input is
# parse_form_schema(root.content()) — a single document. These back the
# CONSERVATIVE REFUSE-BACKSTOP (_verify_no_unverifiable_form_surface) that
# makes soundness independent of what any one parser call can recognize: a
# raw structural census of form-shaped controls, checked against what
# parse_form_schema actually turned into a field — not a re-run of any one
# channel's own rules. Mirrors the exclusions every existing parser already
# applies (a hidden reCAPTCHA token, the intl-tel-input library's own
# internal state field) — those are deliberate non-questions, not unknown
# surfaces, and flagging them would be noise that trains someone to ignore
# this gate.
_CENSUS_EXCLUDED_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image", "search"}
_CENSUS_INTERACTIVE_ROLES = {
    "combobox", "radio", "checkbox", "listbox", "switch", "textbox",
    "spinbutton", "slider", "menuitemradio", "menuitemcheckbox",
}


def _wait(page: Any, ms: int) -> None:
    """Best-effort settle. Unit-test fakes may not implement the clock."""
    try:
        page.wait_for_timeout(ms)
    except Exception:  # noqa: BLE001 — a fake page without a clock waits zero
        pass


def _reachable_frames(page: Any) -> list[Any]:
    """Every child frame currently attached to ``page``, main frame excluded.

    CLI-SUB-005-R5: re-read FRESH by the caller on every pass — a frame can
    attach, navigate or detach between passes exactly like any other live DOM
    mutation, so a snapshot taken once would go stale the same way the pre-R4
    name-ledger did. A page-like object with no frame concept at all (this
    repo's own unit-test fakes, which predate frame support) reports zero
    frames rather than erroring: there is nothing beyond the top document it
    already represents, never an unknown surface to refuse over.
    """
    try:
        frames = list(page.frames)
    except Exception:  # noqa: BLE001 — no `.frames` at all is zero frames, not an error
        return []
    main = getattr(page, "main_frame", None)
    reachable: list[Any] = []
    for frame in frames:
        if frame is main:
            continue
        try:
            if frame.is_detached():
                continue
        except Exception:  # noqa: BLE001 — can't tell; leave it to the caller's own read
            pass
        reachable.append(frame)
    return reachable


def _frame_label(frame: Any) -> str:
    """A human-readable pointer at one frame, for a manual-step message."""
    try:
        url = str(frame.url or "")
    except Exception:  # noqa: BLE001 — an unreadable frame has no url either
        url = ""
    return f"embedded frame ({url})" if url else "an embedded frame"


def _first_present(page: Any, selectors: list[str]) -> Any | None:
    """The first selector that actually matches, resolved WITHOUT auto-waiting.

    ``count()`` returns immediately, so probing candidate selectors costs
    milliseconds instead of one action-timeout each.
    """
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                return locator.first
        except Exception:  # noqa: BLE001 — a malformed selector is just a miss
            continue
    return None


#: An answer that unambiguously means "tick it", anchored at the START of the
#: answer so the affirmation is the answer's subject and not a clause buried
#: inside it. Read together with :data:`_ANSWER_REFUSAL`, which vetoes it.
_AFFIRMATIVE_ANSWER = re.compile(
    r"^(yes|y|true|agreed?|confirmed?|accepted?|acknowledged?|certify|certified|"
    r"i (agree|confirm|accept|acknowledge|certify|understand|declare|have read))\b"
)

#: Any word that turns an answer into a refusal. Deliberately broad — the cost
#: of a false positive is a required box left unticked, which
#: :func:`run_apply_execution` already turns into an honest ``form_fill_failed``
#: manual step; the cost of a false negative is the agent agreeing to something
#: on the user's behalf.
_ANSWER_REFUSAL = re.compile(
    r"\b(no|not|never|cannot|decline|declined|refuse|refused|unwilling)\b"
)


def _match_choice_option(answer: str, options: list[str]) -> str | None:
    """The option label a radio/checkbox answer selects, or ``None``.

    Gives choice widgets the same tolerance the combobox path already has for
    widgets whose option text differs from the user's wording — a banked
    ``"Yes"`` onto ``"Yes, I'm based in Australia"``, ``"Australian Citizen"``
    onto ``"I am an Australian/New Zealand Citizen"``. Order: exact, then the
    LONE-OPTION rule, then a yes/no head match, then a one-way prefix, then a
    >=1-shared-token STRICT DOMINANCE rule. A tie or no overlap returns
    ``None`` (recorded as unfilled) rather than guessing between an employer's
    options.

    THE LONE-OPTION RULE (SUB-008). An acknowledgement tick is ONE checkbox
    whose label is the statement itself ("I certify that the information
    provided is true"). There is nothing to choose between, so the answer's
    POLARITY is the only thing that decides it, and the token-overlap rule
    below is the wrong instrument twice over: a bare ``"Yes"`` shares no word
    with the employer's sentence and would leave a required box unticked,
    while a REFUSAL ("no, I do not want a blanket declaration that the
    information provided is true") shares most of them and would tick the box
    the user just declined. So a lone option is ticked only for an
    unambiguously affirmative answer, and a refusal stops here — never falling
    through to a rule that reads it as agreement.
    """
    if not options:
        return None

    def _n(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", str(text).lower())).strip()

    ans = _n(answer)
    if not ans:
        return None
    norm = [(opt, _n(opt)) for opt in options]
    for opt, no in norm:  # exact
        if no == ans:
            return opt
    if len(norm) == 1:
        only_option, only_norm = norm[0]
        if _ANSWER_REFUSAL.search(ans):
            return None
        if _AFFIRMATIVE_ANSWER.match(ans) and not _ANSWER_REFUSAL.match(only_norm):
            return only_option
    ans_head = ans.split(" ", 1)[0]
    if ans_head in ("yes", "no"):  # yes/no question — head word decides
        heads = [opt for opt, no in norm if no.split(" ", 1)[0] == ans_head]
        if len(heads) == 1:
            return heads[0]
    prefix = [opt for opt, no in norm if no and (no.startswith(ans) or ans.startswith(no))]
    if len(prefix) == 1:
        return prefix[0]
    ans_tokens = {t for t in ans.split() if len(t) > 1}
    best, best_score, second = None, 0, 0
    for opt, no in norm:
        score = len({t for t in no.split() if len(t) > 1} & ans_tokens)
        if score > best_score:
            best, second, best_score = opt, best_score, score
        elif score > second:
            second = score
    if best is not None and best_score >= 1 and best_score > second:
        return best
    return None


def _locate_file_input(page: Any, field: dict[str, Any]) -> Any | None:
    """The field's OWN ``input[type=file]`` — verified, never a page gamble.

    CLI-SUB-005: the live Ashby page mounts an "Autofill from resume" file
    input ABOVE the real form, outside every ``[data-field-path]`` block, and
    uploading into it re-renders the form and wipes already-typed fields (the
    flagship empty-application evidence). So every candidate match is verified
    to actually BE a file input, and — when the parsed field carries a scope —
    to live INSIDE that scope. No verified in-scope input means ``None``: the
    caller refuses (honest unfilled) rather than uploading into a stranger.
    """
    name = str(field["name"])
    scope = str(field.get("scope") or "")
    live_selector = str(field.get("liveSelector") or "")
    escaped = name.replace('"', '\\"')
    # CLI-SUB-005-R6: a live-census-discovered field (root cause 1) carries a
    # `liveSelector` — a marker attribute placed directly on the control
    # itself, which Playwright's CSS engine resolves by piercing shadow DOM —
    # tried FIRST, ahead of the id/name guesses this control may not have.
    candidates = ([live_selector] if live_selector else []) + (
        [f"{scope} input[type=file]"] if scope else []
    ) + [
        f'[id="{escaped}"]',
        f'[name="{escaped}"]',
    ]
    for selector in candidates:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception:  # noqa: BLE001 — a malformed selector is just a miss
            continue
        for index in range(min(count, 5)):
            candidate = locator.nth(index)
            try:
                if not candidate.evaluate("el => el.tagName === 'INPUT' && el.type === 'file'"):
                    continue
                if scope and not candidate.evaluate("(el, s) => !!el.closest(s)", scope):
                    continue
            except Exception:  # noqa: BLE001 — unverifiable is not usable
                continue
            return candidate
    return None


def _fill_value(page: Any, field: dict[str, Any], value: Any, documents: dict[str, str]) -> bool:
    """Type one planned answer into the real DOM. ``True`` iff it landed.

    Returning ``False`` is recorded (``fieldsNotFilled`` in the evidence
    sidecar) rather than silently ignored: a submission whose fields did not
    all land is a fact the audit trail has to carry.
    """
    name = str(field["name"])
    kind = str(field.get("kind") or "text")
    scope = str(field.get("scope") or "")
    # CLI-SUB-005-R6 root cause 1: a live-census-discovered field's own
    # marker-attribute locator, resolved by Playwright's shadow-DOM-piercing
    # CSS engine — tried BEFORE the id/name guesses below, which a shadow-
    # hosted or otherwise anonymous control may never have at all.
    live_selector = str(field.get("liveSelector") or "")
    escaped = name.replace('"', '\\"')
    # Attribute selectors, never ``#id``: real ATS field ids start with digits
    # (Ashby's UUID-keyed questions) or carry ``[]`` (Greenhouse's checkbox
    # groups), both of which are invalid inside a CSS id selector.
    control_selectors = ([live_selector] if live_selector else []) + [
        f'[id="{escaped}"]', f'[name="{escaped}"]'
    ]
    scoped_controls = (
        [
            f"{scope} input:not([type=hidden])",
            f"{scope} textarea",
            f"{scope} select",
        ]
        if scope
        else []
    )
    if kind == "file":
        path = documents.get(str(value))
        if not path:
            return False
        # CLI-SUB-005 fix (a): strictly the field's own verified file input —
        # never an unguarded [id=]/[name=] grab that can hit Ashby's
        # "Autofill from resume" box outside the field's scope.
        target = _locate_file_input(page, field)
        if target is None:
            return False
        try:
            target.set_input_files(path, timeout=_ACTION_TIMEOUT_MS)
            return True
        except Exception:  # noqa: BLE001 — recorded as unfilled, never faked
            return False
    text_value = str(value)
    if kind in {"radio", "checkbox"}:
        if live_selector:
            # A native shadow-DOM/anonymous checkbox or radio, tagged
            # directly — a real `.check()` is both simpler and more reliable
            # than the label-text guesses below, which assume Ashby/
            # Greenhouse's own UI sugar (a sibling <label> reading the exact
            # answer text) that a bare custom element has no reason to carry.
            try:
                page.locator(live_selector).first.check(timeout=_ACTION_TIMEOUT_MS)
                return True
            except Exception:  # noqa: BLE001 — fall through to the label-text path
                pass
        candidates = [f'{scope} >> text="{text_value}"'] if scope else []
        candidates.append(f'label:text-is("{text_value}")')
        target = _first_present(page, candidates)
        if target is None:
            # Option-aware fuzzy match against the parsed choice labels, so a
            # banked "Yes"/"Australian Citizen" lands on the widget's own
            # verbose option instead of leaving a required yes/no unfilled.
            matched = _match_choice_option(text_value, field.get("options") or [])
            if matched:
                esc = matched.replace('"', '\\"')
                fuzzy = [f'{scope} >> text="{esc}"'] if scope else []
                fuzzy += [
                    f'label:text-is("{esc}")',
                    f'label:has-text("{esc}")',
                    f'text="{esc}"',
                ]
                target = _first_present(page, fuzzy)
        if target is None:
            return False
        try:
            target.click(timeout=_ACTION_TIMEOUT_MS)
            return True
        except Exception:  # noqa: BLE001
            return False
    if kind == "select":
        target = _first_present(page, control_selectors + scoped_controls)
        if target is None:
            return False
        try:
            target.select_option(label=text_value, timeout=_ACTION_TIMEOUT_MS)
            return True
        except Exception:  # noqa: BLE001
            return False
    if kind == "combobox":
        # Greenhouse/Ashby render required dropdowns as React typeahead
        # comboboxes (`role="combobox"` / `select__input`): a bare ``.fill()``
        # types text the widget never commits, so the field stays empty and the
        # site rejects the submit — exactly the Easygo no_confirmation ending
        # (2026-08-15). Operate the widget like a person: open it, type to
        # filter, then CLICK the matching option from the popup listbox. The
        # option must actually match the planned answer — when nothing matching
        # is shown this returns ``False`` (recorded as unfilled) rather than
        # committing whatever happens to be highlighted.
        target = _first_present(page, control_selectors + scoped_controls)
        if target is None:
            return False
        try:
            target.click(timeout=_ACTION_TIMEOUT_MS)
            target.fill(text_value, timeout=_ACTION_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            return False
        option_text = text_value.replace('"', '\\"')
        option_selectors = [
            f'[role="option"]:text-is("{option_text}")',
            f'[role="option"]:has-text("{option_text}")',
            f'[class*="select__option"]:text-is("{option_text}")',
            f'[class*="select__option"]:has-text("{option_text}")',
        ]
        option = _first_present(page, option_selectors)
        if option is None:
            # CLI-SUB-005 root cause: a live ATS combobox populates its popup
            # ASYNCHRONOUSLY (Ashby's Location geocodes the typed text), so an
            # instant probe reads "no options" and the old code fell through to
            # raw typing that the widget wiped on blur — then Submit was
            # clicked over an empty required field (the flagship evidence).
            # Wait — bounded — for the popup to render before concluding.
            for _ in range(_COMBOBOX_POPUP_POLLS):
                try:
                    if page.locator('[role="option"], [class*="select__option"]').count() > 0:
                        break
                except Exception:  # noqa: BLE001
                    break
                _wait(page, 250)
            option = _first_present(page, option_selectors)
        if option is not None:
            try:
                option.click(timeout=_ACTION_TIMEOUT_MS)
                return True
            except Exception:  # noqa: BLE001
                return False
        # No literal match. If the typeahead narrowed the popup to EXACTLY one
        # candidate, that is the widget's own canonical phrasing of the typed
        # answer (e.g. "Australia" -> "Australia (AU)") — commit it. Two or
        # more remaining candidates is a genuine ambiguity: refuse, honestly.
        try:
            options = page.locator('[role="option"], [class*="select__option"]')
            if options.count() == 1:
                options.first.click(timeout=_ACTION_TIMEOUT_MS)
                return True
        except Exception:  # noqa: BLE001
            return False
        # Typing the full answer can filter the popup to NOTHING when the
        # widget's canonical phrasings differ from the user's wording (Easygo:
        # answer "Australian Citizen" vs option "I am an Australian/New Zealand
        # Citizen"). Clear the filter so the popup shows the FULL list and
        # commit the option the answer's own words pick out — but only under a
        # strict-dominance rule: the best option must share >=2 content tokens
        # with the answer AND strictly beat every other option. A tie or a
        # <2-token overlap is a genuine ambiguity: refuse (recorded as
        # unfilled), never guess between an employer's options.
        try:
            target.fill("", timeout=_ACTION_TIMEOUT_MS)
            options = page.locator('[role="option"], [class*="select__option"]')
            count = min(options.count(), 50)
            answer_tokens = {t for t in re.findall(r"[a-z0-9]+", text_value.lower()) if len(t) > 1}
            best_idx, best_score, second_score = -1, 0, 0
            for idx in range(count):
                option_text = str(options.nth(idx).inner_text() or "").lower()
                option_tokens = {
                    t
                    for t in re.findall(r"[a-z0-9]+", option_text)
                    if len(t) > 1
                }
                score = len(answer_tokens & option_tokens)
                if score > best_score:
                    best_idx, second_score, best_score = idx, best_score, score
                elif score > second_score:
                    second_score = score
            if best_idx >= 0 and best_score >= 2 and best_score > second_score:
                options.nth(best_idx).click(timeout=_ACTION_TIMEOUT_MS)
                return True
            if count == 0:
                # The widget rendered NO options at all — even with the filter
                # cleared and after the bounded popup wait above. Either the
                # page is an inert captured DOM (replay mode — page JS is
                # deliberately blocked) or the control is a free-text combobox
                # that takes typed input directly. The only commitment such a
                # widget offers is the typed text itself — so re-type the
                # answer, BLUR the control (the commit gesture), and report it
                # filled ONLY if the input verifiably retained the text
                # through the blur. CLI-SUB-005: a live React widget wipes
                # uncommitted text exactly on blur (the flagship empty
                # Location), so this read-back is what separates a real
                # free-text fill from the lie the old fallback told.
                target.fill(text_value, timeout=_ACTION_TIMEOUT_MS)
                try:
                    target.evaluate("el => el.blur && el.blur()")
                except Exception:  # noqa: BLE001 — no blur surface: value check decides
                    pass
                _wait(page, 150)
                return target.input_value(timeout=_ACTION_TIMEOUT_MS) == text_value
        except Exception:  # noqa: BLE001
            return False
        return False
    for selector in control_selectors + scoped_controls:
        target = _first_present(page, [selector])
        if target is None:
            continue
        try:
            target.fill(text_value, timeout=_ACTION_TIMEOUT_MS)
            return True
        except Exception:  # noqa: BLE001 — try the next shape, never fake it
            continue
    return False


def _normalized_answer(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", str(text).lower())).strip()


def _same_answer(observed: str, expected: str) -> bool:
    """Does the DOM's committed text answer the planned value? (Tolerates the
    widget's own canonical phrasing containing the answer, or vice versa.)"""
    obs, exp = _normalized_answer(observed), _normalized_answer(expected)
    if not obs or not exp:
        return False
    return obs == exp or exp in obs or obs in exp


def _commit_state(
    page: Any, field: dict[str, Any], value: Any, documents: dict[str, str]
) -> tuple[bool, str]:
    """What the DOM actually holds for one planned answer: (committed, observed).

    CLI-SUB-005 fix (b): a fill only counts once the control's COMMITTED state
    can be read back — ``input.value`` / ``:checked`` (plus the class/aria
    markers React choice widgets use) / the selected option's text / the
    uploaded file's name or its file-name chip / a combobox's displayed value.
    Signal choices are grounded in the 2026-08-16 live instrumentation
    (evidence/w1/A/): Ashby yes/no buttons mark the chosen option with an
    ``_active``-style class only; Greenhouse job-boards REMOVES the file input
    once an upload lands, leaving the chip as the only DOM evidence.
    """
    name = str(field["name"])
    kind = str(field.get("kind") or "text")
    scope = str(field.get("scope") or "")
    live_selector = str(field.get("liveSelector") or "")
    escaped = name.replace('"', '\\"')
    control_selectors = ([live_selector] if live_selector else []) + [
        f'[id="{escaped}"]', f'[name="{escaped}"]'
    ]
    scoped_controls = (
        [f"{scope} input:not([type=hidden])", f"{scope} textarea", f"{scope} select"]
        if scope
        else []
    )
    if kind == "file":
        expected = os.path.basename(str(documents.get(str(value)) or ""))
        if not expected:
            return False, "no document to verify"
        target = _locate_file_input(page, field)
        if target is not None:
            try:
                observed = str(
                    target.evaluate(
                        "el => el.files && el.files.length ? el.files[0].name : ''"
                    )
                    or ""
                )
                if observed == expected:
                    return True, f"files[0].name={observed!r}"
            except Exception:  # noqa: BLE001 — fall through to the chip check
                pass
        chip_selectors = ([f'{scope} >> text="{expected}"'] if scope else []) + [
            f'text="{expected}"'
        ]
        if _first_present(page, chip_selectors) is not None:
            return True, f"file-name chip {expected!r}"
        return False, "no file committed"
    text_value = str(value)
    if kind in {"radio", "checkbox"}:
        if live_selector:
            try:
                if page.locator(live_selector).first.is_checked(timeout=_ACTION_TIMEOUT_MS):
                    return True, "live-census control checked"
            except Exception:  # noqa: BLE001 — fall through to the signal-selector path
                pass
        signal_selectors = (
            [
                f"{scope} input:checked",
                f'{scope} [aria-pressed="true"]',
                f'{scope} [aria-checked="true"]',
                f'{scope} [data-state="checked"]',
                f'{scope} [aria-selected="true"]',
                f'{scope} [class*="_active"]',
                f'{scope} [class*="_selected"]',
            ]
            if scope
            else [f'input[name="{escaped}"]:checked', f'[id="{escaped}"]:checked']
        )
        for selector in signal_selectors:
            try:
                if page.locator(selector).count() > 0:
                    return True, f"selection marker {selector!r}"
            except Exception:  # noqa: BLE001 — try the next signal shape
                continue
        return False, "no checked/active option"
    if kind == "select":
        target = _first_present(page, control_selectors + scoped_controls)
        if target is None:
            return False, "control not found"
        try:
            observed = str(
                target.evaluate(
                    "el => el.selectedOptions && el.selectedOptions.length"
                    " ? (el.selectedOptions[0].textContent || '').trim() : ''"
                )
                or ""
            )
        except Exception:  # noqa: BLE001
            return False, "selection unreadable"
        if _same_answer(observed, text_value):
            return True, f"selected {observed!r}"
        return False, f"selected {observed!r}"
    if kind == "combobox":
        target = _first_present(page, control_selectors + scoped_controls)
        if target is None:
            return False, "control not found"
        try:
            expanded = str(target.evaluate("el => el.getAttribute('aria-expanded') || ''") or "")
        except Exception:  # noqa: BLE001
            expanded = ""
        try:
            display = str(target.input_value(timeout=_ACTION_TIMEOUT_MS) or "")
        except Exception:  # noqa: BLE001
            display = ""
        if not display.strip():
            # React selects (Greenhouse) clear the input and render the chosen
            # text in a sibling single-value element instead.
            try:
                display = str(
                    target.evaluate(
                        """el => { let n = el; for (let i = 0; i < 6 && n; i++) {
                            const sv = n.querySelector && n.querySelector(
                                '[class*="single-value"], [class*="singleValue"]');
                            if (sv && sv.textContent && sv.textContent.trim())
                                return sv.textContent.trim();
                            n = n.parentElement; } return ''; }"""
                    )
                    or ""
                )
            except Exception:  # noqa: BLE001
                display = ""
        # Typed-but-uncommitted text sits in an OPEN popup (the flagship live
        # Location state) — display text only counts with the popup closed.
        if display.strip() and expanded != "true":
            return True, f"displays {display.strip()!r}"
        return False, f"displays {display.strip()!r} (aria-expanded={expanded or 'n/a'})"
    # text / textarea / email / tel / url / number / date
    target = _first_present(page, control_selectors + scoped_controls)
    if target is None:
        return False, "control not found"
    try:
        observed = str(target.input_value(timeout=_ACTION_TIMEOUT_MS) or "")
    except Exception:  # noqa: BLE001
        # CLI-SUB-005-R6: a live-census-discovered `[contenteditable]` box
        # (root cause 1) is not an <input>/<textarea>/<select> at all, so
        # `input_value()` always raises for it — read its committed TEXT
        # directly instead of reporting a genuinely readable control as
        # unreadable. Every pre-existing field has no `liveSelector`, so
        # this branch is unreachable for them — zero behaviour change.
        if live_selector:
            try:
                observed = str(
                    page.locator(live_selector)
                    .first.evaluate("el => (el.textContent || '').trim()")
                    or ""
                )
            except Exception:  # noqa: BLE001
                return False, "value unreadable"
        else:
            return False, "value unreadable"
    if kind == "tel":
        observed_digits = re.sub(r"\D", "", observed)
        expected_digits = re.sub(r"\D", "", text_value)
        if observed_digits and expected_digits and (
            observed_digits.endswith(expected_digits)
            or expected_digits.endswith(observed_digits)
        ):
            return True, f"value {observed!r}"
        return False, f"value {observed!r}"
    if observed.strip() == text_value.strip():
        return True, f"value {observed!r}"
    return False, f"value {observed!r}"


def _fill_and_verify(
    page: Any,
    field: dict[str, Any],
    value: Any,
    documents: dict[str, str],
    *,
    verify: bool,
) -> bool:
    """Fill, read the commit back, retry ONCE on mismatch — never claim.

    ``verify=False`` reproduces the raw pre-CLI-SUB-005 behaviour and is used
    ONLY in replay mode: a replayed page is a JS-dead capture (network and
    scripts deliberately blocked), so React widgets can never mirror state
    there and no employer can receive anything from it.
    """
    filled = _fill_value(page, field, value, documents)
    if not verify:
        return filled
    settle = _VERIFY_SETTLE_FILE_MS if str(field.get("kind") or "") == "file" else _VERIFY_SETTLE_MS
    if filled:
        _wait(page, settle)
        committed, _observed = _commit_state(page, field, value, documents)
        if committed:
            return True
    filled = _fill_value(page, field, value, documents)  # ONE retry (re-click/re-fill)
    if not filled:
        return False
    _wait(page, settle)
    committed, _observed = _commit_state(page, field, value, documents)
    return committed


def _run_fill_plan(
    page: Any,
    plan_fields: list[dict[str, Any]],
    documents: dict[str, str],
    *,
    verify: bool,
) -> tuple[list[str], list[str], list[str]]:
    """Execute the plan's fills. Returns (filled, unfilled, blocked_required).

    With ``verify=True`` (live mode) a field is only ``filled`` once its
    committed DOM state was read back — a fill the page did not keep lands in
    ``unfilled`` (and ``blocked_required`` when required) instead of being
    claimed, which is the whole CLI-SUB-005 fix.
    """
    filled: list[str] = []
    unfilled: list[str] = []
    blocked_required: list[str] = []
    for field in plan_fields:
        value = field.get("value")
        if value is None:
            continue
        if _fill_and_verify(page, field, value, documents, verify=verify):
            filled.append(str(field["name"]))
        else:
            unfilled.append(str(field["name"]))
            if field.get("required"):
                blocked_required.append(str(field.get("label") or field["name"]))
    return filled, unfilled, blocked_required


def _uncommitted_required_planned(
    page: Any, plan_fields: list[dict[str, Any]], documents: dict[str, str]
) -> list[dict[str, Any]]:
    """REQUIRED planned fields whose committed DOM state is missing right now."""
    stale: list[dict[str, Any]] = []
    for field in plan_fields:
        value = field.get("value")
        if value is None or not field.get("required"):
            continue
        committed, _observed = _commit_state(page, field, value, documents)
        if not committed:
            stale.append(field)
    return stale


def _presubmit_required_commit_gate(
    page: Any, plan_fields: list[dict[str, Any]], documents: dict[str, str]
) -> None:
    """No empty application is ever fired at an employer (CLI-SUB-005 fix (c)).

    Immediately before the submit click, every REQUIRED planned field is
    re-verified against the live DOM — this is what catches a re-render that
    wiped fields AFTER their own fills verified (Ashby's autofill-from-resume
    upload re-renders the whole form). Wiped fields get ONE refill pass; if
    anything required is still uncommitted, ``ManualStepRequired
    ('form_fill_failed')`` is raised carrying the exact field labels and the
    submit control is NEVER activated.
    """
    _wait(page, _PRESUBMIT_SETTLE_MS)
    stale = _uncommitted_required_planned(page, plan_fields, documents)
    if not stale:
        return
    for field in stale:  # one refill pass — a re-render wiped these
        _fill_and_verify(page, field, field.get("value"), documents, verify=True)
    still = _uncommitted_required_planned(page, plan_fields, documents)
    if not still:
        return
    labels = "; ".join(str(field.get("label") or field["name"]) for field in still)
    raise ManualStepRequired(
        "form_fill_failed",
        (
            "Aether typed the answers but this application form did not keep "
            "every required one (the page re-rendered or rejected the "
            "values), so it submitted nothing. Open the posting and apply "
            "yourself: " + labels
        ),
        question=labels,
    )


def _live_required_fields_not_in(
    page: Any, channel: str, known_names: set[str]
) -> list[dict[str, Any]]:
    """REQUIRED fields the LIVE DOM shows right now that ``known_names`` never saw.

    Re-runs the channel's OWN schema parser (:func:`parse_form_schema`)
    against the CURRENT ``page.content()`` — never the static pre-fill
    snapshot :func:`build_form_fill_plan` was built from. This is what catches
    a conditional/branching question (first-class on both Ashby and
    Greenhouse: "Do you require visa sponsorship?" -> Yes -> reveals a
    required "please explain" box) that could not have existed in an
    unanswered snapshot taken before the browser session even opened.
    """
    try:
        html = page.content()
    except Exception:  # noqa: BLE001 — a page without a live DOM yields nothing new
        return []
    try:
        live_schema = parse_form_schema(html, channel=channel)
    except Exception:  # noqa: BLE001 — a parse failure must not crash the gate
        return []
    return [
        field
        for field in live_schema
        if field.get("required") and str(field["name"]) not in known_names
    ]


def _resolve_unplanned_required_fields(
    page: Any,
    channel: str,
    plan_fields: list[dict[str, Any]],
    documents: dict[str, str],
    *,
    profile: dict[str, Any] | None,
    answer_bank: Callable[[dict[str, Any]], Any] | None,
) -> list[str]:
    """Catch a required field the pre-fill snapshot could not have seen.

    CLI-SUB-005-R2 (adversarial review FAIL, 08-adversarial-review.md):
    :func:`build_form_fill_plan` runs exactly ONCE, against a STATIC,
    UNANSWERED page snapshot taken before the browser session that fills and
    submits the form ever opens (``fetch_apply_page`` -> ``page.content()``).
    A conditional/branching question is therefore structurally invisible to
    that plan — not a race condition, a logical impossibility for an
    unanswered snapshot to contain a question that only exists once an
    earlier question is answered. Both the fill loop and the pre-submit gate
    used to iterate that same fixed ``plan["fields"]`` list and nothing
    else, so a real required field sitting in the live DOM at submit time
    was never attempted, never verified — and the executor reported a
    VERIFIED, CONFIRMED submission over it (reproduced against the real
    ``playwright_form_submitter`` in ``adversarial/attack_stale_plan.py``).

    Immediately before the final pre-submit gate, re-scan the LIVE DOM with
    the channel's own parser and resolve anything the plan never saw, via
    the EXACT SAME ``_answer_for`` / answer-bank path
    :func:`build_form_fill_plan` itself uses — never inventing an answer. A
    resolved field is APPENDED to ``plan_fields`` in place, so the caller's
    own :func:`_presubmit_required_commit_gate` re-verifies it (and catches
    it being wiped by a later re-render) exactly like every other planned
    field.

    Filling a newly-revealed field can itself reveal a FURTHER conditional (a
    chain of branching questions), so this re-scans again after every
    successful pass — bounded at :data:`_MAX_RESCAN_PASSES`, after which it
    refuses honestly rather than assume the chain has ended. Any field that
    cannot be answered, or whose fill cannot be verified as committed, raises
    immediately with the distinct ``"unplanned_required_field"`` reason: this
    NEVER submits past an unplanned required field.

    Returns the names of the fields it resolved (filled AND verified), for
    the caller's own evidence sidecar — visibility that a submission needed
    this safety net at all, not just that it eventually succeeded.
    """
    known = {str(field["name"]) for field in plan_fields}
    resolved: list[str] = []
    for _pass in range(_MAX_RESCAN_PASSES):
        unplanned = _live_required_fields_not_in(page, channel, known)
        if not unplanned:
            return resolved
        unresolved_labels: list[str] = []
        for field in unplanned:
            name = str(field["name"])
            known.add(name)  # never re-attempt the same field name
            answer = _answer_for(field, profile or {})
            if answer is None and answer_bank is not None:
                match = answer_bank(field)
                if match is not None:
                    answer = match.answer
            if answer is None:
                unresolved_labels.append(str(field.get("label") or name))
                continue
            entry = dict(field)
            entry["value"] = answer
            if not _fill_and_verify(page, entry, answer, documents, verify=True):
                unresolved_labels.append(str(field.get("label") or name))
                continue
            plan_fields.append(entry)
            resolved.append(name)
        if unresolved_labels:
            labels = "; ".join(unresolved_labels)
            raise ManualStepRequired(
                "unplanned_required_field",
                (
                    "This application revealed a required question after "
                    "Aether had already built its plan (a conditional "
                    "follow-up), and it could not be answered and verified, "
                    "so nothing was submitted. Open the posting and finish "
                    "it yourself: " + labels
                ),
                question=labels,
            )
    # Exhausted every bounded pass and the DOM is STILL revealing new
    # required fields (a chain of conditionals deeper than any real ATS form
    # should need) -- refuse rather than guess how many more there are.
    still = _live_required_fields_not_in(page, channel, known)
    labels = "; ".join(str(f.get("label") or f["name"]) for f in still)
    raise ManualStepRequired(
        "unplanned_required_field",
        (
            "This application kept revealing new required questions after "
            "Aether's plan was built, so it stopped rather than guess how "
            "many more there might be. Open the posting and finish it "
            "yourself." + (f" Last seen: {labels}" if labels else "")
        ),
        question=labels or None,
    )


# ---------------------------------------------------------------------------
# CLI-SUB-005-R6 — ROOT-CAUSE fix for the two mechanisms
# RUN-20260818T0223Z/SUB-005-R5/08-adversarial-final.md proved underlie the
# ENTIRE R2->R5 series (05-decision-memos/SUB-005-and-COV-3-rulings.md, "SUB-
# 005 R5 outcome + R6 ruling"):
#
# (1) Every census above this point (_uncommitted_live_required_fields'
#     `parse_form_schema(page.content())` call, _unclassifiable_controls'
#     BeautifulSoup walk) reads `page.content()`/`frame.content()` — a
#     SERIALIZED STRING SNAPSHOT of the light DOM only. An OPEN shadow root's
#     content is not merely unparsed by that string: it is STRUCTURALLY
#     ABSENT from it, so no amount of re-parsing, however fresh, can ever see
#     a control that lives inside one (attack #6: a bare custom-element host
#     with no role/contenteditable, whose real required control lives in its
#     own open shadow root).
# (2) The call site was CHECK-then-ACT: every safety net above runs, THEN
#     `_activate_submit` clicks — and Playwright's own click dispatches a
#     real DOM event sequence (mousedown before click, by spec, deterministic
#     for the SAME click) a page's own handler can use to reveal a brand-new,
#     perfectly classifiable required field in that gap, with nothing here
#     ever re-verifying anything after (attack #7).
#
# _composed_live_census (below) closes (1): it runs LIVE, inside the page's
# or frame's own JS execution context via Playwright's `evaluate()`, and
# walks the COMPOSED tree — every element reachable through `.shadowRoot`
# (OPEN shadow roots only; a CLOSED shadow root's content is genuinely
# unreachable by ANY web API, Playwright's locators included — a real
# browser-platform limit, not a gap left open by choice) — so a shadow-DOM-
# hosted required control IS seen, read at the instant this runs, never from
# a cached string. It feeds :func:`_uncommitted_live_required_fields` as a
# SUPPLEMENTARY source, additive to (never replacing) the existing
# `parse_form_schema` path, so every already-covered field (Ashby/Greenhouse/
# generic, matched by id/name/`[data-field-path]`) is still resolved exactly
# as before — only a control NO parser call can classify at all newly
# appears, exactly the residual class this round must close.
#
# _install_submission_guard closes (2) by construction rather than by adding
# yet another check-then-act layer (the same class of gap, merely narrower):
# it installs a CAPTURE-PHASE 'submit' and submit-click listener, in-browser,
# that re-runs the SAME composed census AT THE INSTANT the event fires and
# cancels the submission outright (`preventDefault` + `stopImmediatePropagation`)
# if anything required is still uncommitted THEN — never a Python-side gap for
# page-authored JS to win a race against. The property this makes hold:
# a required control uncommitted at the instant of submission => the
# submission does not complete => Python observes no submission occurred and
# raises an honest ManualStepRequired, never a silent submit.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CLI-SUB-005-R7 — FAIL CLOSED at every verification boundary, plus a
# BUBBLE-PHASE re-check. RUN-20260818T0223Z/SUB-005-R6/08-adversarial-
# final.md FAILed R6 on three silent submits over an empty required field
# (05-decision-memos/SUB-005-and-COV-3-rulings.md, "SUB-005 R6 outcome + R7
# ruling"), which split into two distinct classes:
#
# (1) attacks B and F — REAL correctness defects, not exotic-DOM cat-and-
#     mouse: `_install_submission_guard` and `_composed_live_census` each
#     wrapped their `evaluate()` call in a bare `except Exception:
#     pass`/`return []` — an exception on EITHER (attack B: guard install
#     poisoned via `document.addEventListener`; attack F: the census
#     function itself poisoned via `Element.prototype.getAttribute`)
#     resolved to "proceed as if nothing were wrong", i.e. FAIL OPEN — a
#     direct violation of this repo's own NON-NEGOTIABLE-CONSTRAINTS (no
#     masked errors producing false-positive success). Both now FAIL CLOSED:
#     an exception raises ManualStepRequired rather than being swallowed —
#     the invariant this makes hold: the ONLY way a submission ever
#     completes is a census that ran to completion AND reported zero
#     uncommitted required fields; any inability to run it refuses. This
#     also converts attack C2 (a closed shadow root with zero external
#     light-DOM signal) from a silent submit into a safe refusal —
#     :data:`_CLOSED_SHADOW_MARKER_INIT_JS` gives the otherwise-genuinely-
#     invisible closed shadow root an honest, page-JS-independent signal of
#     its own EXISTENCE (never its content, which stays genuinely
#     unreadable — a real browser-platform limit) for the pre-existing
#     :func:`_unclassifiable_controls` backstop to flag.
# (2) attack A — a structural ceiling, not a correctness defect: a required
#     control created strictly INSIDE the form's own TARGET-phase `onsubmit`
#     handler is invisible to a CAPTURE-phase-only guard by DOM event-
#     ordering spec (capture always completes before the event ever reaches
#     the target). A BUBBLE-phase 'submit' listener — which fires AFTER the
#     target's own handler has run — narrows this: a field the handler
#     reveals and LEAVES IN THE DOM is now caught. What it cannot close: a
#     handler that reveals the field and, in that SAME synchronous
#     execution, either fires an outbound request (`fetch()`/XHR — a
#     completely ordinary way modern SPA-style ATS forms implement "submit")
#     or removes the field from the DOM again before returning — by the time
#     ANY listener on an ancestor node gets to run, that JS has already
#     executed and, in the fetch/XHR case, may have already reached the
#     employer. This is honestly recorded as an irreducible residual (a
#     pinned regression test asserting the limit precisely), never claimed
#     closed — no client-side event-listener ordering can guarantee seeing,
#     or undoing, a same-handler side effect that completes before control
#     ever returns to the browser's own event-dispatch machinery.
# ---------------------------------------------------------------------------

# Walks `document` plus every OPEN shadow root reachable from it, recursively,
# and defines `window.__aetherComposedCensus()` (idempotent: a no-op if
# already installed on THIS document — a navigation/reload replaces the
# document, and with it this installation, so every caller re-runs this
# rather than assuming a prior install still holds). Calling the installed
# function returns one descriptor per REQUIRED control the composed tree
# currently holds (native form control, a recognized interactive ARIA role
# with no native control nested inside, or a bare `[contenteditable]` box),
# each carrying its live-read `committed` state and a STABLE identifying
# `marker` — persisted as a `data-aether-live-field` attribute directly on
# the control itself, so the SAME control maps to the SAME marker (and
# therefore the same Playwright locator) across every call for as long as
# the document lives, exactly like a normal field's own name would.
_COMPOSED_CENSUS_SETUP_JS = r"""
() => {
  if (window.__aetherComposedCensus) { return true; }
  const EXCLUDED_TYPES = { hidden: 1, submit: 1, button: 1, reset: 1, image: 1, search: 1 };
  const ROLES = {
    combobox: 1, radio: 1, checkbox: 1, listbox: 1, switch: 1, textbox: 1,
    spinbutton: 1, slider: 1, menuitemradio: 1, menuitemcheckbox: 1,
  };
  function walk(root, out) {
    let all;
    try { all = root.querySelectorAll('*'); } catch (e) { return; }
    for (let i = 0; i < all.length; i++) {
      const el = all[i];
      out.push(el);
      if (el.shadowRoot) { walk(el.shadowRoot, out); }
    }
  }
  function kindFor(el) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'textarea') { return 'textarea'; }
    if (tag === 'select') { return 'select'; }
    const t = (el.getAttribute('type') || 'text').toLowerCase();
    if (t === 'radio' || t === 'checkbox' || t === 'file' || t === 'email' ||
        t === 'tel' || t === 'number' || t === 'url' || t === 'date') { return t; }
    return 'text';
  }
  function isRequired(el, tag) {
    if ((tag === 'input' || tag === 'select' || tag === 'textarea') && el.required) { return true; }
    return (el.getAttribute('aria-required') || '').toLowerCase() === 'true';
  }
  function nativeCommitted(el, kind) {
    if (kind === 'checkbox' || kind === 'radio') { return !!el.checked; }
    if (kind === 'file') { return !!(el.files && el.files.length); }
    return !!(el.value && el.value.trim());
  }
  function fieldPathFor(el) {
    try {
      const w = el.closest ? el.closest('[data-field-path]') : null;
      return w ? (w.getAttribute('data-field-path') || '') : '';
    } catch (e) { return ''; }
  }
  function labelFor(el) {
    const aria = el.getAttribute('aria-label');
    if (aria && aria.trim()) { return aria.trim(); }
    const id = el.id;
    if (id) {
      try {
        const root = el.getRootNode();
        const esc = (window.CSS && CSS.escape) ? CSS.escape(id) : id;
        const lab = root.querySelector ? root.querySelector('label[for="' + esc + '"]') : null;
        if (lab && lab.textContent && lab.textContent.trim()) { return lab.textContent.trim(); }
      } catch (e) {}
    }
    try {
      const root2 = el.getRootNode();
      if (root2 && root2.querySelectorAll) {
        const labels = root2.querySelectorAll('label');
        if (labels.length === 1 && labels[0].textContent && labels[0].textContent.trim()) {
          return labels[0].textContent.trim();
        }
      }
    } catch (e) {}
    const ph = el.getAttribute('placeholder');
    if (ph && ph.trim()) { return ph.trim(); }
    const txt = (el.textContent || '').trim();
    if (txt) { return txt.slice(0, 120); }
    return '';
  }
  window.__aetherComposedCensus = function () {
    const nodes = [];
    walk(document, nodes);
    const results = [];
    for (let i = 0; i < nodes.length; i++) {
      const el = nodes[i];
      const tag = el.tagName.toLowerCase();
      let kind = null;
      let isRole = false;
      let isCE = false;
      if (tag === 'input' || tag === 'select' || tag === 'textarea') {
        const type = (el.getAttribute('type') || 'text').toLowerCase();
        if (EXCLUDED_TYPES[type]) { continue; }
        if ((el.getAttribute('aria-hidden') || '').toLowerCase() === 'true') { continue; }
        const nameAttr = el.getAttribute('name') || '';
        const idAttr = el.id || '';
        if (nameAttr === 'g-recaptcha-response' || idAttr.indexOf('iti-') === 0) { continue; }
        kind = kindFor(el);
      } else {
        const role = (el.getAttribute('role') || '').toLowerCase();
        const ce = el.getAttribute('contenteditable');
        if (role && ROLES[role]) {
          if (el.querySelector && el.querySelector('input, select, textarea')) { continue; }
          isRole = true; kind = 'role:' + role;
        } else if (ce !== null && ce.toLowerCase() !== 'false') {
          if (el.querySelector && el.querySelector('input, select, textarea')) { continue; }
          isCE = true; kind = 'contenteditable';
        } else { continue; }
      }
      if (!isRequired(el, tag)) { continue; }
      let committed;
      if (isRole) {
        const ac = (el.getAttribute('aria-checked') || '').toLowerCase();
        const asel = (el.getAttribute('aria-selected') || '').toLowerCase();
        const ap = (el.getAttribute('aria-pressed') || '').toLowerCase();
        committed = ac === 'true' || asel === 'true' || ap === 'true';
      } else if (isCE) {
        committed = !!((el.textContent || '').trim());
      } else {
        committed = nativeCommitted(el, kind);
      }
      let marker = el.getAttribute('data-aether-live-field');
      if (!marker) {
        window.__aetherCensusSeq = (window.__aetherCensusSeq || 0) + 1;
        marker = 'c' + window.__aetherCensusSeq;
        el.setAttribute('data-aether-live-field', marker);
      }
      results.push({
        marker: marker,
        kind: kind,
        label: labelFor(el),
        required: true,
        committed: committed,
        inShadow: el.getRootNode() !== document,
        id: el.id || '',
        controlName: el.getAttribute('name') || '',
        fieldPath: fieldPathFor(el),
      });
    }
    return results;
  };
  return true;
}
"""

_COMPOSED_CENSUS_CALL_JS = "() => window.__aetherComposedCensus()"

# Idempotent (per document): ensures the composed census is installed, then
# installs a CAPTURE-PHASE 'submit' listener, a BUBBLE-PHASE 'submit'
# listener (CLI-SUB-005-R7 — see the module note above), and a capture-phase
# 'click' listener scoped to submit-shaped controls (the same selector shapes
# :func:`_activate_submit` targets). Capture phase at `document` runs BEFORE
# the event reaches the form/button at all — before any page-authored
# handler, before the browser's own default action (the actual form
# submission) — so a `preventDefault`+`stopImmediatePropagation` here reliably
# stops the submission from ever happening, regardless of what the page's own
# JS does at, or after, that point. The bubble-phase listener on the SAME
# event runs AFTER the target's own handler has already executed — see
# `guard`'s own re-use below — the two together are what root-cause 2's
# module note calls "guarding the submission event itself", now at BOTH ends
# of the target phase rather than only before it.
#
# CLI-SUB-005-R7 (adversarial FAIL, RUN-20260818T0223Z/SUB-005-R6/08-
# adversarial-final.md, attack F): `guard`'s own `catch (e) { return; }`
# around `window.__aetherComposedCensus()` was the SAME fail-open shape as
# the Python-side wrappers, one layer deeper — a page that makes the census
# function itself throw defeated the click-time re-check silently, in-
# browser, even though Python's own `_composed_live_census` (used only
# during pre-click convergence) independently closes the SAME poison earlier
# in the flow. FAIL CLOSED here too, for defense in depth against a poison
# that activates only at click/submit time rather than during convergence:
# an exception from the census IS treated as an uncommitted required field
# (a synthetic `census_unavailable` entry), never as "nothing to report".
_SUBMIT_GUARD_INSTALL_JS = (
    "() => {\n"
    "  (" + _COMPOSED_CENSUS_SETUP_JS.strip() + ")();\n"
    "  if (window.__aetherSubmitGuardInstalled) { return true; }\n"
    "  window.__aetherSubmitGuardInstalled = true;\n"
    "  function isSubmitControl(el) {\n"
    "    if (!el || !el.closest) { return false; }\n"
    "    if (el.closest('button[type=\"submit\"], input[type=\"submit\"]')) { return true; }\n"
    "    const btn = el.closest('button');\n"
    "    if (btn && /submit/i.test(btn.textContent || '')) { return true; }\n"
    "    return false;\n"
    "  }\n"
    "  function guard(event) {\n"
    "    let census = null;\n"
    "    let censusFailed = false;\n"
    "    try { census = window.__aetherComposedCensus(); }\n"
    "    catch (e) { censusFailed = true; }\n"
    "    const bad = censusFailed\n"
    "      ? [{ required: true, committed: false, kind: 'census_unavailable',\n"
    "           label: 'this page could not be verified at the instant of submitting' }]\n"
    "      : (census || []).filter(function (c) { return c.required && !c.committed; });\n"
    "    if (bad.length) {\n"
    "      window.__aetherBlockedSubmit = bad;\n"
    "      event.preventDefault();\n"
    "      event.stopImmediatePropagation();\n"
    "    }\n"
    "  }\n"
    "  document.addEventListener('submit', guard, true);\n"
    "  document.addEventListener('submit', guard, false);\n"
    "  document.addEventListener('click', function (event) {\n"
    "    if (!isSubmitControl(event.target)) { return; }\n"
    "    guard(event);\n"
    "  }, true);\n"
    "  return true;\n"
    "}\n"
)

_READ_BLOCKED_SUBMIT_JS = "() => window.__aetherBlockedSubmit || null"

# CLI-SUB-005-R7 (attack C2) — a CLOSED shadow root's CONTENT is unreadable
# by any web API, by design: `element.shadowRoot` returns `null` for every
# external accessor, including this codebase's own composed census, for a
# host that carries no OTHER external signal (no role/aria-required/
# contenteditable) — a genuine browser-platform limit, not a gap left open
# by choice. Its EXISTENCE, however, is detectable, cheaply and honestly, by
# intercepting the one call that ever creates one:
# `Element.prototype.attachShadow`. Installed via Playwright's
# `page.add_init_script` — the one hook that runs BEFORE any script on a
# newly created document, including the page's own `customElements.define
# (...)` — so this is armed before ANY custom element's `connectedCallback`
# (where a shadow root is normally attached) ever runs, for the top document
# and every child frame alike (`add_init_script` applies to both). The
# marker it writes lives on the HOST element, in the LIGHT DOM — never
# inside the closed root itself — so it is fully visible to
# ``page.content()``'s ordinary string serialization; :func:`
# _unclassifiable_controls` flags it exactly like any other unclassifiable
# control, and the pre-existing :func:`_verify_no_unverifiable_form_surface`
# backstop refuses rather than guesses. An OPEN shadow root (``mode`` is
# always checked, never assumed) is left completely untouched — this must
# never regress attack #6/E's own open-shadow resolution.
_CLOSED_SHADOW_MARKER_INIT_JS = r"""
(() => {
  if (!window.Element || !Element.prototype.attachShadow) { return; }
  const original = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (init) {
    const root = original.call(this, init);
    try {
      if (!init || init.mode !== 'open') {
        this.setAttribute('data-aether-closed-shadow-host', 'true');
      }
    } catch (e) {
      // Marking failed -- the shadow root itself is returned either way;
      // only OUR OWN bookkeeping attribute is at risk here, never the
      // page's own behaviour.
    }
    return root;
  };
})();
"""


def _composed_live_census(root: Any) -> list[dict[str, Any]]:
    """Every REQUIRED control the LIVE composed DOM tree of ``root`` (the top
    document, or one Playwright frame) holds RIGHT NOW — light DOM plus every
    open shadow root, walked recursively — with its committed state read at
    THIS instant. See :data:`_COMPOSED_CENSUS_SETUP_JS`.

    CLI-SUB-005-R7 (adversarial FAIL,
    RUN-20260818T0223Z/SUB-005-R6/08-adversarial-final.md, attack F): the
    previous revision of this function caught ANY exception from either
    ``evaluate()`` call — including ``window.__aetherComposedCensus()``
    itself throwing, not merely an unreadable root — and returned ``[]``,
    which :func:`_uncommitted_live_required_fields` and the in-page
    click-time guard both then treated as "nothing required is uncommitted
    here". A page that makes the census function itself throw (attack F:
    ``Element.prototype.getAttribute`` poisoned for the census's own marker
    attribute) silently reverted an otherwise-closed shadow-DOM field to
    fully invisible, at both the point it feeds convergence AND the point
    the click-time guard re-checks it — the exact fail-OPEN shape
    05-decision-memos/SUB-005-and-COV-3-rulings.md's R7 ruling names: "an
    exception ... resolves to 'proceed as if nothing were wrong,' not
    'refuse'". FAIL CLOSED now: an exception from a root that CAN run JS at
    all raises :class:`ManualStepRequired` — never a silent zero-results
    return — so the ONLY way a submission ever completes is a census that
    ran to completion and reported nothing required-and-uncommitted.

    The ONE exception this still does not raise on is a root with no
    ``evaluate`` at all (``hasattr`` false, checked BEFORE any call, never
    from a caught exception) — this repo's own unit-test fakes predate
    frame/JS-eval support entirely, a fact about the Python object Aether
    itself constructed, not something page-authored JS running inside a real
    browser could ever influence or poison. There is nothing beyond what the
    existing parser-based census already covers for such a root to add.
    """
    if not hasattr(root, "evaluate"):
        return []
    try:
        root.evaluate(_COMPOSED_CENSUS_SETUP_JS)
        result = root.evaluate(_COMPOSED_CENSUS_CALL_JS)
    except Exception as exc:  # CLI-SUB-005-R7 — FAIL CLOSED (was: return [])
        raise ManualStepRequired(
            "census_unavailable",
            (
                "Aether could not verify this application's fields — its "
                "own in-page check failed to run — so nothing was "
                "submitted. Open the posting and finish it yourself."
            ),
        ) from exc
    return list(result or [])


def _live_census_kind(raw_kind: str) -> str:
    """Map a composed-census control's raw JS-reported kind onto the exact
    vocabulary :func:`_kind_for` already produces, so :func:`_fill_value` /
    :func:`_commit_state`'s existing kind dispatch handles a live-census
    field exactly like any other. A custom ARIA role (other than
    ``combobox``, which behaves enough like the existing typeahead widgets to
    reuse that branch) or a bare ``[contenteditable]`` box has no reliable
    native fill mechanism this codebase automates — falls through to the
    generic text-fill attempt, which either lands (Playwright's own
    ``fill()`` supports ``[contenteditable]`` directly) or fails cleanly and
    is reported unfilled, never faked as committed.
    """
    if raw_kind == "role:combobox":
        return "combobox"
    if raw_kind.startswith("role:") or raw_kind == "contenteditable":
        return "text"
    return raw_kind or "text"


def _install_submission_guard(root: Any) -> None:
    """CLI-SUB-005-R6 root cause 2 — see the module note above. Installs the
    capture-phase AND bubble-phase submission guard on ``root`` (idempotent).
    The ONLY DOM mutation this performs is adding event listeners (plus, if
    the guard ever fires, an inert ``data-aether-live-field`` marker
    attribute already added by the census itself during convergence) — it
    can never reveal, hide, or answer anything, so it does not violate the
    "no mutation between convergence's return and the submit click"
    invariant the call site documents; it is what CLOSES that invariant's
    remaining gap.

    CLI-SUB-005-R7 (adversarial FAIL,
    RUN-20260818T0223Z/SUB-005-R6/08-adversarial-final.md, attack B): the
    previous revision caught ANY exception from ``root.evaluate(...)`` and
    silently passed — the comment's own justification ("an unreadable root
    cannot submit anything either") is true for a genuinely DEAD page but
    false for a LIVE one whose ``document.addEventListener`` has specifically
    been shadowed (attack B): the page stays fully alive, fully clickable,
    fully able to submit — only Aether's OWN instrumentation call failed,
    leaving the click completely unguarded. FAIL CLOSED now: an exception
    from a root that CAN run JS at all raises :class:`ManualStepRequired`
    rather than letting an unguarded click through.

    Same ``hasattr`` carve-out as :func:`_composed_live_census`, for the
    identical reason: a root with no ``evaluate`` at all is a fact about the
    Python object itself, never something page-authored JS could influence.
    """
    if not hasattr(root, "evaluate"):
        return
    try:
        root.evaluate(_SUBMIT_GUARD_INSTALL_JS)
    except Exception as exc:  # CLI-SUB-005-R7 — FAIL CLOSED (was: pass)
        raise ManualStepRequired(
            "guard_install_failed",
            (
                "Aether could not arm its own submission safety check on "
                "this page, so nothing was submitted. Open the posting and "
                "finish it yourself."
            ),
        ) from exc


def _read_blocked_submission(root: Any) -> list[dict[str, Any]] | None:
    """Whatever :data:`_SUBMIT_GUARD_INSTALL_JS` blocked on ``root``'s most
    recent submit attempt, or ``None`` if nothing was blocked.

    CLI-SUB-005-R7 — deliberately NOT converted to fail-closed like
    :func:`_composed_live_census`/:func:`_install_submission_guard`: this
    runs strictly AFTER :func:`_activate_submit`'s click, when a genuinely
    SUCCESSFUL native submission may have already navigated the page,
    destroying this exact JS execution context — an entirely ordinary,
    expected outcome for a well-behaved form, not a hostile-page signal, and
    raising here would turn every such legitimate success into a false
    refusal. Safety does not depend on this call succeeding: if the guard
    truly blocked the submission, its `preventDefault()` means the page
    never navigated, so this read reliably succeeds; and independent of
    this function entirely, :func:`_confirmation_signal` downstream still
    demands PROOF (a real confirmation or a real navigation) before
    ``submitted`` is ever reported true — a call that fails here can widen
    who gets asked to double-check, never who gets a silent success.
    """
    try:
        result = root.evaluate(_READ_BLOCKED_SUBMIT_JS)
    except Exception:  # noqa: BLE001 — see docstring: a post-click read, not a verification boundary
        return None
    return list(result) if result else None


def _uncommitted_live_required_fields(
    page: Any,
    channel: str,
    plan_fields: list[dict[str, Any]],
    documents: dict[str, str],
) -> list[dict[str, Any]]:
    """Every field the channel's OWN schema parser (:func:`parse_form_schema`)
    can recognize as required, right now, in ``page``'s content (the top
    document, or — since CLI-SUB-005-R5 — a single frame's content, passed
    here as ``page``) that is not, right now, committed. A TOTAL
    re-derivation over what THAT parser call can see, never a delta against
    a ledger of names or flags seen on some earlier pass.

    CLI-SUB-005-R5 (adversarial FAIL,
    RUN-20260818T0223Z/SUB-005-R4/08-adversarial-final.md): the previous
    revision of this docstring called this "the COMPLETE set of fields the
    LIVE DOM marks required" and "a fact only the LIVE DOM holds" — language
    this review proved false as written. :func:`parse_form_schema` runs over
    ``page.content()``, one document's serialized HTML; it does not descend
    into ``<iframe>`` documents, so a required field that exists only inside
    one was invisible here no matter how many times this re-parsed. This
    function does NOT close that gap by itself, and no longer claims to:
    :func:`_converge_presubmit_state` now calls it once per reachable
    Playwright frame as well as the top document (closing the iframe
    instance of the class), and :func:`_verify_no_unverifiable_form_surface`
    is the CONSERVATIVE BACKSTOP that makes the overall submit-safety
    property hold independent of parser vocabulary — any form-shaped control
    on any reachable surface that no parser call anywhere in this path can
    classify, or any frame whose content cannot even be read, refuses
    instead of submitting. What THIS function alone guarantees is exact and
    narrower: every field ITS OWN parser call recognizes as required, on the
    one root it was given, is proven committed or reported uncommitted —
    never silently skipped by a stale ledger.

    CLI-SUB-005-R4 (adversarial re-review FAIL,
    RUN-20260818T0223Z/SUB-005-R3/08-adversarial-rereview.md, finding #1):
    R3's two convergence signals were both DELTAS against state captured at
    plan-build time or on an earlier pass — a required field's NAME being new
    to a ``known_names`` set, or a PLANNED field's own frozen ``required``
    flag going uncommitted. Neither one re-checks whether a field that was
    already known — present, but OPTIONAL, in the original snapshot — has
    since turned required live in the DOM (a sibling ``<select>``'s
    ``onchange`` marking an already-rendered, already-planned-but-optional
    node ``aria-required="true"``: no new node, same name, exactly how a
    React-driven ATS conditional would toggle an existing field's
    requiredness). Reproduced
    (``adversarial/attack2_required_toggle_escapes_ledger.py``):
    ``_converge_presubmit_state`` converged on pass 1 because the toggled
    field's name was already ``known`` and its PLAN entry still said
    ``required=False, value=None`` — both delta signals are blind to a fact
    only the LIVE DOM holds, and there was never anything to update them.

    This function never asks "is this name new?" or "does the plan's OWN
    stale copy say uncommitted?" as its ONLY test for requiredness. It
    re-parses ``page.content()`` with the channel's own
    :func:`parse_form_schema` FRESH on every single call, and treats a field
    as required-right-now if EITHER source says so:

    * the FRESH live parse marks it required (catches a toggle-to-required
      the plan's frozen copy cannot see — the fix for finding #1), OR
    * the PLAN's own ``required`` flag says so (preserves the pre-existing
      invariant that a plan's own requiredness decision is always honoured
      even if a re-render happens to strip the ``required``/``aria-required``
      markup along with the value it wiped — a plan is never LESS trusted
      than the live markup, only ever supplemented by it).

    Every such field is then checked against the live DOM's actual committed
    state via :func:`_commit_state`. A field's name being ``known`` from an
    earlier pass, or its plan entry's own stale ``required`` flag being the
    ONLY thing consulted, is never how requiredness is decided here — there
    is no ledger for a live requiredness toggle to escape, by construction.

    A field with no planned value yet (truly new to the plan, OR
    known-but-was-optional-and-just-turned-required — the two are
    indistinguishable from here, and both need the identical treatment:
    resolve via a real answer, or refuse) is always reported uncommitted. A
    field that already has a planned value is reported uncommitted only if
    the live DOM does not currently hold that value (a re-render wipe).
    """
    try:
        html = page.content()
    except Exception:  # noqa: BLE001 — a page without a live DOM has nothing to check
        html = None
    live_fields: list[dict[str, Any]] = []
    if html is not None:
        try:
            live_fields = parse_form_schema(html, channel=channel)
        except Exception:  # noqa: BLE001 — a parse failure must not crash the gate
            live_fields = []

    # CLI-SUB-005-R6 root cause 1 (see the module note above
    # _uncommitted_live_required_fields' neighbourhood): `parse_form_schema`
    # above can only ever see what `page.content()`'s STRING serialized —
    # never an open shadow root's content, which is structurally absent from
    # that string, not merely unparsed. Supplement (never replace) the
    # parser-derived `live_fields` with the LIVE, shadow-DOM-piercing
    # composed census — but only for a control the parser could NOT already
    # classify (matched by its own id/name/`[data-field-path]` ancestor
    # against every name the parser DID recognize): a field the parser
    # already covers is already handled, correctly, by the two loops below,
    # and must not be double-processed under a second, synthetic name.
    known_field_names = {str(f["name"]) for f in live_fields}
    for item in _composed_live_census(page):
        if item.get("committed"):
            continue  # already satisfied — not this census's job to report
        control_id = str(item.get("id") or "")
        control_name = str(item.get("controlName") or "")
        field_path = str(item.get("fieldPath") or "")
        if (
            (control_id and control_id in known_field_names)
            or (control_name and control_name in known_field_names)
            or (field_path and field_path in known_field_names)
        ):
            continue
        marker = str(item.get("marker") or "")
        if not marker:
            continue
        synthetic_name = f"__aether_live_census_{marker}"
        if synthetic_name in known_field_names:
            continue
        known_field_names.add(synthetic_name)
        live_fields.append(
            {
                "name": synthetic_name,
                "label": str(item.get("label") or "an embedded control"),
                "kind": _live_census_kind(str(item.get("kind") or "")),
                "required": True,
                "options": [],
                "scope": "",
                # A direct, shadow-DOM-piercing locator (Playwright's CSS
                # engine pierces open shadow roots by default) — never
                # assembled from an id/name this control may not have.
                "liveSelector": f'[data-aether-live-field="{marker}"]',
            }
        )

    live_required_names = {str(f["name"]) for f in live_fields if f.get("required")}

    seen: set[str] = set()
    uncommitted: list[dict[str, Any]] = []

    # Every PLANNED field required either by the plan's own flag or by the
    # fresh live parse — this is what catches a known-but-optional field
    # turning required live (name already in the plan, plan's own flag still
    # False, but now present in live_required_names) without ever trusting
    # the plan's frozen flag as the SOLE signal.
    for field in plan_fields:
        name = str(field["name"])
        if name in seen or not (field.get("required") or name in live_required_names):
            continue
        seen.add(name)
        value = field.get("value")
        if value is None:
            uncommitted.append(field)
            continue
        committed, _observed = _commit_state(page, field, value, documents)
        if not committed:
            uncommitted.append(field)

    # Every field the LIVE DOM marks required RIGHT NOW that the plan never
    # saw at all — structurally new, not merely toggled (the loop above
    # already covers a plan-known name via live_required_names).
    for live_field in live_fields:
        name = str(live_field["name"])
        if name in seen or not live_field.get("required"):
            continue
        seen.add(name)
        uncommitted.append(live_field)

    return uncommitted


def _resolve_uncommitted_live_required_once(
    page: Any,
    plan_fields: list[dict[str, Any]],
    documents: dict[str, str],
    uncommitted: list[dict[str, Any]],
    *,
    profile: dict[str, Any] | None,
    answer_bank: Callable[[dict[str, Any]], Any] | None,
) -> list[str]:
    """Resolve every field ONE fresh :func:`_uncommitted_live_required_fields`
    snapshot just reported. The caller's fixed-point loop controls the bound
    and re-derives a brand-new, total snapshot on the NEXT pass rather than
    trusting anything decided here — this function never marks a name as
    "handled" for future passes to skip.

    Two cases, handled differently on purpose:

    * A field that ALREADY has a planned value (a committed answer the live
      DOM no longer shows — a re-render wipe) is simply REFILLED with that
      SAME answer, and is never counted into the return value: it was
      already planned and already accounted for in the caller's ``filled``.
      A refill that does not stick this pass is left for the NEXT pass's
      fresh, total re-derivation to see and retry — never an immediate
      refusal here, exactly like the pre-existing gate's own wipe-refill
      behaviour.
    * A field with NO planned value (truly new, or known-but-was-optional-
      and-just-turned-required-live) is resolved via the EXACT SAME
      ``_answer_for``/answer-bank path :func:`build_form_fill_plan` itself
      uses, never inventing an answer — an existing plan entry gets its
      ``value``/``required`` updated in place; a genuinely new one is
      appended. Anything that cannot be answered AND verified raises
      ``ManualStepRequired("unplanned_required_field")`` immediately: this
      NEVER submits past a live-required field with no honest answer.
      Successfully resolved names ARE returned, for the caller's
      ``unplannedFilled`` evidence — this is exactly the class of field that
      needed this safety net at all, whether it was structurally invisible
      to the original snapshot or merely optional in it at the time.
    """
    plan_by_name = {str(field["name"]): field for field in plan_fields}
    resolved: list[str] = []
    unresolved_labels: list[str] = []
    for field in uncommitted:
        name = str(field["name"])
        existing = plan_by_name.get(name)
        value = existing.get("value") if existing else None
        if existing is not None and value is not None:
            _fill_and_verify(page, existing, value, documents, verify=True)
            continue
        answer = _answer_for(field, profile or {})
        if answer is None and answer_bank is not None:
            match = answer_bank(field)
            if match is not None:
                answer = match.answer
        if answer is None:
            unresolved_labels.append(str(field.get("label") or name))
            continue
        if existing is not None:
            existing["value"] = answer
            existing["required"] = True
            target = existing
        else:
            target = dict(field)
            target["value"] = answer
            target["required"] = True
            plan_fields.append(target)
            plan_by_name[name] = target
        if _fill_and_verify(page, target, answer, documents, verify=True):
            resolved.append(name)
        else:
            unresolved_labels.append(str(target.get("label") or name))
    if unresolved_labels:
        labels = "; ".join(unresolved_labels)
        raise ManualStepRequired(
            "unplanned_required_field",
            (
                "This application revealed a required question after "
                "Aether had already built its plan (a conditional "
                "follow-up), and it could not be answered and verified, "
                "so nothing was submitted. Open the posting and finish "
                "it yourself: " + labels
            ),
            question=labels,
        )
    return resolved


def _plan_entry_for(
    name: str, *sources: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """The first known plan entry for ``name`` across one or more plans — the
    top document's and, since CLI-SUB-005-R5, each frame's own — checked in
    the order given, never merged: the same ``name`` string appearing in two
    genuinely different documents is a coincidence, not the same field."""
    for source in sources:
        entry = source.get(name)
        if entry is not None:
            return entry
    return None


def _converge_presubmit_state(
    page: Any,
    channel: str,
    plan_fields: list[dict[str, Any]],
    documents: dict[str, str],
    *,
    profile: dict[str, Any] | None,
    answer_bank: Callable[[dict[str, Any]], Any] | None,
) -> list[str]:
    """Fixed point over a TOTAL re-derivation of live-required-field state,
    across the top document AND every reachable Playwright frame — the ONLY
    thing between the last fill and the submit click, and the last thing it
    ever does is that SAME re-derivation, read-only, with zero mutation
    after it.

    CLI-SUB-005-R4 (adversarial re-review FAIL,
    RUN-20260818T0223Z/SUB-005-R3/08-adversarial-rereview.md): R3 folded a
    live-DOM rescan and a stale-planned-field refill into one bounded loop,
    but its "has anything changed?" ledger tracked two DELTAS — a required
    field's NAME being new to a ``known_names`` set, and a PLANNED field's
    OWN frozen ``required`` flag going uncommitted — neither of which can see
    an already-known, already-OPTIONAL field turning required LIVE via a
    mutation the loop's own actions triggered (finding #1: a sibling
    ``<select>``'s ``onchange`` marking an already-rendered, already-known,
    already-optional node ``aria-required="true"``; no new node, no changed
    plan flag, invisible to both deltas by construction). Separately,
    counting the confirming "nothing changed" pass INSIDE the same bounded
    counter as the resolving passes left a chain needing exactly
    ``_MAX_CONVERGENCE_PASSES`` resolving passes with no budget left for the
    pass that proves it is done — the R2 off-by-one, reproduced one bound
    deeper instead of eliminated (finding #2).

    R4 replaces both DELTA signals with ONE total enumeration
    (:func:`_uncommitted_live_required_fields`): every pass, re-parse the
    live DOM from scratch with the channel's own schema parser, and check
    EVERY field it reports required RIGHT NOW against the live DOM's actual
    committed state — never a name-ledger, never a plan's own stale copy of
    its ``required`` flag. There is no ledger here for a live requiredness
    toggle to escape, by construction: what matters is only ever what the DOM
    says THIS INSTANT.

    The loop and the "did it converge?" check are the SAME re-derivation, run
    at the TOP of every pass, which is what decouples "prove it's done" from
    "resolve one more thing" and eliminates the off-by-one structurally
    rather than by picking a bigger number:

    * If this pass's total re-derivation reports nothing live-required and
      uncommitted, the loop stops immediately — this IS the read-only,
      zero-mutation confirming pass, and it is NEVER counted against the
      resolving-pass bound, because it did not resolve anything. A chain
      that finishes after exactly ``_MAX_CONVERGENCE_PASSES`` resolving
      passes still gets this free, uncounted check on the very next
      iteration — a legitimately-terminating chain of any depth up to the
      bound is always given the pass that proves it is finished, because
      that pass is never the thing being bounded.
    * Otherwise a resolving pass runs
      (:func:`_resolve_uncommitted_live_required_once` — refills a wiped
      planned value, or answers and fills a never-answered one via the exact
      ``_answer_for``/answer-bank path, raising immediately if anything
      discovered cannot be answered AND verified) and the resolving-pass
      counter increments. Only genuine resolving work counts toward
      :data:`_MAX_CONVERGENCE_PASSES` — an application whose form keeps
      changing under it, or keeps losing typed answers, faster than that
      many resolving passes can keep up is exactly the case a manual step
      exists for.

    CLI-SUB-005-R5 (adversarial FAIL,
    RUN-20260818T0223Z/SUB-005-R4/08-adversarial-final.md): R4's "TOTAL
    re-derivation" was total only over the TOP-LEVEL document —
    :func:`parse_form_schema` runs on ``page.content()``, which does not
    descend into ``<iframe>`` documents, so a required field revealed only
    inside an iframe was invisible on every pass, forever. This function now
    re-derives EACH :func:`_reachable_frames` frame's own uncommitted-required
    state (re-read fresh every pass, exactly like the top document) the
    IDENTICAL way it re-derives the top document's — against a SEPARATE,
    per-frame plan (a frame was never part of the original static snapshot,
    so every field it reveals starts unplanned there, just like an unplanned
    top-document field does), resolved or refused through the exact same
    :func:`_resolve_uncommitted_live_required_once` path. Convergence is now
    "the top document AND every reachable frame each report nothing
    uncommitted" — a resolving pass anywhere (top or any frame) still counts
    once against the SAME bound, and the free confirming pass is still the
    one where NOTHING anywhere changed.

    This still is not an ABSOLUTE claim: a frame whose content cannot be
    read at all, or a control no parser call anywhere in this path can
    recognize, is exactly what :func:`_verify_no_unverifiable_form_surface`
    exists to catch as a LAST, CONSERVATIVE gate right before the submit
    click — this function's own guarantee stays scoped to what its parser
    calls can see, on every surface it can enumerate.

    Returns the names of every field resolved (top document or any frame)
    because it had NO planned value yet (truly new to the plan, or
    known-but-turned-required-live) — never a field that was only refilled
    after a wipe, which was already planned and already accounted for in the
    caller's ``filled``.
    """
    resolving_passes = 0
    resolved: list[str] = []
    frame_plan_fields: dict[int, list[dict[str, Any]]] = {}
    while True:
        _wait(page, _PRESUBMIT_SETTLE_MS)
        # TOTAL, read-only re-derivation — see _uncommitted_live_required_fields.
        # An empty result here is, itself, the zero-mutation confirming pass:
        # nothing below this branch runs, and the function returns.
        uncommitted = _uncommitted_live_required_fields(
            page, channel, plan_fields, documents
        )
        # CLI-SUB-005-R5: the SAME re-derivation, once per reachable frame,
        # against that frame's OWN plan — never the top document's, since a
        # frame field was never in the original static snapshot.
        frame_batches: list[
            tuple[Any, list[dict[str, Any]], list[dict[str, Any]]]
        ] = []
        for frame in _reachable_frames(page):
            frame_fields = frame_plan_fields.setdefault(id(frame), [])
            frame_uncommitted = _uncommitted_live_required_fields(
                frame, channel, frame_fields, documents
            )
            if frame_uncommitted:
                frame_batches.append((frame, frame_fields, frame_uncommitted))

        if not uncommitted and not frame_batches:
            return resolved

        resolving_passes += 1
        if resolving_passes > _MAX_CONVERGENCE_PASSES:
            combined = list(uncommitted)
            for _frame, _frame_fields, batch in frame_batches:
                combined.extend(batch)
            plan_by_name = {str(field["name"]): field for field in plan_fields}
            frame_plan_by_name = {
                str(field["name"]): field
                for fields_for_frame in frame_plan_fields.values()
                for field in fields_for_frame
            }
            still_unanswered = [
                field
                for field in combined
                if (
                    entry := _plan_entry_for(
                        str(field["name"]), plan_by_name, frame_plan_by_name
                    )
                )
                is None
                or entry.get("value") is None
            ]
            if still_unanswered:
                raise ManualStepRequired(
                    "unplanned_required_field",
                    (
                        "This application kept revealing new required "
                        "questions — or kept turning already-visible fields "
                        "required — faster than Aether could keep resolving "
                        "them, so it stopped rather than guess how many "
                        "more passes it might take. Open the posting and "
                        "finish it yourself."
                    ),
                )
            labels = "; ".join(
                str(field.get("label") or field["name"]) for field in combined
            )
            raise ManualStepRequired(
                "form_fill_failed",
                (
                    "Aether typed the answers but this application form "
                    "kept losing them (the page re-rendered or rejected the "
                    "values) faster than it could keep refilling them, so "
                    "it submitted nothing. Open the posting and apply "
                    "yourself: " + labels
                ),
                question=labels,
            )

        if uncommitted:
            resolved.extend(
                _resolve_uncommitted_live_required_once(
                    page,
                    plan_fields,
                    documents,
                    uncommitted,
                    profile=profile,
                    answer_bank=answer_bank,
                )
            )
        for frame, frame_fields, batch in frame_batches:
            resolved.extend(
                _resolve_uncommitted_live_required_once(
                    frame,
                    frame_fields,
                    documents,
                    batch,
                    profile=profile,
                    answer_bank=answer_bank,
                )
            )


def _unclassifiable_controls(html: str, channel: str) -> list[str]:
    """Form-shaped controls in ``html`` that :func:`parse_form_schema`
    (``channel``'s own dialect) cannot turn into a field entry AT ALL — a
    raw structural DOM census, not a re-run of any one parser's rules, so it
    catches what NO current or future channel dialect happens to recognize: a
    control with neither an ``id`` nor a ``name`` and no
    ``[data-field-path]`` ancestor, a custom ARIA widget with no underlying
    native control, a ``contenteditable`` question box with none either.
    This is the structural counterpart to the iframe gap
    (RUN-20260818T0223Z/SUB-005-R4/08-adversarial-final.md): that review's
    own "other angles" section separately named a Greenhouse-shaped
    contenteditable widget with no wrapped ``<input>`` as the SAME root
    cause one level shallower ("parser vocabulary is the ceiling on what the
    safety net can ever see") — this closes that class too, not just the
    iframe instance of it.

    A control already accounted for by ``g-recaptcha-response``'s name, an
    ``iti-``-prefixed id (the international-phone-input library's own
    internal state field), or any of the input types every parser already
    treats as non-data-entry is excluded here for the identical reason the
    parsers exclude them: a hidden reCAPTCHA token or a widget's own
    bookkeeping is not a question a human applicant answers, and flagging it
    would not be conservative — it would be noise that trains someone to
    ignore this gate.
    """
    soup = _soup(html)
    try:
        schema = parse_form_schema(html, channel=channel)
    except Exception:  # noqa: BLE001 — an unparseable page IS the finding
        return ["the page's own schema could not be parsed"]
    covered = {str(field["name"]) for field in schema}

    def _covered(node: Any) -> bool:
        node_id = str(node.get("id") or "")
        node_name = str(node.get("name") or "")
        if node_id and node_id in covered:
            return True
        if node_name and node_name in covered:
            return True
        wrapper = node.find_parent(attrs={"data-field-path": True})
        if wrapper is not None and str(wrapper.get("data-field-path") or "") in covered:
            return True
        return False

    findings: list[str] = []
    flagged: set[int] = set()

    def _flag(node: Any, why: str) -> None:
        if id(node) in flagged:
            return
        flagged.add(id(node))
        findings.append(why)

    for control in soup.find_all(["input", "select", "textarea"]):
        control_type = str(control.get("type") or "").lower()
        if control_type in _CENSUS_EXCLUDED_INPUT_TYPES:
            continue
        if str(control.get("aria-hidden") or "").lower() == "true":
            continue
        control_id = str(control.get("id") or "")
        control_name = str(control.get("name") or "")
        if control_name == "g-recaptcha-response" or control_id.startswith("iti-"):
            continue
        if not _covered(control):
            _flag(control, f"unclassified <{control.name}> control")

    for node in soup.find_all(attrs={"role": True}):
        if node.name in {"input", "select", "textarea"}:
            continue
        role = str(node.get("role") or "").lower()
        if role not in _CENSUS_INTERACTIVE_ROLES:
            continue
        if node.find(["input", "select", "textarea"]) is not None:
            continue  # a native control inside it is censused on its own
        if not _covered(node):
            _flag(node, f'unclassified [role="{role}"] control')

    for node in soup.find_all(attrs={"contenteditable": True}):
        if str(node.get("contenteditable") or "").lower() == "false":
            continue
        if node.find(["input", "select", "textarea"]) is not None:
            continue
        if not _covered(node):
            _flag(node, "unclassified contenteditable control")

    # CLI-SUB-005-R7 (attack C2) — a host tagged by
    # :data:`_CLOSED_SHADOW_MARKER_INIT_JS` carries a CLOSED shadow root
    # whose content no code in this browser process (Aether's, Playwright's,
    # or the page's own) can ever read — flagged UNCONDITIONALLY, never
    # gated on `_covered`: even a host whose id/name happens to match an
    # already-recognized field cannot have that field's FILL verified either,
    # since verification itself would need to read the same unreadable
    # content. An open shadow root never carries this marker at all (see the
    # init script), so this can never fire for attack #6/E's own resolved
    # construction.
    for node in soup.find_all(attrs={"data-aether-closed-shadow-host": True}):
        _flag(
            node,
            "a closed shadow root whose content cannot be inspected",
        )

    return findings


def _verify_no_unverifiable_form_surface(page: Any, channel: str) -> None:
    """CLI-SUB-005-R5 CONSERVATIVE REFUSE-BACKSTOP — the decisive invariant.

    Immediately before :func:`_activate_submit`: every reachable surface
    (the top document and every :func:`_reachable_frames` frame, re-read
    fresh here) must be READABLE, and everything on it that LOOKS like a
    control a human applicant could interact with must be something
    :func:`parse_form_schema` actually turned into a field — never assumed
    empty of meaning just because no parser call happened to recognize it.

    RUN-20260818T0223Z/SUB-005-R4/08-adversarial-final.md proved
    :func:`_uncommitted_live_required_fields` (top-document-only at the
    time) could never see a required field embedded in an iframe, no matter
    how many times it re-parsed — a residual
    ``05-decision-memos/SUB-005-and-COV-3-rulings.md`` accepted as bounded IN
    KIND ("the safety net can only see what parse_form_schema can see") and
    ordered closed two ways: (a) extend the re-derivation across frames
    (:func:`_converge_presubmit_state`, above) and (b) THIS function — a
    backstop that no longer depends on any parser recognizing a control AT
    ALL. Unknown ⇒ manual refusal. Never unknown ⇒ submit.

    This is not a claim that the census below is a total enumeration of
    every ATS convention that will ever exist — it cannot be, by the exact
    argument that produced it. It is a claim that nothing shaped like a
    control on any surface this function could read goes unaccounted for,
    and that a surface it could NOT read is refused rather than assumed
    clean.
    """
    unreadable: list[str] = []
    unclassifiable: list[str] = []
    try:
        html = page.content()
    except Exception:  # noqa: BLE001 — an unreadable top document IS the finding
        html = None
    if html is None:
        unreadable.append("the application page itself")
    else:
        unclassifiable.extend(_unclassifiable_controls(html, channel))
    for frame in _reachable_frames(page):
        try:
            frame_html = frame.content()
        except Exception:  # noqa: BLE001 — an unreadable frame IS the finding
            unreadable.append(_frame_label(frame))
            continue
        unclassifiable.extend(
            f"{_frame_label(frame)}: {finding}"
            for finding in _unclassifiable_controls(frame_html, channel)
        )
    if not unreadable and not unclassifiable:
        return
    details = "; ".join(unreadable + unclassifiable)
    raise ManualStepRequired(
        "unverifiable_form_surface",
        (
            "This application page has a part Aether could not fully read "
            "and account for before submitting — rather than guess whether "
            "it held a required question, it stopped and left the form "
            "untouched: " + details
        ),
        question=details,
    )


def _resume_suffix(data: bytes) -> str:
    """Name the uploaded résumé for what it ACTUALLY is (RFMT-5).

    Every outbound résumé is now the user's PRESERVED document, which is
    whatever they uploaded: a spliced PDF, a natively rewritten ``.docx``, or a
    ``.txt``. Until RFMT-5 the in-process render always came back as the Aether
    branded template — always a PDF — so this file could be named ``.pdf``
    unconditionally. It no longer can: handing an employer's portal a Word
    document called ``resume.pdf`` is a file they cannot open.

    Sniffed from the bytes themselves (the format's own magic number), never
    from a caller's label, so the name on disk cannot disagree with the content.
    Empty bytes — the "no résumé on this application" case, which the sweep
    already handles upstream — keep the historical ``.pdf`` name.
    """
    if data.startswith(b"%PDF-"):
        return ".pdf"
    if data.startswith(b"PK\x03\x04"):  # OOXML (.docx) is a ZIP package
        return ".docx"
    if data:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return ".pdf"
        return ".txt"
    return ".pdf"


def playwright_form_submitter(
    *,
    application_id: str,
    channel: str,
    page_html: str,
    apply_url: str | None,
    plan: dict[str, Any],
    resume_pdf_bytes: bytes,
    cover_letter_text: str,
    evidence_dir: str,
    profile: dict[str, Any] | None = None,
    answer_bank: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Fill and submit the application in a REAL headless Chromium.

    ``apply_url`` (production) navigates to the employer's live posting so the
    fill and the submit happen against their real form. Without one, the
    supplied ``page_html`` is loaded directly — the replay/offline mode used by
    tests and by re-running a captured page — and the returned summary says so
    in ``mode``, so an audit can always tell the two apart.

    ``profile``/``answer_bank`` (CLI-SUB-005-R2) are consulted ONLY to resolve
    a required field the live DOM reveals that the plan's static snapshot
    never saw — see :func:`_resolve_unplanned_required_fields`. Omitting them
    reproduces the pre-R2 behaviour for that (rare, additive) safety net: no
    stored answer means an honest refusal, exactly like every other unanswered
    required field.

    Returns ``{"submitted", "evidencePath", "destination", "filled",
    "unfilled", "unplannedFilled", "mode"}``. Raises
    :class:`ApplyExecutorTransportError` if the browser itself could not be
    driven — never a fake success.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ApplyExecutorTransportError(
            "browser_unavailable",
            "The application browser is not installed on this server — nothing was submitted.",
        ) from exc

    documents: dict[str, str] = {}
    temp_dir = tempfile.mkdtemp(prefix="aether-apply-")
    resume_path = Path(temp_dir) / (
        f"resume-{application_id[:8]}{_resume_suffix(resume_pdf_bytes)}"
    )
    resume_path.write_bytes(resume_pdf_bytes or b"")
    documents[RESUME_DOCUMENT] = str(resume_path)
    cover_path = Path(temp_dir) / f"cover-letter-{application_id[:8]}.txt"
    cover_path.write_text(cover_letter_text or "")
    documents[COVER_LETTER_DOCUMENT] = str(cover_path)

    filled: list[str] = []
    unfilled: list[str] = []
    blocked_required: list[str] = []
    unplanned_filled: list[str] = []
    mode = "live" if apply_url else "replay"
    screenshot = _evidence_path(evidence_dir, application_id, "confirmation.png")
    try:
        with sync_playwright() as runner:  # noqa: SIM117 — cleanup handled below
            browser = runner.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            _renice_browser_tree()
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 1600})
                # CLI-SUB-005-R7 (attack C2) — armed BEFORE any navigation, so
                # it is in place before the page's own scripts (and therefore
                # any custom element's connectedCallback) ever run. See the
                # module note above _CLOSED_SHADOW_MARKER_INIT_JS.
                page.add_init_script(_CLOSED_SHADOW_MARKER_INIT_JS)
                if apply_url:
                    page.goto(apply_url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2000)
                else:
                    # Replay: the DOM was captured elsewhere, so every
                    # subresource in it (CDN CSS, fonts, the employer's
                    # analytics, Google's reCAPTCHA script) is both useless and
                    # a live third-party request we have no reason to make.
                    # Block the lot — it also stops a replay from hanging on a
                    # host that no longer answers.
                    page.route("**/*", lambda route: route.abort())
                    page.set_content(page_html or "", wait_until="domcontentloaded")
                if _hcaptcha_widget_mounted(page):
                    # SUB-011: an hCaptcha widget needs a REAL human to solve
                    # it — nothing here does, or tries to, and there is no
                    # point filling the rest of the form first: the outcome
                    # is already decided. Screenshot the page as evidence
                    # and refuse honestly, distinctly from a TRIGGERED
                    # challenge (`detect_blocking_state`'s "captcha" reason,
                    # checked earlier while the PLAN was built) — this is a
                    # MOUNT, caught here because build_form_fill_plan's
                    # static snapshot cannot see the live DOM's widget.
                    page.screenshot(path=str(screenshot), full_page=True)
                    raise ManualStepRequired(
                        "captcha_challenge",
                        (
                            "This application is protected by an hCaptcha "
                            "challenge Aether cannot solve or bypass, so "
                            "nothing was submitted. Open the posting and "
                            "finish it yourself."
                        ),
                    )
                # CLI-SUB-005: live mode verifies every fill's committed DOM
                # state (read-back + one retry); replay keeps the raw fills —
                # a replayed page is a JS-dead capture no employer can
                # receive anything from, and React widgets cannot mirror
                # state without their scripts.
                verify_commit = bool(apply_url)
                filled, unfilled, blocked_required = _run_fill_plan(
                    page, plan["fields"], documents, verify=verify_commit
                )
                if blocked_required:
                    # A REQUIRED answer we hold did not land in the form. The
                    # employer would receive an incomplete application with the
                    # user's name on it, so nothing is submitted: screenshot the
                    # half-filled form as evidence and hand it back as a manual
                    # step. (The click is skipped ENTIRELY — this is not a
                    # "submit and hope" path.)
                    page.screenshot(path=str(screenshot), full_page=True)
                    raise ManualStepRequired(
                        "form_fill_failed",
                        (
                            "Aether could not enter every required answer into "
                            "this application form, so it submitted nothing. "
                            "Open the posting and apply yourself: "
                            + "; ".join(blocked_required)
                        ),
                        question="; ".join(blocked_required),
                    )
                if verify_commit:
                    # CLI-SUB-005-R3 (adversarial review FAIL,
                    # RUN-20260818T0223Z/SUB-005-R2/08-adversarial-review-
                    # premerge.md): the plan was built from a STATIC,
                    # unanswered page snapshot — a conditional/branching
                    # question (first-class on Ashby/Greenhouse) only exists
                    # in the live DOM once an earlier question is answered,
                    # so it is structurally invisible to that plan, AND the
                    # gate's own refill of a wiped field can itself trigger
                    # the same reveal. Both halves are now ONE bounded
                    # fixed-point loop (_converge_presubmit_state) that
                    # rescans and refills together until a pass changes
                    # nothing, then a final READ-ONLY pass confirms it before
                    # returning. CLI-SUB-005-R6: the ONLY thing that happens
                    # between this call returning and the submit click below
                    # is installing our OWN defensive instrumentation
                    # (_install_submission_guard) — an inert marker attribute
                    # plus an event listener that can never itself reveal,
                    # hide, or answer anything — never a change to any
                    # question's requiredness or committed state.
                    try:
                        unplanned_filled = _converge_presubmit_state(
                            page,
                            channel,
                            plan["fields"],
                            documents,
                            profile=profile,
                            answer_bank=answer_bank,
                        )
                        # CLI-SUB-005-R5 CONSERVATIVE REFUSE-BACKSTOP — see
                        # _verify_no_unverifiable_form_surface. Runs AFTER
                        # convergence has resolved everything it CAN see,
                        # still strictly before the submit click below: the
                        # decisive check that nothing shaped like a control,
                        # on any readable or unreadable surface, was left
                        # unaccounted for. Read-only, like everything above it.
                        _verify_no_unverifiable_form_surface(page, channel)
                        # CLI-SUB-005-R6 root cause 2 (RUN-20260818T0223Z/
                        # SUB-005-R5/08-adversarial-final.md attack #7):
                        # everything above is a CHECK; the click below is the
                        # ACT, and a page's own mousedown/focus handler on the
                        # submit control can reveal a brand-new required field
                        # in that exact gap — deterministically, by DOM
                        # event-ordering spec, not a race. Rather than add
                        # another check-then-act layer, GUARD THE SUBMISSION
                        # EVENT ITSELF: install a capture-phase listener, in
                        # the browser, that re-runs the identical shadow-DOM-
                        # piercing live census (root cause 1) at the literal
                        # instant the submit/click event fires and cancels the
                        # submission outright if anything required is still
                        # uncommitted THEN. Installed on the top document and
                        # every reachable frame, mirroring the backstop above.
                        _install_submission_guard(page)
                        for frame in _reachable_frames(page):
                            _install_submission_guard(frame)
                    except ManualStepRequired:
                        page.screenshot(path=str(screenshot), full_page=True)
                        raise
                    filled.extend(unplanned_filled)
                before_url = page.url
                submitted = _activate_submit(page)
                # The click above can succeed (Playwright's own actionability
                # check is satisfied) even when our capture-phase guard
                # cancelled the SUBMISSION itself — `submitted` alone cannot
                # tell the two apart, so read back what the guard actually
                # blocked, on every surface it was installed on.
                blocked_submission = _read_blocked_submission(page)
                if not blocked_submission:
                    for frame in _reachable_frames(page):
                        frame_blocked = _read_blocked_submission(frame)
                        if frame_blocked:
                            blocked_submission = frame_blocked
                            break
                if blocked_submission:
                    # CLI-SUB-005-R6 — THE DECISIVE INVARIANT: a required
                    # control uncommitted at the instant of submission ⇒ the
                    # submission never completed ⇒ this is an honest refusal,
                    # never a submitted:true outcome. The employer received
                    # NOTHING — the guard cancelled the browser's own default
                    # action before it ever fired.
                    page.screenshot(path=str(screenshot), full_page=True)
                    labels = "; ".join(
                        str(item.get("label") or item.get("kind") or "a required field")
                        for item in blocked_submission
                    )
                    # CLI-SUB-005-R7 — the in-browser guard's own fail-closed
                    # path (see _SUBMIT_GUARD_INSTALL_JS) reports a census
                    # that could not run as a synthetic `census_unavailable`
                    # entry, never a real field — an HONEST, distinct reason
                    # from a genuine unanswered question.
                    unverifiable = all(
                        item.get("kind") == "census_unavailable"
                        for item in blocked_submission
                    )
                    if unverifiable:
                        raise ManualStepRequired(
                            "unverifiable_form_surface",
                            (
                                "This application's own submit handling "
                                "could not be verified at the instant of "
                                "submitting — Aether's browser-level guard "
                                "refused to let the submission go through "
                                "rather than guess, so nothing was sent."
                            ),
                            question=labels,
                        )
                    raise ManualStepRequired(
                        "unplanned_required_field",
                        (
                            "This application revealed a required question "
                            "(sometimes hidden inside a shadow-DOM widget, "
                            "sometimes only at the exact instant of "
                            "submitting) that Aether could not verify was "
                            "answered — its own browser-level guard refused "
                            "to let the submission go through, so nothing "
                            "was sent: " + labels
                        ),
                        question=labels,
                    )
                page.wait_for_timeout(1500)
                confirmation = (
                    _confirmation_signal(page, before_url) if apply_url else None
                )
                page.screenshot(path=str(screenshot), full_page=True)
                if apply_url and submitted and confirmation is None:
                    # LIVE mode demands PROOF, not a click. Without a
                    # confirmation page (or a navigation away from the form),
                    # we do not know the employer received anything — and
                    # "clicked submit" is not "applied". The screenshot above
                    # captures whatever the page is actually showing (usually
                    # its own validation errors) so the user can act on it.
                    raise ManualStepRequired(
                        "no_confirmation",
                        (
                            "Aether filled and submitted this application but "
                            "the site showed no confirmation, so it will not "
                            "claim the application was received. Check the "
                            "screenshot and finish it on the site if needed."
                        ),
                    )
                destination = (
                    page.url
                    if apply_url
                    else f"{channel}: replayed page — no live application URL was opened"
                )
            finally:
                browser.close()
    except (ApplyExecutorTransportError, ManualStepRequired):
        raise
    except Exception as exc:  # noqa: BLE001 — a driver failure is not a submission
        raise ApplyExecutorTransportError(
            "browser_failed",
            (
                "The application browser could not complete this submission "
                f"({type(exc).__name__}) — nothing was submitted."
            ),
        ) from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    sidecar = screenshot.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "applicationId": application_id,
                "channel": channel,
                "mode": mode,
                "applyUrl": apply_url,
                "capturedAt": datetime.now(timezone.utc).isoformat(),
                "submitted": submitted,
                "confirmation": confirmation,
                "commitVerified": verify_commit,
                "fieldsFilled": filled,
                "fieldsNotFilled": unfilled,
                # CLI-SUB-005-R2: which of the above were NOT in the plan's
                # static snapshot and only resolved by the live-DOM rescan —
                # visible in the audit even on a successful submission.
                "unplannedFieldsFilled": unplanned_filled,
                "screenshot": screenshot.name,
            },
            indent=2,
        )
    )
    return {
        "submitted": submitted,
        "confirmation": confirmation,
        "evidencePath": str(screenshot),
        "destination": destination,
        "filled": filled,
        "unfilled": unfilled,
        "unplannedFilled": unplanned_filled,
        "mode": mode,
    }


def fetch_apply_page(apply_url: str) -> str:
    """The employer's application page, rendered — the schema's only source.

    Modern ATS forms are client-rendered (the real Ashby capture is a React
    SPA), so a plain HTTP GET returns a shell with no fields in it. The schema
    must come from the DOM a human would actually see, which is why this runs
    a real browser. Read-only: it navigates and reads, and submits nothing.
    """
    if not apply_url:
        raise ApplyExecutorTransportError(
            "no_apply_url", "No application URL to open — nothing was submitted."
        )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ApplyExecutorTransportError(
            "browser_unavailable",
            "The application browser is not installed on this server — nothing was submitted.",
        ) from exc
    try:
        with sync_playwright() as runner:
            browser = runner.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            _renice_browser_tree()
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 1600})
                page.goto(apply_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                return str(page.content())
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 — a fetch failure is not a submission
        raise ApplyExecutorTransportError(
            "page_fetch_failed",
            (
                f"Could not open the application page ({type(exc).__name__}) — "
                "nothing was submitted."
            ),
        ) from exc


#: Text an ATS shows once it has actually taken the application. Matching one
#: of these (or navigating away from the form) is the only thing that counts as
#: proof in live mode — a click is an attempt, not a receipt.
_CONFIRMATION_TEXT = re.compile(
    r"thank you for (applying|your application)"
    r"|application (has been )?(received|submitted|sent)"
    r"|we(?:'|\u2019)?ve received your application"
    r"|successfully (submitted|applied)"
    r"|your application (is|has been) (in|complete|submitted)",
    re.I,
)


def _confirmation_signal(page: Any, before_url: str) -> str | None:
    """Proof the employer's site accepted the submission, or ``None``."""
    try:
        if page.url and page.url != before_url:
            return f"navigated to {page.url}"
    except Exception:  # noqa: BLE001 — a dead page proves nothing
        return None
    for _ in range(8):
        try:
            body = page.inner_text("body", timeout=1000)
        except Exception:  # noqa: BLE001
            body = ""
        match = _CONFIRMATION_TEXT.search(body or "")
        if match:
            return match.group(0)
        try:
            if page.url and page.url != before_url:
                return f"navigated to {page.url}"
            page.wait_for_timeout(1000)
        except Exception:  # noqa: BLE001
            break
    return None


def _hcaptcha_widget_mounted(page: Any) -> bool:
    """An hCaptcha widget is present in the live DOM at the point of submit.

    SUB-011 scout evidence: every real Lever ``/apply`` page captured so far
    mounts hCaptcha (``#h-captcha`` widget div + a hidden
    ``h-captcha-response`` input) — and unlike the invisible Google
    reCAPTCHA v3 widget every real Ashby/Greenhouse capture ALSO mounts (see
    :func:`detect_blocking_state`'s docstring), a mere MOUNT is not harmless
    here: hCaptcha's checkbox widget requires a genuine human interaction to
    mint a valid response token, so nothing short of a person solving it can
    make the hidden ``h-captcha-response`` input non-empty. Clicking submit
    anyway would not bypass it — it would just submit an application missing
    the token the employer's own server checks for, which is indistinguishable
    from "submitted" until the employer silently drops it. Detecting the
    MOUNT and refusing here, honestly, is the only choice that is not either
    an attempted bypass or a false "submitted" claim.

    CLI-SUB-005-R7 fail-closed discipline (SUB-011-R2 rebase — see
    :func:`_composed_live_census` / :func:`_install_submission_guard` for the
    identical pattern this mirrors) applies here too: this check exists
    BECAUSE a mount cannot be safely bypassed, so an exception while reading
    a LIVE page's own DOM must not silently report "not mounted" and let the
    fill/submit proceed — that would be exactly the fail-open shape R7's
    ruling named ("an exception ... resolves to 'proceed as if nothing were
    wrong,' not 'refuse'"), applied to a check whose whole job is to catch
    the one case (a captcha widget on the page) that makes "proceed anyway"
    genuinely unsafe. FAIL CLOSED: an unreadable LIVE page raises
    :class:`ManualStepRequired` here, never a silent ``False``.
    """
    try:
        return (
            page.locator("#h-captcha, .h-captcha, iframe[src*='hcaptcha.com']").count() > 0
        )
    except Exception as exc:  # CLI-SUB-005-R7 pattern — FAIL CLOSED (was: return False)
        raise ManualStepRequired(
            "captcha_verification_failed",
            (
                "Aether could not verify whether this application is "
                "protected by a captcha challenge, so nothing was "
                "submitted. Open the posting and finish it yourself."
            ),
        ) from exc


def _activate_submit(page: Any) -> bool:
    """Click the form's OWN submit control. ``False`` if there is none."""
    for selector in (
        'button[type="submit"]',
        'input[type="submit"]',
        "button:has-text('Submit application')",
        "button:has-text('Submit Application')",
        "button:has-text('Submit')",
    ):
        try:
            control = page.locator(selector).first
            if control.count() == 0:
                continue
            control.click(timeout=_ACTION_TIMEOUT_MS)
            return True
        except Exception:  # noqa: BLE001 — try the next control shape
            continue
    return False


# ---------------------------------------------------------------------------
# The gated execution.
# ---------------------------------------------------------------------------


def execute_site_application(
    user_id: str,
    application_id: str,
    approval_id: str,
    *,
    page_html: str,
    channel: str,
    profile: dict[str, Any],
    resume_pdf_bytes: bytes,
    cover_letter_text: str,
    evidence_dir: str,
    apply_url: str | None = None,
    submitter: Callable[..., dict[str, Any]] | None = None,
    answer_bank: Callable[[dict[str, Any]], Any] | None = None,
    company: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Apply on the employer's site behind an APPROVED approval — or refuse.

    Order matters and is enforced here, not by callers:

    1. **Gate.** The approval must exist and be ``approved``
       (:class:`ApplyExecutorGuardError`, 404/409, zero side effects).
    2. **Claim.** ``claim_execution`` — the EXISTING single-shot guard, reused
       so a second attempt can never produce a second real submission.
    3. **Plan.** A CAPTCHA, a login wall or an unanswerable required question
       raises :class:`ManualStepRequired`; the reason, the employer's verbatim
       question and (U5d-3) the question's STRUCTURE are persisted on the row
       and the claim is RELEASED, so answering the question in the card makes
       the application retryable.
    4. **Submit + record.** Only a submitter that reports a real submission
       stamps ``transmittedAt``/``transmissionChannel``/``transmissionRef``
       (the evidence screenshot) and completes the approval.

    U5d-3: the Answer Bank is consulted while the plan is built, and every
    answer it supplies is recorded in ``AnswerBankUsage`` BEFORE the browser
    runs. Recording at that point is the honest one: what the audit claims is
    "this banked answer was put into this application's form", which becomes
    true the moment the plan carries it — whether the site then confirms, times
    out or shows a CAPTCHA. Waiting for a confirmed transmission would silently
    lose the audit for exactly the attempts most worth auditing.
    """
    from app.repositories.approval import ApprovalRepository

    # Both additive column sets are ensured up front, before the gate: every
    # exit from here (manual step OR transmission) writes one of them, and the
    # lazy DDL must not be ordered by which branch happens to run first.
    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    repo = ApprovalRepository()
    approval = repo.get_by_id(approval_id, user_id)
    if approval is None:
        raise ApplyExecutorGuardError(
            "approval_not_found",
            "No approval for this application — nothing was submitted.",
            http_status=404,
        )
    if approval.get("status") != "approved":
        raise ApplyExecutorGuardError(
            "not_approved",
            (
                "This application has not been approved for submission — "
                "nothing was submitted."
            ),
            http_status=409,
        )
    if not repo.claim_execution(approval_id, user_id):
        raise ApplyExecutorGuardError(
            "already_executed",
            "This application was already submitted — nothing was submitted again.",
            http_status=409,
        )
    resolver = answer_bank
    if resolver is None:
        resolver = build_answer_bank_resolver(user_id, profile, company=company)
    try:
        plan = build_form_fill_plan(
            page_html, channel=channel, profile=profile, answer_bank=resolver
        )
    except ManualStepRequired as exc:
        record_manual_step(
            user_id,
            application_id,
            exc.reason,
            exc.question or exc.message,
            questions=exc.fields or None,
        )
        repo.release_execution(approval_id, user_id)
        raise
    record_answer_bank_usage(
        user_id, application_id, plan, job_id=job_id
    )
    submit = submitter or playwright_form_submitter
    try:
        outcome = submit(
            application_id=application_id,
            channel=channel,
            page_html=page_html,
            apply_url=apply_url,
            plan=plan,
            resume_pdf_bytes=resume_pdf_bytes,
            cover_letter_text=cover_letter_text,
            evidence_dir=evidence_dir,
            # CLI-SUB-005-R2: so a required field the live DOM reveals AFTER
            # this static plan was built (a conditional/branching question)
            # can still be resolved via the same profile/answer-bank path —
            # never a guess, and never silently unattempted.
            profile=profile,
            answer_bank=resolver,
        )
    except ManualStepRequired as exc:
        record_manual_step(
            user_id,
            application_id,
            exc.reason,
            exc.question or exc.message,
            questions=exc.fields or None,
        )
        repo.release_execution(approval_id, user_id)
        raise
    except Exception:
        repo.release_execution(approval_id, user_id)
        raise
    if not outcome.get("submitted"):
        repo.release_execution(approval_id, user_id)
        record_manual_step(
            user_id,
            application_id,
            "submit_control_not_found",
            (
                "Aether filled this application but could not find the page's "
                "own submit button, so it did NOT submit anything. Open the "
                "posting and submit it yourself."
            ),
        )
        raise ManualStepRequired(
            "submit_control_not_found",
            "The application form exposed no submit control — nothing was submitted.",
        )
    evidence_path = str(outcome.get("evidencePath") or "")
    if outcome.get("mode") == "replay":
        # A replay filled and screenshotted a page that was handed to us rather
        # than one we opened live. Production never takes this path — the sweep
        # only routes channels that HAVE a URL and always passes it — so if this
        # ever fires outside a test the recorded submission is not a live send
        # and the operator needs to know immediately.
        logger.warning(
            "apply-executor recorded application %s as transmitted from a "
            "REPLAYED page (no live application URL was opened)",
            application_id,
        )
    _record_site_transmission(
        user_id,
        application_id,
        destination=str(outcome.get("destination") or apply_url or channel),
        channel=channel,
        ref=evidence_path,
    )
    repo.complete_execution(approval_id, user_id)
    return {
        "transmitted": True,
        "applicationId": application_id,
        "approvalId": approval_id,
        "channel": channel,
        "evidencePath": evidence_path,
        "destination": outcome.get("destination"),
        "mode": outcome.get("mode"),
        "confirmation": outcome.get("confirmation"),
        "fieldsFilled": outcome.get("filled") or [],
        "fieldsNotFilled": outcome.get("unfilled") or [],
        "unplannedFieldsFilled": outcome.get("unplannedFilled") or [],
    }
