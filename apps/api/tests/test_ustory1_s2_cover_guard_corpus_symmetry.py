"""U-STORY-1 step 2 — the cover letter's FabricationGuard corpus must include
the Story Bank.

Discovery §2.2 (``U-STORY-DISCOVERY.md``) found the cover-letter agent building
TWO different evidence corpora from the same candidate:

* ``cover_letter_agent.py:1548-1550`` — the ``FabricationGuard`` corpus:
  résumé + title + company + sanitized description + date + signer + position
  (+ career corpus). **No story evidence.**
* ``cover_letter_agent.py:1557-1563`` — the §9 claim corpus: résumé + career +
  **story evidence** + signer + position + company.

So a system name, an employer or a number that only the Story Bank evidences
passes the §9 unsupported-claim check and is then flagged by
``FabricationGuard.check`` as an unsupported entity — the candidate's own true,
stored achievement reads as a fabrication. That is the most likely source of
"the guard rejected a true claim" cover-letter failures on accounts with a rich
Story Bank.

The fix is a strict WIDENING of the corpus with candidate-own evidence that the
neighbouring claim guard already trusts. No guard is relaxed: an entity that
NOTHING in the résumé, the career corpus or the Story Bank supports is still
flagged exactly as before — pinned below.

Run under the shared test-DB lock::

    nice flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_ustory1_s2_cover_guard_corpus_symmetry.py -p no:randomly -q
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents.cover_letter_agent import CoverLetterAgent
from app.services.fabrication_guard import FabricationGuard
from app.services.llm_client import LLMClient

_JD = (
    "Platform Engineer at Northwind Logistics. You will lead a platform "
    "migration off legacy virtual machines, own the deployment pipeline and "
    "improve release reliability for a distributed Python estate."
)

#: The résumé says nothing about Kookaburra — the ONLY evidence for it is the
#: stored story below. "Kookaburra" is a capitalised token, so
#: ``find_unsupported_entities`` flags it whenever it is absent from the corpus.
_RESUME = (
    "Jordan Rivera. Senior engineer. Led a platform migration in Python, "
    "owning the deployment pipeline and release reliability for a distributed "
    "estate."
)

_STORY: dict[str, Any] = {
    "id": "story-kookaburra",
    "title": "Kookaburra platform migration",
    "situation": "The legacy virtual machines behind the platform were fragile.",
    "task": "Lead the migration of the platform to a new deployment pipeline.",
    "action": "I rebuilt the Kookaburra deployment pipeline in Python.",
    "result": "Release reliability improved and the migration finished early.",
    "tags": ["platform", "migration"],
    "metrics": {},
}


class _StubStories:
    def __init__(self, stories: list[dict[str, Any]]) -> None:
        self._stories = stories

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        return list(self._stories)


class _GuardVerdict(RuntimeError):
    """Carries the REAL guard's verdict out of ``run()`` before persistence."""

    def __init__(self, flagged: list[str], corpus: str) -> None:
        super().__init__("guard verdict captured")
        self.flagged = flagged
        self.corpus = corpus


class _CapturingGuard(FabricationGuard):
    """The real guard, run on the real corpus ``run()`` assembles — then the
    verdict is raised out so no DB persistence is needed."""

    def check(self, generated: str, evidence_corpus: str) -> list[str]:
        raise _GuardVerdict(super().check(generated, evidence_corpus), evidence_corpus)


class _FakeJobs:
    def get_by_id(self, job_id, user_id):  # noqa: ANN001
        return {
            "id": job_id,
            "title": "Platform Engineer",
            "company": "Northwind Logistics",
            "description": _JD,
        }


class _FakeUsers:
    def get_by_id(self, user_id):  # noqa: ANN001
        return {"name": "Jordan Rivera"}

    def get_target_role(self, user_id):  # noqa: ANN001
        return None


def _draft_llm(body: str) -> LLMClient:
    class _StubLLM(LLMClient):
        def __init__(self) -> None:
            super().__init__(mode="auto")

        def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
            return {"hook_reason": "", "body": body}

    return _StubLLM()


def _run_and_capture(monkeypatch: Any, body: str, stories: list[dict[str, Any]]):
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.build_career_corpus", lambda uid: ""
    )
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.require_user_resume_text",
        lambda user_id, message: _RESUME,
    )
    agent = CoverLetterAgent(
        llm=_draft_llm(body),
        jobs=_FakeJobs(),
        users=_FakeUsers(),
        stories=_StubStories(stories),
        guard=_CapturingGuard(),
    )
    with pytest.raises(_GuardVerdict) as excinfo:
        agent.run("user-1", "job-1")
    return excinfo.value


_STORY_BACKED_BODY = (
    "I rebuilt the Kookaburra deployment pipeline in Python, leading the "
    "platform migration off legacy virtual machines and improving release "
    "reliability.\n\n"
    "I would welcome the chance to discuss this work with your team."
)


def test_a_story_evidenced_fact_is_not_guard_flagged(monkeypatch: Any) -> None:
    """The §2.2 asymmetry: a fact the Story Bank evidences (and the §9 claim
    guard already accepts) must not be reported as an unsupported entity."""
    verdict = _run_and_capture(monkeypatch, _STORY_BACKED_BODY, [_STORY])
    assert "Kookaburra" not in verdict.flagged, verdict.flagged
    assert "Kookaburra" in verdict.corpus, (
        "story evidence never reached the FabricationGuard corpus"
    )


def test_the_same_fact_is_still_flagged_without_the_story(monkeypatch: Any) -> None:
    """The pin proving this is a WIDENING, not a weakening: with an empty Story
    Bank the identical draft is still flagged exactly as before."""
    verdict = _run_and_capture(monkeypatch, _STORY_BACKED_BODY, [])
    assert "Kookaburra" in verdict.flagged, verdict.flagged


def test_an_entity_no_evidence_supports_is_still_flagged(monkeypatch: Any) -> None:
    """A claim NOTHING supports — not the résumé, not the posting, not the
    Story Bank — is still a fabrication with the widened corpus in place."""
    body = (
        "I rebuilt the Kookaburra deployment pipeline in Python and also led "
        "the Wallaby ledger rewrite for a different employer.\n\n"
        "I would welcome the chance to discuss this work with your team."
    )
    verdict = _run_and_capture(monkeypatch, body, [_STORY])
    assert "Wallaby" in verdict.flagged, verdict.flagged
