"""GOLD-MASTER-V4, §22 STEP 2 (SECOND ROUND) — adversarial-review FAIL on
GMV4-ats-001 (W-HF): the MOST SEVERE leak site.

``TailoringLoop.run()`` (``apps/api/app/services/tailoring_loop.py:176-200``)
consumes ``ats_score.overall`` for the per-iteration record, ``best_score``,
the convergence check (``ats_score.overall >= self.target_score``), and the
``success``/``requires_review`` outcome — all WITHOUT ever reading
``ats_score.semantic_path``. ``overall`` is 40% built from
``semantic_similarity``, so whenever the engine falls back to the honest
``_DEGRADED_SEMANTIC_SCORE = 50.0`` placeholder (GMV4-ats-001), that 40% share
of ``overall`` is fabricated — yet the loop's automated success/failure
decision, which a human never reviews when ``success=True``, is made off that
contaminated number with no record of which scoring path produced it.

PRODUCT DECISION (see also the final report note handed back to the
orchestrator): two honest contracts are defensible here —
  (a) REFUSE-AND-ERROR — raise before returning any result at all, or
  (b) CONVERGE-BUT-FLAG — never declare ``success`` on a degraded score;
      report ``requires_review=True`` with a warning naming the degradation.
This file pins (b), because it is the contract this codebase has already
chosen twice elsewhere for the exact same "no genuine signal available"
situation: ``ATSEngine.score()`` itself never raises on
``SemanticScoringUnavailableError`` — it degrades gracefully and stamps
``semantic_path="degraded"`` (ats_engine.py's own module docstring, "HONEST
DEGRADATION"); and the cover-letter pipeline's own prior incident (2026-07-21,
commit 56552e0) was a hard-fail-the-whole-pipeline bug on
``FabricationError`` that got REVERTED in favour of graceful degradation
specifically because hard-failing broke user-facing flows worse than an
honest flagged result did. (a) REFUSE-AND-ERROR remains the alternative the
orchestrator may prefer instead; if so, ``test_loop_does_not_declare_success_on_degraded_scores``
below is the one test to rewrite (assert a raised exception instead of
``success is False`` + a named warning) — every other test in this file is
contract-agnostic.

Stubs/fixtures below intentionally mirror the SAME conventions already
established in the still-green ``test_wc_tailoring_loop.py`` (``_CountingService``,
a stepwise fake ATS engine) — redefined locally here (not imported) so this
file stays self-contained and that file is never touched.
"""
from __future__ import annotations

from app.services.ats_engine import ATSScore
from app.services.resume_tailor import TailorResult

_RESUME = (
    "JANE DOE\nBackend Engineer\n\nEXPERIENCE\n"
    "• Built backend services handling 500 requests per day.\n"
)
_ORIGINALS = [
    {"text": "Built backend services handling 500 requests per day.", "evidenceRef": "bullet-0"}
]
_JD = "Backend Engineer. We're looking for someone who cares about Kubernetes and Kafka."


class _CountingService:
    """Records every ``job_description`` it is called with; returns the
    (unchanged) originals as a no-op "rewrite" — sufficient for tests that
    only pin loop MECHANICS, not real tailoring content."""

    def __init__(self) -> None:
        self.jd_by_call: list[str] = []

    def tailor(self, resume_text, job_description, originals=None, evidence_extra=""):  # noqa: ANN001
        self.jd_by_call.append(job_description)
        bullets = list(originals or _ORIGINALS)
        return TailorResult(bullets=bullets, changes=1, originals=bullets)

    @property
    def calls(self) -> int:
        return len(self.jd_by_call)


class _StepwiseATSWithPath:
    """Like ``test_wc_tailoring_loop.py``'s ``_StepwiseATS``, but each call
    also carries an independently-controlled ``semantic_path`` — needed to
    prove the loop propagates + honours GMV4-ats-001's degradation signal
    rather than trusting the (possibly placeholder-contaminated) ``overall``
    alone."""

    def __init__(self, overalls: list[float], semantic_paths: list[str]) -> None:
        assert len(overalls) == len(semantic_paths), "fixture bug: lists must be same length"
        self._overalls = overalls
        self._paths = semantic_paths
        self.calls = 0

    def score(self, resume_text, job_description) -> ATSScore:  # noqa: ANN001
        idx = min(self.calls, len(self._overalls) - 1)
        overall = self._overalls[idx]
        path = self._paths[idx]
        self.calls += 1
        return ATSScore(
            overall=overall,
            keyword_match=overall,
            semantic_similarity=overall,
            experience_gap=overall,
            matched_keywords=[],
            missing_keywords=[],
            requires_review=overall < 60.0,
            semantic_path=path,
        )


def _iteration_path(iteration: dict) -> str | None:
    return iteration.get("semantic_path") or iteration.get("semanticPath")


# ---------------------------------------------------------------------------
# 1 — the path must be recorded per iteration at all
# ---------------------------------------------------------------------------


def test_loop_records_semantic_path_per_iteration():
    from app.services.tailoring_loop import TailoringLoop

    service = _CountingService()
    ats = _StepwiseATSWithPath(overalls=[40.0, 90.0], semantic_paths=["local", "degraded"])
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=2, target_score=85.0)
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS)

    assert len(result.iterations) == 2
    for i, iteration in enumerate(result.iterations):
        assert _iteration_path(iteration) is not None, (
            f"iteration {i} does not record which scoring path (local/hf_api/degraded) "
            f"produced its score — the caller/UI has no way to know if it was fabricated: {iteration}"
        )
    assert _iteration_path(result.iterations[0]) == "local"
    assert _iteration_path(result.iterations[1]) == "degraded"


