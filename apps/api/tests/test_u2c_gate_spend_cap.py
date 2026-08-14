"""U2c — the quality gate cannot outspend the LLM budget it runs inside.

This slice turned two SINGLE-SHOT improvement attempts into BOUNDED LOOPS:

* ``cover_letter_agent.run`` previously fired at most ONE improvement pass,
  behind a one-time ``remaining_budget_seconds() >= _QUALITY_PASS_MIN_SECONDS``
  check (GAP-P6-COV-002 — firing a doomed call when the budget is already spent
  is the exact starvation that produced live 503s);
* ``TailoringLoop.run`` previously stopped at ``max_iterations``.

Turning a guarded single shot into a loop is precisely where a budget check
silently stops protecting anything: hoist it out of the loop body, or evaluate
it once before iterating, and the SECOND attempt fires into an exhausted budget
again. The iteration cap alone does not save it — the cap bounds the NUMBER of
calls, not whether the budget can still afford the next one.

So these tests pin the spend contract that the iteration-cap tests
(``test_u2c_quality_gate.py`` §2) deliberately do not cover:

1. The cover-letter gate re-checks the budget before EVERY pass, so a budget
   that drains mid-gate stops the loop rather than starving it.
2. A budget that is already spent buys ZERO gate passes — and the letter still
   ships carrying its honest below-floor verdict, never an inflated one.
3. On the résumé side the equivalent exhaustion arrives as
   ``LLMUnavailableError`` mid-gate-attempt: the run keeps the best guard-clean
   draft it actually achieved, reports the honest below-floor verdict, and
   never reports success.

The scorer is scripted in the cover-letter tests below: what is under test is
the BUDGET/loop contract, not ``score_cover_letter``'s arithmetic (pinned in
``test_cover_letter_quality.py``) nor the gate verdict (pinned in
``test_u2c_quality_gate.py``).

Run under the shared test-DB lock::

    nice flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_u2c_gate_spend_cap.py -p no:randomly -q
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents.cover_letter_agent import _QUALITY_PASS_MIN_SECONDS, CoverLetterAgent
from app.services.ats_engine import ATSScore
from app.services.cover_letter_quality import CoverLetterQuality
from app.services.llm_client import LLMClient, LLMUnavailableError
from app.services.resume_tailor import TailorResult

# ---------------------------------------------------------------------------
# Cover-letter harness
# ---------------------------------------------------------------------------

#: Grounded in the résumé below, with an explicit CTA — the shape the
#: structural/fabrication/claim guards already pass, so the gate loop is
#: genuinely reached instead of being short-circuited by a guard flag.
#:
#: TWO paragraphs, not three: ``compose_letter`` prepends the model's
#: ``hook_reason`` as the opening paragraph, and the §10.2 format contract
#: requires the assembled body to have exactly three.
_CLEAN_BODY = (
    "My recent work centres on owning sprint cadence, PI Planning, capacity "
    "management, and executive status reporting for multiple squads. I "
    "architected test-automation strategies that cut evidence effort from "
    "roughly 3 hours to about 15 minutes per scenario, and delivered analytics "
    "applications with Next.js and Supabase that expose sprint velocity "
    "metrics.\n\n"
    "I would welcome the opportunity to discuss how this experience can "
    "support your team, and I am available for an interview at your "
    "convenience."
)

_RESUME = (
    "Jordan Rivera\nDelivery Lead\n\n"
    "- Owned sprint cadence and PI Planning for delivery squads, plus capacity "
    "management and executive status reporting.\n"
    "- Ran test-automation strategies that cut evidence effort from roughly 3 "
    "hours to about 15 minutes per scenario.\n"
    "- Delivered analytics applications with Next.js and Supabase that expose "
    "sprint velocity metrics.\n"
)


def _below_floor_quality() -> CoverLetterQuality:
    """Clears the headline target, fails a MEASURED dimension.

    This is the exact shape that used to ship unflagged: ``reached_target`` is
    true, so the pre-U2c improvement pass never fired, while grounding sat far
    below the floor. ``missing_keywords`` is non-empty so the failure is
    genuinely CLOSABLE — an unmeasurable failure buys no attempts at all, which
    would make this test pass for the wrong reason.
    """
    return CoverLetterQuality(
        overall=88.0,
        jd_alignment=90.0,
        grounding=61.0,
        structure=100.0,
        reached_target=True,
        jd_alignment_measured=True,
        missing_keywords=["kafka"],
        unreachable_keywords=[],
    )


class _CountingLLM(LLMClient):
    """Returns the same clean draft every time and counts the paid calls."""

    def __init__(self) -> None:
        super().__init__(mode="auto")
        self.calls = 0

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        self.calls += 1
        return {
            "hook_reason": (
                "The emphasis this posting places on shipping reliable, "
                "measurable delivery outcomes is exactly the work I already do."
            ),
            "body": _CLEAN_BODY,
        }


class _FakeJobs:
    def get_by_id(self, job_id, user_id):  # noqa: ANN001
        return {
            "id": job_id,
            "title": "Delivery Lead",
            "company": "Northwind",
            "description": (
                "We need a delivery lead to own sprint cadence, PI Planning and "
                "capacity management across squads, with Kafka experience."
            ),
        }


class _FakeUsers:
    def get_by_id(self, user_id):  # noqa: ANN001
        return {"name": "Jordan Rivera"}

    def get_target_role(self, user_id):  # noqa: ANN001
        return None


class _NoStories:
    def list_by_user(self, user_id):  # noqa: ANN001
        return []


class _FakeTailor:
    def resume_for_job(self, user_id, job_id):  # noqa: ANN001
        return {
            "id": "resume-1",
            "sections": {"raw_text": _RESUME, "bullets": []},
        }


class _Captured(RuntimeError):
    """Short-circuits ``run`` at the seam where the gate loop has finished and
    the shipped quality record is assembled — the DB-backed persistence tail is
    irrelevant to the budget contract."""

    def __init__(self, kwargs: dict[str, Any]) -> None:
        super().__init__("gate loop finished")
        self.kwargs = kwargs


def _drive(monkeypatch: Any, budgets: list[float]) -> tuple[_Captured, _CountingLLM]:
    """Run the agent with ``remaining_budget_seconds`` scripted per call.

    The LAST value repeats once the script is exhausted, so a test only has to
    state the values it actually cares about.
    """
    module = "app.agents.cover_letter_agent"
    monkeypatch.setattr(f"{module}.build_career_corpus", lambda uid: "")
    monkeypatch.setattr(f"{module}.build_story_evidence", lambda *a, **k: "")
    monkeypatch.setattr(f"{module}.build_corpus_evidence", lambda *a, **k: "")
    monkeypatch.setattr(
        f"{module}.require_user_resume_text", lambda uid, message: _RESUME
    )
    monkeypatch.setattr(f"{module}.score_cover_letter", lambda *a, **k: _below_floor_quality())
    # Sits between the gate loop and the capture seam below: the draft résumé
    # the letter is filed against is DB-backed and has nothing to do with the
    # budget contract.
    monkeypatch.setattr(f"{module}.TailoringAgent", lambda *a, **k: _FakeTailor())

    reads: list[float] = []

    def _budget() -> float:
        value = budgets[min(len(reads), len(budgets) - 1)]
        reads.append(value)
        return value

    monkeypatch.setattr(f"{module}.remaining_budget_seconds", _budget)

    def _capture(**kwargs: Any) -> dict[str, Any]:
        raise _Captured(kwargs)

    monkeypatch.setattr(f"{module}.build_letter_quality", _capture)

    llm = _CountingLLM()
    agent = CoverLetterAgent(
        llm=llm, jobs=_FakeJobs(), users=_FakeUsers(), stories=_NoStories()
    )
    with pytest.raises(_Captured) as excinfo:
        agent.run("u2c-spend-cap-user", "job-1")
    return excinfo.value, llm


class TestTheCoverLetterGateRespectsTheBudgetEveryPass:
    def test_a_budget_that_drains_mid_gate_stops_the_loop(
        self, monkeypatch: Any
    ) -> None:
        """The loop-specific regression this slice could have introduced.

        The budget affords the FIRST gate pass and not the second. A check
        evaluated once before iterating — or hoisted out of the loop body —
        fires both, which is the GAP-P6-COV-002 starvation all over again.
        """
        ample = _QUALITY_PASS_MIN_SECONDS * 3
        spent = _QUALITY_PASS_MIN_SECONDS - 1.0
        captured, llm = _drive(monkeypatch, [ample, spent])

        assert captured.kwargs["gate_attempts_used"] == 1, (
            "the gate must re-check the budget before EVERY pass"
        )
        # One initial generation + exactly one affordable gate pass.
        assert llm.calls == 2

    def test_an_already_spent_budget_buys_no_passes_and_still_ships(
        self, monkeypatch: Any
    ) -> None:
        """Skipping is always safe: the clean letter ships and its HONEST score
        — gate verdict included — is what gets recorded. Never inflated to hide
        that no attempt was affordable, never suppressed."""
        captured, llm = _drive(
            monkeypatch, [_QUALITY_PASS_MIN_SECONDS - 1.0]
        )

        assert captured.kwargs["gate_attempts_used"] == 0
        assert llm.calls == 1, "no gate pass may be fired into a spent budget"

        shipped = captured.kwargs["final_quality"]
        assert shipped.grounding == 61.0, "the real score, never a rounded-up one"

        from app.services.quality_gate import evaluate_cover_letter

        verdict = evaluate_cover_letter(shipped)
        assert verdict.passed is False
        assert [d.label for d in verdict.failing] == ["Evidence Grounding"]

    def test_an_ample_budget_still_spends_the_whole_gate_budget(
        self, monkeypatch: Any
    ) -> None:
        """The counter-pin: the budget guard must not be so eager that it
        strangles a gate that CAN afford its attempts — otherwise the first
        test above would pass on an implementation that never iterates."""
        from app.agents.cover_letter_agent import gate_pass_labels

        captured, llm = _drive(monkeypatch, [_QUALITY_PASS_MIN_SECONDS * 10])

        assert captured.kwargs["gate_attempts_used"] == len(gate_pass_labels())
        assert llm.calls == 1 + len(gate_pass_labels())


# ---------------------------------------------------------------------------
# Résumé side: exhaustion arrives as LLMUnavailableError mid-gate-attempt
# ---------------------------------------------------------------------------

_ORIGINALS = [
    {"text": "Built backend services handling 500 requests per day.", "evidenceRef": "b0"},
]
_TAILOR_RESUME = "JANE DOE\nBackend Engineer\n\n- Built backend services.\n"
_TAILOR_JD = "Backend Engineer at Acme. Kafka and distributed systems."


def _ats(overall: float, *, keyword: float) -> ATSScore:
    return ATSScore(
        overall=overall,
        keyword_match=keyword,
        semantic_similarity=overall,
        experience_gap=overall,
        matched_keywords=[],
        missing_keywords=[],
        requires_review=False,
        semantic_path="local",
    )


class _StarvingService:
    """Succeeds for ``ok_calls`` attempts, then reports the budget exhausted."""

    def __init__(self, ok_calls: int) -> None:
        self._ok_calls = ok_calls
        self.calls = 0

    def tailor(self, resume_text, job_description, originals=None, evidence_extra="", **kw):  # noqa: ANN001
        self.calls += 1
        if self.calls > self._ok_calls:
            raise LLMUnavailableError("LLM call exceeded hard budget of 68.6s")
        return TailorResult(
            bullets=[dict(b) for b in (originals or _ORIGINALS)],
            changes=1,
            originals=list(originals or _ORIGINALS),
        )


class _FlatATS:
    def __init__(self, score: ATSScore) -> None:
        self._score = score
        self.calls = 0

    def score(self, resume_text, job_description):  # noqa: ANN001
        self.calls += 1
        return self._score


class TestTheTailoringGateRespectsTheBudget:
    def test_exhaustion_during_a_gate_attempt_keeps_the_best_honest_draft(
        self,
    ) -> None:
        """The gate must never cost a user the work already done, and must
        never be reported as a pass because the attempt that would have proved
        otherwise could not be paid for."""
        from app.services.quality_gate import QUALITY_FLOOR
        from app.services.tailoring_loop import TailoringLoop

        # One successful pass (reaches the ATS target, keyword below floor), so
        # the loop extends into the gate budget — and the extra attempt starves.
        service = _StarvingService(ok_calls=1)
        loop = TailoringLoop(
            service=service,
            ats_engine=_FlatATS(_ats(90.0, keyword=61.0)),
            max_iterations=1,
            dimension_floor=QUALITY_FLOOR,
            gate_extra_attempts=2,
        )
        result = loop.run(
            _TAILOR_RESUME, _TAILOR_JD, originals=_ORIGINALS, evidence_extra=""
        )

        # The starving attempt stopped the loop — it did not burn the whole
        # gate budget on calls that could never complete.
        assert service.calls == 2
        assert result.stop_reason == "llm_budget_exhausted"
        # Honest terminal state: the artifact ships, the verdict does not.
        assert result.final_bullets
        assert result.success is False
        assert result.quality_gate is not None
        assert result.quality_gate["passed"] is False
        assert [d["key"] for d in result.quality_gate["failing"]] == ["keywordMatch"]

    def test_first_attempt_exhaustion_still_propagates(self) -> None:
        """Iteration 1 has nothing to keep, so the caller must still see the
        outage and refund the reserved run (W-TAILOR-CONVERGE). The gate must
        not swallow it into a fabricated below-floor 'result' with no content."""
        from app.services.quality_gate import QUALITY_FLOOR
        from app.services.tailoring_loop import TailoringLoop

        loop = TailoringLoop(
            service=_StarvingService(ok_calls=0),
            ats_engine=_FlatATS(_ats(90.0, keyword=61.0)),
            max_iterations=2,
            dimension_floor=QUALITY_FLOOR,
            gate_extra_attempts=2,
        )
        with pytest.raises(LLMUnavailableError):
            loop.run(
                _TAILOR_RESUME, _TAILOR_JD, originals=_ORIGINALS, evidence_extra=""
            )
