"""STORM-1 — a paused agent must never mint one failed AgentRun row per job, per pass.

LIVE INCIDENT 2026-08-17. With ``resumeTailoring`` and ``coverLetter`` both
stopped from the Agents page, the board sweep still walked every eligible job
on every pass, let each dispatch be refused by the pause guard, and wrote an
``AgentRun`` row (``status='failed'``, ``error='agent_paused: ...'``) for each
refusal: 5,862 rows minted between 02:24Z and 03:04Z for one owner (~146/min),
carrying the ``AgentRun`` table to 104,791 rows while every one of those passes
burned ~291s of CPU doing no work at all.

Two separate harms, both pinned here:

* **Ledger integrity** — a failure row must mean a real failure. A refusal the
  user themselves asked for is not a failure of anything, and at ~200K rows/day
  it drowns the run history and every metric derived from it.
* **Cost** — the sweep must not attempt per-job dispatches (nor ask for a
  continuation) when the agents that would do the work are paused.

The honest replacement is a BOUNDED episode summary: at most ONE
``skipped``/``agent_paused``/``skippedJobs`` AgentRun row per user per 6h
(<= 4/day worst case), which keeps the paused state traceable in "Recent runs"
without minting per-job noise.

Mixed pause state is pinned too (clause 4 of the ledger requirement): pausing
ONE of tailor/coverLetter must never stop the sweep from doing the OTHER
agent's real work.

The agent-execution seam (``board_sweep._run_agent``) is monkeypatched with a
spy that reproduces the REAL refusal ``_dispatch`` raises for a paused agent
(HTTP 409, plain-string ``"agent_paused: ..."`` detail — pinned by
``tests/test_stopall_interim_guard.py::TestDispatchRefusal``), so these tests
exercise the sweep's orchestration contract against the true refusal shape
while the pause state itself comes from REAL ``AgentConfig`` rows written
through the real PUT endpoint.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from fastapi import HTTPException

from app.workers import board_sweep


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


def _far_deadline() -> float:
    return time.monotonic() + 3600.0


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(conn, user_id: str, *, status: str = "screening",
              fit: float | None = 80.0, title: str = "Engineer") -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, title, "Acme", "Build.", "greenhouse",
             f"https://example.com/job/{job_id}", status, fit),
        )
    conn.commit()
    return job_id


def _set_agent_enabled(client, auth_headers, ui_key: str, enabled: bool) -> None:
    """Pause/re-enable through the REAL endpoint the Agents page uses."""
    resp = client.put(
        f"/agents/config/{ui_key}", headers=auth_headers, json={"enabled": enabled}
    )
    assert resp.status_code == 200, resp.text


def _spy(calls: list[tuple[str, str]], paused: set[str]):
    """``_run_agent`` stand-in that refuses EXACTLY like the real pause guard.

    Records every dispatch attempt (so "did the sweep even try?" is
    observable), raises ``_dispatch``'s plain-string 409 for a paused agent,
    and returns a genuinely successful cover result otherwise.
    """

    def _run(uid: str, agent_key: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((agent_key, params["job_id"]))
        if agent_key in paused:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"agent_paused: {agent_key} is stopped by the user's agent "
                    "controls (Agents page). Re-enable it to run."
                ),
            )
        if agent_key == "coverLetter":
            return {"cover_letter_id": "cl-" + params["job_id"]}
        return {"resume_id": "r-" + params["job_id"], "changes": [{"field": "summary"}]}

    return _run


def _paused_runs(conn, user_id: str) -> list[dict[str, Any]]:
    """Every AgentRun row this user has that records an ``agent_paused`` skip."""
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "id", "agentName", "status", "input", "output", "error" '
            'FROM "AgentRun" WHERE "userId" = %s '
            "AND (\"output\"->>'reason' = 'agent_paused' "
            "     OR COALESCE(\"error\", '') LIKE 'agent_paused%%')",
            (user_id,),
        )
        return [
            {
                "id": r[0], "agentName": r[1], "status": r[2],
                "input": r[3] or {}, "output": r[4] or {}, "error": r[5],
            }
            for r in cur.fetchall()
        ]


class TestPausedSweepMintsNoPerJobRows:
    """Clauses 1, 2, 3, 5: both agents paused."""

    def test_two_consecutive_passes_mint_at_most_one_summary_row(
        self, db_session, client, auth_headers, user_id, monkeypatch,
    ):
        jobs = [
            # Both above the live schema's User.agentConfig column default
            # match threshold (80 — see information_schema.columns.
            # column_default, out-of-band, no matching migration file) so
            # BOTH are counted as eligible-but-paused; this test measures the
            # pause short-circuit, not the fit gate.
            _seed_job(db_session, user_id, fit=90.0),
            _seed_job(db_session, user_id, fit=85.0),
        ]
        _set_agent_enabled(client, auth_headers, "resumeTailoring", False)
        _set_agent_enabled(client, auth_headers, "coverLetter", False)

        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            board_sweep, "_run_agent", _spy(calls, {"tailor", "coverLetter"})
        )

        first = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        second = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        # (5) short-circuit: not a single per-job dispatch was attempted.
        assert calls == [], f"paused board must cost zero dispatch attempts: {calls}"
        # (1)+(2) at most ONE summary row across BOTH passes, never per job.
        rows = _paused_runs(db_session, user_id)
        assert len(rows) == 1, (
            f"expected exactly one paused-episode summary row, got {len(rows)}: "
            f"{[(r['agentName'], r['status'], r['output']) for r in rows]}"
        )
        row = rows[0]
        assert row["output"].get("skipped") is True, row
        assert row["output"].get("reason") == "agent_paused", row
        assert row["output"].get("skippedJobs") == len(jobs), row
        assert not row["input"].get("job_id"), (
            "an episode summary row is per-EPISODE, never per-job: " f"{row}"
        )
        assert row["status"] != "failed", (
            "a refusal the user asked for is not a failure — failure counts "
            f"must mean real failures: {row}"
        )
        # (3) paused work is not remaining work: no continuation re-enqueue.
        for summary in (first, second):
            assert summary["needs_continuation"] is False, summary
            assert summary["skipped_paused"] == len(jobs), summary
            assert summary["failures"] == 0, summary
            assert summary["processed"] == 0, summary

    def test_summary_row_is_deduped_for_six_hours_then_minted_again(
        self, db_session, client, auth_headers, user_id, monkeypatch,
    ):
        for _ in range(3):
            _seed_job(db_session, user_id)
        _set_agent_enabled(client, auth_headers, "resumeTailoring", False)
        _set_agent_enabled(client, auth_headers, "coverLetter", False)
        monkeypatch.setattr(
            board_sweep, "_run_agent", _spy([], {"tailor", "coverLetter"})
        )

        board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert len(_paused_runs(db_session, user_id)) == 1, (
            "one episode row for the whole board, never one per job"
        )

        # Age the episode row past the dedup window: the NEXT pause episode is
        # a new episode and must be traceable again.
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "AgentRun" SET "createdAt" = NOW() - INTERVAL \'7 hours\' '
                'WHERE "userId" = %s',
                (user_id,),
            )
        db_session.commit()

        board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert len(_paused_runs(db_session, user_id)) == 2, (
            "a pause episode outside the dedup window must be recorded once"
        )


class TestPausedEpisodeRowIsNotCountedAsWork:
    """The bounded episode row must not become a NEW dishonesty in the metrics.

    It is ``status='completed'`` (nothing failed — the user asked for the
    refusal), so ``/agents/stats`` has to exclude it from BOTH sides of the
    success ratio: no model was asked anything, so it is not a task, not a
    success and not a failure. This is where it differs from the letterless
    cover-letter degrade, which WAS a real attempt and correctly stays in the
    denominator (``test_agents_screen.py::
    test_stats_success_rate_excludes_degraded_coverletter_runs``).
    """

    def test_stats_exclude_the_paused_episode_row_from_the_ratio(
        self, client, auth_headers, test_user_id,
    ):
        from app.repositories.agent_run import AgentRunRepository
        from app.workers import board_sweep

        runs = AgentRunRepository()
        real = runs.start(test_user_id, "coverLetter", {})
        runs.finish(
            real["id"], "completed",
            output={"cover_letter_id": "cl_1", "model": "x", "costUsd": 0.01},
            cost_usd=0.01,
        )
        assert board_sweep._record_paused_skip_episode(
            test_user_id, ("tailor", "coverLetter"), 7,
        ) is True

        stats = client.get("/agents/stats", headers=auth_headers).json()
        assert stats["skippedCount"] == 1, stats
        assert stats["taskCount"] == 1, (
            "a skipped run is not a task performed: " f"{stats}"
        )
        assert stats["successRate"] == pytest.approx(100.0), (
            "the one REAL run succeeded; a pause skip must neither inflate nor "
            f"deflate that: {stats}"
        )


class TestMixedPauseStillDoesRealWork:
    """Clause 4: pausing ONE agent must not skip the OTHER agent's real work."""

    def test_paused_tailor_does_not_block_the_cover_letter(
        self, db_session, client, auth_headers, user_id, monkeypatch,
    ):
        job_id = _seed_job(db_session, user_id)
        _set_agent_enabled(client, auth_headers, "resumeTailoring", False)

        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(board_sweep, "_run_agent", _spy(calls, {"tailor"}))

        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert calls == [("coverLetter", job_id)], (
            "the paused tailor must be skipped WITHOUT a dispatch attempt and "
            f"the enabled cover agent must still run: {calls}"
        )
        assert summary["covers"] == 1 and summary["processed"] == 1, summary
        assert summary["tailored"] == 0, summary
        assert summary["skipped_paused"] == 1, summary
        assert summary["failures"] == 0, summary
        per_job = [r for r in _paused_runs(db_session, user_id) if r["input"].get("job_id")]
        assert per_job == [], f"no per-job paused row may be minted: {per_job}"

    def test_paused_cover_letter_does_not_block_tailoring(
        self, db_session, client, auth_headers, user_id, monkeypatch,
    ):
        job_id = _seed_job(db_session, user_id)
        _set_agent_enabled(client, auth_headers, "coverLetter", False)

        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(board_sweep, "_run_agent", _spy(calls, {"coverLetter"}))

        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert calls == [("tailor", job_id)], (
            "real tailoring work must still be done while only the cover "
            f"agent is paused: {calls}"
        )
        assert summary["tailored"] == 1, summary
        assert summary["covers"] == 0 and summary["processed"] == 0, summary
        assert summary["skipped_paused"] == 1, summary
        assert summary["failures"] == 0, summary
        assert summary["needs_continuation"] is False, summary
        per_job = [r for r in _paused_runs(db_session, user_id) if r["input"].get("job_id")]
        assert per_job == [], f"no per-job paused row may be minted: {per_job}"
