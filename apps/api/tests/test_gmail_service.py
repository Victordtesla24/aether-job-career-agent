"""P4 — GmailService unit tests (google client fully mocked, no network).

The Gmail REST client is replaced with a MagicMock so we assert the service
builds the right requests and normalizes responses, without any live call.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.gmail_service import (
    GmailError,
    GmailNotConnectedError,
    GmailService,
    _decode_body,
    _split_address,
)


class _FakeCreds:
    """A credential repo returning nothing → not connected."""

    def get(self, user_id):
        return None

    def is_connected(self, user_id):
        return False


def _mock_client() -> MagicMock:
    return MagicMock()


# ------------------------------------------------------------------ helpers
def test_split_address_variants():
    assert _split_address("Sarah Chen <sarah@acme.com>") == ("Sarah Chen", "sarah@acme.com")
    assert _split_address("plain@acme.com") == ("plain@acme.com", "plain@acme.com")


def test_decode_body_walks_multipart():
    import base64

    text = "Hello from the recruiter"
    data = base64.urlsafe_b64encode(text.encode()).decode()
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": ""}},
            {"mimeType": "text/plain", "body": {"data": data}},
        ],
    }
    assert _decode_body(payload) == text


# ------------------------------------------------------------------ auth gate
def test_send_without_credential_raises_not_connected():
    svc = GmailService("u1", creds_repo=_FakeCreds())
    with pytest.raises(GmailNotConnectedError):
        svc.send(to="r@x.com", subject="Hi", body="Hello")


# ------------------------------------------------------------------ send
def test_send_builds_message_and_calls_api(monkeypatch):
    svc = GmailService("u1")
    mock = _mock_client()
    mock.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "m1",
        "threadId": "T1",
    }
    monkeypatch.setattr(svc, "_client", lambda: mock)

    result = svc.send(to="r@x.com", subject="Re: role", body="Thanks!", thread_id="T1")

    assert result == {"id": "m1", "threadId": "T1"}
    send_call = mock.users.return_value.messages.return_value.send
    _, kwargs = send_call.call_args
    assert kwargs["userId"] == "me"
    assert "raw" in kwargs["body"]
    assert kwargs["body"]["threadId"] == "T1"


def test_raw_message_attachment_size_guard():
    svc = GmailService("u1")
    huge = ("big.pdf", b"x" * (26 * 1024 * 1024), "application/pdf")
    with pytest.raises(GmailError):
        svc._raw_message("r@x.com", "Subject", "body", attachments=[huge])


# ------------------------------------------------------------------ read
def test_list_threads_normalizes(monkeypatch):
    import base64

    body = base64.urlsafe_b64encode(b"We have an opening").decode()
    full = {
        "id": "th1",
        "messages": [
            {
                "id": "msg1",
                "snippet": "We have an opening",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "body": {"data": body},
                    "headers": [
                        {"name": "Subject", "value": "Exciting role"},
                        {"name": "From", "value": "Sarah Chen <sarah@acme.com>"},
                        {"name": "Date", "value": "Mon, 14 Jul 2026 10:00:00 +0000"},
                    ],
                },
            }
        ],
    }
    svc = GmailService("u1")
    mock = _mock_client()
    mock.users.return_value.threads.return_value.list.return_value.execute.return_value = {
        "threads": [{"id": "th1"}]
    }
    mock.users.return_value.threads.return_value.get.return_value.execute.return_value = full
    monkeypatch.setattr(svc, "_client", lambda: mock)

    threads = svc.list_threads(max_results=5)
    assert len(threads) == 1
    t = threads[0]
    assert t["gmailThreadId"] == "th1"
    assert t["subject"] == "Exciting role"
    assert t["from"] == "Sarah Chen"
    assert t["fromEmail"] == "sarah@acme.com"
    assert t["body"] == "We have an opening"


def test_modify_labels_calls_api(monkeypatch):
    svc = GmailService("u1")
    mock = _mock_client()
    mock.users.return_value.messages.return_value.modify.return_value.execute.return_value = {
        "id": "m1"
    }
    monkeypatch.setattr(svc, "_client", lambda: mock)
    svc.modify_labels("m1", add=["Label_1"], remove=["INBOX"])
    _, kwargs = mock.users.return_value.messages.return_value.modify.call_args
    assert kwargs["body"] == {"addLabelIds": ["Label_1"], "removeLabelIds": ["INBOX"]}
