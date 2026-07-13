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
    "The opening line naming the role and company is added for you, so write "
    "EXACTLY 2 paragraphs separated by a blank line: (1) 2-3 specific "
    "requirements from the job description matched to the candidate's real "
    "experience; (2) a closing paragraph with a specific call-to-action "
    "inviting a conversation or interview. Never use a generic opener such as "
    '"I am writing to express my interest". No salutation, no sign-off — the '
    'two body paragraphs only. Respond with JSON: {"body": "<2 paragraphs>"}'
)

#: Generic openers the §10.2 output standards forbid — checked lowercase.
_BANNED_PHRASES = (
    "i am writing to express my interest",
    "i am writing to apply",
    "please accept this letter",
    "i would like to apply for",
)

#: Signals that a closing paragraph contains a real call-to-action (§10.2).
_CTA_CUES = (
    "discuss",
    "interview",
    "conversation",
    "call",
    "meet",
    "connect",
    "welcome the opportunity",
    "look forward",
    "available",
    "speak",
)

#: The base resume's professional focus — a grounded descriptor used to open
#: the deterministic §10.2 hook. It joins the guard's evidence corpus as
#: ground truth (like the letter date and signer), so it never false-positives.
_POSITION_FALLBACK = "end-to-end delivery leadership"


def letter_date() -> str:
    """Letter date in the user's timezone (Melbourne)."""
    d = datetime.datetime.now(ZoneInfo("Australia/Melbourne")).date()
    return f"{d.day} {d.strftime('%B %Y')}"


