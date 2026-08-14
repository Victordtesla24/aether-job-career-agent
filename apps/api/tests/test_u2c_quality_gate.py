"""U2c — the 80%-across-all-dimensions quality floor is ENFORCED, not decorative.

Before this slice the product COMPUTED and DISPLAYED per-artifact dimension
scores (``ATSScore``'s components for a tailored résumé, ``CoverLetterQuality``'s
for a letter) and computed the 80% floor for the RIGOR POLICY
(``quality_policy.DIMENSION_FLOOR``), but nothing ever acted on a single
artifact falling below it: a résumé whose keyword match was 61% shipped exactly
like one at 91%.

These tests pin the enforcement contract:

1. The floor is ONE number, imported from ``quality_policy`` — never re-typed.
2. Every dimension is judged on its REAL score. A dimension that could not be
   MEASURED (degraded semantic scoring, an unmeasurable JD alignment) is
   neither passed nor failed silently: it blocks the gate and says why.
3. Iteration is BOUNDED — the extra attempts the gate may spend come from an
   env-capped constant, never an open-ended "keep trying".
4. A below-floor run still DELIVERS its artifact, flagged with the failing
   dimensions verbatim. Never silently passed, never blocked with no output.
5. THE CARDINAL SIN: an iteration attempt that introduces an unsupported claim
   is rejected even when it would clear the threshold. Scores are never bought
   with fabrication.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services.ats_engine import ATSScore
from app.services.resume_tailor import TailorResult

_RESUME = (
    "JANE DOE\nBackend Engineer\n\nEXPERIENCE\n"
    "- Built backend services handling 500 requests per day.\n"
    "- Ran the Kafka ingestion pipeline for the billing team.\n"
)
_ORIGINALS = [
    {"text": "Built backend services handling 500 requests per day.", "evidenceRef": "bullet-0"},
    {"text": "Ran the Kafka ingestion pipeline for the billing team.", "evidenceRef": "bullet-1"},
]
_JD = "Backend Engineer at Acme. We care about Kafka and distributed systems."


def _ats(
    overall: float,
    *,
    keyword: float | None = None,
    semantic: float | None = None,
    experience: float | None = None,
    path: str = "local",
) -> ATSScore:
    return ATSScore(
        overall=overall,
        keyword_match=overall if keyword is None else keyword,
        semantic_similarity=overall if semantic is None else semantic,
        experience_gap=overall if experience is None else experience,
        matched_keywords=[],
        missing_keywords=[],
        requires_review=False,
        semantic_path=path,
    )


class _Service:
    """Minimal tailor double that records what each attempt was handed."""

    def __init__(self, bullets_by_call: list[list[dict[str, str]]] | None = None) -> None:
        self.jd_by_call: list[str] = []
        self.evidence_by_call: list[str] = []
        self._bullets_by_call = bullets_by_call

    def tailor(
        self,
        resume_text: str,
        job_description: str,
        originals: Any = None,
        evidence_extra: str = "",
        **kwargs: Any,
    ) -> TailorResult:
        idx = len(self.jd_by_call)
        self.jd_by_call.append(job_description)
        self.evidence_by_call.append(evidence_extra)
        if self._bullets_by_call is not None:
            bullets = [dict(b) for b in self._bullets_by_call[idx]]
        else:
            bullets = [dict(b) for b in (originals or _ORIGINALS)]
        return TailorResult(
            bullets=bullets, changes=1, originals=list(originals or _ORIGINALS)
        )

    @property
    def calls(self) -> int:
        return len(self.jd_by_call)


class _ScriptedATS:
    def __init__(self, scores: list[ATSScore]) -> None:
        self._scores = scores
        self.calls = 0

    def score(self, resume_text: str, job_description: str) -> ATSScore:
        idx = min(self.calls, len(self._scores) - 1)
        self.calls += 1
        return self._scores[idx]


# ---------------------------------------------------------------------------
# 1. The module: one floor, real dimensions, honest ignorance
# ---------------------------------------------------------------------------


def test_the_floor_is_the_policy_floor_never_a_second_copy() -> None:
    from app.services import quality_gate
    from app.services.quality_policy import DIMENSION_FLOOR

    assert quality_gate.QUALITY_FLOOR == DIMENSION_FLOOR
    assert quality_gate.QUALITY_FLOOR == 80.0


def test_tailoring_gate_passes_only_when_every_dimension_clears_the_floor() -> None:
    from app.services.quality_gate import evaluate_tailoring

    ok = evaluate_tailoring(_ats(91.0, keyword=88.0, semantic=85.0, experience=100.0))
    assert ok.passed is True
    assert ok.failing == ()

    bad = evaluate_tailoring(_ats(91.0, keyword=61.0, semantic=85.0, experience=79.9))
    assert bad.passed is False
    keys = [d.key for d in bad.failing]
    assert keys == ["keywordMatch", "experienceMatch"], keys
    # The user-facing text must quote the REAL numbers, never a rounded claim.
    assert "61.0" in bad.summary and "79.9" in bad.summary


def test_a_dimension_exactly_at_the_floor_has_not_cleared_it() -> None:
    """``quality_policy`` treats 80.0 as NOT above the floor. The per-artifact
    gate must agree — two thresholds with the same name and different meanings
    is how a product starts lying to itself."""
    from app.services.quality_gate import evaluate_tailoring

    verdict = evaluate_tailoring(_ats(90.0, keyword=80.0))
    assert verdict.passed is False
    assert [d.key for d in verdict.failing] == ["keywordMatch"]


def test_an_unmeasured_dimension_blocks_the_gate_and_says_why() -> None:
    """A degraded semantic score is a neutral PLACEHOLDER, not a measurement
    (``ATSScore.semantic_path``). Passing the gate on it would fabricate a
    verdict; failing it on the placeholder's numeric value would fabricate a
    deficiency. It blocks, labelled ``not measured``."""
    from app.services.quality_gate import evaluate_tailoring

    verdict = evaluate_tailoring(_ats(95.0, path="degraded"))
    assert verdict.passed is False
    semantic = next(d for d in verdict.dimensions if d.key == "semanticSimilarity")
    assert semantic.measured is False
    assert semantic.score is None
    # ``overall`` is 40% built from that same component, so it cannot be
    # certified either.
    overall = next(d for d in verdict.dimensions if d.key == "overall")
    assert overall.measured is False
    assert "not measured" in verdict.summary.lower()


def test_an_unmeasurable_failure_is_reported_but_never_iterated_on() -> None:
    """A failure nothing can rewrite away must not buy LLM attempts — the same
    rule ``split_gap_keywords`` applies to unreachable keywords."""
    from app.services.quality_gate import evaluate_tailoring

    degraded = evaluate_tailoring(_ats(95.0, path="degraded"))
    assert degraded.passed is False
    assert degraded.closable is False

    weak = evaluate_tailoring(_ats(95.0, keyword=61.0))
    assert weak.passed is False
    assert weak.closable is True


def test_untracked_provenance_is_the_callers_opt_out_not_a_degradation() -> None:
    """``ATSScore.semantic_path`` distinguishes the engine's own "degraded"
    verdict from "this caller tracks no provenance at all". ``tailoring_loop``
    already rules that the second must NOT withhold a converged pass, and this
    gate lives inside that same convergence decision — reading it as degraded
    would both contradict that rule and spend the bounded gate budget chasing
    a dimension no rewrite can move. Real ``ATSEngine.score`` calls always emit
    local/hf_api/degraded, so production behaviour is identical either way."""
    from app.services.quality_gate import evaluate_tailoring

    verdict = evaluate_tailoring(_ats(95.0, path="untracked"))
    assert verdict.passed is True


def test_cover_letter_gate_uses_the_letter_dimension_set() -> None:
    from app.services.cover_letter_quality import CoverLetterQuality
    from app.services.quality_gate import evaluate_cover_letter

    good = CoverLetterQuality(
        overall=90.0, jd_alignment=84.0, grounding=88.0, structure=100.0,
        reached_target=True, jd_alignment_measured=True,
    )
    assert evaluate_cover_letter(good).passed is True

    weak = CoverLetterQuality(
        overall=90.0, jd_alignment=42.0, grounding=88.0, structure=75.0,
        reached_target=True, jd_alignment_measured=True,
    )
    verdict = evaluate_cover_letter(weak)
    assert verdict.passed is False
    assert [d.key for d in verdict.failing] == ["jdAlignment", "structure"]
    assert "42.0" in verdict.summary and "75.0" in verdict.summary


def test_cover_letter_unmeasurable_alignment_blocks_rather_than_scores_zero() -> None:
    from app.services.cover_letter_quality import CoverLetterQuality
    from app.services.quality_gate import evaluate_cover_letter

    quality = CoverLetterQuality(
        overall=88.0, jd_alignment=0.0, grounding=90.0, structure=100.0,
        reached_target=True, jd_alignment_measured=False,
    )
    verdict = evaluate_cover_letter(quality)
    assert verdict.passed is False
    alignment = next(d for d in verdict.dimensions if d.key == "jdAlignment")
    assert alignment.measured is False
    assert alignment.score is None


def test_acknowledgement_label_names_the_number_of_failing_dimensions() -> None:
    from app.services.quality_gate import acknowledgement_label, evaluate_tailoring

    verdict = evaluate_tailoring(_ats(90.0, keyword=61.0, experience=70.0))
    assert acknowledgement_label(verdict) == "Approve anyway — 2 dimensions below floor"
    single = evaluate_tailoring(_ats(90.0, keyword=61.0))
    assert acknowledgement_label(single) == "Approve anyway — 1 dimension below floor"


# ---------------------------------------------------------------------------
# 2. The iteration budget is bounded and env-capped
# ---------------------------------------------------------------------------


def test_gate_attempts_default_small_and_are_env_capped(monkeypatch: Any) -> None:
    from app.services import quality_gate

    monkeypatch.delenv(quality_gate.GATE_ATTEMPTS_ENV, raising=False)
    assert quality_gate.gate_extra_attempts() == quality_gate.DEFAULT_GATE_EXTRA_ATTEMPTS
    assert quality_gate.DEFAULT_GATE_EXTRA_ATTEMPTS == 2

    monkeypatch.setenv(quality_gate.GATE_ATTEMPTS_ENV, "1")
    assert quality_gate.gate_extra_attempts() == 1

    # Never unbounded: a wild value is clamped to the module's own ceiling,
    # because every extra attempt is a full extra LLM generation and the plan
    # spend cap is checked PRE-run (a run in flight is never interrupted).
    monkeypatch.setenv(quality_gate.GATE_ATTEMPTS_ENV, "999")
    assert quality_gate.gate_extra_attempts() == quality_gate.MAX_GATE_EXTRA_ATTEMPTS
    assert quality_gate.MAX_GATE_EXTRA_ATTEMPTS <= 4

    # Never negative, never a crash on garbage.
    monkeypatch.setenv(quality_gate.GATE_ATTEMPTS_ENV, "-3")
    assert quality_gate.gate_extra_attempts() == 0
    monkeypatch.setenv(quality_gate.GATE_ATTEMPTS_ENV, "banana")
    assert quality_gate.gate_extra_attempts() == quality_gate.DEFAULT_GATE_EXTRA_ATTEMPTS


# ---------------------------------------------------------------------------
# 3. The tailoring loop ENFORCES the gate — bounded, honest, evidence-fed
# ---------------------------------------------------------------------------


def test_loop_does_not_declare_success_when_a_dimension_is_below_floor() -> None:
    """The headline ATS target is reached on every pass, but keyword match sits
    at 61. Before this slice the loop stopped at pass 1 and reported success."""
    from app.services.quality_gate import QUALITY_FLOOR
    from app.services.tailoring_loop import TailoringLoop

    service = _Service()
    ats = _ScriptedATS([_ats(90.0, keyword=61.0)])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=3,
        dimension_floor=QUALITY_FLOOR, gate_extra_attempts=0,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert result.success is False
    assert result.requires_review is True
    assert result.quality_gate is not None
    assert result.quality_gate["passed"] is False
    assert [d["key"] for d in result.quality_gate["failing"]] == ["keywordMatch"]
    # Honest terminal: the artifact IS delivered.
    assert result.final_bullets
    assert "Keyword Match" in (result.warning or "")
    assert "61.0" in (result.warning or "")


def test_loop_stops_the_moment_the_gate_passes() -> None:
    from app.services.quality_gate import QUALITY_FLOOR
    from app.services.tailoring_loop import TailoringLoop

    service = _Service()
    ats = _ScriptedATS([
        _ats(90.0, keyword=61.0),   # target met, gate open
        _ats(91.0, keyword=88.0),   # gate closes
        _ats(99.0, keyword=99.0),   # must never be reached
    ])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=5,
        dimension_floor=QUALITY_FLOOR, gate_extra_attempts=2,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert service.calls == 2
    assert result.success is True
    assert result.stop_reason == "target_reached"
    assert result.quality_gate["passed"] is True


def test_gate_spends_at_most_its_extra_attempt_budget() -> None:
    """The score target is reached immediately, so without the gate the loop
    would have stopped at pass 1. The gate may spend the loop's remaining
    iterations plus AT MOST ``gate_extra_attempts`` more — never more than
    that, however far below the floor the run stays."""
    from app.services.quality_gate import QUALITY_FLOOR
    from app.services.tailoring_loop import TailoringLoop

    service = _Service()
    ats = _ScriptedATS([_ats(90.0, keyword=61.0)])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=3,
        dimension_floor=QUALITY_FLOOR, gate_extra_attempts=2,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert service.calls == 5  # 3 loop iterations + 2 gate attempts, hard stop
    assert result.stop_reason == "quality_gate_cap"
    assert result.gate_attempts_used == 2
    assert result.success is False


def test_a_sub_target_run_never_spends_the_gate_budget() -> None:
    """A run that cannot even reach the ATS target has an open score gap, not a
    dimension-gate problem — the existing iteration cap must still bound it, so
    arming the gate cannot silently raise every run's worst-case LLM spend."""
    from app.services.quality_gate import QUALITY_FLOOR
    from app.services.tailoring_loop import TailoringLoop

    service = _Service()
    ats = _ScriptedATS([_ats(40.0)])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=3,
        dimension_floor=QUALITY_FLOOR, gate_extra_attempts=2,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert service.calls == 3
    assert result.gate_attempts_used == 0
    assert result.stop_reason == "iteration_cap"


