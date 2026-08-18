"""W-SUB — REAL application submission (transmission), not a claimed one.

GROUND TRUTH THIS FILE PINS (verified live against the production ``aether``
schema on 2026-08-02, before the fix):

  * ``ApprovalRequest.executedAt`` was NULL on ALL 133 rows — no approval had
    ever executed a side-effect;
  * ``POST /approvals/{id}/execute`` returned ``{"status": "executed"}`` for
    every ``application_submit`` approval WITHOUT doing anything at all;
  * ``Job`` had no recipient column, so there was nowhere to send to;
  * no resume was ever attached to anything;
  * 86 ``Application`` rows read ``submitted`` to the user while nothing had
    ever left the system.

The contract asserted here:

  1. A job with no genuine recipient derivable from real posting data is NOT
     auto-submittable, and executing a submission approval for it refuses
     honestly (422) — never a silent "executed".
  2. Executing an APPROVED submission approval builds a real email, ATTACHES
     the tailored resume AND the cover letter as real PDF bytes, sends it
     through the existing Gmail send path, stamps ``executedAt``, stamps the
     ``Application`` transmission columns and advances the stage.
  3. Idempotency: a second execute is a 409 and sends NOTHING.
  4. The approval gate holds: a PENDING approval cannot transmit (403).
  5. Presentation is truthful: an Application that was never transmitted
     reports ``transmitted: false`` / ``submissionState: "not_transmitted"``
     however its stored ``status`` reads.

No live Gmail call is made by this suite: the transport (``GmailService.send``)
is the seam that is substituted, so everything up to and including the exact
RFC message + attachment bytes is the real production code path.
"""
from __future__ import annotations

import json

import pytest

from app.db import get_connection, new_id

_MAILTO_DESCRIPTION = (
    "We are hiring a Senior Delivery Lead for our Sydney platform team.\n"
    "To apply, send your CV and a short cover letter to "
    "<a href=\"mailto:careers@examplecorp.com\">careers@examplecorp.com</a>."
)

_NO_CONTACT_DESCRIPTION = (
    "Lead cross-functional delivery of the platform program. "
    "Apply through our careers portal."
)


@pytest.fixture()
def user_id(client, auth_headers, db_session) -> str:
    with db_session.cursor() as cur:
        cur.execute('SELECT "id" FROM "User" LIMIT 1')
        return cur.fetchone()[0]


def _make_job(user_id: str, *, description: str) -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Senior Delivery Lead", "ExampleCorp",
                    "Sydney NSW", False, description, json.dumps([]),
                    "adzuna", f"https://example.com/{job_id}", 82.0,
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


