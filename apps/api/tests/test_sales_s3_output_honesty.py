"""S3 — the run result must EXPLAIN ITSELF.

Live defect: the owner's manual run returned all zeros with nothing saying why.
Zeros are only trustworthy when they carry their own explanation, so every run
now reports, per Gmail account, what was actually scanned and over what window,
plus one plain sentence a founder can read without opening a log.

Pinned here: the ``accounts`` array (email / scanned / skippedAutomated /
backlogRemaining / scanWindow) and the ``explanation`` sentence, including the
two zero cases that previously looked identical — "nothing new arrived" versus
"no mailbox is connected at all".
"""
from __future__ import annotations

import time
import uuid

from tests._sales_fakes import RecordingLLM, WindowedGmail, agent_for, make_message
from tests.test_sales_agent import (  # type: ignore[import-untyped]
    _email,
    admin_headers,  # noqa: F401 — fixture
    repo,  # noqa: F401 — fixture
    sales_env,  # noqa: F401 — fixture
)


def _acct() -> str:
    return f"acct-s3-{uuid.uuid4().hex[:10]}"


def _noise_llm() -> RecordingLLM:
    return RecordingLLM({"category": "noise", "confidence": 0.95, "reason": "internal"})


def test_every_run_reports_per_account_scan_facts(repo, sales_env, monkeypatch):  # noqa: F811
    account_id = _acct()
    now = int(time.time())
    fake = WindowedGmail([
        make_message(sender=_email("prospect"), subject="Question about pricing",
                     text="Interested — how does pricing work?", epoch=now - 3600),
        make_message(sender="notifications@github.com", name="GitHub",
                     subject="Run failed", text="CI failed.", epoch=now - 7200),
    ])
    agent = agent_for(repo, fake, monkeypatch, account_id=account_id, llm=_noise_llm())

    result = agent.run(trigger="manual")

    accounts = result["accounts"]
    assert isinstance(accounts, list) and len(accounts) == 1
    entry = accounts[0]
    assert entry["email"] == f"{account_id}@aether.local"
    assert entry["scanned"] == 2
    assert entry["skippedAutomated"] == 1
    assert entry["backlogRemaining"] is False
    window = entry["scanWindow"]
    assert set(window) >= {"fromEpoch", "toEpoch"}
    assert int(window["fromEpoch"]) < int(window["toEpoch"]) <= now + 5


def test_zero_result_explains_itself(repo, sales_env, monkeypatch):  # noqa: F811
    """The owner's exact complaint: all zeros, no explanation."""
    fake = WindowedGmail([])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=_noise_llm())

    result = agent.run(trigger="manual")

    assert result["inboundScanned"] == 0 and result["leadsCreated"] == 0
    explanation = result["explanation"]
    assert isinstance(explanation, str) and explanation.strip()
    assert "0" in explanation
    # It states the backlog is clear, so a zero is not "we never looked".
    assert "backlog" in explanation.lower()


def test_no_sending_account_is_a_distinct_explanation(repo, sales_env, monkeypatch):  # noqa: F811
    fake = WindowedGmail([])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=_noise_llm())
    monkeypatch.setattr(repo, "sales_sending_accounts", lambda user_id: [])

    result = agent.run(trigger="manual")

    assert result["noSendingAccount"] is True
    assert result["accounts"] == []
    explanation = result["explanation"]
    assert "no gmail account" in explanation.lower()


def test_backlog_in_progress_is_disclosed_in_the_explanation(
    repo, sales_env, monkeypatch  # noqa: F811
):
    from app.agents.sales_agent import INBOUND_MAX_RESULTS

    now = int(time.time())
    fake = WindowedGmail([
        make_message(sender=f"b-{i}@example.com", subject="Weekly notes",
                     text="Notes from the meeting.", epoch=now - (i + 1) * 3600)
        for i in range(INBOUND_MAX_RESULTS + 5)
    ])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=_noise_llm())

    result = agent.run(trigger="manual")

    assert result["accounts"][0]["backlogRemaining"] is True
    assert "backlog" in result["explanation"].lower()


def test_explanation_is_one_sentence(repo, sales_env, monkeypatch):  # noqa: F811
    """Founder-readable means ONE sentence, not a paragraph of telemetry."""
    fake = WindowedGmail([])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=_noise_llm())

    explanation = agent.run(trigger="manual")["explanation"]

    assert explanation.count(".") <= 1
    assert "\n" not in explanation