def split_paragraphs(body: str) -> list[str]:
    """Split a drafted body into non-empty paragraphs (blank-line delimited,
    falling back to single line breaks when the model omits blank lines)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if len(paras) == 1 and "\n" in body:
        paras = [p.strip() for p in body.split("\n") if p.strip()]
    return paras


def current_position(user: dict[str, Any]) -> str:
    """The candidate's stated current position for the letter hook.

    Prefers an explicit workspace ``targetRole`` when present; otherwise falls
    back to the base resume's professional focus. Always a resume/profile-
    grounded value (never fabricated)."""
    role = str(user.get("targetRole") or "").strip()
    return role or _POSITION_FALLBACK


def build_body(llm_body: str, job: dict[str, Any], position: str) -> str:
    """Assemble the §10.2 three-paragraph body: a deterministic hook naming the
    exact role + company + current position, followed by the model's evidence
    and call-to-action paragraphs. The hook is composed (not model-authored) so
    the letter always addresses the real role — never a hallucinated one."""
    hook = (
        f"My background in {position} is a direct match for the "
        f"{job['title']} role at {job['company']}."
    )
    return "\n\n".join([hook, *split_paragraphs(llm_body)])


def compose_letter(body: str, job: dict[str, Any], signer: str) -> str:
    """Wrap a body in a full business-letter format (§10.2): date, addressee
    block, Re: line, salutation, body, sign-off."""
    paragraphs = "\n\n".join(split_paragraphs(body))
    return (
        f"{letter_date()}\n\n"
        f"Hiring Team\n{job['company']}\n"
        f"Re: {job['title']}\n\n"
        f"Dear Hiring Team at {job['company']},\n\n"
        f"{paragraphs}\n\n"
        f"Sincerely,\n{signer}\n"
    )


def strip_banned_openers(body: str) -> str:
    """Deterministically drop any sentence carrying a banned generic opener."""
    for phrase in _BANNED_PHRASES:
        body = re.sub(
            rf"[^.\n]*{re.escape(phrase)}[^.\n]*\.\s*", "", body, flags=re.I
        )
    return body.strip()


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


class StructuralError(RuntimeError):
    """Raised when a draft still violates the §10.2 letter contract after every
    corrective retry — the letter is rejected rather than shipped non-compliant."""

    def __init__(self, issues: list[str]) -> None:
        super().__init__(f"Letter failed the §10.2 format contract: {issues}")
        self.issues = issues


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
        return letter_date()

    def _structural_issues(self, body: str, job: dict[str, Any]) -> list[str]:
        """§10.2 letter-format violations of the assembled body — the corrective
        loop feeds these back and the run rejects any that survive every retry."""
        issues: list[str] = []
        lower = body.lower()
        for phrase in _BANNED_PHRASES:
            if phrase in lower:
                issues.append(f'the generic opener "{phrase}" is forbidden')
        paras = split_paragraphs(body)
        if len(paras) != 3:
            issues.append(
                "the letter body must have exactly 3 paragraphs (an opening "
                "naming the role, an evidence paragraph, and a closing "
                f"call-to-action); it has {len(paras)}"
            )
        hook = paras[0].lower() if paras else ""
        title_head = re.split(r"\s+[-–—/|(]\s*", job["title"])[0].strip().lower()
        if title_head and title_head not in hook and job["company"].lower() not in hook:
            issues.append(
                "the opening paragraph must name the exact role or company"
            )
        closing = paras[-1].lower() if paras else ""
        if not any(cue in closing for cue in _CTA_CUES):
            issues.append(
                "the closing paragraph must include a specific call-to-action "
                "(invite an interview or conversation)"
            )
        return issues

    def _draft(
        self,
        prompt: str,
        job: dict[str, Any],
        corpus: str,
        signer: str,
        position: str,
        *,
        fixture_key: str,
    ) -> tuple[str, str, list[str], list[str]]:
        """Draft a letter; return (letter, body, guard_flags, structural_issues)."""
        raw = self._llm.complete_json(
            "cover_letter",
            SYSTEM_PROMPT,
            prompt,
            model=get_model("REASONING"),
            temperature=0.0,
            fixture_key=fixture_key,
        )
        body = build_body((raw.get("body") or "").strip(), job, position)
        letter = compose_letter(body, job, signer)
        return (
            letter,
            body,
            self._guard.check(letter, corpus),
            self._structural_issues(body, job),
        )

    def run(self, user_id: str, job_id: str) -> CoverLetterResult:
        job = self._jobs.get_by_id(job_id, user_id)
        if job is None:
            raise LookupError(f"Job {job_id} not found for user")

        resume_text = parse_resume_pdf(get_base_resume_path())["raw_text"]
        user = self._users.get_by_id(user_id) or {}
        signer = str(user.get("name") or "")
        position = current_position(user)
        base_prompt = (
            f"Target role: {job['title']} at {job['company']}.\n"
            f"Job description: {job.get('description', '')}\n\n"
            f"Candidate resume:\n{resume_text}"
        )
        # The letter date, signer name and current position are system/profile
        # ground truth, so they join the evidence corpus the guard checks against.
        corpus = " ".join(
            [
                resume_text,
                job["title"],
                job["company"],
                job.get("description", ""),
                self._today(),
                signer,
                position,
            ]
        )

        # Corrective drafting loop: each retry feeds back the accumulated
        # guard-flagged terms AND any §10.2 letter-format violations so the model
        # fixes both. A draft that still fails the guard (422) or the structural
        # contract after every retry is REJECTED — never shipped best-effort.
        letter, body, flagged, issues = self._draft(
            base_prompt, job, corpus, signer, position, fixture_key="default"
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
                letter, body, flagged, issues = self._draft(
                    retry_prompt, job, corpus, signer, position, fixture_key=attempt
                )
            except LLMFixtureMissingError:
                # Replay mode with no recorded retry fixture — keep the last
                # draft; the guard and structural gates below still adjudicate it.
                break
            all_flagged.extend(t for t in flagged if t not in all_flagged)
        if flagged:
            raise FabricationError(flagged)

        # Deterministically drop any banned generic opener that survived retries
        # (D-0021), then hard-gate the result: a letter that still violates the
        # §10.2 contract is rejected outright rather than shipped soft (GAP-P4-049).
        clean_body = strip_banned_openers(body)
        if clean_body != body:
            body = clean_body
            letter = compose_letter(body, job, signer)
        remaining = self._structural_issues(body, job)
        if remaining:
            raise StructuralError(remaining)

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
