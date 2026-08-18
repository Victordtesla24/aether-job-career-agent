"""Networking CRM honesty, freshness, and agent hand-off.

These tests pin the defects the adversarial review found, then the fix:

* ``stats.responseRate`` must be null when nothing has been sent — never a
  fabricated 0 that the UI would render as ``0%``.
* Outreach ``subject`` is the first line of the stored message, not an
  invented ``Type — Company`` string.
* ``followUpsDueToday`` counts pending tasks scheduled for today in
  Australia/Melbourne — never a hardcoded 0.
* Re-import / upsert refreshes title/company/URL instead of counting a
  duplicate and leaving the row stale.
* ``POST /networking/refresh-from-inbox`` promotes already-synced career
  EmailThread senders into Contact rows and stamps ``contactId``.
* ``GET /analytics/networking`` is the Orchestrator snapshot (additive).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.db import new_id
from app.repositories.sales import SalesRepository
from app.services.gmail_service import (
    ensure_email_thread_gmail_columns,
    ensure_email_thread_last_message_column,
)

MELBOURNE = ZoneInfo("Australia/Melbourne")


def _summary(client, auth_headers):
    resp = client.get("/workspaces/networking/summary", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_response_rate_is_null_when_no_outreach_has_been_sent(client, auth_headers):
    """NET-HONEST-01: empty or pending-only CRM must not report 0% as a rate."""
    client.post("/networking/contacts", json={"name": "Ada"}, headers=auth_headers)
    data = _summary(client, auth_headers)
    assert data["stats"]["contacts"] == 1
    assert data["stats"]["responseRate"] is None


def test_response_rate_is_measured_from_terminal_outreach(client, auth_headers):
    """Accepted + declined over sent/accepted/declined/bounced — honest percent."""
    created = client.post(
        "/networking/contacts",
        json={"name": "Bea", "company": "Acme"},
        headers=auth_headers,
    )
    cid = created.json()["id"]
    for status in ("sent", "accepted"):
        task = client.post(
            "/networking/outreach",
            json={"contact_id": cid, "type": "message", "message": "Hello"},
            headers=auth_headers,
        )
        assert task.status_code == 201, task.text
        patched = client.patch(
            f"/networking/outreach/{task.json()['id']}",
            json={"status": status},
            headers=auth_headers,
        )
        assert patched.status_code == 200, patched.text
    data = _summary(client, auth_headers)
    assert data["stats"]["responseRate"] == 50


def test_outreach_subject_uses_stored_message_not_invented_type_company(
    client, auth_headers
):
    """NET-HONEST-04: the queue must surface the real draft, not a fake subject."""
    created = client.post(
        "/networking/contacts",
        json={"name": "Casey", "company": "Canva"},
        headers=auth_headers,
    )
    cid = created.json()["id"]
    client.post(
        "/networking/outreach",
        json={
            "contact_id": cid,
            "type": "follow_up",
            "message": "Let's catch up next week\nI have two times that work.",
        },
        headers=auth_headers,
    )
    data = _summary(client, auth_headers)
    assert data["outreachQueue"]
    assert data["outreachQueue"][0]["subject"] == "Let's catch up next week"
    assert "Follow Up — Canva" not in data["outreachQueue"][0]["subject"]


def test_follow_ups_due_today_counts_melbourne_scheduled_pending(
    client, auth_headers
):
    """NET-HONEST-02: followUpsDueToday is a real count, not a hardcoded 0."""
    created = client.post(
        "/networking/contacts", json={"name": "Dee"}, headers=auth_headers
    )
    cid = created.json()["id"]
    today = datetime.now(MELBOURNE).replace(hour=10, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    client.post(
        "/networking/outreach",
        json={
            "contact_id": cid,
            "type": "follow_up",
            "message": "Ping today",
            "scheduled_at": today.isoformat(),
        },
        headers=auth_headers,
    )
    client.post(
        "/networking/outreach",
        json={
            "contact_id": cid,
            "type": "follow_up",
            "message": "Ping tomorrow",
            "scheduled_at": tomorrow.isoformat(),
        },
        headers=auth_headers,
    )
    data = _summary(client, auth_headers)
    assert data["crmSummary"]["followUpsDueToday"] == 1


def test_linkedin_reimport_refreshes_stale_title_and_company(client, auth_headers):
    """Re-upload of Connections.csv must UPDATE title/company/URL, not skip."""
    shared = f"casey-{uuid.uuid4().hex[:10]}@example.com"
    first = (
        "Notes:\n\n"
        "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        f"Casey,Connector,https://www.linkedin.com/in/casey,{shared},"
        "Acme Corp,Engineering Manager,12 Mar 2024\n"
    )
    second = (
        "Notes:\n\n"
        "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        f"Casey,Connector,https://www.linkedin.com/in/casey,{shared},"
        "Acme Corp,Director of Engineering,12 Mar 2024\n"
    )
    r1 = client.post(
        "/networking/linkedin/import-contacts",
        headers=auth_headers,
        files={"file": ("Connections.csv", first.encode(), "text/csv")},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["contactsCreated"] == 1

    r2 = client.post(
        "/networking/linkedin/import-contacts",
        headers=auth_headers,
        files={"file": ("Connections.csv", second.encode(), "text/csv")},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["contactsCreated"] == 0
    assert body["contactsUpdated"] == 1
    assert body["leadsCreated"] == 0

    listed = client.get("/networking/contacts", headers=auth_headers).json()
    casey = next(c for c in listed if (c.get("email") or "").lower() == shared)
    assert casey["title"] == "Director of Engineering"


def test_refresh_from_inbox_upserts_career_senders_and_stamps_contact_id(
    client, auth_headers, test_user_id, db_session
):
    """Career EmailThread senders become contacts; personal mail is ignored."""
    ensure_email_thread_gmail_columns()
    ensure_email_thread_last_message_column()
    career_email = f"recruiter-{uuid.uuid4().hex[:8]}@acme.test"
    personal_email = f"mum-{uuid.uuid4().hex[:8]}@family.test"
    now = datetime.now(MELBOURNE)
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "EmailThread" '
            '("id","userId","subject","messages","classification",'
            ' "gmailThreadId","lastMessageAt","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)",
            (
                new_id(),
                test_user_id,
                "Senior platform engineering role",
                json.dumps(
                    [
                        {
                            "role": "received",
                            "from": f"Riley Recruiter <{career_email}>",
                            "fromEmail": career_email,
                            "body": "Can we discuss this engineering role?",
                        }
                    ]
                ),
                "priority",
                f"gm-{uuid.uuid4().hex[:12]}",
                now,
                now,
                now,
            ),
        )
        cur.execute(
            'INSERT INTO "EmailThread" '
            '("id","userId","subject","messages","classification",'
            ' "gmailThreadId","lastMessageAt","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)",
            (
                new_id(),
                test_user_id,
                "Dinner Sunday",
                json.dumps(
                    [
                        {
                            "role": "received",
                            "from": f"Mum <{personal_email}>",
                            "fromEmail": personal_email,
                            "body": "See you this weekend",
                        }
                    ]
                ),
                "personal",
                f"gm-{uuid.uuid4().hex[:12]}",
                now,
                now,
                now,
            ),
        )
    db_session.commit()

    resp = client.post("/networking/refresh-from-inbox", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["contactsCreated"] >= 1
    assert data["contactsUpdated"] >= 0

    listed = client.get("/networking/contacts", headers=auth_headers).json()
    emails = {(c.get("email") or "").lower() for c in listed}
    assert career_email in emails
    assert personal_email not in emails

    with db_session.cursor() as cur:
        cur.execute(
            'SELECT "contactId" FROM "EmailThread" '
            'WHERE "userId" = %s AND "classification" = %s',
            (test_user_id, "priority"),
        )
        row = cur.fetchone()
    assert row is not None and row[0]


def test_analytics_networking_snapshot_is_honest(client, auth_headers):
    """Orchestrator analytics surface — additive, no fabricated rates."""
    client.post(
        "/networking/contacts",
        json={"name": "Eve", "company": "Atlassian", "email": "eve@atlassian.test"},
        headers=auth_headers,
    )
    resp = client.get("/analytics/networking", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["contacts"] == 1
    assert data["responseRate"] is None
    assert "companies" in data
    assert "Atlassian" in data["companies"]
    assert "followUpsDueToday" in data
    assert "lastContactUpdatedAt" in data
    # Never dump PII into the orchestrator snapshot.
    blob = json.dumps(data)
    assert "eve@atlassian.test" not in blob


def test_network_snapshot_for_prompt_has_counts_not_emails():
    """Sales marketing prompts may cite counts/companies, never contact PII."""
    from app.services.networking_insights import network_snapshot_for_prompt

    text = network_snapshot_for_prompt("user-does-not-exist")
    assert "contacts:" in text.lower()
    assert "@" not in text


def test_network_snapshot_for_prompt_never_fabricates_zero_on_missing_user_id():
    """Honesty: missing user_id is 'not measured', never contacts: 0."""
    from app.services.networking_insights import network_snapshot_for_prompt

    text = network_snapshot_for_prompt(None)
    assert "not measured" in text
    assert "contacts: 0" not in text


def test_nurture_candidates_are_consented_contacts_only(client, auth_headers, test_user_id):
    """Sales nurture only sees existing_relationship / inbound_signal leads
    that also exist as this user's Contact rows."""
    from app.services.networking_insights import list_nurture_candidates

    shared = f"warm-{uuid.uuid4().hex[:8]}@acme.test"
    client.post(
        "/networking/contacts",
        json={"name": "Fay Connector", "email": shared, "company": "Acme"},
        headers=auth_headers,
    )
    SalesRepository().create_lead(
        email=shared,
        name="Fay Connector",
        source="manual_approved",
        consent_type="existing_relationship",
        consent_evidence="LinkedIn Connections.csv export uploaded by the account owner.",
    )
    rows = list_nurture_candidates(test_user_id, limit=5)
    emails = {r["email"] for r in rows}
    assert shared in emails
    assert all(
        r["consentType"] in ("existing_relationship", "inbound_signal") for r in rows
    )
