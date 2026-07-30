"""RT-005 — agents must manage the Applications-board swimlanes.

Operator mandate (2026-07-24): "the agents must manage the application board —
ensuring the job cards are in the correct swimlanes." Before this fix the
agent pipeline wrote ``Job.status`` exactly ZERO times: every scouted job sat
in "Discovered" forever unless a human dragged it (FEAT-B2) or the cover-letter
draft Application incidentally rendered in "Ready to Apply".

Contract locked here (forward-only, never demoting a manual move):
- ``JobRepository.advance_status`` is a guarded transition: it advances ONLY
  from an explicitly allowed set of earlier statuses and no-ops otherwise;
- scoring a job advances it discovered → screening ("Evaluating" column);
- a previously scored job still sitting at "discovered" (scored before this
  feature existed) is self-healed to "screening" on the next scorer pass;
- a manual FEAT-B2 move is never demoted by a later agent pass;
- the full pipeline leaves its top job at "ready" after tailor + cover.
"""
from __future__ import annotations

import pytest
from conftest import seed_own_resume

from app.agents.fit_scorer import get_base_resume_path
from app.repositories.job import JobRepository
from app.services.resume_parser import parse_resume_pdf


def _operator_resume_text() -> str:
    """Bundled PDF text — the corpus the static tailor/cover replay fixtures
    were recorded against (see test_pipeline.py)."""
    return parse_resume_pdf(get_base_resume_path())["raw_text"]


def _seed_jobs(client, auth_headers, raw_text: str | None = None) -> list[dict]:
    if raw_text is None:
        seed_own_resume(client, auth_headers)
    else:
        seed_own_resume(client, auth_headers, raw_text=raw_text)
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202, run.text
    jobs = client.get("/jobs?include_stale=true", headers=auth_headers).json()
    assert jobs, "scout should have persisted fixture jobs"
    return jobs


def _job_status(client, auth_headers, job_id: str) -> str:
    jobs = client.get("/jobs?include_stale=true", headers=auth_headers).json()
    return next(j["status"] for j in jobs if j["id"] == job_id)


class TestAdvanceStatusPrimitive:
    def test_advances_from_allowed_status(self, client, auth_headers):
        job = _seed_jobs(client, auth_headers)[0]
        repo = JobRepository()
        assert job["status"] == "discovered"
        assert repo.advance_status(
            job["id"], "screening", allowed_from={"discovered"}
        ) is True
        assert _job_status(client, auth_headers, job["id"]) == "screening"

    def test_noops_when_not_in_allowed_from(self, client, auth_headers):
        job = _seed_jobs(client, auth_headers)[0]
        repo = JobRepository()
        repo.update_status(job["id"], "tailoring")  # manual FEAT-B2-style move
        assert repo.advance_status(
            job["id"], "screening", allowed_from={"discovered"}
        ) is False
        assert _job_status(client, auth_headers, job["id"]) == "tailoring"

    def test_invalid_target_status_raises(self, client, auth_headers):
        repo = JobRepository()
        with pytest.raises(ValueError):
            repo.advance_status("cnope", "not-a-status", allowed_from={"discovered"})

    def test_invalid_allowed_from_raises(self, client, auth_headers):
        repo = JobRepository()
        with pytest.raises(ValueError):
            repo.advance_status("cnope", "screening", allowed_from={"bogus"})


class TestFitScorerManagesBoard:
    def test_scored_jobs_advance_to_screening(self, client, auth_headers):
        jobs = _seed_jobs(client, auth_headers)
        assert all(j["status"] == "discovered" for j in jobs)
        resp = client.post("/agents/fit-scorer/run", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        after = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        assert after and all(j["status"] == "screening" for j in after), [
            (j["id"], j["status"]) for j in after
        ]

    def test_manual_move_is_never_demoted(self, client, auth_headers):
        jobs = _seed_jobs(client, auth_headers)
        moved = jobs[0]
        JobRepository().update_status(moved["id"], "tailoring")
        resp = client.post("/agents/fit-scorer/run", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        # The manually-moved card stays where the human put it — but it IS scored.
        after = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        moved_after = next(j for j in after if j["id"] == moved["id"])
        assert moved_after["status"] == "tailoring"
        assert moved_after["fitScore"] is not None

    def test_previously_scored_job_is_self_healed(self, client, auth_headers):
        _seed_jobs(client, auth_headers)
        client.post("/agents/fit-scorer/run", headers=auth_headers)
        after = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        legacy = after[0]
        # Simulate a job scored BEFORE stage-sync existed: scored, yet discovered.
        JobRepository().update_status(legacy["id"], "discovered")
        resp = client.post("/agents/fit-scorer/run", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert _job_status(client, auth_headers, legacy["id"]) == "screening"


class TestPipelineManagesBoard:
    def test_pipeline_leaves_top_job_ready_and_rest_screening(
        self, client, auth_headers
    ):
        seed_own_resume(client, auth_headers, raw_text=_operator_resume_text())
        resp = client.post("/agents/pipeline/run", json={}, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        top = body.get("top_job_id")
        assert top, "fixture pipeline should select a top job"
        after = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        by_id = {j["id"]: j["status"] for j in after}
        if body["status"] == "awaiting_approval":
            # tailor + cover completed → the top job is Ready to Apply.
            assert by_id[top] == "ready"
        else:
            # Cover guard-rejected (degrade path): the tailored top job must
            # still sit honestly in "tailoring", never stuck in discovered.
            assert by_id[top] in ("tailoring", "ready")
        # Every other scored job advanced out of "discovered" to "screening".
        rest = {jid: s for jid, s in by_id.items() if jid != top}
        assert rest and all(s == "screening" for s in rest.values()), rest


class TestTailorEndpointManagesBoard:
    def test_tailor_run_advances_job_to_tailoring(self, client, auth_headers):
        jobs = _seed_jobs(client, auth_headers, raw_text=_operator_resume_text())
        target = jobs[0]
        resp = client.post(
            "/agents/tailor/run", json={"job_id": target["id"]}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert _job_status(client, auth_headers, target["id"]) == "tailoring"
