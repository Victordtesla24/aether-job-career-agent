"""U2c — the cover-letter gate: same semantics, the letter's dimension set.

The résumé had a score-aware loop; the letter had ONE optional improvement
pass, fired only when the headline ``reachedTarget`` was false and there were
missing keywords to chase. A letter whose STRUCTURE scored 50 or whose
GROUNDING scored 61 shipped untouched and unflagged, because neither is what
that condition looked at.

These tests pin the letter half of the enforcement contract:

* the gate is judged over the letter's OWN dimensions, with the same floor;
* iteration is bounded by the same env-capped budget, and an unmeasurable
  failure buys none of it;
* the shipped letter carries the verdict, so the card, the Studio panel and the
  approval modal all read one computation;
* the guards stay fully armed inside every improvement pass — a pass whose
  draft is not clean is DISCARDED even when it scores higher.
"""
from __future__ import annotations

from typing import Any

from app.services.cover_letter_quality import CoverLetterQuality


def _quality(
    overall: float = 90.0,
    *,
    alignment: float = 90.0,
    grounding: float = 90.0,
    structure: float = 100.0,
    measured: bool = True,
    missing: list[str] | None = None,
    unreachable: list[str] | None = None,
) -> CoverLetterQuality:
    return CoverLetterQuality(
        overall=overall,
        jd_alignment=alignment,
        grounding=grounding,
        structure=structure,
        reached_target=overall >= 85.0,
        jd_alignment_measured=measured,
        missing_keywords=list(missing or []),
        unreachable_keywords=list(unreachable or []),
    )


class TestTheLetterGateDecision:
    def test_a_weak_dimension_fails_the_gate_even_when_the_headline_passes(
        self,
    ) -> None:
        """The exact hole this slice closes: ``reachedTarget`` was true, so the
        old improvement pass never fired, and a 61% grounding shipped silently."""
        from app.services.quality_gate import evaluate_cover_letter

        quality = _quality(overall=88.0, grounding=61.0)
        assert quality.reached_target is True
        verdict = evaluate_cover_letter(quality)
        assert verdict.passed is False
        assert [d.label for d in verdict.failing] == ["Evidence Grounding"]
        assert verdict.closable is True

    def test_needs_gate_pass_is_false_once_every_dimension_clears(self) -> None:
        from app.agents.cover_letter_agent import needs_gate_pass

        assert needs_gate_pass(_quality()) is False

    def test_needs_gate_pass_is_true_for_a_closable_dimension_failure(self) -> None:
        from app.agents.cover_letter_agent import needs_gate_pass

        assert needs_gate_pass(_quality(overall=88.0, structure=50.0)) is True

    def test_needs_gate_pass_is_false_when_nothing_can_be_rewritten(self) -> None:
        """Alignment could not be MEASURED for this posting. No rewrite changes
        that, so spending a paid generation on it is waste, not rigor."""
        from app.agents.cover_letter_agent import needs_gate_pass

        assert needs_gate_pass(_quality(alignment=0.0, measured=False)) is False


class TestTheGateDirective:
    def test_it_names_the_failing_dimensions_and_forbids_invention(self) -> None:
        from app.agents.cover_letter_agent import gate_improvement_instruction
        from app.services.quality_gate import evaluate_cover_letter

        quality = _quality(
            overall=88.0, grounding=61.0, structure=75.0,
            missing=["kafka"], unreachable=["kubernetes"],
        )
        text = gate_improvement_instruction(
            evaluate_cover_letter(quality), quality
        )
        assert "Evidence Grounding" in text and "61.0" in text
        assert "Letter Structure" in text and "75.0" in text
        assert "80" in text
        assert "kafka" in text
        # The unsupported term is named as FORBIDDEN, never as a target.
        assert "kubernetes" in text
        assert "NEVER" in text


class TestTheShippedLetterCarriesTheVerdict:
    def test_letter_quality_carries_the_gate_and_the_failing_dimensions(
        self,
    ) -> None:
        from app.agents.cover_letter_agent import build_letter_quality

        final = _quality(overall=88.0, grounding=61.0)
        passes: list[dict[str, Any]] = [
            {"iteration": 1, "stage": "initial_draft", **final.as_dict()},
        ]
        letter_quality = build_letter_quality(
            final_quality=final, passes=passes, gate_attempts_used=2
        )
        assert letter_quality["qualityGate"]["passed"] is False
        assert letter_quality["belowQualityFloor"] is True
        assert letter_quality["failingDimensions"] == ["Evidence Grounding"]
        assert letter_quality["gateAttemptsUsed"] == 2
        # The pre-existing shape is preserved byte-for-byte for its readers.
        assert letter_quality["finalScore"] == 88.0
        assert letter_quality["initialScore"] == 88.0
        assert letter_quality["passes"][-1]["stage"] == "shipped"

    def test_a_clean_letter_is_reported_as_clearing_the_floor(self) -> None:
        from app.agents.cover_letter_agent import build_letter_quality

        final = _quality()
        letter_quality = build_letter_quality(
            final_quality=final, passes=[], gate_attempts_used=0
        )
        assert letter_quality["qualityGate"]["passed"] is True
        assert letter_quality["belowQualityFloor"] is False
        assert letter_quality["failingDimensions"] == []


class TestGuardsStayArmedInsideEveryGatePass:
    def test_an_unclean_higher_scoring_candidate_is_discarded(self) -> None:
        """THE CARDINAL SIN, letter edition: a pass that scores better because
        it claimed something the evidence does not prove is thrown away. Score
        is never the tiebreak on its own — cleanliness is a precondition."""
        from app.agents.cover_letter_agent import accept_gate_candidate

        weak_but_clean = _quality(overall=70.0)
        strong_but_dirty = _quality(overall=95.0)

        assert (
            accept_gate_candidate(
                candidate=strong_but_dirty,
                incumbent_overall=weak_but_clean.overall,
                guard_clean=False,
            )
            is False
        )
        assert (
            accept_gate_candidate(
                candidate=strong_but_dirty,
                incumbent_overall=weak_but_clean.overall,
                guard_clean=True,
            )
            is True
        )
        # A clean candidate that scores no better than the incumbent is also
        # rejected — an improvement pass must actually improve.
        assert (
            accept_gate_candidate(
                candidate=weak_but_clean,
                incumbent_overall=weak_but_clean.overall,
                guard_clean=True,
            )
            is False
        )


class TestTheGatePassBudgetIsBounded:
    def test_it_is_the_same_env_capped_budget_the_resume_gate_uses(
        self, monkeypatch: Any
    ) -> None:
        from app.agents.cover_letter_agent import gate_pass_labels
        from app.services import quality_gate

        monkeypatch.delenv(quality_gate.GATE_ATTEMPTS_ENV, raising=False)
        labels = gate_pass_labels()
        assert len(labels) == quality_gate.DEFAULT_GATE_EXTRA_ATTEMPTS
        # The FIRST label is byte-for-byte the historic fixture key, so every
        # recorded LLM replay fixture keeps replaying.
        assert labels[0] == "quality"
        assert labels[1] == "quality2"

        monkeypatch.setenv(quality_gate.GATE_ATTEMPTS_ENV, "0")
        assert gate_pass_labels() == ()

        monkeypatch.setenv(quality_gate.GATE_ATTEMPTS_ENV, "999")
        assert len(gate_pass_labels()) == quality_gate.MAX_GATE_EXTRA_ATTEMPTS
