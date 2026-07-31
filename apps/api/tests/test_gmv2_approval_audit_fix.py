"""GOLD-MASTER-V2 §15 — approval decision audit gap + TOCTOU double-resolve.

Ground truth (uat/reports/evidence/gold-master-v2/adversarial/APPROVAL-AUDIT-INCIDENT.md):

Defect 1 (HIGH, governance): ``approve()``/``reject()`` in
``app/routers/approvals.py`` call ``ApprovalService().resolve(...)`` and write
NO ``AdminAuditLog`` row — the SAME file already calls ``write_audit()`` for
``approval.delete`` and ``approval.purge_expired``, so the facility exists and
is used twice in this very file, just never applied to the decision itself.
Zero ``approval.approve``/``approval.reject`` rows exist in production across
110 approvals.

Defect 2 (TOCTOU): ``ApprovalRepository._resolve()``'s UPDATE is
``WHERE "id" = %s`` only — no ``userId`` predicate, no ``status = 'pending'``
predicate. Two racing resolves (or a resolve reached with a stale/wrong
ownership context) can both succeed silently.

These tests are written FIRST and proven RED against the pre-fix code before
any production code changes (§15 step 2).
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
        user_id, "application_submit", {"kind": "gm2-audit-fix", "note": note}
    )


class TestApproveRejectAuditRows:
    def test_approve_writes_audit_row_naming_actor_target_decision(
        self, client, auth_headers, user_id, db_session
    ):
        approval = _create_approval(user_id)
        resp = client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "actorUserId", "targetType", "targetId", "detailJson" '
                'FROM "AdminAuditLog" WHERE "actorUserId" = %s AND "action" = %s',
                (user_id, "approval.approve"),
            )
            row = cur.fetchone()
        assert row is not None, "expected an approval.approve audit row — none written"
        actor, target_type, target_id, detail = row
        assert actor == user_id
        assert target_type == "approval"
        assert target_id == approval["id"]
        assert detail["decision"] == "approved"

    def test_reject_writes_audit_row_naming_actor_target_decision(
        self, client, auth_headers, user_id, db_session
    ):
        approval = _create_approval(user_id)
        resp = client.post(f"/approvals/{approval['id']}/reject", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "actorUserId", "targetType", "targetId", "detailJson" '
                'FROM "AdminAuditLog" WHERE "actorUserId" = %s AND "action" = %s',
                (user_id, "approval.reject"),
            )
            row = cur.fetchone()
        assert row is not None, "expected an approval.reject audit row — none written"
        actor, target_type, target_id, detail = row
        assert actor == user_id
        assert target_type == "approval"
        assert target_id == approval["id"]
        assert detail["decision"] == "rejected"

    def test_audit_row_shape_matches_delete_convention(
        self, client, auth_headers, user_id, db_session
    ):
        """The new approve/reject rows must use the SAME shape as the
        already-working ``approval.delete`` row (same helper, same columns
        populated) — not a bespoke, inconsistent audit format."""
        to_delete = _create_approval(user_id, "for delete convention")
        assert (
            client.post(
                f"/approvals/{to_delete['id']}/reject", headers=auth_headers
            ).status_code
            == 200
        )
        ApprovalRepository().backdate(to_delete["id"], hours=EXPIRY_HOURS + 1)
        assert (
            client.delete(f"/approvals/{to_delete['id']}", headers=auth_headers).status_code
            == 200
        )

        to_approve = _create_approval(user_id, "for approve audit")
        assert (
            client.post(
                f"/approvals/{to_approve['id']}/approve", headers=auth_headers
            ).status_code
            == 200
        )

        def _row(action: str, target_id: str):
            with db_session.cursor() as cur:
                cur.execute(
                    'SELECT "actorUserId", "targetType", "targetId", "detailJson" '
                    'FROM "AdminAuditLog" '
                    'WHERE "actorUserId" = %s AND "action" = %s AND "targetId" = %s',
                    (user_id, action, target_id),
                )
                return cur.fetchone()

        delete_row = _row("approval.delete", to_delete["id"])
        approve_row = _row("approval.approve", to_approve["id"])
        assert delete_row is not None, "baseline approval.delete row missing"
        assert approve_row is not None, "expected an approval.approve audit row — none written"
        assert delete_row[0] == approve_row[0] == user_id
        assert delete_row[1] == approve_row[1] == "approval"
        assert isinstance(delete_row[3], dict)
        assert isinstance(approve_row[3], dict)
        assert approve_row[2] == to_approve["id"]


class TestResolvedByUserIdPersisted:
    def test_resolved_by_user_id_persisted_and_readable(
        self, client, auth_headers, user_id
    ):
        approval = _create_approval(user_id)
        resp = client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json().get("resolvedByUserId") == user_id, (
            "resolvedByUserId must be persisted and returned by the approve "
            f"response; got {resp.json()!r}"
        )
        fetched = client.get(f"/approvals/{approval['id']}", headers=auth_headers)
        assert fetched.status_code == 200
        assert fetched.json().get("resolvedByUserId") == user_id, (
            "resolvedByUserId must be readable from GET /approvals/{id} after "
            f"resolve; got {fetched.json()!r}"
        )


class TestToctouWriteScoping:
    def test_repository_second_resolve_does_not_silently_succeed(
        self, auth_headers, user_id
    ):
        """Two resolves of the same approval (simulating a race that both
        passed the pending read) — the SECOND write must not silently
        succeed."""
        approval = _create_approval(user_id)
        repo = ApprovalRepository()
        first = repo.approve(approval["id"], user_id)
        assert first is not None and first["status"] == "approved"
        second = repo.approve(approval["id"], user_id)
        assert second is None, (
            "a second resolve of an already-resolved approval must not "
            "silently succeed a second time (TOCTOU close at the write, "
            "§15 Defect 2)"
        )

    def test_repository_write_is_owner_scoped(self, auth_headers, user_id):
        """The UPDATE itself must be owner-scoped, independent of any
        upstream (service-layer) ownership check."""
        approval = _create_approval(user_id)
        repo = ApprovalRepository()
        result = repo.approve(approval["id"], "not-the-real-owner-id")
        assert result is None, (
            "resolving with a mismatched userId must not succeed at the "
            "write layer, independent of any upstream ownership check"
        )
        still = repo.get_by_id(approval["id"], user_id)
        assert still is not None and still["status"] == "pending", (
            "the row must be untouched by the foreign-owner write attempt"
        )

    def test_service_stale_read_race_returns_honest_conflict_not_500(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """Simulates the losing side of a TOCTOU race: the DB row is already
        resolved by write-time, but this call's read (patched to return a
        stale snapshot) still believes it is pending. The WRITE — not the
        read — must be what makes this honest: 409, never a silent second
        resolve and never a 500/AssertionError."""
        approval = _create_approval(user_id)
        repo = ApprovalRepository()
        winner = repo.approve(approval["id"], user_id)
        assert winner is not None

        stale = dict(winner)
        stale["status"] = "pending"
        stale["resolvedAt"] = None
        monkeypatch.setattr(
            ApprovalRepository, "get_by_id", lambda self, aid, uid: dict(stale)
        )

        resp = client.post(f"/approvals/{approval['id']}/reject", headers=auth_headers)
        assert resp.status_code == 409, (
            "a losing racer must get an honest 409, not a silent second "
            f"resolve or a 500; got {resp.status_code} {resp.text}"
        )
