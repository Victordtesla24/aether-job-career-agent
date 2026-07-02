"""Approval gateway state machine (P2-S07).

State machine: ``pending → approved | rejected`` (terminal). Rules enforced:

- Only the owning user may see or act on an approval (user isolation is at
  the repository layer — every read is keyed by ``userId``).
- Resolved approvals cannot be re-resolved (409).
- Approvals expire after :data:`EXPIRY_HOURS`; acting on an expired approval
  returns 409 and the underlying high-risk action stays blocked.
- A high-risk action without an *approved*, unexpired approval is blocked
  with 403 (see :func:`assert_action_allowed`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status

from app.repositories.approval import ApprovalRepository

#: Approvals older than this are void — the user must re-trigger the agent.
EXPIRY_HOURS = 48


def _is_expired(approval: dict[str, Any]) -> bool:
    created = approval["createdAt"]
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created > timedelta(hours=EXPIRY_HOURS)


class ApprovalService:
    def __init__(self, repository: ApprovalRepository | None = None) -> None:
        self._repo = repository or ApprovalRepository()

    def get(self, approval_id: str, user_id: str) -> dict[str, Any]:
        approval = self._repo.get_by_id(approval_id, user_id)
        if approval is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found")
        return approval

    def list_pending(self, user_id: str) -> list[dict[str, Any]]:
        return self._repo.list_pending(user_id)

    def resolve(self, approval_id: str, user_id: str, decision: str) -> dict[str, Any]:
        approval = self.get(approval_id, user_id)
        if approval["status"] != "pending":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Approval already {approval['status']} — terminal state",
            )
        if _is_expired(approval):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Approval expired (> {EXPIRY_HOURS}h old); re-run the agent",
            )
        resolver = self._repo.approve if decision == "approved" else self._repo.reject
        resolved = resolver(approval_id)
        assert resolved is not None  # existence verified above
        return resolved

    def assert_action_allowed(self, approval_id: str, user_id: str) -> dict[str, Any]:
        """Gate a high-risk action: requires an approved, unexpired approval."""
        approval = self.get(approval_id, user_id)
        if _is_expired(approval):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Approval expired — action blocked",
            )
        if approval["status"] != "approved":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "High-risk action requires an approved approval request",
            )
        return approval
