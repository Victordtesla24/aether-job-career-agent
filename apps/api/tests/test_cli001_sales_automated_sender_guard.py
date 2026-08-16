"""CLI-001 (FABLE-SEC-01) — the sales agent must NEVER treat an automated /
no-reply / notification sender as an inbound sales signal.

Regression for the live incident where 19 real auto-replies were dispatched to
``notifications@github.com`` because GitHub CI mail tripped ``INTEREST_PHRASES``
("aether", "sign up", "question about", ...) and nothing checked the sender
address. A DB suppression of that one address was a band-aid; the root cause is
the missing automated-sender guard in the inbound classification path.

These tests exercise the real ``SalesAgent._poll_account`` pipeline through the
injected fake Gmail seam (same harness as ``test_sales_agent.py``), in DRY-RUN,
so nothing can leave the machine even before the guard exists.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.sales_agent import _is_automated_sender

# Reuse the proven fake-Gmail harness from the sibling suite.
from tests.test_sales_agent import (  # type: ignore[import-untyped]
    FakeGmail,
    _agent_with,
    _email,
    admin_headers,  # noqa: F401 — fixture
    repo,  # noqa: F401 — fixture
    sales_env,  # noqa: F401 — fixture
)


# --- unit: the classifier of the sender address itself -----------------------
@pytest.mark.parametrize(
    "addr,expected",
    [
        ("notifications@github.com", True),
        ("noreply@example.com", True),
        ("no-reply@linkedin.com", True),
        ("no_reply@service.io", True),
        ("donotreply@bank.com", True),
        ("do-not-reply@vendor.net", True),
        ("mailer-daemon@mail.example.com", True),
        ("postmaster@example.com", True),
        ("bounces@sendgrid.net", True),
        ("newsletter@substack.com", True),
        ("automated@ci.example.com", True),
        # Genuine humans must NOT be blocked (guard must not over-suppress):
        ("pat.prospect@example.com", False),
        ("vikram@gmail.com", False),
        ("hannah.lee@acmecorp.com", False),
        ("j.doe@bigco.com.au", False),
    ],
)
def test_is_automated_sender_classifies_correctly(addr: str, expected: bool) -> None:
    assert _is_automated_sender(addr) is expected


# --- pipeline: an automated sender is skipped, never engaged ------------------
@pytest.mark.parametrize(
    "automated_from",
    [
        "GitHub <notifications@github.com>",
        "Acme No-Reply <no-reply@acme.com>",
        "Mailer Daemon <mailer-daemon@mail.example.com>",
    ],
)
def test_automated_sender_is_never_engaged_even_with_interest_phrases(
    repo, sales_env, monkeypatch, automated_from  # noqa: F811
):
    """The message body deliberately trips INTEREST/DEMO phrases ("interested",
    "sign up", "aether", "pricing") — a genuine prospect with this text WOULD be
    engaged, but an automated sender must be skipped: no lead, no outreach row of
    any outcome, nothing sent, and it is counted as inboundSkippedAutomated."""
    fake = FakeGmail([
        {
            "id": f"m-{uuid.uuid4().hex[:12]}",
            "threadId": f"t-{uuid.uuid4().hex[:12]}",
            "from": automated_from,
            "subject": "You signed up — question about pricing for Aether",
            "text": "You are receiving notifications. Interested parties can sign up. "
                    "How does the Aether pricing work? Reply to this automated message.",
        }
    ])
    agent = _agent_with(repo, fake, monkeypatch)
    result = agent.run(trigger="manual")

    # Extract the bare address the pipeline saw.
    addr = automated_from.split("<")[-1].rstrip(">").strip().lower()

    assert result["ran"] is True
    # The automated sender must be skipped and counted; NOT engaged as a lead.
    # (result["dryRunLogged"] may be >0 from the unrelated owner digest — that
    #  path does not target the automated sender, which is what we assert below.)
    assert result["leadsCreated"] == 0, "must not create a lead for an automated sender"
    assert result.get("inboundSkippedAutomated", 0) >= 1
    assert repo.get_lead_by_email(addr) is None
    assert not any((s.get("to") or "").lower() == addr for s in fake.sent), (
        "nothing may be dispatched to an automated sender"
    )
    rows, _ = repo.list_outreach(limit=500)
    assert not any((r["recipient"] or "").lower() == addr for r in rows), (
        "no outreach row of any outcome may exist for an automated sender"
    )


@pytest.mark.parametrize(
    "automated_from",
    [
        "GitHub <notifications@github.com>",
        "Acme No-Reply <no-reply@acme.com>",
    ],
)
def test_automated_sender_gets_no_live_send(
    repo, sales_env, monkeypatch, automated_from  # noqa: F811
):
    """Direct reproduction of the live incident: in LIVE (non-dry-run) mode an
    automated sender whose body trips the interest phrases must receive NO live
    reply. Without the guard, ``fake.sent`` would contain a reply addressed to
    the automated sender (this is exactly how 19 replies reached
    notifications@github.com)."""
    monkeypatch.setenv("AETHER_SALES_AGENT_DRY_RUN", "false")
    fake = FakeGmail([
        {
            "id": f"m-{uuid.uuid4().hex[:12]}",
            "threadId": f"t-{uuid.uuid4().hex[:12]}",
            "from": automated_from,
            "subject": "You signed up — question about pricing for Aether",
            "text": "Interested parties can sign up. How does the Aether pricing work?",
        }
    ])
    agent = _agent_with(repo, fake, monkeypatch)
    result = agent.run(trigger="manual", dry_run=False)
    addr = automated_from.split("<")[-1].rstrip(">").strip().lower()

    assert result["dryRun"] is False
    assert result["leadsCreated"] == 0
    assert result.get("inboundSkippedAutomated", 0) >= 1
    assert not any((s.get("to") or "").lower() == addr for s in fake.sent), (
        "LIVE reply reached an automated sender — the incident is not fixed"
    )
    rows, _ = repo.list_outreach(limit=500)
    assert not any(
        (r["recipient"] or "").lower() == addr and r.get("outcome") == "sent"
        for r in rows
    ), "a 'sent' outreach row exists for an automated sender"


def test_real_prospect_with_same_text_is_still_engaged(repo, sales_env, monkeypatch):  # noqa: F811
    """Negative control: the guard must NOT suppress a genuine human prospect —
    the identical interest text from a normal address still produces a lead and a
    dry-run outreach row."""
    sender = _email("real-prospect")
    fake = FakeGmail([
        {
            "id": f"m-{uuid.uuid4().hex[:12]}",
            "threadId": f"t-{uuid.uuid4().hex[:12]}",
            "from": f"Real Prospect <{sender}>",
            "subject": "Question about pricing for Aether",
            "text": "I'm interested in Aether — how does the pricing work?",
        }
    ])
    agent = _agent_with(repo, fake, monkeypatch)
    result = agent.run(trigger="manual")

    assert result["leadsCreated"] == 1
    assert result.get("inboundSkippedAutomated", 0) == 0
    assert repo.get_lead_by_email(sender) is not None
