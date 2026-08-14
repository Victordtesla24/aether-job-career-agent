"""U-STORY-1 step 3 — the cover letter must read the provenance-tagged corpus.

Discovery §2.3 gap 2 / AGENT-GRAPH.json edge ``svc.build_corpus_evidence ->
agent.coverLetter`` (``status: absent``): ``cover_letter_agent.py``'s import
block contains no ``evidence_corpus`` import — only ``tailor_agent.py:24``
imports ``build_corpus_evidence``. **A claim can therefore be citable in the
tailored résumé and rejected by the claim guard of the cover letter belonging
to the SAME application** — the two artifacts of one application disagree about
what the candidate is allowed to say.

This pins the symmetry: an ``EvidenceCorpusItem`` the candidate genuinely owns
(the same store the tailor already reads through the same door,
``build_corpus_evidence(user_id, jd)``) makes a claim cover-letter-citable.

Nothing is relaxed — the corpus is candidate-own, provenance-tagged evidence,
and the pin below proves a claim NO corpus item supports is still flagged.

Run under the shared test-DB lock::

    nice flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_ustory1_s3_cover_reads_evidence_corpus.py -p no:randomly -q
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents.cover_letter_agent import CoverLetterAgent
from app.repositories.evidence_corpus import EvidenceCorpusRepository
from app.services.llm_client import LLMClient
from app.services.resume_tailor import unsupported_claim_tokens

#: The ML-W23 live-repro posting: its responsibilities block names an artifact
#: the résumé never mentions, which is exactly the phrase channel the §9 claim
#: guard polices.
_JD_TITLE = "Program Manager, Security GRC"
_JD_BODY = (
    "Responsibilities Act as an information security subject matter expert "
    "during cross-functional audit engagements. Create and maintain a central "
    "repository of audit evidence artifacts required for compliance with SOC 2, "
    "PCI DSS, SOX and other global regulatory standards. Perform security risk "
    "and control assessments against common frameworks."
)

#: The résumé proves none of the audit-evidence-repository vocabulary.
_RESUME = (
    "Jordan Rivera. Senior engineer. I led 6 engineers on a payments platform "
    "in Python and PostgreSQL, improving throughput 40 percent."
)

#: The candidate's OWN provenance-tagged corpus item — the same store, the same
#: shape and the same door the tailoring agent already reads.
_CORPUS_ITEM: dict[str, Any] = {
    "id": "ustory1-s3-item-1",
    "claim": (
        "Built and maintained a central repository of audit evidence artifacts "
        "for the compliance program, covering SOC 2 and PCI DSS control "
        "evidence."
    ),
    "category": "experience",
    "source": "resume_baseline",
    "sourceUrl": "https://example.invalid/baseline",
    "stated_or_inferred": "stated",
    "confidence": "high",
}

#: A first-person claim to exactly what the corpus item evidences.
_CLAIM_BODY = (
    "My experience building and maintaining a central repository of audit "
    "evidence artifacts maps directly onto this role's compliance "
    "obligations.\n\n"
    "I would welcome the opportunity to discuss this work with your team."
)

_USER_ID = "ustory1-s3-user"


class _NoStories:
    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        return []


class _ClaimVerdict(RuntimeError):
    def __init__(self, flagged: list[str], evidence: str) -> None:
        super().__init__("claim-guard verdict captured")
        self.flagged = flagged
        self.evidence = evidence


class _FakeJobs:
    def get_by_id(self, job_id, user_id):  # noqa: ANN001
        return {
            "id": job_id,
            "title": _JD_TITLE,
            "company": "Northwind Compliance",
            "description": _JD_BODY,
        }


class _FakeUsers:
    def get_by_id(self, user_id):  # noqa: ANN001
        return {"name": "Jordan Rivera"}

    def get_target_role(self, user_id):  # noqa: ANN001
        return None


class _StubLLM(LLMClient):
    def __init__(self, body: str) -> None:
        super().__init__(mode="auto")
        self._body = body

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        return {"hook_reason": "", "body": self._body}


@pytest.fixture
def seeded_corpus():
    """One real ``EvidenceCorpusItem`` row, removed again afterwards.

    The table is additive and FK-free (see ``repositories/evidence_corpus.py``),
    so this seeds and cleans up without touching the shared truncation
    fixtures.
    """
    repo = EvidenceCorpusRepository()
    repo.upsert_many(_USER_ID, [_CORPUS_ITEM])
    yield repo
    repo.delete_sources(_USER_ID, ["resume_baseline"])


def _run_and_capture(monkeypatch: Any, body: str, user_id: str) -> _ClaimVerdict:
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.build_career_corpus", lambda uid: ""
    )
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.require_user_resume_text",
        lambda uid, message: _RESUME,
    )

    def _spy(text, evidence, jd_risk_terms, jd_body=""):  # noqa: ANN001
        raise _ClaimVerdict(
            unsupported_claim_tokens(text, evidence, jd_risk_terms, jd_body), evidence
        )

    monkeypatch.setattr(
        "app.agents.cover_letter_agent.unsupported_claim_tokens", _spy
    )
    agent = CoverLetterAgent(
        llm=_StubLLM(body), jobs=_FakeJobs(), users=_FakeUsers(), stories=_NoStories()
    )
    with pytest.raises(_ClaimVerdict) as excinfo:
        agent.run(user_id, "job-1")
    return excinfo.value


def test_a_corpus_evidenced_claim_is_cover_letter_citable(
    monkeypatch: Any, seeded_corpus
) -> None:
    """The claim the tailor can already cite must not be rejected by the cover
    letter of the same application."""
    verdict = _run_and_capture(monkeypatch, _CLAIM_BODY, _USER_ID)
    assert verdict.flagged == [], verdict.flagged
    assert "audit evidence artifacts" in verdict.evidence, (
        "corpus evidence never reached the cover letter's claim corpus"
    )


def test_the_same_claim_is_still_flagged_without_a_corpus(monkeypatch: Any) -> None:
    """The pin: for a user whose corpus is empty (every self-serve account
    today) behaviour is byte-identical to before — the unevidenced
    re-labelling is still caught."""
    verdict = _run_and_capture(monkeypatch, _CLAIM_BODY, "ustory1-s3-user-no-corpus")
    assert verdict.flagged, verdict.flagged


# ---------------------------------------------------------------------------
# The corpus must reach BOTH guards. Feeding it to the claim guard alone would
# recreate the §2.2 asymmetry step 2 just closed, wearing a different source
# label: an entity the corpus evidences would pass the claim check and then be
# flagged by FabricationGuard as an unsupported entity.
# ---------------------------------------------------------------------------


class _GuardVerdict(RuntimeError):
    def __init__(self, flagged: list[str], corpus: str) -> None:
        super().__init__("guard verdict captured")
        self.flagged = flagged
        self.corpus = corpus


def _run_and_capture_guard(monkeypatch: Any, body: str, user_id: str) -> _GuardVerdict:
    from app.services.fabrication_guard import FabricationGuard

    class _CapturingGuard(FabricationGuard):
        def check(self, generated: str, evidence_corpus: str) -> list[str]:
            raise _GuardVerdict(
                super().check(generated, evidence_corpus), evidence_corpus
            )

    monkeypatch.setattr(
        "app.agents.cover_letter_agent.build_career_corpus", lambda uid: ""
    )
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.require_user_resume_text",
        lambda uid, message: _RESUME,
    )
    agent = CoverLetterAgent(
        llm=_StubLLM(body),
        jobs=_FakeJobs(),
        users=_FakeUsers(),
        stories=_NoStories(),
        guard=_CapturingGuard(),
    )
    with pytest.raises(_GuardVerdict) as excinfo:
        agent.run(user_id, "job-1")
    return excinfo.value


#: A capitalised entity evidenced ONLY by a corpus item — the FabricationGuard's
#: unit of adjudication.
_ENTITY_ITEM: dict[str, Any] = {
    "id": "ustory1-s3-item-2",
    "claim": "Led the Kookaburra control-assessment programme end to end.",
    "category": "experience",
    "source": "resume_baseline",
    "stated_or_inferred": "stated",
    "confidence": "high",
}

_ENTITY_BODY = (
    "I led the Kookaburra control-assessment programme end to end.\n\n"
    "I would welcome the opportunity to discuss this work with your team."
)


def test_a_corpus_evidenced_entity_is_not_fabrication_flagged(
    monkeypatch: Any,
) -> None:
    repo = EvidenceCorpusRepository()
    user_id = "ustory1-s3-entity-user"
    repo.upsert_many(user_id, [_ENTITY_ITEM])
    try:
        verdict = _run_and_capture_guard(monkeypatch, _ENTITY_BODY, user_id)
        assert "Kookaburra" not in verdict.flagged, verdict.flagged
    finally:
        repo.delete_sources(user_id, ["resume_baseline"])


def test_the_same_entity_is_still_flagged_without_a_corpus(monkeypatch: Any) -> None:
    verdict = _run_and_capture_guard(
        monkeypatch, _ENTITY_BODY, "ustory1-s3-entity-user-no-corpus"
    )
    assert "Kookaburra" in verdict.flagged, verdict.flagged
