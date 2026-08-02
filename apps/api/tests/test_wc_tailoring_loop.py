"""GOLD-MASTER-V2 §5.4 (gate G-C) — failing unit tests for the score-aware
iterative tailoring loop (§5.3 items 1, 2, 3, 4, 6).

CURRENT STATE (measured this run, 2026-07-31): `app.services.resume_tailor`
is a SINGLE LLM pass with a per-bullet non-regression guard — there is NO
score-aware loop anywhere in the codebase, and `app.services.tailoring_loop`
does not exist. Live measurement: tailoring yields a +0.10 ATS delta that
rounds to +0.0% in the UI; all 51 production jobs sampled score 24.89-50.05
(avg 39.63), every one below the 85 target. The 0-change outcome is the
anti-fabrication entailment guard CORRECTLY refusing to invent experience the
résumé lacks — that behaviour is preserved and re-asserted here (item 6), not
weakened.

`ATSEngine.missing_keywords` (the raw candidate for "gap_keywords") carries
tokenization noise today — reproduced live against the real, currently-running
`app.services.ats_engine.ATSEngine`:

    >>> ATSEngine().score(
    ...     "I am a backend engineer with Python experience.",
    ...     "We're looking for a Senior Backend Engineer who cares deeply "
    ...     "about scalability. You'll use Python and Kubernetes daily.",
    ... ).missing_keywords
    [...'about', ..., 're', ...'use', ...]

("re" comes from "we're"/"we'll" splitting on the apostrophe; "ll" from
"we'll"; neither "re", "ll", "use" nor "about" is in `ats_engine._STOPWORDS`.)
Any convergence directive built from the raw list is poisoned by this noise.

BINDING CONTRACT these tests assume for the not-yet-built module
`app.services.tailoring_loop` (test-author defines the interface here;
`ai-loop-engineer` implements against it — this is the FIX-1-style
"failing tests before implementation" pattern):

    class TailoringLoop:
        def __init__(self, service, ats_engine,
                     max_iterations: int = 5, target_score: float = 85.0): ...
        def run(self, resume_text, job_description, *, originals=None,
                evidence_extra="") -> TailoringLoopResult: ...

    @dataclass
    class TailoringLoopResult:
        iterations: list[dict]     # [{"iteration": int, "score": float,
                                    #   "bullets": [...], "changes": int,
                                    #   "gapKeywords": [str, ...]}, ...]
        final_bullets: list[dict]  # bullets of the BEST-scoring iteration
        best_score: float
        best_iteration: int        # 1-based
        success: bool              # best_score >= target_score
        requires_review: bool      # == not success
        warning: str | None        # populated iff requires_review, must
                                    # name the best_score achieved

    def clean_gap_keywords(raw: list[str]) -> list[str]:
        # Strips tokenization noise (contraction fragments, bare 1-2 char
        # tokens, generic non-skill words like "use"/"about") from
        # ATSScore.missing_keywords so the per-iteration directive only ever
        # asks the model to surface real, checkable skill terms.

`service` and `ats_engine` are duck-typed to `ResumeTailorService`
(`.tailor(resume_text, job_description, originals=None, evidence_extra="")
-> TailorResult`) and `ATSEngine` (`.score(resume_text, job_description) ->
ATSScore`) respectively — real instances are used wherever a test needs the
REAL anti-fabrication guard (item 6); lightweight stubs are used elsewhere to
pin the loop's own mechanics deterministically.
"""
from __future__ import annotations

import re

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


class _StepwiseATS:
    """Returns a pre-programmed sequence of ``overall`` scores, one per call;
    holds the LAST value for any call beyond the sequence (safety net so a
    loop bug that over-iterates doesn't crash the test with an IndexError —
    the call-count assertions in each test catch that instead)."""

    def __init__(self, overalls: list[float], missing_keywords: list[str] | None = None) -> None:
        self._overalls = overalls
        self._missing = missing_keywords or []
        self.calls = 0

    def score(self, resume_text, job_description) -> ATSScore:  # noqa: ANN001
        idx = min(self.calls, len(self._overalls) - 1)
        overall = self._overalls[idx]
        self.calls += 1
        return ATSScore(
            overall=overall,
            keyword_match=overall,
            semantic_similarity=overall,
            experience_gap=overall,
            matched_keywords=[],
            missing_keywords=list(self._missing),
            requires_review=overall < 60.0,
        )


# --- 1. TailoringLoop exists and iterates -----------------------------------


