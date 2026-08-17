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
    ensure_application_apply_resolution_columns,
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
    ``login_wall``, ``no_automatable_channel``, …). ``question`` carries the
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
    """A label without its required-marker asterisk."""
    return re.sub(r"\s*\*\s*$", "", (raw or "").strip()).strip()


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
    :data:`app.services.apply_channel_resolver.AUTOMATABLE_CHANNELS`, so the
    sweep only ever calls this with ``ashby`` or ``greenhouse``. The fallback
    stays because it is a legitimate schema READER (and the seam Track-2 slice
    U5c builds the lever/smartrecruiters dialects against); it is
    ``AUTOMATABLE_CHANNELS`` — pinned by ``tests/test_u5_invariant_sweep.py`` —
    that decides what may be clicked, not this dispatch.
    """
    soup = _soup(html)
    if channel == "ashby":
        return _parse_ashby(soup)
    if channel == "greenhouse":
        return _parse_greenhouse(soup)
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


def record_apply_url_resolution(
    user_id: str,
    application_id: str,
    *,
    original_url: str,
    resolved_url: str,
) -> None:
    """DISCLOSE that Aether will apply at a different URL than the posting's.

    SUB-006. A Greenhouse posting stored as the employer's own ``?gh_jid=``
    page hosts no form (live probe 2026-08-17: 0 ``<form>`` elements on a
    700KB page); the real form lives at the canonical
    ``boards.greenhouse.io/embed/job_app`` URL, and the apply engine resolves
    to it — but only after fetching the candidate and confirming a real form is
    there (``apply_channel_resolver.resolve_greenhouse_apply_url``).

    Substituting a URL silently would mean the run record said "submitted to
    the posting" while a different page was driven. This writes BOTH sides onto
    the row, so the substitution is auditable from the application itself
    rather than only from a log line.

    Never touches ``transmittedAt``: recording where we are about to apply is
    not a claim that we applied.
    """
    ensure_application_apply_resolution_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                UPDATE "Application"
                SET "applyResolvedFrom" = %s,
                    "applyResolvedUrl" = %s,
                    "applyResolvedAt" = NOW(),
                    "updatedAt" = NOW()
                WHERE "id" = %s AND "userId" = %s
                ''',
                (original_url, resolved_url, application_id, user_id),
            )
        conn.commit()
    logger.info(
        "apply-url resolved for application %s: %s -> %s",
        application_id,
        original_url,
        resolved_url,
    )


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


def _wait(page: Any, ms: int) -> None:
    """Best-effort settle. Unit-test fakes may not implement the clock."""
    try:
        page.wait_for_timeout(ms)
    except Exception:  # noqa: BLE001 — a fake page without a clock waits zero
        pass


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
    escaped = name.replace('"', '\\"')
    candidates = ([f"{scope} input[type=file]"] if scope else []) + [
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
    escaped = name.replace('"', '\\"')
    # Attribute selectors, never ``#id``: real ATS field ids start with digits
    # (Ashby's UUID-keyed questions) or carry ``[]`` (Greenhouse's checkbox
    # groups), both of which are invalid inside a CSS id selector.
    control_selectors = [f'[id="{escaped}"]', f'[name="{escaped}"]']
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
    escaped = name.replace('"', '\\"')
    control_selectors = [f'[id="{escaped}"]', f'[name="{escaped}"]']
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
) -> dict[str, Any]:
    """Fill and submit the application in a REAL headless Chromium.

    ``apply_url`` (production) navigates to the employer's live posting so the
    fill and the submit happen against their real form. Without one, the
    supplied ``page_html`` is loaded directly — the replay/offline mode used by
    tests and by re-running a captured page — and the returned summary says so
    in ``mode``, so an audit can always tell the two apart.

    Returns ``{"submitted", "evidencePath", "destination", "filled",
    "unfilled", "mode"}``. Raises :class:`ApplyExecutorTransportError` if the
    browser itself could not be driven — never a fake success.
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
                    # CLI-SUB-005 PRE-SUBMIT GATE: re-verify every REQUIRED
                    # planned field is still committed in the DOM (a résumé
                    # upload can re-render the form and wipe earlier fills);
                    # one refill pass, then an honest refusal — the submit
                    # control is never activated over an empty required field.
                    try:
                        _presubmit_required_commit_gate(page, plan["fields"], documents)
                    except ManualStepRequired:
                        page.screenshot(path=str(screenshot), full_page=True)
                        raise
                before_url = page.url
                submitted = _activate_submit(page)
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
    }
