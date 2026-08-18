"""GAP-P7-DISCOVERY-002 (R3) — the real periodic discovery cron.

Closes the R2 delta review's P0 Finding 1 (docs/delivery/evidence/
RUN-20260818T0223Z/FEAT-JOBBOARD/10-r2-delta-review.md): NOTHING automatically
searched any job board for any subscriber in production — the Abacus-era
``aether-discovery.timer`` systemd unit the R2 copy cited does not exist, and
none of the ARQ crons registered on the live worker
(``apps/api/app/workers/settings.py::_cron_jobs()``) ever dispatched scout or
fitScorer.

This file pins TWO things, following the exact pattern of
``test_rt_007_board_sweep.py``'s ``TestEligibilityAndCron`` (the sibling
autopilot's own registration + enable/disable + dedup tests):

1. Registration — the new cron is actually wired into
   ``app.workers.settings.WorkerSettings`` at the chosen cadence, and its
   per-user task is a registered worker function (so a mock/omission here
   could never again be the whole gap).
2. Behaviour — the cron enqueues exactly the ``_sweep_eligible_users``
   population (no new eligibility rule invented), respects the same
   agent-pause guard a manual dispatch would, and never double-enqueues a
   user swept moments earlier (dedup/overlap safety).

The end-to-end scout+fitScorer dispatch behaviour itself (real per-user
results, one failing user never aborting the rest) is already covered by
``test_sfix_a_discovery_scale.py::TestDiscoverySweep`` against
``POST /agents/discovery/sweep`` — unchanged by this fix, since
``_execute_discovery_for_user`` is the exact same code both callers share.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

import pytest


def _uid() -> str:
    return str(uuid.uuid4())


def _seed_user(
    db_session,
    email: str,
    *,
    target_role: str = "Delivery Lead",
    location: str = "Melbourne, AU",
    entitled: bool = True,
) -> str:
    """A user with (optionally) a real search target and an active paid plan
    — the exact two conditions ``_sweep_eligible_users`` requires."""
    from app.repositories.billing import _ensure_billing_tables

    _ensure_billing_tables()
    user_id = _uid()
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "User" ("id","email","name","passwordHash",'
            '"targetRole","location","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,now())',
            (user_id, email, "Sweep User", "x", target_role, location),
        )
        if entitled:
            cur.execute(
                'INSERT INTO "Subscription" ("id","userId","planId","status")'
                ' VALUES (%s,%s,%s,%s)',
                (_uid(), user_id, "pro", "active"),
            )
    db_session.commit()
    return user_id


class _RecordingRedis:
    """Fake ARQ redis pool: records every enqueue call, never actually queues."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    async def enqueue_job(self, fn, uid, _job_id=None):
        self.calls.append((fn, uid, _job_id))
        return object()


class _RefusingRedis:
    async def enqueue_job(self, *a, **k):  # pragma: no cover — must not run
        pytest.fail("a disabled/no-eligible-user cron tick must not enqueue")


class TestDiscoverySweepCronRegistration:
    def test_cron_is_registered_at_the_chosen_cadence(self):
        from app.workers.discovery_sweep import discovery_sweep_cron
        from app.workers.settings import WorkerSettings

        matches = [
            job
            for job in WorkerSettings.cron_jobs
            if getattr(job, "coroutine", None) is discovery_sweep_cron
        ]
        assert matches, "discovery_sweep_cron must be registered in WorkerSettings.cron_jobs"
        # Every 30 minutes at :03/:33 — offset from every sibling cron on this
        # worker (board-sweep :00/10/20/30/40/50, apply-sweep :07/22/37/52,
        # sales-agent :15/:45, stale-job watchdog :00/05/.../55).
        assert matches[0].minute == {3, 33}

    def test_discovery_sweep_user_is_a_registered_worker_function(self):
        from app.workers.discovery_sweep import discovery_sweep_user
        from app.workers.settings import WorkerSettings

        assert discovery_sweep_user in WorkerSettings.functions


