"""SUB-010 — the Answer Pack: one honest screen for a manual application.

LEDGER (SUB-010, owner's idea): *"read-only ``GET /applications/{id}/
answer-pack`` fusing profile + answer bank + resume + cover for every manual
job, + a 'needs your click' filter. Buildable from existing parts. Honesty
contract: never claims applied."*

WHAT THIS SOLVES. Most applications in this product end at an honest manual
step: the platform prohibits automation (Seek), the site wants a login, or the
form asks something Aether refuses to invent an answer to. The user then has to
finish the application themselves — and until now that meant re-assembling, by
hand and from four different screens, material Aether already holds for that
one job: the contact details on their résumé, the answers they banked for the
screening questions this form asks, the job-tailored résumé, and the cover
letter. This module fuses those four into one payload.

THREE RULES, all of them the existing honesty floor rather than new policy:

1. **Nothing here is generated.** Every value is either the user's own words
   (résumé contact block, banked answers, per-application answers), an artifact
   Aether already produced for THIS application (the tailored résumé, the cover
   letter), or a fact off the row. There is no summariser, no LLM call, no
   "suggested" anything. A piece that does not exist is reported ABSENT with a
   reason — never defaulted, never filled from a neighbouring job.

2. **The pack never claims a submission.** It is built for exactly the
   population that has none: prepared-but-not-transmitted rows (SUB-006). So
   every string this module authors about a non-transmitted application says
   *prepared* / *ready*, and :func:`honesty_block` states the fact outright.
   The user's stored ``Application.status`` is deliberately NOT echoed into the
   pack: for the live production rows it reads ``submitted`` while
   ``transmittedAt`` is NULL, and re-publishing that word into a new surface is
   how the over-claim happened the first time.

3. **The transmission gate is reported, never widened.** A banked answer the
   user cannot have Aether send for them (sensitive class, or a judgement call
   they have not opted in) is still SHOWN here — it is the user's own answer,
   already served verbatim to the same owner by ``GET /answer-bank``, and this
   pack exists so they can copy it into the form THEMSELVES. What travels with
   it is ``wouldAutoSend: false`` plus the gate reason, so the pack can never
   be mistaken for "Aether will handle this one". ``find_match``'s gate is
   evaluated separately and unchanged; nothing here can open it.

PURE. No I/O, no network, no clock beyond an injectable ``now``. The router
does every read and hands the rows in, so every rule below is pinned by
``tests/test_sub010_answer_pack.py`` rather than by luck.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Sequence

from app.services.answer_bank import (
    SEED_QUESTIONS,
    AnswerBankMatch,
    classify_sensitivity,
    describe_gate,
    find_match,
    per_application_items,
    semantic_key,
)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: What the pack claims about the application it describes. ``prepared`` is the
#: SUB-006 word for "the artifacts are ready, nothing was transmitted, the
#: click is still yours".
CLAIM_PREPARED = "prepared"
CLAIM_TRANSMITTED = "transmitted"

#: Where a question in the pack came from. ``employer_form`` is the employer's
#: OWN verbatim wording, captured off their page by the apply-executor and
#: persisted on the row; ``likely_for_any_application`` is the seed question
#: set — the classes ATS platforms ask on nearly every form.
QUESTION_SOURCE_EMPLOYER = "employer_form"
QUESTION_SOURCE_LIKELY = "likely_for_any_application"

#: Where an answer came from. Never anywhere else — there is no third layer,
#: and in particular no generator.
ANSWER_SOURCE_THIS_APPLICATION = "this_application"
ANSWER_SOURCE_BANK = "answer_bank"

#: The honest absence text for a question nobody has answered yet.
NO_ANSWER_ABSENCE = (
    "You have not answered this yet, and Aether will not invent an answer. "
    "Type one into the card or your Answer Bank and it is yours from then on."
)

#: Honest absence for the two artifacts.
NO_RESUME_ABSENCE = (
    "There is no job-tailored résumé for this role yet. Tailor one in the "
    "Résumé Studio and it appears here — Aether will not offer a résumé "
    "written for a different job in its place."
)
NO_COVER_LETTER_ABSENCE = (
    "There is no cover-letter draft for this application yet. Write one in the "
    "Cover Letter Studio and it appears here."
)

#: The pack's own statement of what it is. Note the negation: "transmitted"
#: appears in this module's copy only inside one.
PREPARED_STATEMENT = (
    "Aether has NOT transmitted this application anywhere. Everything below is "
    "material Aether prepared for you, ready to copy into the employer's own "
    "form — the click is still yours."
)
TRANSMITTED_STATEMENT = (
    "Aether transmitted this application, with the evidence recorded on the "
    "row. The material below is what went with it."
)
READ_ONLY_NOTE = (
    "Opening this pack changes nothing and contacts no employer. It is a "
    "read-only view of what Aether already holds for this role."
)

# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_URL_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.I)
#: Deliberately strict: at least 8 digits, and nothing but the punctuation a
#: phone number is written with. A looser pattern would claim a postcode or a
#: date is the user's phone number, which is a fabrication with a real cost —
#: an employer calling the wrong number.
_PHONE_RE = re.compile(r"^\+?[\d][\d\s().\-]{6,}\d$")

#: Absence copy for a profile field, per field, so the user is told WHERE to
#: put it rather than only that it is missing.
_PROFILE_ABSENCE = {
    "fullName": "Not on file. Add your name to your Aether account or your résumé.",
    "email": "Not on file. Your account email is the address employers reply to.",
    "phone": "No phone number on your résumé's contact block. Aether will not guess one.",
    "location": "No location on your résumé's contact block.",
    "linkedin": "No LinkedIn URL on file — add it under Career Data or to your résumé.",
    "github": "No GitHub URL on file — add it under Career Data or to your résumé.",
    "portfolio": "No portfolio URL on file — add it under Career Data or to your résumé.",
}

_PROFILE_LABELS = {
    "fullName": "Full name",
    "email": "Email",
    "phone": "Phone",
    "location": "Location",
    "linkedin": "LinkedIn",
    "github": "GitHub",
    "portfolio": "Portfolio",
}

#: The order a form asks for them in.
PROFILE_KEYS = (
    "fullName",
    "email",
    "phone",
    "location",
    "linkedin",
    "github",
    "portfolio",
)

_LINK_HOSTS = {
    "linkedin": ("linkedin.com",),
    "github": ("github.com",),
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _field(key: str, value: str, source: str) -> dict[str, Any]:
    """One profile field, present or honestly absent."""
    text = _clean(value)
    return {
        "key": key,
        "label": _PROFILE_LABELS.get(key, key),
        "value": text or None,
        "present": bool(text),
        # WHERE it came from — a copied value the user cannot trace is a value
        # they cannot check before pasting it into a real employer's form.
        "source": source if text else None,
        "absence": None if text else _PROFILE_ABSENCE.get(key, "Not on file."),
    }


def classify_contact_line(line: str) -> str:
    """Which profile field a résumé contact line is, or ``""``.

    Order matters: a URL is tested first so ``linkedin.com/in/…`` is never
    read as a phone number by the digit-heavy pattern below.
    """
    text = _clean(line)
    if not text:
        return ""
    if _URL_RE.match(text):
        lowered = text.lower()
        for key, hosts in _LINK_HOSTS.items():
            if any(host in lowered for host in hosts):
                return key
        return "portfolio"
    if _EMAIL_RE.match(text):
        return "email"
    if _PHONE_RE.match(text):
        return "phone"
    return ""


def build_profile(
    *,
    account_name: str = "",
    account_email: str = "",
    resume_name: str = "",
    resume_contact: Sequence[str] = (),
    resume_location: str = "",
    career_profiles: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """The profile half of the pack: the fields every application form asks for.

    Sources, in precedence order per field, all of them things the user
    themselves put into the product:

    * the Aether account (name, email);
    * the résumé's own contact block, parsed by ``resume_document`` — the same
      lines the employer will see on the document;
    * the Career Data store (``CareerProfile``) for the three link fields.

    Nothing is derived, inferred from the company, or defaulted. A field with
    no source is returned ``present: False`` with the place to go and fix it.
    """
    from_contact: dict[str, str] = {}
    other_lines: list[str] = []
    for line in resume_contact:
        key = classify_contact_line(line)
        if key and key not in from_contact:
            from_contact[key] = _clean(line)
        elif not key:
            text = _clean(line)
            if text:
                other_lines.append(text)

    links: dict[str, str] = {}
    for profile in career_profiles:
        source = _clean(profile.get("source"))
        url = _clean(profile.get("url"))
        if source in ("github", "linkedin", "portfolio") and url:
            links.setdefault(source, url)

    fields: list[dict[str, Any]] = []
    for key in PROFILE_KEYS:
        if key == "fullName":
            fields.append(
                _field("fullName", account_name, "your Aether account")
                if _clean(account_name)
                else _field("fullName", resume_name, "your résumé")
            )
        elif key == "email":
            fields.append(
                _field("email", account_email, "your Aether account")
                if _clean(account_email)
                else _field("email", from_contact.get("email", ""), "your résumé")
            )
        elif key == "location":
            fields.append(_field("location", resume_location, "your résumé"))
        elif key in ("linkedin", "github", "portfolio"):
            if links.get(key):
                fields.append(_field(key, links[key], "your Career Data"))
            else:
                fields.append(_field(key, from_contact.get(key, ""), "your résumé"))
        else:
            fields.append(_field(key, from_contact.get(key, ""), "your résumé"))

    return {
        "fields": fields,
        "presentCount": sum(1 for item in fields if item["present"]),
        "missingCount": sum(1 for item in fields if not item["present"]),
        # Contact lines the classifier could not name. Kept VERBATIM rather
        # than dropped or guessed at: they are the user's own words and may be
        # the very line the form wants.
        "otherResumeContactLines": other_lines,
    }


# ---------------------------------------------------------------------------
# Questions and answers
# ---------------------------------------------------------------------------


def employer_questions(row: dict[str, Any]) -> list[dict[str, str]]:
    """The questions this employer's own form asked, verbatim.

    Read off ``Application.manualStepQuestions`` (what the apply-executor
    parsed off the page) and the keys of ``answers.screeningAnswers`` (what the
    user has already typed for this application). Both are the EMPLOYER's
    wording; neither is paraphrased here, because the user is about to answer
    that exact question on that exact form.
    """
    questions: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        label = _clean(text)
        if not label:
            return
        key = semantic_key(label)
        if key in seen:
            return
        seen.add(key)
        questions.append({"question": label, "questionSource": QUESTION_SOURCE_EMPLOYER})

    raw = row.get("manualStepQuestions")
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                add(_clean(entry.get("label")) or _clean(entry.get("name")))

    answers = row.get("answers")
    if isinstance(answers, dict):
        screening = answers.get("screeningAnswers")
        if isinstance(screening, dict):
            for question in screening:
                add(str(question))
    return questions


def likely_questions(exclude: Sequence[str] = ()) -> list[dict[str, str]]:
    """The questions this form is LIKELY to ask, from the seed set.

    The seed questionnaire is this product's curated list of "the most common
    real screening questions across ATS platforms" — so it is exactly the right
    answer to "what will this form want that we have not seen yet". A question
    already captured from the employer's own page wins and is excluded here, so
    the pack never shows the same question twice in two wordings.
    """
    taken = {semantic_key(text) for text in exclude}
    out: list[dict[str, str]] = []
    for seed in SEED_QUESTIONS:
        key = semantic_key(seed.question)
        if key in taken:
            continue
        taken.add(key)
        out.append({"question": seed.question, "questionSource": QUESTION_SOURCE_LIKELY})
    return out


def _entry(
    question: str,
    question_source: str,
    *,
    match: AnswerBankMatch | None,
    answer_source: str | None,
    would_auto_send: bool,
) -> dict[str, Any]:
    answered = match is not None
    return {
        "question": question,
        "questionSource": question_source,
        "sensitivity": classify_sensitivity(question),
        "answered": answered,
        "answer": match.answer if match else None,
        "answerSource": answer_source if answered else None,
        # ADR honesty floor 3: an answer never travels without the facts that
        # justify the match, so the user can judge it before pasting it.
        "bankedQuestion": match.banked_question if match else None,
        "matchConfidence": round(match.confidence, 3) if match else None,
        "matchMethod": match.method if match else None,
        # Would Aether ever send this for you, unattended? Reported, never
        # widened — see this module's rule 3.
        "wouldAutoSend": bool(would_auto_send),
        "gateReason": describe_gate(question),
        "absence": None if answered else NO_ANSWER_ABSENCE,
    }


def build_answers(
    questions: Sequence[dict[str, str]],
    *,
    bank_items: Sequence[dict[str, Any]],
    screening_answers: Any = None,
    company: str | None = None,
    job_family: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Every question in the pack, with the user's own answer where one exists.

    Two layers, exactly the ones ``answer_bank.build_resolver`` uses and in the
    same order — this application's own answers first, then the standing bank —
    so the pack shows what the apply-executor would actually use rather than a
    second, divergent opinion.

    For the standing bank the match is computed TWICE on purpose: once through
    the real transmission gate (which decides ``wouldAutoSend``) and once
    without it (which decides what is DISPLAYED to the owner of the answer).
    They are different questions. "May Aether send this to an employer without
    asking?" is gated hard, and this pack cannot and does not change that
    answer. "May the user see the answer they wrote?" was never gated — the
    Answer Bank page serves the same string to the same person — and hiding it
    here would only mean they retype it.
    """
    local_items = per_application_items(screening_answers)
    entries: list[dict[str, Any]] = []
    for item in questions:
        question = item["question"]
        source = item["questionSource"]

        local = find_match(
            question,
            local_items,
            company=company,
            job_family=job_family,
            now=now,
            ignore_sensitivity_gate=True,
        )
        if local is not None:
            entries.append(
                _entry(
                    question,
                    source,
                    match=local,
                    answer_source=ANSWER_SOURCE_THIS_APPLICATION,
                    # The user answered THIS form themselves, so the executor
                    # uses it without a class gate (build_resolver layer 1).
                    would_auto_send=True,
                )
            )
            continue

        gated = find_match(
            question, bank_items, company=company, job_family=job_family, now=now
        )
        shown = gated or find_match(
            question,
            bank_items,
            company=company,
            job_family=job_family,
            now=now,
            ignore_sensitivity_gate=True,
        )
        entries.append(
            _entry(
                question,
                source,
                match=shown,
                answer_source=ANSWER_SOURCE_BANK,
                would_auto_send=gated is not None,
            )
        )

    answered = sum(1 for entry in entries if entry["answered"])
    return {
        "entries": entries,
        "answeredCount": answered,
        "unansweredCount": len(entries) - answered,
        "note": (
            "Answers are your own words, stored exactly as you wrote them. "
            "Aether never rewrites one and never invents one it does not have."
        ),
    }


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def resume_block(tailored: dict[str, Any] | None) -> dict[str, Any]:
    """The tailored-résumé artifact REFERENCE — an id and its download path.

    The bytes are not inlined: ``GET /resumes/{id}/download`` is the one
    renderer the user's own download button and the email attachment path both
    go through, so the document the employer receives is byte-identical to the
    one this pack points at. A second rendering here could disagree with it.

    ``None`` in means there is no résumé tailored to THIS job, which is
    reported as absent — the base résumé is deliberately not substituted:
    offering an untailored document as "the résumé for this role" is exactly
    the silent substitution the submission gate refuses.
    """
    if not tailored:
        return {
            "present": False,
            "resumeId": None,
            "version": None,
            "label": None,
            "tailoredToThisJob": False,
            "downloadPath": None,
            "updatedAt": None,
            "absence": NO_RESUME_ABSENCE,
        }
    resume_id = _clean(tailored.get("id"))
    return {
        "present": True,
        "resumeId": resume_id,
        "version": tailored.get("version"),
        "label": _clean(tailored.get("label")) or None,
        "tailoredToThisJob": True,
        "downloadPath": f"/resumes/{resume_id}/download",
        "updatedAt": tailored.get("updatedAt"),
        "absence": None,
    }


