"""Job-alert email intake — agent mode + persistence (W-ALERT).

``EmailAgent.run(mode="job_alerts")`` scans EVERY connected mailbox for the
candidate's own automated job-alert mail and persists the postings it can read
as real ``Job`` rows through the EXISTING ``JobRepository.create`` path.

The Gmail client is faked (there is no way to make a real OAuth round-trip from
the test suite) but the MESSAGES it returns are the REAL alert emails captured
from the operator's own mailboxes on 2026-08-02 and anonymised — see
``tests/data/job_alerts/`` and the header of ``test_job_alert_parser.py``. The
Job rows asserted below are therefore produced from real market data end to
end, and the repository, dedup and ``lastSeenAt`` behaviour under test is the
production one.

Fail-before: ``EmailAgent`` has no ``job_alerts`` mode, so ``run(...)`` raises
``EmailAgentError("Unknown email agent mode 'job_alerts'")``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.email_agent import EmailAgent
from app.db import get_connection, rows_to_dicts

_DATA = Path(__file__).parent / "data" / "job_alerts"

SEEK_FROM = "SEEK Job Alerts <jobmail@s.seek.com.au>"
SEEK_SUBJECT_EA = "20 new jobs for enterprise architect in Melbourne VIC 3000"
SEEK_SUBJECT_PM = "20 new jobs for senior project manager in Melbourne VIC 3000"
MP_FROM = "Michael Page Australia <noreply@mail.michaelpage.com.au>"
MP_SUBJECT = "New jobs for: Information Technology : Melbourne"


def _read(name: str) -> str:
    return (_DATA / name).read_text()


def _seek_message(msg_id: str, subject: str, filename: str) -> dict:
    return {
        "id": msg_id,
        "from": SEEK_FROM,
        "subject": subject,
        "date": "Sun, 02 Aug 2026 01:38:08 +1000",
        "text": _read(filename),
        "html": "",
    }


def _michael_page_message(msg_id: str) -> dict:
    return {
        "id": msg_id,
        "from": MP_FROM,
        "subject": MP_SUBJECT,
        "date": "Sat, 01 Aug 2026 18:16:36 +1000",
        "text": "",
        "html": _read("michaelpage-job-alert.html"),
    }


#: A real non-alert message from the same 7-day window — it must be scanned and
#: then ignored, never turned into a Job row.
NOISE_MESSAGE = {
    "id": "noise-1",
    "from": "Adobe <noreply@adobe.com>",
    "subject": "Your payment failed",
    "date": "Sun, 02 Aug 2026 02:00:00 +1000",
    "text": "Update your payment method.",
    "html": "",
}


class _FakeMailbox:
    """One connected mailbox holding a fixed list of real messages."""

    def __init__(self, messages: list[dict], error: Exception | None = None) -> None:
        self.messages = messages
        self.error = error
        self.queries: list[str] = []
        self.bodies_fetched: list[str] = []

    def list_message_headers(self, query=None, max_results=100):
        if self.error is not None:
            raise self.error
        self.queries.append(query)
        return [
            {k: m[k] for k in ("id", "from", "subject", "date")}
            for m in self.messages[:max_results]
        ]

    def get_message_bodies(self, message_id):
        self.bodies_fetched.append(message_id)
        for m in self.messages:
            if m["id"] == message_id:
                return m
        raise LookupError(message_id)


class _FakeGmailFactory:
    """Routes ``for_account(id)`` to the right fake mailbox (GAP-D2 shape)."""

    def __init__(self, by_account: dict[str, _FakeMailbox]) -> None:
        self.by_account = by_account

    def for_account(self, account_id):
        return self.by_account[account_id]


class _FakeCredentials:
    def __init__(self, accounts: list[dict]) -> None:
        self._accounts = accounts

    def is_connected(self, user_id):
        return bool(self._accounts)

    def list_accounts(self, user_id):
        return list(self._accounts)


def _accounts() -> list[dict]:
    return [
        {"id": "acct-primary", "accountEmail": "primary@example.com"},
        {"id": "acct-secondary", "accountEmail": "secondary@example.com"},
    ]


def _jobs_for(user_id: str) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "title", "company", "location", "source", "sourceUrl",'
                ' "description", "salaryMin", "salaryMax", "postedAt", "lastSeenAt"'
                ' FROM "Job" WHERE "userId" = %s ORDER BY "sourceUrl"',
                (user_id,),
            )
            return rows_to_dicts(cur)


# ---------------------------------------------------------------- the mode
def test_job_alerts_mode_persists_real_postings_from_both_mailboxes(test_user_id):
    gmail = _FakeGmailFactory(
        {
            # The operator's PRIMARY mailbox holds only non-alert mail plus the
            # Michael Page alert; the alerts land in the SECONDARY one.
            "acct-primary": _FakeMailbox([NOISE_MESSAGE, _michael_page_message("mp-1")]),
            "acct-secondary": _FakeMailbox(
                [
                    _seek_message(
                        "seek-1",
                        SEEK_SUBJECT_EA,
                        "seek-job-alert-enterprise-architect.txt",
                    ),
                    _seek_message(
                        "seek-2",
                        SEEK_SUBJECT_PM,
                        "seek-job-alert-senior-project-manager.txt",
                    ),
                ]
            ),
        }
    )
    agent = EmailAgent(credentials=_FakeCredentials(_accounts()), gmail=gmail)
    result = agent.run(test_user_id, mode="job_alerts")

    assert result.mode == "job_alerts"
    # Deterministic parser — a job-alert run must NEVER be billed as an LLM run.
    assert result.llm_called is False
    assert result.accounts_scanned == 2
    assert result.messages_scanned == 4
    assert result.alert_emails == 3  # 2 SEEK + 1 Michael Page
    assert result.platforms == {"seek": 2, "michaelpage": 1}
    # 23 postings per SEEK alert; Michael Page yields none (no company).
    assert result.postings_extracted == 46
    assert result.postings_skipped == 2

    rows = _jobs_for(test_user_id)
    # Job 93654381 appears in BOTH alerts, so 46 postings dedup to 45 rows.
    assert len(rows) == 45
    assert result.jobs_created == 45
    assert result.jobs_updated == 1

    assert {r["source"] for r in rows} == {"seek-alert"}
    talent = next(
        r for r in rows if r["sourceUrl"] == "https://au.seek.com/job/93696282"
    )
    assert talent["title"] == "Solution Architect"
    assert talent["company"] == "Talent"
    assert talent["location"] == "Melbourne VIC"
    # lastSeenAt is stamped by the shared repository path — these rows are live.
    assert talent["lastSeenAt"] is not None


def test_alert_rows_never_carry_an_invented_salary_or_description(test_user_id):
    gmail = _FakeGmailFactory(
        {
            "acct-primary": _FakeMailbox([]),
            "acct-secondary": _FakeMailbox(
                [
                    _seek_message(
                        "seek-1",
                        SEEK_SUBJECT_EA,
                        "seek-job-alert-enterprise-architect.txt",
                    )
                ]
            ),
        }
    )
    EmailAgent(credentials=_FakeCredentials(_accounts()), gmail=gmail).run(
        test_user_id, mode="job_alerts"
    )
    rows = _jobs_for(test_user_id)
    assert rows
    for row in rows:
        # A job-alert email contains no salary figures we can trust and no job
        # description at all — neither may be synthesised.
        assert row["salaryMin"] is None
        assert row["salaryMax"] is None
        assert len(row["description"]) < 200
        assert row["title"].strip() and row["company"].strip()
    posted = [r for r in rows if r["postedAt"] is not None]
    # Only the three "Jobs you may have missed" cards state a posting date.
    assert len(posted) == 3


def test_rerunning_the_same_alerts_creates_no_duplicate_rows(test_user_id):
    def _run():
        gmail = _FakeGmailFactory(
            {
                "acct-primary": _FakeMailbox([]),
                "acct-secondary": _FakeMailbox(
                    [
                        _seek_message(
                            "seek-1",
                            SEEK_SUBJECT_EA,
                            "seek-job-alert-enterprise-architect.txt",
                        )
                    ]
                ),
            }
        )
        return EmailAgent(
            credentials=_FakeCredentials(_accounts()), gmail=gmail
        ).run(test_user_id, mode="job_alerts")

    first = _run()
    count_after_first = len(_jobs_for(test_user_id))
    second = _run()
    assert first.jobs_created == 23
    assert second.jobs_created == 0
    assert second.jobs_updated == 23
    assert len(_jobs_for(test_user_id)) == count_after_first


def test_a_dead_mailbox_is_reported_and_the_other_still_runs(test_user_id):
    gmail = _FakeGmailFactory(
        {
            "acct-primary": _FakeMailbox([], error=RuntimeError("token revoked")),
            "acct-secondary": _FakeMailbox(
                [
                    _seek_message(
                        "seek-1",
                        SEEK_SUBJECT_EA,
                        "seek-job-alert-enterprise-architect.txt",
                    )
                ]
            ),
        }
    )
    result = EmailAgent(credentials=_FakeCredentials(_accounts()), gmail=gmail).run(
        test_user_id, mode="job_alerts"
    )
    assert result.degraded is True
    errored = [a for a in result.per_account if a["error"]]
    assert len(errored) == 1
    assert "token revoked" in errored[0]["error"]
    # The healthy mailbox still delivered its real postings.
    assert result.jobs_created == 23
    assert "reconnect" in result.message.lower()


def test_no_alerts_in_the_window_is_reported_honestly_not_as_success(test_user_id):
    gmail = _FakeGmailFactory(
        {
            "acct-primary": _FakeMailbox([NOISE_MESSAGE]),
            "acct-secondary": _FakeMailbox([]),
        }
    )
    result = EmailAgent(credentials=_FakeCredentials(_accounts()), gmail=gmail).run(
        test_user_id, mode="job_alerts"
    )
    assert result.alert_emails == 0
    assert result.postings_extracted == 0
    assert result.jobs_created == 0
    assert "no job-alert emails were found" in result.message
    assert _jobs_for(test_user_id) == []


def test_no_connected_mailbox_degrades_honestly(test_user_id):
    result = EmailAgent(credentials=_FakeCredentials([]), gmail=None).run(
        test_user_id, mode="job_alerts"
    )
    assert result.connected is False
    assert result.degraded is True
    assert result.jobs_created == 0
    assert "connect gmail" in result.message.lower()


def test_scan_window_is_bounded_and_passed_to_gmail(test_user_id):
    mailbox = _FakeMailbox([])
    gmail = _FakeGmailFactory({"acct-primary": mailbox, "acct-secondary": _FakeMailbox([])})
    agent = EmailAgent(credentials=_FakeCredentials(_accounts()), gmail=gmail)
    agent.run(test_user_id, mode="job_alerts")
    assert mailbox.queries == ["newer_than:7d"]
    # Out-of-range values are clamped, never trusted verbatim.
    agent.run(test_user_id, mode="job_alerts", days=9999)
    assert mailbox.queries[-1] == "newer_than:30d"


def test_only_alert_messages_have_their_body_fetched(test_user_id):
    """Body fetches are the expensive Gmail call — they must be spent only on
    messages that are genuinely alerts."""
    mailbox = _FakeMailbox(
        [
            NOISE_MESSAGE,
            _seek_message(
                "seek-1", SEEK_SUBJECT_EA, "seek-job-alert-enterprise-architect.txt"
            ),
        ]
    )
    gmail = _FakeGmailFactory({"acct-primary": mailbox, "acct-secondary": _FakeMailbox([])})
    EmailAgent(credentials=_FakeCredentials(_accounts()), gmail=gmail).run(
        test_user_id, mode="job_alerts"
    )
    assert mailbox.bodies_fetched == ["seek-1"]


# ------------------------------------------------------------- API surface
def test_job_alerts_is_reachable_as_a_real_agent_run(client, auth_headers, monkeypatch):
    """It must appear in agent-run history like every other agent, and must be
    priced at zero (no LLM call)."""
    from app.agents import email_agent as email_agent_module

    accounts = _accounts()
    gmail = _FakeGmailFactory(
        {
            "acct-primary": _FakeMailbox([]),
            "acct-secondary": _FakeMailbox(
                [
                    _seek_message(
                        "seek-1",
                        SEEK_SUBJECT_EA,
                        "seek-job-alert-enterprise-architect.txt",
                    )
                ]
            ),
        }
    )
    original_init = email_agent_module.EmailAgent.__init__

    def _patched(self, *args, **kwargs):
        kwargs.setdefault("credentials", _FakeCredentials(accounts))
        kwargs.setdefault("gmail", gmail)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(email_agent_module.EmailAgent, "__init__", _patched)

    response = client.post(
        "/agents/email/run", json={"mode": "job_alerts"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "job_alerts"
    assert body["jobs_created"] == 23
    assert body["run_id"]
    # A deterministic run is never charged and never stamps a model id.
    assert body["model"] is None
    assert body["costUsd"] == 0.0
    assert body["tokensIn"] == 0 and body["tokensOut"] == 0

    history = client.get("/agents/runs", headers=auth_headers)
    assert history.status_code == 200
    runs = history.json()
    assert any(
        r["agentName"] == "emailAgent" and (r.get("input") or {}).get("mode")
        == "job_alerts"
        for r in (runs if isinstance(runs, list) else runs.get("items", []))
    )


def test_approval_required_is_not_a_decorative_flag_on_an_intake_run(
    client, auth_headers, monkeypatch
):
    """MV-resume-studio-001: ``approvalRequired: true`` must be backed by a real
    ApprovalRequest. A ``job_alerts`` run persists its Job rows outright and
    opens no approval, so the flag must be False — while ``send``, the one
    emailAgent mode that DOES open one, must still report True.
    """
    from app.agents import email_agent as email_agent_module

    accounts = _accounts()
    gmail = _FakeGmailFactory(
        {"acct-primary": _FakeMailbox([]), "acct-secondary": _FakeMailbox([])}
    )
    original_init = email_agent_module.EmailAgent.__init__

    def _patched(self, *args, **kwargs):
        kwargs.setdefault("credentials", _FakeCredentials(accounts))
        kwargs.setdefault("gmail", gmail)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(email_agent_module.EmailAgent, "__init__", _patched)

    intake = client.post(
        "/agents/email/run", json={"mode": "job_alerts"}, headers=auth_headers
    )
    assert intake.status_code == 200, intake.text
    assert intake.json()["approvalRequired"] is False

    queued = client.post(
        "/agents/email/run",
        json={
            "mode": "send",
            "to": "recruiter@example.com",
            "subject": "Re: the role",
            "body": "Thanks for reaching out.",
        },
        headers=auth_headers,
    )
    assert queued.status_code == 200, queued.text
    sent = queued.json()
    assert sent["approvalRequired"] is True
    # …and the flag is backed by a real, pending approval row.
    assert sent["approval_id"] and sent["approval_status"] == "pending"
    approvals = client.get("/approvals?status=all", headers=auth_headers).json()
    assert [a for a in approvals if a["id"] == sent["approval_id"]]


def test_alert_sourced_rows_are_filterable_by_their_own_provenance(
    client, auth_headers, test_user_id, monkeypatch
):
    """The card shows "Seek alert email"; ``?source=seek-alert`` must therefore
    be a filter the API accepts, not a 422 — the alert channel is real and
    always available, it is just not a discovery ADAPTER."""
    from app.agents import email_agent as email_agent_module

    accounts = _accounts()
    gmail = _FakeGmailFactory(
        {
            "acct-primary": _FakeMailbox([]),
            "acct-secondary": _FakeMailbox(
                [
                    _seek_message(
                        "seek-1",
                        SEEK_SUBJECT_EA,
                        "seek-job-alert-enterprise-architect.txt",
                    )
                ]
            ),
        }
    )
    original_init = email_agent_module.EmailAgent.__init__

    def _patched(self, *args, **kwargs):
        kwargs.setdefault("credentials", _FakeCredentials(accounts))
        kwargs.setdefault("gmail", gmail)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(email_agent_module.EmailAgent, "__init__", _patched)
    assert (
        client.post(
            "/agents/email/run", json={"mode": "job_alerts"}, headers=auth_headers
        ).status_code
        == 200
    )

    listed = client.get("/jobs?source=seek-alert", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert rows, "alert-sourced rows must be reachable through the active feed"
    assert {r["source"] for r in rows} == {"seek-alert"}

    # An genuinely unknown source is still rejected honestly.
    bad = client.get("/jobs?source=not-a-real-source", headers=auth_headers)
    assert bad.status_code == 422
    assert "seek-alert" in bad.json()["detail"]


@pytest.mark.parametrize("mode", ["job_alerts", "job-alerts"])
def test_both_mode_spellings_dispatch(test_user_id, mode):
    gmail = _FakeGmailFactory(
        {"acct-primary": _FakeMailbox([]), "acct-secondary": _FakeMailbox([])}
    )
    result = EmailAgent(credentials=_FakeCredentials(_accounts()), gmail=gmail).run(
        test_user_id, mode=mode
    )
    assert result.mode == "job_alerts"
