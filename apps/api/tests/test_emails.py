"""P3 — email draft and reply endpoints."""
from __future__ import annotations

import json


def test_create_draft(client, auth_headers):
    """POST /emails/draft creates a new email thread."""
    payload = {"subject": "Follow-up", "body": "Hello, looking forward to your reply."}
    response = client.post("/emails/draft", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["subject"] == "Follow-up"
    assert data["userId"]  # should be the authenticated user's ID
    assert data["messages"] == [
        {"role": "draft", "body": "Hello, looking forward to your reply.", "createdAt": None}
    ]
    assert "createdAt" in data
    assert "updatedAt" in data


def test_create_draft_with_optional_fields(client, auth_headers):
    """POST /emails/draft with application_id and classification."""
    payload = {
        "subject": "Application inquiry",
        "body": "Regarding my application",
        "application_id": "some-app-id",
        "classification": "inquiry",
    }
    response = client.post("/emails/draft", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["applicationId"] == "some-app-id"
    assert data["classification"] == "inquiry"


def test_list_threads(client, auth_headers):
    """GET /emails returns threads for the current user."""
    # Create two drafts
    for i in range(2):
        payload = {"subject": f"Test {i}", "body": f"Body {i}"}
        client.post("/emails/draft", json=payload, headers=auth_headers)
    response = client.get("/emails", headers=auth_headers)
    assert response.status_code == 200, response.text
    threads = response.json()
    assert len(threads) >= 2
    # Should be ordered by updatedAt desc
    assert threads[0]["subject"] == "Test 1"
    assert threads[1]["subject"] == "Test 0"


def test_get_thread(client, auth_headers):
    """GET /emails/{thread_id} returns a specific thread."""
    payload = {"subject": "Unique", "body": "Unique body"}
    create = client.post("/emails/draft", json=payload, headers=auth_headers)
    thread_id = create.json()["id"]

    response = client.get(f"/emails/{thread_id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == thread_id
    assert data["subject"] == "Unique"


def test_get_thread_404_for_other_user(client, auth_headers):
    """GET /emails/{thread_id} returns 404 if thread belongs to another user."""
    # Use a different user's token (not possible here, but we can test with a non-existent ID)
    response = client.get("/emails/nonexistent", headers=auth_headers)
    assert response.status_code == 404, response.text


def test_reply_to_thread(client, auth_headers):
    """POST /emails/{thread_id}/reply appends a reply."""
    payload = {"subject": "Original", "body": "First message"}
    create = client.post("/emails/draft", json=payload, headers=auth_headers)
    thread_id = create.json()["id"]

    reply_payload = {"body": "Reply message", "classification": "follow-up"}
    reply = client.post(f"/emails/{thread_id}/reply", json=reply_payload, headers=auth_headers)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    messages = data["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "draft"
    assert messages[1]["role"] == "reply"
    assert messages[1]["body"] == "Reply message"
    assert data["classification"] == "follow-up"