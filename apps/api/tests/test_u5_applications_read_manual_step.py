"""U5 read-back regression — the honest manual-step state must reach the UI.

U-PLAN "U5 MANDATE SHARPENED" rule 1 (NO-PREPARED-ONLY): every approved
application ends either TRANSMITTED or in an HONEST, ACTIONABLE state — never
silently stuck in "prepared". The backend writes that actionable state onto the
row (``app.services.apply_executor.record_manual_step`` →
``manualStepReason``/``manualStepDetail``/``manualStepAt``;
``app.services.apply_channel_resolver`` → ``applyChannel``), but a write nobody
reads back is the same silence with extra steps: the user still sees nothing.

These tests pin the READ half of the contract on both application-read
endpoints, so a future edit to ``applications._COLUMNS`` cannot quietly delete
the only channel through which a CAPTCHA / login wall / unanswerable screening
question ever reaches the person who has to act on it.
"""
from __future__ import annotations

import json
import uuid

import pytest


def _uid() -> str:
    return uuid.uuid4().hex


def _seed_application(conn, user_id: str, *, app_status: str = "draft") -> tuple[str, str]:
    """Insert Job + Resume + Application for ``user_id``; return (app_id, job_id)."""
    job_id, resume_id, app_id = _uid(), _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (job_id, user_id, "Staff Engineer", "Ashby Co", "Build things.", "seek",
             f"https://jobs.ashbyhq.com/ashby-co/{job_id}", 91.0),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"sourceJobId","updatedAt") VALUES (%s,%s,1,%s,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "test"}), "hash-u5-read", job_id),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,NOW(),NOW())',
            (app_id, user_id, job_id, resume_id, app_status, "Dear Hiring Manager,"),
        )
    conn.commit()
    return app_id, job_id


def _record_manual_step(conn, app_id: str, *, channel: str, reason: str, detail: str) -> None:
    """Write the SAME columns the real apply pipeline writes, via the same DDL."""
    from app.db import (
        ensure_application_apply_channel_column,
        ensure_application_manual_step_columns,
    )

    ensure_application_apply_channel_column()
    ensure_application_manual_step_columns()
    with conn.cursor() as cur:
        cur.execute(
            'UPDATE "Application" SET "applyChannel" = %s, "manualStepReason" = %s,'
            ' "manualStepDetail" = %s, "manualStepAt" = NOW() WHERE "id" = %s',
            (channel, reason, detail, app_id),
        )
    conn.commit()


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


class TestManualStepRoundTrip:
    """A recorded manual step must be visible through BOTH read endpoints."""

    #: The verbatim question text an Ashby form asked that no stored profile
    #: answer can honestly answer. Fabricating an answer is forbidden, so the
    #: real words must reach the user — paraphrasing loses the question.
    QUESTION = "Do you hold current unrestricted work rights in Australia? (yes/no)"

    def test_list_returns_apply_channel_and_manual_step(
        self, client, auth_headers, user_id, db_session
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status="draft")
        _record_manual_step(
            db_session,
            app_id,
            channel="ashby",
            reason="unknown_required_question",
            detail=self.QUESTION,
        )

        rows = client.get("/applications", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == app_id)

        assert row["applyChannel"] == "ashby"
        assert row["manualStepReason"] == "unknown_required_question"
        assert row["manualStepDetail"] == self.QUESTION
        assert row["manualStepAt"] is not None
        # A manual step is NOT a send: the two states are mutually exclusive.
        assert row["transmitted"] is False
        assert row["submissionState"] == "not_transmitted"

    def test_detail_returns_apply_channel_and_manual_step(
        self, client, auth_headers, user_id, db_session
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status="draft")
        _record_manual_step(
            db_session,
            app_id,
            channel="greenhouse",
            reason="captcha",
            detail="reCAPTCHA challenge on the application page",
        )

        detail = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        assert detail["applyChannel"] == "greenhouse"
        assert detail["manualStepReason"] == "captcha"
        assert detail["manualStepDetail"] == "reCAPTCHA challenge on the application page"
        assert detail["manualStepAt"] is not None
        assert detail["transmitted"] is False

    def test_untouched_application_reports_null_never_a_guess(
        self, client, auth_headers, user_id, db_session
    ):
        """No attempt yet ⇒ all four fields are NULL, present, and unguessed.

        The fields must be PRESENT (so the UI can distinguish "no manual step"
        from "this backend doesn't tell me") and NULL (so nothing invents a
        channel for a posting the resolver has never looked at).
        """
        app_id, _ = _seed_application(db_session, user_id, app_status="draft")

        rows = client.get("/applications", headers=auth_headers).json()
        row = next(r for r in rows if r["id"] == app_id)
        detail = client.get(f"/applications/{app_id}", headers=auth_headers).json()

        for payload in (row, detail):
            for field in (
                "applyChannel",
                "manualStepReason",
                "manualStepDetail",
                "manualStepAt",
            ):
                assert field in payload, f"{field} missing from application read payload"
                assert payload[field] is None
