"""GOLD-MASTER-V2 §8.2 — approvals contract.

Ground truth (this run): ``DELETE /approvals/{approval_id}``
(app/routers/approvals.py:139) and ``POST /approvals/purge-expired`` (:112)
ALREADY EXIST and are believed to work — this file VERIFIES the contract, it
does NOT rebuild it (an equivalent, more exhaustive suite already lives in
test_approvals_delete.py; these are a smaller, self-contained set filed
alongside the W-F wave's failing PATCH-endpoint tests for evidence
completeness). The non-expired-protection assertion
(``test_purge_never_touches_a_live_pending_approval``) is the important one
per the brief.

Unlike the PATCH-endpoint file in this wave, these tests are expected to
PASS against current code — that is itself a valid, honestly-reported finding
(the endpoints are not broken), not a defect in the tests.
"""
from __future__ import annotations

import pytest

from app.repositories.approval import ApprovalRepository
from app.services.approval_service import EXPIRY_HOURS


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _create_approval(user_id: str, note: str = "gate me") -> dict:
    return ApprovalRepository().create(
        user_id, "application_submit", {"kind": "wf-contract-verify", "note": note}
    )


class TestDeleteOwnerScopedAndIdempotent:
    def test_delete_is_owner_scoped(self, client, auth_headers, user_id):
        approval = _create_approval(user_id)
        other = {"email": "wf-contract-other@example.com", "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=other).status_code == 201
        other_token = client.post("/auth/login", json=other).json()["access_token"]
        other_headers = {"Authorization": f"Bearer {other_token}"}

        # Not yet expired -> the OWNER would get a 409 ("still pending");
        # a FOREIGN caller must get an honest 404, never a 409 that would
        # leak the row's existence, and never a silent success.
        resp = client.delete(f"/approvals/{approval['id']}", headers=other_headers)
        assert resp.status_code == 404, resp.text
        # Row is untouched — the owner can still see it.
        still = client.get(f"/approvals/{approval['id']}", headers=auth_headers)
        assert still.status_code == 200

    def test_delete_is_idempotent_honest(self, client, auth_headers, user_id):
        approval = _create_approval(user_id)
        ApprovalRepository().backdate(approval["id"], hours=EXPIRY_HOURS + 1)
        first = client.delete(f"/approvals/{approval['id']}", headers=auth_headers)
        assert first.status_code == 200, first.text
        second = client.delete(f"/approvals/{approval['id']}", headers=auth_headers)
        assert second.status_code == 404, (
            "repeating a delete must be idempotent-honest: no zombie row, no "
            f"500, an honest 404; got {second.status_code} {second.text}"
        )

    def test_delete_is_audit_logged(self, client, auth_headers, user_id, db_session):
        approval = _create_approval(user_id)
        ApprovalRepository().backdate(approval["id"], hours=EXPIRY_HOURS + 1)
        assert client.delete(
            f"/approvals/{approval['id']}", headers=auth_headers
        ).status_code == 200
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "targetId" FROM "AdminAuditLog" WHERE "actorUserId" = %s '
                'AND "action" = %s',
                (user_id, "approval.delete"),
            )
            rows = cur.fetchall()
        assert any(r[0] == approval["id"] for r in rows), "expected an audit row"


class TestPurgeExpiredProtectsLivePending:
    def test_purge_never_touches_a_live_pending_approval(
        self, client, auth_headers, user_id
    ):
        """The important assertion per the brief: a non-expired pending
        approval — the human-in-the-loop gate — must survive purge-expired
        untouched, both in the response body and in a subsequent listing."""
        repo = ApprovalRepository()
        expired = _create_approval(user_id, "expired")
        repo.backdate(expired["id"], hours=EXPIRY_HOURS + 1)
        live_pending = _create_approval(user_id, "live and pending — must survive")

        resp = client.post("/approvals/purge-expired", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert live_pending["id"] not in body["ids"], (
            "purge-expired must never report a non-expired pending approval "
            f"as purged; got ids={body['ids']}"
        )

        still_there = client.get(
            f"/approvals/{live_pending['id']}", headers=auth_headers
        )
        assert still_there.status_code == 200
        assert still_there.json()["status"] == "pending"

    def test_purge_is_audit_logged_with_expiry_window(
        self, client, auth_headers, user_id, db_session
    ):
        repo = ApprovalRepository()
        expired = _create_approval(user_id, "expired for audit")
        repo.backdate(expired["id"], hours=EXPIRY_HOURS + 2)
        resp = client.post("/approvals/purge-expired", headers=auth_headers)
        assert resp.status_code == 200
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "detailJson" FROM "AdminAuditLog" WHERE "actorUserId" = %s '
                'AND "action" = %s ORDER BY "createdAt" DESC LIMIT 1',
                (user_id, "approval.purge_expired"),
            )
            row = cur.fetchone()
        assert row is not None, "expected an approval.purge_expired audit row"
        assert row[0]["expiry_hours"] == EXPIRY_HOURS
