"""U5d-2 — the Submission Agent finally REACHES the U5 engine (RED first).

GROUND TRUTH: ``uat/reports/evidence/agents-uplift/u5d/FORENSICS.md`` §4.2,
recommendation **(a)**. U5d (slice b, live at 63d9204) made the agent stop
LYING; it did not make it stop being disconnected. The forensics proved
``apply_channel_resolver`` / ``apply_executor`` have exactly ONE caller family
in the whole codebase — the OFF ``apply_sweep`` worker — and that there is no
code path at all from the Agents card to a real transmission.

This file pins the rewire:

1. **Application-scoped, not job-scoped.** The agent carries the READY DRAFT's
   own id all the way through. It never calls ``submit_application_for_job``
   again (asserted over the parsed module, so a docstring mention cannot
   satisfy or break it), so the newest-row-wins reuse branch that produced all
   three production false positives is unreachable by construction.
2. **The channel is really resolved**, through ``apply_channel_resolver`` —
   the U5 module the agent could not previously reach — and persisted on the
   row.
3. **The honest terminal is ``awaiting_approval``.** A correct run CANNOT end
   "submitted": the ApprovalRequest gate is the product's safety contract, so
   the agent's terminal act is a queued approval and nothing else.
4. **A channel Aether will not drive gets an honest, actionable, persisted
   manual step** (ASSISTED / Seek / unresolvable), never a fabricated
   submission and never silence.
5. **Every U5d invariant survives**: no claim without ``transmittedAt``, the
   placeholder-sign-off guard still refuses, nothing transmits un-approved.

ABSOLUTE SAFETY. No test in this file performs, simulates or approaches a real
submission to a real employer. Both real transmission entry points —
``apply_executor.playwright_form_submitter`` (a browser) and
``application_submission.transmit_application`` (a Gmail send) — are asserted
UNREACHED by monkeypatching them to fail the test loudly if called. Every URL
used is an ``example``/RFC-2606 host or a synthetic id; no request leaves this
process (the resolver is only ever handed non-redirector URLs, which it
classifies by string).
"""
from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

import pytest

_AGENT_SOURCE = (
    Path(__file__).resolve().parents[1] / "app" / "agents" / "submission_agent.py"
)


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


@pytest.fixture(autouse=True)
def _no_real_transmission(monkeypatch):
    """Both real entry points are wired to EXPLODE, in every test in this file.

    This is the existing U5 test pattern (``test_u5b_apply_executor``): the
    safety property under test is "nothing reaches a real employer", and the
    only way to assert it is to make the real seams fatal.
    """
    from app.services import application_submission, apply_executor

    def _forbidden_browser(**kwargs):  # pragma: no cover - must never run
        raise AssertionError(
            "playwright_form_submitter was reached in a unit test — a REAL "
            "browser submission to a REAL employer was about to be attempted."
        )

    def _forbidden_email(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError(
            "transmit_application was reached in a unit test — a REAL "
            "application email was about to be sent."
        )

    monkeypatch.setattr(
        apply_executor, "playwright_form_submitter", _forbidden_browser
    )
    monkeypatch.setattr(
        application_submission, "transmit_application", _forbidden_email
    )
    yield


def _seed_job(
    conn,
    user_id: str,
    *,
    source_url: str,
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
             "lever", source_url, status, 90.0),
        )
    conn.commit()
    return job_id


def _seed_resume(conn, user_id: str, *, source_job_id: str | None) -> str:
    resume_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"sourceJobId","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,NOW())',
            (resume_id, user_id, 1, json.dumps({"raw_text": "cv"}), "h", source_job_id),
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
) -> str:
    app_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,NOW(),NOW())',
            (app_id, user_id, job_id, resume_id, status, cover_letter),
        )
    conn.commit()
    return app_id


def _row(conn, app_id: str) -> dict:
    from app.db import (
        ensure_application_apply_channel_column,
        ensure_application_manual_step_columns,
        ensure_application_transmission_columns,
    )

    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    ensure_application_apply_channel_column()
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "status","transmittedAt","manualStepReason","manualStepDetail",'
            '"applyChannel","updatedAt" FROM "Application" WHERE "id" = %s',
            (app_id,),
        )
        r = cur.fetchone()
    assert r is not None
    return {
        "status": r[0], "transmittedAt": r[1], "manualStepReason": r[2],
        "manualStepDetail": r[3], "applyChannel": r[4], "updatedAt": r[5],
    }


