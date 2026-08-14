"""NTH-05 (wave2 web review, uat/reports/evidence/models-live/wave2-*-review-verdict.json)
-- TEST-ONLY pin for the snake->camel cover-letter degrade normalizer.

The Agents feed / catalog's degradation predicate (apps/web) reads
``coverLetterUnavailable`` (camelCase) off a run's output. That flag is
produced in exactly ONE place server-side --
``app/routers/agents.py`` (``_execute_reserved_run``, ~:823-827):

    cover_degraded = bool(
        output.get("cover_letter_unavailable") or output.get("coverLetterUnavailable")
    )
    if cover_degraded:
        output["coverLetterUnavailable"] = True

``CoverLetterAgent.run()`` returns a ``CoverLetterResult`` dataclass whose
field is spelled ``cover_letter_unavailable`` (snake_case); ``_to_output()``
turns it into a plain dict via ``dataclasses.asdict()``, which preserves the
snake_case key verbatim -- there is no camelCase key at all until the
normalizer above adds one. ``AgentRunRepository.finish()``/``list_recent()``
persist and return that output dict completely verbatim (no serialization-time
key transformation anywhere in the read path, app/repositories/agent_run.py).

So the ONLY thing that makes the camelCase flag exist at all, anywhere the FE
can see it, is the three-line normalizer above. This test is a deliberate
TEST-ONLY pin (agents.py itself is explicitly out of scope for this fix
bundle): it stubs ``CoverLetterAgent.run`` to return a result that carries
ONLY the snake_case flag, drives a real cover-letter run through the full
``POST /agents/cover-letter/run`` -> ``GET /agents/runs`` round trip, and
asserts the persisted, HTTP-surfaced run carries the camelCase flag. Deleting
the normalizer makes this fail loudly instead of the feed silently never
degrading.

Run under the shared test DB lock (schema=aether_test ONLY):
    flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_ml_nth05_normalizer_pin.py -q
"""
from __future__ import annotations

from app.agents.cover_letter_agent import CoverLetterAgent, CoverLetterResult
from app.repositories.job import JobRepository


def _seed_job(user_id: str) -> str:
    created = JobRepository().create(
        user_id,
        {
            "title": "Senior Backend Engineer",
            "company": "Acme Robotics",
            "location": "Remote",
            "remote": True,
            "description": "Own the backend platform end to end.",
            "requirements": [],
            "source": "test",
            "sourceUrl": "https://example.test/nth-05-normalizer-pin",
            "postedAt": None,
        },
    )
    return created["id"]


def test_snake_case_cover_letter_unavailable_surfaces_as_camelcase_via_runs_list(
    client, auth_headers, test_user_id, monkeypatch, patch_agent_run
):
    """FAILS LOUDLY if the agents.py:823-827 normalizer is ever removed.

    The stub below returns a ``CoverLetterResult`` with ONLY the snake_case
    dataclass field set -- exactly what a real degraded run looks like before
    normalization -- so the camelCase key seen through ``GET /agents/runs``
    can only exist if the normalizer actually ran.
    """
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "false")  # exercise the sync path
    job_id = _seed_job(test_user_id)

    def _degraded_run():
        return CoverLetterResult(
            cover_letter_unavailable=True,
            message="Your cover letter writing model was temporarily unavailable.",
        )

    # Signature-derived double (conftest ``patch_agent_run``): the stub only
    # has to produce the snake_case-only result this pin is about, and can no
    # longer fail merely because the real ``run`` grew a dispatch keyword.
    cover_calls = patch_agent_run(CoverLetterAgent, _degraded_run)

    resp = client.post(
        "/agents/cover-letter/run", json={"job_id": job_id}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("coverLetterUnavailable") is True
    # The normalizer under test ran over THIS stub's output — the router
    # genuinely reached the agent rather than short-circuiting somewhere.
    assert cover_calls, "the router never reached CoverLetterAgent.run"

    runs = client.get("/agents/runs", headers=auth_headers).json()
    cover_runs = [r for r in runs if r["agentName"] == "coverLetter"]
    assert cover_runs, "the coverLetter run was not audited via GET /agents/runs"
    run = cover_runs[0]
    assert run["status"] == "completed", run

    output = run["output"] or {}
    # The RAW dataclass field is snake_case -- asdict() never produces a
    # camelCase key on its own, so if this key is ever missing from the
    # persisted output the stub above (and _to_output's asdict()) changed,
    # not the normalizer this test targets.
    assert output.get("cover_letter_unavailable") is True, output
    # This is the actual pin: the camelCase key must ALSO be present, through
    # the real HTTP runs-list endpoint -- proof the normalizer fired and
    # persisted before this row was ever written to the DB.
    assert output.get("coverLetterUnavailable") is True, (
        f"GET /agents/runs did not surface camelCase coverLetterUnavailable "
        f"for a run whose agent output only set the snake_case flag -- the "
        f"agents.py cover-letter degrade normalizer is missing or broken: "
        f"{output!r}"
    )