def test_loop_uses_discovered_default_of_five_and_stops_once_target_reached():
    """§5.3 item 1: default ``max_iterations`` is 5 (no existing cap was found
    that governs a *multi-pass* tailoring loop — ``AETHER_LLM_BUDGET_SECONDS``
    / ``get_budget_seconds()`` governs a single LLM call's wall-clock budget,
    not an iteration count, per ``app/services/llm_client.py``). The loop must
    actually iterate (call the tailor service again) when the score stays
    below target, and stop the moment the target is cleared."""
    from app.services.tailoring_loop import TailoringLoop

    service = _CountingService()
    ats = _StepwiseATS([40.0, 60.0, 88.0])
    loop = TailoringLoop(service=service, ats_engine=ats)
    assert loop.max_iterations == 5

    result = loop.run(_RESUME, _JD, originals=_ORIGINALS)
    assert service.calls > 1, "loop never iterated past the first pass"
    assert service.calls == 3, "loop must stop the moment ats_score >= 85"
    assert len(result.iterations) == 3
    assert result.best_score == 88.0
    assert result.success is True


# --- 2. gap_keywords: clean + passed each iteration -------------------------


def test_clean_gap_keywords_strips_tokenization_noise():
    """§5.3 item 2: ``clean_gap_keywords`` must strip contraction fragments /
    bare 1-2 char tokens / generic non-skill noise ("re", "ll", "use",
    "about", "a", and any bare 2-char fragment) while keeping real multi-char
    skill keywords — otherwise the loop's convergence directive is poisoned
    by garbage on every single iteration."""
    from app.services.tailoring_loop import clean_gap_keywords

    raw = ["about", "ll", "re", "use", "kubernetes", "kafka", "a", "xz"]
    cleaned = clean_gap_keywords(raw)
    for noise in ("about", "ll", "re", "use", "a", "xz"):
        assert noise not in cleaned, f"{noise!r} leaked into cleaned gap_keywords: {cleaned}"
    for keep in ("kubernetes", "kafka"):
        assert keep in cleaned, f"{keep!r} wrongly dropped from cleaned gap_keywords: {cleaned}"


def test_loop_embeds_clean_gap_keywords_directive_into_next_iteration():
    """§5.3 item 2: each iteration after the first must hand the tailor
    service a directive embedding the PREVIOUS iteration's CLEAN gap
    keywords — this is what is supposed to drive convergence. The directive
    must not carry the tokenization noise a naive pass-through of
    ``ATSScore.missing_keywords`` would (see the previous test / module
    docstring for the live reproduction of that noise).

    AMENDED (W-TAILOR-CONVERGE, 2026-08-02). This test originally required the
    directive to REPLACE the job description outright, which is what the
    implementation did. Measured live, that was the loop's biggest defect:
    with the posting gone from iteration 2 onward, ``select_bullets_to_tailor``
    ranked bullets against the directive's own boilerplate and the rewrite
    prompt could no longer mirror the role's terminology at all (résumé
    ``c875546f41138d92c60ceb428``: 5 iterations, +4.2 ATS points total, and
    only 8 of 25 bullets ever eligible).

    The noise requirement the test exists to protect is UNCHANGED and still
    asserted — it now applies to the DIRECTIVE SECTION, which is the only part
    the loop authors. The posting itself is reproduced verbatim above the
    marker, and reproducing it cannot reintroduce tokenization noise into the
    keyword list, because that list comes from ``ATSScore.missing_keywords``
    via ``clean_gap_keywords`` — never from the directive text.

    NOTE the JD deliberately contains "we're" and "about": if a future change
    reverted to splicing raw JD prose into the KEYWORD REQUEST, the
    ``surface`` assertions below would catch it.
    """
    from app.services.tailoring_loop import DIRECTIVE_MARKER, TailoringLoop

    service = _CountingService()
    ats = _StepwiseATS(
        [40.0, 40.0, 40.0],
        missing_keywords=["about", "ll", "re", "use", "kubernetes", "kafka"],
    )
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=3)
    # ``evidence_extra`` carries the candidate's real evidence for both skills,
    # so both are genuinely closable and both belong in the directive.
    loop.run(
        _RESUME, _JD, originals=_ORIGINALS,
        evidence_extra="Ran Kubernetes clusters and Kafka pipelines in production.",
    )

    assert service.calls == 3
    assert service.jd_by_call[0] == _JD, "first pass must not be altered"
    full_2 = service.jd_by_call[1]
    assert _JD in full_2, "iteration 2 lost the real job description"
    assert DIRECTIVE_MARKER in full_2, "no gap-keyword directive was added for iteration 2"
    directive_2 = full_2.split(DIRECTIVE_MARKER, 1)[1].lower()
    # The keyword REQUEST — everything before the standing prohibition.
    surface = directive_2.split("never invent")[0]
    for keyword in ("kubernetes", "kafka"):
        assert re.search(rf"\b{keyword}\b", surface), (
            f"gap keyword {keyword!r} missing from iteration-2 directive: {directive_2}"
        )
    for noise in ("about", "ll", "re", "use"):
        assert not re.search(rf"\b{noise}\b", surface), (
            f"tokenization noise {noise!r} leaked into iteration-2 directive: {directive_2}"
        )


