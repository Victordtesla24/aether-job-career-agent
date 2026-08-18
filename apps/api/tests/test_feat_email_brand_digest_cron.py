"""FEAT-EMAIL-BRAND — the daily notification-digest cron (RUN-20260818T0223Z).

GAP CLOSED: ``NotificationAgent.run()`` (the "daily job-application summary")
has always composed a correctly BRANDED email, but nothing ever triggered it
— ``apps/api/app/workers/settings.py::_cron_jobs()`` registered no digest
cron, so it only ran when a human POSTed ``/agents/run mode=notification``.

Covers (phase 1, cron scheduling/eligibility):
* the cron is registered on ``WorkerSettings`` at 21:00 UTC, minute :11;
* the kill-switch (``AETHER_DIGEST_CRON_ENABLED=false``) is an honest no-op;
* an eligible Gmail-connected user with real activity gets a
  ``notification_digest`` approval QUEUED;
* a user with nothing new is honestly counted, not silently skipped;
* a user with the ``notification`` agent paused is honestly skipped, not run;
* a user without an active paid subscription is honestly skipped (the
  GAP-P6-PAYWALL gate applies to this automated trigger exactly as it does to
  a manual click — ``system_run=True`` does not exempt ``notification``);
* a user with NO connected Gmail account is never even attempted (the digest
  can never be mailed to them, so the cron's eligibility query excludes them
  entirely — confirmed both via the repository query and via the cron body);
* ``GmailAccountRepository.list_connected_user_ids`` returns exactly the
  distinct connected user ids;
* a SUSPENDED or SOFT-DELETED user is never counted eligible, queued, or
  sent a digest, even at production-default flags (P0 fix,
  RUN-20260818T0223Z adversarial review — `03-adversarial-review.md`).

Covers (phase 2, FEAT-EMAIL-BRAND, RUN-20260818T0223Z — Owner directive
2026-08-18, strictly-scoped auto-send; see
docs/delivery/evidence/RUN-20260818T0223Z/05-decision-memos/
FEAT-EMAIL-BRAND-autosend.md):
* a digest addressed to the user's OWN connected Gmail is auto-approved +
  auto-sent, rendered through the SAME ``email_branding.
  build_notification_digest_bodies`` a manual execute uses (branding markers
  asserted present in the sent HTML);
* a recipient that is NOT provably self-mail is left pending, honestly
  logged, and Gmail send is never called — even with the flag on;
* ANY approval kind other than ``notification_digest`` is never auto-executed
  — even with the flag on and a genuinely self-mail recipient (defense in
  depth inside ``auto_execute_notification_digest`` itself, not just "the
  cron never calls it for other kinds");
* the kill-switch ``AETHER_DIGEST_AUTO_SEND=false`` restores the phase-1
  pending-only behaviour exactly.

NOTE ON A REMOVED PIN: the phase-1 test
``test_digest_cron_never_auto_sends_only_queues_for_manual_approval`` pinned
"the cron must never call Gmail send directly" as an ABSOLUTE. That absolute
is no longer true by Owner directive (2026-08-18) and is REPLACED here by the
two invariants that now bound auto-send precisely: never a non-digest kind,
never a non-self recipient. This is a deliberate, directed policy change —
see the commit body and the decision memo — not a silent weakening.

Fail-before (phase 1): ``app.workers.digest_cron`` does not exist, and
``WorkerSettings.cron_jobs`` carries no job whose coroutine is
``notification_digest_cron``.
Fail-before (phase 2): ``app.routers.approvals.auto_execute_notification_digest``
does not exist.
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


def _approval_row(user_id: str) -> dict | None:
    """The most recent ``notification_digest`` approval's id/status/execution
    marker/payload — used by the phase-2 auto-send tests to assert the row
    ends in the SAME "approved + executionCompletedAt stamped" state a manual
    Approve-then-Execute click leaves."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","status"::text,"executionCompletedAt","payload"'
                ' FROM "ApprovalRequest" WHERE "userId" = %s'
                ' AND "payload"->>\'kind\' = \'notification_digest\''
                ' ORDER BY "createdAt" DESC LIMIT 1',
                (user_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "status": row[1], "executionCompletedAt": row[2],
        "payload": row[3],
    }


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
# Suspension / soft-delete exclusion — P0 fix (RUN-20260818T0223Z adversarial
# review, `03-adversarial-review.md`). Account suspension (GAP-P6 §15) is
# enforced ONLY at the HTTP auth-dependency layer
# (apps/api/app/middleware/auth.py) — a suspended user gets a 403 on every
# authenticated route. This cron calls app.routers.agents._dispatch directly
# as a Python function, in-process, bypassing that layer entirely. The
# reviewer live-reproduced: a suspended user with a connected Gmail account
# and real activity was counted eligible, auto-approved, AND auto-executed —
# a real branded email sent with zero human in the loop. Both tests below run
# at PRODUCTION-DEFAULT flags (both kill-switches explicitly ON) to match the
# exact conditions of the reported leak, and must FAIL against the
# pre-fix query (captured in the evidence file) and PASS after it.
# ===========================================================================


