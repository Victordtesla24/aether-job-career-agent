"""Receipt-before-Submitted: Gmail application receipts, not a page click."""
from __future__ import annotations

from email.utils import formatdate

from app.services.apply_receipt_inbox import (
    is_application_receipt,
    poll_application_receipt,
    ReceiptMailboxUnavailable,
)
from app.services.gmail_service import GmailAuthError, GmailNotConnectedError


def _header(
    *,
    subject: str,
    from_addr: str,
    epoch: float,
    message_id: str = "msg-1",
) -> dict:
    return {
        "id": message_id,
        "threadId": "thr-1",
        "from": from_addr,
        "subject": subject,
        "date": formatdate(epoch, usegmt=True),
        "internalDate": str(int(epoch * 1000)),
    }


SUBMITTED_AT = 1_700_000_000.0


def test_ashby_receipt_naming_the_role_is_proof():
    header = _header(
        subject="Thank you for applying to Senior Platform Engineer at Dovetail",
        from_addr="Dovetail <notifications@ashbyhq.com>",
        epoch=SUBMITTED_AT + 20,
    )
    assert is_application_receipt(
        header,
        company="Dovetail",
        job_title="Senior Platform Engineer",
        since_epoch=SUBMITTED_AT,
    )


def test_older_receipt_for_the_same_employer_is_not_this_attempt():
    header = _header(
        subject="Thank you for applying to Senior Platform Engineer at Dovetail",
        from_addr="notifications@ashbyhq.com",
        epoch=SUBMITTED_AT - 3600,
    )
    assert not is_application_receipt(
        header,
        company="Dovetail",
        job_title="Senior Platform Engineer",
        since_epoch=SUBMITTED_AT,
    )


def test_verification_code_mail_is_not_a_receipt():
    header = _header(
        subject="Your Greenhouse security code",
        from_addr="no-reply@greenhouse-mail.io",
        epoch=SUBMITTED_AT + 10,
    )
    assert not is_application_receipt(
        header,
        company="Databricks",
        job_title="Data Scientist",
        since_epoch=SUBMITTED_AT,
    )


def test_unrelated_ats_mail_without_employer_or_role_is_not_proof():
    header = _header(
        subject="New jobs this week",
        from_addr="alerts@ashbyhq.com",
        epoch=SUBMITTED_AT + 10,
    )
    assert not is_application_receipt(
        header,
        company="Dovetail",
        job_title="Senior Platform Engineer",
        since_epoch=SUBMITTED_AT,
    )


def test_github_application_wording_is_not_an_employer_receipt():
    header = _header(
        subject="[GitHub] Application for aether-job-career-agent",
        from_addr="notifications@github.com",
        epoch=SUBMITTED_AT + 10,
    )
    assert not is_application_receipt(
        header,
        company="Dovetail",
        job_title="Senior Platform Engineer",
        since_epoch=SUBMITTED_AT,
    )


class _Mailbox:
    def __init__(self, headers: list[dict], bodies: dict[str, dict] | None = None):
        self.headers = headers
        self.bodies = bodies or {}
        self.list_calls = 0

    def list_message_headers(self, query=None, max_results=100):
        self.list_calls += 1
        return list(self.headers)

    def get_message_bodies(self, message_id: str):
        return self.bodies.get(message_id) or {
            "id": message_id,
            "text": "",
            "html": "",
        }


def test_poll_returns_the_receipt_from_the_second_connected_inbox():
    miss = _Mailbox([])
    hit = _Mailbox(
        [
            _header(
                subject="We have received your application to Staff Engineer at Acme",
                from_addr="jobs@hire.lever.co",
                epoch=SUBMITTED_AT + 8,
                message_id="msg-lever",
            )
        ]
    )
    boxes = {"acct-a": miss, "acct-b": hit}

    def factory(user_id: str, account_id: str | None = None):
        assert user_id == "user-1"
        return boxes[str(account_id)]

    found = poll_application_receipt(
        "user-1",
        since_epoch=SUBMITTED_AT,
        company="Acme",
        job_title="Staff Engineer",
        gmail_factory=factory,
        account_ids=["acct-a", "acct-b"],
        sleeper=lambda _s: None,
        monotonic=lambda: SUBMITTED_AT,
        timeout_seconds=0.0,
        interval_seconds=0.0,
    )
    assert found is not None
    assert found["messageId"] == "msg-lever"
    assert found["accountId"] == "acct-b"


def test_poll_times_out_when_no_mailbox_has_a_matching_receipt():
    empty = _Mailbox([])

    def factory(user_id: str, account_id: str | None = None):
        return empty

    clock = {"t": 0.0}

    def monotonic():
        return clock["t"]

    def sleeper(_seconds: float):
        clock["t"] += 10.0

    found = poll_application_receipt(
        "user-1",
        since_epoch=SUBMITTED_AT,
        company="Acme",
        job_title="Staff Engineer",
        gmail_factory=factory,
        account_ids=["acct-a"],
        sleeper=sleeper,
        monotonic=monotonic,
        timeout_seconds=15.0,
        interval_seconds=10.0,
    )
    assert found is None
    assert empty.list_calls >= 2


def test_poll_raises_when_every_grant_is_gone():
    def factory(user_id: str, account_id: str | None = None):
        raise GmailNotConnectedError("not connected")

    try:
        poll_application_receipt(
            "user-1",
            since_epoch=SUBMITTED_AT,
            company="Acme",
            job_title="Staff Engineer",
            gmail_factory=factory,
            account_ids=["acct-a"],
            sleeper=lambda _s: None,
            timeout_seconds=0.0,
        )
    except ReceiptMailboxUnavailable:
        return
    raise AssertionError("expected ReceiptMailboxUnavailable")


def test_poll_raises_on_revoked_grant():
    def factory(user_id: str, account_id: str | None = None):
        raise GmailAuthError("revoked")

    try:
        poll_application_receipt(
            "user-1",
            since_epoch=SUBMITTED_AT,
            company="Acme",
            job_title="Staff Engineer",
            gmail_factory=factory,
            account_ids=["acct-a"],
            sleeper=lambda _s: None,
            timeout_seconds=0.0,
        )
    except ReceiptMailboxUnavailable:
        return
    raise AssertionError("expected ReceiptMailboxUnavailable")
