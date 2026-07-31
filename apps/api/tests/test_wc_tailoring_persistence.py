"""GOLD-MASTER-V2 §5.4 (gate G-C) — failing integration tests proving the
CURRENT single-pass ``/agents/tailor/run`` pipeline (a) never persists
per-iteration tailoring history (§5.3.3) and (b) never surfaces an honest
sub-85 warning (§5.3.1 point 5), reproduced against REAL running code (the
committed ``tests/fixtures/llm/tailor/default.json`` replay fixture and the
real DB), not a stub.

Ground truth measured this run: the live single-pass tailor yields a +0.10
ATS delta that rounds to +0.0% in the UI; every one of the 51 production jobs
sampled scores below 85 (24.89-50.05, avg 39.63). The backend already
computes a ``requires_review`` signal on every ``ATSScore`` — it is never
surfaced on the tailor-run response today.
"""
from __future__ import annotations

from conftest import seed_own_resume

from app.agents.fit_scorer import get_base_resume_path
from app.services.resume_parser import parse_resume_pdf


def _own_operator_text() -> str:
    return parse_resume_pdf(get_base_resume_path())["raw_text"]


def _seed_job(client, auth_headers) -> dict:
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202
    return client.get("/jobs", headers=auth_headers).json()[0]


def _run_tailor(client, auth_headers) -> dict:
    seed_own_resume(client, auth_headers, raw_text=_own_operator_text())
    job = _seed_job(client, auth_headers)
    resp = client.post(
        "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestTailoringLoopPersistence:
    def test_tailored_resume_persists_per_iteration_history(self, client, auth_headers):
        """§5.3.3: each iteration's output + score must persist on the
        tailored Resume so the UI can show progress honestly. The current
        agent performs exactly ONE tailoring pass with no per-iteration
        record at all — this pins the future contract
        (``sections.tailoringIterations``: a list of
        ``{"iteration", "score", "changes", ...}`` dicts) and fails on that
        gap today."""
        body = _run_tailor(client, auth_headers)
        resume = client.get(f"/resumes/{body['resume_id']}", headers=auth_headers).json()
        iterations = (resume.get("sections") or {}).get("tailoringIterations")
        assert iterations, (
            "expected sections.tailoringIterations on the tailored resume so "
            "the UI can show per-iteration progress honestly; got sections "
            f"keys: {sorted((resume.get('sections') or {}).keys())}"
        )
        assert isinstance(iterations, list) and len(iterations) >= 1
        first = iterations[0]
        assert {"iteration", "score", "changes"} <= set(first.keys()), first
        assert isinstance(first["score"], (int, float))

    def test_tailor_run_never_claims_success_below_the_85_target(self, client, auth_headers):
        """§5.3.1 point 5: the backend already computes ``requires_review`` on
        every ATSScore — the tailor-run response must SURFACE an honest
        sub-85 signal instead of reporting only baseline/tailored score
        numbers with no verdict. Measured live: the committed replay
        fixture's rewrite does not clear 85 (matches production: 51/51 jobs
        sampled scored 24.89-50.05), so this run is a genuine sub-target
        case, not a contrived one."""
        body = _run_tailor(client, auth_headers)
        metrics = body["conversionMetrics"]
        assert metrics["tailoredATSScore"] < 85, (
            "fixture assumption broken — re-baseline this test if the replay "
            f"fixture now clears 85 (conversionMetrics={metrics})"
        )
        assert "requires_review" in metrics, sorted(metrics.keys())
        assert metrics["requires_review"] is True
        assert body.get("warning"), "expected an honest sub-85 warning on the run response"