def test_digest_cron_excludes_a_suspended_user(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    """A suspended user (``User.suspended = true``, written through the exact
    repository function ``POST /admin/users/{id}/suspend`` uses) must never
    be counted eligible, queued, or sent a digest — even with both
    kill-switches at their production default (ON)."""
    from app.repositories.admin import set_suspended
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")
    monkeypatch.setenv("AETHER_DIGEST_AUTO_SEND", "true")

    def _fail_if_called(*args, **kwargs):  # noqa: ANN001, ARG001
        pytest.fail("must never send digest email to a suspended user")

    monkeypatch.setattr(
        "app.services.gmail_service.GmailService.send", _fail_if_called
    )
    _seed_activity(client, auth_headers, user_id)
    set_suspended(user_id, True)

    result = asyncio.run(notification_digest_cron({}))

    assert result["eligible"] == 0
    assert result["enqueued"] == 0
    assert result["autoSent"] == 0
    assert _approval_count(user_id) == 0


def test_digest_cron_excludes_a_soft_deleted_user(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    """Independent of the suspended-flag test above: only ``deletedAt`` is
    stamped here (NOT ``suspended``), isolating the eligibility query's own
    ``deletedAt IS NULL`` clause so it is proven to exclude the row on its
    own merits — the real ``admin.soft_delete_user`` write path sets BOTH
    columns together ("suspension is the teeth"), which would leave this
    specific clause untested by that path alone."""
    from app.db import ensure_user_lifecycle_columns
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")
    monkeypatch.setenv("AETHER_DIGEST_AUTO_SEND", "true")

    def _fail_if_called(*args, **kwargs):  # noqa: ANN001, ARG001
        pytest.fail("must never send digest email to a soft-deleted user")

    monkeypatch.setattr(
        "app.services.gmail_service.GmailService.send", _fail_if_called
    )
    _seed_activity(client, auth_headers, user_id)
    ensure_user_lifecycle_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "deletedAt" = now() WHERE "id" = %s', (user_id,)
            )
        conn.commit()

    result = asyncio.run(notification_digest_cron({}))

    assert result["eligible"] == 0
    assert result["enqueued"] == 0
    assert result["autoSent"] == 0
    assert _approval_count(user_id) == 0


# ===========================================================================
# Behaviour — eligible / no-activity / paused / disabled paths
# ===========================================================================


def test_digest_cron_queues_a_real_digest_for_an_eligible_user(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    """Scope note: auto-send is explicitly held OFF here so this test pins
    ONLY the phase-1 concern (does the cron correctly queue a digest) —
    phase-2 auto-send is pinned separately below, deliberately, with the flag
    ON (its own default)."""
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")
    monkeypatch.setenv("AETHER_DIGEST_AUTO_SEND", "false")
    _seed_activity(client, auth_headers, user_id)

    result = asyncio.run(notification_digest_cron({}))

    assert result["enqueued"] >= 1
    assert _approval_count(user_id) == 1
    assert _approval_status(user_id) == "pending"


# ===========================================================================
# Phase 2 — strictly-scoped auto-send (FEAT-EMAIL-BRAND, Owner directive
# 2026-08-18). See docs/delivery/evidence/RUN-20260818T0223Z/
# 05-decision-memos/FEAT-EMAIL-BRAND-autosend.md for the policy rationale.
# ===========================================================================


def test_digest_auto_send_sends_branded_email_to_self_recipient(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    """(a) A digest addressed to the user's OWN connected Gmail is
    auto-approved + auto-sent, rendered through the SAME branded HTML
    (``email_branding.build_notification_digest_bodies``) a manual
    Approve-then-Execute click would produce — proving there is no second
    send path."""
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")
    monkeypatch.setenv("AETHER_DIGEST_AUTO_SEND", "true")
    captured: dict = {}

    def fake_send(self, **kwargs):  # noqa: ANN001, ARG001
        captured.update(kwargs)
        return {"id": "gmail-auto-1", "threadId": "T1"}

    monkeypatch.setattr("app.services.gmail_service.GmailService.send", fake_send)
    _seed_activity(client, auth_headers, user_id)

    result = asyncio.run(notification_digest_cron({}))

    assert result["autoSent"] >= 1
    assert result["outcomes"].get("auto_sent", 0) >= 1
    assert captured["to"] == gmail_connected
    html = captured.get("html_body") or ""
    # Aether design-system markers (design/aether-design-system): the gilt
    # wordmark block and the primary gilt token `#C9A84C`.
    assert "AETHER" in html
    assert "#c9a84c" in html.lower()

    row = _approval_row(user_id)
    assert row is not None
    assert row["status"] == "approved"
    assert row["executionCompletedAt"] is not None
    assert row["payload"].get("autoExecutedBy") == "digest_cron"
    assert row["payload"].get("autoExecutedAt")


def test_digest_auto_send_refuses_a_non_self_recipient(
    user_id, billing_seeded, gmail_connected, monkeypatch
):
    """(b) A ``notification_digest`` approval whose ``to`` does not
    (case-insensitively) match one of the user's own connected Gmail
    addresses is left PENDING, honestly, even with the flag on. Constructs
    the approval directly (rather than via the full cron/NotificationAgent
    path) to pin the guard itself — ``NotificationAgent`` always sets ``to``
    to the user's own connected address by construction, so a mismatch can
    only arise from a stale payload or a reconnect race; this proves the
    re-verification at send time catches it either way."""
    from app.repositories.approval import ApprovalRepository
    from app.routers.approvals import auto_execute_notification_digest

    monkeypatch.setenv("AETHER_DIGEST_AUTO_SEND", "true")

    def _fail_if_called(*args, **kwargs):  # noqa: ANN001, ARG001
        pytest.fail("must never send to a recipient that is not provably self-mail")

    monkeypatch.setattr(
        "app.services.gmail_service.GmailService.send", _fail_if_called
    )
    approval = ApprovalRepository().create(
        user_id, "email_send",
        {
            "kind": "notification_digest", "to": "someone-else@example.com",
            "subject": "Your Aether digest", "body": "Status updates inside.",
        },
    )

    sent = auto_execute_notification_digest(approval["id"], user_id)

    assert sent is None
    row = _approval_row(user_id)
    assert row["status"] == "pending"
    assert "autoExecutedBy" not in (row["payload"] or {})


def test_digest_auto_send_never_executes_other_approval_kinds(
    user_id, billing_seeded, gmail_connected, monkeypatch
):
    """(c) ONLY ``kind == "notification_digest"`` may ever be auto-executed —
    an ``email_send`` approval of any other kind (a drafted reply, recruiter
    outreach, a reference request) stays exactly manual-only, even with the
    flag on AND a genuinely self-mail recipient. Enforced INSIDE
    ``auto_execute_notification_digest`` itself (defense in depth), not just
    by the cron never calling it for other kinds."""
    from app.repositories.approval import ApprovalRepository
    from app.routers.approvals import auto_execute_notification_digest

    monkeypatch.setenv("AETHER_DIGEST_AUTO_SEND", "true")

    def _fail_if_called(*args, **kwargs):  # noqa: ANN001, ARG001
        pytest.fail("must never auto-send a non-notification_digest approval kind")

    monkeypatch.setattr(
        "app.services.gmail_service.GmailService.send", _fail_if_called
    )
    approval = ApprovalRepository().create(
        user_id, "email_send",
        {
            "kind": "email", "to": gmail_connected,
            "subject": "Re: your application", "body": "A drafted reply.",
        },
    )

    sent = auto_execute_notification_digest(approval["id"], user_id)

    assert sent is None
    row = ApprovalRepository().get_by_id(approval["id"], user_id)
    assert row["status"] == "pending"


def test_digest_auto_send_disabled_leaves_approval_pending(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    """(d) ``AETHER_DIGEST_AUTO_SEND=false`` restores the phase-1
    pending-only behaviour exactly — Gmail send is never even attempted."""
    from app.workers.digest_cron import notification_digest_cron

    monkeypatch.setenv("AETHER_DIGEST_CRON_ENABLED", "true")
    monkeypatch.setenv("AETHER_DIGEST_AUTO_SEND", "false")

    def _fail_if_called(*args, **kwargs):  # noqa: ANN001, ARG001
        pytest.fail("auto-send must be fully inert when the flag is off")

    monkeypatch.setattr(
        "app.services.gmail_service.GmailService.send", _fail_if_called
    )
    _seed_activity(client, auth_headers, user_id)

    result = asyncio.run(notification_digest_cron({}))

    assert result["autoSent"] == 0
    assert result["outcomes"].get("auto_sent", 0) == 0
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
