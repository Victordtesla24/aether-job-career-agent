"""U-AX build spec item 1 — instrumentation schema (self-improvement
visibility layer). Failing tests, written BEFORE implementation, per the
U-AX BUILD SPEC ADDITIONS (U-PLAN.md) + the ORIGINAL U-AX plan's
instrumentation schema (the [SUPERSEDED] U4 paragraph — historical scope only,
now absorbed by U-AX):

  * ``ApplicationStatusEvent`` rows written on every Application status
    transition.
  * ``Application.atsScoreAtSubmission`` + ``Application.tailoredResumeVersionId``
    snapshotted at submit time.
  * ``AgentRun.applicationId`` / ``AgentRun.jobId`` — nullable, additive.
  * ``Offer.applicationId`` column.

GROUND TRUTH (verified 2026-08-13 in this worktree, matches the feedback-loop
scout's negative-grep result): none of the above exists on ``main`` — no
``ApplicationStatusEvent`` table/model, no ``atsScoreAtSubmission`` /
``tailoredResumeVersionId`` columns on ``Application``, no ``applicationId`` /
``jobId`` columns on ``AgentRun``, no ``applicationId`` column on the additive
``"Offer"`` table (``app/services/offers.py::_ensure_offers_table``).

CONTRACT PINNED BY THIS FILE (test-author decision, following the repo's own
lazy-DDL convention — see ``app/db.py::ensure_application_transmission_columns``
/ ``app/repositories/agent_run.py::ensure_heartbeat_column`` /
``app/services/offers.py::_ensure_offers_table`` — this is the ONLY additive-
migration mechanism in this codebase; ADR-TR-1, "no migration runner"):

  * ``app.repositories.application_status_event.ensure_application_status_event_table()``
    — lazy DDL creating ``"ApplicationStatusEvent"``
    (id, applicationId, fromStatus, toStatus, at, source).
  * ``app.repositories.application_status_event.record_status_event(
    application_id, from_status, to_status, source)`` — one row per transition.
  * ``app.repositories.application_status_event.list_status_events(application_id)``
    — chronological (oldest first).
  * ``app.db.ensure_application_submission_snapshot_columns()`` — adds
    ``Application.atsScoreAtSubmission`` (double precision, nullable) and
    ``Application.tailoredResumeVersionId`` (text, nullable).
  * ``app.repositories.agent_run.ensure_agent_run_link_columns()`` — adds
    ``AgentRun.applicationId`` / ``AgentRun.jobId`` (text, nullable).
  * ``app.services.offers.ensure_offer_application_id_column()`` — adds
    ``Offer.applicationId`` (text, nullable).

These names are test-author-chosen (the U-AX architect has freedom over
internal wiring so long as the SCHEMA and its honest behaviour match the
spec) but the schema itself — table/column names, additive-only, nullable —
comes directly from the build spec and is not free to change.

Run under ``flock /tmp/aether-pytest.lock`` (shared ``aether_test`` schema).
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.db import get_connection, new_id


def _make_job(user_id: str, *, ats_score: float = 62.5) -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","atsScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Senior Delivery Lead", "ExampleCorp",
                    "Sydney NSW", False, "Lead delivery of the platform program.",
                    json.dumps([]), "adzuna", f"https://example.com/{job_id}",
                    82.0, ats_score,
                ),
            )
        conn.commit()
    return job_id


def _make_tailored_resume(user_id: str, *, source_job_id: str) -> str:
    resume_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
                   VALUES (%s,%s,1,%s,%s,%s,NOW())''',
                (
                    resume_id, user_id,
                    json.dumps({"raw_text": "Jordan Blake — delivery lead, 9 years."}),
                    "hash", source_job_id,
                ),
            )
        conn.commit()
    return resume_id


def _make_draft_application(user_id: str, job_id: str, resume_id: str) -> str:
    """A 'Ready to Apply' draft: tailored resume + non-empty cover letter,
    exactly what ``POST /jobs/{id}/apply`` requires to promote to submitted."""
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Application"
                   ("id","userId","jobId","resumeId","status","coverLetter",
                    "createdAt","updatedAt")
                   VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
                (
                    app_id, user_id, job_id, resume_id,
                    "Dear Hiring Manager,\n\nI am excited to apply.\n\nJordan Blake",
                ),
            )
        conn.commit()
    return app_id


def _column_count(table: str, columns: list[str]) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = %s"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = ANY(%s)",
                (table, columns),
            )
            return cur.fetchone()[0]


class TestApplicationStatusEventTable:
    def test_ensure_table_creates_it_idempotently(self, client, db_session):  # noqa: ARG002
        from app.repositories.application_status_event import (
            ensure_application_status_event_table,
        )

        ensure_application_status_event_table()
        ensure_application_status_event_table()  # idempotent second call
        with db_session.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'ApplicationStatusEvent'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            cols = {row[0] for row in cur.fetchall()}
        assert {"id", "applicationId", "fromStatus", "toStatus", "at", "source"} <= cols

    def test_real_submit_writes_a_status_event(self, client, auth_headers, test_user_id):
        """The REAL submit path (POST /jobs/{id}/apply) must write an
        ApplicationStatusEvent row for the draft->submitted transition — not
        just declare the table."""
        from app.repositories.application_status_event import list_status_events

        job_id = _make_job(test_user_id)
        resume_id = _make_tailored_resume(test_user_id, source_job_id=job_id)
        app_id = _make_draft_application(test_user_id, job_id, resume_id)

        resp = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert resp.status_code == 200, resp.text

        events = list_status_events(app_id)
        assert len(events) >= 1, "no ApplicationStatusEvent row was written on submit"
        last = events[-1]
        assert last["toStatus"] == "submitted"
        assert last["fromStatus"] == "draft"
        assert last["applicationId"] == app_id


class TestSubmissionSnapshotColumns:
    def test_ensure_columns_creates_them_idempotently(self, client, db_session):  # noqa: ARG002
        from app.db import ensure_application_submission_snapshot_columns

        ensure_application_submission_snapshot_columns()
        ensure_application_submission_snapshot_columns()
        assert (
            _column_count(
                "Application", ["atsScoreAtSubmission", "tailoredResumeVersionId"]
            )
            == 2
        )

    def test_real_submit_snapshots_ats_score_and_resume_version(
        self, client, auth_headers, test_user_id, db_session
    ):
        job_id = _make_job(test_user_id, ats_score=71.0)
        resume_id = _make_tailored_resume(test_user_id, source_job_id=job_id)
        app_id = _make_draft_application(test_user_id, job_id, resume_id)

        resp = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert resp.status_code == 200, resp.text

        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "atsScoreAtSubmission", "tailoredResumeVersionId"'
                ' FROM "Application" WHERE "id" = %s',
                (app_id,),
            )
            row = cur.fetchone()
        assert row is not None
        ats_at_submission, resume_version_id = row
        assert ats_at_submission == pytest.approx(71.0), (
            "Application.atsScoreAtSubmission was not snapshotted from the "
            "Job's atsScore at the moment of submission"
        )
        assert resume_version_id == resume_id, (
            "Application.tailoredResumeVersionId was not snapshotted to the "
            "resume version actually submitted"
        )


class TestAgentRunLinkColumns:
    def test_ensure_columns_creates_them_idempotently(self, client, db_session):  # noqa: ARG002
        from app.repositories.agent_run import ensure_agent_run_link_columns

        ensure_agent_run_link_columns()
        ensure_agent_run_link_columns()
        assert _column_count("AgentRun", ["applicationId", "jobId"]) == 2

    def test_tailor_agent_run_records_job_id(self, client, auth_headers, test_user_id, db_session):
        """A tailor run for a specific job must persist AgentRun.jobId — the
        seam the U-AX orchestration map + per-agent metrics rely on to
        correlate a run with the job/application it acted on."""
        from app.repositories.agent_run import ensure_agent_run_link_columns

        ensure_agent_run_link_columns()
        job_id = _make_job(test_user_id)

        resp = client.post(
            "/agents/tailor/run", json={"job_id": job_id}, headers=auth_headers
        )
        # Whatever the tailor run's own outcome (fixture-mode LLM replay may
        # no-op), an AgentRun row for this user's tailor call must exist and
        # must carry the job it ran against.
        assert resp.status_code in (200, 422), resp.text

        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "jobId" FROM "AgentRun"'
                ' WHERE "userId" = %s AND "agentName" = \'tailor\''
                ' ORDER BY "createdAt" DESC LIMIT 1',
                (test_user_id,),
            )
            row = cur.fetchone()
        assert row is not None, "no AgentRun row was recorded for the tailor call"
        assert row[0] == job_id, (
            "AgentRun.jobId was not populated for a job-scoped tailor run"
        )


class TestOfferApplicationIdColumn:
    def test_ensure_column_creates_it_idempotently(self, client, db_session):  # noqa: ARG002
        from app.services.offers import ensure_offer_application_id_column

        ensure_offer_application_id_column()
        ensure_offer_application_id_column()
        assert _column_count("Offer", ["applicationId"]) == 1
