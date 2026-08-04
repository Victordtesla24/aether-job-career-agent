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
from conftest import seed_own_resume, seed_search_target

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


def _seed_unscorable_job(user_id: str, suffix: str) -> dict:
    """A posting with a 0-character description: no scorable evidence
    (``app.services.fit_evidence.has_scorable_evidence``, landed 557739e —
    "an empty job description was scoring 74.63 — refuse to score on no
    evidence"). Used to prove the evidence gate positively, not just assume
    it (RULING 3, docs/delivery/BACKEND-RED-TESTS-2026-08-03.md)."""
    return JobRepository().create(
        user_id,
        {
            "title": "Unscorable — empty description",
            "company": "Nobody",
            "location": None,
            "remote": False,
            "description": "",
            "requirements": [],
            "source": "manual",
            "sourceUrl": f"https://example.invalid/ruling3-empty-description/{suffix}",
            "postedAt": None,
        },
    )


class TestFitScorerManagesBoard:
    def test_scored_jobs_advance_to_screening(self, client, auth_headers, test_user_id):
        from app.services.fit_evidence import has_scorable_evidence, job_evidence_text

        jobs = _seed_jobs(client, auth_headers)
        assert all(j["status"] == "discovered" for j in jobs)

        # RULING 3: seed one job with no scorable evidence alongside the real
        # fixture jobs, so this test can assert BOTH halves of the evidence
        # gate contract in a single pass — scorable jobs advance, the
        # unscorable one honestly does not.
        empty_job = _seed_unscorable_job(test_user_id, "fit-scorer")
        assert empty_job["status"] == "discovered"
        assert not has_scorable_evidence(job_evidence_text(empty_job))

        resp = client.post("/agents/fit-scorer/run", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        run = resp.json()
        assert run["errors"] == [], run
        after = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        assert after

        # Partition the board by the SAME gate the write path uses
        # (fit_scorer.FitScorer.run -> has_scorable_evidence(self._job_text(job))),
        # rather than assuming which fixture postings carry a description.
        scorable = [j for j in after if has_scorable_evidence(job_evidence_text(j))]
        unscorable = [j for j in after if not has_scorable_evidence(job_evidence_text(j))]
        # Neither half may be empty, or one of the two directions below would
        # pass vacuously.
        assert scorable, "fixture board must contain scorable postings"
        assert unscorable, "fixture board must contain unscorable postings"

        # Direction 1 — scoring advances the card. Every scorable posting
        # carries a real score AND sits in "Evaluating".
        assert all(j["status"] == "screening" for j in scorable), [
            (j["id"], j["status"]) for j in scorable if j["status"] != "screening"
        ]
        assert all(j["fitScore"] is not None for j in scorable), [
            j["id"] for j in scorable if j["fitScore"] is None
        ]

        # Direction 2 — NOT scoring must NOT advance the card. This is the
        # assertion that protects the evidence gate: before 557739e a 0-char
        # description scored ~74.63 and led the board.
        assert all(j["status"] == "discovered" for j in unscorable), [
            (j["id"], j["status"]) for j in unscorable if j["status"] != "discovered"
        ]
        assert all(j["fitScore"] is None for j in unscorable), [
            j["id"] for j in unscorable if j["fitScore"] is not None
        ]
        # ...and the ONLY member of that half is the control we deliberately
        # made unscorable. Equality, not membership: the `unscorable` half is
        # otherwise bounded only by `assert unscorable` above, which this
        # test's own seeded control satisfies by construction — so without
        # this line the partition puts NO bound on how much of a real board
        # may go unranked. A regression where an adapter stops delivering
        # descriptions would reclassify those cards into the `unscorable`
        # half and be asserted to leave them in "discovered", i.e. the
        # partition would bless the symptom the RT-005 mandate exists to
        # catch. Every real fixture posting must still advance (measured
        # 2026-08-04 on the fixture-pinned board of 73f98c5: 30/30 scorable,
        # 0 real postings unscorable).
        assert {j["id"] for j in unscorable} == {empty_job["id"]}, [
            (j["id"], j.get("title"), len(job_evidence_text(j))) for j in unscorable
        ]

        # The agent's own tally must agree with the board partition — every
        # scorable job was freshly scored in this run, nothing else was.
        assert run["scored"] == len(scorable), (run["scored"], len(scorable))

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
        self, client, auth_headers, test_user_id
    ):
        from app.services.fit_evidence import has_scorable_evidence, job_evidence_text

        seed_own_resume(client, auth_headers, raw_text=_operator_resume_text())

        # RULING 3 (BACKEND-RED-TESTS-2026-08-03.md): seed one job with a
        # 0-character description alongside the real fixture jobs the
        # pipeline's own scout step will discover. It carries no scorable
        # evidence and must be honestly left at "discovered" through the
        # whole pipeline run — never scored, never selected as top job,
        # never advanced.
        empty_job = _seed_unscorable_job(test_user_id, "pipeline")
        assert not has_scorable_evidence(job_evidence_text(empty_job))

        # F-02: an empty pipeline body now derives the scout step's search from
        # THIS user's profile (and refuses when they have none), so the run
        # needs a configured target. These are the values the router used to
        # substitute for every caller, so the board this test asserts on is
        # sourced exactly as before.
        seed_search_target(
            client, auth_headers,
            target_role="Business Analyst", location="Melbourne, Australia",
        )
        resp = client.post("/agents/pipeline/run", json={}, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        top = body.get("top_job_id")
        assert top, "fixture pipeline should select a top job"
        assert top != empty_job["id"], "an unscorable job must never be selected as top"
        after = client.get("/jobs?include_stale=true", headers=auth_headers).json()
        by_id = {j["id"]: j["status"] for j in after}
        if body["status"] == "awaiting_approval":
            # tailor + cover completed → the top job is Ready to Apply.
            assert by_id[top] == "ready"
        else:
            # Cover guard-rejected (degrade path): the tailored top job must
            # still sit honestly in "tailoring", never stuck in discovered.
            assert by_id[top] in ("tailoring", "ready")

        # Every other SCORABLE posting advanced out of "discovered" to
        # "screening". Scoped by the write path's OWN gate (RULING 3), not by
        # an assumption about which fixture postings carry a description.
        rest_scorable = [
            j
            for j in after
            if j["id"] != top and has_scorable_evidence(job_evidence_text(j))
        ]
        assert rest_scorable, "fixture board must contain other scorable postings"
        assert all(j["status"] == "screening" for j in rest_scorable), [
            (j["id"], j["status"]) for j in rest_scorable if j["status"] != "screening"
        ]

        # The evidence gate holds across the WHOLE pipeline run
        # (scout -> fitScorer -> matcher -> tailor -> cover), not just the
        # scorer: an unscorable posting is never given a score and never
        # leaves "discovered".
        unscorable = [j for j in after if not has_scorable_evidence(job_evidence_text(j))]
        assert unscorable, "fixture board must contain unscorable postings"
        assert all(j["status"] == "discovered" for j in unscorable), [
            (j["id"], j["status"]) for j in unscorable if j["status"] != "discovered"
        ]
        assert all(j["fitScore"] is None for j in unscorable), [
            j["id"] for j in unscorable if j["fitScore"] is not None
        ]
        # Equality, not membership — see the twin assertion in
        # TestFitScorerManagesBoard::test_scored_jobs_advance_to_screening.
        # The seeded control is the ONLY posting allowed to sit out; every
        # real fixture posting the pipeline sourced must still have moved.
        assert {j["id"] for j in unscorable} == {empty_job["id"]}, [
            (j["id"], j.get("title"), len(job_evidence_text(j))) for j in unscorable
        ]


class TestTailorEndpointManagesBoard:
    def test_tailor_run_advances_job_to_tailoring(self, client, auth_headers):
        jobs = _seed_jobs(client, auth_headers, raw_text=_operator_resume_text())
        target = jobs[0]
        resp = client.post(
            "/agents/tailor/run", json={"job_id": target["id"]}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert _job_status(client, auth_headers, target["id"]) == "tailoring"
