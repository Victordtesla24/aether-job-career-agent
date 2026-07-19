"""GAP-P6-COV-002 — decouple the cover-letter/pipeline generation budget from the
tailoring-tuned global LLM budget.

Live E2E QA (uat/reports/evidence/phase6/qa-final-gates.json GATE-26 +
UAT-RESULTS-20260716-173502.json) re-reproduced a chronic HTTP 503 "LLM backend
unavailable" on cover-letter generation and the autonomous pipeline. ROOT CAUSE:
the GAP-P6-TAIL-005 redeploy lowered the GLOBAL ``AETHER_LLM_BUDGET_SECONDS`` to
65 so the tailoring GENERATION + its dedicated ENTAILMENT window fit under the
~100s HTTP edge. But the cover-letter path is a SINGLE long generation call with
NO entailment step, so 65s needlessly starves it (primary reasoning model fails,
faster fallback then runs out of budget) and the request 503s. The cover FEATURE
is sound (craft QA verified a real 62s, 78-craft, zero-fabrication letter) — this
is BUDGET STARVATION, not a logic bug.

FIX: a dedicated ``AETHER_LLM_COVER_BUDGET_SECONDS`` (default 88s) applied as a
fresh :func:`shared_budget` window around the cover generation — exactly mirroring
the GAP-P6-TAIL-004 dedicated entailment window. It DECOUPLES the cover generation
from the tailoring-constrained 65s: standalone cover (a single generation) gets
~88s (< the ~100s edge), and inside the pipeline the cover no longer inherits the
already-drained tailoring budget. Tailoring (prompt ``tailor`` +
``tailor_entailment``) is untouched. AUTH-002 is preserved: a genuine live failure
still raises an HONEST error (no fixture fallback) rather than a canned letter.
"""
from __future__ import annotations

import pytest

from app.agents.cover_letter_agent import CoverLetterAgent
from app.services import llm_client
from app.services.llm_client import LLMClient, LLMUnavailableError


class _StopProbe(RuntimeError):
    """Short-circuits ``CoverLetterAgent.run`` right after the first LLM call so
    the budget can be observed without exercising the DB-backed persistence tail."""


class _FakeJobs:
    def get_by_id(self, job_id, user_id):  # noqa: ANN001
        return {
            "id": job_id,
            "title": "Senior Engineer",
            "company": "Acme",
            "description": "Build resilient services with Python.",
        }


class _FakeUsers:
    def get_by_id(self, user_id):  # noqa: ANN001
        return {"name": "Test User"}

    def get_target_role(self, user_id):  # noqa: ANN001
        return None


class _FakeStories:
    pass


def _stub_evidence(monkeypatch) -> None:
    """Neutralise the DB-backed career/story evidence lookups run() performs
    before it reaches the LLM call under test."""
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.build_career_corpus", lambda uid: ""
    )
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.build_story_evidence",
        lambda uid, repo=None: "",
    )


class _CoverBudgetProbeLLM(LLMClient):
    """Records the wall-clock budget the cover generation call actually sees,
    then aborts the run so no DB persistence is needed."""

    def __init__(self) -> None:
        super().__init__(mode="auto")
        self.observed: dict[str, float] = {}

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        self.observed[prompt_name] = self._remaining_budget()
        raise _StopProbe()


# ===========================================================================
# (a) The cover generation budget is DECOUPLED from the tailoring 65s — inside
#     the pipeline's shared tailoring window it resolves to the larger cover
#     budget, not the 65 the tailoring path is tuned to.
# ===========================================================================


