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

import datetime
import re
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from app.agents.fit_scorer import get_base_resume_path
from app.agents.tailor_agent import TailoringAgent
from app.repositories.approval import ApprovalRepository
from app.repositories.cover_letter import CoverLetterRepository
from app.repositories.job import JobRepository
from app.repositories.user import UserRepository
from app.services.fabrication_guard import FabricationGuard
from app.services.llm_client import LLMClient, LLMFixtureMissingError, get_model
from app.services.resume_parser import parse_resume_pdf

SYSTEM_PROMPT = (
    "You are a truthful cover-letter writer. Use ONLY facts present in the "
    "candidate's resume text. Never invent skills, employers, titles, metrics "
    "or achievements. Do not name any company other than the target company. "
    "Write EXACTLY 3 paragraphs separated by blank lines: (1) a specific hook "
    "naming the exact role and company plus the candidate's current position — "
    'never the phrase "I am writing to express my interest"; (2) 2-3 specific '
    "requirements from the job description matched to the candidate's real "
    "experience; (3) a close with a specific call-to-action inviting a "
    "conversation or interview. No salutation, no sign-off — body only. "
    'Respond with JSON: {"body": "<3 paragraphs>"}'
)

#: Generic openers the output standards forbid (§10.2) — checked lowercase.
_BANNED_PHRASES = ("i am writing to express my interest",)


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
        users: UserRepository | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._guard = guard or FabricationGuard()
        self._letters = letters or CoverLetterRepository()
        self._approvals = approvals or ApprovalRepository()
        self._jobs = jobs or JobRepository()
        self._users = users or UserRepository()

    @staticmethod
    def _today() -> str:
        """Letter date in the user's timezone (Melbourne)."""
        d = datetime.datetime.now(ZoneInfo("Australia/Melbourne")).date()
        return f"{d.day} {d.strftime('%B %Y')}"

    @staticmethod
    def _paragraphs(body: str) -> list[str]:
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        if len(paras) == 1 and "\n" in body:
            paras = [p.strip() for p in body.split("\n") if p.strip()]
        return paras

    def _structural_issues(self, body: str, job: dict[str, Any]) -> list[str]:
        """§10.2 letter-format violations the corrective loop feeds back."""
        issues: list[str] = []
        lower = body.lower()
        for phrase in _BANNED_PHRASES:
            if phrase in lower:
                issues.append(f'generic opener "{phrase}" is forbidden')
        paras = self._paragraphs(body)
        if len(paras) != 3:
            issues.append(f"body must be exactly 3 paragraphs (got {len(paras)})")
        hook = paras[0].lower() if paras else ""
        title_head = re.split(r"\s+[-–—/|(]\s*", job["title"])[0].strip().lower()
        if title_head and title_head not in hook and job["company"].lower() not in hook:
            issues.append(
                "the first paragraph must name the exact role or company as a hook"
            )
        return issues

    def _compose(self, body: str, job: dict[str, Any], signer: str) -> str:
        """Wrap the drafted body in a full business-letter format:
        date, addressee block, Re: line, salutation, body, sign-off."""
        paragraphs = "\n\n".join(self._paragraphs(body))
        return (
            f"{self._today()}\n\n"
            f"Hiring Team\n{job['company']}\n"
            f"Re: {job['title']}\n\n"
            f"Dear Hiring Team at {job['company']},\n\n"
            f"{paragraphs}\n\n"
            f"Sincerely,\n{signer}\n"
        )

    def _draft(
        self,
        prompt: str,
        job: dict[str, Any],
        corpus: str,
        signer: str,
        *,
        fixture_key: str,
    ) -> tuple[str, list[str], list[str]]:
        """Draft a letter; return (letter, guard_flags, structural_issues)."""
        raw = self._llm.complete_json(
            "cover_letter",
            SYSTEM_PROMPT,
            prompt,
            model=get_model("REASONING"),
            temperature=0.0,
            fixture_key=fixture_key,
        )
        body = (raw.get("body") or "").strip()
        letter = self._compose(body, job, signer)
        return letter, self._guard.check(letter, corpus), self._structural_issues(body, job)

    def run(self, user_id: str, job_id: str) -> CoverLetterResult:
        job = self._jobs.get_by_id(job_id, user_id)
        if job is None:
            raise LookupError(f"Job {job_id} not found for user")

        parsed = parse_resume_pdf(get_base_resume_path())
        resume_text = parsed["raw_text"]
        user = self._users.get_by_id(user_id) or {}
        signer = user.get("name") or (parsed.get("contact") or {}).get("name") or ""
        base_prompt = (
            f"Target role: {job['title']} at {job['company']}.\n"
            f"Job description: {job.get('description', '')}\n\n"
            f"Candidate resume:\n{resume_text}"
        )
        # The letter date and signer name are system-generated ground truth,
        # so they join the evidence corpus the guard checks against.
        corpus = " ".join(
            [
                resume_text,
                job["title"],
                job["company"],
                job.get("description", ""),
                self._today(),
                signer,
            ]
        )

        # Corrective drafting loop: each retry feeds back the accumulated
        # guard-flagged terms AND any letter-format violations (§10.2) so the
        # model fixes both. Guard failures after the final attempt fail loudly
        # (422); format issues fail soft — any banned generic sentence is
        # stripped deterministically instead of shipping it.
        letter, flagged, issues = self._draft(
            base_prompt, job, corpus, signer, fixture_key="default"
        )
        all_flagged: list[str] = list(flagged)
        for attempt in ("retry", "retry2"):
            if not flagged and not issues:
                break
            feedback: list[str] = []
            if all_flagged:
                feedback.append(
                    f"your previous draft mentioned terms with no evidence in the "
                    f"resume or job description: {all_flagged}. Rewrite the letter "
                    "WITHOUT those terms. Use ONLY words, exact spellings and "
                    "numbers that appear verbatim in the resume or job description "
                    "above (e.g. never abbreviate or restate a metric). Do not "
                    "introduce any other skill, tool, company or figure."
                )
            if issues:
                feedback.append("fix these format violations: " + "; ".join(issues))
            retry_prompt = f"{base_prompt}\n\nIMPORTANT: " + " ALSO: ".join(feedback)
            try:
                letter, flagged, issues = self._draft(
                    retry_prompt, job, corpus, signer, fixture_key=attempt
                )
            except LLMFixtureMissingError:
                # Replay mode with no recorded retry fixture — keep the last
                # draft; guard failures still fail loudly below, format
                # issues fall through to the deterministic strip.
                break
            all_flagged.extend(t for t in flagged if t not in all_flagged)
        if flagged:
            raise FabricationError(flagged)
        for phrase in _BANNED_PHRASES:
            letter = re.sub(
                rf"[^.\n]*{re.escape(phrase)}[^.\n]*\.\s*", "", letter, flags=re.I
            )

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