class TestDiscoverySweepCronBehaviour:
    def test_cron_is_a_noop_when_disabled(self, monkeypatch):
        from app.workers import discovery_sweep

        monkeypatch.setenv("AETHER_DISCOVERY_CRON_ENABLED", "false")
        result = asyncio.run(discovery_sweep.discovery_sweep_cron({"redis": _RefusingRedis()}))
        assert result == 0

    def test_cron_defaults_enabled_when_the_env_var_is_absent(self, monkeypatch):
        """Owner directive: default-on, unlike the sibling autopilots."""
        from app.workers import discovery_sweep

        monkeypatch.delenv("AETHER_DISCOVERY_CRON_ENABLED", raising=False)
        assert discovery_sweep.discovery_cron_enabled() is True

    def test_cron_enqueues_the_eligible_user_with_a_dedup_job_id(
        self, client, db_session, monkeypatch
    ):
        # `client` forces table truncation (conftest's `_truncate_tables`) so
        # this test's eligible population is exactly what it seeds below —
        # `db_session` alone does not truncate (see conftest.py's note).
        from app.workers import discovery_sweep

        monkeypatch.setenv("AETHER_DISCOVERY_CRON_ENABLED", "true")
        user_id = _seed_user(db_session, f"disc-a-{uuid.uuid4().hex[:6]}@example.com")

        redis = _RecordingRedis()
        n = asyncio.run(discovery_sweep.discovery_sweep_cron({"redis": redis}))
        assert n >= 1
        assert ("discovery_sweep_user", user_id, f"discovery-sweep:{user_id}") in redis.calls

    def test_cron_skips_a_user_with_no_target_role(self, client, db_session, monkeypatch):
        """No new eligibility rule invented: mirrors _sweep_eligible_users
        (and the manual /agents/discovery/sweep endpoint) exactly — an empty
        targetRole means there is nothing to search for."""
        from app.workers import discovery_sweep

        monkeypatch.setenv("AETHER_DISCOVERY_CRON_ENABLED", "true")
        no_target = _seed_user(
            db_session, f"disc-b-{uuid.uuid4().hex[:6]}@example.com", target_role="",
        )
        redis = _RecordingRedis()
        asyncio.run(discovery_sweep.discovery_sweep_cron({"redis": redis}))
        assert no_target not in {uid for _, uid, _ in redis.calls}

    def test_cron_skips_a_non_entitled_user(self, client, db_session, monkeypatch):
        from app.workers import discovery_sweep

        monkeypatch.setenv("AETHER_DISCOVERY_CRON_ENABLED", "true")
        monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
        free_user = _seed_user(
            db_session, f"disc-c-{uuid.uuid4().hex[:6]}@example.com", entitled=False,
        )
        redis = _RecordingRedis()
        asyncio.run(discovery_sweep.discovery_sweep_cron({"redis": redis}))
        assert free_user not in {uid for _, uid, _ in redis.calls}

    def test_cron_skips_a_user_swept_moments_earlier_dedup_overlap_safety(
        self, client, db_session, monkeypatch
    ):
        """A user manually Synced (or was already swept this tick period)
        moments before the cron fires must not get a duplicate storm."""
        from app.repositories.agent_run import AgentRunRepository
        from app.workers import discovery_sweep

        monkeypatch.setenv("AETHER_DISCOVERY_CRON_ENABLED", "true")
        recently_swept = _seed_user(db_session, f"disc-d-{uuid.uuid4().hex[:6]}@example.com")
        also_eligible = _seed_user(db_session, f"disc-e-{uuid.uuid4().hex[:6]}@example.com")

        runs = AgentRunRepository()
        run = runs.start(recently_swept, "scout", {"query": "x", "location": "y"})
        runs.finish(run["id"], "completed", output={"persisted": 0}, cost_usd=0.0)

        redis = _RecordingRedis()
        n = asyncio.run(discovery_sweep.discovery_sweep_cron({"redis": redis}))
        enqueued_ids = {uid for _, uid, _ in redis.calls}
        assert recently_swept not in enqueued_ids, (
            "a user with a scout AgentRun inside the recency window must be skipped"
        )
        assert also_eligible in enqueued_ids
        assert n == 1

    def test_recency_guard_env_tunable_floors_at_60_seconds(self, monkeypatch):
        from app.workers import discovery_sweep

        monkeypatch.setenv("AETHER_DISCOVERY_SWEEP_MIN_INTERVAL_SECONDS", "1")
        assert discovery_sweep.discovery_sweep_min_interval_seconds() == 60.0
        monkeypatch.setenv("AETHER_DISCOVERY_SWEEP_MIN_INTERVAL_SECONDS", "not-a-number")
        assert discovery_sweep.discovery_sweep_min_interval_seconds() == 1500.0

    def test_recency_check_fault_does_not_abort_the_tick_for_later_users(
        self, client, db_session, monkeypatch, caplog
    ):
        """R3 delta review P1 Finding 2 — a transient DB fault on ONE user's
        recency check must never silently abort enqueueing for every
        later-ordered eligible user in the same tick, and the module's own
        advertised summary log line must still fire."""
        from app.workers import discovery_sweep

        monkeypatch.setenv("AETHER_DISCOVERY_CRON_ENABLED", "true")
        user_a = _seed_user(db_session, f"disc-fault-a-{uuid.uuid4().hex[:6]}@example.com")
        user_b = _seed_user(db_session, f"disc-fault-b-{uuid.uuid4().hex[:6]}@example.com")
        user_c = _seed_user(db_session, f"disc-fault-c-{uuid.uuid4().hex[:6]}@example.com")

        real_recently_swept = discovery_sweep._recently_swept

        def _faulting_recently_swept(user_id):
            if user_id == user_b:
                raise RuntimeError("simulated transient DB fault")
            return real_recently_swept(user_id)

        monkeypatch.setattr(discovery_sweep, "_recently_swept", _faulting_recently_swept)

        redis = _RecordingRedis()
        with caplog.at_level(logging.INFO, logger="app.workers.discovery_sweep"):
            n = asyncio.run(discovery_sweep.discovery_sweep_cron({"redis": redis}))

        enqueued_ids = {uid for _, uid, _ in redis.calls}
        assert user_a in enqueued_ids, "user A (before the fault) must still be enqueued"
        assert user_c in enqueued_ids, (
            "user C (ordered after the faulting user B) must still be "
            "enqueued — one user's read fault must not abort the rest of "
            "the tick"
        )
        assert user_b in enqueued_ids, (
            "the faulting user's OWN check must fail toward NOT skipping, "
            "per this module's documented discipline"
        )
        assert n == 3

        # The module's own advertised summary log line must fire on this
        # path too — previously it never executed once the unhandled
        # exception propagated out of the loop.
        assert "eligible (pool)" in caplog.text
        assert "1 recency-check fault(s)" in caplog.text
        assert f"recency check failed for user {user_b}" in caplog.text


