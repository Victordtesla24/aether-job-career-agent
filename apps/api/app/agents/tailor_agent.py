"""Tailoring agent — produces a job-specific child resume version (P2-S05).

Requires the user to have their OWN base resume record (uploaded/ingested — it
is NEVER bootstrapped from the bundled operator PDF, which would leak the
operator's résumé as the user's own; NF-final-B-005), tailors its bullets
against the target job via :class:`ResumeTailorService`, and persists the result
as a child version. The source résumé is never modified — ``formatHash`` is
carried through intact.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.repositories.approval import ApprovalRepository
from app.repositories.job import JobRepository
from app.repositories.resume import ResumeRepository
from app.repositories.story import StoryRepository
from app.services.ats_engine import ATSEngine
from app.services.career_data import build_career_corpus
from app.services.evidence_corpus import build_corpus_evidence, corpus_items_to_evidence_text
from app.services.resume_format import FormatFidelity, describe_fidelity, pending_fidelity
from app.services.resume_grounding import MissingResumeError
from app.services.resume_parser import parse_resume_pdf
from app.services.resume_pdf import bundled_format_hashes, extract_pdf_bullets
from app.services.resume_tailor import (
    ResumeTailorService,
    TailorResult,
    render_tailored_raw_text,
    strip_bullet_lines,
)
from app.services.tailoring_loop import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_TARGET_SCORE,
    TailoringLoop,
)

#: Floor for the ATS-score denominator so a legitimate baseline of exactly
#: 0.0 never raises ZeroDivisionError (GAP-E2).
_LIFT_EPSILON = 1e-6

#: Default share of applications with a tailored resume that convert to an
#: interview, used to scale the ATS-score delta into an estimated lift.
#: Overridable via ``AETHER_CONVERSION_BASELINE_RATE`` for experimentation.
_DEFAULT_POPULATION_BASELINE_RATE = 0.025

#: Terminal punctuation a complete work bullet ends on, and trailing wrappers
#: (closing bracket / quote) stripped before that check.
_BULLET_TERMINAL = (".", "!", "?", ":")
_BULLET_TRAIL = ")\"']"


def _bullets_need_healing(texts: list[str]) -> bool:
    """True when stored base bullets look mangled by the two-column layout.

    A base persisted before the column-aware extractor stored each work bullet
    truncated to its first visual line — a "Heading:" lead-in ending mid-
    sentence — or with a hyphenated line break rejoined as a stray-space word
    ("test- evidence"). Either signature means the stored bullets are unreliable
    and should be re-derived from the source PDF on read (GAP-P5-PDF). Sidebar
    skills / certification lines legitimately lack terminal punctuation and have
    no "Heading:" lead-in, so they never trip the first check.
    """
    for text in texts:
        t = (text or "").strip()
        if not t:
            continue
        if ":" in t[:60] and not t.rstrip(_BULLET_TRAIL).endswith(_BULLET_TERMINAL):
            return True
        if re.search(r"[A-Za-z]- [A-Za-z]", t):
            return True
    return False


def _compute_conversion_metrics(
    original_text: str,
    original_bullets: list[dict[str, str]],
    tailored_bullets: list[dict[str, str]],
    job_description: str,
) -> dict[str, Any]:
    """Deterministic before/after ATS re-score + estimated conversion lift.

    Both scores are computed on corpora that differ ONLY by the bullet wording
    (GAP-TAIL-001). The keyword-dense resume context (skills, summary,
    education) is stripped once via :func:`strip_bullet_lines` and re-attached
    to each bullet set, so ``baselineATSScore`` (context + original bullets) and
    ``tailoredATSScore`` (context + tailored bullets) are a true like-for-like
    comparison. Scoring the full original resume against only the tailored
    bullets previously discarded that shared context and produced a large,
    dishonest negative delta regardless of rewrite quality.

    Both come from the deterministic :class:`ATSEngine` — no extra LLM cost.
    ``estimatedConversionLift`` scales the relative ATS-score delta by a
    population baseline interview-conversion rate (``AETHER_CONVERSION_BASELINE_RATE``,
    default 2.5%). A baseline of exactly 0.0 is floored to avoid a
    ZeroDivisionError while still producing a (large) honest lift figure.
    """
    engine = ATSEngine()
    context = strip_bullet_lines(original_text)

    def _corpus(bullets: list[dict[str, str]]) -> str:
        bullet_text = "\n".join(b.get("text", "") for b in bullets)
        return f"{context}\n{bullet_text}" if context else bullet_text

    baseline = engine.score(_corpus(original_bullets), job_description)
    tailored = engine.score(_corpus(tailored_bullets), job_description)
    baseline_score = baseline.overall
    tailored_score = tailored.overall

    population_rate = float(
        os.environ.get("AETHER_CONVERSION_BASELINE_RATE", str(_DEFAULT_POPULATION_BASELINE_RATE))
    )
    lift_fraction = (
        (tailored_score - baseline_score) / max(baseline_score, _LIFT_EPSILON)
    ) * population_rate
    lift_pct = lift_fraction * 100
    sign = "+" if lift_pct >= 0 else ""

    # GMV4-ats-002: both re-scores are 40% built from semantic_similarity —
    # if EITHER endpoint's semantic component was "degraded" (no genuine
    # embedding model/HF Inference API available), the delta/lift derived
    # from it is a fabricated business metric, not a measurement. Flagged
    # here (never withheld — the numbers are still directionally useful) so
    # a consumer can label them honestly instead of presenting a fabricated
    # "lift" as fact. Round 3: WHITELIST — only "local"/"hf_api" count as
    # genuinely measured; "degraded", "untracked" and any unrecognised value
    # all read as degraded (fails closed instead of open).
    baseline_degraded = baseline.semantic_path not in ("local", "hf_api")
    tailored_degraded = tailored.semantic_path not in ("local", "hf_api")

    return {
        "baselineATSScore": baseline_score,
        "tailoredATSScore": tailored_score,
        "estimatedConversionLift": f"{sign}{lift_pct:.1f}%",
        "methodology": "Like-for-like ATS delta (shared context) × population baseline (2.5%)",
        "confidence": "model-estimated",
        "baselineDegraded": baseline_degraded,
        "tailoredDegraded": tailored_degraded,
        "scoringDegraded": baseline_degraded or tailored_degraded,
    }


#: Default cap on the Story Bank text folded into ONE prompt. Deliberately the
#: same number as ``evidence_corpus._DEFAULT_MAX_CHARS``: the two evidence
#: producers that share a single tailoring/cover prompt must share one
#: budgeting discipline, or the unbounded one silently crowds out the bounded
#: one. Overridable without a deploy via ``AETHER_STORY_EVIDENCE_MAX_CHARS``.
_DEFAULT_STORY_EVIDENCE_MAX_CHARS = 4000

#: Generation-time relevance floor for Story Bank selection (U-STORY-1 step 1).
#:
#: ``story_relevance_score`` is the share of the POSTING's term-frequency
#: weighted vocabulary that ONE story proves, so its realistic ceiling is small:
#: measured against a full-length posting, a squarely on-point story scores
#: ~0.20 and a genuinely unrelated one scores exactly 0.0
#: (``uat/reports/evidence/market-perf/u-story/s1/relevance-range.json``). The
#: §7.3.5 default of 0.4 that ``story_relevance.relevance_threshold()`` returns
#: is therefore unreachable for ANY single story, and applying it here would
#: drop the candidate's entire Story Bank from the prompt — deleting the very
#: candidate-own evidence the cover-letter claim guard needs and turning true
#: claims into rejections. That threshold has never been exercised as a
#: selection floor anywhere (``GET /stories?job_id=`` reports the score, it does
#: not filter on it), so this is its first live calibration, not a relaxation of
#: a shipped guard: no fabrication or entailment guard reads this value, and a
#: WIDER set of the candidate's own TRUE stories can only ever make the guards
#: more permissive about things the candidate genuinely did.
#:
#: The floor kept here is "proves at least something this posting asks for" —
#: the one magnitude with an evidence-grounded meaning rather than a guessed
#: one. Bounding is then done by RANK + CHARACTER BUDGET, exactly as the corpus
#: path does it (``evidence_corpus.build_corpus_evidence``). Overridable via
#: ``AETHER_STORY_EVIDENCE_MIN_RELEVANCE``.
_DEFAULT_STORY_EVIDENCE_MIN_RELEVANCE = 0.01


#: Epistemic provenance every Story Bank unit carries (U-STORY-1 step 4).
#:
#: A story is the candidate's OWN account of their OWN achievement, so the
#: source STATES it — never "inferred". ``confidence high`` records that the
#: extractor's grounding layer already refused any story whose numbers or
#: organisation the résumé did not evidence (``services/resume_bullets.py``
#: guards, ``story_extractor._ground_narrative``), and a hand-authored story is
#: the candidate asserting it directly. These two values are a LABEL on
#: evidence, not a guard input: nothing in the fabrication or entailment path
#: reads them, they exist so a downstream reader (and the model) can tell a
#: Story Bank claim from résumé text — which before this slice was impossible.
_STORY_EVIDENCE_SOURCE = "story_bank"
_STORY_EVIDENCE_EPISTEMIC = "stated"
_STORY_EVIDENCE_CONFIDENCE = "high"


def _story_corpus_item(claim: str) -> dict[str, Any]:
    """One story claim in ``EvidenceCorpusItem`` shape.

    Single definition of the story→corpus mapping, so the evidence-text
    renderer here and the ``EvidenceCorpusItem`` mirror written on every story
    write agree by construction instead of by convention.
    """
    return {
        "claim": claim,
        "source": _STORY_EVIDENCE_SOURCE,
        "stated_or_inferred": _STORY_EVIDENCE_EPISTEMIC,
        "confidence": _STORY_EVIDENCE_CONFIDENCE,
    }


def _story_evidence_max_chars() -> int:
    try:
        value = int(os.environ.get("AETHER_STORY_EVIDENCE_MAX_CHARS", ""))
    except ValueError:
        return _DEFAULT_STORY_EVIDENCE_MAX_CHARS
    return value if value > 0 else _DEFAULT_STORY_EVIDENCE_MAX_CHARS


def _story_evidence_min_relevance() -> float:
    try:
        return float(
            os.environ.get(
                "AETHER_STORY_EVIDENCE_MIN_RELEVANCE",
                str(_DEFAULT_STORY_EVIDENCE_MIN_RELEVANCE),
            )
        )
    except (TypeError, ValueError):
        return _DEFAULT_STORY_EVIDENCE_MIN_RELEVANCE


def build_story_evidence(
    user_id: str,
    repo: StoryRepository | None = None,
    job_description: str | None = None,
) -> str:
    """Flatten the user's Story Bank into evidence text (GAP-P6-TAIL-001).

    The Story Bank holds real, user-authored STAR achievements whose skills are
    often absent from the polished résumé TEXT. Folding them into the tailoring
    evidence corpus is what lets the model surface a JD keyword the candidate
    genuinely proves (and pass the fabrication guard) — the only way a
    like-for-like ATS re-score can rise strictly without inventing anything.
    Every quantified result is kept so metric-bearing evidence survives. Empty
    when the user has no stories (backward compatible).

    ``job_description`` (§7.3.5, optional/backward-compatible — default
    ``None`` preserves the exact prior "every story unconditionally" corpus
    for existing callers) narrows the story set to only those the SAME
    scoring function ``GET /stories?job_id=`` already exposes
    (``app.services.story_relevance.story_relevance_score``) rates >=
    ``relevance_threshold()`` against this specific job. This can only ever
    NARROW which of the candidate's own TRUE stories are included — it never
    adds, rewrites, or invents story content, so the anti-fabrication
    entailment guard downstream is unaffected.

    Selection and bounding mirror the corpus path
    (``services/evidence_corpus.build_corpus_evidence``) so the two producers
    that share one prompt behave the same way:

    * with a ``job_description``, stories that prove nothing the posting asks
      for are dropped (:func:`~app.services.story_relevance.filter_stories_by_relevance`
      at :data:`_DEFAULT_STORY_EVIDENCE_MIN_RELEVANCE`) and the survivors are
      ordered strongest-first;
    * with or without one, the rendered text is truncated to a character budget
      (:func:`_story_evidence_max_chars`). Before U-STORY-1 this path was the
      only unbounded evidence producer in the tailoring prompt — a 40-story
      bank was folded whole into every job's prompt.
    """
    repo = repo or StoryRepository()
    stories = repo.list_by_user(user_id)
    if job_description:
        from app.services.story_relevance import (
            filter_stories_by_relevance,
            story_relevance_score,
        )

        stories = filter_stories_by_relevance(
            stories, job_description, threshold=_story_evidence_min_relevance()
        )
        # Strongest evidence first, so what the character budget below keeps is
        # the evidence most able to move THIS application — never an arbitrary
        # prefix of the bank. The id tiebreak keeps the order deterministic
        # when two stories score identically.
        stories = sorted(
            stories,
            key=lambda s: (
                -story_relevance_score(s, job_description),
                str(s.get("id") or ""),
            ),
        )
    budget = _story_evidence_max_chars()
    parts: list[str] = []
    used = 0
    for story in stories:
        fields = [str(story.get("title") or ""), " ".join(story.get("tags") or [])]
        for key in ("situation", "task", "action", "result"):
            fields.append(str(story.get(key) or ""))
        metrics = story.get("metrics")
        if isinstance(metrics, dict):
            fields.extend(f"{k} {v}" for k, v in metrics.items())
        claim = " ".join(f for f in fields if f).strip()
        if not claim:
            continue
        text = corpus_items_to_evidence_text([_story_corpus_item(claim)])
        # ``continue`` rather than ``break`` (mirrors ``build_corpus_evidence``):
        # one oversized story must not evict every shorter one behind it.
        cost = len(text) + (2 if parts else 0)
        if used + cost > budget:
            continue
        parts.append(text)
        used += cost
    return "\n\n".join(parts)


#: Content-word tokenizer for the tailor grounding metric (mirrors the cover
#: letter's ``grounding_confidence``). Short words / connectives carry no signal.
_TAILOR_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*")
_TAILOR_STOPWORDS = frozenset(
    """
    a an and are as at be been by for from has have i in is it its my of on or
    our that the their this to was we were will with you your who what how when
    across own more most very than then also both each am me not can could would
    should into out about over under they them he she his her role resume
    """.split()
)


def grounding_confidence(bullets: list[dict[str, str]], corpus: str) -> int:
    """Share (0-100) of the tailored bullets' content words backed by the
    candidate's evidence corpus — a REAL, deterministic measurement of the
    finished version, never a fabricated or random score (§ no-fake-metrics).

    Every accepted rewrite already passed the fabrication + entailment guards, so
    a genuinely tailored version sits high; the figure is nonetheless computed
    from the actual bullet text so it degrades honestly if the corpus lacks a
    term. Mirrors ``cover_letter_agent.grounding_confidence`` (kept local to avoid
    a circular import — cover_letter_agent imports this module)."""
    corpus_tokens = {t.lower() for t in _TAILOR_WORD_RE.findall(corpus or "")}
    words = [
        t
        for b in bullets
        for t in _TAILOR_WORD_RE.findall(b.get("text", ""))
        if len(t) >= 3 and t.lower() not in _TAILOR_STOPWORDS
    ]
    if not words:
        return 0
    supported = sum(1 for w in words if w.lower() in corpus_tokens)
    return round(100 * supported / len(words))


def build_tailor_approval_extras(
    result: "Any", job: dict[str, Any], evidence_corpus: str, fidelity: FormatFidelity
) -> dict[str, Any]:
    """Approval-card fields the review modal renders for a tailored résumé
    (MV-resume-studio-001) — ``preview`` (the changed bullets a human reviews),
    ``why`` (why the gate fired), ``reasoning`` (what the agent verified) and
    ``confidence`` (evidence grounding).

    The fabrication/entailment-guard reasoning items are TRUE by construction:
    a version only reaches this point after its rewrites passed both guards.
    The layout-preservation item is NOT — it used to unconditionally claim
    "Original layout preserved... Verified" for every run regardless of the
    base document's own fidelity, which a live coherence re-review proved
    false for 2 of 3 sampled production approvals (reflow-template,
    ``formatPreserved: false`` bases still shown a green "Verified" claim;
    SONNET-COHERENCE-REREVIEW-20260814.md finding F4). ``fidelity`` — the
    SAME ``describe_fidelity``/``pending_fidelity`` decision table
    ``GET /resumes`` stamps every listed version with — is required so this
    item can only ever say what the base document's real mechanism supports:
    a "check" when it claims preservation (still caveated as pending
    per-document verification — no render/download has happened yet at
    approval-creation time), a "warning" naming the true limitation
    otherwise. Never an unconditional claim.
    """
    changed = [
        (cur, orig)
        for cur, orig in zip(result.bullets, result.originals)
        if cur.get("text") != orig.get("text")
    ]
    preview_lines = [
        f"{cur.get('text', '')}" for cur, _ in changed[:6]
    ]
    more = len(changed) - len(preview_lines)
    if more > 0:
        preview_lines.append(f"…and {more} more rewritten bullet(s).")
    preview = (
        f"{len(changed)} bullet(s) rewritten for {job['title']} @ {job['company']}:\n"
        + "\n".join(f"• {line}" for line in preview_lines)
    )
    return {
        "preview": preview,
        "why": (
            "This tailored résumé version awaits your sign-off before it becomes an "
            "approved, authoritative version for this role. Review the reworded "
            "bullets, then approve or request changes."
        ),
        "reasoning": [
            {
                "kind": "check",
                "text": (
                    "Every reworded bullet is grounded in your résumé and career "
                    "evidence (fabrication + entailment guards passed)."
                ),
            },
            {
                "kind": "check" if fidelity.preserved is True else "warning",
                "text": f"Original layout: {fidelity.note}",
            },
            {
                "kind": "check",
                "text": (
                    f"{len(changed)} bullet(s) reworded to surface "
                    f"{job['title']}-relevant keywords you already prove."
                ),
            },
        ],
        "confidence": grounding_confidence(result.bullets, evidence_corpus),
    }


class NoChangesApplied(RuntimeError):
    """Raised when a tailoring run applies ZERO net edits — every proposed rewrite
    was rejected by the fabrication/entailment guards, so the résumé is unchanged
    (MV-resume-studio-003).

    Handled like the cover letter's :class:`FabricationError`: NO new résumé
    version is created, NO approval is opened, and the reserved run is refunded, so
    the user is never billed for — nor shown — a silent no-op "Tailored" version
    that is byte-identical to its parent."""

    def __init__(self, rejected: list[str] | None = None) -> None:
        super().__init__(
            "No verifiable changes could be applied — every suggested edit was "
            "unsupported by your evidence, so your résumé is unchanged and you "
            "were not charged."
        )
        self.rejected = rejected or []


@dataclass
class TailorRunResult:
    resume_id: str
    changes: int
    rejected: list[str]
    conversionMetrics: dict[str, Any]
    #: The pending ApprovalRequest opened for this tailored version so nothing is
    #: treated as authoritative without human sign-off (MV-resume-studio-001).
    #: ``None`` only on legacy/uncreated paths.
    approval_id: str | None = None
    approval_status: str | None = None
    #: §5.3.1 point 5: populated iff the score-aware loop (see
    #: ``TailoringLoop``) never reached the 85 ATS target within its
    #: iteration cap — an honest sub-target signal, NEVER silently dropped.
    warning: str | None = None
    #: GMV4-tailor-001 (§6.1(b)/§6.2): per-attempt progress trail — ONE entry
    #: per ``TailoringLoop`` iteration actually run, each carrying
    #: ``"iteration"`` (1-based index), ``"score"``, ``"gapKeywords"``,
    #: ``"changes"`` and ``"rejected"`` (tailoring_loop.py:179-186). Copied
    #: verbatim from ``loop_result.iterations`` — the SAME object already
    #: persisted to the DB as ``sections["tailoringIterations"]`` (see
    #: ``TailoringAgent.run`` below), so the API response and the DB agree.
    #: Never recomputed here; an empty list iff the loop genuinely ran zero
    #: attempts (never a fabricated placeholder entry).
    iterations: list[dict[str, Any]] = field(default_factory=list)
    #: GMV4-tailor-001 (§6.2 UI chip list): still-missing JD keywords for the
    #: run's WINNING (best-scoring) iteration — the exact
    #: ``clean_gap_keywords`` output already computed by the loop
    #: (tailoring_loop.py:177,184), taken from the same ``best`` iteration
    #: record ``TailoringAgent.run`` already selects to persist the tailored
    #: version, so the chip list always matches what was actually produced.
    gapKeywords: list[str] = field(default_factory=list)
    #: W-TAILOR-CONVERGE: the run's honest verdict + headline numbers, the
    #: SAME dict persisted to ``Resume.sections["tailoringSummary"]`` — so the
    #: response and a later page load can never tell different stories.
    #: Keys: targetScore, bestScore, bestIteration, iterationsRun,
    #: reachedTarget, stopReason, requiresReview, warning,
    #: unreachableKeywords, gapKeywords, netChanges.
    tailoringSummary: dict[str, Any] = field(default_factory=dict)


def resolve_loop_knobs(policy_knobs: "Mapping[str, Any] | None") -> tuple[int, float]:
    """The clamped ``(max_iterations, target_score)`` a ``TailoringLoop`` run
    actually uses (F-UAX-06).

    Extracted out of ``TailoringAgent.run`` so this EXACT clamping logic —
    not a reimplementation of it — is directly unit-testable without driving
    a full tailoring pipeline (LLM calls, resume/job fixtures, etc.) end to
    end. Clamped to the shipped defaults as a FLOOR: even a malformed or
    downgraded knob cannot make the product try less than it does today
    (``quality_policy`` rule 3 — rigor only ever escalates).
    """
    knobs = dict(policy_knobs or {})
    max_iterations = max(
        int(knobs.get("maxIterations") or DEFAULT_MAX_ITERATIONS),
        DEFAULT_MAX_ITERATIONS,
    )
    target_score = max(
        float(knobs.get("targetScore") or DEFAULT_TARGET_SCORE),
        DEFAULT_TARGET_SCORE,
    )
    return max_iterations, target_score


class TailoringAgent:
    def __init__(
        self,
        resumes: ResumeRepository | None = None,
        jobs: JobRepository | None = None,
        service: ResumeTailorService | None = None,
        stories: StoryRepository | None = None,
        approvals: ApprovalRepository | None = None,
        ats_engine: ATSEngine | None = None,
    ) -> None:
        self._resumes = resumes or ResumeRepository()
        self._jobs = jobs or JobRepository()
        self._service = service or ResumeTailorService()
        self._stories = stories or StoryRepository()
        self._approvals = approvals or ApprovalRepository()
        #: Drives the score-aware ``TailoringLoop`` (§5.3 item 1) — the SAME
        #: deterministic engine ``/resumes/{id}/ats`` and the before/after
        #: score banner already use, so the loop's convergence decisions and
        #: the UI's displayed score are computed identically.
        self._ats_engine = ats_engine or ATSEngine()

    def resume_for_job(self, user_id: str, job_id: str) -> dict[str, Any]:
        """Resume to attach when drafting for a job (cover_letter_agent's
        creation-time seam): the newest resume ALREADY tailored for this job
        if one exists, else the user's base résumé (unchanged degradation).

        Adjudicator follow-up (ml-adjudication-review-verdict.json
        resumeResolutionAnalysis): drafts previously always attached base
        and relied on submit_application's promotion-time repair to swap in
        the tailored version. Checking here too means a draft created AFTER
        a tailor run carries the real tailored resume from the start;
        promotion-time repair remains the backstop for legacy drafts.
        """
        tailored = self._resumes.get_tailored_for_job(user_id, job_id)
        return tailored if tailored is not None else self.ensure_base_resume(user_id)

    def ensure_base_resume(self, user_id: str) -> dict[str, Any]:
        base = self._resumes.get_base(user_id)
        raw_text = ((base.get("sections") or {}).get("raw_text") if base else "") or ""
        if not base or not raw_text.strip():
            # No résumé of the user's own on file. NEVER seed the bundled operator
            # résumé as this user's base — that persists the operator's PII as
            # "their" résumé and leaks it into their downloads/attachments
            # (NF-final-B-005). Outbound flows refuse until the user adds one.
            raise MissingResumeError(
                "Add your resume before tailoring or generating an application."
            )
        stored = [
            b.get("text", "")
            for b in ((base.get("sections") or {}).get("bullets") or [])
        ]
        # A base persisted before the column-aware extractor holds truncated
        # first-line fragments (or hyphen-corrupted bullets) even though its
        # raw_text is complete. Re-derive COMPLETE bullets on read and heal in
        # place — non-destructively, preserving the immutable raw_text and format
        # hash (GAP-P5-PDF). A healthy base is returned untouched.
        if stored and not _bullets_need_healing(stored):
            return base
        # Bullets need healing. Re-derive them ONLY from a bundled source PDF that
        # THIS base actually derives from (its formatHash matches a packaged
        # asset, e.g. the BA variant). A user-authored résumé has no bundled
        # source, so its stored bullets are returned as-is — the operator PDF is
        # NEVER used to heal another user's résumé (NF-final-B-005).
        from app.services.resume_pdf import resolve_original_pdf

        source = resolve_original_pdf(base.get("formatHash"))
        if source is None:
            return base
        parsed = parse_resume_pdf(source)
        sections = {
            "raw_text": raw_text,
            "bullets": [
                {"text": b, "evidenceRef": f"bullet-{i}"}
                for i, b in enumerate(extract_pdf_bullets(source))
            ],
            "contact": (base.get("sections") or {}).get("contact") or parsed["contact"],
        }
        healed = self._resumes.update_sections(
            base["id"], user_id, sections, base["formatHash"]
        )
        return healed or base

    def _pending_fidelity_for(self, base: dict[str, Any], user_id: str) -> FormatFidelity:
        """The honest, mechanism-level fidelity report for the version about
        to be tailored FROM ``base`` — the SAME decision table ``GET /resumes``
        stamps every listed version with (:mod:`app.services.resume_format`),
        computed here at approval-creation time so
        :func:`build_tailor_approval_extras` can state a real, per-state
        layout-preservation line instead of an unconditional claim
        (ML-U2B-approval-honesty).

        No download/render has happened yet at this point in the run, so a
        mechanism claim of preservation is wrapped in :func:`pending_fidelity`
        — exactly what ``stamp_fidelity`` does for a tailored listing row
        whose parent claims preservation: state the mechanism, not an
        outcome nobody has checked yet.

        ``original_meta_by_user`` is looked up defensively (``getattr``): test
        doubles for :class:`ResumeRepository` that predate this fix do not
        implement it, and the honest degrade for "we don't know whether the
        original is stored" is the same default ``stamp_fidelity`` already
        uses for a résumé absent from its own ``original_meta`` mapping —
        ``hasOriginal=False`` — never a crash and never an affirmative guess.
        """
        format_hash = base.get("formatHash")
        meta_lookup = getattr(self._resumes, "original_meta_by_user", None)
        meta: dict[str, Any] = {}
        if meta_lookup is not None:
            meta = meta_lookup(user_id).get(base.get("id"), {})
        fidelity = describe_fidelity(
            bundled_match=bool(format_hash) and format_hash in bundled_format_hashes(),
            has_original=bool(meta.get("hasOriginal")),
            content_type=meta.get("originalContentType"),
            is_tailored=True,
        )
        if fidelity.preserved is True:
            fidelity = pending_fidelity(fidelity)
        return fidelity

    def run(
        self,
        user_id: str,
        job_id: str,
        resume_id: str | None = None,
        *,
        policy_knobs: "Mapping[str, Any] | None" = None,
    ) -> TailorRunResult:
        """Tailor ``resume_id`` (or the base résumé) against ``job_id``.

        ``policy_knobs`` (U-AX) carries the deterministic rigor tier's
        ``maxIterations`` / ``targetScore`` resolved by
        ``services.quality_policy`` and injected at the single dispatch seam
        (``routers/agents.py::_with_quality_policy``). ``None``/``{}`` keeps
        ``TailoringLoop``'s shipped defaults exactly — this parameter can only
        ever RAISE rigor, never lower it, because every tier's knobs are
        >= those defaults by construction (see ``quality_policy._KNOBS_BY_TIER``).
        """
        job = self._jobs.get_by_id(job_id, user_id)
        if job is None:
            raise LookupError(f"Job {job_id} not found for user")

        if resume_id:
            # Tailor against an explicitly selected resume (e.g. the BA variant).
            base = self._resumes.get_by_id(resume_id, user_id)
            if base is None:
                raise LookupError(f"Resume {resume_id} not found for user")
        else:
            base = self.ensure_base_resume(user_id)
        resume_text = base["sections"].get("raw_text") or ""
        if not resume_text.strip():
            # Never tailor against the bundled operator résumé (NF-final-B-005).
            raise MissingResumeError(
                "Add your resume before tailoring or generating an application."
            )

        jd = f"{job['title']} at {job['company']}. {job.get('description', '')}"
        # Tailor against the version's stored bullets when present so change
        # counts (and the diff endpoint) are measured against the parent the
        # user selected — not re-derived from the immutable base raw_text.
        parent_bullets = (base.get("sections") or {}).get("bullets") or None
        # Consolidated career evidence (GitHub/portfolio/LinkedIn, ADR D-0031)
        # widens the anti-fabrication corpus so a rewrite may draw on skills the
        # user's public work proves. Empty when no career data is ingested.
        career_corpus = build_career_corpus(user_id)
        # GAP-P6-TAIL-001: the Story Bank is real, evidence-grounded career
        # signal usually absent from the polished résumé text — the source of
        # truthful JD keywords the tailor can surface for a genuine ATS lift.
        # U-STORY-1 step 1: scoped to THIS posting. Without ``job_description``
        # every story the user owns was folded into every job's prompt,
        # unranked and unbounded — the largest unpriced token load in the
        # tailoring prompt on a large bank. Relevance selection can only NARROW
        # the candidate's own true stories, so no guard semantics change.
        story_evidence = build_story_evidence(
            user_id, self._stories, job_description=jd
        )
        # U2b/U2c-0: the provenance-tagged evidence corpus (baseline résumé +
        # portfolio + public repos, each claim carrying its source, epistemic
        # status and confidence). Ranked against THIS job description and
        # bounded to a character budget, so it widens the anti-fabrication
        # evidence base without flooding the model's token/latency budget. The
        # guards are untouched: a claim the corpus does not support is still
        # rejected and reverted. Empty string for a user with no corpus, which
        # keeps behaviour identical to before for those accounts.
        corpus_evidence = build_corpus_evidence(user_id, jd)
        evidence_extra = "\n\n".join(
            p for p in (career_corpus, story_evidence, corpus_evidence) if p
        )
        # §5.3 item 1: score-aware iterative tailoring — tailor, score via the
        # SAME ATSEngine ``/resumes/{id}/ats`` uses, and — while below the 85
        # target and iterations remain — retry with a directive naming the
        # score gap and the clean gap keywords. The anti-fabrication guard
        # inside ``self._service`` runs unmodified on every iteration; closing
        # a keyword gap never means inventing experience the candidate lacks.
        max_iterations, target_score = resolve_loop_knobs(policy_knobs)
        loop = TailoringLoop(
            service=self._service,
            ats_engine=self._ats_engine,
            max_iterations=max_iterations,
            target_score=target_score,
        )
        loop_result = loop.run(
            resume_text, jd, originals=parent_bullets, evidence_extra=evidence_extra
        )
        best = loop_result.iterations[loop_result.best_iteration - 1]
        # The TRUE pre-loop baseline (post-dedup), structured exactly as
        # ``ResumeTailorService.tailor`` structures ``originals`` internally —
        # used below for an honest before/after diff even when a LATER
        # iteration (not the first) ends up the best-scoring one.
        baseline_bullets = ResumeTailorService._structure_originals(
            parent_bullets, resume_text
        )
        # W-TAILOR-CONVERGE: report the CUMULATIVE net change — how many
        # bullets in the returned version actually differ from the parent —
        # rather than ``best["changes"]``, which counts only the winning
        # iteration's own edits against the draft it started from. With the
        # loop now seeding each pass from the best draft so far, a run that
        # rewrote 3 bullets in pass 1 and 2 more in pass 4 has genuinely
        # changed 5 bullets; reporting the last pass's 2 understated the work
        # and (worse) could raise ``NoChangesApplied`` on a run that really
        # did change the résumé.
        _baseline_text = {b.get("evidenceRef"): b.get("text") for b in baseline_bullets}
        if any(b.get("evidenceRef") in _baseline_text for b in loop_result.final_bullets):
            net_changes = sum(
                1
                for b in loop_result.final_bullets
                if b.get("evidenceRef") in _baseline_text
                and b.get("text") != _baseline_text[b.get("evidenceRef")]
            )
        else:
            # No ref overlap at all (the service re-keyed everything) — the
            # per-iteration count is then the only honest figure available.
            net_changes = best["changes"]

        # MV-resume-studio-003: when the fabrication/entailment guards reject
        # EVERY proposed rewrite across every iteration the tailored bullets of
        # the best-scoring pass are byte-identical to the parent (0 net
        # changes). Persisting that as a new "Tailored" version was a silent,
        # billed no-op indistinguishable from a real change. Instead raise —
        # mirroring the cover letter's FabricationError — so NO version is
        # created, NO approval is opened, and the reserved run is refunded (the
        # caller's _execute_reserved_run refunds on any exception). Honest
        # outcome: the résumé is unchanged and the user is not charged.
        if net_changes == 0:
            raise NoChangesApplied(rejected=best["rejected"])

        # GAP-P6-TAIL-002: regenerate the persisted raw_text from the TAILORED
        # bullets (not the parent's verbatim raw_text) so a later independent
        # GET /resumes/{id}/ats — which scores raw_text preferentially —
        # reflects the tailored score, matching the PDF and the run's reported
        # tailoredATSScore instead of reverting to the stale baseline.
        tailored_raw_text = render_tailored_raw_text(resume_text, loop_result.final_bullets)
        # GMV4-tailor-001 §6.1(c) — PERSISTENCE. This block MUST run BEFORE
        # ``self._resumes.create(...)``. It previously ran after, and its
        # result was only ever assigned to the in-memory ``TailorRunResult``,
        # so the before/after ATS scores existed for exactly one HTTP response
        # and a page reload had nothing to show. Computing it first lets the
        # very same dict be written into the Resume row below.
        conversion_metrics = _compute_conversion_metrics(
            resume_text, baseline_bullets, loop_result.final_bullets, jd,
        )
        # §5.3.1 point 5: surface the loop's own honest verdict on this run —
        # wired to the same "needs a human look" concept ``ATSScore.
        # requires_review`` already computes, never silently dropped. Round 3
        # fix: OR in ``conversion_metrics["scoringDegraded"]`` rather than
        # overwriting — ``_compute_conversion_metrics`` re-scores baseline/
        # tailored with two FRESH ``ATSEngine().score()`` calls made after the
        # loop finished, so a transient degradation there is a distinct event
        # the loop's own verdict cannot see. Discarding it (the round-2 bug)
        # meant a degraded conversion re-score produced no warning anywhere.
        conversion_metrics["requires_review"] = (
            loop_result.requires_review or bool(conversion_metrics.get("scoringDegraded"))
        )
        # The run's honest verdict, persisted alongside the numbers so a
        # reload can repeat it word for word instead of showing a bare score.
        tailoring_summary = {
            "targetScore": loop.target_score,
            "bestScore": loop_result.best_score,
            "bestIteration": loop_result.best_iteration,
            "iterationsRun": len(loop_result.iterations),
            "reachedTarget": loop_result.success,
            "stopReason": loop_result.stop_reason,
            "requiresReview": loop_result.requires_review,
            "warning": loop_result.warning,
            "unreachableKeywords": loop_result.unreachable_keywords,
            "gapKeywords": best["gapKeywords"],
            "netChanges": net_changes,
        }
        # MV-resume-studio-001: a freshly tailored version is created ``pending`` —
        # it stays under human review until its ApprovalRequest (below) is
        # approved, at which point ApprovalRepository flips it to ``approved``.
        tailored = self._resumes.create(
            user_id,
            {
                "bullets": loop_result.final_bullets,
                "raw_text": tailored_raw_text,
                # §5.3.3: every iteration's output + score, persisted so the UI
                # can show tailoring progress honestly (the before/after score
                # banner already renders the headline baseline/tailored
                # numbers from conversionMetrics below; this is the
                # per-iteration detail behind them).
                "tailoringIterations": loop_result.iterations,
                # §6.1(c): the ats_score SUMMARY must survive a reload, not
                # just ride along in one HTTP response. Same dict returned to
                # the caller below, so the API and the DB can never disagree.
                "conversionMetrics": conversion_metrics,
                "baselineATSScore": conversion_metrics["baselineATSScore"],
                "tailoredATSScore": conversion_metrics["tailoredATSScore"],
                "tailoringSummary": tailoring_summary,
            },
            base["formatHash"],  # source PDF untouched → hash carried through
            label=f"Tailored — {job['title']} @ {job['company']}",
            version=self._resumes.next_version(user_id),
            parent_id=base["id"],
            source_job_id=job_id,
            approval_status="pending",
        )
        # MV-resume-studio-001: open a REAL pending ApprovalRequest (mirroring the
        # cover letter agent) so the run's ``approvalRequired: true`` flag is backed
        # by an actual human-in-the-loop gate rather than being decorative. Kept
        # idempotent per (job, kind=resume_tailor) by the repository, so re-tailoring
        # the same job refreshes the one pending card at the newest version instead
        # of stacking duplicates — and never collides with the job's cover-letter
        # approval. ``application_submit`` is the shared enum type (as the cover
        # letter uses); ``kind`` discriminates the artifact family.
        evidence_corpus = "\n".join(p for p in (resume_text, evidence_extra) if p)
        loop_as_result = TailorResult(
            bullets=loop_result.final_bullets,
            originals=baseline_bullets,
            changes=net_changes,
            rejected=best["rejected"],
        )
        # ML-U2B-approval-honesty: the base document's REAL fidelity mechanism
        # (not an unconditional claim) drives the approval card's
        # layout-preservation line — see _pending_fidelity_for's docstring.
        fidelity = self._pending_fidelity_for(base, user_id)
        approval = self._approvals.create(
            user_id,
            "application_submit",
            {
                "kind": "resume_tailor",
                "resume_id": tailored["id"],
                "job_id": job_id,
                "job_title": job["title"],
                "company": job["company"],
                # Overrides so the review modal names the Tailoring Agent rather
                # than the application_submit defaults.
                "agent": "Tailoring Agent",
                "action": "apply a tailored résumé",
                **build_tailor_approval_extras(loop_as_result, job, evidence_corpus, fidelity),
            },
        )
        # RT-005: a successfully tailored job belongs in the "Tailoring"
        # swimlane. Forward-only guarded advance — never demotes a manual
        # FEAT-B2 move (e.g. a card the user already dragged to a later stage).
        self._jobs.advance_status(
            job_id, "tailoring", allowed_from={"discovered", "screening", "matched"}
        )
        return TailorRunResult(
            resume_id=tailored["id"],
            changes=net_changes,
            rejected=best["rejected"],
            conversionMetrics=conversion_metrics,
            approval_id=approval["id"],
            approval_status=approval["status"],
            warning=loop_result.warning,
            iterations=loop_result.iterations,
            gapKeywords=best["gapKeywords"],
            tailoringSummary=tailoring_summary,
        )