def test_cover_generation_budget_decoupled_from_tailoring_65(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_LLM_MODE", "auto")
    monkeypatch.setenv("AETHER_LLM_BUDGET_SECONDS", "65")  # the tailoring-tuned global
    monkeypatch.delenv("AETHER_LLM_COVER_BUDGET_SECONDS", raising=False)  # default 88
    _stub_evidence(monkeypatch)
    # DI-stub test using a fake user id ("user-1") that never goes through the
    # real API, so it has no résumé of its own on file. Stub the OUTBOUND
    # résumé-grounding lookup directly so the budget probe under test still
    # reaches the LLM call instead of short-circuiting on MissingResumeError.
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.require_user_resume_text",
        lambda user_id, message: "Senior engineer with Python and distributed systems experience.",
    )

    clock = {"t": 5000.0}
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: clock["t"])

    probe = _CoverBudgetProbeLLM()
    agent = CoverLetterAgent(
        llm=probe, jobs=_FakeJobs(), users=_FakeUsers(), stories=_FakeStories()
    )

    # Simulate the autonomous pipeline: the cover step runs INSIDE the shared
    # tailoring budget window (65s). Without decoupling the cover generation
    # inherits that already-tailoring-constrained 65s and starves -> 503.
    with llm_client.shared_budget(65):
        with pytest.raises(_StopProbe):
            agent.run("user-1", "job-1")

    # The fix: the cover generation gets its OWN ~88s window, NOT the 65s the
    # tailoring path is tuned to.
    assert probe.observed["cover_letter"] == pytest.approx(88.0), probe.observed
    assert probe.observed["cover_letter"] > 65.0


def test_cover_budget_env_default_and_floor(monkeypatch) -> None:
    monkeypatch.delenv("AETHER_LLM_COVER_BUDGET_SECONDS", raising=False)
    assert llm_client.get_cover_budget_seconds() == 88.0
    monkeypatch.setenv("AETHER_LLM_COVER_BUDGET_SECONDS", "not-a-number")
    assert llm_client.get_cover_budget_seconds() == 88.0
    monkeypatch.setenv("AETHER_LLM_COVER_BUDGET_SECONDS", "2")  # below the floor
    assert llm_client.get_cover_budget_seconds() == llm_client._MIN_ATTEMPT_SECONDS
    monkeypatch.setenv("AETHER_LLM_COVER_BUDGET_SECONDS", "85")
    assert llm_client.get_cover_budget_seconds() == pytest.approx(85.0)


def test_cover_budget_strictly_exceeds_tailoring_generation_budget(monkeypatch) -> None:
    """The whole point: with the tailoring-tuned 65s in effect, the cover path
    gets strictly MORE budget (it has no entailment reservation to leave room for)."""
    monkeypatch.setenv("AETHER_LLM_BUDGET_SECONDS", "65")
    monkeypatch.delenv("AETHER_LLM_COVER_BUDGET_SECONDS", raising=False)
    assert llm_client.get_cover_budget_seconds() > llm_client.get_budget_seconds()


# ===========================================================================
# (c) AUTH-002 preserved — a genuine live failure inside the cover window
#     raises an HONEST error; it is NEVER swallowed into a fixture fallback.
# ===========================================================================


def test_cover_run_raises_honest_error_no_fixture_fallback(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_LLM_MODE", "auto")
    _stub_evidence(monkeypatch)
    # DI-stub test using a fake user id ("user-1"); stub the résumé-grounding
    # lookup so the run reaches the LLM call the test is actually exercising.
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.require_user_resume_text",
        lambda user_id, message: "Senior engineer with Python and distributed systems experience.",
    )

    class _FailingLLM(LLMClient):
        def __init__(self) -> None:
            super().__init__(mode="auto")

        def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
            # Mirrors auto-mode's honest failure when the live retry chain is
            # exhausted — NOT a recorded fixture masqueraded as live output.
            raise LLMUnavailableError(
                f"LLM backend unavailable: live call failed for '{prompt_name}'"
            )

    agent = CoverLetterAgent(
        llm=_FailingLLM(), jobs=_FakeJobs(), users=_FakeUsers(), stories=_FakeStories()
    )
    with pytest.raises(LLMUnavailableError):
        agent.run("user-1", "job-1")
