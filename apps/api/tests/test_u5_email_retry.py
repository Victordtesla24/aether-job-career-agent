"""U5 closing round 4 — a failed application email must be RETRYABLE for real.

The UI half of this fix surfaces an approved-but-unsent request with a
``Retry send`` button that re-invokes ``POST /approvals/{id}/execute``. That
button is only honest if the server behind it behaves exactly as advertised,
so this module pins the contract the button depends on:

1. a send that FAILS transmits nothing, releases the execution claim
   (``executedAt`` back to NULL) and therefore leaves the approval retryable;
2. the retry really transmits — same endpoint, no special-casing, and the
   ``Application`` row records the transmission;
3. a THIRD execute after a successful send is a 409 that sends nothing, so
   "retryable" never becomes "sendable twice";
4. ``GET /approvals`` exposes the ``executionState`` the UI derives the
   "not sent" chip from — ``None`` while nothing has been sent, ``executed``
   once the send provably returned.

No live Gmail call happens here: ``GmailService.send`` is the only substituted
seam, exactly as in ``test_wsub_real_submission`` (whose seeding helpers are
reused rather than re-invented), so everything above the transport is the real
production path.
"""
from __future__ import annotations

import pytest

from app.db import get_connection
from tests.test_wsub_real_submission import (
    _MAILTO_DESCRIPTION,
    _seed_submittable,
)


@pytest.fixture()
def user_id(client, auth_headers, db_session) -> str:
    with db_session.cursor() as cur:
        cur.execute('SELECT "id" FROM "User" LIMIT 1')
        return cur.fetchone()[0]


class _FlakyTransport:
    """Gmail transport that fails the first N sends, then succeeds.

    Models the real failure the retry exists for (an expired grant, a 5xx from
    Gmail) without ever contacting Google.
    """

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls: list[dict] = []

    def install(self, monkeypatch) -> None:
        from app.services import gmail_service as gmail_module

        transport = self

        def _fake_send(self_svc, **kwargs):  # noqa: ANN001
            transport.calls.append(kwargs)
            if len(transport.calls) <= transport.failures:
                raise gmail_module.GmailError("Gmail temporarily unavailable")
            return {"id": f"gmail-msg-{len(transport.calls)}", "threadId": "thread-1"}

        monkeypatch.setattr(gmail_module.GmailService, "send", _fake_send, raising=True)
        monkeypatch.setattr(
            "app.repositories.gmail_account.GmailAccountRepository.is_connected",
            lambda self_repo, uid: True,
            raising=True,
        )


def _executed_at(approval_id: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "executedAt" FROM "ApprovalRequest" WHERE "id" = %s',
                (approval_id,),
            )
            return cur.fetchone()[0]


def _transmission(application_id: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "transmittedAt", "transmittedTo", "transmissionRef" '
                'FROM "Application" WHERE "id" = %s',
                (application_id,),
            )
            return cur.fetchone()


def _row_from_list(client, auth_headers, approval_id: str, status: str) -> dict:
    resp = client.get(f"/approvals?status={status}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    matches = [row for row in resp.json() if row["id"] == approval_id]
    assert matches, f"approval {approval_id} missing from the {status} list"
    return matches[0]


class TestFailedSendIsRetryable:
    def _queue_and_approve(self, client, auth_headers, user_id) -> tuple[dict, str]:
        from app.services.application_submission import queue_submission_approval

        job_id, resume_id, app_id = _seed_submittable(
            user_id, description=_MAILTO_DESCRIPTION
        )
        approval = queue_submission_approval(user_id, job_id, app_id, resume_id)
        assert approval is not None
        resp = client.post(
            f"/approvals/{approval['id']}/approve", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        return approval, app_id

    def test_a_failed_send_releases_the_claim_and_the_retry_really_transmits(
        self, client, auth_headers, user_id, monkeypatch
    ):
        transport = _FlakyTransport(failures=1)
        transport.install(monkeypatch)
        approval, app_id = self._queue_and_approve(client, auth_headers, user_id)

        first = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert first.status_code == 502, first.text
        # Nothing was sent, and the approval is NOT burnt — the claim is released.
        assert _executed_at(approval["id"]) is None
        assert _transmission(app_id)[0] is None

        second = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert second.status_code == 200, second.text
        assert second.json()["status"] == "transmitted"
        assert second.json()["to"] == "careers@examplecorp.com"
        transmitted_at, to, ref = _transmission(app_id)
        assert transmitted_at is not None
        assert to == "careers@examplecorp.com"
        assert ref == "gmail-msg-2"

        # Retryable never means sendable twice.
        third = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert third.status_code == 409, third.text
        assert len(transport.calls) == 2, transport.calls

    def test_the_approvals_list_exposes_the_unsent_state_the_retry_reads(
        self, client, auth_headers, user_id, monkeypatch
    ):
        transport = _FlakyTransport(failures=1)
        transport.install(monkeypatch)
        approval, _app_id = self._queue_and_approve(client, auth_headers, user_id)

        failed = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert failed.status_code == 502, failed.text

        # This is the signal the "not sent" chip + Retry send button read: the
        # row is approved, and no execution was ever recorded against it.
        row = _row_from_list(client, auth_headers, approval["id"], "approved")
        assert row["status"] == "approved"
        assert row["type"] == "application_submit"
        assert row["payload"]["kind"] == "submission"
        assert row["executionState"] is None

        retried = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
        assert retried.status_code == 200, retried.text

        row = _row_from_list(client, auth_headers, approval["id"], "approved")
        assert row["executionState"] == "executed"
