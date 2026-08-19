"""LLM form answers restates stored evidence and refuses invention."""
from __future__ import annotations

import pytest

from app.db import get_connection
from app.services.apply_executor import (
    MANUAL_STEP_FORM_NOT_READY,
    RETRYABLE_MANUAL_REASONS,
    ManualStepRequired,
    build_form_fill_plan,
)
from app.services.apply_form_grounding import (
    build_evidence_pack,
    build_form_llm_resolver,
    grounded_answer_from_model,
)
from app.services.llm_client import LLMUnavailableError, QuotaExhaustedError


@pytest.fixture()
def user_id(client, auth_headers) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "id" FROM "User" LIMIT 1')
            return cur.fetchone()[0]


PROFILE = {
    "name": "Vikram Deshpande",
    "email": "sarkar.vikram@gmail.com",
    "location": "Melbourne VIC",
    "coverLetter": (
        "I want to join Dovetail because I have spent a decade on platform "
        "reliability for product-analytics teams."
    ),
}


def test_evidence_pack_carries_profile_stories_and_bank_not_sensitive_rows():
    pack = build_evidence_pack(
        PROFILE,
        stories="Reduced deploy time from 40 minutes to 8 minutes at NAB.",
        answer_bank_items=[
            {
                "questionText": "What is your notice period?",
                "answer": "Four weeks",
                "sensitivity": "factual",
            },
            {
                "questionText": "Do you need visa sponsorship?",
                "answer": "Yes",
                "sensitivity": "sensitive",
            },
        ],
        cover_letter=str(PROFILE["coverLetter"]),
    )
    assert "Vikram Deshpande" in pack
    assert "Four weeks" in pack
    assert "visa sponsorship" not in pack.lower()
    assert "40 minutes to 8 minutes" in pack
    assert "Dovetail" in pack


def test_grounded_completer_answer_is_used():
    field = {
        "name": "why_us",
        "label": "Why do you want to work here?",
        "kind": "textarea",
        "required": True,
        "options": [],
    }

    def completer(question: str, evidence: str):
        assert "Why do you want" in question
        assert "Dovetail" in evidence
        return {
            "refuse": False,
            "answer": "I have spent a decade on platform reliability for product-analytics teams.",
            "source": "cover letter",
        }

    answer = grounded_answer_from_model(
        field, evidence=build_evidence_pack(PROFILE, cover_letter=PROFILE["coverLetter"]),
        completer=completer,
    )
    assert answer is not None
    assert "platform reliability" in answer


def test_sensitive_question_never_reaches_the_completer():
    field = {
        "name": "sponsor",
        "label": "Will you require visa sponsorship to work in Australia?",
        "kind": "select",
        "required": True,
        "options": ["Yes", "No"],
    }
    calls = {"n": 0}

    def completer(question: str, evidence: str):
        calls["n"] += 1
        return {"refuse": False, "answer": "No", "source": "invented"}

    assert grounded_answer_from_model(field, evidence="citizen", completer=completer) is None
    assert calls["n"] == 0


def test_model_refuse_is_no_answer():
    field = {
        "name": "years_k8s",
        "label": "How many years of Kubernetes experience do you have?",
        "kind": "text",
        "required": True,
        "options": [],
    }

    def completer(question: str, evidence: str):
        return {"refuse": True, "answer": None, "source": ""}

    assert grounded_answer_from_model(field, evidence="PROFILE\nname: Vikram", completer=completer) is None


def test_completer_failure_is_no_answer_never_invented():
    field = {
        "name": "why_us",
        "label": "Why this role?",
        "kind": "textarea",
        "required": True,
        "options": [],
    }

    def completer(question: str, evidence: str):
        raise RuntimeError("provider 503")

    assert grounded_answer_from_model(field, evidence="cover letter here", completer=completer) is None


def test_completer_quota_exhausted_error_is_not_swallowed_into_no_answer():
    """Production, 2026-08-19T14:59Z, apply_sweep_user job
    882acebed50d406ea9c9078adb46e013: the live completer hit an Anthropic
    HTTP 429 (``QuotaExhaustedError``, prompt class ``apply_form``) and
    ``grounded_answer_from_model``'s broad ``except Exception`` swallowed it
    into the SAME ``None`` a genuine "no evidence for this" refusal returns.
    A transient LLM outage is not "the model looked and found nothing" —
    the two must stay distinguishable so the caller can retry the outage
    instead of parking the application on an honesty-floor manual step.
    """
    field = {
        "name": "notice_period",
        "label": "What is your notice period?",
        "kind": "text",
        "required": True,
        "options": [],
    }

    def completer(question: str, evidence: str):
        raise QuotaExhaustedError(
            "anthropic", reason="anthropic subscription quota exhausted"
        )

    with pytest.raises(QuotaExhaustedError):
        grounded_answer_from_model(
            field, evidence="PROFILE\nname: Vikram", completer=completer
        )


def test_completer_llm_unavailable_error_is_not_swallowed_into_no_answer():
    """Same outage-vs-refusal distinction as the 429 case above, for the
    other live-completer failure class the executor must recognise:
    ``LLMUnavailableError`` (live call failed with no fixture fallback)."""
    field = {
        "name": "notice_period",
        "label": "What is your notice period?",
        "kind": "text",
        "required": True,
        "options": [],
    }

    def completer(question: str, evidence: str):
        raise LLMUnavailableError("live call failed, no fixture fallback")

    with pytest.raises(LLMUnavailableError):
        grounded_answer_from_model(
            field, evidence="PROFILE\nname: Vikram", completer=completer
        )


