"""U5d-3 — the Answer Bank as a first-class, user-owned surface.

ADR-SUB-AUTON-1 Pillar 1: *"USER-VISIBLE: Answer Bank is a first-class UI
surface (view/edit/expire/delete every answer; see where each was used)."*

Every route here is about the user's OWN words. Nothing in this router
generates an answer, suggests one, or rewrites one:

* ``GET /answer-bank/questionnaire`` serves the seed QUESTIONS with no answers
  and no defaults — a questionnaire that pre-fills itself is a fabrication
  engine wearing a form;
* ``POST /answer-bank/questionnaire`` banks what the user typed, verbatim, with
  provenance ``onboarding``; a skipped question banks nothing and is not an
  error, because "I would rather answer that one per application" is a
  legitimate choice;
* ``GET /answer-bank`` lists every banked answer with its provenance, its
  class, whether it has expired, and WHERE IT WAS USED — read from the recorded
  ``AnswerBankUsage`` audit, never reconstructed;
* ``PATCH``/``expire``/``DELETE`` are the user's controls over their own data.

THE ONE THING THE USER CANNOT DO HERE is switch a sensitive/legal answer on for
auto-answering. That refusal is enforced in the repository AND in the matcher;
this router only reports it, in words, so the UI never has to guess why a
toggle did not move.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.db import (
    ensure_application_manual_step_question_column,
    get_connection,
    rows_to_dicts,
)
from app.middleware.auth import CurrentUser
from app.repositories.answer_bank import AnswerBankRepository
from app.services.answer_bank import (
    AUTO_ANSWER_CONFIDENCE,
    SENSITIVITY_SENSITIVE,
    concept_of,
    describe_gate,
    effective_sensitivity,
    item_auto_answers,
    item_is_expired,
    readiness_summary,
    seed_question_payload,
)

router = APIRouter()


class BankAnswerRequest(BaseModel):
    """Bank one answer the user typed — in the questionnaire or the bank page."""

    question: str = Field(..., max_length=2000)
    answer: str = Field(..., max_length=8000)
    scope: str = Field(default="global", max_length=32)
    scope_value: str | None = Field(default=None, max_length=200)


class QuestionnaireAnswer(BaseModel):
    question: str = Field(..., max_length=2000)
    answer: str = Field(default="", max_length=8000)


class QuestionnaireRequest(BaseModel):
    answers: list[QuestionnaireAnswer] = Field(..., max_length=60)


class UpdateItemRequest(BaseModel):
    answer: str | None = Field(default=None, max_length=8000)
    scope: str | None = Field(default=None, max_length=32)
    scope_value: str | None = Field(default=None, max_length=200)
    autoAnswerOptIn: bool | None = None


def _view(item: dict[str, Any], usage: list[dict[str, Any]]) -> dict[str, Any]:
    """One bank item as the UI reads it — facts plus the honest gate reason.

    ``expired``, ``sensitivity`` and ``autoAnswers`` all come from the
    matcher's own helpers rather than being re-derived here, so a row cannot
    drift into claiming it is live after its staleness policy has run out, and
    the page can never promise an auto-answer the agent would in fact gate.
    ``sensitivity`` is the EFFECTIVE class (the stronger of the stored column
    and the question's own wording) for the same reason.
    """
    expired = item_is_expired(item)
    sensitivity = effective_sensitivity(item)
    return {
        "id": item["id"],
        "questionText": item["questionText"],
        "semanticKey": item["semanticKey"],
        "answer": item["answer"],
        "scope": item["scope"],
        "scopeValue": item["scopeValue"],
        "provenance": item["provenance"],
        "provenanceDetail": item["provenanceDetail"],
        "sensitivity": sensitivity,
        "staleDays": item["staleDays"],
        "expiresAt": item["expiresAt"],
        "expired": expired,
        "autoAnswerOptIn": bool(item["autoAnswerOptIn"]),
        # Will Aether actually send this without asking? The one question a
        # user looking at this page most needs answered, so it is computed
        # here rather than left for the client to re-derive from three fields.
        "autoAnswers": item_auto_answers(item),
        "canOptIn": sensitivity != SENSITIVITY_SENSITIVE,
        "gateReason": describe_gate(item["questionText"], item),
        "timesUsed": item["timesUsed"],
        "lastUsedAt": item["lastUsedAt"],
        "createdAt": item["createdAt"],
        "updatedAt": item["updatedAt"],
        "usedOn": [
            {
                "applicationId": row["applicationId"],
                "jobId": row["jobId"],
                "questionAsSeen": row["questionAsSeen"],
                "matchConfidence": row["matchConfidence"],
                "matchMethod": row["matchMethod"],
                "usedAt": row["usedAt"],
            }
            for row in usage
        ],
    }


@router.get("/questionnaire")
def get_questionnaire(current_user: CurrentUser) -> dict[str, Any]:
    """The onboarding question set, and which of the user's answers exist.

    Returns the questions with NO answers attached. ``answered`` reports which
    concepts the user has already banked, so the UI can show progress without
    the server ever handing back a suggested response.
    """
    items = AnswerBankRepository().list_for_user(current_user["id"])
    answered = {
        concept_of(str(item["semanticKey"]))
        for item in items
        if concept_of(str(item["semanticKey"]))
    }
    return {
        "questions": seed_question_payload(),
        "answeredConcepts": sorted(answered),
        "autoAnswerThreshold": AUTO_ANSWER_CONFIDENCE,
    }


@router.post("/questionnaire")
def submit_questionnaire(
    body: QuestionnaireRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Bank the questionnaire answers the user actually filled in.

    A blank answer is SKIPPED, not rejected: leaving a question for later (or
    for a per-application decision) is a legitimate answer to a questionnaire,
    and failing the whole request over one would punish it.
    """
    repo = AnswerBankRepository()
    user_id = current_user["id"]
    banked: list[dict[str, Any]] = []
    for entry in body.answers:
        item = repo.upsert(
            user_id,
            question=entry.question,
            answer=entry.answer,
            provenance="onboarding",
        )
        if item is not None:
            banked.append(item)
    return {
        "banked": len(banked),
        "skipped": len(body.answers) - len(banked),
        "items": [_view(item, []) for item in banked],
        "detail": (
            f"Saved {len(banked)} answer{'' if len(banked) == 1 else 's'} to your "
            "Answer Bank. Aether sends them exactly as you wrote them, and asks "
            "you again for anything it has no answer for."
        ),
    }


@router.get("/readiness")
def get_readiness(current_user: CurrentUser) -> dict[str, Any]:
    """Set-up state and the measured output of the learning loop.

    This is what the Settings panel and the first-run prompt read to tell the
    user how far their agent can already act on its own. Every field is a count
    of rows that exist — see :func:`app.services.answer_bank.readiness_summary`
    for why there is no single blended "autonomy score".

    ``applicationsWaiting`` is the one figure not derived from the bank: the
    number of this user's applications standing on an unanswered screening
    question right now. It is the actionable half of the story — a user whose
    bank is thin needs to know the agent is *currently* stopped, not just that
    coverage is incomplete.

    Registered ahead of no catch-all, but kept above ``GET ""``'s neighbours
    for readability. ``/questionnaire`` and ``/readiness`` are both literal
    segments, so neither can be swallowed by ``/{item_id}`` (which is only
    reachable via PATCH/DELETE/expire).
    """
    items = AnswerBankRepository().list_for_user(current_user["id"])
    summary = readiness_summary(items)
    summary["autoAnswerThreshold"] = AUTO_ANSWER_CONFIDENCE

    ensure_application_manual_step_question_column()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) AS cnt FROM "Application" '
                'WHERE "userId" = %s AND "manualStepQuestions" IS NOT NULL',
                (current_user["id"],),
            )
            rows = rows_to_dicts(cur)
    summary["applicationsWaiting"] = int(rows[0]["cnt"]) if rows else 0
    return summary


