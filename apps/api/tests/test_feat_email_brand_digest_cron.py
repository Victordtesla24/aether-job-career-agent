"""FEAT-EMAIL-BRAND — the daily notification-digest cron (RUN-20260818T0223Z).

GAP CLOSED: ``NotificationAgent.run()`` (the "daily job-application summary")
has always composed a correctly BRANDED email, but nothing ever triggered it
— ``apps/api/app/workers/settings.py::_cron_jobs()`` registered no digest
cron, so it only ran when a human POSTed ``/agents/run mode=notification``.

Covers:
* the cron is registered on ``WorkerSettings`` at 21:00 UTC, minute :11;
* the kill-switch (``AETHER_DIGEST_CRON_ENABLED=false``) is an honest no-op;
* an eligible Gmail-connected user with real activity gets a
  ``notification_digest`` approval QUEUED — never auto-sent (there is no
  auto-approve/auto-send semantic for any approval kind; the send stays a
  one-click manual approval, mirroring the manual trigger exactly);
* a user with nothing new is honestly counted, not silently skipped;
* a user with the ``notification`` agent paused is honestly skipped, not run;
* a user without an active paid subscription is honestly skipped (the
  GAP-P6-PAYWALL gate applies to this automated trigger exactly as it does to
  a manual click — ``system_run=True`` does not exempt ``notification``);
* a user with NO connected Gmail account is never even attempted (the digest
  can never be mailed to them, so the cron's eligibility query excludes them
  entirely — confirmed both via the repository query and via the cron body);
* ``GmailAccountRepository.list_connected_user_ids`` returns exactly the
  distinct connected user ids.

Fail-before: ``app.workers.digest_cron`` does not exist, and
``WorkerSettings.cron_jobs`` carries no job whose coroutine is
``notification_digest_cron``.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from conftest import JORDAN_RESUME_TEXT, seed_own_resume

from app.db import get_connection, new_id


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
    repo.upsert_account(
        user_id,
        account_email="jordan.rivera@gmail.com",
        refresh_token="refresh-xyz",
        scopes="gmail.send",
    )
    yield "jordan.rivera@gmail.com"
    repo.disconnect(user_id)


def _seed_job(
    user_id: str,
    *,
    title: str = "Senior Software Engineer",
    company: str = "Atlassian",
    fit_score: float | None = 82.5,
) -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Job" ("id","userId","title","company","location",'
                '"remote","description","requirements","source","sourceUrl","status",'
                '"fitScore","createdAt","updatedAt") VALUES '
                "(%s,%s,%s,%s,%s,FALSE,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,"
                "now(),now())",
                (
                    job_id, user_id, title, company, "Melbourne, Australia",
                    "Build distributed backend systems.", json.dumps(["Python"]),
                    "seek", f"https://example.com/job/{job_id}", fit_score,
                ),
            )
        conn.commit()
    return job_id


def _seed_application(user_id: str, job_id: str, resume_id: str) -> str:
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
                '"createdAt","updatedAt")'
                " VALUES (%s,%s,%s,%s,'interview'::\"ApplicationStatus\",now(),now())",
                (app_id, user_id, job_id, resume_id),
            )
        conn.commit()
    return app_id


def _seed_activity(client, auth_headers, user_id) -> None:
    resume = seed_own_resume(client, auth_headers, raw_text=JORDAN_RESUME_TEXT)
    job_id = _seed_job(user_id)
    _seed_application(user_id, job_id, resume["id"])


def _approval_count(user_id: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM "ApprovalRequest" WHERE "userId" = %s'
                ' AND "payload"->>\'kind\' = \'notification_digest\'',
                (user_id,),
            )
            return int(cur.fetchone()[0])


def _approval_status(user_id: str) -> str | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status"::text FROM "ApprovalRequest" WHERE "userId" = %s'
                ' AND "payload"->>\'kind\' = \'notification_digest\''
                ' ORDER BY "createdAt" DESC LIMIT 1',
                (user_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None


def _set_agent_enabled(client, auth_headers, ui_key: str, enabled: bool) -> None:
    """Pause/re-enable an agent through the REAL PATCH endpoint — the exact
    same write path the Agents-page per-agent toggle uses."""
    resp = client.put(
        f"/agents/config/{ui_key}", headers=auth_headers, json={"enabled": enabled}
    )
    assert resp.status_code == 200, resp.text


# ===========================================================================
# Registration + cadence + kill-switch
# ===========================================================================


def test_digest_cron_is_registered_at_21_00_utc_minute_11():
    from app.workers.digest_cron import notification_digest_cron
    from app.workers.settings import WorkerSettings

    jobs = [
        job for job in WorkerSettings.cron_jobs
        if getattr(job, "coroutine", None) is notification_digest_cron
    ]
    assert jobs, "notification_digest_cron must be registered on WorkerSettings"
    job = jobs[0]
    assert job.hour == {21}, job.hour
    assert job.minute == {11}, job.minute


def test_digest_cron_is_noop_when_disabled(monkeypatch):
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "false")
    result = asyncio.run(notification_digest_cron({}))
    assert result == {"ran": False, "reason": "disabled"}


def test_digest_cron_enabled_defaults_true(monkeypatch):
    from app.workers.digest_cron import digest_cron_enabled

    monkeypatch.delenv("AETHER_DIGEST_CRON_ENABLED", raising=False)
    assert digest_cron_enabled() is True


# ===========================================================================
# Eligibility — GmailAccountRepository
# ===========================================================================


def test_list_connected_user_ids_includes_only_connected_users(
    user_id, gmail_connected
):
    from app.repositories.gmail_account import GmailAccountRepository

    ids = GmailAccountRepository().list_connected_user_ids()
    assert user_id in ids


def test_list_connected_user_ids_excludes_disconnected_users(user_id):
    from app.repositories.gmail_account import GmailAccountRepository

    ids = GmailAccountRepository().list_connected_user_ids()
    assert user_id not in ids


# ===========================================================================
# Behaviour — eligible / no-activity / paused / disabled paths
# ===========================================================================


def test_digest_cron_queues_a_real_digest_for_an_eligible_user(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")
    _seed_activity(client, auth_headers, user_id)

    result = asyncio.run(notification_digest_cron({}))

    assert result["enqueued"] >= 1
    assert _approval_count(user_id) == 1
    assert _approval_status(user_id) == "pending"


def test_digest_cron_never_auto_sends_only_queues_for_manual_approval(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    """The central honesty check: the cron must never leave the approval in
    any state that implies a send happened. Nothing here calls Gmail."""
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")

    def _fail_if_called(*args, **kwargs):  # noqa: ANN001, ARG001
        pytest.fail("the digest cron must never call Gmail send directly")

    monkeypatch.setattr(
        "app.services.gmail_service.GmailService.send", _fail_if_called
    )
    _seed_activity(client, auth_headers, user_id)

    asyncio.run(notification_digest_cron({}))

    assert _approval_status(user_id) == "pending"


def test_digest_cron_honestly_counts_users_with_nothing_new(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")
    result = asyncio.run(notification_digest_cron({}))

    assert _approval_count(user_id) == 0
    assert result["outcomes"].get("no_activity", 0) >= 1


def test_digest_cron_skips_a_paused_notification_agent(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")
    _seed_activity(client, auth_headers, user_id)
    _set_agent_enabled(client, auth_headers, "notification", False)

    result = asyncio.run(notification_digest_cron({}))

    assert _approval_count(user_id) == 0
    assert result["outcomes"].get("paused", 0) >= 1


def test_digest_cron_skips_a_user_without_an_active_subscription(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")
    _seed_activity(client, auth_headers, user_id)

    result = asyncio.run(notification_digest_cron({}))

    assert _approval_count(user_id) == 0
    assert result["outcomes"].get("subscription_required", 0) >= 1


def test_digest_cron_never_attempts_a_user_with_no_gmail_connected(
    client, auth_headers, user_id, billing_seeded, monkeypatch
):
    """No fixture connects Gmail here — the user must never even be dispatched."""
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")
    _seed_activity(client, auth_headers, user_id)

    def _fail_if_dispatched(uid):  # noqa: ANN001
        pytest.fail(f"user {uid} has no Gmail connected and must not be dispatched")

    monkeypatch.setattr(
        "app.workers.digest_cron._run_notification_for_user", _fail_if_dispatched
    )

    result = asyncio.run(notification_digest_cron({}))

    assert result["eligible"] == 0
    assert _approval_count(user_id) == 0
