"""LLM form answers restates stored evidence and refuses invention."""
from __future__ import annotations

import pytest

from app.db import get_connection
from app.services.apply_form_grounding import (
    build_evidence_pack,
    build_form_llm_resolver,
    grounded_answer_from_model,
)


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
