"""Per-artifact quality FLOOR enforcement — the 80%-across-all-dimensions gate.

The product already MEASURED each artifact's dimensions and already knew what
the floor was; it simply never acted on either. ``ATSScore`` breaks a tailored
résumé into keyword match, semantic similarity and experience match;
``CoverLetterQuality`` breaks a letter into JD alignment, evidence grounding
and structure; ``quality_policy.DIMENSION_FLOOR`` says every dimension must be
strictly ABOVE 80%. Until this module, a résumé whose keyword match was 61%
shipped exactly like one at 91% — the numbers were displayed and discarded.

This module is the single place that turns those measurements into a VERDICT.
It is deliberately tiny and pure: no LLM, no clock, no DB, no randomness. The
same scores always produce the same verdict and the same words, which is what
lets the run card, the Studio, the approval modal and the persisted run record
all quote ONE sentence instead of four paraphrases.

Four honesty rules, each of which a test pins:

1. **One floor.** :data:`QUALITY_FLOOR` IS ``quality_policy.DIMENSION_FLOOR``,
   imported rather than re-typed. Two thresholds with the same name and
   different values is how a product starts lying to itself.
2. **Never scored, never guessed.** A dimension that could not be MEASURED —
   semantic similarity when ``ATSScore.semantic_path`` is not a genuine
   measurement path, JD alignment when the posting yielded no
   evidence-supported keywords — is neither passed nor failed on its
   placeholder value. It blocks the gate and is reported as ``not measured``.
   Failing CLOSED is the only safe direction: the alternative is certifying a
   dimension nobody measured.
3. **Bounded effort.** :func:`gate_extra_attempts` reads an env-capped small
   integer. Every extra attempt is a whole extra LLM generation, and the plan
   spend cap is checked PRE-run (``docs/subscription/billing-architecture.md``:
   a run already in flight is never interrupted), so the gate must bound its
   own worst case rather than lean on the cap to stop it.
4. **Below the floor is a STATE, not a silence.** A gate failure never
   suppresses the artifact and never inflates the score. The artifact ships,
   flagged, with the failing dimensions and their REAL numbers — and a human
   must acknowledge that explicitly before approving it
   (:func:`acknowledgement_label`).

The guards are untouched by everything here. Nothing in this module can make a
fabricated claim acceptable: a rewrite that would clear a dimension by
inventing evidence is rejected by ``resume_tailor``/``cover_letter_agent``
exactly as before, and the honest (lower) score is what this module then judges.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

#: THE floor: "10-dimensional fit score > 80% across ALL dimensions" (U2c/U5
#: ENRICHMENT MANDATE). A dimension sitting exactly AT 80.0 has not cleared it.
#:
#: This module owns the constant and ``services.quality_policy.DIMENSION_FLOOR``
#: is bound to it, rather than the other way round, purely to keep the import
#: graph acyclic: ``quality_policy`` imports ``tailoring_loop`` (for the shipped
#: rigor defaults) and ``tailoring_loop`` imports THIS module (to judge each
#: attempt), so the floor has to live at the leaf. One definition either way —
#: which is the property that actually matters.
QUALITY_FLOOR: float = 80.0

#: Extra bounded attempts the gate may spend on ONE run beyond what the
#: artifact's own loop already spends. Deliberately small: two.
DEFAULT_GATE_EXTRA_ATTEMPTS = 2

#: Hard ceiling regardless of configuration (see rule 3 above).
MAX_GATE_EXTRA_ATTEMPTS = 4

#: Operator override for :data:`DEFAULT_GATE_EXTRA_ATTEMPTS`.
GATE_ATTEMPTS_ENV = "AETHER_QUALITY_GATE_MAX_ATTEMPTS"

#: The ``semantic_path`` value that means the score is a PLACEHOLDER rather
#: than a measurement.
#:
#: This is deliberately the NARROW ``== "degraded"`` test, not the whitelist
#: (``in ("local", "hf_api")``) the SNAPSHOT consumers — resumes.py, jobs.py,
#: tailor_agent's conversion metrics — correctly use. The distinction is the
#: one ``tailoring_loop`` already argued for its own convergence check, and
#: this gate lives inside that same convergence decision:
#:
#: * ``"degraded"`` is the engine's own explicit verdict that no genuine
#:   embedding model or HF Inference API was available. Real ``ATSEngine.score``
#:   calls always set one of local/hf_api/degraded unambiguously, so in
#:   production this test and the whitelist behave identically.
#: * ``"untracked"`` is a DIFFERENT signal: the caller opted out of provenance
#:   for this dimension entirely (a test double pinning loop mechanics, a
#:   deterministic re-score). Reading that as "degraded" would (a) contradict
#:   the sibling convergence rule 40 lines away in ``tailoring_loop``, and
#:   (b) make every such run spend its bounded extra LLM attempts chasing a
#:   dimension no rewrite can move — the exact "burning passes on unreachable
#:   keywords" waste W-TAILOR-CONVERGE removed.
#:
#: A genuinely degraded dimension still BLOCKS the gate (it cannot be
#: certified), and :attr:`GateVerdict.closable` is what stops the loop paying
#: for attempts against it.
_DEGRADED_SEMANTIC_PATH = "degraded"

#: Artifact families this gate judges. Used verbatim as the ``artifact`` key of
#: the persisted verdict so a reader never has to guess which dimension set a
#: stored gate belongs to.
ARTIFACT_RESUME = "resume_tailor"
ARTIFACT_COVER_LETTER = "cover_letter"


def gate_extra_attempts() -> int:
    """Bounded extra attempts, from the environment. Never unbounded.

    Garbage or an absent value falls back to the shipped default; a negative
    value means "no extra attempts" (the artifact's own loop still runs in
    full); anything above :data:`MAX_GATE_EXTRA_ATTEMPTS` is clamped down to it.
    """
    raw = os.environ.get(GATE_ATTEMPTS_ENV)
    if raw is None or not str(raw).strip():
        return DEFAULT_GATE_EXTRA_ATTEMPTS
    try:
        requested = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_GATE_EXTRA_ATTEMPTS
    return max(0, min(requested, MAX_GATE_EXTRA_ATTEMPTS))


@dataclass(frozen=True)
class DimensionScore:
    """One measured (or explicitly unmeasured) dimension of one artifact."""

    key: str
    label: str
    #: The REAL score, or ``None`` when the dimension could not be measured.
    #: Never a placeholder standing in for a measurement.
    score: float | None
    floor: float = QUALITY_FLOOR
    measured: bool = True
    #: Populated iff ``not measured`` — the honest reason, in the user's words.
    unmeasured_reason: str | None = None

    @property
    def passed(self) -> bool:
        """Strictly ABOVE the floor, and genuinely measured.

        ``> floor`` (not ``>=``) matches ``quality_policy.compute_rigor_policy``,
        which treats a dimension sitting exactly AT 80.0 as not having cleared
        the bar.
        """
        return self.measured and self.score is not None and self.score > self.floor

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "score": self.score,
            "floor": self.floor,
            "measured": self.measured,
            "passed": self.passed,
            "unmeasuredReason": self.unmeasured_reason,
        }

    def describe(self) -> str:
        """This dimension's contribution to the honest failure sentence."""
        if not self.measured:
            return f"{self.label} (not measured — {self.unmeasured_reason})"
        return f"{self.label} ({self.score:.1f}% vs {self.floor:.0f}% floor)"


