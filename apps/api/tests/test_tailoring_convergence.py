"""W-TAILOR-CONVERGE — the tailoring loop must actually converge.

MEASURED CAUSE (live production data, 2026-08-02, real rows in the ``aether``
schema — see the run report for the full decomposition):

1. **Iterations 2-5 never saw the job description.** ``TailoringLoop.run``
   did ``current_jd = self._build_directive(...)`` and passed THAT as the
   ``job_description`` argument of the next ``ResumeTailorService.tailor``
   call. The real posting was therefore invisible from pass 2 onward — both
   to the rewrite prompt AND to ``select_bullets_to_tailor``, whose
   ``jd_key_stems`` were then computed from the directive's own boilerplate
   ("tailoring directive iterative refinement retry previous draft scored…").

2. **Only ``AETHER_TAILOR_MAX_BULLETS`` (8) bullets were EVER eligible.**
   Resume ``c875546f41138d92c60ceb428`` (Insurance Product Manager @
   safetyculture) has 25 bullets; across all 5 iterations exactly 8 distinct
   bullets ever changed — bullet-1/4/10/11/13/14/16/19. The other 17 (68% of
   the résumé) could never be touched, because the top-K selector's ranking
   is deterministic and nothing told it a bullet had already had its turn.

3. **The directive asked for keywords the candidate has NO evidence for.**
   Same run: of the 40 TF-IDF JD keywords, 21 ("underwriting", "lloyd",
   "surplus", "carrier", …) appear nowhere in the candidate's résumé, story
   bank or career data. Asking for them can only ever produce a rewrite the
   entailment guard rejects — live rejected counts were 5, 4, 1, 0, 3 per
   iteration. Those keywords are UNREACHABLE without fabricating, and the
   loop must say so instead of burning passes on them.

None of these tests weaken the anti-fabrication/entailment guard: (3) makes
the loop stop *asking* for unsupported keywords, which is strictly stricter,
and (2) only changes which bullets are SHOWN to the model — every rewrite
still goes through the same guard.
"""
from __future__ import annotations

import re
from typing import Any

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
_JD = (
    "Backend Engineer at Acme. We're looking for someone who cares about "
    "Kubernetes and Kafka and about distributed systems."
)


class _RecordingService:
    """Records every ``(job_description, originals, kwargs)`` it is handed."""

    def __init__(self, bullets_by_call: list[list[dict[str, str]]] | None = None) -> None:
        self.jd_by_call: list[str] = []
        self.originals_by_call: list[list[dict[str, str]]] = []
        self.kwargs_by_call: list[dict[str, Any]] = []
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
        self.originals_by_call.append([dict(b) for b in (originals or [])])
        self.kwargs_by_call.append(dict(kwargs))
        if self._bullets_by_call is not None:
            bullets = [dict(b) for b in self._bullets_by_call[idx]]
        else:
            bullets = [dict(b) for b in (originals or _ORIGINALS)]
        return TailorResult(bullets=bullets, changes=1, originals=list(originals or _ORIGINALS))

    @property
    def calls(self) -> int:
        return len(self.jd_by_call)


class _StepwiseATS:
    def __init__(self, overalls: list[float], missing_keywords: list[str] | None = None) -> None:
        self._overalls = overalls
        self._missing = missing_keywords or []
        self.calls = 0

    def score(self, resume_text: str, job_description: str) -> ATSScore:
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
            semantic_path="local",
        )


# --- cause 1: the real JD must survive every iteration ----------------------


def test_every_iteration_still_receives_the_real_job_description() -> None:
    """Cause 1. The retry directive must be ADDED to the posting, never
    SUBSTITUTED for it: a pass that cannot see the job description cannot
    align the résumé to it, and the top-K bullet selector then ranks bullets
    against the directive's own boilerplate instead of the role."""
    from app.services.tailoring_loop import TailoringLoop

    service = _RecordingService()
    ats = _StepwiseATS([40.0, 41.0, 42.0], missing_keywords=["kubernetes", "kafka"])
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=3)
    loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert service.calls == 3
    for i, jd in enumerate(service.jd_by_call, start=1):
        assert _JD in jd, (
            f"iteration {i} lost the real job description — it received:\n{jd}"
        )


def test_retry_directive_is_appended_and_stays_noise_free() -> None:
    """The directive half must still be free of the tokenization noise
    (``re``/``ll``/``about``/``use``) that poisoned earlier versions — that
    guarantee now applies to the DIRECTIVE SECTION, since the posting itself
    is (correctly) reproduced verbatim above it."""
    from app.services.tailoring_loop import DIRECTIVE_MARKER, TailoringLoop

    service = _RecordingService()
    ats = _StepwiseATS(
        [40.0, 40.0, 40.0],
        missing_keywords=["about", "ll", "re", "use", "kubernetes", "kafka"],
    )
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=3)
    loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert service.jd_by_call[0] == _JD, "first pass must not be altered"
    assert DIRECTIVE_MARKER in service.jd_by_call[1]
    directive = service.jd_by_call[1].split(DIRECTIVE_MARKER, 1)[1].lower()
    assert re.search(r"\bkafka\b", directive), directive
    for noise in ("about", "ll", "use"):
        assert not re.search(rf"\b{noise}\b", directive), (
            f"tokenization noise {noise!r} leaked into the directive: {directive}"
        )


# --- cause 3: never ask for a keyword the evidence cannot support -----------


