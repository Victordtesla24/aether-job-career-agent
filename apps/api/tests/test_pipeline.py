"""Full-pipeline orchestration tests (defect: dead "Run Full Pipeline" button).

The Agents console showed Supervisor and Matcher as "Never run" because the
pipeline endpoint skipped those LangGraph nodes entirely. These tests pin the
contract: POST /agents/pipeline/run executes and audit-records ALL nodes
(supervisor → scout → fitScorer → matcher → tailor → coverLetter) so the
agent cards and the RECENT RUNS table reflect real activity.
"""
from __future__ import annotations

from conftest import seed_own_resume

from app.agents.fit_scorer import get_base_resume_path
from app.services.resume_parser import parse_resume_pdf


def _operator_resume_text() -> str:
    """The bundled operator PDF's own text, seeded EXPLICITLY as the fixture
    user's OWN résumé (never auto-seeded — NF-final-B-005). The pipeline runs
    the real tailor + cover-letter generation, whose STATIC replay fixtures were
    recorded against this text; a synthetic résumé would make those steps 422 on
    fabrication grounds (and the tailor collapse to a no-op)."""
    return parse_resume_pdf(get_base_resume_path())["raw_text"]


def _register_and_login(client) -> dict[str, str]:
    creds = {"email": "pipeline-user@aether.dev", "password": "Str0ngPass1"}
    client.post("/auth/register", json=creds)
    token = client.post("/auth/login", json=creds).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPipelineRun:
    def test_pipeline_records_every_node_including_supervisor_and_matcher(
        self, client, auth_headers
    ):
        # The pipeline reaches tailor/coverLetter for a matched job — both are
        # OUTBOUND paths that now require the caller's own résumé on file.
        seed_own_resume(client, auth_headers, raw_text=_operator_resume_text())
        resp = client.post("/agents/pipeline/run", json={}, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        agents_in_order = [s["agent"] for s in body["steps"]]
        # Supervisor plans first; matcher selects the top job before tailoring.
        assert agents_in_order[:4] == ["supervisor", "scout", "fitScorer", "matcher"]
        assert body["status"] in ("awaiting_approval", "completed")

        sup = body["steps"][0]["output"]
        assert sup["plan"] == ["scout", "fitScorer", "matcher", "tailor", "coverLetter"]

        matcher = body["steps"][3]["output"]
        assert "matched" in matcher and "top_job_id" in matcher

        if body["status"] == "awaiting_approval":
            assert agents_in_order == [
                "supervisor", "scout", "fitScorer", "matcher", "tailor", "coverLetter",
            ]
            assert body["approvalRequired"] is True
            assert matcher["top_job_id"] == body["top_job_id"]

        # Every node left an AgentRun audit row → no card shows "Never run".
        runs = client.get("/agents/runs", headers=auth_headers).json()
        run_agents = {r["agentName"] for r in runs}
        assert {"supervisor", "matcher"} <= run_agents

        agents = client.get("/agents", headers=auth_headers).json()
        by_name = {a["name"]: a for a in agents}
        assert by_name["supervisor"]["last_run"] is not None
        assert by_name["matcher"]["last_run"] is not None
        assert by_name["supervisor"]["status"] == "completed"
        assert by_name["matcher"]["status"] == "completed"

    def test_pipeline_with_no_jobs_completes_with_empty_match(self, client):
        headers = _register_and_login(client)
        # Defensive: if a job IS matched (fixture-dependent), the pipeline would
        # reach tailor/coverLetter, both of which now require a résumé on file.
        seed_own_resume(client, headers, raw_text=_operator_resume_text())
        resp = client.post("/agents/pipeline/run", json={}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        agents_in_order = [s["agent"] for s in body["steps"]]
        assert "supervisor" in agents_in_order and "matcher" in agents_in_order
        # Fresh user: scout fixtures may or may not persist jobs; if none were
        # persisted the pipeline must complete gracefully with matched == 0.
        matcher = next(s for s in body["steps"] if s["agent"] == "matcher")["output"]
        if body["status"] == "completed" and not body["approvalRequired"]:
            assert matcher["matched"] == 0
            assert matcher["top_job_id"] is None
