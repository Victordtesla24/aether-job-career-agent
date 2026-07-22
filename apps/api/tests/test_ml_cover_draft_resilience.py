"""cover _draft() resilience — failing test BEFORE fix (MODELS-LIVE §7 step 2).

RCA verified against CURRENT code (2026-07-22):
- ``CoverLetterAgent.run`` (apps/api/app/agents/cover_letter_agent.py:1182+)
  makes its FIRST ``self._draft(...)`` call at line 1290, OUTSIDE any
  try/except for ``LLMUnavailableError``. Only the CORRECTIVE-RETRY
  ``_draft()`` calls inside the ``for attempt in ("retry", "retry2")`` loop
  (line 1337) are wrapped in a try/except — and that except only catches
  ``LLMFixtureMissingError`` (a replay-mode fixture gap), never
  ``LLMUnavailableError``. A live-call failure on the very FIRST draft
  attempt therefore propagates straight out of ``run()`` uncaught: there is
  no agent-level graceful degrade for it. (The pipeline's own graceful
  degrade, agents.py:1558-1600, only catches FabricationError/StructuralError
  — an upstream LLMUnavailableError from the first draft attempt is a
  DIFFERENT, earlier failure mode it never sees.)

Target behaviour (not yet implemented): a ``LLMUnavailableError`` raised by
the FIRST ``_draft()`` call should degrade gracefully to an honest
``coverLetterUnavailable``-shaped outcome, not propagate as an unhandled
raise out of ``CoverLetterAgent.run()``.
"""
from __future__ import annotations

import pytest
from conftest import JORDAN_RESUME_TEXT, seed_own_resume

from app.agents.cover_letter_agent import CoverLetterAgent
from app.services.llm_client import LLMUnavailableError


class _FailFirstDraftLLM:
    """Raises LLMUnavailableError on every complete_json call — stands in for
    a live-call failure hitting the FIRST _draft() attempt."""

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *args, **kwargs):
        self.calls += 1
        raise LLMUnavailableError("simulated live failure on first draft attempt")


def _seed_job(client, auth_headers) -> dict:
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202, run.text
    jobs = client.get("/jobs", headers=auth_headers).json()
    assert jobs, "scout must have persisted at least one job to seed this test"
    return jobs[0]


class TestCoverDraftLLMUnavailableResilience:
    def test_first_draft_llm_unavailable_degrades_not_unhandled_raise(
        self, client, auth_headers, test_user_id
    ):
        """FAILS TODAY: ``CoverLetterAgent.run()`` lets the raw
        ``LLMUnavailableError`` from the first ``_draft()`` call propagate
        unhandled — this test explicitly fails the moment that happens
        instead of silently accepting it as a passing outcome."""
        seed_own_resume(client, auth_headers, raw_text=JORDAN_RESUME_TEXT)
        job = _seed_job(client, auth_headers)

        stub_llm = _FailFirstDraftLLM()
        agent = CoverLetterAgent(llm=stub_llm)

        try:
            result = agent.run(test_user_id, job["id"])
        except LLMUnavailableError:
            pytest.fail(
                "CoverLetterAgent.run() let a raw LLMUnavailableError from "
                "the FIRST _draft() call propagate unhandled -- it must "
                "degrade gracefully (an honest coverLetterUnavailable-shaped "
                "outcome) instead, mirroring the pipeline's own cover "
                "graceful-degrade handling (agents.py:1558-1600)."
            )

        # Once fixed: the agent should report an honest, non-fabricated
        # degraded outcome rather than a normal successful CoverLetterResult
        # (which would require a real generated letter that never happened).
        unavailable = getattr(result, "cover_letter_unavailable", None)
        if unavailable is None:
            unavailable = getattr(result, "coverLetterUnavailable", None)
        assert unavailable is True, (
            f"expected an honest coverLetterUnavailable degraded result, got {result!r}"
        )
        assert stub_llm.calls >= 1