# ---------------------------------------------------------------------------
# 2 — the loop must not silently declare success off a fabricated number
# ---------------------------------------------------------------------------


def test_loop_does_not_declare_success_on_degraded_scores():
    """A single pass whose ``overall`` CROSSES ``target_score`` purely
    because the semantic component came back as the 50.0 degraded
    placeholder rather than a genuine measurement — the exact contamination
    the review flagged. The loop must not report ``success`` (nor skip
    ``requires_review``) off that number, however cleanly it appears to
    clear the bar."""
    from app.services.tailoring_loop import TailoringLoop

    service = _CountingService()
    ats = _StepwiseATSWithPath(overalls=[90.0], semantic_paths=["degraded"])
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=1, target_score=85.0)

    result = loop.run(_RESUME, _JD, originals=_ORIGINALS)

    assert result.success is False, (
        "loop declared success on a score whose semantic component was the "
        f"degraded (fabricated) placeholder — result.success={result.success}, "
        f"best_score={result.best_score}, iterations={result.iterations}"
    )
    assert result.requires_review is True, (
        "a degraded-score result must always require human review, regardless "
        "of the numeric overall score"
    )
    assert result.warning, "an honest warning must explain why a score that cleared target was not accepted"
    assert "degrad" in result.warning.lower(), (
        f"warning must name the degradation as the reason (not just repeat the score gap): {result.warning!r}"
    )


# ---------------------------------------------------------------------------
# 3 — baseline/tailored/lift (tailor_agent._compute_conversion_metrics) must
#     also be flagged when either endpoint of the delta was degraded
# ---------------------------------------------------------------------------


def test_baseline_and_tailored_scores_are_flagged_when_degraded(monkeypatch):
    """``TailorRunResult.conversionMetrics`` (tailor_agent.py:74-119) computes
    ``baselineATSScore`` / ``tailoredATSScore`` / ``estimatedConversionLift``
    from two independent ``ATSEngine().score()`` calls with no check on
    either result's ``semantic_path`` — a 'lift' computed from two
    placeholders (or one placeholder vs. one genuine score) is a fabricated
    business metric shown to the user as a real optimisation result."""
    from app.agents import tailor_agent

    class _SeqEngine:
        """First call (baseline) degraded, second call (tailored) genuine —
        still means the delta/lift is built on a fabricated baseline."""

        def __init__(self, paths: list[str]) -> None:
            self._paths = paths
            self._n = 0

        def score(self, resume_text, job_description):  # noqa: ANN001
            idx = min(self._n, len(self._paths) - 1)
            path = self._paths[idx]
            self._n += 1
            overall = 40.0 if path == "degraded" else 78.0
            return ATSScore(
                overall=overall,
                keyword_match=overall,
                semantic_similarity=overall,
                experience_gap=overall,
                matched_keywords=[],
                missing_keywords=[],
                requires_review=overall < 60.0,
                semantic_path=path,
            )

    monkeypatch.setattr(tailor_agent, "ATSEngine", lambda: _SeqEngine(["degraded", "local"]))

    metrics = tailor_agent._compute_conversion_metrics(
        original_text="Backend engineer with Python.",
        original_bullets=[{"text": "Built APIs.", "evidenceRef": "b0"}],
        tailored_bullets=[{"text": "Built scalable APIs.", "evidenceRef": "b0"}],
        job_description="Looking for a backend engineer.",
    )

    flag_keys = ("baselineDegraded", "tailoredDegraded", "scoringDegraded", "semanticPath", "semantic_path", "degraded")
    flagged = any(metrics.get(key) for key in flag_keys)
    withheld = metrics.get("baselineATSScore") is None or metrics.get("tailoredATSScore") is None
    assert flagged or withheld, (
        "baselineATSScore/tailoredATSScore/estimatedConversionLift are computed "
        "from scores where the baseline endpoint was degraded, with NO flag and "
        f"NO withholding anywhere in the payload — a fabricated 'lift' presented "
        f"as a real business metric: {metrics}"
    )


# ---------------------------------------------------------------------------
# 4 — positive control: genuine scores must behave exactly as today
# ---------------------------------------------------------------------------


def test_loop_succeeds_normally_on_genuine_scores():
    """Once the degraded-guard lands, a run where every iteration's
    ``semantic_path == "local"`` must behave EXACTLY as the loop does today
    (success/requires_review/warning/best_score unchanged) — the guard must
    never over-fire on a genuine result. This also ties to test 1 above: the
    per-iteration path must be recorded and must read back as the genuine
    value used, which is what currently makes this positive control fail
    (the success/requires_review/warning/best_score half is already correct
    and must stay that way)."""
    from app.services.tailoring_loop import TailoringLoop

    service = _CountingService()
    ats = _StepwiseATSWithPath(overalls=[40.0, 90.0], semantic_paths=["local", "local"])
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=5, target_score=85.0)
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS)

    assert result.success is True
    assert result.requires_review is False
    assert result.warning is None
    assert result.best_score == 90.0
    for iteration in result.iterations:
        assert _iteration_path(iteration) == "local", (
            f"positive-control iteration is missing/mismatched semantic_path (expected 'local'): {iteration}"
        )
