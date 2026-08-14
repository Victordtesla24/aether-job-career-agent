#!/usr/bin/env python3
"""U5d-2 — clean up the two QA/verify rows left in PRODUCTION (ops one-shot).

WHY THIS EXISTS. Two production ``Application`` rows are artefacts of Aether's
own verification activity, not of the owner's job search, and leaving them in
the tracker would corrupt the very counts this workstream exists to make
honest:

* ``cb9d9a5942d309855c7d64c65`` — a REAL application of the owner's that a
  verify probe advanced. It is reverted to the DRAFT state it was in before
  the probe touched it.
* ``c708fb1dfc227479e3175788c`` — created WHOLLY by the 09:56 verify probe. It
  is WITHDRAWN (the tracker's own terminal state for "this is not a live
  application"), so it stops being counted as one.

WHAT IT NEVER DOES
------------------
* **No ``Application`` is ever deleted, and this file issues no raw DELETE
  statement of any kind.** Row 2 leaves the active tracker through the
  product's own ``withdrawn`` status, exactly as a user withdrawing an
  application would; row 1 goes back to ``draft``. Status-event history is only
  ever appended to. The one thing that IS removed is an ARMED, never-executed
  ``ApprovalRequest`` the probe itself created — through the repository's own
  documented removal method, with an ``AdminAuditLog`` row naming this cleanup,
  because leaving a live authorisation to submit somebody's application behind
  is the more dangerous of the two options.
* **It never touches a row carrying transmission proof.** If ``transmittedAt``
  is set on either target, that is real evidence of a real submission and the
  script REFUSES and exits non-zero rather than reverting anything.
* **It writes no positive claim.** There is no code path here that can set
  ``transmittedAt``, ``transmissionRef`` or ``status='submitted'``.
* **It invents no history.** Every status change it makes is recorded as a real
  ``ApplicationStatusEvent`` with ``source = 'qa-cleanup'``, so the transition
  is attributable to this cleanup forever and is distinguishable from anything
  the owner did.

IDEMPOTENT. Each target's action is guarded on the state it is changing FROM,
so a second run reports "already clean" and writes nothing — including no
duplicate status event.

DRY RUN IS THE DEFAULT. Without ``--apply`` it performs SELECTs only and prints
exactly what it would change.

    cd apps/api && python3 ../../scripts/qa_cleanup_u5d2_test_rows.py
    cd apps/api && python3 ../../scripts/qa_cleanup_u5d2_test_rows.py --apply

``DATABASE_URL`` comes from ``os.environ`` only — never a literal in source,
never defaulted. An unset ``DATABASE_URL`` is refused.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

#: The real application a verify probe advanced — reverted to draft.
REVERT_TO_DRAFT_ID = "cb9d9a5942d309855c7d64c65"
#: The application the 09:56 verify probe created outright — withdrawn.
WITHDRAW_ID = "c708fb1dfc227479e3175788c"

#: Provenance stamped on every transition this script makes.
SOURCE = "qa-cleanup"


def _load_row(application_id: str) -> dict[str, Any] | None:
    from app.db import (
        ensure_application_manual_step_columns,
        ensure_application_submission_truth_columns,
        ensure_application_transmission_columns,
        get_connection,
        rows_to_dicts,
    )

    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    ensure_application_submission_truth_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id", "userId", "jobId", "status"::text AS "status", '
                '"transmittedAt", "manualStepReason", "submissionTruthState", '
                '"updatedAt" FROM "Application" WHERE "id" = %s',
                (application_id,),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def _open_approvals(user_id: str, application_id: str) -> list[str]:
    """Un-executed ``application_submit`` approvals still armed for this row."""
    from app.db import get_connection, rows_to_dicts

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''SELECT "id" FROM "ApprovalRequest"
                   WHERE "applicationId" = %s AND "userId" = %s
                     AND "type" = 'application_submit'::"ApprovalType"
                     AND "status" IN ('pending'::"ApprovalStatus",
                                      'approved'::"ApprovalStatus")
                     AND "executedAt" IS NULL''',
                (application_id, user_id),
            )
            return [str(r["id"]) for r in rows_to_dicts(cur)]


def _disarm_approvals(user_id: str, application_id: str, apply: bool) -> list[str]:
    """Remove any approval the probe left ARMED on this row — probe artefacts.

    An ``application_submit`` approval that is still ``pending``/``approved``
    with ``executedAt`` NULL is a live authorisation to submit this
    application. On these two rows every such card was created by the verify
    probe, so leaving one behind would leave a real submission armed by
    something that was never the owner's intent — and, for the revert target,
    "the state before the probe" is precisely "this card did not exist".

    ``ApprovalRepository.delete_by_id`` is the repository's OWN documented
    removal path — the same call ``DELETE /approvals/{id}`` makes, and the
    schema's only one, because ``ApprovalStatus`` has no terminal "dismissed"
    value (see that method's docstring). ``reject`` cannot be used for an
    already-APPROVED card: ``_resolve``'s compare-and-set requires
    ``status='pending'``, so it would silently match nothing and leave the card
    armed while reporting success.

    Attributability is preserved rather than destroyed: each removal writes an
    ``AdminAuditLog`` row through the SAME ``write_audit`` helper the Approvals
    router uses, naming this cleanup.

    An approval with ``executedAt`` SET is never touched. Its side-effect really
    happened, and rewriting or removing it would be a lie about the past.
    """
    ids = _open_approvals(user_id, application_id)
    if not ids or not apply:
        return ids
    from app.repositories.admin import write_audit
    from app.repositories.approval import ApprovalRepository

    repo = ApprovalRepository()
    for approval_id in ids:
        removed = repo.delete_by_id(approval_id, user_id)
        if removed is not None:
            write_audit(
                user_id,
                "approval.delete",
                target_type="approval",
                target_id=approval_id,
                detail={
                    "applicationId": application_id,
                    "reason": SOURCE,
                    "note": (
                        "verify-probe artefact removed by the U5d-2 QA cleanup; "
                        "it was never executed"
                    ),
                },
            )
    return ids


def _set_status(application_id: str, user_id: str, from_status: str, to_status: str) -> bool:
    """Guarded status write + a real status event. Returns whether it moved."""
    from app.db import get_connection
    from app.repositories.application_status_event import record_status_event

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''UPDATE "Application"
                   SET "status" = %s::"ApplicationStatus",
                       "manualStepReason" = NULL,
                       "manualStepDetail" = NULL,
                       "manualStepAt" = NULL,
                       "submissionTruthState" = NULL,
                       "submissionTruthAt" = NULL,
                       "updatedAt" = NOW()
                   WHERE "id" = %s AND "userId" = %s
                     AND "status" = %s::"ApplicationStatus"
                     AND "transmittedAt" IS NULL''',
                (to_status, application_id, user_id, from_status),
            )
            moved = cur.rowcount > 0
        conn.commit()
    if moved:
        record_status_event(application_id, from_status, to_status, SOURCE)
    return moved


def revert_to_draft(apply: bool) -> dict[str, Any]:
    """Target 1 — put the owner's own application back the way the probe found it."""
    row = _load_row(REVERT_TO_DRAFT_ID)
    if row is None:
        return {"id": REVERT_TO_DRAFT_ID, "action": "revert_to_draft", "result": "absent"}
    if row["transmittedAt"] is not None:
        return {
            "id": REVERT_TO_DRAFT_ID,
            "action": "revert_to_draft",
            "result": "REFUSED",
            "why": (
                "this row carries transmission evidence — it records a real "
                "submission and must not be reverted"
            ),
        }
    if row["status"] == "draft":
        # Already clean. Still disarm any approval left over, since an armed
        # approval on a draft is exactly what would re-run the probe's effect.
        armed = _disarm_approvals(str(row["userId"]), REVERT_TO_DRAFT_ID, apply)
        return {
            "id": REVERT_TO_DRAFT_ID,
            "action": "revert_to_draft",
            "result": "already-clean",
            "approvalsDisarmed": armed,
        }
    # Order matters: reject the approvals FIRST (a rejection moves a DRAFT row
    # to 'rejected', so doing it after the revert would undo the revert), then
    # move the row back to draft from whatever the probe left it in.
    armed = _disarm_approvals(str(row["userId"]), REVERT_TO_DRAFT_ID, apply)
    if not apply:
        return {
            "id": REVERT_TO_DRAFT_ID,
            "action": "revert_to_draft",
            "result": "would-revert",
            "from": row["status"],
            "approvalsWouldDisarm": armed,
        }
    current = _load_row(REVERT_TO_DRAFT_ID)
    assert current is not None
    moved = _set_status(
        REVERT_TO_DRAFT_ID, str(row["userId"]), str(current["status"]), "draft"
    )
    return {
        "id": REVERT_TO_DRAFT_ID,
        "action": "revert_to_draft",
        "result": "reverted" if moved else "no-change",
        "from": current["status"],
        "approvalsDisarmed": armed,
    }


def withdraw_probe_row(apply: bool) -> dict[str, Any]:
    """Target 2 — retire the row the probe created, without deleting anything."""
    row = _load_row(WITHDRAW_ID)
    if row is None:
        return {"id": WITHDRAW_ID, "action": "withdraw", "result": "absent"}
    if row["transmittedAt"] is not None:
        return {
            "id": WITHDRAW_ID,
            "action": "withdraw",
            "result": "REFUSED",
            "why": (
                "this row carries transmission evidence — a real application "
                "reached an employer and it must not be retired silently"
            ),
        }
    if row["status"] == "withdrawn":
        return {"id": WITHDRAW_ID, "action": "withdraw", "result": "already-clean"}
    armed = _disarm_approvals(str(row["userId"]), WITHDRAW_ID, apply)
    if not apply:
        return {
            "id": WITHDRAW_ID,
            "action": "withdraw",
            "result": "would-withdraw",
            "from": row["status"],
            "approvalsWouldDisarm": armed,
        }
    current = _load_row(WITHDRAW_ID)
    assert current is not None
    moved = _set_status(
        WITHDRAW_ID, str(row["userId"]), str(current["status"]), "withdrawn"
    )
    return {
        "id": WITHDRAW_ID,
        "action": "withdraw",
        "result": "withdrawn" if moved else "no-change",
        "from": current["status"],
        "approvalsDisarmed": armed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="U5d-2 QA test-row cleanup")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the cleanup (default: dry run, SELECT only)",
    )
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print(
            "REFUSING TO RUN: DATABASE_URL is not set. It is read from the "
            "environment only and is never defaulted.",
            file=sys.stderr,
        )
        return 2

    targets: list[dict[str, Any]] = [
        revert_to_draft(args.apply),
        withdraw_probe_row(args.apply),
    ]
    report: dict[str, Any] = {
        "mode": "apply" if args.apply else "dry-run",
        "source": SOURCE,
        "targets": targets,
    }
    print(json.dumps(report, indent=2, default=str))
    # A REFUSAL is an operator-visible failure, not a shrug: it means a target
    # carries transmission evidence and this cleanup must not proceed on it.
    return 1 if any(t.get("result") == "REFUSED" for t in targets) else 0


if __name__ == "__main__":
    raise SystemExit(main())
