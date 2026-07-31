"""Score-aware iterative tailoring loop (GOLD-MASTER-V2 §5.3, gate G-C).

``app.services.resume_tailor.ResumeTailorService`` performs exactly ONE LLM
pass per call. :class:`TailoringLoop` wraps it (and the deterministic
:class:`~app.services.ats_engine.ATSEngine`) in a score-aware retry: tailor,
score, and — while the score stays below ``target_score`` and iterations
remain — re-run with a directive that names the score gap and the
still-missing JD keywords, so the next pass has something concrete to close.

Exit conditions (§5.3 item 1):

- ``ats_score >= target_score`` (default 85.0) — stop immediately, success.
- ``iteration == max_iterations`` (default 5) — stop, report the BEST score
  actually achieved and an honest sub-target warning. The loop NEVER reports
  success for a score below target, however close it got (§5.3.1 point 5).

The anti-fabrication entailment guard inside :class:`ResumeTailorService`
runs unmodified on every iteration — closing a keyword gap never means
inventing experience the candidate does not have. A directive that keeps
proposing an unsupported keyword is simply rejected again and again; the
loop's score-tracking already prefers whichever iteration scored highest, so
a run that can never close a gap truthfully honestly reports failure rather
than fabricating its way to 85.

Design note on the retry directive: it is intentionally SELF-CONTAINED — it
never re-embeds the original job description's raw prose. Ordinary JD prose
routinely contains contraction fragments ("we're" tokenizes to "re" on the
apostrophe) and generic words ("about") that are not in
``app.services.ats_engine._STOPWORDS``; re-emitting that prose into a
"cleaned" directive would silently reintroduce exactly the tokenization noise
this module exists to strip. The directive instead names the score gap and
the CLEAN gap keywords directly — which is also strictly more actionable for
the model than repeating prose it already saw on the first pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.ats_engine import _STOPWORDS as _ATS_STOPWORDS
from app.services.resume_tailor import strip_bullet_lines

#: §5.3 item 1: no existing cap governs a *multi-pass* tailoring loop —
#: ``AETHER_LLM_BUDGET_SECONDS`` / ``get_budget_seconds()`` bounds a single
#: LLM client's wall-clock life (armed once, shared by every call made on
#: that client instance — see ``LLMClient._remaining_budget``), not an
#: iteration count. Because :class:`TailoringLoop` is handed ONE
#: ``ResumeTailorService`` (and therefore one ``LLMClient``) and reuses it
#: across every iteration, that existing per-client budget already bounds the
#: loop's total live-call wall-clock time for free; on top of it, 5 is the
#: iteration ceiling this module adds.
DEFAULT_MAX_ITERATIONS = 5

#: §5.3 item 1 / hard rule: the ATS score at which tailoring is "done".
DEFAULT_TARGET_SCORE = 85.0

#: Contraction fragments that a naive apostrophe split leaves behind
#: ("we're" -> "we" + "re", "we'll" -> "we" + "ll", "I've" -> "i" + "ve").
_CONTRACTION_FRAGMENTS = frozenset({"re", "ll", "ve", "d", "m", "s", "t"})

#: Generic non-skill words the docstring/tests call out explicitly — carry no
#: checkable skill signal even though they are not in ``ats_engine._STOPWORDS``.
_GENERIC_NOISE = frozenset({"use", "uses", "used", "using", "about"})


def clean_gap_keywords(raw: list[str]) -> list[str]:
    """Strip tokenization noise from ``ATSScore.missing_keywords``.

    Drops bare 1-2 char fragments (covers "re", "ll", "ve", "xz", "a", ...),
    generic non-skill words ("use", "about") and duplicates, while preserving
    real multi-char skill keywords and their first-seen order — so the
    per-iteration directive only ever asks the model to surface real,
    checkable skill terms.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_kw in raw:
        token = (raw_kw or "").strip().lower()
        if len(token) <= 2:
            continue
        if token in _CONTRACTION_FRAGMENTS or token in _GENERIC_NOISE:
            continue
        if token in _ATS_STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


class _TailorServiceLike(Protocol):
    def tailor(
        self,
        resume_text: str,
        job_description: str,
        originals: Any = None,
        evidence_extra: str = "",
    ) -> Any: ...


class _ATSEngineLike(Protocol):
    def score(self, resume_text: str, job_description: str) -> Any: ...


@dataclass
class TailoringLoopResult:
    """Outcome of a full :meth:`TailoringLoop.run` — every iteration's output
    + score (so the UI can show progress honestly, §5.3.3), plus the winning
    iteration and an honest verdict (§5.3.1 point 5)."""

    #: One entry per iteration actually run:
    #: {"iteration", "score", "bullets", "changes", "gapKeywords", "rejected"}.
    iterations: list[dict[str, Any]] = field(default_factory=list)
    #: Bullets of the BEST-scoring iteration (never a lower-scoring later one).
    final_bullets: list[dict[str, str]] = field(default_factory=list)
    best_score: float = 0.0
    #: 1-based index into ``iterations`` of the best-scoring pass.
    best_iteration: int = 0
    #: True iff ``best_score >= target_score`` — NEVER true otherwise.
    success: bool = False
    #: == ``not success``. Wired to the existing ``ATSScore.requires_review``
    #: signal's spirit: a sub-target result always needs a human look.
    requires_review: bool = True
    #: Populated iff ``requires_review``; always names the best score achieved.
    warning: str | None = None


