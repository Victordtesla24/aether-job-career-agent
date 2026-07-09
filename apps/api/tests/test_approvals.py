"""P2-S07 — Approval gateway tests (state machine + expiry + gating)."""
from __future__ import annotations

import pytest

from app.repositories.approval import ApprovalRepository


@pytest.fixture()
def user_id(client, auth_headers) -> str:
    me = client.get("/jobs", headers=auth_headers)
    assert me.status_code == 200
    # Resolve the user id from the registered fixture user via the repository.
    from app.repositories.user import UserRepository

    user = UserRepository().get_by_email("fixture-user@example.com")
    assert user is not None
    return user["id"]


def _create_approval(user_id: str) -> dict:
    return ApprovalRepository().create(
        user_id, "application_submit", {"kind": "test", "note": "gate me"}
    )


class TestApprovalGateway:
    def test_approval_list_shows_pending(self, client, auth_headers, user_id):
        approval = _create_approval(user_id)
        listing = client.get("/approvals", headers=auth_headers).json()
        assert any(a["id"] == approval["id"] and a["status"] == "pending" for a in listing)

    def test_approve_transitions_status(self, client, auth_headers, user_id):
        approval = _create_approval(user_id)
        resp = client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        assert resp.json()["resolvedAt"] is not None
        # Terminal: cannot re-resolve.
        again = client.post(f"/approvals/{approval['id']}/reject", headers=auth_headers)
        assert again.status_code == 409

    def test_reject_transitions_status(self, client, auth_headers, user_id):
        approval = _create_approval(user_id)
        resp = client.post(f"/approvals/{approval['id']}/reject", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_high_risk_action_blocked_without_approval(self, client, auth_headers, user_id):
        approval = _create_approval(user_id)  # still pending
        resp = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert resp.status_code == 403

    def test_high_risk_action_allowed_after_approval(self, client, auth_headers, user_id):
        approval = _create_approval(user_id)
        client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        resp = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "executed"

    def test_approval_expiry_blocks_action(self, client, auth_headers, user_id):
        repo = ApprovalRepository()
        approval = _create_approval(user_id)
        repo.backdate(approval["id"], hours=49)  # past the 48h window
        # Resolving an expired approval is a conflict …
        resp = client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        assert resp.status_code == 409
        # … and the gated action stays blocked with 409 too.
        resp2 = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert resp2.status_code == 409

    def _seed_letter_approval(self, client, auth_headers) -> dict:
        """Full flow: scout a job → cover-letter run → draft app + approval."""
        run = client.post(
            "/agents/scout/run",
            json={"query": "python engineer", "location": "Sydney"},
            headers=auth_headers,
        )
        assert run.status_code == 202
        job = client.get("/jobs", headers=auth_headers).json()[0]
        resp = client.post(
            "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_approve_moves_linked_application_to_submitted(self, client, auth_headers):
        """D2 regression (Phase-2 audit, J4): approve must update the tracker."""
        body = self._seed_letter_approval(client, auth_headers)
        app_id = body["cover_letter_id"]  # letter is stored on the Application row
        before = client.get(f"/applications/{app_id}", headers=auth_headers).json()
        assert before["status"] == "draft"
        resp = client.post(f"/approvals/{body['approval_id']}/approve", headers=auth_headers)
        assert resp.status_code == 200
        after = client.get(f"/applications/{app_id}", headers=auth_headers).json()
        assert after["status"] == "submitted"

    def test_reject_moves_linked_application_to_rejected(self, client, auth_headers):
        """D2 regression (Phase-2 audit, J4): reject must update the tracker."""
        body = self._seed_letter_approval(client, auth_headers)
        app_id = body["cover_letter_id"]
        resp = client.post(f"/approvals/{body['approval_id']}/reject", headers=auth_headers)
        assert resp.status_code == 200
        after = client.get(f"/applications/{app_id}", headers=auth_headers).json()
        assert after["status"] == "rejected"

    def test_user_isolation(self, client, auth_headers, user_id):
        approval = _create_approval(user_id)
        other = {"email": "other-user@example.com", "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=other).status_code == 201
        token = client.post("/auth/login", json=other).json()["access_token"]
        other_headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/approvals/{approval['id']}", headers=other_headers)
        assert resp.status_code == 404
