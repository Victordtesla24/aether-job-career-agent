"""U5d — SUBMISSION TRUTH invariants (failing tests, written before the fix).

FORENSICS (production, 2026-08-14T07:35:45Z —
``uat/reports/evidence/agents-uplift/u5d/FORENSICS.md`` + ``CENSUS.json``):
346 production ``Application`` rows assert ``status='submitted'``; **0 of 606
rows in the entire database has ever carried a ``transmittedAt``**. All three
production Submission-Agent runs returned ``submitted: true`` and the sentence
*"Submitted your application for Project Finance Specialist at WSP USA."* while
performing **no write at all** (the target row's ``updatedAt`` never moved
across three runs) and while the backend they called returned the honest
sentence *"this application is recorded as prepared, not transmitted"*, which
the agent discarded. Slowest run: 0.611 s.

The four binding invariants pinned here:

1. **A submission/transmission claim requires transmission evidence.** A
   bookkeeping-only path (tracker write, no ``transmittedAt``) can NEVER
   produce a "submitted"/"transmitted" claim — asserted over the returned
   object, the persisted row AND the agent's source (no field or literal that
   could make a claim without reading ``Application."transmittedAt"``).
2. **The run record tells the truth about what the run did** — four DISTINCT
   states counted separately (transmitted N / assisted M / manual-step K /
   recorded-only J), plus a message that never says "Submitted" over a row
   whose ``transmittedAt`` is NULL.
3. **Existing false positives are remediated additively** — claimed-submitted
   rows with no proof are reclassified to an honest state through a
   migration-safe backfill that rewrites no ``status``, deletes no row and is
   idempotent; the count is reported.
4. **U5's safety contracts are preserved** — the ApprovalRequest gate still
   holds (nothing transmits without an approved card), the placeholder /
   fabrication guard still refuses a contaminated draft, and the apply sweep
   is still OFF by default.

SAFETY: no test in this file performs, simulates or approaches a real
submission to a real employer. Every transmission fact asserted here is
written directly into the test database by the test itself.
"""
from __future__ import annotations

import ast
import json
import re
import uuid
from pathlib import Path

import pytest


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(
    conn,
    user_id: str,
    *,
    description: str = "Build things. No application address is published here.",
    status: str = "ready",
) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, "Project Finance Specialist", "WSP USA", description,
             "lever", f"https://example.com/job/{job_id}", status, 90.0),
        )
    conn.commit()
    return job_id


def _seed_resume(conn, user_id: str, *, source_job_id: str | None, version: int = 1) -> str:
    resume_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"sourceJobId","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,NOW())',
            (resume_id, user_id, version, json.dumps({"raw_text": "cv"}), "h",
             source_job_id),
        )
    conn.commit()
    return resume_id


def _seed_application(
    conn,
    user_id: str,
    job_id: str,
    resume_id: str | None,
    *,
    status: str = "draft",
    cover_letter: str | None = "Dear team, I would love to help.",
    created_offset_minutes: int = 0,
) -> str:
    app_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,'
            "NOW() - (%s || ' minutes')::interval, NOW() - (%s || ' minutes')::interval)",
            (app_id, user_id, job_id, resume_id, status, cover_letter,
             created_offset_minutes, created_offset_minutes),
        )
    conn.commit()
    return app_id


def _application_row(conn, app_id: str) -> dict:
    from app.db import (
        ensure_application_manual_step_columns,
        ensure_application_transmission_columns,
    )

    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "id","status","updatedAt","transmittedAt","transmissionRef",'
            '"manualStepReason" FROM "Application" WHERE "id" = %s',
            (app_id,),
        )
        row = cur.fetchone()
    assert row is not None
    return {
        "id": row[0], "status": row[1], "updatedAt": row[2],
        "transmittedAt": row[3], "transmissionRef": row[4],
        "manualStepReason": row[5],
    }


def _run_agent(user_id: str, job_id: str | None = None):
    from app.agents.submission_agent import SubmissionAgent

    return SubmissionAgent().run(user_id, job_id=job_id)


# ---------------------------------------------------------------------------
# INVARIANT 1 — a submission claim requires transmission evidence
# ---------------------------------------------------------------------------


