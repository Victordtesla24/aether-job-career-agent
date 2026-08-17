"""Approvals router — human-in-the-loop gateway (P2-S07)."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi import status as http_status
from pydantic import BaseModel, Field

from app.db import get_connection
from app.middleware.auth import CurrentUser
from app.repositories.admin import write_audit
from app.repositories.approval import ApprovalRepository
from app.services.approval_service import EXPIRY_HOURS, ApprovalService, _is_expired
from app.services.quality_gate import (
    acknowledgement_label_for,
    failing_labels,
    is_below_floor,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_STATUS_FILTERS = frozenset({"pending", "approved", "rejected", "all"})


def _client_ip(request: Request) -> str | None:
    """Best-effort caller IP for the decision audit trail (GOLD-MASTER-V2
    §15 Defect 1). Duplicated locally rather than imported from
    ``routers/admin.py`` to avoid a cross-router dependency on a private
    helper; behaviour intentionally mirrors it: behind Envoy->nginx the
    socket peer is nginx, so prefer the forwarded chain's first hop when
    present."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip() or None
    return request.client.host if request.client else None


def _write_decision_audit(
    user_id: str, action: str, decision: str, resolved: dict[str, Any]
) -> None:
    """Append the approve/reject audit row — MIRRORS the existing
    ``approval.delete`` / ``approval.purge_expired`` calls in this file
    (§13.1: reuse, don't reinvent). Closes GOLD-MASTER-V2 §15 Defect 1: the
    human approval gate's decisions must be as attributable as its
    housekeeping actions.
    """
    payload = ApprovalRepository._payload_dict(resolved)
    write_audit(
        user_id,
        action,
        target_type="approval",
        target_id=resolved["id"],
        detail={
            "decision": decision,
            "type": resolved.get("type"),
            "kind": payload.get("kind"),
            "job_id": payload.get("job_id"),
            "application_id": resolved.get("applicationId"),
            "edited": bool(payload.get("edited")),
            "trust_agent": payload.get("trust_agent"),
        },
    )


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
    #: U2c: the human's explicit "yes, I know it is below the quality floor"
    #: for an artifact whose gate verdict failed. Required to APPROVE such an
    #: artifact (never to reject one — refusing is the safe direction and must
    #: never be obstructed). Recorded on the payload so the decision stays
    #: attributable long after the request that carried it.
    acknowledge_below_floor: bool | None = None


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
    if body.acknowledge_below_floor is not None:
        extra["acknowledgedBelowFloor"] = body.acknowledge_below_floor
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


@router.post("/purge-expired")
def purge_expired_approvals(current_user: CurrentUser) -> dict[str, Any]:
    """Bulk-remove every EXPIRED pending approval in one request (FEAT-B1).

    Expiry is decided SERVER-SIDE in SQL with the same 48h window the service
    layer and the UI badge use (``approval_service.EXPIRY_HOURS`` — single
    source of truth): pending rows older than the window are hard-deleted;
    live pending and resolved rows are never touched. Returns an honest
    ``{"purged": 0, "ids": []}`` when nothing qualifies.
    """
    user_id = current_user["id"]
    ids = ApprovalRepository().purge_expired(user_id, EXPIRY_HOURS)
    if ids:
        write_audit(
            user_id,
            "approval.purge_expired",
            target_type="approval",
            detail={"purged": len(ids), "ids": ids, "expiry_hours": EXPIRY_HOURS},
        )
    return {"purged": len(ids), "ids": ids}


@router.get("/{approval_id}")
def get_approval(approval_id: str, current_user: CurrentUser) -> dict[str, Any]:
    return ApprovalService().get(approval_id, current_user["id"])


