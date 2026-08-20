"""EMAIL-CENTER -> JOBS automation (RUN-20260818T0223Z, Owner directive).

GAP CLOSED: inbox job-ad emails (Seek/LinkedIn/etc.) must automatically become
Job cards. The parse pipeline was already fully wired end to end
(``EmailAgent._job_alerts`` -> ``app.services.job_alert_parser`` ->
``JobRepository.create`` -> ``routers/jobs.py`` -> web cards) — see
``test_job_alert_intake.py`` for that path's own coverage, unchanged here.
BUT ``apps/api/app/workers/settings.py::_cron_jobs()`` never registered a
cron for it: the ONLY trigger was the manual "Scan Job Alerts" button
(``apps/web/src/app/dashboard/email/page.tsx``, ``mode: "job_alerts"``).
This file pins the missing trigger, following the exact pattern of
``test_gap_p7_discovery_002_cron.py`` (registration + cadence + kill-switch +
eligibility + recency-skip + fault-isolation) crossed with
``test_feat_email_brand_digest_cron.py`` (Gmail-connected eligibility via
``GmailAccountRepository.list_connected_user_ids``, which already excludes
suspended/soft-deleted users).

Fail-before: ``app.workers.email_alerts_sweep`` does not exist, and
``WorkerSettings.cron_jobs`` carries no job whose coroutine is
``email_alerts_cron``.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

import pytest


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


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


@pytest.fixture()
def billing_seeded(user_id):
    from app.repositories.billing import ensure_user_billing

    ensure_user_billing(user_id)
    return user_id


@pytest.fixture()
def gmail_connected(user_id):
    """Connect a Gmail account for the run's duration, then disconnect."""
    from app.repositories.gmail_account import GmailAccountRepository

    repo = GmailAccountRepository()
    account = repo.upsert_account(
        user_id,
        account_email="jordan.rivera@gmail.com",
        refresh_token="refresh-xyz",
        scopes="gmail.readonly",
    )
    yield account
    repo.disconnect(user_id)


# ===========================================================================
# Registration + cadence + kill-switch
# ===========================================================================


class TestEmailAlertsCronRegistration:
    def test_cron_is_registered_at_the_chosen_cadence(self):
        from app.workers.email_alerts_sweep import email_alerts_cron
        from app.workers.settings import WorkerSettings

        matches = [
            job
            for job in WorkerSettings.cron_jobs
            if getattr(job, "coroutine", None) is email_alerts_cron
        ]
        assert matches, "email_alerts_cron must be registered in WorkerSettings.cron_jobs"
        # Every 30 minutes at :18/:48 — the cadence recorded for this unit in
        # docs/delivery/evidence/RUN-20260818T0223Z/INTERDEP/
        # 01-remediation-plan.md, clear of every other cron on this worker
        # (board :00/10/20/30/40/50, apply :07/22/37/52, sales :15/:45,
        # discovery :03/:33, and the every-5-minute watchdogs).
        assert matches[0].minute == {18, 48}

    def test_email_alerts_user_is_a_registered_worker_function(self):
        from app.workers.email_alerts_sweep import email_alerts_user
        from app.workers.settings import WorkerSettings

        assert email_alerts_user in WorkerSettings.functions


class TestEmailAlertsCronKillSwitch:
    def test_cron_is_a_noop_when_disabled(self, monkeypatch):
        from app.workers import email_alerts_sweep

        monkeypatch.setenv("AETHER_EMAIL_ALERTS_CRON_ENABLED", "false")
        result = asyncio.run(
            email_alerts_sweep.email_alerts_cron({"redis": _RefusingRedis()})
        )
        assert result == 0

    def test_cron_defaults_enabled_when_the_env_var_is_absent(self, monkeypatch):
        """Owner directive: default-on, same posture as discovery_sweep_cron."""
        from app.workers import email_alerts_sweep

        monkeypatch.delenv("AETHER_EMAIL_ALERTS_CRON_ENABLED", raising=False)
        assert email_alerts_sweep.email_alerts_cron_enabled() is True


# ===========================================================================
# Eligibility — GmailAccountRepository.list_connected_user_ids
# ===========================================================================