@router.get("")
def list_bank(current_user: CurrentUser) -> dict[str, Any]:
    """Every banked answer, with where each one was actually used."""
    repo = AnswerBankRepository()
    items = repo.list_for_user(current_user["id"])
    usage = repo.usage_for_items(current_user["id"], [item["id"] for item in items])
    return {
        "items": [_view(item, usage.get(item["id"], [])) for item in items],
        "autoAnswerThreshold": AUTO_ANSWER_CONFIDENCE,
    }


@router.post("")
def bank_answer(body: BankAnswerRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Add (or replace) one answer by hand from the Answer Bank page."""
    item = AnswerBankRepository().upsert(
        current_user["id"],
        question=body.question,
        answer=body.answer,
        provenance="user_answered",
        scope=body.scope,
        scope_value=body.scope_value,
    )
    if item is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            (
                "A question and an answer are both required — Aether will not "
                "store a blank answer or send one to an employer."
            ),
        )
    return _view(item, [])


@router.patch("/{item_id}")
def update_item(
    item_id: str, body: UpdateItemRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Edit one answer, its scope, or its auto-answer switch.

    Switching auto-answering ON is honoured only for a non-sensitive item; for
    a sensitive one the response comes back with the switch still OFF and
    ``gateReason`` saying why, rather than silently ignoring the request.
    """
    repo = AnswerBankRepository()
    updated = repo.update(
        current_user["id"],
        item_id,
        answer=body.answer,
        scope=body.scope,
        scope_value=body.scope_value,
        auto_answer_opt_in=body.autoAnswerOptIn,
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That saved answer was not found.")
    usage = repo.usage_for_items(current_user["id"], [item_id])
    return _view(updated, usage.get(item_id, []))


@router.post("/{item_id}/expire")
def expire_item(item_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Retire an answer without erasing where it was used."""
    repo = AnswerBankRepository()
    expired = repo.expire(current_user["id"], item_id)
    if expired is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That saved answer was not found.")
    usage = repo.usage_for_items(current_user["id"], [item_id])
    return _view(expired, usage.get(item_id, []))


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: str, current_user: CurrentUser) -> Response:
    """Erase an answer and its usage audit."""
    if not AnswerBankRepository().delete(current_user["id"], item_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That saved answer was not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