@dataclass(frozen=True)
class GateVerdict:
    """The gate's whole, deterministic answer for one artifact."""

    artifact: str
    floor: float
    dimensions: tuple[DimensionScore, ...]

    @property
    def failing(self) -> tuple[DimensionScore, ...]:
        return tuple(d for d in self.dimensions if not d.passed)

    @property
    def passed(self) -> bool:
        """True only when there is something to judge AND all of it cleared."""
        return bool(self.dimensions) and not self.failing

    @property
    def closable(self) -> bool:
        """True iff at least one failing dimension is one a REWRITE could move.

        A dimension that failed because it could not be MEASURED (degraded
        semantic scoring, an unmeasurable JD alignment) is a measurement
        problem, not a drafting problem: no amount of rewriting will change it,
        and every attempt spent on it is a paid LLM call bought for nothing.
        This is the same principle ``tailoring_loop.split_gap_keywords`` applies
        to unreachable keywords — stop ASKING for what cannot truthfully be
        delivered, and report it instead.
        """
        return any(d.measured for d in self.failing)

    @property
    def summary(self) -> str:
        """The one sentence every surface quotes — card, Studio, modal, run row.

        Names each failing dimension with its REAL number, so a user reading it
        can reconcile it against the score breakdown beside it without having
        to trust a rounded restatement.
        """
        if self.passed:
            return (
                f"Every quality dimension is above the {self.floor:.0f}% floor."
            )
        failing = self.failing
        noun = "dimension" if len(failing) == 1 else "dimensions"
        return (
            f"Below quality floor: {len(failing)} {noun} did not clear the "
            f"{self.floor:.0f}% floor — "
            + "; ".join(d.describe() for d in failing)
            + "."
        )

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable form persisted on the artifact, the approval and
        the ``AgentRun`` — one object, so no two surfaces can disagree."""
        return {
            "artifact": self.artifact,
            "floor": self.floor,
            "passed": self.passed,
            "dimensions": [d.as_dict() for d in self.dimensions],
            "failing": [d.as_dict() for d in self.failing],
            "failingLabels": [d.label for d in self.failing],
            "closable": self.closable,
            "summary": self.summary,
            "acknowledgementLabel": acknowledgement_label_for(len(self.failing)),
        }


def acknowledgement_label_for(failing_count: int) -> str:
    """The exact words the approve button carries for a below-floor artifact."""
    noun = "dimension" if failing_count == 1 else "dimensions"
    return f"Approve anyway — {failing_count} {noun} below floor"


def acknowledgement_label(verdict: GateVerdict) -> str:
    return acknowledgement_label_for(len(verdict.failing))


# ---------------------------------------------------------------------------
# Dimension sets — the REAL components each scorer already computes
# ---------------------------------------------------------------------------

#: ``(key, label, ATSScore attribute)``. ``overall`` is included deliberately:
#: a résumé whose weighted total sits below the floor has not cleared it either,
#: however healthy the individual parts look.
TAILORING_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ("overall", "Overall ATS", "overall"),
    ("keywordMatch", "Keyword Match", "keyword_match"),
    ("semanticSimilarity", "Semantic Similarity", "semantic_similarity"),
    ("experienceMatch", "Experience Match", "experience_gap"),
)

#: ``(key, label, CoverLetterQuality attribute)``.
COVER_LETTER_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ("overall", "Overall Quality", "overall"),
    ("jdAlignment", "Job-Description Alignment", "jd_alignment"),
    ("grounding", "Evidence Grounding", "grounding"),
    ("structure", "Letter Structure", "structure"),
)


#: Structural types for the two scorers. Declared as READ-ONLY properties, not
#: mutable attributes: ``CoverLetterQuality`` is a FROZEN dataclass, and a
#: protocol asking for settable attributes cannot be satisfied by one. This gate
#: only ever reads, so read-only is also the honest contract — nothing here may
#: mutate a score it is judging.
class _ATSScoreLike(Protocol):
    @property
    def overall(self) -> float: ...
    @property
    def keyword_match(self) -> float: ...
    @property
    def semantic_similarity(self) -> float: ...
    @property
    def experience_gap(self) -> float: ...
    @property
    def semantic_path(self) -> str: ...


class _CoverQualityLike(Protocol):
    @property
    def overall(self) -> float: ...
    @property
    def jd_alignment(self) -> float: ...
    @property
    def grounding(self) -> float: ...
    @property
    def structure(self) -> float: ...
    @property
    def jd_alignment_measured(self) -> bool: ...


def _coerce(value: Any) -> float | None:
    """Numeric coercion that NEVER invents a number (mirrors quality_policy)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def evaluate_tailoring(
    ats_score: _ATSScoreLike, *, floor: float = QUALITY_FLOOR
) -> GateVerdict:
    """Judge one tailored résumé's ATS breakdown against the floor.

    ``semantic_similarity`` is only judged when ``semantic_path`` names a
    genuine measurement path; otherwise the value is a neutral placeholder
    (GMV4-ats-001) and the dimension is reported unmeasured, which blocks the
    gate. ``overall`` is 40% built from that same component, so it is treated
    as unmeasured for the same reason — certifying a weighted total that is
    40% placeholder would be exactly the fabricated metric the whole scoring
    stack exists to avoid.
    """
    semantic_measured = (
        getattr(ats_score, "semantic_path", "untracked") != _DEGRADED_SEMANTIC_PATH
    )
    reason = (
        "semantic scoring was degraded — no genuine embedding model or HF "
        "Inference API was available for this run"
    )
    dimensions: list[DimensionScore] = []
    for key, label, attribute in TAILORING_DIMENSIONS:
        value = _coerce(getattr(ats_score, attribute, None))
        # Both the semantic component itself and the weighted overall it feeds
        # are only trustworthy when the semantic path was genuine.
        depends_on_semantic = key in ("semanticSimilarity", "overall")
        measured = value is not None and (semantic_measured or not depends_on_semantic)
        dimensions.append(
            DimensionScore(
                key=key,
                label=label,
                score=value if measured else None,
                floor=floor,
                measured=measured,
                unmeasured_reason=(
                    None
                    if measured
                    else (reason if depends_on_semantic else "no score was produced")
                ),
            )
        )
    return GateVerdict(
        artifact=ARTIFACT_RESUME, floor=floor, dimensions=tuple(dimensions)
    )