class TailoringLoop:
    """Score-aware wrapper around a tailor service + ATS engine.

    ``service``/``ats_engine`` are duck-typed to
    ``ResumeTailorService``/``ATSEngine`` (see module docstring) so tests can
    pin the loop's own mechanics with lightweight stubs while production code
    wires the real, LLM-backed instances — every iteration's tailoring call
    goes through the app's real configured LLM routing exactly like the
    single-pass path did; the loop only decides whether to call it again.
    """

    def __init__(
        self,
        service: _TailorServiceLike,
        ats_engine: _ATSEngineLike,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        target_score: float = DEFAULT_TARGET_SCORE,
    ) -> None:
        self._service = service
        self._ats = ats_engine
        self.max_iterations = max_iterations
        self.target_score = target_score

    def run(
        self,
        resume_text: str,
        job_description: str,
        *,
        originals: Any = None,
        evidence_extra: str = "",
    ) -> TailoringLoopResult:
        iterations: list[dict[str, Any]] = []
        best_bullets: list[dict[str, str]] = []
        best_score = -1.0
        best_iteration = 0

        current_originals = originals
        current_jd = job_description

        for i in range(1, self.max_iterations + 1):
            tailor_result = self._service.tailor(
                resume_text,
                current_jd,
                originals=current_originals,
                evidence_extra=evidence_extra,
            )
            corpus = self._corpus(resume_text, tailor_result.bullets)
            ats_score = self._ats.score(corpus, job_description)
            gap_keywords = clean_gap_keywords(list(ats_score.missing_keywords))

            iterations.append({
                "iteration": i,
                "score": ats_score.overall,
                "bullets": tailor_result.bullets,
                "changes": tailor_result.changes,
                "gapKeywords": gap_keywords,
                "rejected": tailor_result.rejected,
            })

            if ats_score.overall > best_score:
                best_score = ats_score.overall
                best_bullets = tailor_result.bullets
                best_iteration = i

            if ats_score.overall >= self.target_score:
                break

            # Prepare the next pass: feed this iteration's output forward as
            # the new baseline, plus a directive naming the score gap and the
            # clean gap keywords (never the raw JD prose — see module docstring).
            current_originals = tailor_result.bullets
            current_jd = self._build_directive(ats_score.overall, gap_keywords)

        success = best_score >= self.target_score
        requires_review = not success
        warning = None
        if requires_review:
            warning = (
                f"Tailoring stopped after {len(iterations)} iteration(s) "
                f"without reaching the target ATS score of "
                f"{self.target_score:.0f}. Best score achieved: "
                f"{best_score:.1f}/100. Please review this resume manually "
                "before submitting."
            )

        return TailoringLoopResult(
            iterations=iterations,
            final_bullets=best_bullets,
            best_score=best_score,
            best_iteration=best_iteration,
            success=success,
            requires_review=requires_review,
            warning=warning,
        )

    # -- internals -------------------------------------------------------

    @staticmethod
    def _corpus(resume_text: str, bullets: list[dict[str, str]]) -> str:
        """Résumé context (skills/summary/headers) + bullet text — the same
        like-for-like corpus ``_compute_conversion_metrics`` scores, so the
        loop's own convergence decisions match what the UI ultimately shows.
        """
        context = strip_bullet_lines(resume_text)
        bullet_text = "\n".join(b.get("text", "") for b in bullets)
        return f"{context}\n{bullet_text}" if context else bullet_text

    def _build_directive(self, score: float, gap_keywords: list[str]) -> str:
        """A self-contained retry directive naming the score gap and the
        clean gap keywords still missing — never the raw original JD prose
        (see module docstring: that would reintroduce tokenization noise)."""
        gap = max(0.0, self.target_score - score)
        lines = [
            "TAILORING DIRECTIVE (iterative refinement retry).",
            f"The previous draft scored {score:.1f}/100 against an ATS "
            f"target of {self.target_score:.0f}/100 (a gap of {gap:.1f} "
            "points).",
        ]
        if gap_keywords:
            lines.append(
                "Close the gap by TRUTHFULLY surfacing these still-missing, "
                "job-relevant keywords wherever the candidate's own "
                "evidence genuinely supports them. NEVER invent or "
                "fabricate a skill, tool or achievement the candidate does "
                "not have — an unsupported keyword must stay out: "
                + ", ".join(gap_keywords)
                + "."
            )
        else:
            lines.append(
                "Continue strengthening the resume's alignment with the "
                "role using only truthful, evidence-backed language."
            )
        return "\n".join(lines)
