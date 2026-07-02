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

    def approve(self, approval_id: str) -> dict[str, Any] | None:
        return self._resolve(approval_id, "approved")

    def reject(self, approval_id: str) -> dict[str, Any] | None:
        return self._resolve(approval_id, "rejected")

    def _resolve(self, approval_id: str, status: str) -> dict[str, Any] | None:
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
            conn.commit()
        return rows[0] if rows else None

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
