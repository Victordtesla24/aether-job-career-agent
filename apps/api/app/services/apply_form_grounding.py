"""Grounded LLM answers for employer form questions the profile/bank cannot fill.

The honesty floor does not move: the model may ONLY restate facts already in
the candidate's stored profile, Answer Bank, Story Bank or cover letter. A
sensitive question (visa specifics, salary, pronouns as a disclosure, health,
criminal) is never sent to the model. A refuse or an ungrounded answer is
treated as no answer — the executor raises the existing unknown-required
manual step rather than inventing.

Production uses ``LLMClient.complete_json`` with prompt class ``apply_form``
against the live provider keys. Tests inject a completer; they never hit the
network. Replay ``AETHER_LLM_MODE`` returns ``None`` from the default builder
so the pytest suite cannot accidentally spend or invent.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from app.services.answer_bank import (
    SENSITIVITY_SENSITIVE,
    classify_sensitivity,
    question_text_for_field,
)
from app.services.llm_client import LLMUnavailableError, QuotaExhaustedError

logger = logging.getLogger(__name__)

APPLY_FORM_PROMPT = "apply_form"

APPLY_FORM_SYSTEM = (
    "You answer ONE employer application question using ONLY the candidate's "
    "stored evidence. Return JSON with keys answer (string or null), refuse "
    "(boolean) and source (string). If the evidence does not contain a direct "
    "answer, refuse is true and answer is null. Never invent visa, sponsorship, "
    "salary, pronouns, disability, criminal or medical facts. Never guess. "
    "Australian English. No exclamation marks."
)

_SKIP_KINDS = frozenset({"file", "hidden"})


def build_evidence_pack(
    profile: dict[str, Any],
    *,
    stories: str = "",
    answer_bank_items: list[dict[str, Any]] | None = None,
    cover_letter: str = "",
) -> str:
    """Plain-text evidence the model is allowed to read. Nothing invented."""
    parts: list[str] = ["PROFILE"]
    for key in (
        "name",
        "firstName",
        "lastName",
        "email",
        "phone",
        "location",
        "country",
        "linkedin",
        "github",
        "website",
        "hearAbout",
    ):
        value = str((profile or {}).get(key) or "").strip()
        if value:
            parts.append(f"{key}: {value}")
    custom = (profile or {}).get("customAnswers")
    if isinstance(custom, dict):
        for key, value in custom.items():
            text = str(value or "").strip()
            if text:
                parts.append(f"custom {key}: {text}")
    screening = (profile or {}).get("screeningAnswers")
    if isinstance(screening, dict):
        for key, value in screening.items():
            text = str(value or "").strip()
            if text:
                parts.append(f"screening {key}: {text}")
    if cover_letter.strip():
        parts.append("COVER LETTER")
        parts.append(cover_letter.strip()[:4000])
    if stories.strip():
        parts.append("STORY BANK")
        parts.append(stories.strip()[:6000])
    if answer_bank_items:
        parts.append("ANSWER BANK")
        for item in answer_bank_items:
            question = str(item.get("questionText") or "").strip()
            answer = str(item.get("answer") or "").strip()
            sensitivity = str(item.get("sensitivity") or "")
            if not question or not answer:
                continue
            if sensitivity == SENSITIVITY_SENSITIVE:
                continue
            parts.append(f"Q: {question}\nA: {answer}")
    return "\n".join(parts)


def _parse_model_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def grounded_answer_from_model(
    field: dict[str, Any],
    *,
    evidence: str,
    completer: Callable[[str, str], Any],
) -> str | None:
    """Return a stored-evidence answer, or None when the model must refuse."""
    if (field.get("kind") or "") in _SKIP_KINDS:
        return None
    asked = question_text_for_field(field)
    if not asked.strip():
        return None
    if classify_sensitivity(asked) == SENSITIVITY_SENSITIVE:
        return None
    if not (evidence or "").strip():
        return None
    try:
        raw = completer(asked, evidence)
    except (QuotaExhaustedError, LLMUnavailableError):
        # A live-provider outage is NOT "the model looked and found nothing" —
        # collapsing the two into the same None the honest refusal returns
        # would park the application on unknown_required_question (a human
        # must answer this) for a question the LLM never actually evaluated.
        # Let the caller (build_form_fill_plan) turn this into a retryable
        # manual step instead.
        raise
    except Exception as exc:  # noqa: BLE001 — an unclassified miss is "no answer"
        logger.info(
            "apply-form-grounding: completer failed (%s) — refusing to invent",
            type(exc).__name__,
        )
        return None
    payload = _parse_model_payload(raw)
    if payload is None:
        return None
    if payload.get("refuse") is True:
        return None
    answer = payload.get("answer")
    if not isinstance(answer, str):
        return None
    text = answer.strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    return text[:2000]


def _live_completer(question: str, evidence: str) -> Any:
    from app.services.llm_client import LLMClient

    client = LLMClient()
    if client.mode == "replay":
        return {"refuse": True, "answer": None, "source": "replay"}
    user = (
        f"Question: {question}\n\nEvidence:\n{evidence}\n\n"
        "JSON only."
    )
    return client.complete_json(APPLY_FORM_PROMPT, APPLY_FORM_SYSTEM, user)


def build_form_llm_resolver(
    user_id: str,
    profile: dict[str, Any],
    *,
    company: str | None = None,
    completer: Callable[[str, str], Any] | None = None,
) -> Callable[[dict[str, Any]], str | None]:
    """A ``field -> answer | None`` callable for :func:`build_form_fill_plan`."""
    stories = ""
    items: list[dict[str, Any]] = []
    try:
        from app.agents.tailor_agent import build_story_evidence

        stories = build_story_evidence(user_id) or ""
    except Exception as exc:  # noqa: BLE001 — missing stories are not a failure
        logger.info("apply-form-grounding: story bank unread (%s)", type(exc).__name__)
    try:
        from app.repositories.answer_bank import AnswerBankRepository

        items = AnswerBankRepository().list_for_user(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.info("apply-form-grounding: answer bank unread (%s)", type(exc).__name__)
    cover = str((profile or {}).get("coverLetter") or "")
    evidence = build_evidence_pack(
        profile,
        stories=stories,
        answer_bank_items=items,
        cover_letter=cover,
    )
    if company:
        evidence = f"Employer: {company}\n{evidence}"
    fn = completer or _live_completer

    def resolve(field: dict[str, Any]) -> str | None:
        return grounded_answer_from_model(field, evidence=evidence, completer=fn)

    return resolve
