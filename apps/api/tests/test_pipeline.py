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


def test_pipeline_degrades_gracefully_on_cover_fabrication(monkeypatch):
    """GAP-P7-COV-PIPE-001: a coverLetter FabricationError (an ungrounded term
    survived every retry) must NOT discard the successful tailoring nor fail the
    whole job. The pipeline completes with the tailored résumé preserved and the
    cover marked unavailable + an honest message (never a raw guard exception)."""
    from app.routers import agents as agents_mod
    from app.agents.cover_letter_agent import FabricationError

    # Bypass quota/DB: run the wrapped fn directly for every _record_run node.
    monkeypatch.setattr(
        agents_mod, "_record_run", lambda uid, name, params, fn, **kw: fn()
    )

    def fake_dispatch(user_id, name, params, *, system_run=False):
        if name == "scout":
            return {"persisted": 2}
        if name == "fitScorer":
            return {"scored": 3}
        if name == "tailor":
            return {"changes": 7, "version_id": "v1"}
        if name == "coverLetter":
            raise FabricationError(["origination"])
        return {}

    monkeypatch.setattr(agents_mod, "_dispatch", fake_dispatch)

    class _FakeMatcher:
        def run(self, uid):
            return {
                "matched": 1,
                "top_job_id": "job-x",
                "top_job_title": "Senior PM",
                "top_company": "Deputy",
            }

    monkeypatch.setattr("app.agents.matcher_agent.MatcherAgent", _FakeMatcher)

    out = agents_mod._pipeline_core("u1", {}, budget_seconds=480)

    assert out["status"] == "completed"
    assert out["approvalRequired"] is False
    assert out["coverLetterUnavailable"] is True
    assert "cover letter" in out["message"].lower()
    steps = {s["agent"]: s["output"] for s in out["steps"]}
    # Tailoring is preserved (NOT discarded by the cover failure).
    assert steps["tailor"]["changes"] == 7
    # The cover step is recorded as unavailable, carrying the honest reason.
    assert steps["coverLetter"]["coverLetterUnavailable"] is True
    assert "origination" in steps["coverLetter"]["reason"]


def test_pipeline_still_awaits_approval_when_cover_succeeds(monkeypatch):
    """Regression guard: when the cover step SUCCEEDS the pipeline still returns
    the awaiting_approval contract (the degradation branch must not swallow it)."""
    from app.routers import agents as agents_mod

    monkeypatch.setattr(
        agents_mod, "_record_run", lambda uid, name, params, fn, **kw: fn()
    )

    def fake_dispatch(user_id, name, params, *, system_run=False):
        return {
            "scout": {"persisted": 2},
            "fitScorer": {"scored": 3},
            "tailor": {"changes": 7},
            "coverLetter": {"approval_id": "appr-1", "approvalRequired": True},
        }.get(name, {})

    monkeypatch.setattr(agents_mod, "_dispatch", fake_dispatch)

    class _FakeMatcher:
        def run(self, uid):
            return {"matched": 1, "top_job_id": "job-x"}

    monkeypatch.setattr("app.agents.matcher_agent.MatcherAgent", _FakeMatcher)

    out = agents_mod._pipeline_core("u1", {}, budget_seconds=480)
    assert out["status"] == "awaiting_approval"
    assert out["approvalRequired"] is True
    assert out.get("coverLetterUnavailable") is None
    assert out["approval_id"] == "appr-1"


def test_pipeline_degradation_message_honest_when_tailor_also_noops(monkeypatch):
    """Adversarial-review fix: in the COMPOUND case (tailor no-op AND cover
    guard-rejects) the degraded message must NOT claim 'your résumé was tailored'
    — no résumé version was persisted, so that would be a false success claim."""
    from app.routers import agents as agents_mod
    from app.agents.cover_letter_agent import FabricationError
    from app.agents.tailor_agent import NoChangesApplied

    monkeypatch.setattr(
        agents_mod, "_record_run", lambda uid, name, params, fn, **kw: fn()
    )

    def fake_dispatch(user_id, name, params, *, system_run=False):
        if name == "scout":
            return {"persisted": 1}
        if name == "fitScorer":
            return {"scored": 1}
        if name == "tailor":
            raise NoChangesApplied("No verifiable changes could be applied.")
        if name == "coverLetter":
            raise FabricationError(["origination"])
        return {}

    monkeypatch.setattr(agents_mod, "_dispatch", fake_dispatch)

    class _FakeMatcher:
        def run(self, uid):
            return {"matched": 1, "top_job_id": "job-x"}

    monkeypatch.setattr("app.agents.matcher_agent.MatcherAgent", _FakeMatcher)

    out = agents_mod._pipeline_core("u1", {}, budget_seconds=480)
    assert out["status"] == "completed"
    assert out["coverLetterUnavailable"] is True
    # HONEST: the tailor no-op'd, so the message must NOT claim tailoring succeeded.
    assert "was tailored" not in out["message"]
    assert "No verifiable résumé changes" in out["message"]
    steps = {s["agent"]: s["output"] for s in out["steps"]}
    assert steps["tailor"].get("noChangesApplied") is True
