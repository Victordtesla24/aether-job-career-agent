"""CRITICAL-1 — abandoned ``AgentRun`` reconciliation + worker heartbeat.

THE DEFECT (measured in production 2026-08-03): one ``tailor`` AgentRun has
been ``status='running'`` since 2026-07-26 03:41:20 UTC — 192.6 hours (8 days).
No process is attached to it; ``aether-worker`` was restarted 2026-08-03 00:17,
which would have killed any real job. Nothing in the codebase ever reconciles a
``running`` AgentRun row, so it survives every restart forever and the UI keeps
presenting it as an ACTIVE run. The product therefore concealed a week of total
inactivity instead of surfacing it.

THE CONTRACT these tests pin:

1. A ``running`` run with no live worker behind it is FAILED with an HONEST
   error naming the real cause (abandoned / no heartbeat). Never deleted, never
   fabricated as ``completed``.
2. Reconciliation is automatic — API startup, worker startup, and a periodic
   cron — never a script somebody has to remember to run.
3. The wall-clock ceiling is env-configurable with a default derived from real
   observed durations (see ``agent_run_watchdog`` module docstring for the
   production query and its numbers).
4. A genuinely live run is NEVER murdered: the worker stamps ``heartbeatAt``
   while it executes, and a run whose heartbeat is fresh is untouchable no
   matter how old it is. Age alone only reconciles runs that never produced a
   single heartbeat (they predate this fix, or their process died before it
   ever reached execution) and have blown past the ceiling.
"""
from __future__ import annotations

import asyncio
import json
import os
import time


