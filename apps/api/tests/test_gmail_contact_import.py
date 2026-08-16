"""R4 Gmail professional-contact import.

The Gmail boundary is a fake: production code still owns parsing, persistence,
consent/suppression gates, and sales-lead handoff. No live inbox is contacted.
"""
from __future__ import annotations

import uuid

from app.db import get_connection
from app.repositories.sales import SalesRepository


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


class FakeGmail:
    def __init__(self, messages: list[dict[str, str]]) -> None:
        self.messages = messages
        self.calls: list[str] = []

    def list_message_headers(self, query=None, max_results=100):  # noqa: ANN001
        self.calls.append("headers")
        return [
            {
                "id": message["id"],
                "threadId": message["threadId"],
                "from": message["from"],
                "subject": message["subject"],
                "date": "",
            }
            for message in self.messages
        ]

    def get_message_bodies(self, message_id):  # noqa: ANN001
        self.calls.append(message_id)
        message = next(item for item in self.messages if item["id"] == message_id)
        return {
            **message,
            "date": "",
            "html": "",
        }


def _install_gmail(monkeypatch, fake: FakeGmail) -> None:
    monkeypatch.setattr(
        "app.services.gmail_service.GmailService",
        lambda *args, **kwargs: fake,
    )


def test_import_normalizes_deduplicates_and_hands_professional_contact_to_sales(
    client, auth_headers, monkeypatch
):
    sender = _email("recruiter")
    fake = FakeGmail(
        [
            {
                "id": "message-1",
                "threadId": "thread-1",
                "from": f"Riley Recruiter < {sender.upper()} >",
                "subject": "Senior platform engineering role",
                "text": "Hi, I recruit engineering leaders at Acme. Can we discuss this role?",
            },
            {
                "id": "message-2",
                "threadId": "thread-2",
                "from": f"Riley Recruiter <{sender}>",
                "subject": "Following up on the engineering role",
                "text": "I am the technical recruiter for Acme and would welcome a conversation.",
            },
            {
                "id": "message-3",
                "threadId": "thread-3",
                "from": "Newsletter <news@updates.example.com>",
                "subject": "Weekly roundup",
                "text": "Read this week's articles.",
            },
        ]
    )
    _install_gmail(monkeypatch, fake)

    response = client.post("/networking/gmail/import-contacts", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["contactsCreated"] == 1
    assert data["leadsCreated"] == 1
    assert data["duplicates"] == 1
    assert fake.calls == ["headers", "message-1", "message-2", "message-3"]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "name", "email" FROM "Contact" WHERE LOWER("email") = %s',
                (sender,),
            )
            imported = cur.fetchall()
    assert imported == [("Riley Recruiter", sender)]

    lead = SalesRepository().get_lead_by_email(sender)
    assert lead is not None
    assert lead["source"] == "inbound_email"
    assert lead["consentType"] == "inbound_signal"
    assert lead["sourceThreadId"] == "thread-1"
    assert "message-1" in lead["consentEvidence"]


def test_import_never_persists_or_hands_off_suppressed_sender(
    client, auth_headers, monkeypatch
):
    sender = _email("suppressed-recruiter")
    SalesRepository().suppress(sender, "user_opt_out")
    fake = FakeGmail(
        [
            {
                "id": "message-suppressed",
                "threadId": "thread-suppressed",
                "from": f"Jordan Hiring Manager <{sender}>",
                "subject": "Opportunity to discuss a director role",
                "text": "I lead hiring at Acme and would like to discuss this professional opportunity.",
            }
        ]
    )
    _install_gmail(monkeypatch, fake)

    response = client.post("/networking/gmail/import-contacts", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["suppressed"] == 1
    assert response.json()["contactsCreated"] == 0
    assert response.json()["leadsCreated"] == 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "Contact" WHERE LOWER("email") = %s', (sender,)
            )
            row = cur.fetchone()
            assert row is not None and row[0] == 0
    assert SalesRepository().get_lead_by_email(sender) is None


def test_import_requires_professional_inbound_signal_before_creating_contact_or_lead(
    client, auth_headers, monkeypatch
):
    sender = _email("personal")
    fake = FakeGmail(
        [
            {
                "id": "message-personal",
                "threadId": "thread-personal",
                "from": f"Alex <{sender}>",
                "subject": "Hello",
                "text": "Hope you are doing well. See you this weekend!",
            }
        ]
    )
    _install_gmail(monkeypatch, fake)

    response = client.post("/networking/gmail/import-contacts", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["ignored"] == 1
    assert response.json()["contactsCreated"] == 0
    assert response.json()["leadsCreated"] == 0
    assert SalesRepository().get_lead_by_email(sender) is None


def test_import_refuses_candidate_without_gmail_thread_provenance(
    client, auth_headers, monkeypatch
):
    sender = _email("no-provenance")
    fake = FakeGmail(
        [
            {
                "id": "message-no-thread",
                "threadId": "",
                "from": f"Morgan Recruiter <{sender}>",
                "subject": "Engineering opportunity",
                "text": "I am recruiting for a professional engineering position.",
            }
        ]
    )
    _install_gmail(monkeypatch, fake)

    response = client.post("/networking/gmail/import-contacts", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["ignored"] == 1
    assert response.json()["contactsCreated"] == 0
    assert response.json()["leadsCreated"] == 0
    assert SalesRepository().get_lead_by_email(sender) is None


def test_import_requires_authenticated_owner(client):
    response = client.post("/networking/gmail/import-contacts")
    assert response.status_code == 401


def test_import_without_gmail_connected_is_an_honest_409_not_a_500(
    client, auth_headers, monkeypatch
):
    """CLI-003 / F5-008: a user who has not connected Gmail must get the same
    honest 409 gmail_not_connected contract the send paths use — never a 500
    stack trace (live incident: POST /networking/gmail/import-contacts
    returned 500 when GmailService raised GmailNotConnectedError)."""
    from app.services.gmail_service import GmailNotConnectedError

    class DisconnectedGmail:
        def list_message_headers(self, query=None, max_results=100):  # noqa: ANN001
            raise GmailNotConnectedError(
                "Gmail is not connected — connect your account to continue."
            )

        def get_message_bodies(self, message_id):  # noqa: ANN001
            raise AssertionError("must not be reached")

    _install_gmail(monkeypatch, DisconnectedGmail())

    response = client.post("/networking/gmail/import-contacts", headers=auth_headers)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "gmail_not_connected"
    assert "connect" in detail["message"].lower()
    assert "Nothing was imported" in detail["message"]


def test_import_gmail_outage_is_502_not_500(client, auth_headers, monkeypatch):
    """F5-008: a transient Gmail failure maps to 502 with an honest message."""
    from app.services.gmail_service import GmailError

    class BrokenGmail:
        def list_message_headers(self, query=None, max_results=100):  # noqa: ANN001
            raise GmailError("backend unavailable")

    _install_gmail(monkeypatch, BrokenGmail())

    response = client.post("/networking/gmail/import-contacts", headers=auth_headers)

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["error"] == "gmail_unavailable"
