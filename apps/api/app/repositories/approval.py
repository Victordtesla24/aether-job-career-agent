"""Approval repository — raw psycopg2 against ``ApprovalRequest`` (P2-S07)."""
from __future__ import annotations

import json
from typing import Any

from app.db import ensure_approval_columns, get_connection, new_id, rows_to_dicts

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
                # Idempotent per (job, type, kind): regenerating or refining an
                # artifact for the same job REFRESHES the existing PENDING request
                # (pointing it at the newest version) instead of stacking duplicate
                # cards in the approval queue. Resolved requests are history and
                # never reused. The ``kind`` scope keeps DISTINCT artifact families
                # that share the ``application_submit`` type from colliding — a
                # tailored-résumé approval (kind=resume_tailor) and a cover-letter
                # approval (kind=cover_letter) for the SAME job are independent
                # requests and must not overwrite each other (MV-resume-studio-001);
                # ``IS NOT DISTINCT FROM`` also matches a legacy kind-less request.
                job_id = payload.get("job_id")
                if job_id:
                    cur.execute(
                        f'''
                        UPDATE "ApprovalRequest"
                        SET "payload" = %s, "applicationId" = %s
                        WHERE "id" = (
                            SELECT "id" FROM "ApprovalRequest"
                            WHERE "userId" = %s AND "type" = %s::"ApprovalType"
                              AND "status" = 'pending'
                              AND "payload"->>'job_id' = %s
                              AND "payload"->>'kind' IS NOT DISTINCT FROM %s
                            ORDER BY "createdAt" DESC LIMIT 1
                        )
                        RETURNING {_COLUMNS}
                        ''',
                        (
                            json.dumps(payload), application_id, user_id, type_,
                            job_id, payload.get("kind"),
                        ),
                    )
                    rows = rows_to_dicts(cur)
                    if rows:
                        conn.commit()
                        return rows[0]
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

    def claim_execution(self, approval_id: str, user_id: str) -> bool:
        """Atomically claim an approved request for execution exactly once.

        Stamps ``executedAt`` only on the single pending→executed transition
        (``status = approved`` AND not yet executed). Returns ``True`` iff THIS
        call won the claim; a subsequent (concurrent or sequential) call returns
        ``False`` — already executed, or not approved — so the caller fires no
        side-effect and answers with an honest 409 (MV-approval-modal-010). The
        row-level lock the ``UPDATE`` takes serializes racing callers, so at most
        one ever observes a matching row.
        """
        ensure_approval_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    UPDATE "ApprovalRequest"
                    SET "executedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                      AND "status" = 'approved'::"ApprovalStatus"
                      AND "executedAt" IS NULL
                    RETURNING "id"
                    ''',
                    (approval_id, user_id),
                )
                claimed = cur.fetchone() is not None
            conn.commit()
        return claimed

    def release_execution(self, approval_id: str, user_id: str) -> None:
        """Release a claim so an approval stays retryable after an honest failure.

        Called when the side-effect behind a *claimed* execute raises (e.g. Gmail
        not connected, or a send/attachment error): clearing ``executedAt`` lets
        the user retry once the underlying problem is fixed. A *successful*
        execute keeps the stamp, so the real action can never fire twice.
        """
        ensure_approval_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "ApprovalRequest" SET "executedAt" = NULL '
                    'WHERE "id" = %s AND "userId" = %s',
                    (approval_id, user_id),
                )
            conn.commit()

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
                    self._sync_resume(cur, approval, user_id)
            conn.commit()
        return approval

    @staticmethod
    def _payload_dict(approval: dict[str, Any]) -> dict[str, Any]:
        """The approval's payload as a dict (jsonb comes back as a dict under the
        default psycopg2 cursor, but tolerate a JSON string defensively)."""
        payload = approval.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _sync_resume(
        cls, cur: Any, approval: dict[str, Any], user_id: str
    ) -> None:
        """Propagate a resume-tailor approval decision to the linked Résumé version.

        Runs on the caller's cursor so it commits atomically with the approval
        update (mirroring :meth:`_sync_application`). Approve → the tailored
        version becomes ``approved``; reject → ``rejected``. This is what makes the
        tailor approval gate REAL rather than decorative (MV-resume-studio-001): a
        tailored version created ``pending`` only becomes authoritative once a human
        signs off. Scoped by ``kind`` so it never touches an application/email/offer
        approval. A missing résumé (already deleted) is a harmless no-op.
        """
        payload = cls._payload_dict(approval)
        if payload.get("kind") != "resume_tailor":
            return
        resume_id = payload.get("resume_id")
        if not resume_id:
            return
        new_status = "approved" if approval["status"] == "approved" else "rejected"
        cur.execute(
            '''
            UPDATE "Resume"
            SET "approvalStatus" = %s, "updatedAt" = NOW()
            WHERE "id" = %s AND "userId" = %s
            ''',
            (new_status, resume_id, user_id),
        )

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

    def delete_by_id(self, approval_id: str, user_id: str) -> dict[str, Any] | None:
        """Hard-delete one approval, owner-scoped (FEAT-B1).

        Hard delete is the schema convention — the ``ApprovalStatus`` enum has
        no terminal "dismissed" state, and every other domain (offers,
        interviews, networking, stories) removes rows with
        ``DELETE … WHERE id AND userId``. Returns the deleted row, or ``None``
        when nothing matched (unknown/foreign id — the caller answers 404, so
        a repeated delete is idempotent-honest with no side effect).
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'DELETE FROM "ApprovalRequest" '
                    f'WHERE "id" = %s AND "userId" = %s RETURNING {_COLUMNS}',
                    (approval_id, user_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def purge_expired(self, user_id: str, expiry_hours: int) -> list[str]:
        """Bulk hard-delete every EXPIRED PENDING approval for ``user_id``.

        One statement, expiry evaluated SERVER-SIDE with the same window the
        service layer (and the UI's ``isExpired``) uses: a pending row whose
        ``createdAt`` is older than ``expiry_hours``. Resolved rows and live
        pending rows are never touched. Returns the deleted ids.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    DELETE FROM "ApprovalRequest"
                    WHERE "userId" = %s
                      AND "status" = 'pending'::"ApprovalStatus"
                      AND "createdAt" < NOW() - make_interval(hours => %s)
                    RETURNING "id"
                    ''',
                    (user_id, expiry_hours),
                )
                ids = [row[0] for row in cur.fetchall()]
            conn.commit()
        return ids

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