def _approvals(conn, user_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "id","status","payload","executedAt","applicationId" '
            'FROM "ApprovalRequest" WHERE "userId" = %s '
            'AND "type" = \'application_submit\'::"ApprovalType" '
            'ORDER BY "createdAt"',
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "status": r[1], "payload": r[2], "executedAt": r[3],
         "applicationId": r[4]}
        for r in rows
    ]


def _run(user_id: str, job_id: str | None = None):
    from app.agents.submission_agent import SubmissionAgent

    return SubmissionAgent().run(user_id, job_id=job_id)


ASHBY_URL = "https://jobs.ashbyhq.com/example-co/00000000-0000-4000-8000-000000000001"
GREENHOUSE_URL = "https://boards.greenhouse.io/examplecorp/jobs/4000001"
#: SUB-011: re-admitted to AUTOMATABLE_CHANNELS — LEVER_URL already carries
#: the derived ``/apply`` suffix so the payload/applyUrl assertions below
#: compare against exactly what the resolver hands back (see
#: TestLeverApplyUrlDerivation in test_u5a_apply_channel_resolver.py for the
#: bare-posting-URL derivation contract itself).
LEVER_URL = "https://jobs.lever.co/example-co/00000000-0000-4000-8000-000000000002/apply"
#: SmartRecruiters has NO dedicated parser (unlike Lever) and stays ASSISTED.
SMARTRECRUITERS_URL = "https://jobs.smartrecruiters.com/example-co/4000000001"
SEEK_URL = "https://www.seek.com.au/job/00000001"
GENERIC_URL = "https://careers.example.com/postings/finance-specialist"


# ---------------------------------------------------------------------------
# 1 — the agent is wired to the U5 engine, application-scoped
# ---------------------------------------------------------------------------