def test_an_unmeasurable_gate_failure_buys_no_extra_attempts() -> None:
    """Semantic scoring degraded: the gate cannot certify the run, but no
    rewrite can change that, so the loop must stop rather than spend its
    bounded (paid) attempts on it — and must still withhold success."""
    from app.services.quality_gate import QUALITY_FLOOR
    from app.services.tailoring_loop import TailoringLoop

    service = _Service()
    ats = _ScriptedATS([_ats(95.0, path="degraded")])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=5,
        dimension_floor=QUALITY_FLOOR, gate_extra_attempts=2,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert service.calls == 1
    assert result.gate_attempts_used == 0
    assert result.stop_reason == "quality_gate_unmeasurable"
    assert result.success is False
    assert result.final_bullets  # the artifact still ships


def test_every_attempt_receives_the_corpus_and_story_evidence() -> None:
    """"with corpus+story evidence in each attempt's context" — an iteration
    that cannot see the candidate's own evidence can only close a gap by
    inventing, which is precisely what the guards then reject."""
    from app.services.quality_gate import QUALITY_FLOOR
    from app.services.tailoring_loop import TailoringLoop

    evidence = "STORY: Ran the Kafka ingestion pipeline.\nCORPUS: Kafka consumer groups."
    service = _Service()
    ats = _ScriptedATS([_ats(90.0, keyword=61.0)])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=3,
        dimension_floor=QUALITY_FLOOR, gate_extra_attempts=1,
    )
    loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra=evidence)

    assert service.calls == 4
    for i, seen in enumerate(service.evidence_by_call, start=1):
        assert seen == evidence, f"attempt {i} lost the evidence corpus"


