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

(f)/(g) 2026-08-14 rebind (ML-STOPALL-002): ``_execute_reserved_run`` (the
async worker's direct entry point, bypassing ``_dispatch`` entirely) used
its OWN guard, ``_agent_enabled_for_dispatch``, which wrongly resolved a
backend to UI key through the single-key ``_UI_KEY_FOR_BACKEND`` mapping —
the same bug class the interim ``_dispatch`` pre-check (``_agent_paused_by_
user`` / ``_ALL_UI_KEYS_FOR_BACKEND``) was already written to avoid.
``fitScorer`` is dispatched by THREE UI cards (atsOptimization,
matchScoring, skillGap); (f) pins the discriminating case — disabling only
ONE of the three must never block a dispatch, and disabling all three must.
(g) pins the SAME rule at the async worker layer specifically: a pause that
lands AFTER a job is enqueued (but before the worker executes it) must still
be honoured, honestly, at execution time.
"""
from __future__ import annotations

import asyncio
import json
import types
import uuid

import pytest
from fastapi import HTTPException

from app.db import get_connection
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


#: Additive, test-schema-only ``BackgroundJob`` table (mirrors
#: test_mon020_async_scout.py / test_gap_p7_async_001.py's DDL verbatim) —
#: needed here only to drive the async worker path in
#: ``TestAsyncWorkerHonoursAllCardsRule`` below.
_BACKGROUND_JOB_DDL = (
    '''
    CREATE TABLE IF NOT EXISTS "BackgroundJob" (
        "id"              text PRIMARY KEY DEFAULT gen_random_uuid()::text,
        "userId"          text        NOT NULL,
        "agentKey"        text        NOT NULL,
        "runId"           text,
        "params"          jsonb,
        "status"          text        NOT NULL DEFAULT 'enqueued',
        "arqJobId"        text,
        "result"          jsonb,
        "error"           text,
        "attempts"        integer     NOT NULL DEFAULT 0,
        "quotaReserved"   boolean     NOT NULL DEFAULT false,
        "quotaReservedAt" timestamptz,
        "quotaRefundedAt" timestamptz,
        "startedAt"       timestamptz,
        "finishedAt"      timestamptz,
        "createdAt"       timestamptz NOT NULL DEFAULT now(),
        "updatedAt"       timestamptz NOT NULL DEFAULT now()
    )
    ''',
)


@pytest.fixture()
def bg_table(client):
    """Ensure the additive ``BackgroundJob`` table exists (test schema) and is
    empty for the test. Depends on ``client`` so the standard per-test
    TRUNCATE (which wipes ``User``) runs first."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            for stmt in _BACKGROUND_JOB_DDL:
                cur.execute(stmt)
            cur.execute('TRUNCATE TABLE "BackgroundJob"')
        conn.commit()
    return True


class FakeArqPool:
    """In-memory stand-in for the ARQ Redis pool (no broker touched)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def enqueue_job(self, function_name, *args, **kwargs):
        self.calls.append((function_name, *args))
        return types.SimpleNamespace(job_id="fake-arq-" + uuid.uuid4().hex[:10])


def _get_bg_job(job_id: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","userId","agentKey","runId","status","result","error" '
                'FROM "BackgroundJob" WHERE "id"=%s',
                (job_id,),
            )
            row = cur.fetchone()
            cols = [c.name for c in cur.description]
    if row is None:
        raise AssertionError(f"BackgroundJob {job_id} not found")
    rec = dict(zip(cols, row))
    if isinstance(rec.get("result"), str):
        rec["result"] = json.loads(rec["result"])
    return rec


class TestDirectDispatchRefusal:
    """(a) RED CORE — the lowest-level entry point every other path shares.

    2026-08-14 (main's interim Stop-All guard merge): ``_dispatch`` now has
    its OWN pre-side-effect refusal (``_agent_paused_by_user``, defense in
    depth — no ``AgentRun`` row, no quota reserve, nothing to refund), which
    fires BEFORE ``_execute_reserved_run`` is ever reached for a synchronous
    ``_dispatch`` call. Its detail shape is a plain string starting with
    ``"agent_paused"`` — a DELIBERATE, separately-pinned contract
    (``tests/test_stopall_interim_guard.py::TestDispatchRefusal``), distinct
    from ``_execute_reserved_run``'s coded dict shape. This test therefore
    now asserts the string shape, since a direct ``_dispatch`` call can no
    longer reach the dict-shaped refusal at all — that shape is only
    reachable through the async worker's direct ``_execute_reserved_run``
    entry point (bypassing ``_dispatch`` entirely), which is what
    ``TestAsyncWorkerHonoursAllCardsRule`` below exercises."""

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
        assert isinstance(detail, str), detail
        assert detail.startswith("agent_paused"), detail
        assert "tailor" in detail
        assert "stopped" in detail.lower()
        assert "re-enable the agent on the agents page" in detail.lower()
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
    """(b) the SAME chokepoint, reached through a real HTTP entry point.

    Shape note: see ``TestDirectDispatchRefusal`` above — this route is
    synchronous (``AETHER_ASYNC_GENERATION`` off by default in tests), so it
    goes through ``_dispatch``'s own plain-string refusal, not
    ``_execute_reserved_run``'s dict."""

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
        detail = resp.json()["detail"]
        assert isinstance(detail, str), detail
        assert detail.startswith("agent_paused"), detail
        assert "coverLetter" in detail
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
    """(d) the board-sweep autopilot treats the refusal as a per-job SKIP.

    Was pinned RED via ``@pytest.mark.xfail(strict=True)`` (2026-08-14):
    board_sweep.py:1033 classified a paused-agent refusal as an honest skip
    only when ``exc.detail`` was a DICT carrying ``code == "agent_paused"``.
    Since main's interim Stop-All guard merge, ``_dispatch``'s own
    pre-side-effect refusal (the one the board sweep actually hits — see
    ``tests/test_stopall_interim_guard.py::TestDispatchRefusal``) raises a
    PLAIN STRING starting with ``"agent_paused"`` instead, so the
    ``isinstance(exc.detail, dict)`` check was never true for this path and
    the skip silently fell through to ``summary["failures"] += 1`` with a
    WARNING log instead of ``skipped_paused`` + an INFO log. Fixed by having
    board_sweep.py also recognize the string shape; xfail marker removed now
    that the test is green again.
    """

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
        # Shape note: see TestDirectDispatchRefusal — a direct _dispatch call
        # hits _dispatch's own plain-string pre-check, not the dict-shaped
        # _execute_reserved_run refusal.
        detail = excinfo.value.detail
        assert isinstance(detail, str), detail
        assert detail.startswith("agent_paused"), detail
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


class TestFitScorerMultiCardRule:
    """(f) ML-STOPALL-002 discriminating case — a backend dispatched by
    SEVERAL UI cards (fitScorer: atsOptimization/matchScoring/skillGap) is
    paused only when EVERY one of its cards is disabled. Exercised through
    ``_dispatch`` end-to-end so BOTH enforcement layers are in the loop: the
    interim ``_dispatch`` pre-check (already correct, every-card) AND
    ``_execute_reserved_run``'s complete guard (the buggy single-key
    resolution this fix rebinds) — a bug in EITHER layer fails these tests.
    """

    def test_one_of_three_fitscorer_cards_disabled_still_dispatches(
        self, client, auth_headers, test_user_id, patch_agent_run,
    ):
        """THE discriminating case. ``_UI_KEY_FOR_BACKEND`` (the single-key
        map the pre-fix ``_execute_reserved_run`` guard used) resolves
        ``fitScorer`` to ``"skillGap"`` — the LAST catalog card, not the only
        one. Disabling just that one card, while atsOptimization/
        matchScoring stay enabled, must still let fitScorer dispatch: this
        is exactly the case a single-key resolution gets wrong (it sees only
        ``skillGap``'s row, finds it disabled, and wrongly refuses) while the
        every-card rule correctly proceeds (not ALL three are disabled)."""
        from app.agents.fit_scorer import FitScorerAgent, FitScoreResult
        from app.routers.agents import _UI_KEY_FOR_BACKEND, _dispatch

        # Pin the exact assumption this test discriminates on.
        assert _UI_KEY_FOR_BACKEND["fitScorer"] == "skillGap"

        ensure_user_billing(test_user_id)
        calls = patch_agent_run(FitScorerAgent, lambda: FitScoreResult(scored=3))
        _set_agent_enabled(client, auth_headers, "skillGap", False)
        # atsOptimization / matchScoring deliberately left enabled.

        output = _dispatch(test_user_id, "fitScorer", {"rescore": False})

        assert output["scored"] == 3, (
            "one disabled card out of three must never block fitScorer — the "
            "every-card rule only pauses when ALL of its cards are disabled"
        )
        assert len(calls) == 1, "FitScorerAgent.run must have been reached"

    def test_all_three_fitscorer_cards_disabled_refused(
        self, client, auth_headers, test_user_id, patch_agent_run,
    ):
        from app.agents.fit_scorer import FitScorerAgent, FitScoreResult
        from app.routers.agents import _dispatch

        ensure_user_billing(test_user_id)
        calls = patch_agent_run(FitScorerAgent, lambda: FitScoreResult(scored=3))
        for ui_key in ("atsOptimization", "matchScoring", "skillGap"):
            _set_agent_enabled(client, auth_headers, ui_key, False)

        with pytest.raises(HTTPException) as excinfo:
            _dispatch(test_user_id, "fitScorer", {"rescore": False})

        assert excinfo.value.status_code == 409
        detail = excinfo.value.detail
        message = detail.get("message") if isinstance(detail, dict) else detail
        assert "paused" in str(message).lower(), detail
        assert calls == [], "FitScorerAgent.run must never be reached when every card is off"


class TestAsyncWorkerHonoursAllCardsRule:
    """(g) The SAME every-card rule at the async worker's direct entry point
    (``_execute_reserved_run``, reached via ``_run_single_agent_body`` —
    bypassing ``_dispatch`` entirely). Pins the exact scenario
    ``_execute_reserved_run``'s own docstring names: an agent paused AFTER a
    background job was already enqueued is still honestly refused the
    instant it reaches execution — never a silent run, never a crash."""

    def test_async_worker_refuses_when_agent_paused_after_enqueue(
        self, client, auth_headers, test_user_id, patch_agent_run, bg_table,
        monkeypatch,
    ):
        from app.agents.tailor_agent import TailoringAgent
        from app.repositories.agent_run import AgentRunRepository
        from app.routers import agents as agents_mod

        ensure_user_billing(test_user_id)
        calls = patch_agent_run(TailoringAgent, _tailor_ok)
        fake_pool = FakeArqPool()
        monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: fake_pool, raising=True)
        monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")

        # Enqueue while the agent is ENABLED (default — no PATCH yet).
        resp = client.post(
            "/agents/tailor/run", headers=auth_headers, json={"job_id": "job-1"},
        )
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]

        # Pause it AFTER enqueue, before the worker ever runs it — tailor has
        # exactly one UI card (``resumeTailoring``), so disabling it disables
        # ALL of tailor's cards.
        _set_agent_enabled(client, auth_headers, "resumeTailoring", False)

        from app.workers.tasks import run_agent_job

        asyncio.run(run_agent_job({}, job_id))

        assert calls == [], (
            "TailoringAgent.run must never be reached once every one of its "
            "cards is disabled, even when the pause landed after enqueue"
        )
        job = _get_bg_job(job_id)
        assert job["status"] == "failed", job
        assert "paused" in (job["error"] or "").lower(), (
            "the recorded failure must honestly name the pause, not a generic "
            f"crash: {job}"
        )

        run = AgentRunRepository().get_by_id(job["runId"], test_user_id)
        assert run is not None
        assert run["status"] == "failed", run
        assert "paused" in (run["error"] or "").lower(), run
