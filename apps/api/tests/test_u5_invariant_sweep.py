"""U5 INVARIANT — the sweep job: no application remains "prepared only"
(failing tests, written before implementation).

U-PLAN "U5 MANDATE SHARPENED" binding rule 1 (verbatim): "NO-PREPARED-ONLY
invariant -- every application the user approves must reach a TERMINAL
state: TRANSMITTED (email or web-form, with evidence screenshot +
transmittedAt/channel) or an HONEST ACTIONABLE state (e.g. 'manual step
required...') -- never silently stuck in prepared; a sweep job re-drives
non-terminal applications."

LIVE EVIDENCE this invariant is currently violated in production (scout,
2026-08-13): "all 339 approved application_submit approvals have
executedAt=NULL" -- 339 real approved gates, in production RIGHT NOW, that
nothing has ever driven to a terminal state. This is the exact class of row
the sweep must eliminate.

WHAT DOES NOT EXIST YET (confirmed by grep, 2026-08-13): no
``apps/api/app/workers/apply_sweep.py``. Depends on U5b's
``app.services.apply_executor`` (``ManualStepRequired`` /
``ApplyExecutorGuardError``), which also does not exist yet -- so every test
below is expected to fail with ImportError/ModuleNotFoundError until BOTH
U5b and this sweep are implemented.

CONTRACT under test (mirrors ``app.workers.board_sweep``'s orchestration-seam
pattern: the real per-application transmission attempt is monkeypatched at
``apply_sweep._attempt_transmission`` so this file pins ORCHESTRATION, not
the executor internals already covered by ``test_u5b_apply_executor.py``):

  ``_attempt_transmission(user_id: str, application_id: str, approval_id:
  str) -> None``
    The real seam: loads the tailored resume/cover letter/profile and calls
    ``app.services.apply_executor.execute_site_application``. May raise
    ``ManualStepRequired`` (executor already persisted the manual-step
    columns) or ``ApplyExecutorGuardError`` (already executed / not
    approved -- a race with a concurrent sweep or a manual execute).

  ``sweep_pending_transmissions(user_id: str, *, deadline: float | None =
  None) -> dict``
    Selects every ``Application`` with an ``ApprovalRequest(type=
    'application_submit', status='approved')`` and NO terminal state yet
    (``transmittedAt IS NULL AND manualStepReason IS NULL``), calls
    ``_attempt_transmission`` for each, and returns
    ``{"processed": N, "transmitted": N, "manual_step": N, "skipped": N}``.
    A ``ManualStepRequired`` counts as ``manual_step`` (DRIVEN, not
    skipped -- the row now carries an honest actionable state, which
    satisfies the invariant even though nothing was sent). An
    ``ApplyExecutorGuardError`` (already executed elsewhere / no longer
    approved) counts as ``skipped`` with no further action -- the row is
    already someone else's terminal outcome.
"""
from __future__ import annotations

import json

import pytest

from app.db import get_connection, new_id
from app.repositories.approval import ApprovalRepository


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _make_job(conn, user_id: str) -> str:
    job_id = new_id()
    with conn.cursor() as cur:
        cur.execute(
            '''INSERT INTO "Job"
               ("id","userId","title","company","location","remote","description",
                "requirements","source","sourceUrl","fitScore","updatedAt")
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
            (
                job_id, user_id, "Senior Engineer", "Xero", "Sydney NSW", False,
                "Build things.", json.dumps([]), "ashby",
                f"https://jobs.ashbyhq.com/xero/{job_id}/application", 78.0,
            ),
        )
    conn.commit()
    return job_id


def _make_resume(conn, user_id: str, *, source_job_id: str) -> str:
    resume_id = new_id()
    with conn.cursor() as cur:
        cur.execute(
            '''INSERT INTO "Resume"
               ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
               VALUES (%s,%s,1,%s,%s,%s,NOW())''',
            (resume_id, user_id, json.dumps({"raw_text": "Jordan Blake."}), "hash", source_job_id),
        )
    conn.commit()
    return resume_id


def _make_application(conn, user_id: str, job_id: str, resume_id: str) -> str:
    app_id = new_id()
    with conn.cursor() as cur:
        cur.execute(
            '''INSERT INTO "Application"
               ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
               VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
            (app_id, user_id, job_id, resume_id, "Dear Hiring Manager,\n\nExcited to apply.\n\nJordan"),
        )
    conn.commit()
    return app_id