def _insert_run(
    conn,
    user_id: str,
    *,
    agent_name: str = "tailor",
    status: str = "running",
    age_seconds: float = 0.0,
    heartbeat_age_seconds: float | None = None,
) -> str:
    """Insert an AgentRun whose startedAt/createdAt are ``age_seconds`` old.

    ``heartbeat_age_seconds`` None leaves ``heartbeatAt`` NULL (the state of
    every row written before this fix shipped).
    """
    from app.db import new_id
    from app.repositories.agent_run import ensure_heartbeat_column

    ensure_heartbeat_column()
    run_id = new_id()
    with conn.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO "AgentRun"
                ("id", "userId", "agentName", "status", "input",
                 "startedAt", "createdAt", "heartbeatAt")
            VALUES (%s, %s, %s, %s::"AgentRunStatus", %s::jsonb,
                    NOW() - make_interval(secs => %s),
                    NOW() - make_interval(secs => %s),
                    CASE WHEN %s::float8 IS NULL THEN NULL
                         ELSE NOW() - make_interval(secs => %s::float8) END)
            ''',
            (
                run_id,
                user_id,
                agent_name,
                status,
                json.dumps({"job_id": "test"}),
                age_seconds,
                age_seconds,
                heartbeat_age_seconds,
                heartbeat_age_seconds,
            ),
        )
    conn.commit()
    return run_id


def _row(conn, run_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "status"::text, "error", "completedAt", "heartbeatAt" '
            'FROM "AgentRun" WHERE "id" = %s',
            (run_id,),
        )
        row = cur.fetchone()
    conn.commit()
    assert row is not None, "the run row must never be deleted"
    return {
        "status": row[0],
        "error": row[1],
        "completedAt": row[2],
        "heartbeatAt": row[3],
    }


# ---------------------------------------------------------------------------
# 1. The 8-day zombie: reconciled, honestly, never deleted, never "completed".
# ---------------------------------------------------------------------------


def test_eight_day_zombie_run_is_failed_with_an_honest_error(
    client, auth_headers, test_user_id, db_session
):
    from app.services.agent_run_watchdog import reconcile_abandoned_agent_runs

    run_id = _insert_run(db_session, test_user_id, age_seconds=192.6 * 3600)

    outcome = reconcile_abandoned_agent_runs(reason="test")

    assert outcome.before >= 1
    assert outcome.reconciled >= 1
    assert outcome.after == 0, "no abandoned run may survive reconciliation"

    row = _row(db_session, run_id)
    assert row["status"] == "failed", "must never be silently deleted or completed"
    assert row["completedAt"] is not None
    error = (row["error"] or "").lower()
    assert "abandoned" in error
    assert "heartbeat" in error


def test_reconciliation_never_fabricates_a_completed_run(
    client, auth_headers, test_user_id, db_session
):
    from app.services.agent_run_watchdog import reconcile_abandoned_agent_runs

    run_id = _insert_run(db_session, test_user_id, age_seconds=200 * 3600)
    reconcile_abandoned_agent_runs(reason="test")
    assert _row(db_session, run_id)["status"] != "completed"


# ---------------------------------------------------------------------------
# 2. A genuinely live run is never murdered.
# ---------------------------------------------------------------------------


def test_a_long_run_with_a_fresh_heartbeat_is_never_reconciled(
    client, auth_headers, test_user_id, db_session
):
    """Three days old but heartbeating: a live worker owns it. Hands off."""
    from app.services.agent_run_watchdog import reconcile_abandoned_agent_runs

    run_id = _insert_run(
        db_session,
        test_user_id,
        age_seconds=3 * 24 * 3600,
        heartbeat_age_seconds=1.0,
    )
    reconcile_abandoned_agent_runs(reason="test")
    assert _row(db_session, run_id)["status"] == "running"


def test_a_young_run_without_a_heartbeat_is_below_the_ceiling(
    client, auth_headers, test_user_id, db_session
):
    """A run that has only just started has not blown any ceiling yet."""
    from app.services.agent_run_watchdog import reconcile_abandoned_agent_runs

    run_id = _insert_run(db_session, test_user_id, age_seconds=45.0)
    reconcile_abandoned_agent_runs(reason="test")
    assert _row(db_session, run_id)["status"] == "running"


def test_a_stale_heartbeat_means_the_process_died(
    client, auth_headers, test_user_id, db_session
):
    """Heartbeats stopped long ago -> the owning process is gone."""
    from app.services.agent_run_watchdog import (
        get_heartbeat_stale_seconds,
        reconcile_abandoned_agent_runs,
    )

    stale = get_heartbeat_stale_seconds()
    run_id = _insert_run(
        db_session,
        test_user_id,
        age_seconds=stale * 2 + 60,
        heartbeat_age_seconds=stale + 60,
    )
    reconcile_abandoned_agent_runs(reason="test")
    row = _row(db_session, run_id)
    assert row["status"] == "failed"
    assert "heartbeat" in (row["error"] or "").lower()


def test_a_completed_run_is_never_touched(
    client, auth_headers, test_user_id, db_session
):
    from app.services.agent_run_watchdog import reconcile_abandoned_agent_runs

    run_id = _insert_run(
        db_session, test_user_id, status="completed", age_seconds=500 * 3600
    )
    reconcile_abandoned_agent_runs(reason="test")
    assert _row(db_session, run_id)["status"] == "completed"


# ---------------------------------------------------------------------------
# 3. Configurable ceiling with a documented, evidence-derived default.
# ---------------------------------------------------------------------------


def test_ceiling_default_and_env_override():
    from app.services import agent_run_watchdog as wd

    os.environ.pop("AETHER_AGENT_RUN_MAX_SECONDS", None)
    # Default derived from production: the longest COMPLETED run ever observed
    # is 403.4 s (fitScorer) and ARQ's own hard job ceiling is 900 s.
    assert wd.get_max_run_seconds() == 1800.0
    assert wd.get_max_run_seconds() > 900.0

    os.environ["AETHER_AGENT_RUN_MAX_SECONDS"] = "3600"
    try:
        assert wd.get_max_run_seconds() == 3600.0
    finally:
        os.environ.pop("AETHER_AGENT_RUN_MAX_SECONDS", None)


def test_ceiling_cannot_be_configured_below_the_observed_maximum():
    """A too-small ceiling would murder legitimately long runs — clamp it."""
    from app.services import agent_run_watchdog as wd

    os.environ["AETHER_AGENT_RUN_MAX_SECONDS"] = "5"
    try:
        assert wd.get_max_run_seconds() >= 900.0
    finally:
        os.environ.pop("AETHER_AGENT_RUN_MAX_SECONDS", None)


def test_env_override_is_honoured_end_to_end(
    client, auth_headers, test_user_id, db_session
):
    from app.services.agent_run_watchdog import reconcile_abandoned_agent_runs

    run_id = _insert_run(db_session, test_user_id, age_seconds=1000.0)
    reconcile_abandoned_agent_runs(reason="test")
    assert _row(db_session, run_id)["status"] == "running", "below the 1800s default"

    os.environ["AETHER_AGENT_RUN_MAX_SECONDS"] = "900"
    try:
        reconcile_abandoned_agent_runs(reason="test")
    finally:
        os.environ.pop("AETHER_AGENT_RUN_MAX_SECONDS", None)
    assert _row(db_session, run_id)["status"] == "failed"


# ---------------------------------------------------------------------------
# 4. The heartbeat itself.
# ---------------------------------------------------------------------------


def test_heartbeat_context_manager_stamps_a_running_run(
    client, auth_headers, test_user_id, db_session
):
    from app.services.agent_run_watchdog import agent_run_heartbeat

    run_id = _insert_run(db_session, test_user_id, age_seconds=10.0)
    assert _row(db_session, run_id)["heartbeatAt"] is None

    with agent_run_heartbeat(run_id, interval_seconds=0.05):
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if _row(db_session, run_id)["heartbeatAt"] is not None:
                break
            time.sleep(0.05)
    assert _row(db_session, run_id)["heartbeatAt"] is not None


def test_heartbeat_stops_when_the_run_leaves_running(
    client, auth_headers, test_user_id, db_session
):
    from app.repositories.agent_run import AgentRunRepository

    repo = AgentRunRepository()
    run_id = _insert_run(db_session, test_user_id, age_seconds=10.0)
    assert repo.heartbeat(run_id) is True
    repo.finish(run_id, "completed", output={"ok": True})
    assert repo.heartbeat(run_id) is False, "a finished run must not be stamped"


def test_executing_a_reserved_run_stamps_a_heartbeat(
    client, auth_headers, test_user_id, db_session
):
    """The real execution seam both the sync API and the ARQ worker share."""
    from app.routers.agents import _execute_reserved_run

    run_id = _insert_run(db_session, test_user_id, agent_name="supervisor")
    seen: dict[str, object] = {}

    def _fn():
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            hb = _row(db_session, run_id)["heartbeatAt"]
            if hb is not None:
                seen["heartbeatAt"] = hb
                break
            time.sleep(0.05)
        return {"plan": []}

    _execute_reserved_run(
        run_id, test_user_id, "supervisor", {}, _fn, None, {}
    )
    assert seen.get("heartbeatAt") is not None, (
        "a run must heartbeat WHILE it executes — otherwise the watchdog "
        "cannot tell a live run from a dead one"
    )


# ---------------------------------------------------------------------------
# 5. The reconciled run must SURFACE, not be re-hidden by transient tolerance.
# ---------------------------------------------------------------------------


def test_abandonment_is_never_classified_as_a_transient_blip():
    """``/agents/catalog`` paints a card "active" when the last run's error
    reads like an upstream blip (ML-agents-err-001). An abandoned run is the
    opposite of a blip — it is the process dying — and re-hiding it behind an
    "active" card would restore exactly the concealment this fix removes."""
    from app.routers.agents import _is_transient_failure
    from app.services.agent_run_watchdog import _honest_error

    never_stamped = _honest_error(
        {"agentName": "tailor", "ageSeconds": 192.6 * 3600, "heartbeatAgeSeconds": None}
    )
    stale_stamp = _honest_error(
        {
            "agentName": "tailor",
            "ageSeconds": 40000.0,
            "heartbeatAgeSeconds": 30180.0,  # 503.0 minutes -> a bare "503" token
        }
    )
    for message in (never_stamped, stale_stamp):
        assert _is_transient_failure({"error": message}) is False, message


def test_reconciled_row_from_the_database_is_not_transient(
    client, auth_headers, test_user_id, db_session
):
    from app.routers.agents import _is_transient_failure
    from app.services.agent_run_watchdog import reconcile_abandoned_agent_runs

    run_id = _insert_run(db_session, test_user_id, age_seconds=192.6 * 3600)
    reconcile_abandoned_agent_runs(reason="test")
    row = _row(db_session, run_id)
    assert _is_transient_failure({"error": row["error"]}) is False


# ---------------------------------------------------------------------------
# 6. Automatic wiring: API startup, worker startup, periodic cron.
# ---------------------------------------------------------------------------


def test_api_startup_reconciles_abandoned_runs(
    client, auth_headers, test_user_id, db_session
):
    from fastapi.testclient import TestClient

    from app.main import create_app

    run_id = _insert_run(db_session, test_user_id, age_seconds=192.6 * 3600)
    with TestClient(create_app()):
        pass
    assert _row(db_session, run_id)["status"] == "failed"


def test_worker_startup_reconciles_orphaned_runs(
    client, auth_headers, test_user_id, db_session
):
    from app.workers.settings import WorkerSettings

    on_startup = getattr(WorkerSettings, "on_startup", None)
    assert on_startup is not None, "the worker must reconcile what it orphaned"

    run_id = _insert_run(db_session, test_user_id, age_seconds=192.6 * 3600)
    asyncio.run(on_startup({}))
    assert _row(db_session, run_id)["status"] == "failed"


def test_a_periodic_cron_is_registered():
    from app.workers.settings import WorkerSettings

    names = {getattr(job, "name", "") or "" for job in WorkerSettings.cron_jobs}
    assert any("reconcile_abandoned_agent_runs" in n for n in names), names


def test_cron_body_reconciles(
    client, auth_headers, test_user_id, db_session
):
    from app.workers.tasks import reconcile_abandoned_agent_runs_cron

    run_id = _insert_run(db_session, test_user_id, age_seconds=192.6 * 3600)
    reconciled = asyncio.run(reconcile_abandoned_agent_runs_cron({}))
    assert reconciled >= 1
    assert _row(db_session, run_id)["status"] == "failed"
