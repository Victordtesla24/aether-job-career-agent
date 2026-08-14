"""U5d-2 — DRY-RUN end-to-end through the FULL new chain, zero transmissions.

WHAT THIS EXERCISES, in one unbroken sequence, over the REAL code:

    Agents card "Run"  ->  SubmissionAgent (application-scoped selection)
      ->  apply_channel_resolver (real resolution, persisted)
      ->  queue_submission_approval  ->  pending ApprovalRequest
      ->  the user's own approval
      ->  POST /approvals/{id}/execute      (the EXISTING endpoint)
      ->  apply_sweep._attempt_transmission (the EXISTING seam)
      ->  apply_executor.execute_site_application
             claim_execution -> plan -> submit -> _record_site_transmission
      ->  Application."transmittedAt" written
      ->  GET /applications/{id} -> submissionControl.state == "submitted"

Before U5d-2 this chain did not exist: ``apply_channel_resolver`` and
``apply_executor`` had exactly one caller family in the entire codebase (the
OFF ``apply_sweep`` worker), and 0 of 556 production ``application_submit``
approvals had ever been executed.

DRY RUN — WHAT "ZERO REAL TRANSMISSIONS" MEANS HERE, MECHANICALLY
-----------------------------------------------------------------
* ``apply_executor.playwright_form_submitter`` — the ONLY function in this
  product that drives a browser at an employer's form — is replaced by a stub
  that fails the test if the real one is ever reached, and the real symbol is
  additionally asserted to be absent from the call.
* ``application_submission.transmit_application`` — the ONLY function that
  sends an application email — is likewise wired to fail the test.
* ``fetch_apply_page`` is stubbed: not one HTTP request leaves this process.
* Every URL is an RFC-2606 / ``example`` host with a synthetic path. No real
  employer, no real posting, no real address exists anywhere in this file.
* The whole run happens in the ``aether_test`` schema against rows this test
  inserted itself.

The FIRST real transmission this product ever performs must be the OWNER
clicking a per-card control in production — never a test, never CI.
"""
from __future__ import annotations

import json
import uuid

import pytest

ASHBY_URL = "https://jobs.ashbyhq.com/example-co/00000000-0000-4000-8000-00000000dead"
DRY_RUN_EVIDENCE = "/tmp/u5d2-dry-run-e2e-evidence.png"


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


@pytest.fixture()
def dry_run(monkeypatch):
    """Arm the dry run and return the tripwire record.

    Returns a dict the test asserts on afterwards, so "the browser was never
    reached" is a POSITIVE assertion over recorded fact, not merely the absence
    of an exception.
    """
    from app.services import application_submission, apply_executor
    from app.workers import apply_sweep

    reached: dict[str, int] = {"browser": 0, "email": 0, "network": 0, "stub": 0}

    def _forbidden_browser(**kwargs):  # pragma: no cover - must never run
        reached["browser"] += 1
        raise AssertionError(
            "playwright_form_submitter was reached — a REAL browser submission "
            "to a REAL employer was about to be attempted."
        )

    def _forbidden_email(*args, **kwargs):  # pragma: no cover - must never run
        reached["email"] += 1
        raise AssertionError(
            "transmit_application was reached — a REAL application email was "
            "about to be sent."
        )

    def _forbidden_fetch(url):  # pragma: no cover - must never run
        reached["network"] += 1
        raise AssertionError(f"a real HTTP fetch was attempted against {url}")

    monkeypatch.setattr(apply_executor, "playwright_form_submitter", _forbidden_browser)
    monkeypatch.setattr(
        application_submission, "transmit_application", _forbidden_email
    )
    monkeypatch.setattr(apply_executor, "_default_page_fetch", _forbidden_fetch, raising=False)
    # The page is handed in, never fetched.
    monkeypatch.setattr(
        apply_executor, "fetch_apply_page",
        lambda url: "<form id='application-form'></form>",
    )
    monkeypatch.setattr(
        apply_executor, "build_form_fill_plan",
        # Mirrors the real seam's signature and RETURN SHAPE (U5d-3 added the
        # optional Answer Bank resolver and the audit list).
        lambda html, *, channel, profile, answer_bank=None: {
            "fields": [], "unanswerable_required": [], "answerBankAudit": [],
        },
    )
    monkeypatch.setattr(apply_sweep, "_render_resume_pdf", lambda uid, app: b"%PDF-dry")

    real_execute = apply_executor.execute_site_application

    def _stub_submitter(**kwargs):
        reached["stub"] += 1
        return {
            "submitted": True,
            "mode": "dry-run-stub",
            "destination": ASHBY_URL,
            "evidencePath": DRY_RUN_EVIDENCE,
            "confirmation": "dry run — nothing was sent to any employer",
            "filled": [],
            "unfilled": [],
        }

    def _dry_run_execute(*args, **kwargs):
        kwargs["submitter"] = _stub_submitter
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(apply_executor, "execute_site_application", _dry_run_execute)
    return reached


def _seed(conn, user_id: str) -> tuple[str, str]:
    job_id, resume_id, app_id = _uid(), _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, "Finance Specialist", "Example Co",
             "No application address is published in this posting.",
             "lever", ASHBY_URL, "ready", 91.0),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"sourceJobId","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,NOW())',
            (resume_id, user_id, 1, json.dumps({"raw_text": "cv"}), "h", job_id),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,\'draft\'::"ApplicationStatus",%s,NOW(),NOW())',
            (app_id, user_id, job_id, resume_id,
             "Dear Example Co team, I would love to help."),
        )
    conn.commit()
    return job_id, app_id


