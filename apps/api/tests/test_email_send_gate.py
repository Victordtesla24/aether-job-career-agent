"""P4 — Email send-gate: honest 409 until Gmail is connected, real send after.

Preserves the GAP-P4-042 discipline (no provider → 409, no silent fabricated
"sent") while proving the real Gmail send path once a credential exists. The
Gmail API call itself is monkeypatched — no live send.
"""
from __future__ import annotations

from app.db import get_connection, new_id
from app.repositories.gmail_account import GmailAccountRepository


def test_send_gate_409_without_gmail(client, auth_headers):
    resp = client.post(
        "/workspaces/emails/send",
        json={"message_id": "nonexistent", "body": "hi"},
        headers=auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"] == "no_email_provider_connected"


def _seed_contact_thread(user_id: str, email: str) -> str:
    """Insert a Contact (with email) and a linked EmailThread; return thread id."""
    contact_id = new_id()
    thread_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Contact" ("id","userId","name","email","updatedAt")'
                " VALUES (%s,%s,%s,%s,now())",
                (contact_id, user_id, "Sarah Chen", email),
            )
            cur.execute(
                'INSERT INTO "EmailThread"'
                ' ("id","userId","contactId","subject","messages","updatedAt")'
                " VALUES (%s,%s,%s,%s,%s::jsonb,now())",
                (
                    thread_id,
                    user_id,
                    contact_id,
                    "Re: Delivery Lead role",
                    '[{"role":"received","body":"We have an opening"}]',
                ),
            )
        conn.commit()
    return thread_id


def test_send_real_when_gmail_connected(client, auth_headers, test_user_id, monkeypatch):
    repo = GmailAccountRepository()
    repo.upsert_account(
        test_user_id,
        account_email="me@gmail.com",
        refresh_token="refresh-xyz",
        scopes="gmail.send",
    )
    monkeypatch.setattr(
        "app.services.gmail_service.GmailService.send",
        lambda self, **kwargs: {"id": "gmail-msg-1", "threadId": "T1"},
    )
    try:
        thread_id = _seed_contact_thread(test_user_id, "recruiter@acme.com")
        resp = client.post(
            "/workspaces/emails/send",
            json={"message_id": thread_id, "body": "Thanks, happy to chat."},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "sent"
        assert data["gmailMessageId"] == "gmail-msg-1"
    finally:
        repo.disconnect(test_user_id)


def test_approved_send_attaches_pdfs_in_process(
    client, auth_headers, test_user_id, monkeypatch
):
    """An approved ``email_send`` resolves resume/CL PDFs in-process and hands
    them to Gmail as attachments. The approval card carries only ids (never the
    bytes), and a broken reference would fail before any send."""
    repo = GmailAccountRepository()
    repo.upsert_account(
        test_user_id,
        account_email="me@gmail.com",
        refresh_token="refresh-xyz",
        scopes="gmail.send",
    )
    captured: dict = {}

    def fake_send(self, **kwargs):
        captured.update(kwargs)
        return {"id": "gmail-msg-2", "threadId": "T2"}

    monkeypatch.setattr("app.services.gmail_service.GmailService.send", fake_send)
    # Stub the PDF resolution (real bytes come from the download handlers; here
    # we assert the wiring, not reportlab): only when a resume id is supplied.
    monkeypatch.setattr(
        "app.services.email_attachments.resolve_email_attachments",
        lambda current_user, *, resume_id=None, cover_letter_id=None: (
            [("resume-abc.pdf", b"%PDF-1.4 resume", "application/pdf")]
            if resume_id
            else []
        ),
    )
    try:
        run = client.post(
            "/agents/email/run",
            json={
                "mode": "send",
                "to": "recruiter@acme.com",
                "subject": "Application — Delivery Lead",
                "body": "Please find my resume attached.",
                "attach_resume_id": "res-123",
            },
            headers=auth_headers,
        )
        assert run.status_code == 200, run.text
        approval_id = run.json()["approval_id"]
        # The approval card stores only the id, never the PDF bytes.
        card = client.get(f"/approvals/{approval_id}", headers=auth_headers).json()
        assert card["payload"]["attach_resume_id"] == "res-123"

        assert (
            client.post(
                f"/approvals/{approval_id}/approve", headers=auth_headers
            ).status_code
            == 200
        )
        ex = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)
        assert ex.status_code == 200, ex.text
        assert ex.json()["gmailMessageId"] == "gmail-msg-2"
        # The resume PDF reached Gmail as an attachment tuple.
        assert captured["attachments"] == [
            ("resume-abc.pdf", b"%PDF-1.4 resume", "application/pdf")
        ]
    finally:
        repo.disconnect(test_user_id)


def test_inbox_reports_connected_account(client, auth_headers, test_user_id, monkeypatch):
    """Once connected, the inbox account bar flips to connected + the Google
    email, and a Gmail sync hiccup never 500s the inbox."""
    repo = GmailAccountRepository()
    repo.upsert_account(
        test_user_id,
        account_email="me@gmail.com",
        refresh_token="refresh-xyz",
        scopes="gmail.modify",
    )
    # Make the best-effort sync a no-op so the test needs no live Gmail.
    monkeypatch.setattr(
        "app.services.gmail_service.GmailService.sync_threads_to_db",
        lambda self, *a, **k: 0,
    )
    try:
        resp = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        account = resp.json()["accounts"][0]
        assert account["status"] == "connected"
        assert account["email"] == "me@gmail.com"
    finally:
        repo.disconnect(test_user_id)