class TestEmailAlertsCronEligibility:
    def test_cron_enqueues_the_connected_user_with_a_dedup_job_id(
        self, client, user_id, gmail_connected, monkeypatch
    ):
        from app.workers import email_alerts_sweep

        monkeypatch.setenv("AETHER_EMAIL_ALERTS_CRON_ENABLED", "true")
        redis = _RecordingRedis()
        n = asyncio.run(email_alerts_sweep.email_alerts_cron({"redis": redis}))
        assert n >= 1
        assert (
            ("email_alerts_user", user_id, f"email-alerts:{user_id}") in redis.calls
        )

    def test_cron_never_attempts_a_user_with_no_gmail_connected(
        self, client, user_id, monkeypatch
    ):
        """No fixture connects Gmail here — the user must never be enqueued."""
        from app.workers import email_alerts_sweep

        monkeypatch.setenv("AETHER_EMAIL_ALERTS_CRON_ENABLED", "true")
        redis = _RecordingRedis()
        asyncio.run(email_alerts_sweep.email_alerts_cron({"redis": redis}))
        assert user_id not in {uid for _, uid, _ in redis.calls}

    def test_cron_excludes_a_suspended_user(
        self, client, user_id, gmail_connected, monkeypatch
    ):
        """Account suspension is enforced only at the HTTP auth-dependency
        layer; this cron calls ``_dispatch`` directly, in-process, bypassing
        it entirely, so eligibility must exclude a suspended user itself —
        the SAME ``GmailAccountRepository.list_connected_user_ids`` guarantee
        ``digest_cron`` already relies on."""
        from app.repositories.admin import set_suspended
        from app.workers import email_alerts_sweep

        monkeypatch.setenv("AETHER_EMAIL_ALERTS_CRON_ENABLED", "true")
        set_suspended(user_id, True)

        redis = _RecordingRedis()
        n_before = len(redis.calls)
        asyncio.run(email_alerts_sweep.email_alerts_cron({"redis": redis}))
        assert user_id not in {uid for _, uid, _ in redis.calls[n_before:]}

    def test_cron_excludes_a_soft_deleted_user(
        self, client, user_id, gmail_connected, monkeypatch
    ):
        from app.db import ensure_user_lifecycle_columns, get_connection
        from app.workers import email_alerts_sweep

        monkeypatch.setenv("AETHER_EMAIL_ALERTS_CRON_ENABLED", "true")
        ensure_user_lifecycle_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "User" SET "deletedAt" = now() WHERE "id" = %s',
                    (user_id,),
                )
            conn.commit()

        redis = _RecordingRedis()
        asyncio.run(email_alerts_sweep.email_alerts_cron({"redis": redis}))
        assert user_id not in {uid for _, uid, _ in redis.calls}


# ===========================================================================
# Recency guard
# ===========================================================================


