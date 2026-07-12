"""P2-S05 — Resume tailoring agent tests (LLM record-replay mode)."""
from __future__ import annotations

from app.agents.fit_scorer import get_base_resume_path
from app.services.resume_parser import compute_format_hash, parse_resume_pdf
from app.services.resume_tailor import _evidence_index, unsupported_tokens


def _seed_job(client, auth_headers) -> dict:
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202
    return client.get("/jobs", headers=auth_headers).json()[0]


def _run_tailor(client, auth_headers) -> dict:
    job = _seed_job(client, auth_headers)
    resp = client.post(
        "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestTailoring:
    def test_tailoring_does_not_invent_skills(self, client, auth_headers):
        """Every accepted bullet is fully evidence-traced (D-0015 semantics)."""
        body = _run_tailor(client, auth_headers)
        resume = client.get(f"/resumes/{body['resume_id']}", headers=auth_headers).json()
        raw_text = parse_resume_pdf(get_base_resume_path())["raw_text"]
        stems, numbers = _evidence_index(raw_text)
        for bullet in resume["sections"]["bullets"]:
            novel = unsupported_tokens(bullet["text"], stems, numbers)
            assert not novel, f"invented tokens: {novel}"

    def test_every_changed_bullet_has_evidence_ref(self, client, auth_headers):
        body = _run_tailor(client, auth_headers)
        resume = client.get(f"/resumes/{body['resume_id']}", headers=auth_headers).json()
        for bullet in resume["sections"]["bullets"]:
            assert bullet.get("evidenceRef"), f"missing evidenceRef: {bullet}"

    def test_format_hash_unchanged_after_tailoring(self, client, auth_headers):
        before = compute_format_hash(get_base_resume_path())
        _run_tailor(client, auth_headers)
        assert compute_format_hash(get_base_resume_path()) == before

    def test_tailored_resume_is_child_of_base(self, client, auth_headers):
        body = _run_tailor(client, auth_headers)
        resume = client.get(f"/resumes/{body['resume_id']}", headers=auth_headers).json()
        assert resume["parentId"] is not None
        parent = client.get(f"/resumes/{resume['parentId']}", headers=auth_headers).json()
        assert parent["parentId"] is None  # parent is the base resume

    def test_resume_list_and_diff_endpoints(self, client, auth_headers):
        body = _run_tailor(client, auth_headers)
        resumes = client.get("/resumes", headers=auth_headers).json()
        assert len(resumes) >= 2  # base + tailored
        diff = client.get(f"/resumes/{body['resume_id']}/diff", headers=auth_headers)
        assert diff.status_code == 200
        assert "changes" in diff.json()
        download = client.get(
            f"/resumes/{body['resume_id']}/download", headers=auth_headers
        )
        assert download.status_code == 200
        assert download.headers.get("content-type") == "application/pdf"