def test_gate_directive_names_the_failing_dimensions_and_forbids_invention() -> None:
    from app.services.quality_gate import QUALITY_FLOOR
    from app.services.tailoring_loop import DIRECTIVE_MARKER, TailoringLoop

    service = _Service()
    ats = _ScriptedATS([_ats(90.0, keyword=61.0)])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=2,
        dimension_floor=QUALITY_FLOOR, gate_extra_attempts=0,
    )
    loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    directive = service.jd_by_call[1].split(DIRECTIVE_MARKER, 1)[1]
    assert "Keyword Match" in directive
    assert "61.0" in directive
    assert "80" in directive
    assert "NEVER invent or fabricate" in directive


def test_a_gate_passing_iteration_beats_a_higher_scoring_failing_one() -> None:
    """Ranking by raw ``overall`` alone would throw away the only draft that
    actually cleared every dimension."""
    from app.services.quality_gate import QUALITY_FLOOR
    from app.services.tailoring_loop import TailoringLoop

    passing = [{"text": "Ran the Kafka ingestion pipeline.", "evidenceRef": "bullet-1"}]
    failing = [{"text": "Built backend services.", "evidenceRef": "bullet-0"}]
    service = _Service(bullets_by_call=[failing, passing, failing])
    ats = _ScriptedATS([
        _ats(95.0, keyword=61.0),   # highest overall, gate FAILS
        _ats(86.0, keyword=86.0),   # lower overall, gate PASSES
        _ats(97.0, keyword=61.0),
    ])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=3,
        dimension_floor=QUALITY_FLOOR, gate_extra_attempts=0,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert result.best_iteration == 2
    assert result.final_bullets == passing
    assert result.success is True