def test_completer_generic_failure_still_no_answer_never_invented():
    """The honesty floor for an UNCLASSIFIED completer failure is unchanged
    by the fix above: only the two named outage classes
    (``QuotaExhaustedError``/``LLMUnavailableError``) are elevated past
    ``None``. Anything else stays "no answer" — never invented, and never
    silently promoted to a retryable outage it was not proven to be."""
    field = {
        "name": "notice_period",
        "label": "What is your notice period?",
        "kind": "text",
        "required": True,
        "options": [],
    }

    def completer(question: str, evidence: str):
        raise RuntimeError("some other completer bug")

    assert (
        grounded_answer_from_model(
            field, evidence="PROFILE\nname: Vikram", completer=completer
        )
        is None
    )


def test_form_llm_quota_exhausted_raises_retryable_manual_step_not_unknown_required_question(
    user_id,
):
    """Same production incident, exercised at the executor seam
    ``build_form_fill_plan`` actually calls: a 429 on the ONE required
    question the profile/answer-bank cannot answer must raise a RETRYABLE
    manual step (``form_not_ready`` — already in ``RETRYABLE_MANUAL_REASONS``
    for exactly this "try the site again" class), never
    ``unknown_required_question`` — that reason means "a human must answer
    this question", and a spent LLM quota is not that.
    """
    html = (
        '<div data-field-path="notice_period">'
        "<label>What is your notice period?</label>"
        '<input name="notice_period_input" required>'
        "</div>"
    )

    def raising_completer(question: str, evidence: str):
        raise QuotaExhaustedError(
            "anthropic", reason="anthropic subscription quota exhausted"
        )

    resolver = build_form_llm_resolver(
        user_id,
        {
            "name": "Jordan Blake",
            "email": "jordan.blake@example.com",
            "location": "Melbourne VIC",
        },
        company="Acme",
        completer=raising_completer,
    )

    with pytest.raises(ManualStepRequired) as exc:
        build_form_fill_plan(
            html,
            channel="ashby",
            profile={
                "name": "Jordan Blake",
                "email": "jordan.blake@example.com",
                "location": "Melbourne VIC",
            },
            form_llm=resolver,
        )
    assert exc.value.reason != "unknown_required_question", (
        "an LLM 429 outage must never be recorded as 'no stored answer for "
        f"this question' — got {exc.value.reason!r}"
    )
    assert exc.value.reason in RETRYABLE_MANUAL_REASONS
    assert exc.value.reason == MANUAL_STEP_FORM_NOT_READY


def test_sensitive_required_question_stays_unknown_required_question_when_llm_healthy(
    user_id,
):
    """The honesty floor must not move to fix the 429 case above: a
    sensitive required question (visa, pronouns, criminal, gender) is
    answered by asking the user, never by calling the model — and that must
    hold even while the LLM is completely healthy, so the 429 fix can never
    be implemented by widening what counts as "an LLM outage" to also cover
    a question the model was never allowed to see in the first place.

    Currently passes against unfixed code (the sensitivity gate already
    runs before any completer call) — kept as a locked contract so a fix
    for the 429 case cannot regress it.
    """
    calls = {"n": 0}

    def healthy_completer(question: str, evidence: str):
        calls["n"] += 1
        return {"refuse": False, "answer": "No", "source": "invented"}

    html = (
        '<div data-field-path="visa_sponsorship">'
        "<label>Will you require visa sponsorship to work in Australia?</label>"
        '<select name="visa_sponsorship_input" required>'
        "<option>Yes</option><option>No</option>"
        "</select>"
        "</div>"
    )
    resolver = build_form_llm_resolver(
        user_id,
        {"name": "Jordan Blake", "email": "jordan.blake@example.com"},
        company="Acme",
        completer=healthy_completer,
    )

    with pytest.raises(ManualStepRequired) as exc:
        build_form_fill_plan(
            html,
            channel="ashby",
            profile={"name": "Jordan Blake", "email": "jordan.blake@example.com"},
            form_llm=resolver,
        )
    assert exc.value.reason == "unknown_required_question"
    assert calls["n"] == 0, "a sensitive question must never reach the model, healthy or not"


def test_default_llm_resolver_never_reaches_the_live_client_in_replay_mode(
    user_id, monkeypatch
):
    """``build_form_llm_resolver`` with NO injected completer uses the real
    ``_live_completer``. In replay mode (the pytest default —
    ``AETHER_LLM_MODE`` is pinned to ``replay`` in ``conftest.py`` so the
    suite can never spend or invent) it must refuse WITHOUT ever calling
    ``LLMClient.complete_json`` — a fixture-less prompt returning ``None``
    for an unrelated reason (a missing fixture raising, then being
    swallowed by ``grounded_answer_from_model``'s broad except) would be a
    false pass of this guarantee, so the test proves the client was never
    invoked at all, not merely that the answer came back empty.
    """
    from app.services import llm_client as llm_client_module

    monkeypatch.setenv("AETHER_LLM_MODE", "replay")
    calls: list[str] = []

    def _spy_complete_json(self, prompt_name, system, user, **kwargs):
        calls.append(prompt_name)
        return {
            "answer": "An answer the model invented rather than restated.",
            "refuse": False,
            "source": "live",
        }

    monkeypatch.setattr(llm_client_module.LLMClient, "complete_json", _spy_complete_json)

    resolver = build_form_llm_resolver(
        user_id,
        {
            "name": "Vikram Deshpande",
            "email": "sarkar.vikram@gmail.com",
            "location": "Melbourne VIC",
        },
        company="Acme",
    )
    field = {
        "name": "why_us",
        "label": "Why do you want to work at Acme?",
        "kind": "textarea",
        "required": True,
        "options": [],
    }
    assert resolver(field) is None
    assert calls == [], "replay mode must never reach the live LLM client"