def test_directive_only_asks_for_evidence_supported_gap_keywords() -> None:
    """Cause 3. ``kafka`` is in the candidate's own résumé evidence, so it is
    genuinely closable. ``underwriting`` is nowhere in their evidence — asking
    for it can only produce a rewrite the entailment guard rejects, so the
    directive must NOT request it, and must name it as unreachable instead."""
    from app.services.tailoring_loop import DIRECTIVE_MARKER, TailoringLoop

    service = _RecordingService()
    ats = _StepwiseATS(
        [40.0, 40.0],
        missing_keywords=["kafka", "underwriting", "reinsurance"],
    )
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=2)
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    directive = service.jd_by_call[1].split(DIRECTIVE_MARKER, 1)[1].lower()
    surface = directive.split("never invent")[0]
    assert "kafka" in surface, directive
    assert "underwriting" not in surface, (
        "the loop asked the model to surface a keyword the candidate has NO "
        f"evidence for — that can only end in a guard rejection: {directive}"
    )
    assert "underwriting" in result.unreachable_keywords, result.unreachable_keywords
    assert "kafka" not in result.unreachable_keywords, result.unreachable_keywords
    first = result.iterations[0]
    assert first["supportedGapKeywords"] == ["kafka"], first
    assert set(first["unsupportedGapKeywords"]) == {"underwriting", "reinsurance"}, first


def test_warning_names_the_unreachable_keywords_honestly() -> None:
    """A sub-target run must explain WHY it is sub-target — including the JD
    keywords no truthful rewrite can ever add. It must never imply the target
    was reachable, and never round the achieved score up."""
    from app.services.tailoring_loop import TailoringLoop

    service = _RecordingService()
    ats = _StepwiseATS([42.5, 42.5], missing_keywords=["underwriting"])
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=2)
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert result.success is False
    assert result.best_score == 42.5
    assert "42.5" in (result.warning or ""), result.warning
    assert "underwriting" in (result.warning or ""), result.warning
    assert result.stop_reason == "iteration_cap", result.stop_reason


# --- cause 2: every bullet must eventually become eligible ------------------


def test_loop_rotates_bullet_selection_so_untouched_bullets_get_a_turn() -> None:
    """Cause 2. The loop must tell the tailor service which bullets have
    already been rewritten, so the deterministic top-K selector stops handing
    the model the same 8 bullets on every pass while 17 others stay frozen."""
    from app.services.tailoring_loop import TailoringLoop

    service = _RecordingService(
        bullets_by_call=[
            [
                {"text": "Built backend services handling 500 requests per day, on Kubernetes.",
                 "evidenceRef": "bullet-0"},
                {"text": "Ran the Kafka ingestion pipeline for the billing team.",
                 "evidenceRef": "bullet-1"},
            ],
            [
                {"text": "Built backend services handling 500 requests per day, on Kubernetes.",
                 "evidenceRef": "bullet-0"},
                {"text": "Ran the Kafka ingestion pipeline for the billing team.",
                 "evidenceRef": "bullet-1"},
            ],
        ]
    )
    ats = _StepwiseATS([40.0, 41.0], missing_keywords=["kafka"])
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=2)
    loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert service.kwargs_by_call[0].get("already_tailored_refs") == frozenset()
    assert service.kwargs_by_call[1].get("already_tailored_refs") == frozenset({"bullet-0"}), (
        "iteration 2 must know bullet-0 already had its rewrite, so the "
        "selector can give an untouched bullet a turn: "
        f"{service.kwargs_by_call[1]}"
    )


def test_select_bullets_deprioritises_already_tailored_refs() -> None:
    """The selector half of the same fix, pinned directly: with a cap of 1 and
    bullet-0 already rewritten, the untouched bullet must be chosen even
    though bullet-0 still ranks higher on raw JD overlap."""
    from app.services.resume_tailor import select_bullets_to_tailor

    structured = [
        {"text": "Ran Kafka and Kubernetes pipelines end to end.", "evidenceRef": "bullet-0"},
        {"text": "Ran the billing service.", "evidenceRef": "bullet-1"},
    ]
    resume_text = "\n".join(b["text"] for b in structured)
    jd = "Kafka Kubernetes pipelines engineer"

    plain = select_bullets_to_tailor(structured, jd, resume_text, "", max_bullets=1)
    assert [b["evidenceRef"] for b in plain] == ["bullet-0"]

    rotated = select_bullets_to_tailor(
        structured, jd, resume_text, "", max_bullets=1,
        already_tailored_refs={"bullet-0"},
    )
    assert [b["evidenceRef"] for b in rotated] == ["bullet-1"], rotated


# --- best-scoring draft must be what the next pass builds on ----------------


def test_next_iteration_builds_on_the_best_draft_not_a_regression() -> None:
    """Iteration 2 scored WORSE than iteration 1. Feeding its (worse) bullets
    into iteration 3 compounds the regression; the loop must hand forward the
    best-scoring draft it has, which is what it will ultimately return."""
    from app.services.tailoring_loop import TailoringLoop

    good = [{"text": "GOOD draft bullet.", "evidenceRef": "bullet-0"}]
    bad = [{"text": "BAD draft bullet.", "evidenceRef": "bullet-0"}]
    service = _RecordingService(bullets_by_call=[good, bad, good])
    ats = _StepwiseATS([60.0, 30.0, 60.0], missing_keywords=["kafka"])
    loop = TailoringLoop(service=service, ats_engine=ats, max_iterations=3)
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS, evidence_extra="")

    assert service.originals_by_call[2] == good, (
        "iteration 3 was seeded with the LOWER-scoring iteration-2 draft: "
        f"{service.originals_by_call[2]}"
    )
    assert result.final_bullets == good
    assert result.best_score == 60.0
