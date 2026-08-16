"""R4.1/R4.2 — LinkedIn Connections import (owner-provided export, zero network).

Covers, against the REAL test database:
* Connections.csv upload (with LinkedIn's real "Notes:" preamble) → deduped
  Contact rows (name/title/company/linkedinUrl), and rows whose connection
  chose to share an email become Sales leads with ratified
  ``existing_relationship`` consent provenance;
* the export .zip path opens ONLY Connections.csv (B7 bounded reader reused);
* suppressed emails are neither saved nor handed off;
* re-upload is idempotent (all duplicates, no new rows/leads);
* wrong file types are honest 422s; anonymous is 401;
* the endpoint makes zero network calls — it is pure upload parsing.
"""
from __future__ import annotations

import io
import uuid
import zipfile

from app.db import get_connection
from app.repositories.sales import SalesRepository


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _connections_csv(rows: list[str]) -> str:
    """A realistic Connections.csv: LinkedIn's Notes preamble + header + rows."""
    return (
        "Notes:\n"
        '"When exporting your connection data, you may notice that some of '
        'the email addresses are missing."\n'
        "\n"
        "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        + "\n".join(rows)
    )


def _upload(client, auth_headers, filename: str, payload: bytes):
    return client.post(
        "/networking/linkedin/import-contacts",
        headers=auth_headers,
        files={"file": (filename, payload, "application/octet-stream")},
    )


def test_csv_import_creates_deduped_contacts_and_hands_shared_emails_to_sales(
    client, auth_headers
):
    shared = _email("connection")
    csv_text = _connections_csv(
        [
            f"Casey,Connector,https://www.linkedin.com/in/casey,{shared},"
            "Acme Corp,Engineering Manager,12 Mar 2024",
            f"Casey,Connector,https://www.linkedin.com/in/casey,{shared},"
            "Acme Corp,Engineering Manager,12 Mar 2024",
            "Nia,NoEmail,https://www.linkedin.com/in/nia,,Beta Pty,Director,01 Jan 2023",
            ",,,,,,",
        ]
    )
    resp = _upload(client, auth_headers, "Connections.csv", csv_text.encode())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["rows"] == 4
    assert data["contactsCreated"] == 2   # Casey + Nia (email-less still a contact)
    assert data["leadsCreated"] == 1      # only the shared email becomes a lead
    assert data["duplicates"] == 1
    assert data["ignored"] == 1           # fully blank row

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "name","title","company","linkedinUrl" FROM "Contact" '
                'WHERE LOWER("email") = %s',
                (shared,),
            )
            row = cur.fetchone()
    assert row == (
        "Casey Connector", "Engineering Manager", "Acme Corp",
        "https://www.linkedin.com/in/casey",
    )

    lead = SalesRepository().get_lead_by_email(shared)
    assert lead is not None
    assert lead["source"] == "manual_approved"
    assert lead["consentType"] == "existing_relationship"
    assert "Connections.csv" in lead["consentEvidence"]
    assert "Casey Connector" in lead["consentEvidence"]

    # Idempotent re-upload: nothing new, everything a duplicate or ignored.
    again = _upload(client, auth_headers, "Connections.csv", csv_text.encode())
    assert again.status_code == 200
    d2 = again.json()
    assert d2["contactsCreated"] == 0
    assert d2["leadsCreated"] == 0
    assert d2["duplicates"] >= 2


def test_zip_import_opens_only_connections_csv(client, auth_headers):
    shared = _email("zipconn")
    csv_text = _connections_csv(
        [
            f"Zoe,Zipper,https://www.linkedin.com/in/zoe,{shared},"
            "Gamma Ltd,CTO,05 May 2025",
        ]
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Complete_LinkedInDataExport/Connections.csv", csv_text)
        zf.writestr("Complete_LinkedInDataExport/Ad_Targeting.csv", "should,never,open")
    resp = _upload(client, auth_headers, "export.zip", buf.getvalue())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["contactsCreated"] == 1
    assert data["leadsCreated"] == 1
    assert SalesRepository().get_lead_by_email(shared) is not None


def test_suppressed_email_is_neither_saved_nor_handed_off(client, auth_headers):
    suppressed = _email("optedout")
    SalesRepository().suppress(suppressed, reason="test opt-out")
    csv_text = _connections_csv(
        [
            f"Sam,Suppressed,https://www.linkedin.com/in/sam,{suppressed},"
            "Delta Inc,VP,02 Feb 2024",
        ]
    )
    resp = _upload(client, auth_headers, "Connections.csv", csv_text.encode())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["suppressed"] == 1
    assert data["contactsCreated"] == 0
    assert data["leadsCreated"] == 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM "Contact" WHERE LOWER("email") = %s',
                (suppressed,),
            )
            assert cur.fetchone()[0] == 0
    assert SalesRepository().get_lead_by_email(suppressed) is None


def test_wrong_file_types_are_honest_422(client, auth_headers):
    assert _upload(
        client, auth_headers, "Positions.csv", b"First Name\n"
    ).status_code == 422
    assert _upload(client, auth_headers, "resume.pdf", b"%PDF-").status_code == 422
    assert _upload(client, auth_headers, "export.zip", b"not a zip").status_code == 422
    # A zip without Connections.csv is honestly rejected too.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Profile.csv", "First Name,Last Name\nA,B")
    assert _upload(
        client, auth_headers, "export.zip", buf.getvalue()
    ).status_code == 422


def test_import_requires_authenticated_owner(client):
    resp = client.post(
        "/networking/linkedin/import-contacts",
        files={"file": ("Connections.csv", b"x", "text/csv")},
    )
    assert resp.status_code == 401


def test_import_path_makes_zero_network_calls(client, auth_headers, monkeypatch):
    """Hard rule: NO LinkedIn automation. Block sockets — import still works."""
    import socket

    def _blocked(*a, **k):  # pragma: no cover - trip wire
        raise AssertionError("network call attempted during LinkedIn import")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    shared = _email("offline")
    csv_text = _connections_csv(
        [
            f"Olive,Offline,https://www.linkedin.com/in/olive,{shared},"
            "Epsilon,Founder,03 Mar 2024",
        ]
    )
    resp = _upload(client, auth_headers, "Connections.csv", csv_text.encode())
    assert resp.status_code == 200, resp.text
    assert resp.json()["contactsCreated"] == 1
