"""ML-STOPALL-001 — "Stop All Agents" must actually stop agents.

Operator-reported honesty defect: the Agents page "Stop All Agents" control
reported success ("Paused N agents. New runs are on hold.") but NOTHING
enforced the pause — ``AgentConfig.enabled`` was written by the per-agent
PATCH and read back ONLY for catalog display; no dispatch path ever
consulted it, so a "paused" agent kept running/being scheduled exactly as
before.

The fix adds a single honest-refusal check inside ``_execute_reserved_run``
(``routers/agents.py``) — the ONE function every dispatch path converges on
immediately before real work happens:

* the synchronous route -> ``_dispatch`` -> ``_record_run`` -> HERE
* every direct pipeline ``_record_run`` call -> HERE
* the async ARQ worker's ``_run_single_agent_body`` -> HERE (bypasses
  ``_record_run`` entirely, calling this function directly)
* the board-sweep autopilot's ``_run_agent`` -> ``_dispatch`` -> HERE

These tests pin: (a) the core defect at the lowest level (a direct
``_dispatch`` call), (b) the SAME refusal through a real HTTP entry point
(the generic ``/agents/{name}/run`` route) to prove it is the one shared
chokepoint and not a route-local check, (c) the pre-existing "no config row
== enabled" default is unchanged, (d) the board-sweep autopilot treats the
refusal as an honest per-job SKIP (not a sweep failure, not an abort), and
(e) re-enabling the agent lets it run again.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.repositories.billing import ensure_user_billing


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


def _set_agent_enabled(client, auth_headers, ui_key: str, enabled: bool) -> None:
    """Pause/re-enable an agent through the REAL PATCH endpoint — the exact
    same write path the Agents-page per-agent toggle and "Stop All Agents"
    use, never a hand-rolled SQL upsert that could silently drift from it."""
    resp = client.put(
        f"/agents/config/{ui_key}", headers=auth_headers, json={"enabled": enabled}
    )
    assert resp.status_code == 200, resp.text


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


def _tailor_ok():
    return {"resume_id": "r1", "changes": [{"field": "summary"}], "rejected": []}


class TestDirectDispatchRefusal:
    """(a) RED CORE — the lowest-level entry point every other path shares."""

    def test_paused_agent_direct_dispatch_refused_with_honest_409(
        self, client, auth_headers, test_user_id, patch_agent_run,
    ):
        from app.agents.tailor_agent import TailoringAgent
        from app.routers.agents import _dispatch

        ensure_user_billing(test_user_id)
        calls = patch_agent_run(TailoringAgent, _tailor_ok)
        _set_agent_enabled(client, auth_headers, "resumeTailoring", False)

        with pytest.raises(HTTPException) as excinfo:
            _dispatch(test_user_id, "tailor", {"job_id": "job-1"})

        assert excinfo.value.status_code == 409
        detail = excinfo.value.detail
        assert isinstance(detail, dict), detail
        assert detail["code"] == "agent_paused"
        assert '"tailor"' in detail["message"]
        assert "paused" in detail["message"].lower()
        assert "you disabled it on the agents page" in detail["message"].lower()
        assert calls == [], (
            "TailoringAgent.run must NEVER be reached for a paused agent — "
            "the whole point of the fix is refusing BEFORE real work happens"
        )

    def test_paused_agent_refund_leaves_run_quota_untouched(
        self, client, auth_headers, test_user_id, patch_agent_run,
    ):
        """The atomic reserve-before-dispatch must be refunded on this honest
        refusal exactly like every other pre-existing refusal path — never a
        bill for a run that was never allowed to happen."""
        from app.agents.tailor_agent import TailoringAgent
        from app.repositories.billing import UsageQuotaRepository
        from app.routers.agents import _dispatch

        ensure_user_billing(test_user_id)
        patch_agent_run(TailoringAgent, _tailor_ok)
        _set_agent_enabled(client, auth_headers, "resumeTailoring", False)
        before = UsageQuotaRepository().get_by_user(test_user_id)

        with pytest.raises(HTTPException):
            _dispatch(test_user_id, "tailor", {"job_id": "job-1"})

        after = UsageQuotaRepository().get_by_user(test_user_id)
        assert int(after["runsUsed"]) == int(before["runsUsed"]), (
            "the reserved run must be refunded on a paused-agent refusal"
        )


class TestGenericRouteRefusal:
    """(b) the SAME chokepoint, reached through a real HTTP entry point."""

    def test_paused_agent_refused_through_generic_run_route(
        self, client, auth_headers, test_user_id, patch_agent_run,
    ):
        from app.agents.cover_letter_agent import CoverLetterAgent

        ensure_user_billing(test_user_id)
        calls = patch_agent_run(
            CoverLetterAgent,
            lambda: {"cover_letter_id": "cl1", "coverLetterUnavailable": False},
        )
        # coverLetter's backend name IS its UI key (same namespace) — a useful
        # contrast with tailor/resumeTailoring's differing-namespace mapping.
        _set_agent_enabled(client, auth_headers, "coverLetter", False)

        resp = client.post(
            "/agents/coverLetter/run", headers=auth_headers, json={"job_id": "job-1"}
        )

        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body["detail"]["code"] == "agent_paused"
        assert '"coverLetter"' in body["detail"]["message"]
        assert calls == [], "CoverLetterAgent.run must never be reached"


class TestAbsentConfigDefaultsEnabled:
    """(c) no regression: an agent with no AgentConfig row still runs."""

    def test_agent_with_no_persisted_config_row_still_runs(
        self, client, auth_headers, test_user_id, patch_agent_run,
    ):
        from app.agents.tailor_agent import TailoringAgent
        from app.routers.agents import _dispatch

        ensure_user_billing(test_user_id)
        calls = patch_agent_run(TailoringAgent, _tailor_ok)
        # Deliberately no PATCH /agents/config/resumeTailoring call at all —
        # this user has never touched the toggle for this agent.

        output = _dispatch(test_user_id, "tailor", {"job_id": "job-1"})

        assert output["changes"], "a run with no persisted config row must succeed"
        assert len(calls) == 1, "TailoringAgent.run must have been reached"


class TestBoardSweepHonestSkip:
    """(d) the board-sweep autopilot treats the refusal as a per-job SKIP."""

    def test_sweep_skips_paused_agent_job_honestly_and_completes(
        self, db_session, client, auth_headers, test_user_id, caplog,
    ):
        import logging
        import time

        from app.repositories.agent_run import AgentRunRepository
        from app.workers import board_sweep

        ensure_user_billing(test_user_id)
        job_id = _seed_job(db_session, test_user_id, status="screening", fit=80.0)
        _set_agent_enabled(client, auth_headers, "resumeTailoring", False)

        with caplog.at_level(logging.INFO, logger=board_sweep.logger.name):
            summary = board_sweep.sweep_user_stretch(
                test_user_id, deadline=time.monotonic() + 3600.0,
            )

        assert summary["skipped_paused"] == 1, summary
        assert summary["failures"] == 0, (
            "a paused-agent refusal is an honest skip, never a sweep failure: "
            f"{summary}"
        )
        assert summary["reason"] == "board-complete", summary
        assert any(
            "skipped" in r.getMessage() and "paused by user" in r.getMessage()
            for r in caplog.records
        ), "the sweep must log an honest per-job skip note (sweep-trail idiom)"

        runs = AgentRunRepository().list_recent(test_user_id, limit=10)
        tailor_runs = [r for r in runs if r["agentName"] == "tailor"]
        assert tailor_runs, "the refused attempt must still leave an honest audit row"
        assert tailor_runs[0]["status"] == "failed"
        assert "paused" in (tailor_runs[0]["error"] or "").lower()
        # The job itself was never actually processed.
        assert summary["processed"] == 0
        assert summary["tailored"] == 0
        assert summary["covers"] == 0
        del job_id  # seeded purely to give the sweep one eligible target


class TestStoryExtractorKeyMappingRoundTrip:
    """Cross-session anomaly report: a stale prod ``AgentConfig`` row keyed
    ``"storyExtraction"`` was found that "never matches the storyExtractor
    backend". Per the current catalog (``AGENT_CATALOG``), ``"storyExtraction"``
    IS in fact the live UI key for the ``storyExtractor`` backend — but the
    underlying principle the anomaly report is really asking to be pinned
    holds regardless: enforcement must resolve backend -> UI key through the
    SAME live ``_UI_KEY_FOR_BACKEND`` mapping every other lookup uses (never a
    second, hand-rolled mapping), so (a) pausing through the REAL current key
    actually blocks the backend, and (b) a row sitting under ANY OTHER,
    non-current key — an orphan from a past rename, a typo, a hand-edited row
    — is invisible to the query and stays honestly inert (default
    enabled=True), never silently blocking a run it was never meant to.
    """

    def test_pausing_via_the_real_catalog_key_blocks_storyextractor_dispatch(
        self, client, auth_headers, test_user_id, patch_agent_run,
    ):
        from app.agents.story_extractor import StoryExtractorAgent
        from app.routers.agents import _UI_KEY_FOR_BACKEND, _dispatch

        # Pin down the mapping this test relies on rather than assuming it.
        assert _UI_KEY_FOR_BACKEND["storyExtractor"] == "storyExtraction"

        ensure_user_billing(test_user_id)
        calls = patch_agent_run(StoryExtractorAgent, lambda: {"extracted": 3})
        _set_agent_enabled(client, auth_headers, "storyExtraction", False)

        with pytest.raises(HTTPException) as excinfo:
            _dispatch(test_user_id, "storyExtractor", {})

        assert excinfo.value.status_code == 409
        assert excinfo.value.detail["code"] == "agent_paused"
        assert calls == [], "StoryExtractorAgent.run must never be reached"

    def test_stale_row_under_a_wrong_key_never_blocks_dispatch(
        self, client, auth_headers, test_user_id, patch_agent_run, db_session,
    ):
        """An orphaned row under a key that is NOT the current live mapping
        (here: the literal backend name ``"storyExtractor"`` itself, which is
        NOT the catalog's UI key ``"storyExtraction"``) must be invisible to
        the enforcement query and never block a dispatch."""
        from app.agents.story_extractor import StoryExtractorAgent
        from app.routers.agents import _ensure_agent_config_schema, _dispatch

        ensure_user_billing(test_user_id)
        calls = patch_agent_run(StoryExtractorAgent, lambda: {"extracted": 5})
        _ensure_agent_config_schema()
        with db_session.cursor() as cur:
            cur.execute(
                'INSERT INTO "AgentConfig" ("userId", "agentKey", "enabled") '
                'VALUES (%s, %s, false)',
                (test_user_id, "storyExtractor"),  # the WRONG (backend) key
            )
        db_session.commit()

        output = _dispatch(test_user_id, "storyExtractor", {})

        assert output["extracted"] == 5
        assert len(calls) == 1, (
            "a row under a non-current, orphaned key must never block a "
            "dispatch through the real live key"
        )


class TestReEnableRunsAgain:
    """(e) re-enabling the agent lets it run again."""

    def test_reenabled_agent_dispatches_successfully(
        self, client, auth_headers, test_user_id, patch_agent_run,
    ):
        from app.agents.tailor_agent import TailoringAgent
        from app.routers.agents import _dispatch

        ensure_user_billing(test_user_id)
        calls = patch_agent_run(TailoringAgent, _tailor_ok)
        _set_agent_enabled(client, auth_headers, "resumeTailoring", False)
        with pytest.raises(HTTPException) as excinfo:
            _dispatch(test_user_id, "tailor", {"job_id": "job-1"})
        assert excinfo.value.status_code == 409

        _set_agent_enabled(client, auth_headers, "resumeTailoring", True)
        output = _dispatch(test_user_id, "tailor", {"job_id": "job-1"})

        assert output["changes"], "re-enabling must let the agent dispatch again"
        assert len(calls) == 1, "exactly the re-enabled attempt must have reached run()"