class TestDiscoverySweepRotationFairness:
    def test_rotation_prioritises_least_recently_swept_over_account_age(
        self, client, db_session, monkeypatch
    ):
        """R3 delta review P2 Finding 3 — once eligible population exceeds
        the per-tick enqueue cap, the OLDEST account must not always win
        every tick forever; the LEAST recently (or never) swept user must be
        prioritised so every eligible subscriber eventually rotates in."""
        from app.repositories.agent_run import AgentRunRepository
        from app.workers import discovery_sweep

        monkeypatch.setenv("AETHER_DISCOVERY_CRON_ENABLED", "true")
        monkeypatch.setenv("AETHER_DISCOVERY_SWEEP_USER_CAP", "1")

        older_but_recently_swept = _seed_user(
            db_session, f"disc-rot-old-{uuid.uuid4().hex[:6]}@example.com",
        )
        newer_but_never_swept = _seed_user(
            db_session, f"disc-rot-new-{uuid.uuid4().hex[:6]}@example.com",
        )

        runs = AgentRunRepository()
        run = runs.start(older_but_recently_swept, "scout", {"query": "x", "location": "y"})
        runs.finish(run["id"], "completed", output={"persisted": 0}, cost_usd=0.0)
        # Backdate the run OUTSIDE the recency-guard window, so
        # `_recently_swept` alone would NOT exclude this user — isolating
        # the assertion to rotation ORDER, not the unrelated recency skip
        # (Finding 2's mechanism, already covered above).
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "AgentRun" SET "createdAt" = NOW() - INTERVAL \'2 hours\' '
                'WHERE "id" = %s',
                (run["id"],),
            )
        db_session.commit()

        redis = _RecordingRedis()
        n = asyncio.run(discovery_sweep.discovery_sweep_cron({"redis": redis}))
        enqueued_ids = {uid for _, uid, _ in redis.calls}

        assert newer_but_never_swept in enqueued_ids, (
            "the never-swept user must win the single enqueue slot over an "
            "OLDER account that was already (if less recently) swept — the "
            "pre-fix ORDER BY createdAt behaviour would have picked the "
            "older account every time"
        )
        assert older_but_recently_swept not in enqueued_ids
        assert n == 1

    def test_rotation_is_a_noop_when_the_pool_already_fits_inside_the_cap(self):
        from app.workers import discovery_sweep

        users = [{"id": "u1"}, {"id": "u2"}]
        result = discovery_sweep._rotate_least_recently_swept(users, cap=5)
        assert result == users

    def test_rotation_falls_back_to_natural_pool_order_when_the_ordering_read_fails(
        self, monkeypatch
    ):
        """A fault in the rotation-ordering read degrades honestly to the
        pool's own natural order truncated at cap — never crashes the tick."""
        from app.workers import discovery_sweep

        def _faulting_last_scout_run_at(user_ids):
            raise RuntimeError("simulated transient DB fault")

        monkeypatch.setattr(discovery_sweep, "_last_scout_run_at", _faulting_last_scout_run_at)
        users = [{"id": f"u{i}"} for i in range(5)]
        result = discovery_sweep._rotate_least_recently_swept(users, cap=2)
        assert result == users[:2]


