"""GAP-COV-VOICE (§11.3): first-person voice consistency + grammatical opener.

A live writer-audit found the generated cover letter inconsistently switched
person — the opening/closing spoke in the first person ("My background…", "I
would welcome…") while the middle lapsed into the third person about the
candidate ("Vikram's proven ability…", "his orchestration…", "His
facilitation…"). A real cover letter is the candidate SPEAKING, so it must be
first person throughout. The audit also flagged the opener grammar: "My
background in <role title> is a direct match…" reads as broken English when the
configured target role is an actual job title — it should read "…as a <role>…".

These tests exercise ``CoverLetterAgent.run`` end-to-end against a REAL seeded
job (so the deterministic hook, structural gate, FabricationGuard and injection
guard all run unmodified) with a stub LLM standing in for the model, proving:

  1. the generated letter body contains NO third-person self-reference — no
     candidate name in the possessive, and no standalone he/his/she/her/him
     referring to the candidate;
  2. the opener is grammatical for a job-title role ("…as a Senior Technical
     Program Manager…", never "…background in Senior Technical Program
     Manager…");
  3. the specific company/role hook, the closing call-to-action, the full
     §10.2 business-letter structure, and the FabricationGuard all still hold.
"""
from __future__ import annotations

import re

import pytest
from conftest import seed_own_resume

from app.agents.cover_letter_agent import (
    CoverLetterAgent,
    FabricationError,
    split_paragraphs,
)
from app.repositories.job import JobRepository
from app.services.fabrication_guard import FabricationGuard

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

_NAME = "Vikram Sarkar"
_TARGET_ROLE = "Senior Technical Program Manager"

_JOB = {
    "title": "Senior Platform Engineer",
    "company": "Culture Amp",
    "location": "Remote",
    "remote": True,
    "description": (
        "We need a senior engineer who can own sprint cadence and PI "
        "Planning, and who has shipped analytics with Next.js and Supabase."
    ),
    "requirements": [],
    "source": "test",
    "postedAt": None,
}

_HOOK_REASON = (
    "This role's focus on owning sprint cadence and PI Planning mirrors "
    "exactly how I already run delivery."
)

#: A body that lapses into the third person about the candidate mid-letter,
#: exactly like the audited draft — every capitalized/number token is grounded
#: in the resume/JD so the FabricationGuard passes and the VOICE fix is what is
#: under test (not the guard).
_THIRD_PERSON_BODY = (
    "Vikram's proven ability to own sprint cadence and PI Planning, and his "
    "delivery of analytics with Next.js and Supabase, maps directly to this "
    "role. His facilitation of PI Planning kept squads aligned.\n\n"
    "I would welcome the opportunity to discuss this further in an interview "
    "at your convenience."
)


class _VoiceUserRepoStub:
    def get_by_id(self, user_id):
        return {"name": _NAME}

    def get_target_role(self, user_id):
        return _TARGET_ROLE


class _StubLLM:
    def __init__(self, hook_reason: str, body: str) -> None:
        self.hook_reason = hook_reason
        self.body = body
        self.calls = 0

    def complete_json(self, prompt_name, system, user, **kwargs):
        self.calls += 1
        return {"hook_reason": self.hook_reason, "body": self.body}


def _seed_job(user_id: str, suffix: str, job: dict) -> str:
    created = JobRepository().create(
        user_id,
        {
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "remote": job["remote"],
            "description": job["description"],
            "requirements": job["requirements"],
            "source": job["source"],
            "sourceUrl": f"https://example.test/gap-p5-cover-voice/{suffix}",
            "postedAt": job["postedAt"],
        },
    )
    return created["id"]


def _run(client, auth_headers, suffix: str, llm) -> str:
    seed_own_resume(client, auth_headers)
    me = client.get("/auth/me", headers=auth_headers).json()
    user_id = me["id"]
    job_id = _seed_job(user_id, suffix, _JOB)
    agent = CoverLetterAgent(
        llm=llm, guard=FabricationGuard(), users=_VoiceUserRepoStub()
    )
    return agent.run(user_id, job_id).cover_letter