def test_disarmed_gate_leaves_the_shipped_loop_behaviour_byte_identical() -> None:
    """``dimension_floor=None`` must be exactly today's loop — the gate is
    additive, never a silent behaviour change for callers that never armed it."""
    from app.services.tailoring_loop import TailoringLoop

    service = _Service()
    ats = _ScriptedATS([_ats(90.0, keyword=10.0)])
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=3)
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert service.calls == 1
    assert result.success is True
    assert result.quality_gate is None
    assert result.stop_reason == "target_reached"


def test_every_attempt_records_its_own_dimension_scores() -> None:
    """INSTRUMENTATION: the Supervisor's directive loop (ADR-AGI-2) consumes
    the per-attempt trail, so each attempt carries its OWN real scores."""
    from app.services.quality_gate import QUALITY_FLOOR
    from app.services.tailoring_loop import TailoringLoop

    service = _Service()
    ats = _ScriptedATS([_ats(90.0, keyword=61.0), _ats(92.0, keyword=70.0)])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=2,
        dimension_floor=QUALITY_FLOOR, gate_extra_attempts=0,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    gates = [it["qualityGate"] for it in result.iterations]
    assert len(gates) == 2
    assert gates[0]["dimensions"][1]["score"] == 61.0
    assert gates[1]["dimensions"][1]["score"] == 70.0
    assert all(g["passed"] is False for g in gates)