class TestDiscoverySweepUserTask:
    def test_task_dispatches_scout_then_fitscorer_via_the_shared_executor(
        self, client, db_session, monkeypatch
    ):
        """discovery_sweep_user must delegate to the SAME
        _execute_discovery_for_user the HTTP sweep endpoint uses — proven here
        by observing the real module-level _dispatch calls it makes."""
        from app.routers import agents as agents_router
        from app.workers.discovery_sweep import discovery_sweep_user

        user_id = _seed_user(db_session, f"disc-f-{uuid.uuid4().hex[:6]}@example.com")
        calls: list[tuple[str, str]] = []

        def _fake_dispatch(uid, agent_name, params, **kwargs):
            calls.append((uid, agent_name))
            assert kwargs.get("system_run") is True
            if agent_name == "scout":
                return {"persisted": 3, "updated": 1, "per_source": []}
            return {"scored": 2}

        monkeypatch.setattr(agents_router, "_dispatch", _fake_dispatch)
        result = asyncio.run(discovery_sweep_user({}, user_id))

        assert result["status"] == "ok"
        assert result["persisted"] == 3
        assert result["scored"] == 2
        assert calls == [(user_id, "scout"), (user_id, "fitScorer")]

    def test_task_honours_the_users_own_agent_pause_without_raising(
        self, client, db_session, monkeypatch
    ):
        """A user who stopped Job Discovery via Agent Controls must be
        skipped exactly as honestly as a manual dispatch would refuse them —
        never bypassed, never a crashed ARQ job."""
        from app.repositories.billing import _ensure_billing_tables
        from app.routers.agents import _ensure_agent_config_schema
        from app.workers.discovery_sweep import discovery_sweep_user

        user_id = _seed_user(db_session, f"disc-g-{uuid.uuid4().hex[:6]}@example.com")
        _ensure_billing_tables()
        _ensure_agent_config_schema()
        with db_session.cursor() as cur:
            cur.execute(
                'INSERT INTO "AgentConfig" ("userId", "agentKey", "enabled") '
                'VALUES (%s, %s, false)',
                (user_id, "jobDiscovery"),  # the UI key that maps to backend "scout"
            )
        db_session.commit()

        # No monkeypatch of _dispatch here: the REAL _agent_paused_by_user
        # pre-check inside _dispatch must be what refuses this run.
        result = asyncio.run(discovery_sweep_user({}, user_id))

        assert result["status"] == "error"
        assert "agent_paused" in (result["error"] or "")

    def test_task_reports_a_missing_search_target_honestly_never_raises(
        self, client, db_session
    ):
        """_sweep_eligible_users only requires targetRole non-empty (S-FIX-A);
        a user with no location is still selected by the cron, and the
        per-user task must degrade to an honest error row, matching the
        manual endpoint's own documented behaviour — never a crashed job."""
        from app.workers.discovery_sweep import discovery_sweep_user

        user_id = _seed_user(
            db_session, f"disc-h-{uuid.uuid4().hex[:6]}@example.com", location="",
        )
        result = asyncio.run(discovery_sweep_user({}, user_id))
        assert result["status"] == "error"
        assert result["error"]
