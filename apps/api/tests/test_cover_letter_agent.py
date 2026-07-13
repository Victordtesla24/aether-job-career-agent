"""P2-S06 — Cover letter agent + FabricationGuard tests."""
from __future__ import annotations

import re

from app.agents.cover_letter_agent import CoverLetterAgent
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