class TestEmailAlertsCronRecencyGuard:
    def test_recency_guard_env_tunable_floors_at_60_seconds(self, monkeypatch):
        from app.workers import email_alerts_sweep

        monkeypatch.setenv("AETHER_EMAIL_ALERTS_MIN_INTERVAL_SECONDS", "1")
        assert email_alerts_sweep.email_alerts_min_interval_seconds() == 60.0
        monkeypatch.setenv("AETHER_EMAIL_ALERTS_MIN_INTERVAL_SECONDS", "not-a-number")
        assert email_alerts_sweep.email_alerts_min_interval_seconds() == 1500.0

    def test_cron_skips_a_user_who_ran_job_alerts_moments_earlier(
        self, client, user_id, gmail_connected, monkeypatch
    ):
        """A user who just clicked "Scan Job Alerts" (or was already swept
        this tick period) moments before the cron fires must not get a
        duplicate mailbox re-scan."""
        from app.repositories.agent_run import AgentRunRepository
        from app.workers import email_alerts_sweep

        monkeypatch.setenv("AETHER_EMAIL_ALERTS_CRON_ENABLED", "true")
        runs = AgentRunRepository()
        run = runs.start(user_id, "emailAgent", {"mode": "job_alerts"})
        runs.finish(run["id"], "completed", output={"jobs_created": 0})

        redis = _RecordingRedis()
        n = asyncio.run(email_alerts_sweep.email_alerts_cron({"redis": redis}))
        assert user_id not in {uid for _, uid, _ in redis.calls}
        assert n == 0

    def test_cron_ignores_a_run_of_a_different_email_agent_mode(
        self, client, user_id, gmail_connected, monkeypatch
    ):
        """A recent ``triage`` (or any non-job_alerts) emailAgent run must
        NOT suppress the job-alerts enqueue — the recency guard is scoped to
        the job_alerts mode specifically."""
        from app.repositories.agent_run import AgentRunRepository
        from app.workers import email_alerts_sweep

        monkeypatch.setenv("AETHER_EMAIL_ALERTS_CRON_ENABLED", "true")
        runs = AgentRunRepository()
        run = runs.start(user_id, "emailAgent", {"mode": "triage"})
        runs.finish(run["id"], "completed", output={"triaged": 3})

        redis = _RecordingRedis()
        n = asyncio.run(email_alerts_sweep.email_alerts_cron({"redis": redis}))
        assert user_id in {uid for _, uid, _ in redis.calls}
        assert n >= 1

    def test_recency_check_fault_does_not_abort_the_tick_for_later_users(
        self, client, monkeypatch, caplog
    ):
        """A transient DB fault on ONE user's recency check must never
        silently abort enqueueing for every later-ordered eligible user in
        the same tick, and the module's own advertised summary log line must
        still fire — mirrors GAP-P7-DISCOVERY-002's R3/R4 discipline."""
        from app.repositories.gmail_account import GmailAccountRepository
        from app.workers import email_alerts_sweep

        monkeypatch.setenv("AETHER_EMAIL_ALERTS_CRON_ENABLED", "true")
        repo = GmailAccountRepository()

        def _connect(label: str) -> str:
            from app.db import get_connection, new_id

            uid = str(uuid.uuid4())
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        'INSERT INTO "User" ("id","email","name","passwordHash",'
                        '"updatedAt") VALUES (%s,%s,%s,%s,now())',
                        (uid, f"{label}-{new_id()}@example.com", label, "x"),
                    )
                conn.commit()
            repo.upsert_account(
                uid, account_email=f"{label}@gmail.com", refresh_token="r",
            )
            return uid

        user_a = _connect("alerts-fault-a")
        user_b = _connect("alerts-fault-b")
        user_c = _connect("alerts-fault-c")

        real_recently_ran = email_alerts_sweep._recently_ran_job_alerts

        def _faulting(user_id):
            if user_id == user_b:
                raise RuntimeError("simulated transient DB fault")
            return real_recently_ran(user_id)

        monkeypatch.setattr(
            email_alerts_sweep, "_recently_ran_job_alerts", _faulting
        )

        redis = _RecordingRedis()
        with caplog.at_level(logging.INFO, logger="app.workers.email_alerts_sweep"):
            asyncio.run(email_alerts_sweep.email_alerts_cron({"redis": redis}))

        enqueued_ids = {uid for _, uid, _ in redis.calls}
        assert user_a in enqueued_ids
        assert user_c in enqueued_ids, (
            "user C (ordered after the faulting user B) must still be "
            "enqueued — one user's read fault must not abort the rest of "
            "the tick"
        )
        assert user_b in enqueued_ids, (
            "the faulting user's OWN check must fail toward NOT skipping"
        )
        assert "eligible" in caplog.text
        assert "1 recency-check fault(s)" in caplog.text
        assert f"recency check failed for user {user_b}" in caplog.text


# ===========================================================================
# Per-user dispatch — email_alerts_user
# ===========================================================================


class TestEmailAlertsUserTask:
    def test_task_dispatches_job_alerts_mode_via_the_shared_dispatch(
        self, client, user_id, gmail_connected, monkeypatch
    ):
        """``email_alerts_user`` must delegate to the SAME
        ``app.routers.agents._dispatch`` the manual "Scan Job Alerts" button
        uses — proven here by observing the real module-level call it makes,
        with the exact automated-run kwargs (``system_run=True``,
        ``skip_quota=True``)."""
        from app.routers import agents as agents_router
        from app.workers.email_alerts_sweep import email_alerts_user

        calls: list[tuple[str, str, dict]] = []

        def _fake_dispatch(uid, agent_name, params, **kwargs):
            calls.append((uid, agent_name, dict(params)))
            assert kwargs.get("system_run") is True
            assert kwargs.get("skip_quota") is True
            return {
                "jobs_created": 4, "jobs_updated": 1, "alert_emails": 2,
                "degraded": False,
            }

        monkeypatch.setattr(agents_router, "_dispatch", _fake_dispatch)
        result = asyncio.run(email_alerts_user({}, user_id))

        assert result["status"] == "ok"
        assert result["jobsCreated"] == 4
        assert result["jobsUpdated"] == 1
        assert result["alertEmails"] == 2
        assert calls == [(user_id, "emailAgent", {"mode": "job_alerts"})]

    def test_task_honours_the_users_own_agent_pause_without_raising(
        self, client, user_id, gmail_connected
    ):
        """A user who stopped the Email Agent via Agent Controls must be
        skipped exactly as honestly as a manual dispatch would refuse them —
        never bypassed, never a crashed ARQ job. No monkeypatch of
        ``_dispatch`` here: the REAL ``_agent_paused_by_user`` pre-check
        inside ``_dispatch`` must be what refuses this run."""
        from app.db import get_connection
        from app.repositories.billing import _ensure_billing_tables
        from app.routers.agents import _ensure_agent_config_schema
        from app.workers.email_alerts_sweep import email_alerts_user

        _ensure_billing_tables()
        _ensure_agent_config_schema()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "AgentConfig" ("userId", "agentKey", "enabled") '
                    'VALUES (%s, %s, false)',
                    (user_id, "emailAgent"),
                )
            conn.commit()

        result = asyncio.run(email_alerts_user({}, user_id))

        assert result["status"] == "error"
        # ``_skip_reason`` normalises every pause shape _dispatch can raise
        # (a plain-string 409 from its own pre-check, or a dict-detail 409
        # from the defense-in-depth guard) to the same honest "paused" label
        # — mirrors digest_cron's own outcome vocabulary exactly.
        assert result["error"] == "paused"

    def test_task_reports_an_unexpected_failure_honestly_never_raises(
        self, client, user_id, gmail_connected, monkeypatch
    ):
        from app.routers import agents as agents_router
        from app.workers.email_alerts_sweep import email_alerts_user

        def _boom(uid, agent_name, params, **kwargs):
            raise RuntimeError("simulated dispatch failure")

        monkeypatch.setattr(agents_router, "_dispatch", _boom)
        result = asyncio.run(email_alerts_user({}, user_id))

        assert result["status"] == "error"
        assert "simulated dispatch failure" in result["error"]


