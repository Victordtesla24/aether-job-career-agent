"""Contract tests for the workspaces endpoints (GAP-P4-003)."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    """TestClient fixture with fresh app."""
    return TestClient(create_app())


def test_workspaces_interviews_prep_returns_200(client, auth_headers):
    """GET /workspaces/interviews/prep returns 200 with expected shape."""
    resp = client.get("/workspaces/interviews/prep", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "session" in data
    assert "compliance" in data
    assert "brief" in data
    assert "questions" in data
    assert "liveAssist" in data
    assert "debrief" in data


def test_workspaces_networking_summary_returns_200(client, auth_headers):
    """GET /workspaces/networking/summary returns 200 with expected shape."""
    resp = client.get("/workspaces/networking/summary", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "stats" in data
    assert "pipeline" in data
    assert "outreachQueue" in data
    assert "communicationLog" in data
    assert "crmSummary" in data


def test_workspaces_networking_summary_buckets_real_contacts_into_pipeline(client, auth_headers):
    """GET /workspaces/networking/summary must bucket real Contact rows into the
    5-column pipeline the frontend renders as Kanban cards (GAP-P4-052).

    Regression guard: the endpoint used to group contacts by the literal
    ``ContactStage`` enum values (identified/contacted/responded/meeting/referral)
    but then only ever read back the wireframe's stage labels
    (new/warm/active/scheduled/placed) when building ``pipeline`` — a total key
    mismatch that left every column at count 0 with no contact cards, even
    though ``stats.contacts`` correctly reported real rows in the DB.
    """
    stage_to_label = {
        "identified": "New",
        "contacted": "Warm",
        "responded": "Active",
        "meeting": "Scheduled",
        "referral": "Placed",
    }
    for db_stage in stage_to_label:
        payload = {"name": f"Contact {db_stage}", "company": "Acme", "stage": db_stage}
        resp = client.post("/networking/contacts", json=payload, headers=auth_headers)
        assert resp.status_code == 201, resp.text

    resp = client.get("/workspaces/networking/summary", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["stats"]["contacts"] == 5

    columns_by_label = {col["stage"]: col for col in data["pipeline"]}
    assert set(columns_by_label) == set(stage_to_label.values())
    for db_stage, label in stage_to_label.items():
        column = columns_by_label[label]
        assert column["count"] == 1, (
            f"{label} column should show the 1 real '{db_stage}' contact, "
            f"got count={column['count']}"
        )
        assert [c["name"] for c in column["contacts"]] == [f"Contact {db_stage}"]


def test_workspaces_emails_inbox_returns_200(client, auth_headers):
    """GET /workspaces/emails/inbox returns 200 with expected shape."""
    resp = client.get("/workspaces/emails/inbox", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "accounts" in data
    assert "stats" in data
    assert "followUps" in data
    assert "messages" in data
    assert "recruiterProfile" in data


def test_workspaces_offers_returns_200(client, auth_headers):
    """GET /workspaces/offers returns 200 with expected shape."""
    resp = client.get("/workspaces/offers", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "offers" in data
    assert "weights" in data
    assert "negotiation" in data


def test_workspaces_emails_send_requires_auth(client):
    """POST /workspaces/emails/send rejects unauthenticated requests."""
    resp = client.post("/workspaces/emails/send", json={"message_id": "123", "body": "test"})
    assert resp.status_code == 401


def test_workspaces_emails_send_no_provider_returns_409(
    client, auth_headers, test_user_id, db_session
):
    """POST /workspaces/emails/send must return an honest 409 when no email
    provider is connected — never a fabricated ``status=sent`` (GAP-P4-042,
    ADR D-0029). The thread must be left untouched (no message appended)."""
    import json as _json

    thread_id = "thread-fixc-042"
    original_messages = [{"role": "recruiter", "body": "Are you free for a call?"}]
    with db_session.cursor() as cur:
        # Deterministic seed: clear any leftover with this fixed id first so the
        # test is repeatable across invocations.
        cur.execute('DELETE FROM "EmailThread" WHERE id = %s', (thread_id,))
        cur.execute(
            'INSERT INTO "EmailThread" '
            '("id","userId","subject","messages","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s::jsonb, now(), now())",
            (thread_id, test_user_id, "Interview", _json.dumps(original_messages)),
        )
    db_session.commit()

    resp = client.post(
        "/workspaces/emails/send",
        headers=auth_headers,
        json={"message_id": thread_id, "body": "Yes, I am available."},
    )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body.get("status") != "sent"
    detail = body["detail"]
    assert detail["error"] == "no_email_provider_connected"
    assert detail["message"]  # honest, human-facing message present

    # No fabricated send: the stored thread must be byte-for-byte unchanged.
    with db_session.cursor() as cur:
        cur.execute('SELECT messages FROM "EmailThread" WHERE id = %s', (thread_id,))
        row = cur.fetchone()
    assert row is not None
    assert row[0] == original_messages


def test_workspaces_endpoints_require_auth(client):
    """All workspaces endpoints require authentication."""
    endpoints = [
        ("/workspaces/interviews/prep", "GET"),
        ("/workspaces/networking/summary", "GET"),
        ("/workspaces/emails/inbox", "GET"),
        ("/workspaces/offers", "GET"),
        ("/workspaces/offers", "POST"),
    ]
    for path, method in endpoints:
        if method == "GET":
            resp = client.get(path)
            assert resp.status_code == 401, f"{path} returned {resp.status_code} instead of 401"
        elif method == "POST":
            resp = client.post(path, json={})
            assert resp.status_code == 401, f"{path} returned {resp.status_code} instead of 401"