# ---------------------------------------------------------------------------
# 4. THE CARDINAL SIN — a score is never bought with a fabricated claim
# ---------------------------------------------------------------------------


def test_iteration_introducing_an_unsupported_claim_is_rejected_by_the_guard() -> None:
    """A rewrite that would clear the floor by CLAIMING something the
    candidate's evidence never proves must still be rejected. The guard is the
    real ``ResumeTailorService`` machinery — the gate never gets to relax it."""
    from app.services.resume_tailor import _evidence_index, unsupported_tokens

    stems, numbers = _evidence_index(_RESUME)
    jd_stems, _ = _evidence_index(_JD)
    # "Kubernetes" and the AWS certification appear NOWHERE in the evidence —
    # and naming them is exactly what would lift the keyword-match dimension
    # over the floor for a posting that asks for them.
    fabricated = (
        "Ran the Kafka ingestion pipeline on Kubernetes as an AWS Certified "
        "Solutions Architect for the billing team."
    )
    flagged = unsupported_tokens(fabricated, stems, numbers, jd_stems)
    assert "kubernetes" in flagged, "the guard accepted a fabricated tool claim"
    assert "aws" in flagged, "the guard accepted a fabricated certification claim"
    # ...while an honest rewrite of the SAME bullet passes untouched.
    honest = "Ran the Kafka ingestion pipeline for the billing team end to end."
    assert unsupported_tokens(honest, stems, numbers, jd_stems) == []


def test_the_loop_reports_the_guards_rejection_instead_of_the_better_score() -> None:
    """End-to-end at the loop seam: an attempt whose fabricated rewrite the
    guard rejected leaves the bullets unchanged, so the honest (low) score is
    what the gate judges — the run reports below-floor, never success."""
    from app.services.quality_gate import QUALITY_FLOOR
    from app.services.tailoring_loop import TailoringLoop

    class _GuardedService(_Service):
        """Emulates the real service's contract: a rejected rewrite is NOT
        applied, and is reported in ``rejected``."""

        def tailor(
            self,
            resume_text: str,
            job_description: str,
            originals: Any = None,
            evidence_extra: str = "",
            **kwargs: Any,
        ) -> TailorResult:
            self.jd_by_call.append(job_description)
            self.evidence_by_call.append(evidence_extra)
            kept = [dict(b) for b in (originals or _ORIGINALS)]
            return TailorResult(
                bullets=kept,
                changes=0,
                originals=list(originals or _ORIGINALS),
                rejected=["bullet-1: 'Kubernetes' is not supported by your evidence"],
            )

    service = _GuardedService()
    ats = _ScriptedATS([_ats(90.0, keyword=61.0)])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=2,
        dimension_floor=QUALITY_FLOOR, gate_extra_attempts=1,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert result.success is False
    assert result.quality_gate["passed"] is False
    assert any("Kubernetes" in r for it in result.iterations for r in it["rejected"])


@pytest.mark.parametrize("floor_env", ["0", "2"])
def test_gate_never_lowers_the_shipped_iteration_floor(floor_env: str, monkeypatch: Any) -> None:
    """Whatever the env says, arming the gate can only ever ADD attempts on top
    of the loop's own cap — it can never make the product try LESS than it does
    today (``quality_policy`` rule 3)."""
    from app.services import quality_gate
    from app.services.tailoring_loop import TailoringLoop

    monkeypatch.setenv(quality_gate.GATE_ATTEMPTS_ENV, floor_env)
    service = _Service()
    ats = _ScriptedATS([_ats(40.0)])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=3,
        dimension_floor=quality_gate.QUALITY_FLOOR,
        gate_extra_attempts=quality_gate.gate_extra_attempts(),
    )
    loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")
    assert service.calls == 3
