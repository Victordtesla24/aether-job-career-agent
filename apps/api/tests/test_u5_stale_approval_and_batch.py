"""U5 closing round — the stale-approval guard and the bounded sweep.

Two binding orchestrator rulings, written as failing tests first.

**RULING 2 — stale-approval guard.** Production carries 339 approved
``application_submit`` approvals with ``executedAt = NULL`` (submission scout,
2026-08-13). The sweep exists to drive exactly those rows to a terminal state —
but "the user clicked approve" is a fact with a shelf life. An approval a user
gave weeks ago, on a posting they may since have taken themselves, must NOT
turn into a real application landing on a real employer's desk the moment a
kill-switch is flipped. An approval older than
``AETHER_APPROVAL_MAX_AGE_DAYS`` (default 7) is therefore never auto-executed:
it surfaces as an honest, actionable manual step ("approval expired — reconfirm
to submit") with a one-click server-side re-approve path that reuses the
EXISTING ``ApprovalRequest`` machinery.

**RULING 3 — bounded sweep.** One pass processes at most
``AETHER_APPLY_SWEEP_BATCH`` (default 10) transmissions, OLDEST APPROVAL FIRST,
and says honestly how many remain queued. The 339-row backlog must drain
predictably from the oldest end rather than being re-shuffled every tick.

Both contracts are pinned at the ``sweep_pending_transmissions`` level (the
per-application attempt stays monkeypatched at the ``_attempt_transmission``
seam, as in ``test_u5_invariant_sweep.py``) plus, for the re-approve path, at
the HTTP boundary a real user's click goes through.
"""
from __future__ import annotations

import json

import pytest

