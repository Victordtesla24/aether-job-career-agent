"""U5d-2 — the per-application submit CONTROL, computed once on the backend.

USER MANDATE (2026-08-14): every card on ``/dashboard/applications`` gets a
channel-aware control, and clicking it IS the user's approval for THAT
application. This module answers, for ONE application row, the only two
questions the card needs:

* **which honest state is this application in?**
* **what, truthfully, can the user do about it right now?**

WHY THIS LIVES ON THE BACKEND. The FE could derive most of this from the row,
and an earlier generation of this product did exactly that — which is how the
Submitted column ended up asserting 346 submissions the database could not
support (``uat/reports/evidence/agents-uplift/u5d/FORENSICS.md``). A card
state is a CLAIM about what happened to a real job application, so it is
computed in one place, from persisted columns, and pinned by one test suite.
The FE renders what it is given and adds only the two states the server cannot
observe (see :data:`CARD_STATES`).

PURE. No I/O, no network, no clock. Every input is a column already SELECTed by
``applications._COLUMNS``; the apply channel is classified by
``apply_channel_resolver.classify_url``, which is deliberately the offline,
string-only classifier — a READ of the tracker board must never make an
outbound HTTP request to an employer's site.
"""
from __future__ import annotations

from typing import Any

from app.services.apply_channel_resolver import (
    ASSISTED_CHANNELS,
    AUTOMATABLE_CHANNELS,
    classify_url,
    platform_label,
)

#: Every state a card can be in. The first six are decided HERE, from persisted
#: columns. ``submitting`` and ``failed`` are deliberately NOT server-derived:
#: they describe the browser's own in-flight request (the click has been sent,
#: the execute call has not answered yet / answered with an honest error), and
#: no column records them. The FE owns those two and may only hold them for the
#: lifetime of its own request — it must re-read the row afterwards and adopt
#: whichever state THIS module then reports, so a failed transmission can never
#: leave a card stuck claiming progress.
CARD_STATES = frozenset(
    {
        "draft",
        "ready",
        "needs_your_click",
        "manual_step",
        "expired_reconfirm",
        "recorded_not_transmitted",
        "submitted",
        # FE-owned, transient, never persisted:
        "submitting",
        "failed",
    }
)

#: What the control DOES when clicked. ``submit``/``send_email`` are the only
#: two that can ever lead to a transmission, and both go through
#: ``POST /applications/{id}/request-submission`` (create + approve) followed by
#: the EXISTING ``POST /approvals/{id}/execute`` — never a private path.
#:
#: ``answer_question`` (U5d-3, ADR-SUB-AUTON-1 Pillar 4a) is the LAW OF MINIMAL
#: USER ACTIVITY made concrete: the card renders the employer's own question
#: with a real input, the user answers inside Aether, and the answer is banked.
#: It transmits nothing either — ``POST /applications/{id}/answer-question``
#: banks the answer and unblocks the card; submitting is still a separate,
#: explicit act.
ACTIONS = frozenset(
    {
        "submit",
        "send_email",
        "open_posting",
        "reconfirm",
        "fix_artifacts",
        "answer_question",
        "none",
    }
)

#: Application statuses that mean the user has already recorded this as sent.
_RECORDED_STATUSES = frozenset({"submitted", "screening", "interview", "offer"})

#: Statuses where the application is over and no control belongs on the card.
_CLOSED_STATUSES = frozenset({"rejected", "withdrawn"})


def resolve_channel(row: dict[str, Any]) -> str:
    """The apply channel for this row, WITHOUT any network call.

    Precedence mirrors ``apply_channel_resolver.resolve_apply_channel`` exactly
    — persisted answer first (the sweep/agent may already have followed a
    redirector), then the employer's published address, then offline
    classification of the stored URL — minus the one branch that costs an
    outbound request. An Adzuna redirector that has never been resolved
    therefore reads as its own host's classification rather than being followed
    from a page render; that is the honest, cheap answer, and the agent's own
    run upgrades it to the real one.
    """
    persisted = (row.get("applyChannel") or "").strip()
    if persisted:
        return persisted
    if (row.get("applyEmail") or "").strip():
        return "email"
    return classify_url((row.get("applyUrl") or "").strip())


