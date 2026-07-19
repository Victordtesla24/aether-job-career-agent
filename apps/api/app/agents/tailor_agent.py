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
from dataclasses import dataclass
from typing import Any

from app.repositories.approval import ApprovalRepository
from app.repositories.job import JobRepository
from app.repositories.resume import ResumeRepository
from app.repositories.story import StoryRepository
from app.services.ats_engine import ATSEngine
from app.services.career_data import build_career_corpus
from app.services.resume_grounding import MissingResumeError
from app.services.resume_parser import parse_resume_pdf
from app.services.resume_pdf import extract_pdf_bullets
from app.services.resume_tailor import (
    ResumeTailorService,
    render_tailored_raw_text,
    strip_bullet_lines,
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

    baseline_score = engine.score(_corpus(original_bullets), job_description).overall
    tailored_score = engine.score(_corpus(tailored_bullets), job_description).overall

    population_rate = float(
        os.environ.get("AETHER_CONVERSION_BASELINE_RATE", str(_DEFAULT_POPULATION_BASELINE_RATE))
    )
    lift_fraction = (
        (tailored_score - baseline_score) / max(baseline_score, _LIFT_EPSILON)
    ) * population_rate
    lift_pct = lift_fraction * 100
    sign = "+" if lift_pct >= 0 else ""

    return {
        "baselineATSScore": baseline_score,
        "tailoredATSScore": tailored_score,
        "estimatedConversionLift": f"{sign}{lift_pct:.1f}%",
        "methodology": "Like-for-like ATS delta (shared context) × population baseline (2.5%)",
        "confidence": "model-estimated",
    }


def build_story_evidence(user_id: str, repo: StoryRepository | None = None) -> str:
    """Flatten the user's Story Bank into evidence text (GAP-P6-TAIL-001).

    The Story Bank holds real, user-authored STAR achievements whose skills are
    often absent from the polished résumé TEXT. Folding them into the tailoring
    evidence corpus is what lets the model surface a JD keyword the candidate
    genuinely proves (and pass the fabrication guard) — the only way a
    like-for-like ATS re-score can rise strictly without inventing anything.
    Every quantified result is kept so metric-bearing evidence survives. Empty
    when the user has no stories (backward compatible)."""
    repo = repo or StoryRepository()
    parts: list[str] = []
    for story in repo.list_by_user(user_id):
        fields = [str(story.get("title") or ""), " ".join(story.get("tags") or [])]
        for key in ("situation", "task", "action", "result"):
            fields.append(str(story.get(key) or ""))
        metrics = story.get("metrics")
        if isinstance(metrics, dict):
            fields.extend(f"{k} {v}" for k, v in metrics.items())
        text = " ".join(f for f in fields if f).strip()
        if text:
            parts.append(text)
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
    result: "Any", job: dict[str, Any], evidence_corpus: str
) -> dict[str, Any]:
    """Approval-card fields the review modal renders for a tailored résumé
    (MV-resume-studio-001) — ``preview`` (the changed bullets a human reviews),
    ``why`` (why the gate fired), ``reasoning`` (what the agent verified) and
    ``confidence`` (evidence grounding). Every reasoning item is TRUE by
    construction: a version only reaches this point after its rewrites passed the
    fabrication + entailment guards, and the source PDF's ``formatHash`` is carried
    through untouched.
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
                "kind": "check",
                "text": (
                    "Original layout preserved — the source PDF's format hash is "
                    "carried through untouched."
                ),
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


class TailoringAgent:
    def __init__(
        self,
        resumes: ResumeRepository | None = None,
        jobs: JobRepository | None = None,
        service: ResumeTailorService | None = None,
        stories: StoryRepository | None = None,
        approvals: ApprovalRepository | None = None,
    ) -> None:
        self._resumes = resumes or ResumeRepository()
        self._jobs = jobs or JobRepository()
        self._service = service or ResumeTailorService()
        self._stories = stories or StoryRepository()
        self._approvals = approvals or ApprovalRepository()

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

    def run(self, user_id: str, job_id: str, resume_id: str | None = None) -> TailorRunResult:
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
        story_evidence = build_story_evidence(user_id, self._stories)
        evidence_extra = "\n\n".join(p for p in (career_corpus, story_evidence) if p)
        result = self._service.tailor(
            resume_text, jd, originals=parent_bullets, evidence_extra=evidence_extra
        )

        # MV-resume-studio-003: when the fabrication/entailment guards reject
        # EVERY proposed rewrite the tailored bullets are byte-identical to the
        # parent (0 net changes). Persisting that as a new "Tailored" version was a
        # silent, billed no-op indistinguishable from a real change. Instead raise
        # — mirroring the cover letter's FabricationError — so NO version is
        # created, NO approval is opened, and the reserved run is refunded (the
        # caller's _execute_reserved_run refunds on any exception). Honest outcome:
        # the résumé is unchanged and the user is not charged.
        if result.changes == 0:
            raise NoChangesApplied(rejected=result.rejected)

        # GAP-P6-TAIL-002: regenerate the persisted raw_text from the TAILORED
        # bullets (not the parent's verbatim raw_text) so a later independent
        # GET /resumes/{id}/ats — which scores raw_text preferentially —
        # reflects the tailored score, matching the PDF and the run's reported
        # tailoredATSScore instead of reverting to the stale baseline.
        tailored_raw_text = render_tailored_raw_text(resume_text, result.bullets)
        # MV-resume-studio-001: a freshly tailored version is created ``pending`` —
        # it stays under human review until its ApprovalRequest (below) is
        # approved, at which point ApprovalRepository flips it to ``approved``.
        tailored = self._resumes.create(
            user_id,
            {"bullets": result.bullets, "raw_text": tailored_raw_text},
            base["formatHash"],  # source PDF untouched → hash carried through
            label=f"Tailored — {job['title']} @ {job['company']}",
            version=self._resumes.next_version(user_id),
            parent_id=base["id"],
            source_job_id=job_id,
            approval_status="pending",
        )
        conversion_metrics = _compute_conversion_metrics(
            resume_text, result.originals, result.bullets, job.get("description") or ""
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
                **build_tailor_approval_extras(result, job, evidence_corpus),
            },
        )
        return TailorRunResult(
            resume_id=tailored["id"],
            changes=result.changes,
            rejected=result.rejected,
            conversionMetrics=conversion_metrics,
            approval_id=approval["id"],
            approval_status=approval["status"],
        )
