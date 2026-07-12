"""Approval repository — raw psycopg2 against ``ApprovalRequest`` (P2-S07)."""
from __future__ import annotations

import json
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

_COLUMNS = (
    '"id", "userId", "applicationId", "type", "status", "payload", '
    '"createdAt", "resolvedAt"'
)

VALID_TYPES = frozenset({"application_submit", "email_send", "offer_response"})


class ApprovalRepository:
    def create(
        self,
        user_id: str,
        type_: str,
        payload: dict[str, Any],
        application_id: str | None = None,
    ) -> dict[str, Any]:
        if type_ not in VALID_TYPES:
            raise ValueError(f"Invalid approval type '{type_}'")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "ApprovalRequest"
                        ("id", "userId", "applicationId", "type", "payload")
                    VALUES (%s, %s, %s, %s::"ApprovalType", %s)
                    RETURNING {_COLUMNS}
                    ''',
                    (new_id(), user_id, application_id, type_, json.dumps(payload)),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def get_by_id(self, approval_id: str, user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "ApprovalRequest" '
                    'WHERE "id" = %s AND "userId" = %s',
                    (approval_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def list_pending(self, user_id: str) -> list[dict[str, Any]]:
        return self._list(user_id, "pending")

    def list_by_user(self, user_id: str, status: str | None = None) -> list[dict[str, Any]]:
        return self._list(user_id, status)

    def _list(self, user_id: str, status: str | None) -> list[dict[str, Any]]:
        clauses = ['"userId" = %s']
        params: list[Any] = [user_id]
        if status is not None:
            clauses.append('"status" = %s::"ApprovalStatus"')
            params.append(status)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "ApprovalRequest" '
                    f'WHERE {" AND ".join(clauses)} ORDER BY "createdAt" DESC',
                    params,
                )
                return rows_to_dicts(cur)

    def approve(self, approval_id: str, user_id: str) -> dict[str, Any] | None:
        return self._resolve(approval_id, "approved", user_id)

    def reject(self, approval_id: str, user_id: str) -> dict[str, Any] | None:
        return self._resolve(approval_id, "rejected", user_id)

    def _resolve(
        self, approval_id: str, status: str, user_id: str
    ) -> dict[str, Any] | None:
        """Resolve an approval and sync its linked Application atomically.

        The approval status change and the ``Application`` propagation (defect
        D2) share a single transaction: committing the approval on its own left
        the tracked application stuck in ``draft`` whenever the follow-up write
        failed, so the approval became terminal (re-tries 409) while the kanban
        still showed ``draft``. Both writes now land together or not at all.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "ApprovalRequest"
                    SET "status" = %s::"ApprovalStatus", "resolvedAt" = NOW()
                    WHERE "id" = %s
                    RETURNING {_COLUMNS}
                    ''',
                    (status, approval_id),
                )
                rows = rows_to_dicts(cur)
                approval = rows[0] if rows else None
                if approval is not None:
                    self._sync_application(cur, approval, user_id)
            conn.commit()
        return approval

    @staticmethod
    def _sync_application(
        cur: Any, approval: dict[str, Any], user_id: str
    ) -> None:
        """Propagate an application_submit decision to the linked Application.

        Runs on the caller's cursor so it commits with the approval update.
        Approve → the application moves to ``submitted``; reject → ``rejected``
        (ADR D-0016). Only ``draft`` applications are touched so a decision can
        never regress an application that already advanced (e.g. to
        ``interview``).
        """
        if approval.get("type") != "application_submit":
            return
        application_id = approval.get("applicationId")
        if not application_id:
            return
        new_status = "submitted" if approval["status"] == "approved" else "rejected"
        cur.execute(
            '''
            UPDATE "Application"
            SET "status" = %s::"ApplicationStatus", "updatedAt" = NOW()
            WHERE "id" = %s AND "userId" = %s
              AND "status" = 'draft'::"ApplicationStatus"
            ''',
            (new_status, application_id, user_id),
        )

    def backdate(self, approval_id: str, hours: int) -> None:
        """Test/ops helper: shift ``createdAt`` into the past (expiry checks)."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "ApprovalRequest" '
                    'SET "createdAt" = NOW() - make_interval(hours => %s) '
                    'WHERE "id" = %s',
                    (hours, approval_id),
                )
            conn.commit()