def _seed_approved(conn, user_id: str) -> tuple[str, str]:
    """``(application_id, approval_id)`` for an approved, non-terminal app."""
    job_id = _make_job(conn, user_id)
    resume_id = _make_resume(conn, user_id, source_job_id=job_id)
    app_id = _make_application(conn, user_id, job_id, resume_id)
    approval = ApprovalRepository().create(
        user_id, "application_submit",
        {"kind": "site_apply", "job_id": job_id, "application_id": app_id},
        application_id=app_id,
    )
    ApprovalRepository().approve(approval["id"], user_id)
    return app_id, approval["id"]


def _seed_pending(conn, user_id: str) -> tuple[str, str]:
    """An application whose approval is still PENDING -- must never be
    touched by the sweep (approval-gate, not just non-terminal-state)."""
    job_id = _make_job(conn, user_id)
    resume_id = _make_resume(conn, user_id, source_job_id=job_id)
    app_id = _make_application(conn, user_id, job_id, resume_id)
    approval = ApprovalRepository().create(
        user_id, "application_submit",
        {"kind": "site_apply", "job_id": job_id, "application_id": app_id},
        application_id=app_id,
    )
    return app_id, approval["id"]


def _mark_transmitted(conn, application_id: str) -> None:
    from app.db import ensure_application_transmission_columns

    ensure_application_transmission_columns()
    with conn.cursor() as cur:
        cur.execute(
            '''UPDATE "Application" SET "transmittedAt" = NOW(),
               "transmissionChannel" = 'ashby', "transmissionRef" = 'evidence/x.png'
               WHERE "id" = %s''',
            (application_id,),
        )
    conn.commit()


class TestSweepDrivesOnlyApprovedNonTerminalApplications:
    def test_approved_non_terminal_applications_are_attempted(self, db_session, user_id, monkeypatch):
        from app.workers import apply_sweep

        driven, _approval_id = _seed_approved(db_session, user_id)
        pending_app_id, _ = _seed_pending(db_session, user_id)

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert calls == [driven]
        assert pending_app_id not in calls
        assert summary["processed"] == 1

    def test_already_transmitted_applications_are_never_re_attempted(self, db_session, user_id, monkeypatch):
        """No-double-submission at the SWEEP level: an application that
        already carries transmittedAt must never reach the executor seam
        again, even though its ApprovalRequest is still 'approved'."""
        from app.workers import apply_sweep

        app_id, _approval_id = _seed_approved(db_session, user_id)
        _mark_transmitted(db_session, app_id)

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert calls == []
        assert summary["processed"] == 0

    def test_re_running_the_sweep_after_a_real_transmission_is_idempotent(self, db_session, user_id, monkeypatch):
        """End-to-end idempotency: the FIRST sweep pass transmits (the fake
        attempt writes transmittedAt, exactly as the real executor would);
        the SECOND pass over the same board must not touch that row again."""
        from app.workers import apply_sweep

        app_id, _approval_id = _seed_approved(db_session, user_id)

        def fake_attempt(uid, application_id, approval_id):
            _mark_transmitted(db_session, application_id)

        monkeypatch.setattr(apply_sweep, "_attempt_transmission", fake_attempt)

        first = apply_sweep.sweep_pending_transmissions(user_id)
        assert first["processed"] == 1

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        second = apply_sweep.sweep_pending_transmissions(user_id)
        assert calls == [], "a second sweep pass re-drove an already-transmitted application"
        assert second["processed"] == 0


