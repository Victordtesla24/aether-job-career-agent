"""P2-S04 — FitScorer agent tests.

The FitScorer agent runs the ATS engine over every unscored job for the
authenticated user and persists ``fitScore`` + ``atsScore``.
"""
from __future__ import annotations


def _seed_jobs(client, auth_headers) -> list[dict]:
    """Run the scout (fixture mode) to seed discoverable jobs."""
    from conftest import seed_own_resume

    # NF-final-B-008: the fit scorer scores only against the caller's OWN
    # resume, so give this user one (otherwise the run is honestly refused).
    seed_own_resume(client, auth_headers)
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202, run.text
    # include_stale=true → the FULL persisted set (the fit scorer scores every
    # persisted job, not just the active-feed subset that GAP-P6-DATA-001 shows).
    jobs = client.get("/jobs?include_stale=true", headers=auth_headers).json()
    assert jobs, "scout should have persisted fixture jobs"
    return jobs


class TestFitScorer:
    def test_fit_scorer_updates_job_scores(self, client, auth_headers):
        jobs = _seed_jobs(client, auth_headers)
        assert all(j["fitScore"] is None for j in jobs)

        resp = client.post("/agents/fit-scorer/run", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # v5 CONTRACT: not every persisted job is scorable. A posting carrying
        # only a teaser line is REFUSED rather than given a spuriously-high
        # score (production measurement: <200-char rows averaged 58.9 vs 40.8
        # for rows with a real description, topping out at 74.63 on an EMPTY
        # one). So the guarantee is "every job with real evidence is scored,
        # and nothing is silently dropped" — not "scored == len(jobs)".
        assert body["scored"] >= 1, body
        scored = client.get("/jobs", headers=auth_headers).json()
        for job in scored:
            if job["fitScore"] is None:
                # Unscored is allowed ONLY for a posting without real evidence.
                assert job["atsScore"] is None
                continue
            assert 0 <= job["fitScore"] <= 100
            assert job["atsScore"] is not None
            assert 0 <= job["atsScore"] <= 100
        assert any(j["fitScore"] is not None for j in scored)

    def test_jobs_sorted_by_fit_score(self, client, auth_headers):
        _seed_jobs(client, auth_headers)
        client.post("/agents/fit-scorer/run", headers=auth_headers)

        # Unscorable postings carry a NULL fitScore (v5 evidence gate), so the
        # ordering guarantee applies to the scores that actually exist.
        resp = client.get("/jobs?sort=fitScore", headers=auth_headers)
        assert resp.status_code == 200
        scores = [j["fitScore"] for j in resp.json() if j["fitScore"] is not None]
        assert scores == sorted(scores, reverse=True)

        # snake_case alias also accepted per spec.
        resp2 = client.get("/jobs?sort=fit_score", headers=auth_headers)
        assert resp2.status_code == 200
        scores2 = [j["fitScore"] for j in resp2.json() if j["fitScore"] is not None]
        assert scores2 == sorted(scores2, reverse=True)