# ===========================================================================
# End-to-end — a real fixture Seek alert email becomes a Job row through the
# dispatched cron path (never the manual endpoint).
# ===========================================================================


class TestEmailAlertsCronEndToEnd:
    def test_a_fixture_seek_alert_email_becomes_a_job_row_via_the_cron(
        self, client, user_id, gmail_connected, monkeypatch
    ):
        """Connects Gmail for real (through the repository), fakes ONLY the
        live Gmail API surface (``GmailService`` — there is no way to make a
        real OAuth round-trip from the test suite), and drives the FULL cron
        path: ``email_alerts_cron`` enqueues the user, then
        ``email_alerts_user`` (the exact ARQ task the enqueue names) runs
        ``_dispatch(..., "emailAgent", {"mode": "job_alerts"}, ...)`` for
        real. The Seek alert TEXT is the same real, anonymised fixture
        ``test_job_alert_intake.py`` uses."""
        from pathlib import Path

        from app.db import get_connection, rows_to_dicts
        from app.workers import email_alerts_sweep

        monkeypatch.setenv("AETHER_EMAIL_ALERTS_CRON_ENABLED", "true")

        fixture_text = (
            Path(__file__).parent / "data" / "job_alerts"
            / "seek-job-alert-enterprise-architect.txt"
        ).read_text()
        message = {
            "id": "seek-e2e-1",
            "from": "SEEK Job Alerts <jobmail@s.seek.com.au>",
            "subject": "20 new jobs for enterprise architect in Melbourne VIC 3000",
            "date": "Sun, 02 Aug 2026 01:38:08 +1000",
            "text": fixture_text,
            "html": "",
        }

        class _FakeGmailService:
            def __init__(self, uid, account_id=None):
                self.uid = uid
                self.account_id = account_id

            def list_message_headers(self, query=None, max_results=100):
                return [
                    {k: message[k] for k in ("id", "from", "subject", "date")}
                ]

            def get_message_bodies(self, message_id):
                assert message_id == message["id"]
                return message

        monkeypatch.setattr(
            "app.services.gmail_service.GmailService", _FakeGmailService
        )

        redis = _RecordingRedis()
        n = asyncio.run(email_alerts_sweep.email_alerts_cron({"redis": redis}))
        assert n >= 1
        assert (
            ("email_alerts_user", user_id, f"email-alerts:{user_id}") in redis.calls
        )

        result = asyncio.run(email_alerts_sweep.email_alerts_user({}, user_id))
        assert result["status"] == "ok"
        assert result["jobsCreated"] >= 1
        assert result["alertEmails"] == 1

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "title", "company", "source", "sourceUrl" FROM "Job"'
                    ' WHERE "userId" = %s ORDER BY "sourceUrl"',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        assert rows, "the Seek alert posting must have landed as a real Job row"
        assert all(r["source"] == "seek-alert" for r in rows)
        talent = next(
            (r for r in rows if r["sourceUrl"] == "https://au.seek.com/job/93696282"),
            None,
        )
        assert talent is not None
        assert talent["title"] == "Solution Architect"
        assert talent["company"] == "Talent"
