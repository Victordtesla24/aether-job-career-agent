"""Approvals router — human-in-the-loop gateway (P2-S07)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi import status as http_status
from pydantic import BaseModel, Field

from app.db import get_connection
from app.middleware.auth import CurrentUser
from app.repositories.approval import ApprovalRepository
from app.services.approval_service import ApprovalService

router = APIRouter()

_STATUS_FILTERS = frozenset({"pending", "approved", "rejected", "all"})


class CreateApprovalBody(BaseModel):
    """Body for creating a new approval request (POST /approvals)."""

    type: str = Field(
        ..., description="Approval type: application_submit, email_send, offer_response"
    )
    payload: dict[str, Any] = Field(
        ..., description="Arbitrary key-value payload for the approval card"
    )
    application_id: str | None = Field(default=None, max_length=50)


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


@router.post("", status_code=http_status.HTTP_201_CREATED)
def create_approval(
    body: CreateApprovalBody, current_user: CurrentUser
) -> dict[str, Any]:
    """Create a new approval request for human-in-the-loop gating.

    Supported types: application_submit, email_send, offer_response.
    Returns the created ApprovalRequest row.
    """
    return ApprovalRepository().create(
        user_id=current_user["id"],
        type_=body.type,
        payload=body.payload,
        application_id=body.application_id,
    )


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
    user_id = current_user["id"]
    approval = ApprovalService().assert_action_allowed(approval_id, user_id)
    # Idempotency guard (MV-approval-modal-010): atomically claim the approved
    # request so the side-effect (a real Gmail send) can fire AT MOST ONCE. A
    # double-submit/retry loses the claim and gets an honest 409 with no send.
    repo = ApprovalRepository()
    if not repo.claim_execution(approval_id, user_id):
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Approval already executed — no action taken.",
        )
    try:
        if approval["type"] == "email_send":
            return _execute_email_send(approval, current_user)
        return {"status": "executed", "approval_id": approval["id"], "type": approval["type"]}
    except Exception:
        # The side-effect failed (e.g. Gmail not connected / send error). Release
        # the claim so the honest 4xx/5xx surfaces AND the user can retry once the
        # underlying problem is fixed — a failed attempt never burns the approval.
        repo.release_execution(approval_id, user_id)
        raise


def _execute_email_send(
    approval: dict[str, Any], current_user: dict[str, Any]
) -> dict[str, Any]:
    """Send the Gmail message behind an approved ``email_send`` approval.

    The approval was created by the Email Agent (``mode=send``); executing it is
    the single point where a real outbound email leaves the system. Sending
    requires a connected Gmail account — absent one (or on an expired grant) it
    fails honestly with a 409 and no email is sent.
    """
    user_id = current_user["id"]
    payload = approval.get("payload") or {}
    to = payload.get("to")
    subject = payload.get("subject") or "(no subject)"
    body = payload.get("body") or ""
    if not to:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Approval payload is missing a recipient — cannot send.",
        )
    from app.repositories.gmail_account import GmailAccountRepository

    if not GmailAccountRepository().is_connected(user_id):
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            detail={
                "error": "no_email_provider_connected",
                "message": (
                    "No Gmail account connected — connect Gmail to send. "
                    "No email has been sent."
                ),
            },
        )
    # Resolve any resume / cover-letter PDFs to attach — in-process, from the
    # real download handlers. A dangling reference raises here (404/422) *before*
    # the send, so a broken attachment never yields a partial email.
    attachments = None
    resume_id = payload.get("attach_resume_id")
    cover_letter_id = payload.get("attach_cover_letter_id")
    if resume_id or cover_letter_id:
        from app.services.email_attachments import resolve_email_attachments

        try:
            attachments = resolve_email_attachments(
                current_user, resume_id=resume_id, cover_letter_id=cover_letter_id
            )
        except ValueError as exc:  # aggregate over Gmail's size cap
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
            ) from exc
    from app.services.gmail_service import (
        GmailAuthError,
        GmailError,
        GmailNotConnectedError,
        GmailService,
    )

    try:
        # ``thread_id`` (the Gmail threadId) is what actually threads the reply
        # into the existing conversation; ``in_reply_to`` sets the RFC In-Reply-To
        # header from the original Message-ID when the agent captured one.
        sent = GmailService(user_id).send(
            to=to,
            subject=subject,
            body=body,
            thread_id=payload.get("gmail_thread_id"),
            in_reply_to=payload.get("in_reply_to"),
            attachments=attachments,
        )
    except (GmailAuthError, GmailNotConnectedError):
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            detail={
                "error": "gmail_auth_failed",
                "message": (
                    "Gmail authorization expired — reconnect Gmail. "
                    "No email has been sent."
                ),
            },
        ) from None
    except GmailError:
        raise HTTPException(
            http_status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "gmail_send_failed",
                "message": (
                    "Gmail could not send the message right now — no email was "
                    "sent. Please try again."
                ),
            },
        ) from None
    return {
        "status": "sent",
        "approval_id": approval["id"],
        "type": approval["type"],
        "gmailMessageId": sent.get("id"),
    }