# --- 3. Exit conditions ------------------------------------------------------


def test_loop_exits_immediately_once_target_score_is_met():
    from app.services.tailoring_loop import TailoringLoop

    service = _CountingService()
    ats = _StepwiseATS([91.0, 91.0, 91.0])  # would trivially clear the bar every time
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=5, target_score=85.0)
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS)
    assert service.calls == 1, "loop must not keep iterating once the target is already met"
    assert len(result.iterations) == 1
    assert result.success is True


def test_loop_stops_at_max_iterations_when_score_never_reaches_target():
    from app.services.tailoring_loop import TailoringLoop

    service = _CountingService()
    ats = _StepwiseATS([40.0, 41.0, 42.0, 43.0])  # improves, but never gets near 85
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=4, target_score=85.0)
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS)
    assert service.calls == 4, "loop must stop exactly at the iteration cap, not run forever"
    assert len(result.iterations) == 4
    assert result.success is False


# --- 4. Honest failure: best-achieved score surfaced, never a false success -


def test_loop_surfaces_honest_warning_with_best_achieved_score_when_capped_out():
    """§5.3.1 point 5: when max_iterations is reached below target, the loop
    must surface an honest warning carrying the BEST score actually achieved
    — and must NEVER report success for a score below target, however close
    it got."""
    from app.services.tailoring_loop import TailoringLoop

    service = _CountingService()
    ats = _StepwiseATS([40.0, 55.0, 84.9])  # tantalisingly close, never crosses 85
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=3, target_score=85.0)
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS)

    assert result.success is False, "84.9 is below the 85 target — must never be reported as success"
    assert result.requires_review is True
    assert result.best_score == 84.9
    assert result.warning, "an honest sub-target warning must be surfaced"
    assert "84.9" in result.warning, result.warning
    assert "85" in result.warning, result.warning


# --- 6. Anti-fabrication preserved through the loop -------------------------


def test_loop_never_lets_a_fabricated_keyword_close_the_gap():
    """§5.3 item 6: the loop must never "reach 85" by inventing content the
    résumé/story bank doesn't support. Wired through the REAL
    ``ResumeTailorService`` (not a stub) so the existing anti-fabrication
    guard (``unsupported_tokens``) actually runs: the stub LLM repeatedly
    tries to inject "Kubernetes" — a skill the candidate's evidence never
    proves — no matter what directive the loop sends it. The guard must keep
    rejecting it every iteration, so the score can never climb via
    fabrication and the loop must honestly report failure rather than a
    false 85+. This test must FAIL if a future implementation "reaches 85"
    by fabricating."""
    from app.services.ats_engine import ATSEngine
    from app.services.resume_tailor import ResumeTailorService, _evidence_index, unsupported_tokens
    from app.services.tailoring_loop import TailoringLoop

    class _FabricationAttemptLLM:
        def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
            if prompt_name == "tailor":
                return {
                    "bullets": [
                        {
                            "text": "Built backend services on Kubernetes handling 500 requests per day.",
                            "evidenceRef": "bullet-0",
                        }
                    ],
                    "evidenceRefs": ["bullet-0"],
                }
            return {"results": []}

    service = ResumeTailorService(llm=_FabricationAttemptLLM())
    ats = ATSEngine()
    jd = "Backend Engineer. Requirements: Kubernetes, distributed systems."
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=3, target_score=85.0)
    result = loop.run(_RESUME, jd, originals=_ORIGINALS)

    stems, numbers = _evidence_index(_RESUME)
    for bullet in result.final_bullets:
        novel = unsupported_tokens(bullet["text"], stems, numbers)
        assert not novel, f"fabricated/unsupported tokens leaked through the loop: {novel}"
    assert "kubernetes" not in " ".join(b["text"] for b in result.final_bullets).lower()
    assert result.success is False, (
        "score reached >=85 despite every proposed change being an "
        "evidence-rejected fabrication attempt — the anti-fabrication guard was bypassed"
    )