def evaluate_cover_letter(
    quality: _CoverQualityLike, *, floor: float = QUALITY_FLOOR
) -> GateVerdict:
    """Judge one finished cover letter's quality breakdown against the floor.

    ``jd_alignment`` is only judged when the posting yielded evidence-supported
    keywords at all (``CoverLetterQuality.jd_alignment_measured``); otherwise
    the component was excluded from the score and its 0.0 is an absence, not a
    deficiency. ``overall`` is renormalised in that case and remains a genuine
    measurement of the two components that WERE measured, so it stays judged.
    """
    alignment_measured = bool(getattr(quality, "jd_alignment_measured", True))
    dimensions: list[DimensionScore] = []
    for key, label, attribute in COVER_LETTER_DIMENSIONS:
        value = _coerce(getattr(quality, attribute, None))
        measured = value is not None and (key != "jdAlignment" or alignment_measured)
        dimensions.append(
            DimensionScore(
                key=key,
                label=label,
                score=value if measured else None,
                floor=floor,
                measured=measured,
                unmeasured_reason=(
                    None
                    if measured
                    else (
                        "this posting yielded no job-description keyword your "
                        "evidence supports, so alignment could not be measured"
                        if key == "jdAlignment"
                        else "no score was produced"
                    )
                ),
            )
        )
    return GateVerdict(
        artifact=ARTIFACT_COVER_LETTER, floor=floor, dimensions=tuple(dimensions)
    )


def failing_labels(gate: dict[str, Any] | None) -> list[str]:
    """Failing dimension labels of a PERSISTED verdict dict.

    Readers (routers, the approval gate, the Supervisor) consume the stored
    dict rather than the dataclass, and must never re-derive a verdict of their
    own from raw scores — a second computation is a second opinion.
    """
    if not isinstance(gate, dict):
        return []
    labels = gate.get("failingLabels")
    if isinstance(labels, list):
        return [str(label) for label in labels]
    return [
        str(d.get("label"))
        for d in (gate.get("failing") or [])
        if isinstance(d, dict) and d.get("label")
    ]


def is_below_floor(gate: dict[str, Any] | None) -> bool:
    """True iff a PERSISTED verdict says the artifact is below the floor.

    An absent/malformed verdict is NOT below the floor: artifacts produced
    before this gate existed carry no verdict, and inventing a failure for
    them would claim a judgement that was never made.
    """
    if not isinstance(gate, dict):
        return False
    return gate.get("passed") is False
