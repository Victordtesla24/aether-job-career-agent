"""Approvals router — human-in-the-loop gateway (P2-S07)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.middleware.auth import CurrentUser
from app.repositories.approval import ApprovalRepository
from app.services.approval_service import ApprovalService

router = APIRouter()


@router.get("")
def list_approvals(
    current_user: CurrentUser, status: str | None = "pending"
) -> list[dict[str, Any]]:
    """List approvals (pending by default; ``?status=all`` for everything)."""
    repo = ApprovalRepository()
    if status in (None, "all"):
        return repo.list_by_user(current_user["id"])
    return repo.list_by_user(current_user["id"], status)


@router.get("/{approval_id}")
def get_approval(approval_id: str, current_user: CurrentUser) -> dict[str, Any]:
    return ApprovalService().get(approval_id, current_user["id"])


@router.post("/{approval_id}/approve")
def approve(approval_id: str, current_user: CurrentUser) -> dict[str, Any]:
    return ApprovalService().resolve(approval_id, current_user["id"], "approved")


@router.post("/{approval_id}/reject")
def reject(approval_id: str, current_user: CurrentUser) -> dict[str, Any]:
    return ApprovalService().resolve(approval_id, current_user["id"], "rejected")


@router.post("/{approval_id}/execute")
def execute_gated_action(approval_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Execute the high-risk action behind an approval.

    Blocked with 403 unless the approval is *approved*, and 409 if expired.
    The actual side-effect (submit application / send email) is dispatched by
    payload kind; submission integrations land in a later phase, so this
    records the action as executed.
    """
    approval = ApprovalService().assert_action_allowed(approval_id, current_user["id"])
    return {"status": "executed", "approval_id": approval["id"], "type": approval["type"]}