def cover_letter_block(cover_letter: Any) -> dict[str, Any]:
    """The cover letter Aether wrote for THIS application, verbatim or absent."""
    text = _clean(cover_letter)
    return {
        "present": bool(text),
        "text": text or None,
        "characterCount": len(text) if text else 0,
        # The cover letter is stored as text on the row, so there is no
        # rendered artifact to point at. Stated as None rather than invented.
        "downloadPath": None,
        "absence": None if text else NO_COVER_LETTER_ABSENCE,
    }


# ---------------------------------------------------------------------------
# The honesty block
# ---------------------------------------------------------------------------


def honesty_block(row: dict[str, Any]) -> dict[str, Any]:
    """What the pack is allowed to claim about this application.

    ``transmittedAt`` is the ONLY thing in this product that can make any
    surface say a submission happened (``submission_control`` rung 1), so it is
    the only input here. The stored ``Application.status`` is not consulted and
    not echoed: for every live production row it says ``submitted`` while this
    column is NULL, and that word is the over-claim SUB-006 removed from the
    board.
    """
    transmitted = row.get("transmittedAt") is not None
    return {
        "transmitted": transmitted,
        "claim": CLAIM_TRANSMITTED if transmitted else CLAIM_PREPARED,
        "statement": TRANSMITTED_STATEMENT if transmitted else PREPARED_STATEMENT,
        "readOnly": True,
        "note": READ_ONLY_NOTE,
        # The evidence, when there is any. Never a placeholder when there is
        # not: a reference the user cannot check is worse than none.
        "evidenceRef": row.get("transmissionRef") if transmitted else None,
        "transmittedAt": row.get("transmittedAt") if transmitted else None,
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_answer_pack(
    *,
    row: dict[str, Any],
    account_name: str = "",
    account_email: str = "",
    resume_name: str = "",
    resume_contact: Sequence[str] = (),
    resume_location: str = "",
    career_profiles: Sequence[dict[str, Any]] = (),
    bank_items: Sequence[dict[str, Any]] = (),
    tailored_resume: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The whole pack for ONE application. Pure — the router does the reads."""
    company = _clean(row.get("company")) or None
    known = employer_questions(row)
    questions = known + likely_questions([item["question"] for item in known])
    answers_json = row.get("answers")
    screening = (
        answers_json.get("screeningAnswers") if isinstance(answers_json, dict) else None
    )
    return {
        "applicationId": _clean(row.get("id")),
        "jobId": _clean(row.get("jobId")),
        "jobTitle": _clean(row.get("jobTitle")),
        "company": company or "",
        "applyUrl": _clean(row.get("applyUrl")) or None,
        "honesty": honesty_block(row),
        "profile": build_profile(
            account_name=account_name,
            account_email=account_email,
            resume_name=resume_name,
            resume_contact=resume_contact,
            resume_location=resume_location,
            career_profiles=career_profiles,
        ),
        "answers": build_answers(
            questions,
            bank_items=bank_items,
            screening_answers=screening,
            company=company,
            now=now,
        ),
        "resume": resume_block(tailored_resume),
        "coverLetter": cover_letter_block(row.get("coverLetter")),
    }