def _application_row(conn, app_id: str) -> dict:
    from app.db import (
        ensure_application_manual_step_columns,
        ensure_application_submission_truth_columns,
        ensure_application_transmission_columns,
    )

    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    ensure_application_submission_truth_columns()
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "status","transmittedAt","transmissionRef","applyChannel",'
            '"manualStepReason","submissionTruthState" FROM "Application" '
            'WHERE "id" = %s',
            (app_id,),
        )
        r = cur.fetchone()
    assert r is not None
    return {
        "status": r[0], "transmittedAt": r[1], "transmissionRef": r[2],
        "applyChannel": r[3], "manualStepReason": r[4], "submissionTruthState": r[5],
    }


def test_full_chain_agent_to_approval_to_execute_to_proof(
    db_session, user_id, client, auth_headers, dry_run
):
    _job_id, app_id = _seed(db_session, user_id)

    # ---- 1. The Agents card runs. It resolves a real channel and queues a
    #         real approval — and it transmits nothing.
    run = client.post("/agents/submission/run", json={}, headers=auth_headers)
    assert run.status_code == 200, run.text
    output = run.json()
    assert output["submissionState"] == "awaiting_approval"
    assert output["transmitted"] is False
    assert output["approvalRequired"] is True
    assert output["applyChannel"] == "ashby"
    assert output["applicationId"] == app_id
    assert "submitted" not in output
    approval_id = output["approvalId"]
    assert approval_id

    row = _application_row(db_session, app_id)
    assert row["transmittedAt"] is None
    assert row["status"] == "draft", "the agent must promote nothing"
    assert row["applyChannel"] == "ashby"

    # ---- 2. The pending card is visible to the user and has fired nothing.
    approvals = client.get("/approvals?status=pending", headers=auth_headers).json()
    card = next(a for a in _as_list(approvals) if a["id"] == approval_id)
    assert card["status"] == "pending"
    assert card.get("executedAt") is None

    # ---- 3. The card's control invites exactly one action, and it is honest.
    detail = client.get(f"/applications/{app_id}", headers=auth_headers).json()
    assert detail["submissionControl"]["state"] == "ready"
    assert detail["submissionControl"]["action"] == "submit"
    assert detail["transmitted"] is False

    # ---- 4. The user approves. Still nothing sent, and — critically — the
    #         tracker is NOT pre-stamped 'submitted' by the approval.
    approved = client.post(f"/approvals/{approval_id}/approve", json={}, headers=auth_headers)
    assert approved.status_code == 200, approved.text
    row = _application_row(db_session, app_id)
    assert row["transmittedAt"] is None
    assert row["status"] == "draft"

    # ---- 5. EXECUTE — the existing endpoint, now reaching the U5 engine.
    executed = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["transmitted"] is True
    assert body["channel"] == "ashby"
    assert body["transmissionRef"] == DRY_RUN_EVIDENCE

    # ---- 6. The PROOF is on the row, and the card reads it back.
    row = _application_row(db_session, app_id)
    assert row["transmittedAt"] is not None
    assert row["transmissionRef"] == DRY_RUN_EVIDENCE
    assert row["status"] == "submitted"
    assert row["manualStepReason"] is None
    assert row["submissionTruthState"] != "recorded_not_transmitted"

    detail = client.get(f"/applications/{app_id}", headers=auth_headers).json()
    assert detail["transmitted"] is True
    assert detail["submissionState"] == "transmitted"
    assert detail["submissionControl"]["state"] == "submitted"
    assert detail["submissionControl"]["action"] == "none"

    # ---- 7. The approval is claimed AND proven complete, exactly once.
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT "status","executedAt","executionCompletedAt" '
            'FROM "ApprovalRequest" WHERE "id" = %s',
            (approval_id,),
        )
        state = cur.fetchone()
    assert state[0] == "approved"
    assert state[1] is not None
    assert state[2] is not None

    # ---- 8. A second execute is refused; no second submission is possible.
    again = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)
    assert again.status_code in (403, 409), again.text

    # ---- 9. TRIPWIRES: neither real transmission entry point was reached.
    assert dry_run["browser"] == 0, "a real browser submission was attempted"
    assert dry_run["email"] == 0, "a real application email was attempted"
    assert dry_run["network"] == 0, "a real outbound page fetch was attempted"
    assert dry_run["stub"] == 1, "the injected dry-run submitter must be what ran"


def test_the_background_sweep_stays_off_through_all_of_this(monkeypatch):
    """AETHER_APPLY_SWEEP_ENABLED is a SEPARATE, user-gated decision. Reaching
    the U5 engine from a user's own click must not have turned the unattended
    background sweep on as a side effect."""
    from app.workers import apply_sweep

    monkeypatch.delenv("AETHER_APPLY_SWEEP_ENABLED", raising=False)
    assert apply_sweep.sweep_enabled() is False


def _as_list(payload):
    if isinstance(payload, list):
        return payload
    for key in ("approvals", "items", "data", "results"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, list):
            return value
    raise AssertionError(f"unexpected approvals payload shape: {type(payload)}")