class TestAgentReachesTheU5Engine:
    def test_automatable_channel_run_ends_awaiting_approval_and_sends_nothing(
        self, db_session, user_id
    ):
        """THE pin for recommendation (a): an Ashby posting now produces a REAL
        W-SUB approval card scoped to the READY DRAFT, and the run's honest
        terminal state is ``awaiting_approval`` — never ``submitted``."""
        job_id = _seed_job(db_session, user_id, source_url=ASHBY_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        result = _run(user_id)

        assert result.submissionState == "awaiting_approval"
        assert result.transmitted is False
        assert result.applicationId == app_id
        assert result.applyChannel == "ashby"
        assert result.approvalId
        assert result.counts["assisted"] == 1
        assert "not transmitted" in result.message.lower()

        # The approval really exists, is PENDING, is scoped to THIS application
        # and carries the channel the executor will need.
        approvals = _approvals(db_session, user_id)
        assert len(approvals) == 1
        approval = approvals[0]
        assert approval["status"] == "pending"
        assert approval["executedAt"] is None
        assert approval["applicationId"] == app_id
        payload = approval["payload"]
        assert payload["kind"] == "submission"
        assert payload["channel"] == "ashby"
        assert payload["application_id"] == app_id
        assert payload["apply_url"] == ASHBY_URL

        # …and NOTHING was transmitted or promoted. The draft is still a draft.
        row = _row(db_session, app_id)
        assert row["transmittedAt"] is None
        assert row["status"] == "draft"
        assert row["applyChannel"] == "ashby"

    def test_greenhouse_is_automatable_too(self, db_session, user_id):
        job_id = _seed_job(db_session, user_id, source_url=GREENHOUSE_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(db_session, user_id, job_id, resume_id)

        result = _run(user_id)

        assert result.applyChannel == "greenhouse"
        assert result.submissionState == "awaiting_approval"

    def test_lever_is_automatable_too(self, db_session, user_id):
        """SUB-011 (Track-2 U5c): Lever re-entered AUTOMATABLE_CHANNELS once
        its dedicated parser + fixture-backed tests existed — the agent must
        now queue a REAL approval for it, exactly like Ashby/Greenhouse,
        never the ASSISTED manual-step copy the pre-SUB-011 disposition
        produced (see ``TestNonAutomatableChannelsAreHonest`` below, now pinned
        against SmartRecruiters instead)."""
        job_id = _seed_job(db_session, user_id, source_url=LEVER_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        result = _run(user_id)

        assert result.applyChannel == "lever"
        assert result.submissionState == "awaiting_approval"
        assert result.transmitted is False
        assert result.counts["assisted"] == 1

        approvals = _approvals(db_session, user_id)
        assert len(approvals) == 1
        approval = approvals[0]
        assert approval["status"] == "pending"
        assert approval["executedAt"] is None
        payload = approval["payload"]
        assert payload["channel"] == "lever"
        assert payload["apply_url"] == LEVER_URL

        row = _row(db_session, app_id)
        assert row["transmittedAt"] is None
        assert row["status"] == "draft"
        assert row["applyChannel"] == "lever"

    def test_the_agent_no_longer_calls_submit_application_for_job(self):
        """Source-level invariant over the PARSED module (``test_u5_invariant_
        sweep`` style), so prose in a docstring can neither satisfy nor break
        it: the job-scoped bookkeeping call that produced every observed
        production false positive is GONE from the agent."""
        tree = ast.parse(_AGENT_SOURCE.read_text())
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "submit_application_for_job" not in called
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert "submit_application_for_job" not in imported
        # …and it DOES reach the U5 engine.
        assert "queue_submission_approval" in imported
        assert "resolve_and_persist_apply_channel" in imported

    def test_selection_is_application_scoped_not_job_scoped(
        self, db_session, user_id
    ):
        """The agent must name the row it selected. A run that resolves a job
        and then lets a second query re-pick 'the newest application' is the
        exact defect this slice removes."""
        job_id = _seed_job(db_session, user_id, source_url=ASHBY_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        ready_draft = _seed_application(db_session, user_id, job_id, resume_id)

        result = _run(user_id)

        assert result.applicationId == ready_draft
        approvals = _approvals(db_session, user_id)
        assert approvals[0]["applicationId"] == ready_draft


# ---------------------------------------------------------------------------
# 2 — channels Aether will NOT drive get an honest, persisted manual step
# ---------------------------------------------------------------------------


class TestNonAutomatableChannelsAreHonest:
    def test_assisted_channel_records_a_manual_step_with_the_direct_url(
        self, db_session, user_id
    ):
        """ORCHESTRATOR RULING U5-F3: SmartRecruiters has no dedicated
        parser, so Aether does not click submit there (Lever DID gain one at
        SUB-011 and is exercised by ``test_lever_is_automatable_too`` above
        instead). The honest outcome is a persisted, actionable manual step
        that hands over the real link — never a fabricated submission and
        never a silent no-op."""
        job_id = _seed_job(db_session, user_id, source_url=SMARTRECRUITERS_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        result = _run(user_id)

        assert result.submissionState == "manual_step_required"
        assert result.transmitted is False
        assert result.reason == "assisted_manual_submit"
        assert result.applyChannel == "smartrecruiters"
        assert SMARTRECRUITERS_URL in (result.nextStep or "")
        assert result.counts["manualStep"] == 1

        row = _row(db_session, app_id)
        assert row["manualStepReason"] == "assisted_manual_submit"
        assert SMARTRECRUITERS_URL in (row["manualStepDetail"] or "")
        assert row["transmittedAt"] is None
        assert row["status"] == "draft"
        # No approval may be raised for a channel we will never drive.
        assert _approvals(db_session, user_id) == []

    def test_seek_is_refused_by_ruling_and_never_queued(self, db_session, user_id):
        """ADR-SEEK-V3 (RULING: REFUSED). Seek must never be automated, and
        must never receive an approval card that implies it could be."""
        job_id = _seed_job(db_session, user_id, source_url=SEEK_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        result = _run(user_id)

        assert result.submissionState == "manual_step_required"
        assert result.reason == "seek_manual_only"
        assert result.applyChannel == "seek-manual"
        assert _approvals(db_session, user_id) == []
        assert _row(db_session, app_id)["transmittedAt"] is None

    def test_generic_employer_form_is_assisted_not_automated(
        self, db_session, user_id
    ):
        job_id = _seed_job(db_session, user_id, source_url=GENERIC_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(db_session, user_id, job_id, resume_id)

        result = _run(user_id)

        assert result.applyChannel == "generic"
        assert result.submissionState == "manual_step_required"
        assert result.reason == "assisted_manual_submit"

    def test_no_source_url_is_unknown_and_says_so(self, db_session, user_id):
        job_id = _seed_job(db_session, user_id, source_url="")
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(db_session, user_id, job_id, resume_id)

        result = _run(user_id)

        assert result.applyChannel == "unknown"
        assert result.submissionState == "manual_step_required"
        assert result.reason == "no_automatable_channel"


# ---------------------------------------------------------------------------
# 3 — the email channel still runs the EXISTING W-SUB path, unchanged
# ---------------------------------------------------------------------------


class TestEmailChannelUnchanged:
    def test_published_recipient_still_queues_the_wsub_email_approval(
        self, db_session, user_id
    ):
        job_id = _seed_job(
            db_session,
            user_id,
            source_url=GENERIC_URL,
            description=(
                "To apply, send your CV to careers@wsp-testcorp.io — we read "
                "every application."
            ),
        )
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id)
        # The email channel is decided by the JOB row, not the URL (U5a).
        with db_session.cursor() as cur:
            from app.db import ensure_job_apply_contact_columns

            ensure_job_apply_contact_columns()
            cur.execute(
                'UPDATE "Job" SET "applyEmail" = %s, "applyEmailSource" = %s '
                'WHERE "id" = %s',
                ("careers@wsp-testcorp.io", "description", job_id),
            )
        db_session.commit()

        result = _run(user_id)

        assert result.applyChannel == "email"
        assert result.submissionState == "awaiting_approval"
        assert result.transmitted is False
        approvals = _approvals(db_session, user_id)
        assert len(approvals) == 1
        assert approvals[0]["status"] == "pending"
        assert approvals[0]["executedAt"] is None
        assert approvals[0]["payload"]["recipient"] == "careers@wsp-testcorp.io"
        assert _row(db_session, app_id)["transmittedAt"] is None


# ---------------------------------------------------------------------------
# 4 — U5d invariants survive the rewire
# ---------------------------------------------------------------------------


class TestU5dInvariantsSurvive:
    def test_placeholder_signoff_draft_is_still_refused(self, db_session, user_id):
        """BLOCKER-002 d2. The agent no longer goes through
        ``submit_application_for_job``, so it must run the SAME guard itself —
        a contaminated letter must never reach an approval card."""
        from fastapi import HTTPException

        job_id = _seed_job(db_session, user_id, source_url=ASHBY_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(
            db_session, user_id, job_id, resume_id,
            cover_letter="Dear team, I would love to help.\n\nSincerely,\nTest User",
        )

        with pytest.raises(HTTPException) as excinfo:
            _run(user_id, job_id=job_id)
        assert excinfo.value.status_code == 422
        assert _approvals(db_session, user_id) == []

    def test_missing_tailored_resume_is_refused_not_queued(
        self, db_session, user_id
    ):
        """The gate the card advertises is still a gate. An explicit job with
        no job-tailored résumé is an honest 422, never a queued submission."""
        from fastapi import HTTPException

        job_id = _seed_job(db_session, user_id, source_url=ASHBY_URL)
        base_resume = _seed_resume(db_session, user_id, source_job_id=None)
        _seed_application(db_session, user_id, job_id, base_resume)

        with pytest.raises(HTTPException) as excinfo:
            _run(user_id, job_id=job_id)
        assert excinfo.value.status_code == 422
        assert _approvals(db_session, user_id) == []

    def test_transmitted_row_still_reports_from_the_row_not_control_flow(
        self, db_session, user_id
    ):
        from app.db import ensure_application_transmission_columns

        job_id = _seed_job(db_session, user_id, source_url=ASHBY_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )
        ensure_application_transmission_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "transmittedAt" = NOW(), '
                '"transmissionRef" = %s WHERE "id" = %s',
                ("evidence-u5d2", app_id),
            )
        db_session.commit()

        result = _run(user_id, job_id=job_id)

        assert result.transmitted is True
        assert result.submissionState == "transmitted"
        assert result.transmissionRef == "evidence-u5d2"

    def test_active_application_blocks_a_second_queue_for_the_same_job(
        self, db_session, user_id
    ):
        """PROD REPRO (FORENSICS §2.2): one job, an untouched ready draft plus
        an already-active row. Queueing the draft would put a SECOND
        application in front of the same employer."""
        job_id = _seed_job(db_session, user_id, source_url=ASHBY_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        draft_id = _seed_application(db_session, user_id, job_id, resume_id)
        active_id = _seed_application(
            db_session, user_id, job_id, resume_id, status="submitted"
        )
        before = _row(db_session, draft_id)

        result = _run(user_id)

        assert result.submissionState == "no_change"
        assert result.applicationId == active_id
        assert _approvals(db_session, user_id) == []
        assert _row(db_session, draft_id)["updatedAt"] == before["updatedAt"]

    def test_rerunning_reuses_the_pending_approval_instead_of_stacking(
        self, db_session, user_id
    ):
        job_id = _seed_job(db_session, user_id, source_url=ASHBY_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(db_session, user_id, job_id, resume_id)

        first = _run(user_id)
        second = _run(user_id)

        assert first.submissionState == second.submissionState == "awaiting_approval"
        approvals = _approvals(db_session, user_id)
        assert len(approvals) == 1, "a re-run must refresh, never stack, the card"
        assert second.approvalId == first.approvalId


# ---------------------------------------------------------------------------
# 5 — the agent-runtime contract
# ---------------------------------------------------------------------------


class TestAgentRuntimeContract:
    def test_submission_is_declared_approval_gated(self):
        from app.routers.agents import _APPROVAL_GATED

        assert "submission" in _APPROVAL_GATED

    def test_run_output_reports_the_gate_it_really_created(
        self, db_session, user_id, client, auth_headers
    ):
        job_id = _seed_job(db_session, user_id, source_url=ASHBY_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(db_session, user_id, job_id, resume_id)

        response = client.post("/agents/submission/run", json={}, headers=auth_headers)

        assert response.status_code == 200, response.text
        output = response.json()
        assert "submitted" not in output
        assert output["submissionState"] == "awaiting_approval"
        assert output["transmitted"] is False
        assert output["approvalRequired"] is True
        assert output["applyChannel"] == "ashby"

    def test_a_manual_step_run_does_not_claim_a_gate_it_never_created(
        self, db_session, user_id, client, auth_headers
    ):
        """Adding ``submission`` to ``_APPROVAL_GATED`` must not make every run
        assert an approval card. A run that ended in a manual step created no
        approval, and saying otherwise is the same class of falsehood this
        workstream exists to remove."""
        job_id = _seed_job(db_session, user_id, source_url=SMARTRECRUITERS_URL)
        resume_id = _seed_resume(db_session, user_id, source_job_id=job_id)
        _seed_application(db_session, user_id, job_id, resume_id)

        response = client.post("/agents/submission/run", json={}, headers=auth_headers)

        assert response.status_code == 200, response.text
        output = response.json()
        assert output["submissionState"] == "manual_step_required"
        assert output["approvalRequired"] is False
        assert _approvals(db_session, user_id) == []

    def test_catalog_tip_names_the_approval_gate(self, client, auth_headers):
        response = client.get("/agents/catalog", headers=auth_headers)
        assert response.status_code == 200
        card = next(
            c for c in response.json()["agents"] if c["key"] == "submission"
        )
        tip = card["tip"].lower()
        assert not card["tip"].startswith("Submits ")
        assert "approv" in tip
        assert "transmit" in tip

    def test_agent_run_stream_docs_no_longer_claim_submission_is_ungated(self):
        """``agent_run_stream`` documented, correctly, that ``submission`` had
        no approval gate (FORENSICS §3.2). That is now false, and a docstring
        that stays false is a smaller version of the same defect."""
        source = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "agent_run_stream.py"
        ).read_text()
        assert (
            "``submission`` is deliberately NOT in" not in source
        ), "the module still documents the gap this slice closed"
        assert "a submission run has no approval gate" not in source
