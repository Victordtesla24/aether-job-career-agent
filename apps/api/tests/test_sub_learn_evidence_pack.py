"""Wave A (Submission Learn — WAVE-0-RECON §3/§4/§5): the evidence pack and
the LLM form-fill resolver must include the Evidence Corpus (GitHub repo /
portfolio claims, each tagged stated-or-inferred with a confidence note and
an exact source URL) and career-data claims, so ``apply_form`` can ground an
answer in a fact that is clearly and certainly on the candidate's GitHub,
portfolio, LinkedIn export, or résumé — not just in profile fields, the Story
Bank, the Answer Bank, or the cover letter.

Today ``build_evidence_pack`` has no ``corpus_items`` parameter and
``build_form_llm_resolver`` never reads ``EvidenceCorpusRepository`` or
``CareerProfileRepository`` at all (WAVE-0-RECON.md §3, §8). Every test below
is written to FAIL against that state — a corpus item passed in either
raises ``TypeError`` (no such parameter) or is silently absent from the
evidence text the completer receives. None of these tests implement the
fix; they pin the target behaviour so a real fix turns them green.

No embeddings. No second bank. No LinkedIn scraping — the corpus rows here
only ever carry sources honestly reachable per D-0031 (github, portfolio,
linkedin_export).
"""
from __future__ import annotations

import pytest

from app.db import get_connection
from app.services.apply_form_grounding import (
    build_evidence_pack,
    build_form_llm_resolver,
    grounded_answer_from_model,
)

PROFILE = {
    "name": "Vikram Deshpande",
    "email": "sarkar.vikram@gmail.com",
    "location": "Melbourne VIC",
}

GITHUB_REPO_URL = "https://github.com/vikramd/distributed-queue"


@pytest.fixture()
def user_id(client, auth_headers) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "id" FROM "User" LIMIT 1')
            return cur.fetchone()[0]


def _stated_high_confidence_github_item() -> dict[str, object]:
    """A corpus row exactly as ``EvidenceCorpusRepository.list_by_user`` would
    return it (WAVE-0-RECON §4): a GitHub claim, explicitly STATED in the
    source, HIGH confidence, with a real-looking repo URL."""
    return {
        "claim": "Authored a Python service processing 2 million events per day",
        "category": "project",
        "source": "github",
        "sourceUrl": GITHUB_REPO_URL,
        "statedOrInferred": "stated",
        "confidence": "high",
        "note": None,
    }


# ---------------------------------------------------------------------------
# ADV-DERIVE — build_evidence_pack must carry corpus items the model can cite
# ---------------------------------------------------------------------------


def test_evidence_pack_includes_stated_high_confidence_github_corpus_item():
    """A GitHub corpus claim (Python, stated, high confidence, real repo URL)
    must appear verbatim in the evidence pack text so the form-fill LLM can
    cite it. ``build_evidence_pack`` has no ``corpus_items`` parameter today
    (apply_form_grounding.py:44-50) — this call must fail with a
    ``TypeError`` until Wave A adds it, not merely produce a pack missing the
    claim."""
    pack = build_evidence_pack(
        PROFILE,
        corpus_items=[_stated_high_confidence_github_item()],
    )
    assert "Python" in pack
    assert "stated" in pack.lower()
    assert "github" in pack.lower()
    assert GITHUB_REPO_URL in pack


# ---------------------------------------------------------------------------
# ADV-WEAK — inferred + low confidence must not be enough to auto-answer
# ---------------------------------------------------------------------------


def _stated_or_high_inferred_completer(question: str, evidence: str) -> dict[str, object]:
    """Mirrors the honesty floor Wave A must enforce: a fact may only be
    restated if the evidence marks it "stated", or "inferred" AND "high"
    confidence together. An inferred + low-confidence mention is not enough,
    matching WAVE-0-RECON §6's entailment-not-vibes rule."""
    lowered = evidence.lower()
    if "kubernetes" not in lowered:
        return {"refuse": True, "answer": None, "source": ""}
    stated = "stated" in lowered
    inferred_high = "inferred" in lowered and "high" in lowered
    if stated or inferred_high:
        return {"refuse": False, "answer": "Yes", "source": "corpus"}
    return {"refuse": True, "answer": None, "source": ""}


def test_inferred_low_confidence_tool_mention_does_not_ground_an_answer():
    """A corpus item that only INFERS Kubernetes exposure (from a dependency
    file, say) at LOW confidence must not let the completer answer "Have you
    used Kubernetes?" — only stated facts, or high-confidence inferences, may
    be restated. Fails today because ``build_evidence_pack`` rejects
    ``corpus_items`` outright (TypeError), so this pins the target contract
    once the parameter exists."""
    corpus_items = [
        {
            "claim": "May have Kubernetes exposure based on a repo dependency file",
            "category": "skill",
            "source": "github",
            "sourceUrl": "https://github.com/vikramd/infra-tools",
            "statedOrInferred": "inferred",
            "confidence": "low",
            "note": "dependency-file heuristic, not a direct claim",
        }
    ]
    evidence = build_evidence_pack(PROFILE, corpus_items=corpus_items)

    field = {
        "name": "used_k8s",
        "label": "Have you used Kubernetes?",
        "kind": "select",
        "required": True,
        "options": ["Yes", "No"],
    }

    answer = grounded_answer_from_model(
        field, evidence=evidence, completer=_stated_or_high_inferred_completer
    )
    assert answer is None, (
        "an inferred + low-confidence corpus mention must never be enough to "
        f"auto-answer a form question, got {answer!r}"
    )


