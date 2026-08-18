"""CLI Track B — D1+D2+D6 (audit wf_9a87f76f-eaa): the dead switches are REAL.

The audit found Settings saying autoApply/matchThreshold were "Saved, but not
yet enforced" while the Applications board claimed "Only applications with
Match Score > threshold% and your explicit approval will be submitted". These
tests pin the enforcement that makes the copy true:

* **D1** — the apply sweep honours the per-user ``agentConfig.autoApply``
  toggle: a user who has not turned it on is never swept (missing/false both
  mean OFF), and the skip is reported honestly (``{"skipped": "autoApply_off"}``),
  never silently. The ``AETHER_APPLY_SWEEP_ENABLED`` env var stays an operator
  kill-switch ON TOP of the user's own toggle.
* **D2** — within a sweep pass, an application whose ``Job.fitScore`` is below
  the user's ``agentConfig.matchThreshold`` (default 80 — AUD-UX-1, same
  number the Settings slider and the ``User.agentConfig`` column default
  use) is NOT auto-fired: it
  is skipped non-terminally (``skippedBelowThreshold`` in the summary), its
  approval is NOT burned, and NO manual step is stamped — the user may still
  submit it explicitly from the UI, and the explicit path bypasses the
  threshold by design.
* **D6** — ``maybe_autonomous_transmit`` obeys the SAME two gates: autonomous
  mode on AND ``fitScore >= matchThreshold`` (a null/missing score is BELOW —
  an unscored job never auto-fires). Below the threshold the approval card
  simply stays ``pending`` for the human decision.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.db import get_connection, new_id
from app.repositories.approval import ApprovalRepository

_MAILTO_DESCRIPTION = (
    "We are hiring a Senior Delivery Lead for our Sydney platform team.\n"
    "To apply, send your CV and a short cover letter to "
    '<a href="mailto:careers@examplecorp.com">careers@examplecorp.com</a>.'
)


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _set_agent_config(user_id: str, config: dict[str, Any] | None) -> None:
    from app.db import ensure_user_profile_columns

    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "agentConfig" = %s WHERE "id" = %s',
                (json.dumps(config) if config is not None else None, user_id),
            )
        conn.commit()


def _make_job(
    user_id: str,
    *,
    fit_score: float | None,
    description: str = "Build things.",
    source: str = "ashby",
    source_url: str | None = None,
) -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Senior Engineer", "Xero", "Sydney NSW", False,
                    description, json.dumps([]), source,
                    source_url
                    if source_url is not None
                    else f"https://jobs.ashbyhq.com/xero/{job_id}/application",
                    fit_score,
                ),
            )
        conn.commit()
    return job_id


def _make_resume(user_id: str, *, source_job_id: str) -> str:
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


def _make_application(user_id: str, job_id: str, resume_id: str) -> str:
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
                    "Dear Hiring Manager,\n\nJordan Blake",
                ),
            )
        conn.commit()
    return app_id


def _seed_approved(user_id: str, *, fit_score: float | None) -> tuple[str, str]:
    """``(application_id, approval_id)`` — approved, non-terminal, site channel."""
    job_id = _make_job(user_id, fit_score=fit_score)
    resume_id = _make_resume(user_id, source_job_id=job_id)
    app_id = _make_application(user_id, job_id, resume_id)
    approval = ApprovalRepository().create(
        user_id, "application_submit",
        {"kind": "site_apply", "job_id": job_id, "application_id": app_id},
        application_id=app_id,
    )
    ApprovalRepository().approve(approval["id"], user_id)
    return app_id, approval["id"]


def _approval_state(approval_id: str) -> tuple[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status", "executedAt" FROM "ApprovalRequest" WHERE "id" = %s',
                (approval_id,),
            )
            row = cur.fetchone()
    assert row is not None
    return row[0], row[1]


def _manual_step_reason(application_id: str) -> str | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "manualStepReason" FROM "Application" WHERE "id" = %s',
                (application_id,),
            )
            row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# D1 — the sweep honours the per-user autoApply toggle.
# ---------------------------------------------------------------------------


class TestD1SweepHonoursAutoApply:
    def test_a_default_config_user_is_not_listed_for_the_sweep(
        self, db_session, user_id
    ):
        """A user who never touched Settings (agentConfig NULL) must not be
        swept — autoApply defaults OFF."""
        from app.workers import apply_sweep

        _seed_approved(user_id, fit_score=78.0)
        _set_agent_config(user_id, None)
        assert user_id not in apply_sweep.users_with_pending_transmissions()

    def test_an_autoapply_false_user_is_not_listed_for_the_sweep(
        self, db_session, user_id
    ):
        from app.workers import apply_sweep

        _seed_approved(user_id, fit_score=78.0)
        _set_agent_config(
            user_id, {"autoApply": False, "approvalGate": True, "matchThreshold": 50}
        )
        assert user_id not in apply_sweep.users_with_pending_transmissions()

    def test_an_opted_in_user_is_listed_for_the_sweep(self, db_session, user_id):
        from app.workers import apply_sweep

        _seed_approved(user_id, fit_score=78.0)
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": True, "matchThreshold": 50}
        )
        assert user_id in apply_sweep.users_with_pending_transmissions()

    def test_apply_sweep_user_skips_a_user_whose_toggle_is_off(
        self, db_session, user_id, monkeypatch
    ):
        """Even a directly-enqueued sweep job must honour the toggle, and the
        skip must be reported honestly — never as a swept pass."""
        from app.workers import apply_sweep

        monkeypatch.setenv("AETHER_APPLY_SWEEP_ENABLED", "true")
        _seed_approved(user_id, fit_score=78.0)
        _set_agent_config(
            user_id, {"autoApply": False, "approvalGate": True, "matchThreshold": 50}
        )
        called: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "sweep_pending_transmissions",
            lambda uid, deadline=None: called.append(uid) or {"userId": uid},
        )
        result = asyncio.run(apply_sweep.apply_sweep_user({}, user_id))
        assert result == {"skipped": "autoApply_off", "userId": user_id}
        assert called == [], "a non-opted-in user's board was swept"

    def test_apply_sweep_user_sweeps_an_opted_in_user(
        self, db_session, user_id, monkeypatch
    ):
        from app.workers import apply_sweep

        monkeypatch.setenv("AETHER_APPLY_SWEEP_ENABLED", "true")
        _seed_approved(user_id, fit_score=78.0)
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": True, "matchThreshold": 50}
        )
        called: list[str] = []

        def _fake_sweep(uid, deadline=None):
            called.append(uid)
            return {"processed": 1, "userId": uid}

        monkeypatch.setattr(apply_sweep, "sweep_pending_transmissions", _fake_sweep)
        result = asyncio.run(apply_sweep.apply_sweep_user({}, user_id))
        assert called == [user_id]
        assert result == {"processed": 1, "userId": user_id}

    def test_the_env_kill_switch_still_wins_over_an_opted_in_user(
        self, db_session, user_id, monkeypatch
    ):
        """The operator kill-switch sits ON TOP of the user toggle: with the
        env switch off, even an opted-in user is not swept."""
        from app.workers import apply_sweep

        monkeypatch.delenv("AETHER_APPLY_SWEEP_ENABLED", raising=False)
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": True, "matchThreshold": 50}
        )
        called: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "sweep_pending_transmissions",
            lambda uid, deadline=None: called.append(uid) or {"userId": uid},
        )
        result = asyncio.run(apply_sweep.apply_sweep_user({}, user_id))
        assert result == {"skipped": "disabled", "userId": user_id}
        assert called == []


# ---------------------------------------------------------------------------
# D2 — the match threshold gates the sweep, non-terminally.
# ---------------------------------------------------------------------------


class TestD2ThresholdGatesTheSweep:
    def _sweep_with_recorder(self, monkeypatch, user_id: str) -> tuple[list[str], dict]:
        from app.workers import apply_sweep

        calls: list[str] = []
        monkeypatch.setattr(
            apply_sweep, "_attempt_transmission",
            lambda uid, application_id, approval_id: calls.append(application_id),
        )
        summary = apply_sweep.sweep_pending_transmissions(user_id)
        return calls, summary

    def test_a_below_threshold_application_is_skipped_not_burned(
        self, db_session, user_id, monkeypatch
    ):
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": True, "matchThreshold": 80}
        )
        app_id, approval_id = _seed_approved(user_id, fit_score=40.0)

        calls, summary = self._sweep_with_recorder(monkeypatch, user_id)

        assert calls == [], "a below-threshold application was auto-fired"
        assert summary["skippedBelowThreshold"] == 1
        assert summary["transmitted"] == 0
        # NON-terminal skip: the approval is NOT burned, NO manual step is
        # stamped, and the row is still honestly counted as queued.
        status, executed_at = _approval_state(approval_id)
        assert status == "approved"
        assert executed_at is None
        assert _manual_step_reason(app_id) is None
        assert summary["remaining"] == 1

    def test_an_unscored_job_is_treated_as_below_threshold(
        self, db_session, user_id, monkeypatch
    ):
        """NULL fitScore never auto-fires — an unscored job is BELOW every
        threshold by definition."""
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": True, "matchThreshold": 50}
        )
        app_id, approval_id = _seed_approved(user_id, fit_score=None)

        calls, summary = self._sweep_with_recorder(monkeypatch, user_id)

        assert calls == []
        assert summary["skippedBelowThreshold"] == 1
        status, executed_at = _approval_state(approval_id)
        assert status == "approved"
        assert executed_at is None
        assert _manual_step_reason(app_id) is None

    def test_a_score_at_the_threshold_is_driven(self, db_session, user_id, monkeypatch):
        """The copy says "Match Score > threshold"; the enforced contract is
        >= so a user whose jobs score exactly at their bar is not stranded."""
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": True, "matchThreshold": 80}
        )
        app_id, _approval_id = _seed_approved(user_id, fit_score=80.0)

        calls, summary = self._sweep_with_recorder(monkeypatch, user_id)

        assert calls == [app_id]
        assert summary["skippedBelowThreshold"] == 0

    def test_a_missing_threshold_defaults_to_eighty(
        self, db_session, user_id, monkeypatch
    ):
        """AUD-UX-1: unset matchThreshold must match Settings (80) and the
        live column default (80). A 50 fallback would auto-submit 50–79
        while the slider still showed 80."""
        _set_agent_config(user_id, {"autoApply": True})
        below_app, _ = _seed_approved(user_id, fit_score=79.0)
        above_app, _ = _seed_approved(user_id, fit_score=81.0)

        calls, summary = self._sweep_with_recorder(monkeypatch, user_id)

        assert calls == [above_app]
        assert summary["skippedBelowThreshold"] == 1


def test_aud_ux1_display_code_and_column_default_are_eighty():
    """The three AUD-UX-1 legs must name the same number.

    Display: Settings + GET /settings fallback.
    Code: user_match_threshold when the key is missing.
    DB: User.agentConfig column default, now owned by ensure_user_profile_columns.
    """
    from app import db as db_mod
    from app.db import DEFAULT_AGENT_CONFIG_JSON, ensure_user_profile_columns, get_connection
    from app.services.application_submission import (
        DEFAULT_MATCH_THRESHOLD,
        user_match_threshold,
    )

    assert DEFAULT_MATCH_THRESHOLD == 80
    assert user_match_threshold({}) == 80
    assert user_match_threshold({"autoApply": True}) == 80
    assert user_match_threshold(None) == 80
    parsed = json.loads(DEFAULT_AGENT_CONFIG_JSON)
    assert parsed["matchThreshold"] == 80
    assert parsed["autoApply"] is False
    assert parsed["approvalGate"] is True

    db_mod._user_profile_columns_ready = False
    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_default FROM information_schema.columns"
                " WHERE table_schema = ANY(current_schemas(false))"
                " AND table_name = 'User' AND column_name = 'agentConfig'"
            )
            raw = cur.fetchone()[0]
    assert raw is not None
    assert "80" in raw
    assert "matchThreshold" in raw


class TestD2ExplicitPathBypassesTheThreshold:
    def test_explicit_execute_of_an_approved_card_still_transmits(
        self, client, auth_headers, db_session, user_id, monkeypatch
    ):
        """The threshold gates AUTONOMOUS fire only. A user who personally
        approves and executes a below-threshold application has made the
        decision themselves — the explicit path submits it (by design)."""
        from app.services import gmail_service as gmail_module
        from app.services.application_submission import queue_submission_approval

        _set_agent_config(
            user_id, {"autoApply": False, "approvalGate": True, "matchThreshold": 90}
        )
        job_id = _make_job(
            user_id,
            fit_score=40.0,
            description=_MAILTO_DESCRIPTION,
            source="adzuna",
            source_url=f"https://example.com/{new_id()}",
        )
        resume_id = _make_resume(user_id, source_job_id=job_id)
        app_id = _make_application(user_id, job_id, resume_id)

        sends: list[dict] = []

        def _fake_send(self_svc, **kwargs):  # noqa: ANN001
            sends.append(kwargs)
            return {"id": "gmail-msg-1", "threadId": "thread-1"}

        monkeypatch.setattr(gmail_module.GmailService, "send", _fake_send, raising=True)
        monkeypatch.setattr(
            "app.repositories.gmail_account.GmailAccountRepository.is_connected",
            lambda self_repo, uid: True,
            raising=True,
        )

        approval = queue_submission_approval(user_id, job_id, app_id, resume_id)
        assert approval is not None
        assert ApprovalRepository().approve(approval["id"], user_id) is not None

        resp = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert len(sends) == 1, "explicit execute must NOT be threshold-gated"


# ---------------------------------------------------------------------------
# D6 — maybe_autonomous_transmit obeys both gates.
# ---------------------------------------------------------------------------


class TestD6AutonomousTransmitGated:
    def _queue_email_approval(
        self, user_id: str, *, fit_score: float | None
    ) -> dict[str, Any]:
        from app.services.application_submission import queue_submission_approval

        job_id = _make_job(
            user_id,
            fit_score=fit_score,
            description=_MAILTO_DESCRIPTION,
            source="adzuna",
            source_url=f"https://example.com/{new_id()}",
        )
        resume_id = _make_resume(user_id, source_job_id=job_id)
        app_id = _make_application(user_id, job_id, resume_id)
        approval = queue_submission_approval(user_id, job_id, app_id, resume_id)
        assert approval is not None
        return approval

    def _install_transmit_recorder(self, monkeypatch) -> list[dict]:
        calls: list[dict] = []

        def _fake_transmit(user, approval):  # noqa: ANN001
            calls.append({"user": user, "approval": approval})
            return {"status": "transmitted", "gmailMessageId": "gmail-msg-1"}

        monkeypatch.setattr(
            "app.services.application_submission.transmit_application",
            _fake_transmit,
        )
        return calls

    def test_below_threshold_is_not_auto_sent_and_the_card_stays_pending(
        self, db_session, user_id, monkeypatch
    ):
        from app.services.application_submission import maybe_autonomous_transmit

        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": False, "matchThreshold": 80}
        )
        approval = self._queue_email_approval(user_id, fit_score=40.0)
        calls = self._install_transmit_recorder(monkeypatch)

        result = maybe_autonomous_transmit(user_id, approval)

        assert result is None, "a below-threshold job was auto-sent"
        assert calls == []
        status, executed_at = _approval_state(approval["id"])
        assert status == "pending", "the approval was burned by a blocked auto-send"
        assert executed_at is None

    def test_an_unscored_job_is_never_auto_sent(self, db_session, user_id, monkeypatch):
        from app.services.application_submission import maybe_autonomous_transmit

        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": False, "matchThreshold": 50}
        )
        approval = self._queue_email_approval(user_id, fit_score=None)
        calls = self._install_transmit_recorder(monkeypatch)

        result = maybe_autonomous_transmit(user_id, approval)

        assert result is None
        assert calls == []
        status, _ = _approval_state(approval["id"])
        assert status == "pending"

    def test_at_or_above_threshold_still_auto_sends_with_the_authorisation_recorded(
        self, db_session, user_id, monkeypatch
    ):
        from app.services.application_submission import maybe_autonomous_transmit

        # RUN-20260818T0223Z AUTO-APPLY killswitch — added deliberately as a
        # SAFETY TIGHTENING (not a weakening) per the AUTO-APPLY-enablement
        # decision memo: maybe_autonomous_transmit now also requires the
        # operator switch AETHER_APPLY_SWEEP_ENABLED to be on — the exact
        # switch the sweep (Path A) already honoured — on top of every user
        # gate this test exercises below. See
        # TestOperatorKillSwitchGatesAutonomousTransmit for the switch-off
        # coverage this addition requires.
        monkeypatch.setenv("AETHER_APPLY_SWEEP_ENABLED", "true")
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": False, "matchThreshold": 80}
        )
        approval = self._queue_email_approval(user_id, fit_score=85.0)
        calls = self._install_transmit_recorder(monkeypatch)

        result = maybe_autonomous_transmit(user_id, approval)

        assert result is not None and result.get("status") == "transmitted"
        assert len(calls) == 1
        status, executed_at = _approval_state(approval["id"])
        assert status == "approved"
        assert executed_at is not None

    def test_without_the_autonomous_opt_in_nothing_fires_even_above_threshold(
        self, db_session, user_id, monkeypatch
    ):
        from app.services.application_submission import maybe_autonomous_transmit

        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": True, "matchThreshold": 50}
        )
        approval = self._queue_email_approval(user_id, fit_score=95.0)
        calls = self._install_transmit_recorder(monkeypatch)

        result = maybe_autonomous_transmit(user_id, approval)

        assert result is None
        assert calls == []
        status, _ = _approval_state(approval["id"])
        assert status == "pending"


# ---------------------------------------------------------------------------
# RUN-20260818T0223Z AUTO-APPLY killswitch — the second, previously ungated
# autonomous-send path (docs/delivery/evidence/RUN-20260818T0223Z/AUTO-APPLY/
# 01-enablement-investigation.md §1b; decision memo
# 05-decision-memos/AUTO-APPLY-enablement.md, "SECOND, ungated live path").
#
# ``maybe_autonomous_transmit`` never checked ``AETHER_APPLY_SWEEP_ENABLED`` —
# the operator kill-switch the sweep (Path A, ``workers.apply_sweep``) already
# honoured. An operator turning the sweep off believed ALL autonomous sends
# were stopped; email-channel autonomous sends kept firing regardless. These
# tests pin ONE operator switch governing BOTH paths.
# ---------------------------------------------------------------------------


class TestOperatorKillSwitchGatesAutonomousTransmit:
    def _queue_email_approval(
        self, user_id: str, *, fit_score: float | None
    ) -> dict[str, Any]:
        from app.services.application_submission import queue_submission_approval

        job_id = _make_job(
            user_id,
            fit_score=fit_score,
            description=_MAILTO_DESCRIPTION,
            source="adzuna",
            source_url=f"https://example.com/{new_id()}",
        )
        resume_id = _make_resume(user_id, source_job_id=job_id)
        app_id = _make_application(user_id, job_id, resume_id)
        approval = queue_submission_approval(user_id, job_id, app_id, resume_id)
        assert approval is not None
        return approval

    def _install_transmit_recorder(self, monkeypatch) -> list[dict]:
        calls: list[dict] = []

        def _fake_transmit(user, approval):  # noqa: ANN001
            calls.append({"user": user, "approval": approval})
            return {"status": "transmitted", "gmailMessageId": "gmail-msg-1"}

        monkeypatch.setattr(
            "app.services.application_submission.transmit_application",
            _fake_transmit,
        )
        return calls

    def test_switch_off_blocks_the_send_even_with_every_user_gate_passing(
        self, db_session, user_id, monkeypatch, caplog
    ):
        """THE GAP: autoApply true, approvalGate false, fitScore above the
        user's own threshold — every USER-side gate passes — but the operator
        has the sweep switch off. No send may occur, and the refusal must be
        honest: no fabricated success, no dropped application, no burned
        approval. The card falls back to the normal approval-gated flow."""
        import logging

        from app.services.application_submission import maybe_autonomous_transmit

        monkeypatch.delenv("AETHER_APPLY_SWEEP_ENABLED", raising=False)
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": False, "matchThreshold": 50}
        )
        approval = self._queue_email_approval(user_id, fit_score=95.0)
        calls = self._install_transmit_recorder(monkeypatch)

        with caplog.at_level(logging.INFO):
            result = maybe_autonomous_transmit(user_id, approval)

        assert result is None, "operator switch OFF must not transmit"
        assert calls == [], "the email provider must never be invoked"
        status, executed_at = _approval_state(approval["id"])
        assert status == "pending", "the approval must stay pending, not burned"
        assert executed_at is None
        assert any(
            "disabled by operator" in record.message for record in caplog.records
        ), "the refusal must be logged honestly, not silent"

    def test_switch_off_with_explicit_string_false_also_blocks(
        self, db_session, user_id, monkeypatch
    ):
        from app.services.application_submission import maybe_autonomous_transmit

        monkeypatch.setenv("AETHER_APPLY_SWEEP_ENABLED", "false")
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": False, "matchThreshold": 50}
        )
        approval = self._queue_email_approval(user_id, fit_score=95.0)
        calls = self._install_transmit_recorder(monkeypatch)

        result = maybe_autonomous_transmit(user_id, approval)

        assert result is None
        assert calls == []

    def test_switch_on_transmits_when_every_other_gate_also_passes(
        self, db_session, user_id, monkeypatch
    ):
        """Parity: with the operator switch ON, a fully-opted-in, above-
        threshold user still autonomously transmits exactly as before."""
        from app.services.application_submission import maybe_autonomous_transmit

        monkeypatch.setenv("AETHER_APPLY_SWEEP_ENABLED", "true")
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": False, "matchThreshold": 50}
        )
        approval = self._queue_email_approval(user_id, fit_score=95.0)
        calls = self._install_transmit_recorder(monkeypatch)

        result = maybe_autonomous_transmit(user_id, approval)

        assert result is not None and result.get("status") == "transmitted"
        assert len(calls) == 1
        status, executed_at = _approval_state(approval["id"])
        assert status == "approved"
        assert executed_at is not None

    def test_switch_off_still_respects_every_pre_existing_user_gate(
        self, db_session, user_id, monkeypatch
    ):
        """Adding the operator switch must not become the ONLY gate: with the
        switch on, a user who never opted in (or is below threshold) must
        still be refused for their OWN reasons, unchanged."""
        from app.services.application_submission import maybe_autonomous_transmit

        monkeypatch.setenv("AETHER_APPLY_SWEEP_ENABLED", "true")
        _set_agent_config(
            user_id, {"autoApply": False, "approvalGate": True, "matchThreshold": 50}
        )
        approval = self._queue_email_approval(user_id, fit_score=95.0)
        calls = self._install_transmit_recorder(monkeypatch)

        result = maybe_autonomous_transmit(user_id, approval)

        assert result is None
        assert calls == []

    def test_apply_sweep_delegates_to_the_same_single_source_of_truth(
        self, monkeypatch
    ):
        """Path A (the sweep) must consult the EXACT SAME function as Path B
        — not merely the same env var by coincidence — so the two code paths
        can never silently disagree about whether autonomy is authorised."""
        from app.services import application_submission
        from app.workers import apply_sweep

        sentinel_calls: list[bool] = []

        def _fake_switch() -> bool:
            sentinel_calls.append(True)
            return False

        monkeypatch.setattr(
            application_submission, "autonomous_transmit_enabled", _fake_switch
        )
        assert apply_sweep.sweep_enabled() is False
        assert sentinel_calls == [True], (
            "apply_sweep.sweep_enabled() did not delegate to "
            "application_submission.autonomous_transmit_enabled() — the two "
            "paths are not reading a single source of truth"
        )

    def test_switch_reads_the_documented_env_var_directly(self, monkeypatch):
        """No second, divergent env var was introduced — both paths still
        read AETHER_APPLY_SWEEP_ENABLED, the pre-existing documented switch."""
        from app.services.application_submission import autonomous_transmit_enabled

        monkeypatch.delenv("AETHER_APPLY_SWEEP_ENABLED", raising=False)
        assert autonomous_transmit_enabled() is False
        monkeypatch.setenv("AETHER_APPLY_SWEEP_ENABLED", "true")
        assert autonomous_transmit_enabled() is True
