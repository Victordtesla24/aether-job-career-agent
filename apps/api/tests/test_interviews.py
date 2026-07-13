"""GAP-P4-040 regression — POST /interviews must never 500.

Prior behaviour: ``application_id`` was declared optional in the Pydantic
request schema (``InterviewCreate``) while the ``InterviewSchedule.applicationId``
DB column is (and remains) ``NOT NULL``. Omitting the field let the request
past validation and crashed at the INSERT with an unhandled
``psycopg2.errors.NotNullViolation`` -> HTTP 500.

Fix: ``application_id`` is now a required field, so a missing value is
rejected at the validation layer with a 422 and never reaches the database.
"""
from __future__ import annotations


def test_create_interview_without_application_id_returns_422_not_500(
    client, auth_headers
):
    """Omitting application_id must be a clean 422, never a 500."""
    resp = client.post(
        "/interviews",
        json={
            "type": "video",
            "scheduled_at": "2026-08-01T15:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.status_code != 500


def test_create_interview_with_application_id_succeeds(client, auth_headers):
    """The documented-good path still works: 201 with the schedule persisted."""
    resp = client.post(
        "/interviews",
        json={
            "application_id": "app-does-not-need-to-exist-for-this-fk-less-table",
            "type": "video",
            "scheduled_at": "2026-08-01T15:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["application_id"] == "app-does-not-need-to-exist-for-this-fk-less-table"
    assert body["status"] == "scheduled"
