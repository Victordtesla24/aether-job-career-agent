"""AGT-APPROVE — approval modal API behavior (decision body, status validation).

Covers the additions behind the global approval modal:
- ``GET /approvals?status=<junk>`` answers 422, never 500.
- Approve/reject accept an optional body carrying the modal's edit + trust
  context, merged additively into the payload (auditable afterwards).
- Bodyless decisions stay backward-compatible.
- Resolved rows are immutable: late context merges are ignored.
"""
from __future__ import annotations

import pytest

from app.repositories.approval import ApprovalRepository


@pytest.fixture()
def user_id(client, auth_headers) -> str:
    res = client.get("/auth/me", headers=auth_headers)
    assert res.status_code == 200
    return res.json()["id"]


def _create(user_id: str, payload: dict | None = None) -> dict:
    return ApprovalRepository().create(
        user_id,
        "application_submit",
        payload or {"kind": "application_submit", "preview": "original letter"},
    )


class TestStatusFilterValidation:
    def test_valid_filters_ok(self, client, auth_headers):
        for status in ("pending", "approved", "rejected", "all"):
            resp = client.get(f"/approvals?status={status}", headers=auth_headers)
            assert resp.status_code == 200, (status, resp.text)

    def test_invalid_filter_is_422_not_500(self, client, auth_headers):
        resp = client.get("/approvals?status=bogus", headers=auth_headers)
        assert resp.status_code == 422
        assert "bogus" in resp.json()["detail"]


class TestDecisionContext:
    def test_bodyless_approve_still_works(self, client, auth_headers, user_id):
        approval = _create(user_id)
        resp = client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_edited_preview_is_persisted_on_approve(self, client, auth_headers, user_id):
        approval = _create(user_id)
        resp = client.post(
            f"/approvals/{approval['id']}/approve",
            json={"edited_preview": "human-edited letter"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        payload = resp.json()["payload"]
        assert payload["preview"] == "human-edited letter"
        assert payload["edited_preview"] == "human-edited letter"
        assert payload["edited"] is True

    def test_trust_agent_flag_is_persisted(self, client, auth_headers, user_id):
        approval = _create(user_id)
        resp = client.post(
            f"/approvals/{approval['id']}/approve",
            json={"trust_agent": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["payload"]["trust_agent"] is True

    def test_reject_accepts_context_too(self, client, auth_headers, user_id):
        approval = _create(user_id)
        resp = client.post(
            f"/approvals/{approval['id']}/reject",
            json={"trust_agent": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"
        assert body["payload"]["trust_agent"] is False

    def test_empty_body_merges_nothing(self, client, auth_headers, user_id):
        approval = _create(user_id)
        resp = client.post(
            f"/approvals/{approval['id']}/approve", json={}, headers=auth_headers
        )
        assert resp.status_code == 200
        payload = resp.json()["payload"]
        assert "edited" not in payload
        assert "trust_agent" not in payload
        assert payload["preview"] == "original letter"

    def test_resolved_rows_are_immutable(self, client, auth_headers, user_id):
        approval = _create(user_id)
        first = client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        assert first.status_code == 200
        # A second decision with context 409s AND must not rewrite the payload.
        second = client.post(
            f"/approvals/{approval['id']}/reject",
            json={"edited_preview": "tampered"},
            headers=auth_headers,
        )
        assert second.status_code == 409
        row = client.get(f"/approvals/{approval['id']}", headers=auth_headers).json()
        assert row["payload"]["preview"] == "original letter"

    def test_oversized_edit_is_422(self, client, auth_headers, user_id):
        approval = _create(user_id)
        resp = client.post(
            f"/approvals/{approval['id']}/approve",
            json={"edited_preview": "x" * 20_001},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_other_users_cannot_decide_with_context(self, client, auth_headers, user_id):
        approval = _create(user_id)
        other = {"email": "agtapprove-intruder@example.com", "password": "Sup3rSecret"}
        register = client.post("/auth/register", json=other)
        assert register.status_code in (201, 409)
        token = client.post("/auth/login", json=other).json()["access_token"]
        resp = client.post(
            f"/approvals/{approval['id']}/approve",
            json={"edited_preview": "hijack"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        row = client.get(f"/approvals/{approval['id']}", headers=auth_headers).json()
        assert row["status"] == "pending"
        assert row["payload"]["preview"] == "original letter"
