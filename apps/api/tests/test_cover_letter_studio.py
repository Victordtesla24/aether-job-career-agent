"""AGT-COVER — Cover Letter Studio endpoints (insights / refine / pdf, R11)."""
from __future__ import annotations

from conftest import FIXTURE_LLM_RESUME_TEXT, seed_own_resume


def _make_letter(client, auth_headers) -> tuple[dict, dict]:
    """Seed the fixture user their own base résumé, then a job via scout
    replay fixtures, then draft a letter for it.

    This drives a REAL (non-stub) LLM replay generation, so the seeded
    resume must ground the STATIC "default"/"retry" replay fixtures'
    vocabulary too (see FIXTURE_LLM_RESUME_TEXT docstring in conftest.py)."""
    seed_own_resume(client, auth_headers, raw_text=FIXTURE_LLM_RESUME_TEXT)
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202, run.text
    job = client.get("/jobs", headers=auth_headers).json()[0]
    resp = client.post(
        "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json(), job


class TestAuthz:
    def test_list_requires_auth(self, client):
        assert client.get("/cover-letters").status_code == 401

    def test_insights_404_for_unknown_letter(self, client, auth_headers):
        resp = client.get("/cover-letters/nope/insights", headers=auth_headers)
        assert resp.status_code == 404

    def test_pdf_404_for_unknown_letter(self, client, auth_headers):
        assert client.get("/cover-letters/nope/pdf", headers=auth_headers).status_code == 404

    def test_letter_not_visible_to_other_user(self, client, auth_headers):
        body, _ = _make_letter(client, auth_headers)
        other = {"email": "other-user@example.com", "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=other).status_code == 201
        token = client.post("/auth/login", json=other).json()["access_token"]
        resp = client.get(
            f"/cover-letters/{body['cover_letter_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


class TestInsights:
    def test_insights_computed_from_real_rows(self, client, auth_headers):
        body, job = _make_letter(client, auth_headers)
        resp = client.get(
            f"/cover-letters/{body['cover_letter_id']}/insights", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["letterId"] == body["cover_letter_id"]
        assert data["jobTitle"] == job["title"]
        assert data["company"] == job["company"]
        assert data["wordCount"] == len(body["cover_letter"].split())
        kw = data["keywords"]
        assert 0 < kw["total"] <= 10
        assert 0 <= kw["covered"] <= kw["total"]
        assert kw["covered"] == sum(1 for i in kw["items"] if i["covered"])
        assert 0 <= data["voice"]["authenticity"] <= 100
        assert 1 <= data["voice"]["aiDetectionRisk"] <= 99
        assert isinstance(data["evidence"], list)
        for row in data["evidence"]:
            assert row["claim"]
            assert row["grounded"] == bool(row["storyTitle"])
        assert [v["version"] for v in data["versions"]] == [1]
        assert data["versions"][0]["current"] is True
        assert data["versions"][0]["id"] == body["cover_letter_id"]

    def test_evidence_grounds_claims_in_story_bank(self, client, auth_headers):
        body, _ = _make_letter(client, auth_headers)
        story = {
            "title": "Delivery Leadership Program",
            "situation": "s",
            "task": "t",
            "action": "a",
            "result": "r",
            "tags": ["delivery leadership"],
        }
        created = client.post("/stories", json=story, headers=auth_headers)
        assert created.status_code in (200, 201), created.text
        data = client.get(
            f"/cover-letters/{body['cover_letter_id']}/insights", headers=auth_headers
        ).json()
        grounded = [e for e in data["evidence"] if e["grounded"]]
        if "delivery leadership" in body["cover_letter"].lower():
            assert any(
                e["storyTitle"] == "Delivery Leadership Program" for e in grounded
            )


class TestRefine:
    def test_refine_creates_new_version_and_pending_approval(self, client, auth_headers):
        body, job = _make_letter(client, auth_headers)
        resp = client.post(
            f"/cover-letters/{body['cover_letter_id']}/refine",
            json={"instructions": "Make it more concise.", "tone": 60, "formality": 55},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        refined = resp.json()
        assert refined["cover_letter_id"] != body["cover_letter_id"]
        assert job["company"] in refined["cover_letter"]
        assert refined["approval_status"] == "pending"
        # GAP-P4-049: the Request-Changes redraft is a real business letter and
        # never ships the banned generic opener the studio used to hardcode.
        assert "i am writing to express my interest" not in refined["cover_letter"].lower()
        assert f"Re: {job['title']}" in refined["cover_letter"]

        letters = client.get("/cover-letters", headers=auth_headers).json()
        assert {letter["id"] for letter in letters} >= {
            body["cover_letter_id"],
            refined["cover_letter_id"],
        }
        insights = client.get(
            f"/cover-letters/{refined['cover_letter_id']}/insights", headers=auth_headers
        ).json()
        versions = insights["versions"]
        assert [v["version"] for v in versions] == [1, 2]
        assert versions[-1]["id"] == refined["cover_letter_id"]
        assert versions[-1]["current"] is True

    def test_refine_validates_slider_bounds(self, client, auth_headers):
        body, _ = _make_letter(client, auth_headers)
        resp = client.post(
            f"/cover-letters/{body['cover_letter_id']}/refine",
            json={"tone": 150},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_refine_404_for_unknown_letter(self, client, auth_headers):
        resp = client.post(
            "/cover-letters/nope/refine", json={"instructions": "x"}, headers=auth_headers
        )
        assert resp.status_code == 404


class TestPdfExport:
    def test_pdf_is_real_and_contains_letter(self, client, auth_headers):
        body, job = _make_letter(client, auth_headers)
        resp = client.get(
            f"/cover-letters/{body['cover_letter_id']}/pdf", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert "attachment; filename=" in resp.headers["content-disposition"]
        assert resp.content.startswith(b"%PDF")
        assert len(resp.content) > 800

    def test_pdf_is_submission_ready_business_letter(self, client, auth_headers):
        """GAP-P4-048: the export is a neutral business letter — candidate contact
        details present, no third-party/tool branding or AI-generated disclosure.

        NF-final-B-001: the letterhead is grounded on the CALLER's own résumé
        contact, never the bundled operator's. A JSON-ingested résumé (as
        seeded here via ``seed_own_resume``) stores ``contact={}``, so the
        letterhead falls back to the caller's own workspace profile email —
        never the operator's phone/LinkedIn."""
        import io

        import pdfplumber

        body, job = _make_letter(client, auth_headers)
        me = client.get("/auth/me", headers=auth_headers).json()
        resp = client.get(
            f"/cover-letters/{body['cover_letter_id']}/pdf", headers=auth_headers
        )
        assert resp.status_code == 200
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        lower = text.lower()
        # The candidate's OWN contact details (workspace profile email) head
        # the letter — never the bundled operator résumé's.
        assert me["email"] in text, (
            "the caller's own profile email is missing from the sender block"
        )
        assert "+61 433 224 556" not in text, (
            "operator résumé phone leaked into another user's export"
        )
        assert "linkedin.com/in/vikramd-profile" not in lower, (
            "operator résumé LinkedIn leaked into another user's export"
        )
        # The letter still renders (addressee/company present).
        assert job["company"] in text
        # No third-party/tool branding or AI-generated disclosure.
        assert "aether" not in lower, "tool branding leaked into the export"
        assert "generated by" not in lower, "AI-generated disclosure leaked into the export"
