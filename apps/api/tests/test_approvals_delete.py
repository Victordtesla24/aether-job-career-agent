"""FEAT-B1 — Remove stale/expired approval requests (delete + bulk purge).

Convention check (design note DESIGN-W-B.md): the ApprovalStatus enum has no
terminal "dismissed" state and every other domain hard-deletes with
``DELETE … WHERE id AND userId`` — so removal is a hard delete. The bulk purge
uses the SAME 48h expiry source of truth as the UI
(``approval_service.EXPIRY_HOURS``), evaluated server-side in SQL.
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
        user_id, "application_submit", {"kind": "test-delete", "note": note}
    )


def _audit_rows(db_session, actor: str, action: str) -> list[tuple]:
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT "targetType", "targetId", "detailJson" FROM "AdminAuditLog" '
            'WHERE "actorUserId" = %s AND "action" = %s ORDER BY "createdAt" DESC',
            (actor, action),
        )
        return cur.fetchall()


class TestSingleDelete:
    def test_requires_auth(self, client):
        assert client.delete("/approvals/whatever").status_code == 401

    def test_unknown_id_404(self, client, auth_headers):
        resp = client.delete("/approvals/does-not-exist", headers=auth_headers)
        assert resp.status_code == 404

    def test_foreign_row_404_and_untouched(self, client, auth_headers, user_id):
        approval = _create_approval(user_id)
        other = {"email": "other-user@example.com", "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=other).status_code == 201
        token = client.post("/auth/login", json=other).json()["access_token"]
        other_headers = {"Authorization": f"Bearer {token}"}
        resp = client.delete(f"/approvals/{approval['id']}", headers=other_headers)
        assert resp.status_code == 404
        # The owner's row is untouched.
        still = client.get(f"/approvals/{approval['id']}", headers=auth_headers)
        assert still.status_code == 200

    def test_live_pending_is_409_still_actionable(self, client, auth_headers, user_id):
        """A non-expired pending approval is still actionable — deleting it must
        be refused with an honest 409 so the human-in-the-loop gate can't be
        silently bypassed."""
        approval = _create_approval(user_id)
        resp = client.delete(f"/approvals/{approval['id']}", headers=auth_headers)
        assert resp.status_code == 409
        # Row survives in the pending list — no zombie, no silent removal.
        listing = client.get("/approvals?status=pending", headers=auth_headers).json()
        assert any(a["id"] == approval["id"] for a in listing)

    def test_expired_pending_is_deletable(self, client, auth_headers, user_id):
        approval = _create_approval(user_id)
        ApprovalRepository().backdate(approval["id"], hours=EXPIRY_HOURS + 1)
        resp = client.delete(f"/approvals/{approval['id']}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == approval["id"]
        # Gone from every listing — no zombie rows.
        listing = client.get("/approvals?status=all", headers=auth_headers).json()
        assert all(a["id"] != approval["id"] for a in listing)
        assert (
            client.get(f"/approvals/{approval['id']}", headers=auth_headers).status_code
            == 404
        )

    def test_resolved_row_is_deletable_and_second_delete_404(
        self, client, auth_headers, user_id
    ):
        approval = _create_approval(user_id)
        assert (
            client.post(
                f"/approvals/{approval['id']}/reject", headers=auth_headers
            ).status_code
            == 200
        )
        first = client.delete(f"/approvals/{approval['id']}", headers=auth_headers)
        assert first.status_code == 200
        # Idempotent-honest: repeating the delete is a 404 with no side effect.
        second = client.delete(f"/approvals/{approval['id']}", headers=auth_headers)
        assert second.status_code == 404

    def test_delete_writes_audit_row(self, client, auth_headers, user_id, db_session):
        approval = _create_approval(user_id)
        client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        assert (
            client.delete(
                f"/approvals/{approval['id']}", headers=auth_headers
            ).status_code
            == 200
        )
        rows = _audit_rows(db_session, user_id, "approval.delete")
        assert rows, "expected an approval.delete audit row"
        target_type, target_id, detail = rows[0]
        assert target_type == "approval"
        assert target_id == approval["id"]
        assert detail["status"] == "approved"


class TestBulkPurgeExpired:
    def test_requires_auth(self, client):
        assert client.post("/approvals/purge-expired").status_code == 401

    def test_purges_only_expired_pending(self, client, auth_headers, user_id):
        repo = ApprovalRepository()
        expired_a = _create_approval(user_id, "expired A")
        repo.backdate(expired_a["id"], hours=EXPIRY_HOURS + 1)
        expired_b = _create_approval(user_id, "expired B")
        repo.backdate(expired_b["id"], hours=EXPIRY_HOURS + 12)
        fresh = _create_approval(user_id, "fresh pending")
        resolved_old = _create_approval(user_id, "resolved old")
        client.post(f"/approvals/{resolved_old['id']}/approve", headers=auth_headers)
        repo.backdate(resolved_old["id"], hours=EXPIRY_HOURS + 24)

        resp = client.post("/approvals/purge-expired", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["purged"] == 2
        assert set(body["ids"]) == {expired_a["id"], expired_b["id"]}

        # Non-expired pending and resolved rows are UNTOUCHED.
        remaining = {
            a["id"] for a in client.get("/approvals?status=all", headers=auth_headers).json()
        }
        assert fresh["id"] in remaining
        assert resolved_old["id"] in remaining
        assert expired_a["id"] not in remaining
        assert expired_b["id"] not in remaining

    def test_purge_with_nothing_expired_is_honest_zero(self, client, auth_headers, user_id):
        _create_approval(user_id, "fresh")
        resp = client.post("/approvals/purge-expired", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"purged": 0, "ids": []}

    def test_purge_is_user_scoped(self, client, auth_headers, user_id):
        repo = ApprovalRepository()
        mine = _create_approval(user_id, "mine expired")
        repo.backdate(mine["id"], hours=EXPIRY_HOURS + 1)
        other = {"email": "other-user@example.com", "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=other).status_code == 201
        token = client.post("/auth/login", json=other).json()["access_token"]
        resp = client.post(
            "/approvals/purge-expired", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["purged"] == 0
        # My expired row is still there for ME to purge.
        assert (
            client.get(f"/approvals/{mine['id']}", headers=auth_headers).status_code == 200
        )

    def test_purge_writes_audit_row(self, client, auth_headers, user_id, db_session):
        repo = ApprovalRepository()
        expired = _create_approval(user_id, "expired for audit")
        repo.backdate(expired["id"], hours=EXPIRY_HOURS + 2)
        assert (
            client.post("/approvals/purge-expired", headers=auth_headers).status_code
            == 200
        )
        rows = _audit_rows(db_session, user_id, "approval.purge_expired")
        assert rows, "expected an approval.purge_expired audit row"
        _, _, detail = rows[0]
        assert detail["purged"] == 1
        assert detail["ids"] == [expired["id"]]
