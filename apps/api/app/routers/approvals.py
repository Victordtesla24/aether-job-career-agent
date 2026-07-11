"""Approvals router — human-in-the-loop gateway (P2-S07)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, status as http_status
from pydantic import BaseModel, Field

from app.db import get_connection
from app.middleware.auth import CurrentUser
from app.repositories.approval import ApprovalRepository
from app.services.approval_service import ApprovalService

router = APIRouter()

_STATUS_FILTERS = frozenset({"pending", "approved", "rejected", "all"})


class DecisionBody(BaseModel):
    """Optional context sent with an approve/reject decision.

    ``edited_preview`` carries the human-edited cover letter / message body
    from the modal's Edit & Approve flow; ``trust_agent`` records the "trust
    this agent for similar decisions" checkbox. Both are merged into the
    approval payload so the decision context is auditable afterwards.
    """

    edited_preview: str | None = Field(default=None, max_length=20_000)
    trust_agent: bool | None = None


def _merge_decision_context(
    approval_id: str, user_id: str, body: DecisionBody | None
) -> None:
    """Additively merge decision context into the payload of a pending row.

    Scoped to the owning user and to ``pending`` rows only, so a resolved
    approval's audit trail can never be rewritten. Runs before the resolve;
    if the resolve then fails (409 expired/terminal) the merged context is
    harmless extra metadata on a row that stays pending.
    """
    if body is None:
        return
    extra: dict[str, Any] = {}
    if body.edited_preview is not None:
        extra["preview"] = body.edited_preview
        extra["edited_preview"] = body.edited_preview
        extra["edited"] = True
    if body.trust_agent is not None:
        extra["trust_agent"] = body.trust_agent
    if not extra:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "ApprovalRequest" SET "payload" = "payload" || %s::jsonb '
                'WHERE "id" = %s AND "userId" = %s '
                'AND "status" = \'pending\'::"ApprovalStatus"',
                (json.dumps(extra), approval_id, user_id),
            )
        conn.commit()


@router.get("")
def list_approvals(
    current_user: CurrentUser, status: str | None = "pending"
) -> list[dict[str, Any]]:
    """List approvals (pending by default; ``?status=all`` for everything)."""
    if status is not None and status not in _STATUS_FILTERS:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid status filter '{status}' — expected one of {sorted(_STATUS_FILTERS)}",
        )
    repo = ApprovalRepository()
    if status in (None, "all"):
        return repo.list_by_user(current_user["id"])
    return repo.list_by_user(current_user["id"], status)


@router.get("/{approval_id}")
def get_approval(approval_id: str, current_user: CurrentUser) -> dict[str, Any]:
    return ApprovalService().get(approval_id, current_user["id"])


@router.post("/{approval_id}/approve")
def approve(
    approval_id: str, current_user: CurrentUser, body: DecisionBody | None = None
) -> dict[str, Any]:
    _merge_decision_context(approval_id, current_user["id"], body)
    return ApprovalService().resolve(approval_id, current_user["id"], "approved")


@router.post("/{approval_id}/reject")
def reject(
    approval_id: str, current_user: CurrentUser, body: DecisionBody | None = None
) -> dict[str, Any]:
    _merge_decision_context(approval_id, current_user["id"], body)
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