def _make_application(user_id: str, job_id: str, resume_id: str, *, status: str) -> str:
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Application"
                   ("id","userId","jobId","resumeId","status","coverLetter",
                    "createdAt","updatedAt")
                   VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,NOW(),NOW())''',
                (
                    app_id, user_id, job_id, resume_id, status,
                    "Dear Hiring Manager,\n\nI am excited to apply.\n\nJordan Blake",
                ),
            )
        conn.commit()
    return app_id


def _seed_submittable(user_id: str, *, description: str) -> tuple[str, str, str]:
    """``(job_id, resume_id, application_id)`` for a ready-to-transmit app."""
    job_id = _make_job(user_id, description=description)
    resume_id = _make_resume(user_id, source_job_id=job_id)
    app_id = _make_application(user_id, job_id, resume_id, status="submitted")
    return job_id, resume_id, app_id


class _SendRecorder:
    """Substitutes the Gmail transport ONLY — everything above it is real."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def install(self, monkeypatch) -> None:
        from app.services import gmail_service as gmail_module

        recorder = self

        def _fake_send(self_svc, **kwargs):  # noqa: ANN001
            recorder.calls.append(kwargs)
            return {"id": f"gmail-msg-{len(recorder.calls)}", "threadId": "thread-1"}

        monkeypatch.setattr(
            gmail_module.GmailService, "send", _fake_send, raising=True
        )
        monkeypatch.setattr(
            "app.repositories.gmail_account.GmailAccountRepository.is_connected",
            lambda self_repo, uid: True,
            raising=True,
        )


# ---------------------------------------------------------------------------
# 1. Recipient derivation — real posting data only.
# ---------------------------------------------------------------------------


class TestRecipientDerivation:
    def test_mailto_in_description_is_a_real_recipient(self, client, auth_headers, user_id):
        from app.services.application_submission import resolve_job_apply_recipient

        job_id = _make_job(user_id, description=_MAILTO_DESCRIPTION)
        recipient = resolve_job_apply_recipient(user_id, job_id)
        assert recipient is not None
        assert recipient["email"] == "careers@examplecorp.com"
        assert recipient["source"] == "description_mailto"

    def test_no_contact_means_not_auto_submittable(self, client, auth_headers, user_id):
        from app.services.application_submission import resolve_job_apply_recipient

        job_id = _make_job(user_id, description=_NO_CONTACT_DESCRIPTION)
        assert resolve_job_apply_recipient(user_id, job_id) is None

    def test_noreply_address_is_not_a_real_recipient(self, client, auth_headers, user_id):
        from app.services.application_submission import derive_apply_recipient

        assert derive_apply_recipient(
            "Questions? mailto:no-reply@examplecorp.com"
        ) is None

    @pytest.mark.parametrize(
        "paragraph",
        [
            # VERBATIM production text (Job "Staff Program Manager, Trust &
            # Safety" @ Mozilla, read from the aether schema on 2026-08-02).
            "We will ensure that qualified individuals with disabilities are "
            "provided reasonable accommodations to participate in the job "
            "application or interview process, to perform essential job "
            "functions, and to receive other benefits and privileges of "
            "employment, as appropriate. Please contact us at "
            "hiringaccommodation@mozilla.com to request accommodation. We are "
            "an equal opportunity employer.",
            "Netlify is an equal opportunity employer. If you need assistance "
            "or an accommodation, contact accommodations@netlify.com.",
            "Peloton provides reasonable accommodation to applicants with "
            "disabilities — email applicantaccommodations@onepeloton.com.",
        ],
    )
    def test_accommodation_addresses_are_never_treated_as_apply_inboxes(
        self, client, auth_headers, user_id, paragraph
    ):
        """The FIRST production dry-run of the backfill found exactly four
        published addresses across all 66 stored job descriptions — and every
        one was a disability-accommodation request line inside EEO
        boilerplate, not an application inbox. Emailing an application there
        would both misdirect the application and misuse a channel reserved for
        disabled applicants. These must derive to ``None``."""
        from app.services.application_submission import derive_apply_recipient

        assert derive_apply_recipient(paragraph) is None

    def test_privacy_and_eeo_contacts_are_excluded(self, client, auth_headers, user_id):
        from app.services.application_submission import derive_apply_recipient

        assert derive_apply_recipient(
            "See our privacy policy; data protection queries to dpo@examplecorp.com. "
            "Apply now!"
        ) is None


# ---------------------------------------------------------------------------
# 2. Execute — the real transmission.
# ---------------------------------------------------------------------------


class TestExecuteTransmits:
    def _approve(self, client, auth_headers, approval_id: str) -> None:
        resp = client.post(f"/approvals/{approval_id}/approve", headers=auth_headers)
        assert resp.status_code == 200, resp.text

    def test_refuses_when_no_genuine_recipient(self, client, auth_headers, user_id, monkeypatch):
        from app.services.application_submission import queue_submission_approval

        recorder = _SendRecorder()
        recorder.install(monkeypatch)
        job_id, resume_id, app_id = _seed_submittable(
            user_id, description=_NO_CONTACT_DESCRIPTION
        )
        # No recipient => nothing may be queued for autonomous transmission.
        assert queue_submission_approval(user_id, job_id, app_id, resume_id) is None

        # A submission approval raised without a recipient must refuse, not
        # pretend. (Built directly so the refusal path is provably reachable.)
        from app.repositories.approval import ApprovalRepository

        approval = ApprovalRepository().create(
            user_id,
            "application_submit",
            {"kind": "submission", "job_id": job_id, "application_id": app_id},
            application_id=app_id,
        )
        self._approve(client, auth_headers, approval["id"])
        resp = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert resp.status_code == 422, resp.text
        assert recorder.calls == []
        # The failed attempt must NOT burn the approval.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "executedAt" FROM "ApprovalRequest" WHERE "id" = %s',
                    (approval["id"],),
                )
                assert cur.fetchone()[0] is None

    def test_transmits_with_attachments_and_records_it(
        self, client, auth_headers, user_id, monkeypatch
    ):
        from app.services.application_submission import queue_submission_approval

        recorder = _SendRecorder()
        recorder.install(monkeypatch)
        job_id, resume_id, app_id = _seed_submittable(
            user_id, description=_MAILTO_DESCRIPTION
        )
        approval = queue_submission_approval(user_id, job_id, app_id, resume_id)
        assert approval is not None
        self._approve(client, auth_headers, approval["id"])

        resp = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "transmitted"
        assert body["to"] == "careers@examplecorp.com"

        assert len(recorder.calls) == 1
        sent = recorder.calls[0]
        assert sent["to"] == "careers@examplecorp.com"
        assert "Senior Delivery Lead" in sent["subject"]
        attachments = sent["attachments"]
        assert len(attachments) == 2, attachments
        names = [a[0] for a in attachments]
        assert any(n.startswith("resume-") and n.endswith(".pdf") for n in names)
        assert any(n.startswith("cover-letter-") and n.endswith(".pdf") for n in names)
        for _name, data, mimetype in attachments:
            assert mimetype == "application/pdf"
            assert data[:4] == b"%PDF", "attachment must be real PDF bytes"

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "executedAt" FROM "ApprovalRequest" WHERE "id" = %s',
                    (approval["id"],),
                )
                assert cur.fetchone()[0] is not None
                cur.execute(
                    'SELECT "status", "transmittedAt", "transmittedTo", '
                    '"transmissionChannel", "transmissionRef" '
                    'FROM "Application" WHERE "id" = %s',
                    (app_id,),
                )
                row = cur.fetchone()
        assert row[0] == "submitted"
        assert row[1] is not None
        assert row[2] == "careers@examplecorp.com"
        assert row[3] == "gmail"
        assert row[4] == "gmail-msg-1"

    def test_second_execute_is_a_409_and_sends_nothing(
        self, client, auth_headers, user_id, monkeypatch
    ):
        from app.services.application_submission import queue_submission_approval

        recorder = _SendRecorder()
        recorder.install(monkeypatch)
        job_id, resume_id, app_id = _seed_submittable(
            user_id, description=_MAILTO_DESCRIPTION
        )
        approval = queue_submission_approval(user_id, job_id, app_id, resume_id)
        assert approval is not None
        self._approve(client, auth_headers, approval["id"])
        first = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert first.status_code == 200, first.text
        second = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert second.status_code == 409, second.text
        assert len(recorder.calls) == 1

    def test_pending_approval_cannot_transmit(
        self, client, auth_headers, user_id, monkeypatch
    ):
        from app.services.application_submission import queue_submission_approval

        recorder = _SendRecorder()
        recorder.install(monkeypatch)
        job_id, resume_id, app_id = _seed_submittable(
            user_id, description=_MAILTO_DESCRIPTION
        )
        approval = queue_submission_approval(user_id, job_id, app_id, resume_id)
        assert approval is not None
        assert approval["status"] == "pending"
        resp = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert resp.status_code == 403, resp.text
        assert recorder.calls == []

    def test_no_gmail_connected_refuses_without_pretending(
        self, client, auth_headers, user_id, monkeypatch
    ):
        from app.services.application_submission import queue_submission_approval

        monkeypatch.setattr(
            "app.repositories.gmail_account.GmailAccountRepository.is_connected",
            lambda self_repo, uid: False,
            raising=True,
        )
        job_id, resume_id, app_id = _seed_submittable(
            user_id, description=_MAILTO_DESCRIPTION
        )
        approval = queue_submission_approval(user_id, job_id, app_id, resume_id)
        assert approval is not None
        client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        resp = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert resp.status_code == 409, resp.text
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "transmittedAt" FROM "Application" WHERE "id" = %s', (app_id,)
                )
                assert cur.fetchone()[0] is None


def _set_agent_config(user_id: str, config: dict) -> None:
    from app.db import ensure_user_profile_columns

    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "agentConfig" = %s WHERE "id" = %s',
                (json.dumps(config), user_id),
            )
        conn.commit()


class TestApprovalGate:
    """Rule 4 of the brief: never send without a recorded approval or an
    explicit autonomous opt-in."""

    def test_apply_does_not_send_by_default(
        self, client, auth_headers, user_id, monkeypatch
    ):
        recorder = _SendRecorder()
        recorder.install(monkeypatch)
        job_id = _make_job(user_id, description=_MAILTO_DESCRIPTION)
        resume_id = _make_resume(user_id, source_job_id=job_id)
        _make_application(user_id, job_id, resume_id, status="draft")

        resp = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        submission = resp.json()["submission"]
        assert submission["queued"] is True
        assert submission.get("autonomous") is not True
        assert recorder.calls == [], "the approval gate must hold by default"

    def test_apply_reports_honestly_when_not_auto_submittable(
        self, client, auth_headers, user_id, monkeypatch
    ):
        recorder = _SendRecorder()
        recorder.install(monkeypatch)
        job_id = _make_job(user_id, description=_NO_CONTACT_DESCRIPTION)
        resume_id = _make_resume(user_id, source_job_id=job_id)
        _make_application(user_id, job_id, resume_id, status="draft")

        submission = client.post(
            f"/jobs/{job_id}/apply", headers=auth_headers
        ).json()["submission"]
        assert submission["queued"] is False
        assert submission["autoSubmittable"] is False
        assert submission["reason"] == "no_published_recipient"
        assert recorder.calls == []

    def test_explicit_autonomous_optin_transmits_and_records_the_authorisation(
        self, client, auth_headers, user_id, monkeypatch
    ):
        # RUN-20260818T0223Z AUTO-APPLY killswitch — added deliberately as a
        # SAFETY TIGHTENING (not a weakening), per the AUTO-APPLY-enablement
        # decision memo: autonomous transmission now ALSO requires the
        # operator switch AETHER_APPLY_SWEEP_ENABLED to be on — the same
        # switch the sweep already honoured — on top of the user's own
        # opt-in exercised below. See
        # test_cli_d1d2_real_toggles.TestOperatorKillSwitchGatesAutonomousTransmit
        # for the switch-off coverage this addition requires.
        monkeypatch.setenv("AETHER_APPLY_SWEEP_ENABLED", "true")
        recorder = _SendRecorder()
        recorder.install(monkeypatch)
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": False, "matchThreshold": 80}
        )
        job_id = _make_job(user_id, description=_MAILTO_DESCRIPTION)
        resume_id = _make_resume(user_id, source_job_id=job_id)
        _make_application(user_id, job_id, resume_id, status="draft")

        submission = client.post(
            f"/jobs/{job_id}/apply", headers=auth_headers
        ).json()["submission"]
        assert submission["autonomous"] is True
        assert submission["transmitted"] is True
        assert len(recorder.calls) == 1
        assert recorder.calls[0]["to"] == "careers@examplecorp.com"
        # The authorisation is WRITTEN DOWN, not implicit.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "status", "executedAt", "payload" '
                    'FROM "ApprovalRequest" WHERE "id" = %s',
                    (submission["approvalId"],),
                )
                status_, executed_at, payload = cur.fetchone()
        assert status_ == "approved"
        assert executed_at is not None
        assert payload["autonomous"] is True

    def test_autoapply_alone_is_not_an_optout_of_the_gate(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """``autoApply`` without turning ``approvalGate`` off must NOT send —
        the gate is the setting that authorises an un-reviewed outbound
        email, and the safe reading of an ambiguous pair is 'ask'."""
        recorder = _SendRecorder()
        recorder.install(monkeypatch)
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": True, "matchThreshold": 80}
        )
        job_id = _make_job(user_id, description=_MAILTO_DESCRIPTION)
        resume_id = _make_resume(user_id, source_job_id=job_id)
        _make_application(user_id, job_id, resume_id, status="draft")

        client.post(f"/jobs/{job_id}/apply", headers=auth_headers)
        assert recorder.calls == []

    def test_operator_switch_off_falls_back_to_the_normal_approval_gated_flow(
        self, client, auth_headers, user_id, monkeypatch
    ):
        """RUN-20260818T0223Z AUTO-APPLY killswitch, end-to-end via the real
        Apply-click endpoint. Even a fully opted-in user (autoApply true,
        approvalGate false) must NOT be auto-sent while the operator's
        AETHER_APPLY_SWEEP_ENABLED switch is off — Apply-click must return
        the SAME honest, non-autonomous "queued for approval" shape it
        already returns for any other blocked gate: no fake 'transmitted',
        no dropped application, an approvalId the user can still act on."""
        recorder = _SendRecorder()
        recorder.install(monkeypatch)
        monkeypatch.delenv("AETHER_APPLY_SWEEP_ENABLED", raising=False)
        _set_agent_config(
            user_id, {"autoApply": True, "approvalGate": False, "matchThreshold": 80}
        )
        job_id = _make_job(user_id, description=_MAILTO_DESCRIPTION)
        resume_id = _make_resume(user_id, source_job_id=job_id)
        _make_application(user_id, job_id, resume_id, status="draft")

        submission = client.post(
            f"/jobs/{job_id}/apply", headers=auth_headers
        ).json()["submission"]

        assert recorder.calls == [], "no send may reach the provider"
        assert submission["queued"] is True
        assert submission.get("autonomous") is not True
        assert submission.get("transmitted") is not True
        assert "approvalId" in submission, "the card must still be reachable"
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "status", "executedAt" FROM "ApprovalRequest" WHERE "id" = %s',
                    (submission["approvalId"],),
                )
                status_, executed_at = cur.fetchone()
        assert status_ == "pending", "the approval must not be burned by a blocked switch"
        assert executed_at is None


# ---------------------------------------------------------------------------
# 3. Truthful presentation of the never-transmitted rows.
# ---------------------------------------------------------------------------


class TestTruthfulPresentation:
    def test_untransmitted_application_is_not_presented_as_sent(
        self, client, auth_headers, user_id
    ):
        job_id, resume_id, app_id = _seed_submittable(
            user_id, description=_NO_CONTACT_DESCRIPTION
        )
        listing = client.get("/applications", headers=auth_headers)
        assert listing.status_code == 200, listing.text
        row = next(a for a in listing.json() if a["id"] == app_id)
        assert row["status"] == "submitted"  # history is NOT rewritten
        assert row["transmitted"] is False
        assert row["submissionState"] == "not_transmitted"
        assert row["autoSubmittable"] is False

        detail = client.get(f"/applications/{app_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["transmitted"] is False
        assert detail.json()["submissionState"] == "not_transmitted"

    def test_transmitted_application_reads_as_sent(
        self, client, auth_headers, user_id, monkeypatch
    ):
        from app.services.application_submission import queue_submission_approval

        recorder = _SendRecorder()
        recorder.install(monkeypatch)
        job_id, resume_id, app_id = _seed_submittable(
            user_id, description=_MAILTO_DESCRIPTION
        )
        approval = queue_submission_approval(user_id, job_id, app_id, resume_id)
        client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        assert (
            client.post(
                f"/approvals/{approval['id']}/execute", headers=auth_headers
            ).status_code
            == 200
        )
        row = next(
            a
            for a in client.get("/applications", headers=auth_headers).json()
            if a["id"] == app_id
        )
        assert row["transmitted"] is True
        assert row["submissionState"] == "transmitted"
        assert row["transmittedTo"] == "careers@examplecorp.com"
