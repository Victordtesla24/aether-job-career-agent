"""Wave-4C — notification (ADR-AG-1: REAL email digests, approval-gated).

The digest is DETERMINISTIC — composed from the user's own Application/Job rows, no
model call, so the run is unmetered and free. The contract asserted here:

* every line of the digest is real data; with nothing new the agent queues NOTHING
  (an empty "here's your update" email is exactly the fake activity ADR-AG-1
  forbids);
* the recipient is the user's OWN connected Gmail. With no Gmail connected there is
  no such address, so nothing is queued — but the digest is still returned so the
  user sees the real data in-app;
* "since last digest" means the last digest the user ACTUALLY SENT: a rejected or
  still-pending digest never swallows its own items;
* a status TRANSITION is never asserted (Aether keeps no status history) — the
  digest reports the CURRENT status of applications whose record changed, and the
  email body says so;
* an unscored posting is a discovery, not a match: it is COUNTED, never promoted;
* the send stays gated — `POST /approvals/{id}/execute` 409s honestly if Gmail is
  disconnected before approval, and no email is sent.

Fail-before at 14fca94: `app.agents.notification_agent` does not exist, the
`notification` card is `planned` with `backend: None`, and
`POST /agents/notification/run` 404s with "Unknown agent".
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.db import get_connection, new_id, rows_to_dicts

from conftest import JORDAN_RESUME_TEXT, seed_own_resume


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


def _runs_used(user_id: str) -> int:
    from app.repositories.billing import UsageQuotaRepository

    row = UsageQuotaRepository().get_by_user(user_id)
    return int(row["runsUsed"]) if row else 0


def _seed_job(
    user_id: str,
    *,
    title: str = "Senior Software Engineer",
    company: str = "Atlassian",
    fit_score: float | None = 82.5,
    location: str | None = "Melbourne, Australia",
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
                    job_id, user_id, title, company, location,
                    "Build distributed backend systems.", json.dumps(["Python"]),
                    "seek", f"https://example.com/job/{job_id}", fit_score,
                ),
            )
        conn.commit()
    return job_id


def _seed_application(
    user_id: str, job_id: str, resume_id: str, *, status: str = "interview"
) -> str:
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
                '"createdAt","updatedAt")'
                ' VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",now(),now())',
                (app_id, user_id, job_id, resume_id, status),
            )
        conn.commit()
    return app_id


def _seed_activity(client, auth_headers, user_id, *, status: str = "interview"):
    resume = seed_own_resume(client, auth_headers, raw_text=JORDAN_RESUME_TEXT)
    job_id = _seed_job(user_id)
    app_id = _seed_application(user_id, job_id, resume["id"], status=status)
    return job_id, app_id


def _second_user(client) -> tuple[str, dict[str, str]]:
    creds = {
        "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Sup3rSecret",
    }
    assert client.post("/auth/register", json=creds).status_code == 201
    token = client.post("/auth/login", json=creds).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client.get("/auth/me", headers=headers).json()["id"], headers


def _digest_rows(user_id: str) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","approvalId","windowStart","windowEnd","statusUpdates",'
                '"newMatches" FROM "NotificationDigest" WHERE "userId" = %s'
                ' ORDER BY "createdAt" ASC',
                (user_id,),
            )
            return rows_to_dicts(cur)


def _approval_count(user_id: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM "ApprovalRequest" WHERE "userId" = %s',
                (user_id,),
            )
            return int(cur.fetchone()[0])


def _run(client, auth_headers) -> dict:
    resp = client.post("/agents/notification/run", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _send_digest(client, auth_headers, approval_id: str, monkeypatch) -> None:
    """Approve + execute a queued digest with the Gmail API call stubbed."""
    monkeypatch.setattr(
        "app.services.gmail_service.GmailService.send",
        lambda self, **kwargs: {"id": f"gmail-{uuid.uuid4().hex[:6]}", "threadId": "T"},
    )
    assert (
        client.post(f"/approvals/{approval_id}/approve", headers=auth_headers).status_code
        == 200
    )
    ex = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)
    assert ex.status_code == 200, ex.text


# ===========================================================================
# Real content, real recipient
# ===========================================================================


def test_digest_of_real_activity_is_queued_to_the_connected_gmail(
    client, auth_headers, user_id, billing_seeded, gmail_connected
):
    job_id, app_id = _seed_activity(client, auth_headers, user_id)
    body = _run(client, auth_headers)

    assert body["firstDigest"] is True and body["windowStart"] is None
    assert [u["applicationId"] for u in body["statusUpdates"]] == [app_id]
    assert body["statusUpdates"][0]["status"] == "interview"
    assert body["statusUpdates"][0]["jobTitle"] == "Senior Software Engineer"
    assert [m["jobId"] for m in body["newMatches"]] == [job_id]
    assert body["newMatches"][0]["fitScore"] == 82.5
    assert body["gmailConnected"] is True
    assert body["recipient"] == gmail_connected
    assert body["approvalStatus"] == "pending"
    assert body["approvalRequired"] is True
    # Deterministic: no model, no cost, no plan quota.
    assert body["model"] is None and body["costUsd"] == 0.0

    card = client.get(
        f"/approvals/{body['approvalId']}", headers=auth_headers
    ).json()
    assert card["type"] == "email_send"
    assert card["payload"]["to"] == gmail_connected
    assert card["payload"]["kind"] == "notification_digest"
    # Every fact in the email is a row the user owns.
    assert "Senior Software Engineer" in card["payload"]["body"]
    assert "Atlassian" in card["payload"]["body"]
    assert "fit 82.5" in card["payload"]["body"]


def test_digest_never_asserts_a_status_transition(
    client, auth_headers, user_id, billing_seeded, gmail_connected
):
    """Aether keeps no status history, so the email must report the CURRENT status
    and say so — never a "from -> to" transition it did not observe."""
    _seed_activity(client, auth_headers, user_id, status="screening")
    body = _run(client, auth_headers)
    email = body["body"]
    assert "CURRENT status" in email
    assert "no status history" in email
    assert "screening" in email
    assert "->" not in email and " to interview" not in email


def test_notification_run_is_unmetered(
    client, auth_headers, user_id, billing_seeded, gmail_connected
):
    _seed_activity(client, auth_headers, user_id)
    before = _runs_used(user_id)
    _run(client, auth_headers)
    assert _runs_used(user_id) == before


# ===========================================================================
# Honest emptiness — never fake activity
# ===========================================================================


def test_nothing_to_report_queues_nothing(
    client, auth_headers, user_id, billing_seeded, gmail_connected
):
    body = _run(client, auth_headers)
    assert body["nothingToReport"] is True
    assert body["statusUpdates"] == [] and body["newMatches"] == []
    assert body["approvalId"] is None
    assert body["body"] == "" and body["subject"] == ""
    assert "fake activity" in body["message"]
    assert _approval_count(user_id) == 0
    assert _digest_rows(user_id) == []


def test_unscored_postings_are_counted_not_promoted_to_matches(
    client, auth_headers, user_id, billing_seeded, gmail_connected
):
    _seed_job(user_id, fit_score=None)
    body = _run(client, auth_headers)
    assert body["newMatches"] == []
    assert body["unscoredDiscoveries"] == 1
    assert body["nothingToReport"] is True
    assert "unscored" in body["message"]
    assert body["approvalId"] is None


def test_draft_applications_are_not_reported_as_updates(
    client, auth_headers, user_id, billing_seeded, gmail_connected
):
    _seed_activity(client, auth_headers, user_id, status="draft")
    body = _run(client, auth_headers)
    assert body["statusUpdates"] == []
    # The scored job it was created against IS a real new match.
    assert len(body["newMatches"]) == 1


# ===========================================================================
# Gmail gating
# ===========================================================================


def test_without_gmail_nothing_is_queued_but_the_data_is_still_returned(
    client, auth_headers, user_id, billing_seeded
):
    job_id, app_id = _seed_activity(client, auth_headers, user_id)
    body = _run(client, auth_headers)

    assert body["gmailConnected"] is False
    assert body["recipient"] is None
    assert body["approvalId"] is None
    assert _approval_count(user_id) == 0
    assert _digest_rows(user_id) == []
    # The real digest is still computed and shown in-app — nothing is hidden.
    assert [u["applicationId"] for u in body["statusUpdates"]] == [app_id]
    assert [m["jobId"] for m in body["newMatches"]] == [job_id]
    assert body["body"]
    assert "connect gmail" in body["message"].lower()


def test_approved_digest_409s_when_gmail_is_disconnected_before_sending(
    client, auth_headers, user_id, billing_seeded
):
    """The honest-409 guarantee: the approval was queued while Gmail was connected,
    and the send still refuses (with no email sent) once it is gone."""
    from app.repositories.gmail_account import GmailAccountRepository

    repo = GmailAccountRepository()
    repo.upsert_account(
        user_id, account_email="jordan.rivera@gmail.com",
        refresh_token="refresh-xyz", scopes="gmail.send",
    )
    _seed_activity(client, auth_headers, user_id)
    approval_id = _run(client, auth_headers)["approvalId"]
    assert approval_id
    repo.disconnect(user_id)

    assert (
        client.post(f"/approvals/{approval_id}/approve", headers=auth_headers).status_code
        == 200
    )
    ex = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)
    assert ex.status_code == 409, ex.text
    assert ex.json()["detail"]["error"] == "no_email_provider_connected"


def test_approved_digest_reaches_gmail_with_the_exact_queued_body(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    captured: dict = {}

    def fake_send(self, **kwargs):  # noqa: ANN001, ARG001
        captured.update(kwargs)
        return {"id": "gmail-digest-1", "threadId": "T1"}

    monkeypatch.setattr("app.services.gmail_service.GmailService.send", fake_send)
    _seed_activity(client, auth_headers, user_id)
    body = _run(client, auth_headers)
    assert (
        client.post(
            f"/approvals/{body['approvalId']}/approve", headers=auth_headers
        ).status_code
        == 200
    )
    ex = client.post(f"/approvals/{body['approvalId']}/execute", headers=auth_headers)
    assert ex.status_code == 200, ex.text
    assert captured["to"] == gmail_connected
    assert captured["body"] == body["body"]
    assert captured["subject"] == body["subject"]


# ===========================================================================
# The "since last digest" watermark
# ===========================================================================


def test_window_advances_only_after_the_digest_is_actually_sent(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    _seed_activity(client, auth_headers, user_id)
    first = _run(client, auth_headers)
    assert first["firstDigest"] is True
    _send_digest(client, auth_headers, first["approvalId"], monkeypatch)

    # Nothing new since — the sent digest's items must not repeat.
    second = _run(client, auth_headers)
    assert second["firstDigest"] is False
    assert second["windowStart"] == first["windowEnd"]
    assert second["nothingToReport"] is True

    # Genuinely new activity after the send DOES appear.
    new_job = _seed_job(user_id, title="Staff Engineer", fit_score=91.0)
    third = _run(client, auth_headers)
    assert [m["jobId"] for m in third["newMatches"]] == [new_job]
    assert third["windowStart"] == first["windowEnd"]


def test_a_rejected_digest_never_swallows_its_items(
    client, auth_headers, user_id, billing_seeded, gmail_connected
):
    job_id, app_id = _seed_activity(client, auth_headers, user_id)
    first = _run(client, auth_headers)
    assert client.post(
        f"/approvals/{first['approvalId']}/reject", headers=auth_headers
    ).status_code == 200

    again = _run(client, auth_headers)
    assert again["firstDigest"] is True and again["windowStart"] is None
    assert [u["applicationId"] for u in again["statusUpdates"]] == [app_id]
    assert [m["jobId"] for m in again["newMatches"]] == [job_id]


def test_a_pending_digest_never_swallows_its_items_and_is_refreshed(
    client, auth_headers, user_id, billing_seeded, gmail_connected
):
    _seed_activity(client, auth_headers, user_id)
    first = _run(client, auth_headers)
    _seed_job(user_id, title="Staff Engineer", fit_score=91.0)
    second = _run(client, auth_headers)

    # Still the FIRST window (nothing was sent), and the pending card is refreshed
    # rather than duplicated — one approval, one digest row.
    assert second["firstDigest"] is True and second["windowStart"] is None
    assert len(second["newMatches"]) == 2
    assert second["approvalId"] == first["approvalId"]
    assert _approval_count(user_id) == 1
    rows = _digest_rows(user_id)
    assert len(rows) == 1 and rows[0]["newMatches"] == 2


# ===========================================================================
# Isolation + wiring
# ===========================================================================


def test_another_users_activity_never_enters_the_digest(
    client, auth_headers, user_id, billing_seeded, gmail_connected
):
    other_id, other_headers = _second_user(client)
    other_resume = seed_own_resume(client, other_headers, raw_text=JORDAN_RESUME_TEXT)
    other_job = _seed_job(other_id, title="Not Yours", company="Elsewhere")
    _seed_application(other_id, other_job, other_resume["id"])

    job_id, app_id = _seed_activity(client, auth_headers, user_id)
    body = _run(client, auth_headers)
    assert [m["jobId"] for m in body["newMatches"]] == [job_id]
    assert [u["applicationId"] for u in body["statusUpdates"]] == [app_id]
    assert "Not Yours" not in body["body"]


def test_another_users_sent_digest_does_not_move_my_window(
    client, auth_headers, user_id, billing_seeded, gmail_connected, monkeypatch
):
    from app.repositories.gmail_account import GmailAccountRepository

    other_id, other_headers = _second_user(client)
    other_repo = GmailAccountRepository()
    other_repo.upsert_account(
        other_id, account_email="other@gmail.com", refresh_token="r", scopes="gmail.send"
    )
    other_resume = seed_own_resume(client, other_headers, raw_text=JORDAN_RESUME_TEXT)
    other_job = _seed_job(other_id)
    _seed_application(other_id, other_job, other_resume["id"])
    other = _run(client, other_headers)
    _send_digest(client, other_headers, other["approvalId"], monkeypatch)

    _seed_activity(client, auth_headers, user_id)
    mine = _run(client, auth_headers)
    assert mine["firstDigest"] is True and mine["windowStart"] is None
    assert mine["statusUpdates"] and mine["newMatches"]


def test_card_is_wired_active_runnable_deterministic_and_gated(client, auth_headers):
    cards = {
        a["key"]: a
        for a in client.get("/agents/catalog", headers=auth_headers).json()["agents"]
    }
    card = cards["notification"]
    assert card["backend"] == "notification"
    assert card["status"] == "active" and card["runnable"] is True
    # No model is ever called, so the picker is honestly locked.
    assert card["modelOverridable"] is False
    assert card["recommended"] == "deterministic"

    from app.routers.agents import (
        _APPROVAL_GATED,
        _DETERMINISTIC_BACKENDS,
        _LLM_TIER_BY_BACKEND,
        _RUNNABLE_BACKENDS,
        _call_is_metered,
    )

    assert "notification" in _APPROVAL_GATED
    assert "notification" in _RUNNABLE_BACKENDS
    assert "notification" in _DETERMINISTIC_BACKENDS
    assert "notification" not in _LLM_TIER_BY_BACKEND
    assert _call_is_metered("notification", {}) is False


def test_card_copy_claims_no_push_channel(client, auth_headers):
    cards = {
        a["key"]: a
        for a in client.get("/agents/catalog", headers=auth_headers).json()["agents"]
    }
    tip = cards["notification"]["tip"].lower()
    for forbidden in ("pushes timely alerts", "push notification", "sms"):
        assert forbidden not in tip, f"notification tip still says {forbidden!r}"
    assert "gmail" in tip and "approve" in tip


def test_digest_table_ddl_is_idempotent():
    """ADR-TR-1: the lazy DDL must be safe to run repeatedly."""
    import app.agents.notification_agent as agent_mod

    agent_mod.ensure_notification_digest_table()
    agent_mod._table_ready = False  # force the full path again
    agent_mod.ensure_notification_digest_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_name = 'NotificationDigest'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            assert cur.fetchone()[0] == 1