def _body_of(letter: str) -> str:
    inner = letter.split(f"Dear Hiring Team at {_JOB['company']},\n\n", 1)[1]
    return inner.rsplit("\n\nSincerely,", 1)[0]


class TestFirstPersonThroughout:
    def test_body_has_no_third_person_self_reference(self, client, auth_headers):
        letter = _run(
            client,
            auth_headers,
            "first-person",
            _StubLLM(_HOOK_REASON, _THIRD_PERSON_BODY),
        )
        body = _body_of(letter)
        # No candidate name in the possessive anywhere in the body.
        for name in ("Vikram", "Sarkar", "Vikram Sarkar"):
            assert f"{name}'s" not in body, f"possessive '{name}’s' leaked"
        # No standalone third-person pronoun referring to the candidate.
        assert not re.search(
            r"\b(?:he|she|his|her|hers|him)\b", body, re.I
        ), f"third-person pronoun leaked into body: {body!r}"
        # The voice was rewritten to the first person, not deleted.
        assert "My proven ability" in body
        assert "my delivery of analytics" in body
        assert "My facilitation" in body


class TestGrammaticalOpener:
    def test_opener_uses_as_a_role_not_in_role(self, client, auth_headers):
        letter = _run(
            client,
            auth_headers,
            "opener-grammar",
            _StubLLM(_HOOK_REASON, _THIRD_PERSON_BODY),
        )
        assert f"as a {_TARGET_ROLE}" in letter, letter
        # The awkward "background in <role title>" phrasing is gone.
        assert f"background in {_TARGET_ROLE}" not in letter


class TestHookAndCtaPreserved:
    def test_hook_names_role_and_company_and_closing_has_cta(
        self, client, auth_headers
    ):
        letter = _run(
            client,
            auth_headers,
            "hook-cta",
            _StubLLM(_HOOK_REASON, _THIRD_PERSON_BODY),
        )
        body = _body_of(letter)
        paras = split_paragraphs(body)
        assert len(paras) == 3, f"expected 3 body paragraphs, got {len(paras)}"
        assert _JOB["title"] in paras[0]
        assert _JOB["company"] in paras[0]
        assert _HOOK_REASON in paras[0]
        assert any(cue in paras[-1].lower() for cue in _CTA_CUES)


class TestBusinessStructurePreserved:
    def test_full_business_letter_structure_holds(self, client, auth_headers):
        letter = _run(
            client,
            auth_headers,
            "structure",
            _StubLLM(_HOOK_REASON, _THIRD_PERSON_BODY),
        )
        assert re.match(r"^\d{1,2} [A-Z][a-z]+ \d{4}\n", letter), "missing date line"
        assert (
            f"Hiring Team\n{_JOB['company']}\nRe: {_JOB['title']}" in letter
        ), "missing addressee block / Re: line"
        assert f"Dear Hiring Team at {_JOB['company']}," in letter
        assert "Sincerely," in letter, "missing sign-off"
        assert f"Sincerely,\n{_NAME}\n" in letter, "sign-off must carry the signer"


class TestFabricationGuardStillHolds:
    def test_unsupported_entity_still_rejected_under_first_person(
        self, client, auth_headers
    ):
        """First-person enforcement must not become a fabrication loophole: an
        unsupported entity in the model draft is still rejected."""
        seed_own_resume(client, auth_headers)
        me = client.get("/auth/me", headers=auth_headers).json()
        user_id = me["id"]
        job_id = _seed_job(user_id, "fab-guard", _JOB)
        llm = _StubLLM(
            "My work at Initech directly prepared me for this role.",
            _THIRD_PERSON_BODY,
        )
        agent = CoverLetterAgent(
            llm=llm, guard=FabricationGuard(), users=_VoiceUserRepoStub()
        )
        with pytest.raises(FabricationError) as exc:
            agent.run(user_id, job_id)
        assert "Initech" in exc.value.flagged