# ---------------------------------------------------------------------------
# ADV-SENSITIVE — the sensitivity gate still wins even with corpus evidence
# ---------------------------------------------------------------------------


def test_sensitive_visa_field_unanswered_even_with_stated_high_confidence_corpus_fact(
    user_id, monkeypatch
):
    """Even when the evidence corpus AND career data contain a stated,
    high-confidence work-rights claim, a visa/sponsorship field must stay
    unanswered — the sensitivity gate in ``grounded_answer_from_model`` runs
    BEFORE any completer call, corpus or not. This also proves Wave A wiring
    actually consults the corpus repository (``EvidenceCorpusRepository
    .list_by_user`` must be called at least once by
    ``build_form_llm_resolver`` on user_id) — today it is never called, so
    the call-count assertion fails first."""
    calls = {"list_by_user": 0, "completer": 0}

    def fake_list_by_user(self, uid: str):
        calls["list_by_user"] += 1
        assert uid == user_id
        return [
            {
                "claim": "Holds unrestricted work rights and needs no visa sponsorship",
                "category": "credential",
                "source": "linkedin_export",
                "sourceUrl": "",
                "statedOrInferred": "stated",
                "confidence": "high",
                "note": None,
            }
        ]

    monkeypatch.setattr(
        "app.repositories.evidence_corpus.EvidenceCorpusRepository.list_by_user",
        fake_list_by_user,
    )

    def completer(question: str, evidence: str):
        calls["completer"] += 1
        return {"refuse": False, "answer": "No", "source": "invented"}

    resolver = build_form_llm_resolver(
        user_id,
        dict(PROFILE),
        company="Acme",
        completer=completer,
    )
    field = {
        "name": "visa_sponsorship",
        "label": "Will you require visa sponsorship to work in Australia?",
        "kind": "select",
        "required": True,
        "options": ["Yes", "No"],
    }

    assert resolver(field) is None
    assert calls["completer"] == 0, "a sensitive field must never reach the completer"
    assert calls["list_by_user"] >= 1, (
        "build_form_llm_resolver must read the evidence corpus for this user "
        "(Wave A wiring) even though this particular field is sensitive and "
        "will refuse before the completer runs"
    )


# ---------------------------------------------------------------------------
# build_form_llm_resolver wiring — corpus + career data reach the completer
# ---------------------------------------------------------------------------


def test_form_llm_resolver_puts_corpus_and_career_data_claims_into_evidence(
    user_id, monkeypatch
):
    """``build_form_llm_resolver`` must assemble evidence from the Evidence
    Corpus (``EvidenceCorpusRepository.list_by_user``) and career data
    (``CareerProfileRepository.list_by_user``) — not just profile/stories/
    answer-bank — so the completer actually receives the GitHub repo claim
    and the career-data summary text. Fails today: neither repository is
    read by ``build_form_llm_resolver``, so the monkeypatched fakes below are
    never invoked and none of their content reaches the completer."""
    monkeypatch.setattr(
        "app.repositories.evidence_corpus.EvidenceCorpusRepository.list_by_user",
        lambda self, uid: [_stated_high_confidence_github_item()],
    )
    monkeypatch.setattr(
        "app.repositories.career_profile.CareerProfileRepository.list_by_user",
        lambda self, uid: [
            {
                "userId": uid,
                "source": "github",
                "status": "ok",
                "url": "https://github.com/vikramd",
                "content": {},
                "summary": "Primary languages: Python, Go, TypeScript.",
                "error": None,
                "syncedAt": None,
            }
        ],
    )

    seen: dict[str, str] = {}

    def completer(question: str, evidence: str):
        seen["evidence"] = evidence
        return {"refuse": True, "answer": None, "source": ""}

    resolver = build_form_llm_resolver(
        user_id,
        dict(PROFILE),
        company="Acme",
        completer=completer,
    )
    field = {
        "name": "python_experience",
        "label": "Describe your experience with Python",
        "kind": "textarea",
        "required": True,
        "options": [],
    }
    resolver(field)

    assert "evidence" in seen, "the completer must have been invoked"
    evidence_text = seen["evidence"]
    assert "distributed-queue" in evidence_text
    assert GITHUB_REPO_URL in evidence_text
    assert "stated" in evidence_text.lower()
    assert "Python" in evidence_text
