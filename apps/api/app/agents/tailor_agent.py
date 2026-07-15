"""Tailoring agent — produces a job-specific child resume version (P2-S05).

Ensures the user has a base resume record (bootstrapped from the bundled PDF
on first run), tailors its bullets against the target job via
:class:`ResumeTailorService`, and persists the result as a child version.
The source PDF is never modified — ``formatHash`` is carried through intact.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from app.agents.fit_scorer import get_base_resume_path
from app.repositories.job import JobRepository
from app.repositories.resume import ResumeRepository
from app.services.ats_engine import ATSEngine
from app.services.career_data import build_career_corpus
from app.services.resume_parser import parse_resume_pdf
from app.services.resume_pdf import extract_pdf_bullets
from app.services.resume_tailor import ResumeTailorService, strip_bullet_lines

#: Floor for the ATS-score denominator so a legitimate baseline of exactly
#: 0.0 never raises ZeroDivisionError (GAP-E2).
_LIFT_EPSILON = 1e-6

#: Default share of applications with a tailored resume that convert to an
#: interview, used to scale the ATS-score delta into an estimated lift.
#: Overridable via ``AETHER_CONVERSION_BASELINE_RATE`` for experimentation.
_DEFAULT_POPULATION_BASELINE_RATE = 0.025


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


@dataclass
class TailorRunResult:
    resume_id: str
    changes: int
    rejected: list[str]
    conversionMetrics: dict[str, Any]


class TailoringAgent:
    def __init__(
        self,
        resumes: ResumeRepository | None = None,
        jobs: JobRepository | None = None,
        service: ResumeTailorService | None = None,
    ) -> None:
        self._resumes = resumes or ResumeRepository()
        self._jobs = jobs or JobRepository()
        self._service = service or ResumeTailorService()

    def ensure_base_resume(self, user_id: str) -> dict[str, Any]:
        base = self._resumes.get_base(user_id)
        if base and (base.get("sections") or {}).get("raw_text"):
            return base
        base_path = get_base_resume_path()
        parsed = parse_resume_pdf(base_path)
        # Reconstruct COMPLETE bullets positionally from the PDF. The flat text
        # stream interleaves each wrapped bullet's continuation lines with
        # left-rail content, so line-based extraction would store truncated
        # first-line fragments — which the tailoring LLM then "completes" into
        # incoherent, duplicated output (GAP-P4-044).
        sections = {
            "raw_text": parsed["raw_text"],
            "bullets": [
                {"text": b, "evidenceRef": f"bullet-{i}"}
                for i, b in enumerate(extract_pdf_bullets(base_path))
            ],
            "contact": parsed["contact"],
        }
        if base:
            # Base exists but was seeded with empty sections — heal it from
            # the real PDF so diffs have genuine "before" content.
            healed = self._resumes.update_sections(
                base["id"], user_id, sections, parsed["format_hash"]
            )
            if healed:
                return healed
        return self._resumes.create(
            user_id, sections, parsed["format_hash"], label="Base resume", version=1
        )

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
        resume_text = base["sections"].get("raw_text") or parse_resume_pdf(
            get_base_resume_path()
        )["raw_text"]

        jd = f"{job['title']} at {job['company']}. {job.get('description', '')}"
        # Tailor against the version's stored bullets when present so change
        # counts (and the diff endpoint) are measured against the parent the
        # user selected — not re-derived from the immutable base raw_text.
        parent_bullets = (base.get("sections") or {}).get("bullets") or None
        # Consolidated career evidence (GitHub/portfolio/LinkedIn, ADR D-0031)
        # widens the anti-fabrication corpus so a rewrite may draw on skills the
        # user's public work proves. Empty when no career data is ingested.
        career_corpus = build_career_corpus(user_id)
        result = self._service.tailor(
            resume_text, jd, originals=parent_bullets, evidence_extra=career_corpus
        )

        tailored = self._resumes.create(
            user_id,
            {"bullets": result.bullets, "raw_text": resume_text},
            base["formatHash"],  # source PDF untouched → hash carried through
            label=f"Tailored — {job['title']} @ {job['company']}",
            version=self._resumes.next_version(user_id),
            parent_id=base["id"],
            source_job_id=job_id,
        )
        conversion_metrics = _compute_conversion_metrics(
            resume_text, result.originals, result.bullets, job.get("description") or ""
        )
        return TailorRunResult(
            resume_id=tailored["id"],
            changes=result.changes,
            rejected=result.rejected,
            conversionMetrics=conversion_metrics,
        )
