"""Cover letter agent with FabricationGuard + approval gate (P2-S06).

Composition:
- A deterministic header referencing the target job title and company (so the
  letter always addresses the actual role, never a hallucinated one).
- An LLM-drafted body constrained to the evidence corpus (resume text). Any
  entity/metric in the final letter that lacks evidence support is flagged by
  :class:`FabricationGuard` and the run fails loudly rather than shipping a
  fabricated claim.
- Every generated letter creates a *pending* ``ApprovalRequest`` — nothing is
  sent or submitted without an explicit human approval (P2-S07 gateway).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.fit_scorer import get_base_resume_path
from app.agents.tailor_agent import TailoringAgent
from app.repositories.approval import ApprovalRepository
from app.repositories.cover_letter import CoverLetterRepository
from app.repositories.job import JobRepository
from app.services.fabrication_guard import FabricationGuard
from app.services.llm_client import LLMClient, get_model
from app.services.resume_parser import parse_resume_pdf

SYSTEM_PROMPT = (
    "You are a truthful cover-letter writer. Use ONLY facts present in the "
    "candidate's resume text. Never invent skills, employers, titles, metrics "
    "or achievements. Do not name any company other than the target company. "
    'Respond with JSON: {"body": "<2-3 paragraphs>"}'
)


@dataclass
class CoverLetterResult:
    cover_letter_id: str
    cover_letter: str
    approval_id: str
    approval_status: str
    flagged: list[str] = field(default_factory=list)


class FabricationError(RuntimeError):
    def __init__(self, flagged: list[str]) -> None:
        super().__init__(f"Fabricated entities detected: {flagged}")
        self.flagged = flagged


class CoverLetterAgent:
    def __init__(
        self,
        llm: LLMClient | None = None,
        guard: FabricationGuard | None = None,
        letters: CoverLetterRepository | None = None,
        approvals: ApprovalRepository | None = None,
        jobs: JobRepository | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._guard = guard or FabricationGuard()
        self._letters = letters or CoverLetterRepository()
        self._approvals = approvals or ApprovalRepository()
        self._jobs = jobs or JobRepository()

    def run(self, user_id: str, job_id: str) -> CoverLetterResult:
        job = self._jobs.get_by_id(job_id, user_id)
        if job is None:
            raise LookupError(f"Job {job_id} not found for user")

        resume_text = parse_resume_pdf(get_base_resume_path())["raw_text"]
        raw = self._llm.complete_json(
            "cover_letter",
            SYSTEM_PROMPT,
            f"Target role: {job['title']} at {job['company']}.\n"
            f"Job description: {job.get('description', '')}\n\n"
            f"Candidate resume:\n{resume_text}",
            model=get_model("REASONING"),
            temperature=0.0,
        )
        body = (raw.get("body") or "").strip()

        letter = (
            f"Dear Hiring Team at {job['company']},\n\n"
            f"I am writing to express my interest in the {job['title']} "
            f"position at {job['company']}.\n\n{body}\n\n"
            f"Thank you for your consideration.\n"
        )

        corpus = " ".join(
            [resume_text, job["title"], job["company"], job.get("description", "")]
        )
        flagged = self._guard.check(letter, corpus)
        if flagged:
            raise FabricationError(flagged)

        base_resume = TailoringAgent().ensure_base_resume(user_id)
        stored = self._letters.create(user_id, job_id, base_resume["id"], letter)
        approval = self._approvals.create(
            user_id,
            "application_submit",
            {
                "kind": "cover_letter",
                "cover_letter_id": stored["id"],
                "job_id": job_id,
                "job_title": job["title"],
                "company": job["company"],
            },
            application_id=stored["id"],
        )
        return CoverLetterResult(
            cover_letter_id=stored["id"],
            cover_letter=letter,
            approval_id=approval["id"],
            approval_status=approval["status"],
            flagged=[],
        )


def _job_summary(job: dict[str, Any]) -> str:
    return f"{job['title']} at {job['company']}"