@router.delete("/{approval_id}")
def delete_approval(approval_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Remove one stale approval request (FEAT-B1). Hard delete per schema
    convention (no terminal "dismissed" enum state; offers/interviews/stories
    all hard-delete).

    - 404: unknown or foreign id — repeating a delete is idempotent-honest
      (second call finds nothing, changes nothing).
    - 409: a LIVE (non-expired) pending approval is still actionable; the
      human-in-the-loop gate cannot be bypassed by deleting the card —
      approve or reject it instead.
    - Deletable: expired-pending and resolved (approved/rejected) rows.
    """
    user_id = current_user["id"]
    approval = ApprovalService().get(approval_id, user_id)  # 404 if absent
    if approval["status"] == "pending" and not _is_expired(approval):
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "Approval is still pending and not expired — approve or reject it "
            "instead of removing it.",
        )
    deleted = ApprovalRepository().delete_by_id(approval_id, user_id)
    if deleted is None:  # raced with another delete — honest 404
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Approval not found")
    write_audit(
        user_id,
        "approval.delete",
        target_type="approval",
        target_id=approval_id,
        detail={
            "status": deleted["status"],
            "type": deleted["type"],
            "expired": _is_expired(deleted),
        },
    )
    return deleted


def _require_below_floor_acknowledgement(
    approval_id: str, user_id: str, body: DecisionBody | None
) -> None:
    """Refuse to APPROVE a below-floor artifact without an explicit yes (U2c).

    The verdict is READ off the approval's own payload — the object the
    tailoring / cover-letter agent stamped there when it produced the artifact.
    It is never recomputed here: a second computation is a second opinion, and
    the number the human is being asked to accept must be the number the run
    actually produced.

    An approval with no verdict (every one created before this gate existed) is
    approved unchanged: it was never judged, and inventing a failure for it
    would be as dishonest as hiding a real one.
    """
    approval = ApprovalRepository().get_by_id(approval_id, user_id)
    if approval is None or approval.get("status") != "pending":
        # Not this gate's business — the resolve below answers 404/409 with the
        # existing, well-tested semantics.
        return
    payload = ApprovalRepository._payload_dict(approval)
    gate = payload.get("qualityGate")
    if not is_below_floor(gate):
        return
    if body is not None and body.acknowledge_below_floor:
        return
    labels = failing_labels(gate)
    # ``is_below_floor`` already established ``gate`` is a dict whose ``passed``
    # is False — this restates it for the type checker without a cast, which
    # would assert the fact instead of checking it.
    summary = str((gate or {}).get("summary") or "").strip()
    raise HTTPException(
        http_status.HTTP_409_CONFLICT,
        (
            f"{summary} This artifact is below the quality floor on "
            f"{len(labels)} dimension(s) — {', '.join(labels)}. It has NOT "
            "been withheld: you can read it, edit it and approve it. But "
            "approving it has to be a deliberate choice, so re-send this "
            "decision with acknowledge_below_floor=true "
            f'("{acknowledgement_label_for(len(labels))}").'
        ),
    )


@router.post("/{approval_id}/approve")
def approve(
    approval_id: str,
    current_user: CurrentUser,
    request: Request,
    body: DecisionBody | None = None,
) -> dict[str, Any]:
    user_id = current_user["id"]
    # U2c: checked BEFORE the context merge and the resolve, so a refused
    # approval leaves the row exactly as it was — still pending, unedited.
    _require_below_floor_acknowledgement(approval_id, user_id, body)
    _merge_decision_context(approval_id, user_id, body)
    resolved = ApprovalService().resolve(
        approval_id, user_id, "approved", ip=_client_ip(request)
    )
    _write_decision_audit(user_id, "approval.approve", "approved", resolved)
    return resolved


@router.post("/{approval_id}/reject")
def reject(
    approval_id: str,
    current_user: CurrentUser,
    request: Request,
    body: DecisionBody | None = None,
) -> dict[str, Any]:
    user_id = current_user["id"]
    _merge_decision_context(approval_id, user_id, body)
    resolved = ApprovalService().resolve(
        approval_id, user_id, "rejected", ip=_client_ip(request)
    )
    _write_decision_audit(user_id, "approval.reject", "rejected", resolved)
    return resolved


@router.post("/{approval_id}/execute")
def execute_gated_action(approval_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Execute the high-risk action behind an approval.

    Blocked with 403 unless the approval is *approved*, and 409 if expired.
    The real side-effect is dispatched by ``type`` and, for
    ``application_submit``, by ``payload.kind``:

    * ``email_send`` -> :func:`_execute_email_send` (a real Gmail send);
    * ``application_submit`` with ``kind="submission"`` -> W-SUB: a REAL
      application email with the tailored résumé and cover letter attached
      (:func:`_execute_application_submit`);
    * ``application_submit`` with any other kind (``resume_tailor`` /
      ``cover_letter`` — the artifact-approval cards that share this enum
      type) -> the decision is recorded and NOTHING is transmitted, which the
      response now states explicitly (``transmitted: false`` plus the reason)
      instead of implying a submission that never happened. Before W-SUB this
      branch answered a bare ``{"status": "executed"}`` for EVERY
      ``application_submit`` approval while doing nothing at all — the
      response that made 133 never-executed approvals look actioned.
    """
    user_id = current_user["id"]
    approval = ApprovalService().assert_action_allowed(approval_id, user_id)
    # U5d-2 — the SITE-APPLY channel. Routed BEFORE the claim below, on purpose:
    # ``apply_executor.execute_site_application`` owns the execution claim
    # end-to-end (claim -> submit -> complete, or claim -> release on any
    # refusal), which is the same single-shot guard this router takes for the
    # email path. Claiming here as well would make the executor's own claim lose
    # to ours and report "already executed" for a submission that never
    # happened — a false terminal state on the single most consequential action
    # in the product. Exactly ONE layer claims per channel.
    if _is_site_apply_submission(approval):
        return _execute_site_submission(approval, current_user)
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
            sent = _execute_email_send(approval, current_user)
            # CRITICAL-4: the real side-effect returned. ``executedAt`` alone
            # was stamped BEFORE it ran and so could not distinguish a finished
            # send from a process killed mid-send — and nothing ever revisited
            # the row, so the second case read as executed forever while
            # nothing had been sent.
            repo.complete_execution(approval_id, user_id)
            return sent
        payload = ApprovalRepository._payload_dict(approval)
        if approval["type"] == "application_submit" and payload.get("kind") == "submission":
            submitted = _execute_application_submit(approval, current_user)
            repo.complete_execution(approval_id, user_id)
            return submitted
        # BLOCKER (v5 adversarial review): `claim_execution` stamps
        # ``executedAt = NOW()`` BEFORE any work happens, so reaching this
        # non-transmitting branch left the row reading "executed" while nothing
        # was sent — reintroducing the exact state this workstream existed to
        # remove (133 approvals stamped executed, 0 transmissions).
        #
        # ``executedAt`` means "the real side-effect fired", never "a decision
        # was recorded". Nothing was transmitted here, so the claim is released.
        # Releasing also keeps the approval retryable, which matters for an
        # ``application_submit`` that arrives without a submission payload: the
        # user can fix the payload and execute for real instead of finding it
        # permanently burnt.
        repo.release_execution(approval_id, user_id)
        is_submit = approval["type"] == "application_submit"
        return {
            "status": "recorded",
            "approval_id": approval["id"],
            "type": approval["type"],
            # HONEST: this branch approves an ARTIFACT (a tailored résumé, a
            # cover letter). It transmits nothing, and no longer lets the
            # caller infer that it did.
            "transmitted": False,
            "detail": (
                "Decision recorded. Nothing was transmitted — this approval "
                "request carries no submission payload, so there was nothing "
                "to send. Re-run the submission to generate one."
                if is_submit
                else "Decision recorded. Nothing was transmitted — this approval "
                "covers a document, not a submission."
            ),
        }
    except Exception:
        # The side-effect failed (e.g. Gmail not connected / send error). Release
        # the claim so the honest 4xx/5xx surfaces AND the user can retry once the
        # underlying problem is fixed — a failed attempt never burns the approval.
        repo.release_execution(approval_id, user_id)
        raise


def _is_site_apply_submission(approval: dict[str, Any]) -> bool:
    """Whether this approval is a U5d-2 SITE-APPLY card (not the email one).

    The discriminator is the payload's own shape, written by
    ``application_submission.queue_submission_approval``: an email card carries
    a ``recipient``, a site card carries a ``channel`` that is a member of
    ``AUTOMATABLE_CHANNELS``. Both conditions are required, so neither a legacy
    card (no ``channel`` key at all — 556 of them in production) nor a card
    naming a channel Aether refuses to drive can ever reach the browser path.
    """
    if approval.get("type") != "application_submit":
        return False
    payload = ApprovalRepository._payload_dict(approval)
    if payload.get("kind") != "submission" or payload.get("recipient"):
        return False
    from app.services.apply_channel_resolver import AUTOMATABLE_CHANNELS

    return str(payload.get("channel") or "") in AUTOMATABLE_CHANNELS


def _execute_site_submission(
    approval: dict[str, Any], current_user: dict[str, Any]
) -> dict[str, Any]:
    """U5d-2 — really apply on the employer's site, behind the approved gate.

    Delegates to ``apply_sweep._attempt_transmission`` — the EXISTING, tested
    seam the sweep uses — rather than adding a second implementation of channel
    resolution, form filling, evidence capture and manual-step recording. That
    function raises on every non-transmitting outcome, so the three honest
    endings are distinguishable here without inferring any of them:

    * it returns -> something was attempted AND the row is re-read for proof.
      ``transmitted: true`` is reported ONLY when ``Application."transmittedAt"``
      is really set; a return with no proof is reported as ``transmitted:
      false`` with an explicit reason, never as a success.
    * :class:`ManualStepRequired` -> HTTP 200 carrying the honest, persisted
      obstacle. Not an error: the user asked for an outcome and got a real one,
      and the card needs the reason to render it.
    * :class:`ApplyExecutorGuardError` -> its own 404/409. The approval is no
      longer ours to execute (already executed, or no longer approved).
    """
    from app.services.apply_executor import (
        ApplyExecutorGuardError,
        ApplyExecutorTransportError,
        ManualStepRequired,
    )
    from app.workers.apply_sweep import _attempt_transmission

    user_id = current_user["id"]
    payload = ApprovalRepository._payload_dict(approval)
    application_id = str(
        approval.get("applicationId") or payload.get("application_id") or ""
    )
    if not application_id:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            (
                "This approval names no application, so there was nothing to "
                "submit — nothing was sent."
            ),
        )
    channel = str(payload.get("channel") or "")
    try:
        _attempt_transmission(user_id, application_id, approval["id"])
    except ManualStepRequired as exc:
        return {
            "status": "manual_step",
            "approval_id": approval["id"],
            "applicationId": application_id,
            "channel": channel,
            "transmitted": False,
            "reason": exc.reason,
            "detail": getattr(exc, "question", None) or exc.message,
        }
    except ApplyExecutorGuardError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    except ApplyExecutorTransportError as exc:
        # Our side failed to open/drive the employer page — nothing was
        # submitted, the execution claim is released, and the sweep can retry.
        # An expected refusal, so an honest 502, never a stack-trace 500.
        raise HTTPException(http_status.HTTP_502_BAD_GATEWAY, exc.message) from exc
    proof = _transmission_proof(user_id, application_id)
    if proof.get("transmittedAt") is None:
        # Defensive and deliberately loud: the executor only returns after
        # ``_record_site_transmission`` stamped the row, so this cannot normally
        # happen — and if it ever does, the honest answer is "we cannot show you
        # evidence", never a success the database does not support.
        logger.warning(
            "u5d2: site submission for application %s returned without "
            "transmission proof — reporting transmitted=false",
            application_id,
        )
        return {
            "status": "unproven",
            "approval_id": approval["id"],
            "applicationId": application_id,
            "channel": channel,
            "transmitted": False,
            "reason": "no_transmission_proof",
            "detail": (
                "The submission path returned but recorded no transmission "
                "evidence, so Aether will not claim this was sent."
            ),
        }
    return {
        "status": "transmitted",
        "approval_id": approval["id"],
        "applicationId": application_id,
        "channel": channel,
        "transmitted": True,
        "transmittedAt": proof.get("transmittedAt"),
        "transmissionRef": proof.get("transmissionRef"),
        "detail": "Aether submitted this application on the employer's site.",
    }