class TestNoClaimWithoutTransmissionEvidence:
    def test_bookkeeping_only_run_cannot_claim_submitted(
        self, db_session, user_id
    ):
        """THE pin. Tracker write, no published recipient, nothing sent ->
        the agent may not say "Submitted" and may not report transmitted."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        result = _run_agent(user_id)

        assert result.transmitted is False
        assert result.submissionState == "recorded_not_transmitted"
        assert result.applicationId == app_id
        # The word the production runs used, over a row that was never sent.
        assert "Submitted your application" not in result.message
        assert not re.search(r"\bsubmitted\b", result.message, re.I)
        assert "not transmitted" in result.message.lower()
        # …and the persisted row agrees: no evidence, therefore no claim.
        row = _application_row(db_session, app_id)
        assert row["transmittedAt"] is None
        assert row["status"] == "submitted"  # tracker bookkeeping is real

    def test_transmitted_claim_is_read_back_from_the_row_not_control_flow(
        self, db_session, user_id
    ):
        """The ONLY thing that can flip ``transmitted`` to True is a persisted
        ``transmittedAt`` — the identical code path returns False without it."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )
        from app.db import ensure_application_transmission_columns

        ensure_application_transmission_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "transmittedAt" = NOW(), '
                '"transmittedTo" = %s, "transmissionChannel" = %s, '
                '"transmissionRef" = %s WHERE "id" = %s',
                ("careers@example.com", "gmail", "msg-u5d-test", app_id),
            )
        db_session.commit()

        result = _run_agent(user_id, job_id=job_id)

        assert result.transmitted is True
        assert result.submissionState == "transmitted"
        assert result.transmissionRef == "msg-u5d-test"
        assert result.counts["transmitted"] == 1

    def test_agent_source_carries_no_unconditional_submitted_claim(self):
        """Source-level invariant (``test_u5_invariant_sweep`` style), over the
        PARSED module so prose in the docstrings cannot satisfy or break it:
        no ``submitted`` field, no ``submitted=`` keyword anywhere, and the
        evidence column really is read."""
        path = (
            Path(__file__).resolve().parents[1]
            / "app" / "agents" / "submission_agent.py"
        )
        tree = ast.parse(path.read_text())

        result_class = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "SubmissionResult"
        )
        fields = {
            stmt.target.id for stmt in result_class.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        }
        assert "submitted" not in fields, (
            "a field named 'submitted' cannot be honest on a path that "
            "transmits nothing — it was True on every run in production"
        )
        assert {"transmitted", "recorded", "submissionState"} <= fields

        keywords = {
            kw.arg for node in ast.walk(tree)
            if isinstance(node, ast.Call) for kw in node.keywords
        }
        assert "submitted" not in keywords

        assigned_attrs = {
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        assert "submitted" not in assigned_attrs
        # It must actually READ the evidence column.
        assert "transmittedAt" in path.read_text()


# ---------------------------------------------------------------------------
# INVARIANT 1 + 2 — the production regression, exactly as captured
# ---------------------------------------------------------------------------


class TestProductionRegression:
    def test_newest_row_wins_bug_no_longer_hides_the_ready_draft(
        self, db_session, user_id
    ):
        """PROD REPRO (`14-target-job-applications.txt`): one job, an OLDER
        ready draft plus a NEWER already-'submitted' row. Every run claimed
        *"Submitted your application …"* while writing nothing at all.

        The honest answer is "no change": the database reserves ONE active
        application per job, so the draft cannot be promoted while the
        submitted row holds the slot — and that submitted row has no
        transmission evidence, so nothing may claim it was sent."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        draft_id = _seed_application(
            db_session, user_id, job_id, resume_id, created_offset_minutes=60
        )
        newer_submitted_id = _seed_application(
            db_session, user_id, job_id, resume_id,
            status="submitted", created_offset_minutes=30,
        )
        draft_before = _application_row(db_session, draft_id)
        submitted_before = _application_row(db_session, newer_submitted_id)

        result = _run_agent(user_id)

        assert result.submissionState == "no_change"
        assert result.recorded is False
        assert result.transmitted is False
        assert result.applicationId == newer_submitted_id
        assert "Submitted your application" not in result.message
        assert not re.search(r"\bsubmitted\b", result.message, re.I)
        # BOTH rows are exactly as they were — the defect wrote nothing and
        # the fix must not start writing something to compensate.
        draft_after = _application_row(db_session, draft_id)
        submitted_after = _application_row(db_session, newer_submitted_id)
        assert draft_after["updatedAt"] == draft_before["updatedAt"]
        assert draft_after["status"] == "draft"
        assert submitted_after["updatedAt"] == submitted_before["updatedAt"]
        assert submitted_after["transmittedAt"] is None

    def test_already_recorded_run_reports_no_change_not_a_submission(
        self, db_session, user_id
    ):
        """An explicit job whose only application is already recorded: the
        honest answer is "no change", never a second claimed submission."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )
        before = _application_row(db_session, app_id)

        result = _run_agent(user_id, job_id=job_id)

        assert result.recorded is False
        assert result.transmitted is False
        assert result.submissionState == "no_change"
        assert "Submitted your application" not in result.message
        after = _application_row(db_session, app_id)
        assert after["updatedAt"] == before["updatedAt"]

    def test_backend_reason_is_propagated_not_discarded(self, db_session, user_id):
        """``outcome["submission"]["reason"]`` — the backend's own honest
        verdict — must reach the run record instead of being thrown away."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(db_session, user_id, job_id, resume_id)

        result = _run_agent(user_id)

        assert result.reason == "no_published_recipient"
        assert result.nextStep


# ---------------------------------------------------------------------------
# INVARIANT 2 — four distinct states, counted honestly
# ---------------------------------------------------------------------------


class TestRunRecordTellsTheTruth:
    def test_counts_are_four_distinct_states(self, db_session, user_id):
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(db_session, user_id, job_id, resume_id)

        result = _run_agent(user_id)

        assert set(result.counts) == {
            "transmitted", "assisted", "manualStep", "recordedOnly",
        }
        assert result.counts["recordedOnly"] == 1
        assert result.counts["transmitted"] == 0
        assert result.counts["assisted"] == 0
        assert result.counts["manualStep"] == 0

    def test_manual_step_row_is_reported_as_manual_step(self, db_session, user_id):
        """A row the executor already marked as needing a human step is an
        honest ACTIONABLE state — never "submitted", never "recorded only"."""
        from app.db import ensure_application_manual_step_columns

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )
        ensure_application_manual_step_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "manualStepReason" = %s, '
                '"manualStepDetail" = %s, "manualStepAt" = NOW() WHERE "id" = %s',
                ("captcha", "The employer's form requires a CAPTCHA.", app_id),
            )
        db_session.commit()

        result = _run_agent(user_id, job_id=job_id)

        assert result.transmitted is False
        assert result.submissionState == "manual_step_required"
        assert result.counts["manualStep"] == 1
        assert "captcha" in (result.reason or "")

    def test_no_ready_application_run_claims_nothing(self, db_session, user_id):
        result = _run_agent(user_id)

        assert result.transmitted is False
        assert result.recorded is False
        assert result.submissionState == "none"
        assert result.counts == {
            "transmitted": 0, "assisted": 0, "manualStep": 0, "recordedOnly": 0,
        }

    def test_catalog_card_copy_does_not_promise_a_submission(
        self, client, auth_headers
    ):
        response = client.get("/agents/catalog", headers=auth_headers)
        assert response.status_code == 200
        cards = response.json()["agents"]
        card = next(c for c in cards if c["key"] == "submission")
        tip = card["tip"]
        assert not tip.startswith("Submits ")
        assert "records" in tip.lower() or "tracker" in tip.lower()
        assert "transmit" in tip.lower()


# ---------------------------------------------------------------------------
# INVARIANT 3 — additive remediation of the existing false positives
# ---------------------------------------------------------------------------


class TestFalsePositiveBackfill:
    def test_backfill_reclassifies_unproven_rows_without_touching_history(
        self, db_session, user_id
    ):
        from app.db import ensure_application_transmission_columns
        from app.services.submission_truth import (
            STATE_UNVERIFIED,
            backfill_unverified_submissions,
            count_unverified_submissions,
        )

        # One job each: the database allows only ONE active application per
        # (user, job), so a multi-row census has to span jobs.
        jobs = [_seed_job(db_session, user_id) for _ in range(4)]
        resumes = [
            _seed_resume(db_session, user_id, source_job_id=j) for j in jobs
        ]
        unproven_a = _seed_application(
            db_session, user_id, jobs[0], resumes[0], status="submitted"
        )
        unproven_b = _seed_application(
            db_session, user_id, jobs[1], resumes[1], status="submitted",
            created_offset_minutes=5,
        )
        draft = _seed_application(
            db_session, user_id, jobs[2], resumes[2], created_offset_minutes=10
        )
        proven = _seed_application(
            db_session, user_id, jobs[3], resumes[3], status="submitted",
            created_offset_minutes=15,
        )
        ensure_application_transmission_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "transmittedAt" = NOW(), '
                '"transmissionRef" = %s WHERE "id" = %s',
                ("real-evidence", proven),
            )
            cur.execute('SELECT count(*) FROM "Application" WHERE "userId" = %s', (user_id,))
            total_before = cur.fetchone()[0]
        db_session.commit()

        assert count_unverified_submissions(user_id) == 2
        report = backfill_unverified_submissions(user_id)
        assert report["reclassified"] == 2

        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "id","status","submissionTruthState" FROM "Application" '
                'WHERE "userId" = %s ORDER BY "createdAt"',
                (user_id,),
            )
            rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
            cur.execute('SELECT count(*) FROM "Application" WHERE "userId" = %s', (user_id,))
            total_after = cur.fetchone()[0]

        # NEVER deletes history …
        assert total_after == total_before
        # … and NEVER rewrites the user's own tracker status.
        assert rows[unproven_a][0] == "submitted"
        assert rows[unproven_b][0] == "submitted"
        assert rows[draft][0] == "draft"
        assert rows[proven][0] == "submitted"
        # Only the claimed-submitted-without-proof rows are reclassified.
        assert rows[unproven_a][1] == STATE_UNVERIFIED
        assert rows[unproven_b][1] == STATE_UNVERIFIED
        assert rows[draft][1] is None
        assert rows[proven][1] is None

    def test_backfill_is_idempotent(self, db_session, user_id):
        from app.services.submission_truth import backfill_unverified_submissions

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(db_session, user_id, job_id, resume_id, status="submitted")

        assert backfill_unverified_submissions(user_id)["reclassified"] == 1
        assert backfill_unverified_submissions(user_id)["reclassified"] == 0

    def test_reclassified_row_reads_honestly_through_the_api(
        self, db_session, user_id, client, auth_headers
    ):
        from app.services.submission_truth import backfill_unverified_submissions

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )
        backfill_unverified_submissions(user_id)

        response = client.get("/applications", headers=auth_headers)
        assert response.status_code == 200
        row = next(r for r in response.json() if r["id"] == app_id)
        assert row["submissionState"] == "not_transmitted"
        assert row["submissionTruthState"] == "recorded_transmission_unverified"
        assert "unverified" in row["submissionTruthNote"].lower()


# ---------------------------------------------------------------------------
# INVARIANT 4 — U5's safety contracts are still in force
# ---------------------------------------------------------------------------


class TestSafetyContractsPreserved:
    def test_published_recipient_ends_awaiting_approval_and_sends_nothing(
        self, db_session, user_id
    ):
        job_id = _seed_job(
            db_session,
            user_id,
            description=(
                "To apply, send your CV to careers@wsp-testcorp.io — we read "
                "every application."
            ),
        )
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        result = _run_agent(user_id)

        assert result.transmitted is False
        assert result.submissionState == "awaiting_approval"
        assert "Submitted your application" not in result.message
        assert _application_row(db_session, app_id)["transmittedAt"] is None
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "status","executedAt" FROM "ApprovalRequest" '
                'WHERE "userId" = %s AND "type" = %s::"ApprovalType"',
                (user_id, "application_submit"),
            )
            approvals = cur.fetchall()
        assert approvals, "the approval gate card must exist"
        assert all(a[0] == "pending" for a in approvals)
        assert all(a[1] is None for a in approvals), "nothing may execute un-approved"

    def test_run_record_reports_the_approval_gate_it_actually_created(
        self, db_session, user_id, client, auth_headers
    ):
        """The persisted ``AgentRun.output`` — what the Agents screen and run
        history show — must not say ``approvalRequired: false`` over a run
        whose terminal state is a pending approval card. That combination
        (``submitted: true`` + ``approvalRequired: false``) is verbatim what
        all three production runs recorded."""
        job_id = _seed_job(
            db_session,
            user_id,
            description=(
                "To apply, send your CV to talent@wsp-testcorp.io — every "
                "application is read."
            ),
        )
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(db_session, user_id, job_id, resume_id)

        response = client.post(
            "/agents/submission/run", json={}, headers=auth_headers
        )
        assert response.status_code == 200, response.text
        output = response.json()
        assert "submitted" not in output
        assert output["submissionState"] == "awaiting_approval"
        assert output["transmitted"] is False
        assert output["approvalRequired"] is True
        assert output["counts"] == {
            "transmitted": 0, "assisted": 1, "manualStep": 0, "recordedOnly": 0,
        }
        assert "Submitted your application" not in output["message"]

    def test_placeholder_signoff_draft_is_still_refused(self, db_session, user_id):
        from fastapi import HTTPException

        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(
            db_session, user_id, job_id, resume_id,
            cover_letter="Dear team, I would love to help.\n\nSincerely,\nTest User",
        )

        with pytest.raises(HTTPException) as excinfo:
            _run_agent(user_id, job_id=job_id)
        assert excinfo.value.status_code == 422

    def test_apply_sweep_is_still_off_by_default(self, monkeypatch):
        from app.workers import apply_sweep

        monkeypatch.delenv("AETHER_APPLY_SWEEP_ENABLED", raising=False)
        assert apply_sweep.sweep_enabled() is False