from app.db import new_id
from app.repositories.approval import ApprovalRepository


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_approved(conn, user_id: str) -> tuple[str, str]:
    """``(application_id, approval_id)`` — approved, non-terminal, Ashby."""
    job_id = new_id()
    resume_id = new_id()
    app_id = new_id()
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
        cur.execute(
            '''INSERT INTO "Resume"
               ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
               VALUES (%s,%s,1,%s,%s,%s,NOW())''',
            (resume_id, user_id, json.dumps({"raw_text": "Jordan Blake."}), "hash", job_id),
        )
        cur.execute(
            '''INSERT INTO "Application"
               ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
               VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
            (app_id, user_id, job_id, resume_id, "Dear Hiring Manager,\n\nJordan"),
        )
    conn.commit()
    approval = ApprovalRepository().create(
        user_id, "application_submit",
        {"kind": "site_apply", "job_id": job_id, "application_id": app_id},
        application_id=app_id,
    )
    ApprovalRepository().approve(approval["id"], user_id)
    return app_id, approval["id"]


def _age_approval(conn, approval_id: str, *, days: float) -> None:
    """Shift BOTH approval stamps into the past.

    The guard's clock is the DECISION time (``resolvedAt``, falling back to
    ``createdAt`` for a row that predates it), so a test that only moved one of
    them would not be testing the guard.
    """
    with conn.cursor() as cur:
        cur.execute(
            '''UPDATE "ApprovalRequest"
               SET "createdAt" = NOW() - make_interval(mins => %s),
                   "resolvedAt" = NOW() - make_interval(mins => %s)
               WHERE "id" = %s''',
            (int(days * 24 * 60), int(days * 24 * 60), approval_id),
        )
    conn.commit()


def _drive_to_terminal(user_id: str, application_id: str, approval_id: str) -> None:
    """Stand-in for a real attempt: leaves the row in a TERMINAL state.

    Mirrors what the executor really does on a blocked form (persist the honest
    obstacle), which is what removes the row from the sweep's queue.
    """
    from app.services.apply_executor import record_manual_step

    record_manual_step(user_id, application_id, "captcha", "reCAPTCHA challenge")


def _manual_step(conn, application_id: str) -> tuple[str | None, str | None]:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "manualStepReason", "manualStepDetail" FROM "Application" '
            'WHERE "id" = %s',
            (application_id,),
        )
        row = cur.fetchone()
    return (row[0], row[1]) if row else (None, None)


class TestStaleApprovalGuard:
    def test_an_approval_older_than_the_max_age_is_never_auto_executed(
        self, db_session, user_id, monkeypatch
    ):
        from app.workers import apply_sweep

        app_id, approval_id = _seed_approved(db_session, user_id)
        _age_approval(db_session, approval_id, days=30)

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        summary = apply_sweep.sweep_pending_transmissions(user_id)

        assert calls == [], "a 30-day-old approval was auto-executed"
        assert summary["stale_approval"] == 1
        assert summary["transmitted"] == 0

    def test_a_stale_approval_surfaces_an_honest_actionable_state(
        self, db_session, user_id, monkeypatch
    ):
        """Blocking is not enough — a blocked row must never be silently
        prepared, which is the whole NO-PREPARED-ONLY invariant."""
        from app.workers import apply_sweep

        app_id, approval_id = _seed_approved(db_session, user_id)
        _age_approval(db_session, approval_id, days=9)
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: None,
        )
        apply_sweep.sweep_pending_transmissions(user_id)

        reason, detail = _manual_step(db_session, app_id)
        assert reason == "approval_expired"
        assert "reconfirm" in (detail or "").lower()
        # The real age is stated, not a vague "a while ago".
        assert "9 day" in (detail or "")

    def test_a_fresh_approval_is_still_driven(self, db_session, user_id, monkeypatch):
        from app.workers import apply_sweep

        app_id, approval_id = _seed_approved(db_session, user_id)
        _age_approval(db_session, approval_id, days=2)
        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert calls == [app_id]
        assert summary["stale_approval"] == 0

    def test_the_max_age_is_configurable_without_a_redeploy(
        self, db_session, user_id, monkeypatch
    ):
        from app.workers import apply_sweep

        assert apply_sweep.approval_max_age_days() == 7.0
        monkeypatch.setenv("AETHER_APPROVAL_MAX_AGE_DAYS", "30")
        assert apply_sweep.approval_max_age_days() == 30.0
        monkeypatch.setenv("AETHER_APPROVAL_MAX_AGE_DAYS", "not-a-number")
        assert apply_sweep.approval_max_age_days() == 7.0

    def test_a_stale_row_is_not_re_stale_stamped_every_pass(
        self, db_session, user_id, monkeypatch
    ):
        """Once expired, the row carries a manual step, so the NEXT pass no
        longer selects it at all — the guard must not become a per-tick writer
        hammering the same 339 rows forever."""
        from app.workers import apply_sweep

        _app_id, approval_id = _seed_approved(db_session, user_id)
        _age_approval(db_session, approval_id, days=30)
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: None,
        )
        first = apply_sweep.sweep_pending_transmissions(user_id)
        second = apply_sweep.sweep_pending_transmissions(user_id)
        assert first["stale_approval"] == 1
        assert second["processed"] == 0


class TestReconfirmSubmissionPath:
    def test_reconfirming_creates_a_fresh_approval_and_clears_the_expired_state(
        self, client, auth_headers, db_session, user_id, monkeypatch
    ):
        from app.workers import apply_sweep

        app_id, approval_id = _seed_approved(db_session, user_id)
        _age_approval(db_session, approval_id, days=30)
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: None,
        )
        apply_sweep.sweep_pending_transmissions(user_id)
        assert _manual_step(db_session, app_id)[0] == "approval_expired"

        response = client.post(
            f"/applications/{app_id}/reconfirm-submission", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["reconfirmed"] is True
        assert body["approvalId"] != approval_id

        fresh = ApprovalRepository().get_by_id(body["approvalId"], user_id)
        assert fresh is not None
        assert fresh["status"] == "approved"
        assert fresh["applicationId"] == app_id
        # ...and the expired manual step is gone, so the sweep can pick it up.
        assert _manual_step(db_session, app_id)[0] is None

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(approval_id),
        )
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert calls == [body["approvalId"]]
        assert summary["stale_approval"] == 0

    def test_reconfirming_never_clears_a_real_obstacle(
        self, client, auth_headers, db_session, user_id
    ):
        """A CAPTCHA or a login wall is not solved by re-approving, so the
        endpoint must refuse rather than wipe the honest state and let the
        sweep loop on it."""
        from app.services.apply_executor import record_manual_step

        app_id, _approval_id = _seed_approved(db_session, user_id)
        record_manual_step(user_id, app_id, "captcha", "reCAPTCHA challenge")

        response = client.post(
            f"/applications/{app_id}/reconfirm-submission", headers=auth_headers
        )
        assert response.status_code == 409
        assert _manual_step(db_session, app_id)[0] == "captcha"

    def test_reconfirming_someone_elses_application_is_a_404(
        self, client, auth_headers
    ):
        response = client.post(
            "/applications/not-my-application/reconfirm-submission",
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestBoundedSweep:
    def test_a_pass_processes_at_most_one_batch(self, db_session, user_id, monkeypatch):
        from app.workers import apply_sweep

        monkeypatch.setenv("AETHER_APPLY_SWEEP_BATCH", "3")
        for _ in range(5):
            _seed_approved(db_session, user_id)

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert len(calls) == 3
        assert summary["processed"] == 3

    def test_the_batch_default_is_ten(self, monkeypatch):
        from app.workers import apply_sweep

        monkeypatch.delenv("AETHER_APPLY_SWEEP_BATCH", raising=False)
        assert apply_sweep.sweep_batch_size() == 10
        monkeypatch.setenv("AETHER_APPLY_SWEEP_BATCH", "0")
        assert apply_sweep.sweep_batch_size() == 1
        monkeypatch.setenv("AETHER_APPLY_SWEEP_BATCH", "nonsense")
        assert apply_sweep.sweep_batch_size() == 10

    def test_the_oldest_approval_is_processed_first(
        self, db_session, user_id, monkeypatch
    ):
        from app.workers import apply_sweep

        monkeypatch.setenv("AETHER_APPLY_SWEEP_BATCH", "2")
        newest_app, newest_approval = _seed_approved(db_session, user_id)
        middle_app, middle_approval = _seed_approved(db_session, user_id)
        oldest_app, oldest_approval = _seed_approved(db_session, user_id)
        _age_approval(db_session, newest_approval, days=0.5)
        _age_approval(db_session, middle_approval, days=2)
        _age_approval(db_session, oldest_approval, days=5)

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        apply_sweep.sweep_pending_transmissions(user_id)
        assert calls == [oldest_app, middle_app], (
            "the backlog must drain from the oldest approval, not in row order"
        )

    def test_what_remains_queued_is_reported_honestly(
        self, db_session, user_id, monkeypatch
    ):
        """``remaining`` is a RE-COUNT of the queue after the pass, not
        ``total - processed``: an attempt that ends in a transport failure
        leaves its row queued, and a summary that quietly subtracted it would
        under-report the backlog every single tick."""
        from app.workers import apply_sweep

        monkeypatch.setenv("AETHER_APPLY_SWEEP_BATCH", "2")
        for _ in range(5):
            _seed_approved(db_session, user_id)
        monkeypatch.setattr(apply_sweep, "_attempt_transmission", _drive_to_terminal)
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["processed"] == 2
        assert summary["remaining"] == 3

    def test_a_row_the_pass_could_not_finish_is_still_counted_as_queued(
        self, db_session, user_id, monkeypatch
    ):
        from app.workers import apply_sweep

        monkeypatch.setenv("AETHER_APPLY_SWEEP_BATCH", "2")
        for _ in range(3):
            _seed_approved(db_session, user_id)

        def _transport_failure(uid, application_id, approval_id):
            raise RuntimeError("the browser could not open the page")

        monkeypatch.setattr(apply_sweep, "_attempt_transmission", _transport_failure)
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["processed"] == 2
        assert summary["failed"] == 2
        assert summary["remaining"] == 3, "a failed attempt leaves its row queued"

    def test_remaining_is_zero_when_the_backlog_is_drained(
        self, db_session, user_id, monkeypatch
    ):
        from app.workers import apply_sweep

        monkeypatch.setenv("AETHER_APPLY_SWEEP_BATCH", "10")
        for _ in range(2):
            _seed_approved(db_session, user_id)
        monkeypatch.setattr(apply_sweep, "_attempt_transmission", _drive_to_terminal)
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        assert summary["processed"] == 2
        assert summary["remaining"] == 0