def _transmission_proof(user_id: str, application_id: str) -> dict[str, Any]:
    """Re-read the evidence columns. The single source of the claim above."""
    from app.db import ensure_application_transmission_columns, rows_to_dicts

    ensure_application_transmission_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "transmittedAt", "transmissionRef", "transmissionChannel" '
                'FROM "Application" WHERE "id" = %s AND "userId" = %s',
                (application_id, user_id),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else {}


def _execute_application_submit(
    approval: dict[str, Any], current_user: dict[str, Any]
) -> dict[str, Any]:
    """W-SUB — REALLY submit the application behind an approved request.

    Builds the email, attaches the tailored résumé and the cover letter as
    genuine PDF bytes (rendered by the same in-process download handlers the
    user's own download buttons use), sends it through the single Gmail seam,
    records the transmission on the ``Application`` row and advances the stage.

    Every failure mode is an honest refusal with NOTHING sent:

    * 422 — the posting publishes no application address (so Aether cannot
      submit it; the user is told to apply on the employer's site), the
      application vanished, or no documents could be attached;
    * 409 — no Gmail account connected, or an expired grant;
    * 502 — Gmail accepted the request but failed to send.

    The caller's ``except`` releases the ``executedAt`` claim on all three, so
    a refusal never burns the approval and a fixed problem can be retried.
    """
    from app.services.application_submission import (
        SubmissionRefused,
        SubmissionTransportError,
        transmit_application,
    )

    try:
        return transmit_application(current_user, approval)
    except SubmissionRefused as exc:
        code = (
            http_status.HTTP_409_CONFLICT
            if exc.reason in {"no_email_provider_connected", "not_approved"}
            else http_status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(
            code, detail={"error": exc.reason, "message": exc.message}
        ) from None
    except SubmissionTransportError as exc:
        code = (
            http_status.HTTP_409_CONFLICT
            if exc.reason == "gmail_auth_failed"
            else http_status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            code, detail={"error": exc.reason, "message": exc.message}
        ) from None


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
    html_body = None
    if payload.get("kind") == "notification_digest":
        from app.services.email_branding import build_notification_digest_bodies

        html_body, _branded = build_notification_digest_bodies(subject, body)
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
            html_body=html_body,
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
