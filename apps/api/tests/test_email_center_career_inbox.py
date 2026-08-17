"""Email Center inbox: latest-first sort, career-only list, interview ingest.

These tests reproduce the live Email-Center defects BEFORE the fix:

* Sort used EmailThread.updatedAt / createdAt (triage stomps updatedAt), so
  a tenancy email from yesterday outranked today's recruiter mail.
* Sync pulled the newest 25 Gmail threads with no career query, so personal
  mail occupied the window and an interview invite never entered EmailThread.
* receivedAt was the DB insert date truncated to YYYY-MM-DD, not the Gmail
  message time.
* An inbound interview invite never promoted Application.status, so
  interview-conversion analytics stayed stale.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from app.db import new_id
from app.services.gmail_service import (
    ensure_email_thread_gmail_columns,
    ensure_email_thread_last_message_column,
)


def _inbox(client, auth_headers):
    resp = client.get("/workspaces/emails/inbox", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_gmail_thread(
    db_session,
    user_id: str,
    *,
    subject: str,
    sender: str,
    sender_email: str,
    body: str,
    received_at: datetime,
    updated_at: datetime | None = None,
    classification: str | None = None,
) -> str:
    ensure_email_thread_gmail_columns()
    ensure_email_thread_last_message_column()
    tid = new_id()
    gmail_tid = f"gm-{uuid.uuid4().hex[:12]}"
    messages = json.dumps(
        [
            {
                "role": "received",
                "body": body,
                "from": sender,
                "fromEmail": sender_email,
                "createdAt": received_at.isoformat(),
            }
        ]
    )
    stamp_updated = updated_at or received_at
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "EmailThread" '
            '("id","userId","subject","messages","classification",'
            ' "gmailThreadId","lastMessageAt","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)",
            (
                tid,
                user_id,
                subject,
                messages,
                classification,
                gmail_tid,
                received_at,
                received_at - timedelta(days=30),  # insert time is OLD on purpose
                stamp_updated,
            ),
        )
    db_session.commit()
    return tid


def test_inbox_orders_by_last_message_time_not_updated_at(
    client, auth_headers, test_user_id, db_session
):
    """A freshly-triaged OLD personal thread must not outrank a newer invite.

    Live bug: triage SET updatedAt=now() on every classified row, and the
    inbox ORDER BY updatedAt DESC, so yesterday's tenancy mail sat on top
    of this afternoon's interview invite.
    """
    now = datetime.now(timezone.utc)
    _seed_gmail_thread(
        db_session,
        test_user_id,
        subject="Hearing reminder for 25/32 Queens Road",
        sender="Residential Tenancies",
        sender_email="renting@courts.vic.gov.au",
        body="Your residential tenancies hearing is listed.",
        received_at=now - timedelta(days=1),
        updated_at=now,  # triage just stomped this
        classification="all",
    )
    invite_id = _seed_gmail_thread(
        db_session,
        test_user_id,
        subject="Invitation: Interview with John Black @ 3:00pm",
        sender="John Black",
        sender_email="john.black@talent.example.com",
        body="John Black has invited you to a Google Meet interview.",
        received_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=2),
        classification="priority",
    )
    data = _inbox(client, auth_headers)
    ids = [m["id"] for m in data["messages"]]
    assert invite_id in ids
    assert ids[0] == invite_id, ids
    # Date-only YYYY-MM-DD is how the live UI made same-day order unreadable.
    invite = next(m for m in data["messages"] if m["id"] == invite_id)
    assert "T" in invite["receivedAt"] or "+" in invite["receivedAt"]
    assert invite["receivedAt"][:10] != str(now - timedelta(days=30))[:10]


def test_inbox_hides_personal_mail_and_keeps_interview_invite(
    client, auth_headers, test_user_id, db_session
):
    now = datetime.now(timezone.utc)
    _seed_gmail_thread(
        db_session,
        test_user_id,
        subject="Hearing reminder for 25/32 Queens Road",
        sender="Residential Tenancies",
        sender_email="renting@courts.vic.gov.au",
        body="Your residential tenancies hearing is listed.",
        received_at=now,
        classification="all",
    )
    invite_id = _seed_gmail_thread(
        db_session,
        test_user_id,
        subject="Invitation: Interview with John Black @ 3:00pm",
        sender="John Black",
        sender_email="john.black@talent.example.com",
        body="John Black has invited you to a Google Meet interview.",
        received_at=now - timedelta(minutes=5),
        classification="all",
    )
    data = _inbox(client, auth_headers)
    subjects = [m["subject"] for m in data["messages"]]
    assert any("John Black" in s for s in subjects), subjects
    assert all("Hearing reminder" not in s for s in subjects), subjects
    assert all("courts.vic.gov.au" not in (m.get("fromEmail") or "") for m in data["messages"])
    invite = next(m for m in data["messages"] if m["id"] == invite_id)
    assert invite["category"] == "priority"
    assert data["stats"]["received"] == 1


def test_local_drafts_still_appear_in_inbox(client, auth_headers):
    """Regression: /emails/draft threads have no gmailThreadId and must stay."""
    resp = client.post(
        "/emails/draft",
        json={"subject": "Untriaged recruiter", "body": "Body for Untriaged recruiter"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    data = _inbox(client, auth_headers)
    assert any(m["subject"] == "Untriaged recruiter" for m in data["messages"])


def test_career_gmail_query_includes_calendar_invites_and_interview_terms():
    from app.services.career_email_filter import CAREER_GMAIL_QUERY

    q = CAREER_GMAIL_QUERY.lower()
    assert "has:calendar" in q or "filename:ics" in q
    assert "interview" in q
    assert "recruiter" in q
    assert "calendar-notification@google.com" in q


def test_inbox_returns_persisted_draft_reply(
    client, auth_headers, test_user_id, db_session
):
    """A fabrication-guarded draft_reply is stored on the thread and shown
    in Email Center. Nothing is sent."""
    from conftest import seed_own_resume

    seed_own_resume(client, auth_headers)
    now = datetime.now(timezone.utc)
    tid = _seed_gmail_thread(
        db_session,
        test_user_id,
        subject="Interview availability",
        sender="Jane Recruiter",
        sender_email="jane@talent.example.com",
        body="Are you free Thursday for a screening call?",
        received_at=now,
        classification="priority",
    )
    resp = client.post(
        "/agents/email/run",
        json={"mode": "draft_reply", "thread_id": tid},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("approval_status") in (None, "")
    assert "sent" not in (body.get("message") or "").lower() or "before sending" in (
        body.get("message") or ""
    ).lower()
    draft = (body.get("draft") or "").strip()
    assert draft
    data = _inbox(client, auth_headers)
    msg = next(m for m in data["messages"] if m["id"] == tid)
    assert msg["draftReply"] == draft
    assert data["stats"]["avgResponseHrs"] is None


def test_inbox_force_sync_bypasses_ttl(
    client, auth_headers, test_user_id, monkeypatch
):
    """Sync Now (?force=true) re-pulls Gmail even inside the freshness window."""
    from app.repositories.gmail_account import GmailAccountRepository

    sync_calls: list[str] = []

    class _FakeGmailService:
        def __init__(self, user_id, account_id=None, creds_repo=None):
            self._account_id = account_id

        def sync_threads_to_db(self, user_id=None, query=None, max_results=25):
            sync_calls.append(self._account_id)
            GmailAccountRepository().mark_synced(self._account_id)
            return 0

    repo = GmailAccountRepository()
    repo.upsert_account(
        test_user_id,
        account_email="force-sync@gmail.com",
        refresh_token="refresh-force",
        scopes="gmail.modify",
    )
    monkeypatch.setattr("app.services.gmail_service.GmailService", _FakeGmailService)
    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "120")
    try:
        first = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert first.status_code == 200, first.text
        assert len(sync_calls) == 1
        second = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert second.status_code == 200, second.text
        assert len(sync_calls) == 1
        forced = client.get(
            "/workspaces/emails/inbox?force=true", headers=auth_headers
        )
        assert forced.status_code == 200, forced.text
        assert len(sync_calls) == 2
    finally:
        repo.disconnect(test_user_id)


def test_inbox_unread_counts_unread_labels_not_personal(
    client, auth_headers, test_user_id, db_session, monkeypatch
):
    """Per-account unread is the count of career threads labelled UNREAD."""
    from app.repositories.gmail_account import GmailAccountRepository
    from app.services.gmail_service import ensure_email_thread_gmail_columns

    class _FakeGmailService:
        def __init__(self, user_id, account_id=None, creds_repo=None):
            self._account_id = account_id

        def sync_threads_to_db(self, user_id=None, query=None, max_results=25):
            GmailAccountRepository().mark_synced(self._account_id)
            return 0

    monkeypatch.setattr("app.services.gmail_service.GmailService", _FakeGmailService)
    repo = GmailAccountRepository()
    acc = repo.upsert_account(
        test_user_id,
        account_email="unread@gmail.com",
        refresh_token="refresh-unread",
        scopes="gmail.modify",
    )
    acc_id = acc["id"]
    ensure_email_thread_gmail_columns()
    now = datetime.now(timezone.utc)
    tid = _seed_gmail_thread(
        db_session,
        test_user_id,
        subject="Role at Acme",
        sender="Hiring",
        sender_email="jobs@acme.example",
        body="We would like to chat about the role.",
        received_at=now,
        classification="priority",
    )
    with db_session.cursor() as cur:
        cur.execute(
            'UPDATE "EmailThread" SET "gmailAccountId" = %s, labels = %s'
            ' WHERE id = %s',
            (acc_id, ["UNREAD", "INBOX"], tid),
        )
    db_session.commit()
    try:
        data = _inbox(client, auth_headers)
        match = next(a for a in data["accounts"] if a["email"] == "unread@gmail.com")
        assert match["unread"] == 1
        card = next(m for m in data["messages"] if m["id"] == tid)
        assert card["unread"] is True
    finally:
        repo.disconnect(test_user_id)


def test_inbox_hides_github_notifications(
    client, auth_headers, test_user_id, db_session
):
    now = datetime.now(timezone.utc)
    _seed_gmail_thread(
        db_session,
        test_user_id,
        subject="[Victordtesla24/aether-job-career-agent] interview ingest (PR #16)",
        sender="cursor[bot]",
        sender_email="notifications@github.com",
        body="You can view, comment on, or merge this pull request.",
        received_at=now,
        classification="priority",
    )
    invite_id = _seed_gmail_thread(
        db_session,
        test_user_id,
        subject="Interview: Adan & Vikram (Project Manager @ Next Business Energy)",
        sender="John Black",
        sender_email="john.black@robertwalters.com.au",
        body="John Black has invited you to an interview.",
        received_at=now - timedelta(minutes=1),
        classification="all",
    )
    data = _inbox(client, auth_headers)
    subjects = [m["subject"] for m in data["messages"]]
    assert invite_id in [m["id"] for m in data["messages"]]
    assert all("github.com" not in (m.get("fromEmail") or "") for m in data["messages"])
    assert all("aether-job-career-agent" not in s for s in subjects)
