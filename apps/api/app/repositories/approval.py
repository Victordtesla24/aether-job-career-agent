"""Approval repository — raw psycopg2 against ``ApprovalRequest`` (P2-S07)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.db import ensure_approval_columns, get_connection, new_id, rows_to_dicts
from app.repositories.application_status_event import record_status_event_best_effort
from app.services.submission_snapshot import record_submission_snapshot

logger = logging.getLogger(__name__)

_COLUMNS = (
    '"id", "userId", "applicationId", "type", "status", "payload", '
    '"createdAt", "resolvedAt", "resolvedByUserId", "resolvedFromIp", '
    '"executedAt", "executionCompletedAt"'
)

VALID_TYPES = frozenset({"application_submit", "email_send", "offer_response"})

# ---------------------------------------------------------------------------
# CRITICAL-4 — execution claims that outlive the process that made them.
#
# ``claim_execution`` stamps ``executedAt = NOW()`` BEFORE the side-effect runs
# (an at-most-once guard so a double-submit cannot fire two real Gmail sends),
# and ``release_execution`` clears it if the side-effect raises. But an
# ``except`` only runs if the process is alive to run it: ``aether-api`` is
# restarted on every deploy and runs under ``Restart=on-failure``, and the
# claimed section performs multi-second network I/O (PDF rendering + a Gmail
# send). A restart or a kill inside that window left ``executedAt`` stamped
# with nothing sent, and NOTHING revisited the row — the same shape as the
# 8-day zombie AgentRun: state that survives every restart forever.
#
# ``executionCompletedAt`` splits the claim from the proof, so the three cases
# are finally distinguishable.
# ---------------------------------------------------------------------------

#: A claim was made and the owning request is still plausibly running.
EXECUTION_STATE_RUNNING = "running"
#: A claim was made, the ceiling has passed, and no completion was ever
#: recorded. The outcome is UNKNOWN — the process may have died before the
#: side-effect fired, or after it fired but before the stamp.
EXECUTION_STATE_INTERRUPTED = "interrupted"
#: The side-effect provably returned.
EXECUTION_STATE_EXECUTED = "executed"

#: Wall-clock ceiling (s) for one execute. Sized well above the real work: the
#: claimed section renders the résumé and cover-letter PDFs in-process and then
#: performs a Gmail upload, and it sits behind a synchronous HTTP request that
#: the reverse proxy itself will not hold open anywhere near this long. 10
#: minutes is generous enough that a live-but-slow send is never mislabelled.
_MAX_EXECUTION_SECONDS_DEFAULT = 600.0
#: Never below 5 minutes, whatever the environment says — a ceiling under the
#: real work would declare running executions interrupted, which is the exact
#: dishonesty this exists to remove, pointed the other way.
_MAX_EXECUTION_SECONDS_FLOOR = 300.0


def max_execution_seconds() -> float:
    """How long a claimed execution may run before it is presumed orphaned.

    ``AETHER_APPROVAL_MAX_EXECUTION_SECONDS`` tunes it without a redeploy;
    a malformed or too-small value is clamped to
    :data:`_MAX_EXECUTION_SECONDS_FLOOR` rather than taking a process down or
    mislabelling live work.
    """
    raw = (os.environ.get("AETHER_APPROVAL_MAX_EXECUTION_SECONDS") or "").strip()
    if not raw:
        return _MAX_EXECUTION_SECONDS_DEFAULT
    try:
        value = float(raw)
    except ValueError:
        return _MAX_EXECUTION_SECONDS_DEFAULT
    if value <= 0:
        return _MAX_EXECUTION_SECONDS_DEFAULT
    return max(value, _MAX_EXECUTION_SECONDS_FLOOR)


def execution_state(approval: dict[str, Any], now: datetime | None = None) -> str | None:
    """``None`` (never claimed), ``running``, ``interrupted`` or ``executed``.

    Pure and defensive: a row selected before these columns existed simply has
    no claim, which must degrade to ``None`` rather than raise into an
    approvals response.
    """
    claimed = approval.get("executedAt")
    if not isinstance(claimed, datetime):
        return None
    if isinstance(approval.get("executionCompletedAt"), datetime):
        return EXECUTION_STATE_EXECUTED
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    age = (now - claimed).total_seconds()
    return (
        EXECUTION_STATE_INTERRUPTED
        if age > max_execution_seconds()
        else EXECUTION_STATE_RUNNING
    )


def _with_execution_state(row: dict[str, Any]) -> dict[str, Any]:
    """Attach the derived ``executionState`` to a row leaving the repository.

    Read paths carry it so no consumer can present a claim whose owning
    process died as a completed action — the state is derived from the two
    stamps every time rather than cached anywhere it could go stale.
    """
    row["executionState"] = execution_state(row)
    return row


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
        ensure_approval_columns()
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
                # Same idempotency for a request that is NOT job-scoped: the
                # wave-4C outreach agents raise ``email_send`` requests scoped to a
                # CONTACT (first-touch outreach, a reference request) or to the
                # user themselves (a notification digest), where re-running the
                # agent must REFRESH the still-pending card with the newest draft
                # rather than stack duplicate pending sends to the same recipient.
                # ``dedupe_key`` is supplied by the caller
                # (``outreach_support.queue_email_approval``) and is scoped by
                # ``kind`` exactly like the job-scoped branch above. Purely
                # additive: no pre-existing payload carries ``dedupe_key``, so
                # every existing caller (including ``EmailAgent._send``, whose ad-hoc
                # sends legitimately stack) is byte-for-byte unchanged.
                dedupe_key = payload.get("dedupe_key")
                if dedupe_key:
                    cur.execute(
                        f'''
                        UPDATE "ApprovalRequest"
                        SET "payload" = %s, "applicationId" = %s
                        WHERE "id" = (
                            SELECT "id" FROM "ApprovalRequest"
                            WHERE "userId" = %s AND "type" = %s::"ApprovalType"
                              AND "status" = 'pending'
                              AND "payload"->>'dedupe_key' = %s
                              AND "payload"->>'kind' IS NOT DISTINCT FROM %s
                            ORDER BY "createdAt" DESC LIMIT 1
                        )
                        RETURNING {_COLUMNS}
                        ''',
                        (
                            json.dumps(payload), application_id, user_id, type_,
                            dedupe_key, payload.get("kind"),
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

    def complete_execution(self, approval_id: str, user_id: str) -> bool:
        """Record that the claimed side-effect PROVABLY finished (CRITICAL-4).

        Called only after the real action returned — the Gmail send, the
        application transmission. Until this lands, ``executedAt`` alone says
        no more than "somebody claimed this and may or may not still be
        running"; see :func:`execution_state`.

        Conditional on the claim existing (``executedAt IS NOT NULL``) so a
        completion can never precede or fabricate the claim that authorises
        it. Returns whether a row was stamped.
        """
        ensure_approval_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "ApprovalRequest" SET "executionCompletedAt" = NOW() '
                    'WHERE "id" = %s AND "userId" = %s AND "executedAt" IS NOT NULL '
                    'AND "executionCompletedAt" IS NULL RETURNING "id"',
                    (approval_id, user_id),
                )
                stamped = cur.fetchone() is not None
            conn.commit()
        return stamped

    def release_execution(self, approval_id: str, user_id: str) -> None:
        """Release a claim so an approval stays retryable after an honest failure.

        Called when the side-effect behind a *claimed* execute raises (e.g. Gmail
        not connected, or a send/attachment error): clearing ``executedAt`` lets
        the user retry once the underlying problem is fixed. A *successful*
        execute keeps the stamp, so the real action can never fire twice.

        Clears ``executionCompletedAt`` too, so a released row carries no
        residue of a previous attempt's proof (CRITICAL-4).
        """
        ensure_approval_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "ApprovalRequest" SET "executedAt" = NULL, '
                    '"executionCompletedAt" = NULL '
                    'WHERE "id" = %s AND "userId" = %s',
                    (approval_id, user_id),
                )
            conn.commit()

    def list_interrupted_executions(
        self, max_seconds: float | None = None
    ) -> list[dict[str, Any]]:
        """Claims whose owning process died before recording a completion.

        A row here means: ``executedAt`` was stamped more than
        :func:`max_execution_seconds` ago and no completion ever followed. The
        outcome is genuinely UNKNOWN — see :meth:`report_interrupted_executions`
        for why that is where this stops.

        The age filter runs on the DATABASE clock, not the app server's: the
        hosted Postgres runs measurably ahead (~3 s observed 2026-07-29) and a
        skewed comparison must not promote a live claim to orphaned.
        """
        ensure_approval_columns()
        ceiling = max_execution_seconds() if max_seconds is None else float(max_seconds)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS}, '
                    'EXTRACT(EPOCH FROM (NOW() - "executedAt")) AS "claimAgeSeconds" '
                    'FROM "ApprovalRequest" '
                    'WHERE "executedAt" IS NOT NULL '
                    'AND "executionCompletedAt" IS NULL '
                    'AND "executedAt" < NOW() - (%s || \' seconds\')::interval '
                    'ORDER BY "executedAt" ASC',
                    (str(ceiling),),
                )
                return rows_to_dicts(cur)

    def report_interrupted_executions(
        self, max_seconds: float | None = None
    ) -> dict[str, Any]:
        """Surface interrupted claims. **Deliberately does not release them.**

        WHY THERE IS NO AUTO-RETRY HERE. The only two ways to reach this state
        are (a) the process died before the side-effect fired, and (b) it died
        after Gmail accepted the message but before the completion stamp. Case
        (a) wants a retry; case (b) would send a SECOND real application email
        to a real employer. Nothing in this system can tell them apart — the
        Gmail send is the point at which the evidence is created, and that is
        precisely the window that was lost.

        So this reports, and a human who can look in their own Sent folder
        decides. Releasing on a guess would trade a visible unknown for an
        invisible duplicate, and duplicates land in a stranger's inbox with
        the user's name on them. Auto-retry is refused rather than
        half-implemented.
        """
        rows = self.list_interrupted_executions(max_seconds)
        for row in rows:
            logger.warning(
                "approval %s (type=%s user=%s): execution claimed %.1f min ago "
                "with no completion recorded — the process that owned it died. "
                "The outcome is UNKNOWN and the claim is deliberately NOT "
                "released: re-executing could send a second real message. "
                "Check the Sent folder before retrying.",
                row["id"], row["type"], row["userId"],
                float(row.get("claimAgeSeconds") or 0.0) / 60.0,
            )
        return {
            "interrupted": len(rows),
            "ids": [row["id"] for row in rows],
            "maxExecutionSeconds": (
                max_execution_seconds() if max_seconds is None else float(max_seconds)
            ),
        }

    def get_by_id(self, approval_id: str, user_id: str) -> dict[str, Any] | None:
        ensure_approval_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "ApprovalRequest" '
                    'WHERE "id" = %s AND "userId" = %s',
                    (approval_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return _with_execution_state(rows[0]) if rows else None

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
        ensure_approval_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "ApprovalRequest" '
                    f'WHERE {" AND ".join(clauses)} ORDER BY "createdAt" DESC',
                    params,
                )
                return [_with_execution_state(row) for row in rows_to_dicts(cur)]

    def approve(
        self, approval_id: str, user_id: str, ip: str | None = None
    ) -> dict[str, Any] | None:
        return self._resolve(approval_id, "approved", user_id, ip=ip)

    def reject(
        self, approval_id: str, user_id: str, ip: str | None = None
    ) -> dict[str, Any] | None:
        return self._resolve(approval_id, "rejected", user_id, ip=ip)

    def _resolve(
        self, approval_id: str, status: str, user_id: str, ip: str | None = None
    ) -> dict[str, Any] | None:
        """Resolve an approval and sync its linked Application atomically.

        The approval status change and the ``Application`` propagation (defect
        D2) share a single transaction: committing the approval on its own left
        the tracked application stuck in ``draft`` whenever the follow-up write
        failed, so the approval became terminal (re-tries 409) while the kanban
        still showed ``draft``. Both writes now land together or not at all.

        The UPDATE is a compare-and-set (GOLD-MASTER-V2 §15 Defect 2): the
        ``WHERE`` clause requires ``"userId" = %s AND "status" = 'pending'``,
        so it is owner-scoped and can transition a row at most once. Two
        racing resolves (or a call reached with a stale "pending" read) can no
        longer both succeed — the loser's ``UPDATE`` matches zero rows and this
        returns ``None``, which the caller (``ApprovalService.resolve``) turns
        into an honest 409 instead of a silent second resolve. Also stamps
        ``resolvedByUserId``/``resolvedFromIp`` so the decision is attributable
        on the row itself, independent of ``AdminAuditLog`` or access logs.
        """
        ensure_approval_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "ApprovalRequest"
                    SET "status" = %s::"ApprovalStatus", "resolvedAt" = NOW(),
                        "resolvedByUserId" = %s, "resolvedFromIp" = %s
                    WHERE "id" = %s AND "userId" = %s
                      AND "status" = 'pending'::"ApprovalStatus"
                    RETURNING {_COLUMNS}
                    ''',
                    (status, user_id, ip, approval_id, user_id),
                )
                rows = rows_to_dicts(cur)
                approval = rows[0] if rows else None
                transition: dict[str, Any] | None = None
                if approval is not None:
                    transition = self._sync_application(cur, approval, user_id)
                    self._sync_resume(cur, approval, user_id)
            conn.commit()
        if transition is not None:
            # U-AX: recorded only after the decision transaction committed, so
            # the history can never contain a transition that was rolled back.
            record_status_event_best_effort(
                str(transition["applicationId"]),
                str(transition["fromStatus"]),
                str(transition["toStatus"]),
                "approval.decide",
            )
            if transition["toStatus"] == "submitted" and transition["jobId"]:
                record_submission_snapshot(
                    user_id,
                    str(transition["applicationId"]),
                    str(transition["jobId"]),
                    str(transition["resumeId"]) if transition["resumeId"] else None,
                )
            if transition["toStatus"] == "submitted":
                # U5d-2 WRITE-TIME TRUTH MARKER. This promotion is bookkeeping:
                # an approval decision, not a transmission. Stamp that on the
                # row in the same request, so a claimed-submitted row with no
                # proof and no marker is a bug rather than an ambiguity the
                # U5d census has to interpret after the fact. Guarded on
                # ``transmittedAt IS NULL`` inside the helper, so a row that
                # already carries real evidence is never mislabelled.
                from app.services.submission_truth import (
                    mark_recorded_not_transmitted,
                )

                mark_recorded_not_transmitted(
                    user_id, str(transition["applicationId"])
                )
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
    ) -> dict[str, Any] | None:
        """Propagate an application_submit decision to the linked Application.

        Runs on the caller's cursor so it commits with the approval update.
        Approve → the application moves to ``submitted``; reject → ``rejected``
        (ADR D-0016). Only ``draft`` applications are touched so a decision can
        never regress an application that already advanced (e.g. to
        ``interview``).

        Returns the transition that ACTUALLY happened (or ``None`` when the
        compare-and-set matched no draft), so the caller can record the U-AX
        status event once the transaction has committed.
        """
        if approval.get("type") != "application_submit":
            return None
        application_id = approval.get("applicationId")
        if not application_id:
            return None
        new_status = "submitted" if approval["status"] == "approved" else "rejected"
        if new_status == "submitted":
            from app.services.application_submission import is_site_apply_payload

            if is_site_apply_payload(ApprovalRepository._payload_dict(approval)):
                # U5d-2. For a SITE-APPLY card, approving is AUTHORISATION to
                # attempt a submission — it is not evidence that one happened.
                # Promoting the tracker here would mint exactly the state this
                # workstream exists to remove (346 production rows reading
                # 'submitted' with no transmission proof), and it would do it
                # BEFORE the browser had even opened the page — so an attempt
                # that then hits a CAPTCHA would leave the user's board
                # asserting a submission that never occurred.
                #
                # The promotion for this card shape belongs to
                # ``apply_executor._record_site_transmission``, which writes
                # ``status='submitted'`` and ``transmittedAt`` in the SAME
                # statement: proof and claim, or neither.
                #
                # Narrow BY CONSTRUCTION: no pre-U5d-2 approval carries this
                # payload shape (0 of 556 in production), so every existing
                # card — including every W-SUB email card — is byte-for-byte
                # unchanged.
                return None
        cur.execute(
            '''
            UPDATE "Application"
            SET "status" = %s::"ApplicationStatus", "updatedAt" = NOW()
            WHERE "id" = %s AND "userId" = %s
              AND "status" = 'draft'::"ApplicationStatus"
            RETURNING "jobId", "resumeId"
            ''',
            (new_status, application_id, user_id),
        )
        moved = cur.fetchone()
        if moved is None:
            # The guard above matched no draft — the application had already
            # advanced, so nothing transitioned and nothing is recorded.
            return None
        # U-AX instrumentation is DEFERRED to the caller, to run after this
        # cursor's transaction commits: the status-event/snapshot writes open
        # their OWN connections, so recording them inline would publish a
        # transition that a rollback of this transaction could still undo.
        return {
            "applicationId": application_id,
            "fromStatus": "draft",
            "toStatus": new_status,
            "jobId": moved[0],
            "resumeId": moved[1],
        }

    def delete_by_id(self, approval_id: str, user_id: str) -> dict[str, Any] | None:
        """Hard-delete one approval, owner-scoped (FEAT-B1).

        Hard delete is the schema convention — the ``ApprovalStatus`` enum has
        no terminal "dismissed" state, and every other domain (offers,
        interviews, networking, stories) removes rows with
        ``DELETE … WHERE id AND userId``. Returns the deleted row, or ``None``
        when nothing matched (unknown/foreign id — the caller answers 404, so
        a repeated delete is idempotent-honest with no side effect).
        """
        ensure_approval_columns()
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