def _missing_artifacts(row: dict[str, Any]) -> list[str]:
    """Which of the two gate artifacts this application does not have yet.

    The SAME two conditions ``jobs._resume_for_apply`` /
    ``jobs._cover_letter_for_apply`` enforce — a job-tailored résumé and a
    non-empty Cover Letter Studio draft — read off columns the list endpoint
    already carries, so the card promises exactly what the write path will
    accept and never offers a button that is guaranteed to 422.
    """
    missing: list[str] = []
    if not row.get("hasTailoredResume"):
        missing.append("tailoredResume")
    if not (row.get("coverLetter") or "").strip():
        missing.append("coverLetter")
    return missing


def _manual_step_questions(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The structured questions this row is blocked on — never a guess.

    Reads ``Application.manualStepQuestions`` (U5d-3 additive column), which is
    written straight from what the apply-executor parsed off the employer's
    page. A row blocked BEFORE that column existed carries NULL and gets an
    empty list, which is why the caller keeps the pre-U5d-3 "open the posting"
    control for it: we did not capture that form's structure, so we cannot
    honestly render its inputs.

    Each entry is normalised to exactly the keys the card renders, and the
    sensitivity class is RE-DERIVED from the question text rather than trusted
    from the stored row — the card's "Aether will never send this for you"
    note has to be true even for a row written by an older build.
    """
    from app.services.answer_bank import classify_sensitivity

    raw = row.get("manualStepQuestions")
    if not isinstance(raw, list):
        return []
    questions: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or entry.get("name") or "").strip()
        if not label:
            continue
        sensitivity = classify_sensitivity(label)
        questions.append(
            {
                "name": str(entry.get("name") or label),
                "label": label,
                "kind": str(entry.get("kind") or "text"),
                "options": [str(option) for option in (entry.get("options") or [])],
                "required": bool(entry.get("required", True)),
                "sensitivity": sensitivity,
                # Honest, per-question: will answering this once let Aether
                # answer it next time, or is it user-gated forever?
                "reusable": sensitivity == "factual",
            }
        )
    return questions


def _fix_control(row: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    job_id = row.get("jobId")
    if "tailoredResume" in missing:
        label = "Tailor resume first"
        href = f"/dashboard/resume?job={job_id}" if job_id else "/dashboard/resume"
        detail = (
            "This application has no job-tailored résumé yet"
            + (" and no cover letter" if "coverLetter" in missing else "")
            + ". Aether will not submit an untailored application."
        )
    else:
        label = "Generate a cover letter first"
        href = (
            f"/dashboard/cover-letters?job={job_id}"
            if job_id
            else "/dashboard/cover-letters"
        )
        detail = (
            "This application has no cover-letter draft yet. Generate one in "
            "the Cover Letter Studio."
        )
    return {
        "state": "draft",
        "action": "fix_artifacts",
        "label": label,
        "detail": detail,
        "href": href,
        "missing": missing,
    }


def describe_submission_control(row: dict[str, Any]) -> dict[str, Any]:
    """The card's honest state + the one control it may offer.

    Precedence, highest first — each rung is a fact the one below it cannot
    override:

    1. **Transmission proof.** ``transmittedAt`` is the only thing in this
       product that can make a card say "Submitted". Checked first so no later
       branch can ever talk over it.
    2. **A recorded manual step.** The apply engine hit a real obstacle and
       persisted it. ``approval_expired`` gets its own state because it is the
       one obstacle a single click genuinely fixes; ``assisted_manual_submit``
       gets its own because it is not an obstacle at all — everything is ready
       and the platform simply needs the user's click.
    3. **A closed application** (rejected/withdrawn) — no control.
    4. **Already recorded by the user** without proof: the 346-row production
       state. Offering "Submit" here could put a SECOND application in front of
       the same employer, so the card states the truth and offers nothing.
    5. **Missing gate artifacts** — say which one, and link to where it is
       fixed, instead of showing a button that would 422.
    6. **The channel**, finally, decides which control a ready draft gets.
    """
    transmitted_at = row.get("transmittedAt")
    channel = resolve_channel(row)
    apply_url = (row.get("applyUrl") or "").strip() or None
    status = str(row.get("status") or "")
    base: dict[str, Any] = {
        "channel": channel,
        "applyUrl": apply_url,
        "missing": [],
        "href": None,
        # U5d-3 Pillar 4a: the employer's own questions, structured, so the
        # card can render real inputs. Empty for every state that is not an
        # unanswered-question manual step — including a manual step that is a
        # CAPTCHA or a login wall, which have nothing to type.
        "questions": [],
    }

    if transmitted_at is not None:
        ref = row.get("transmissionRef")
        return {
            **base,
            "state": "submitted",
            "action": "none",
            "label": "Submitted ✓",
            "detail": (
                "Aether transmitted this application"
                + (f" — evidence: {ref}" if ref else "")
                + "."
            ),
        }

    manual_reason = (row.get("manualStepReason") or "").strip()
    manual_detail = (row.get("manualStepDetail") or "").strip()
    if manual_reason == "approval_expired":
        return {
            **base,
            "state": "expired_reconfirm",
            "action": "reconfirm",
            "label": "Reconfirm to submit",
            "detail": manual_detail
            or (
                "Your approval for this application is older than Aether will "
                "act on without a fresh confirmation. Nothing was sent."
            ),
        }
    if manual_reason == "assisted_manual_submit":
        return {
            **base,
            "state": "needs_your_click",
            "action": "open_posting" if apply_url else "none",
            "label": "Ready to submit — open posting",
            "detail": manual_detail
            or (
                f"Your tailored résumé and cover letter are ready — "
                f"{platform_label(channel)} needs your click."
            ),
        }
    if manual_reason:
        questions = _manual_step_questions(row)
        if manual_reason == "unknown_required_question" and questions:
            # PILLAR 4a. The blocker is a question, and we captured its
            # structure, so the irreducible human step is answering it — which
            # happens HERE, in the card. Nothing about that is a site visit,
            # and the applyUrl still travels on the block so the user can
            # always choose to go to the source instead.
            count = len(questions)
            return {
                **base,
                "state": "manual_step",
                "action": "answer_question",
                "questions": questions,
                "label": (
                    f"Answer it here — {count} question{'' if count == 1 else 's'}"
                ),
                "detail": (
                    "This employer asks something Aether has no answer for and "
                    "will not invent. Answer it below and Aether saves it for "
                    "every future application that asks the same thing."
                ),
            }
        return {
            **base,
            "state": "manual_step",
            "action": "open_posting" if apply_url else "none",
            "label": "Needs a manual step",
            "detail": manual_detail
            or f"Aether stopped at an obstacle it will not guess past ({manual_reason}).",
        }

    if status in _CLOSED_STATUSES:
        return {
            **base,
            "state": "recorded_not_transmitted",
            "action": "none",
            "label": f"Closed — {status}",
            "detail": "This application is closed. Aether transmitted nothing.",
        }

    if status in _RECORDED_STATUSES:
        return {
            **base,
            "state": "recorded_not_transmitted",
            "action": "none",
            "label": "Recorded — not transmitted",
            "detail": (
                "You recorded this application as sent. Aether has no evidence "
                "it transmitted anything, and will not submit it again — that "
                "could put a second application in front of the same employer."
            ),
        }

    missing = _missing_artifacts(row)
    if missing:
        return {**base, **_fix_control(row, missing)}

    if channel == "email":
        recipient = (row.get("applyEmail") or "").strip()
        return {
            **base,
            "state": "ready",
            "action": "send_email",
            "label": "Send application email",
            "detail": (
                "This posting publishes an application address"
                + (f" ({recipient})" if recipient else "")
                + ". Clicking approves and sends it — nothing is sent before that."
            ),
        }
    if channel in AUTOMATABLE_CHANNELS:
        return {
            **base,
            "state": "ready",
            "action": "submit",
            "label": "Submit application",
            "detail": (
                f"Aether can complete this {platform_label(channel)} application "
                "for you. Clicking is your approval for THIS application — "
                "nothing is submitted before that click."
            ),
        }
    if channel in ASSISTED_CHANNELS:
        return {
            **base,
            "state": "needs_your_click",
            "action": "open_posting" if apply_url else "none",
            "label": "Ready to submit — open posting",
            "detail": (
                f"Your tailored résumé and cover letter are ready — "
                f"{platform_label(channel)} needs your click. Aether does not "
                "auto-submit on this platform."
            ),
        }
    if channel == "seek-manual":
        return {
            **base,
            "state": "needs_your_click",
            "action": "open_posting" if apply_url else "none",
            "label": "Ready to submit — open posting",
            "detail": (
                "This role is posted on Seek, which prohibits automated access "
                "(ADR-SEEK-V3). Aether will not submit there — open the posting "
                "and apply yourself."
            ),
        }
    return {
        **base,
        "state": "manual_step",
        "action": "open_posting" if apply_url else "none",
        "label": "Apply on the employer's site",
        "detail": (
            "Aether could not determine where this posting's application "
            "actually goes, so it will not submit anything."
        ),
    }
