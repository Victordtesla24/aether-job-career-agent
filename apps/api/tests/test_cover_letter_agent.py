"""P2-S06 — Cover letter agent + FabricationGuard tests."""
from __future__ import annotations

import re

import pytest

from app.agents.cover_letter_agent import (
    CoverLetterAgent,
    StructuralError,
    split_paragraphs,
)
from app.agents.fit_scorer import get_base_resume_path
from app.services.fabrication_guard import FabricationGuard
from app.services.resume_parser import parse_resume_pdf


def _run_cover_letter(client, auth_headers) -> tuple[dict, dict]:
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202
    job = client.get("/jobs", headers=auth_headers).json()[0]
    resp = client.post(
        "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json(), job


class TestFabricationGuard:
    def test_guard_flags_unsupported_entities(self):
        guard = FabricationGuard()
        corpus = "delivery leadership python program management"
        flagged = guard.check("I worked at Google and increased revenue 300%", corpus)
        assert "Google" in flagged
        assert any("300" in f for f in flagged)

    def test_guard_passes_supported_text(self):
        guard = FabricationGuard()
        corpus = "delivery leadership Python program management at Canva"
        assert guard.check("My delivery leadership at Canva used Python", corpus) == []


class TestCoverLetterAgent:
    def test_cover_letter_contains_no_invented_claims(self, client, auth_headers):
        body, job = _run_cover_letter(client, auth_headers)
        parsed = parse_resume_pdf(get_base_resume_path())
        me = client.get("/auth/me", headers=auth_headers).json()
        signer = me.get("name") or ""
        # Mirror the agent's corpus: the letter date and signer name are
        # system-generated ground truth, not fabrications.
        corpus = " ".join(
            [
                parsed["raw_text"],
                job["title"],
                job["company"],
                job.get("description") or "",
                CoverLetterAgent._today(),
                signer,
            ]
        )
        assert FabricationGuard().check(body["cover_letter"], corpus) == []

    def test_cover_letter_references_job_and_company(self, client, auth_headers):
        body, job = _run_cover_letter(client, auth_headers)
        assert job["title"] in body["cover_letter"]
        assert job["company"] in body["cover_letter"]

    def test_cover_letter_business_format(self, client, auth_headers):
        """§10.2 output standards: date, addressee block, salutation,
        sign-off — and never the banned generic opener."""
        body, job = _run_cover_letter(client, auth_headers)
        letter = body["cover_letter"]
        assert re.match(r"^\d{1,2} [A-Z][a-z]+ \d{4}\n", letter), "missing date line"
        assert f"Hiring Team\n{job['company']}\nRe: {job['title']}" in letter, (
            "missing addressee block / Re: line"
        )
        assert f"Dear Hiring Team at {job['company']}," in letter
        assert "Sincerely," in letter, "missing sign-off"
        assert "i am writing to express my interest" not in letter.lower(), (
            "banned generic opener shipped"
        )

    def test_cover_letter_enforces_three_paragraph_contract(self, client, auth_headers):
        """GAP-P4-049: a shipped letter always has exactly 3 body paragraphs,
        a hook naming the role/company, and a real call-to-action in the close."""
        body, job = _run_cover_letter(client, auth_headers)
        letter = body["cover_letter"]
        inner = letter.split(f"Dear Hiring Team at {job['company']},\n\n", 1)[1]
        inner = inner.rsplit("\n\nSincerely,", 1)[0]
        paras = split_paragraphs(inner)
        assert len(paras) == 3, f"expected 3 body paragraphs, got {len(paras)}: {paras}"
        title_head = re.split(r"\s+[-–—/|(]\s*", job["title"])[0].strip().lower()
        assert title_head in paras[0].lower() or job["company"].lower() in paras[0].lower()
        assert any(
            cue in paras[-1].lower()
            for cue in ("interview", "discuss", "conversation", "call", "meet", "available")
        ), f"closing paragraph has no call-to-action: {paras[-1]!r}"

    def test_cover_letter_requires_approval(self, client, auth_headers):
        body, _ = _run_cover_letter(client, auth_headers)
        assert body["approval_status"] == "pending"
        assert body["approval_id"]
        pending = client.get("/approvals", headers=auth_headers).json()
        assert any(a["id"] == body["approval_id"] for a in pending)

    def test_cover_letter_endpoints(self, client, auth_headers):
        body, _ = _run_cover_letter(client, auth_headers)
        listing = client.get("/cover-letters", headers=auth_headers).json()
        assert any(cl["id"] == body["cover_letter_id"] for cl in listing)
        single = client.get(
            f"/cover-letters/{body['cover_letter_id']}", headers=auth_headers
        )
        assert single.status_code == 200
        assert single.json()["coverLetter"] == body["cover_letter"]


# --- GAP-P4-049: §10.2 structural contract is enforced with real retry/reject ---

_JOB = {"title": "DevOps Engineer", "company": "Culture Amp", "description": ""}


class TestStructuralContract:
    def test_structural_issues_detects_each_violation(self):
        agent = CoverLetterAgent()
        good = "\n\n".join(
            [
                "My work is a direct match for the DevOps Engineer role at Culture Amp.",
                "I delivered measurable outcomes across cross-functional teams.",
                "I would welcome an interview to discuss the role further.",
            ]
        )
        assert agent._structural_issues(good, _JOB) == []

        two_paras = "\n\n".join(
            ["Opening naming DevOps Engineer at Culture Amp.", "Let us discuss at an interview."]
        )
        assert any("3 paragraphs" in i for i in agent._structural_issues(two_paras, _JOB))

        no_cta = "\n\n".join(
            [
                "Opening naming DevOps Engineer at Culture Amp.",
                "Evidence paragraph describing real experience.",
                "A closing sentence that makes no request of the reader.",
            ]
        )
        assert any("call-to-action" in i for i in agent._structural_issues(no_cta, _JOB))

        banned = "\n\n".join(
            [
                "I am writing to express my interest in the DevOps Engineer role at Culture Amp.",
                "Evidence paragraph.",
                "I would welcome an interview to discuss.",
            ]
        )
        assert any("generic opener" in i for i in agent._structural_issues(banned, _JOB))

        no_hook = "\n\n".join(
            [
                "A generic opening line that names nothing specific.",
                "Evidence paragraph.",
                "I would welcome an interview to discuss.",
            ]
        )
        assert any("role or company" in i for i in agent._structural_issues(no_hook, _JOB))

    def test_violating_draft_is_retried_then_rejected(self):
        """A draft that never satisfies the contract is retried and then REJECTED
        (raising StructuralError) — never persisted as a soft best-effort pass."""

        class _StubLLM:
            def __init__(self, body: str) -> None:
                self.body = body
                self.calls = 0

            def complete_json(self, *args, **kwargs):
                self.calls += 1
                return {"body": self.body}

        class _PassGuard:
            def check(self, *args, **kwargs):
                return []

        class _JobRepo:
            def get_by_id(self, job_id, user_id):
                return dict(_JOB)

        class _UserRepo:
            def get_by_id(self, user_id):
                return {"name": "Test User"}

        class _NoPersist:
            def create(self, *args, **kwargs):
                raise AssertionError("a non-compliant letter must never be persisted")

        llm = _StubLLM("This single paragraph makes no request of the reader whatsoever.")
        agent = CoverLetterAgent(
            llm=llm,
            guard=_PassGuard(),
            letters=_NoPersist(),
            approvals=_NoPersist(),
            jobs=_JobRepo(),
            users=_UserRepo(),
        )
        with pytest.raises(StructuralError):
            agent.run("user-1", "job-1")
        # default + retry + retry2: the loop performs real corrective retries.
        assert llm.calls == 3