class TestManualStepCountsAsDrivenNotSkipped:
    def test_manual_step_required_is_counted_and_leaves_no_prepared_row(self, db_session, user_id, monkeypatch):
        from app.services.apply_executor import ManualStepRequired
        from app.workers import apply_sweep
        from app.db import ensure_application_manual_step_columns

        ensure_application_manual_step_columns()
        app_id, _approval_id = _seed_approved(db_session, user_id)

        def fake_attempt(uid, application_id, approval_id):
            # Mirrors what the REAL executor does before re-raising: persist
            # the manual-step columns, THEN raise.
            with db_session.cursor() as cur:
                cur.execute(
                    '''UPDATE "Application" SET "manualStepReason" = %s,
                       "manualStepDetail" = %s, "manualStepAt" = NOW()
                       WHERE "id" = %s''',
                    ("unknown_required_question", "Flexible Working", application_id),
                )
            db_session.commit()
            raise ManualStepRequired(
                "unknown_required_question", "unanswerable required question",
                question="Flexible Working",
            )

        monkeypatch.setattr(apply_sweep, "_attempt_transmission", fake_attempt)
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["manual_step"] == 1
        assert summary["processed"] == 1

        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "manualStepReason", "transmittedAt" FROM "Application" WHERE "id" = %s',
                (app_id,),
            )
            reason, transmitted_at = cur.fetchone()
        assert reason == "unknown_required_question"
        assert transmitted_at is None


class TestNoPrepatedOnlyInvariant:
    def test_no_approved_application_remains_silently_prepared_after_one_sweep_pass(
        self, db_session, user_id, monkeypatch
    ):
        """THE core invariant (U5 MANDATE SHARPENED rule 1): after one sweep
        pass, scanning the whole board for "approved application_submit gate
        + neither transmitted nor manual-stepped" must find ZERO rows --
        this is the exact 339-row production defect the scout measured live
        (all 339 approved gates sit with executedAt=NULL, never driven)."""
        from app.services.apply_executor import ManualStepRequired
        from app.workers import apply_sweep
        from app.db import ensure_application_manual_step_columns, ensure_application_transmission_columns

        ensure_application_manual_step_columns()
        ensure_application_transmission_columns()

        transmit_id, _ = _seed_approved(db_session, user_id)
        manual_id, _ = _seed_approved(db_session, user_id)

        def fake_attempt(uid, application_id, approval_id):
            if application_id == transmit_id:
                _mark_transmitted(db_session, application_id)
            else:
                with db_session.cursor() as cur:
                    cur.execute(
                        '''UPDATE "Application" SET "manualStepReason" = %s,
                           "manualStepDetail" = %s, "manualStepAt" = NOW()
                           WHERE "id" = %s''',
                        ("captcha", "reCAPTCHA challenge detected", application_id),
                    )
                db_session.commit()
                raise ManualStepRequired("captcha", "reCAPTCHA challenge detected")

        monkeypatch.setattr(apply_sweep, "_attempt_transmission", fake_attempt)
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["processed"] == 2

        with db_session.cursor() as cur:
            cur.execute(
                '''
                SELECT a."id" FROM "Application" a
                JOIN "ApprovalRequest" ar ON ar."applicationId" = a."id"
                WHERE a."userId" = %s AND ar."type" = 'application_submit'::"ApprovalType"
                  AND ar."status" = 'approved'::"ApprovalStatus"
                  AND a."transmittedAt" IS NULL
                  AND a."manualStepReason" IS NULL
                ''',
                (user_id,),
            )
            silently_prepared = cur.fetchall()
        assert silently_prepared == [], (
            f"{len(silently_prepared)} application(s) remain approved but "
            "neither transmitted nor manual-stepped after a full sweep pass "
            "-- this is the exact prepared-only defect the sweep exists to "
            "eliminate"
        )

    def test_guard_error_from_a_racing_concurrent_execute_is_skipped_not_double_driven(
        self, db_session, user_id, monkeypatch
    ):
        """If a human manually executes the approval WHILE the sweep is
        mid-pass (a real race the sweep must tolerate), the executor seam
        raises the SAME guard the manual path would hit -- the sweep must
        record it as skipped, not crash the whole stretch."""
        from app.services.apply_executor import ApplyExecutorGuardError
        from app.workers import apply_sweep

        _app_id, _approval_id = _seed_approved(db_session, user_id)

        def fake_attempt(uid, application_id, approval_id):
            raise ApplyExecutorGuardError("already_executed", "raced by a concurrent execute")

        monkeypatch.setattr(apply_sweep, "_attempt_transmission", fake_attempt)
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["skipped"] == 1
        assert summary["manual_step"] == 0
        assert summary["transmitted"] == 0
