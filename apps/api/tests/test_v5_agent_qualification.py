"""v5 — job relevance is decided by the agent at run time, never hardcoded.

The old design let an adapter decide with a title regex. Measured live against
the real Adzuna AU feed (2026-08-02): 200 location-valid Melbourne postings ->
only 11 survived the regex, and the scoring engine never saw the other 189.

These tests pin the replacement contract:
  * adapters gate on LOCATION only (a fact about the world),
  * every applicable posting is scored for real against the real résumé,
  * the qualify/reject cut is DERIVED at run time from real data,
  * nothing is silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.discovery import qualification, relevance


@dataclass
class _Score:
    overall: float


class _StubEngine:
    """Deterministic stand-in for ATSEngine so the CONTRACT is under test, not
    the model. Scores by a marker in the posting text — never used in prod."""

    def __init__(self, mapping):
        self._mapping = mapping

    def score(self, resume_text: str, job_text: str) -> _Score:
        for marker, value in self._mapping.items():
            if marker in job_text:
                return _Score(value)
        return _Score(0.0)


def _job(title, location="Melbourne", **extra):
    base = {"title": title, "company": "Employer", "location": location, "remote": False,
            "description": title, "requirements": []}
    base.update(extra)
    return base


# --------------------------------------------------------------------------
# The regex must no longer decide anything
# --------------------------------------------------------------------------

def test_adapters_gate_on_location_only_not_on_title():
    """A Melbourne posting whose title matches no role regex must still reach
    qualification — that judgement belongs to the agent."""
    jobs = [
        _job("ICT Delivery Lead"),
        _job("Senior Manager | Change Management"),
        _job("Chief Vibes Officer"),
    ]
    assert len(relevance.filter_applicable(jobs)) == 3


def test_location_remains_a_hard_gate():
    """Not a heuristic: a Melbourne candidate cannot take an onsite Chicago role."""
    jobs = [_job("Project Manager", location="Chicago, IL"), _job("Project Manager")]
    kept = relevance.filter_applicable(jobs)
    assert [j["location"] for j in kept] == ["Melbourne"]


def test_title_region_lock_still_disqualifies_a_remote_posting():
    jobs = [_job("Engagement Manager - EMEA", location="Remote", remote=True)]
    assert relevance.filter_applicable(jobs) == []


def test_qualification_module_contains_no_hardcoded_relevance_rule():
    """Guard against the old design creeping back: no title regex, no keyword
    list, and no magic pass-mark constant in the decision path."""
    from pathlib import Path

    src = Path(qualification.__file__).read_text()
    body = src.split('"""', 2)[-1]  # ignore the explanatory module docstring
    assert "TARGET_ROLE_RE" not in body
    assert "is_target_role" not in body
    assert "fast_path" not in body
    # A compute budget is allowed; a relevance THRESHOLD constant is not.
    assert "FIT_FLOOR" not in body


# --------------------------------------------------------------------------
# The cut is derived from real data at run time
# --------------------------------------------------------------------------

def test_cut_comes_from_the_users_own_score_history():
    jobs = [_job("ROLE-ONE"), _job("ROLE-TWO"), _job("ROLE-THREE")]
    engine = _StubEngine({"ROLE-ONE": 80.0, "ROLE-TWO": 50.0, "ROLE-THREE": 10.0})
    history = [40.0, 60.0, 70.0, 30.0, 50.0]  # median 50.0

    res = qualification.qualify(jobs, resume_text="real resume", engine=engine,
                                history_scores=history)

    assert [j["title"] for j in res.qualified] == ["ROLE-ONE", "ROLE-TWO"]
    assert res.rejected == 1
    assert "existing board scores" in res.decision_basis
    assert "50.0" in res.decision_basis


def test_falls_back_to_this_sweeps_distribution_without_history():
    jobs = [_job("ROLE-ONE"), _job("ROLE-TWO"), _job("ROLE-THREE")]
    engine = _StubEngine({"ROLE-ONE": 90.0, "ROLE-TWO": 60.0, "ROLE-THREE": 30.0})

    res = qualification.qualify(jobs, resume_text="real resume", engine=engine,
                                history_scores=[])

    assert [j["title"] for j in res.qualified] == ["ROLE-ONE", "ROLE-TWO"]
    assert "this sweep" in res.decision_basis


def test_an_injected_agent_decider_overrides_the_default():
    """The whole point: a live agent can make the call instead of statistics."""

    class _AgentDecider:
        def decide(self, judged):
            for j in judged:
                j.qualified = "Delivery" in j.job["title"]
                j.reason = "agent judged role family"
            return "LLM agent judgement"

    jobs = [_job("Delivery Lead"), _job("Line Cook")]
    engine = _StubEngine({"Delivery Lead": 1.0, "Line Cook": 99.0})

    res = qualification.qualify(jobs, resume_text="r", engine=engine,
                                decider=_AgentDecider())

    # The agent's call beats the raw score — Line Cook scored 99 and still loses.
    assert [j["title"] for j in res.qualified] == ["Delivery Lead"]
    assert res.decision_basis == "LLM agent judgement"


# --------------------------------------------------------------------------
# Honesty: never claim a judgement that was not made
# --------------------------------------------------------------------------

def test_no_resume_means_unjudged_not_admitted_and_not_rejected():
    jobs = [_job("Project Manager"), _job("Line Cook")]
    res = qualification.qualify(jobs, resume_text="", engine=_StubEngine({}))
    assert res.qualified == []
    assert res.rejected == 0
    assert res.unjudged == 2
    assert "NOT JUDGED" in res.decision_basis


def test_budget_overflow_is_unjudged_never_rejected():
    jobs = [_job(f"Role {i}") for i in range(10)]
    engine = _StubEngine({f"Role {i}": float(i * 10) for i in range(10)})

    res = qualification.qualify(jobs, resume_text="r", engine=engine,
                                history_scores=[], budget=4)

    assert res.judged == 4
    assert res.unjudged == 6
    assert res.judged + res.unjudged == len(jobs)
    assert len(res.qualified) + res.rejected == res.judged


def test_a_scoring_failure_is_recorded_not_swallowed():
    class _Boom:
        def score(self, r, j):
            raise RuntimeError("model unavailable")

    res = qualification.qualify([_job("Project Manager")], resume_text="r", engine=_Boom())
    assert res.errors and "model unavailable" in res.errors[0]
    assert res.qualified == []


def test_the_real_computed_score_is_carried_forward_not_reinvented():
    jobs = [_job("ROLE-ONE")]
    res = qualification.qualify(jobs, resume_text="r", engine=_StubEngine({"ROLE-ONE": 77.5}),
                                history_scores=[10.0] * 5)
    assert res.qualified[0]["fitScore"] == 77.5
    assert res.qualified[0]["atsScore"] == 77.5
    assert "77.5" in res.qualified[0]["qualificationReason"]


@pytest.mark.parametrize("engine", [None])
def test_missing_engine_refuses_to_guess(engine):
    res = qualification.qualify([_job("Project Manager")], resume_text="r", engine=engine)
    assert res.unjudged == 1 and res.qualified == []
