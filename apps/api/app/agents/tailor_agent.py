"""Tailoring agent — produces a job-specific child resume version (P2-S05).

Ensures the user has a base resume record (bootstrapped from the bundled PDF
on first run), tailors its bullets against the target job via
:class:`ResumeTailorService`, and persists the result as a child version.
The source PDF is never modified — ``formatHash`` is carried through intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.fit_scorer import get_base_resume_path
from app.repositories.job import JobRepository
from app.repositories.resume import ResumeRepository
from app.services.resume_parser import parse_resume_pdf
from app.services.resume_tailor import ResumeTailorService, extract_bullets


@dataclass
class TailorRunResult:
    resume_id: str
    changes: int
    rejected: list[str]


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
        if base and ((base.get("sections") or {}).get("raw_text") or "").strip():
            return base
        parsed = parse_resume_pdf(get_base_resume_path())
        sections = {
            "raw_text": parsed["raw_text"],
            "bullets": [
                {"text": b, "evidenceRef": f"bullet-{i}"}
                for i, b in enumerate(extract_bullets(parsed["raw_text"]))
            ],
            "contact": parsed["contact"],
        }
        if base:
            # Base exists but was seeded with empty sections — heal it from
            # the real PDF so diffs have genuine "before" content. Return the
            # existing root even if the update no-ops rather than creating a
            # second root (get_base would otherwise keep the empty one first).
            healed = self._resumes.update_sections(
                base["id"], user_id, sections, parsed["format_hash"]
            )
            return healed or base
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
        result = self._service.tailor(resume_text, jd)

        tailored = self._resumes.create(
            user_id,
            {"bullets": result.bullets, "raw_text": resume_text},
            base["formatHash"],  # source PDF untouched → hash carried through
            label=f"Tailored — {job['title']} @ {job['company']}",
            version=self._resumes.next_version(user_id),
            parent_id=base["id"],
            source_job_id=job_id,
        )
        return TailorRunResult(
            resume_id=tailored["id"], changes=result.changes, rejected=result.rejected
        )
