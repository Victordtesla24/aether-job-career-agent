"""Sales Agent network nurture — consented CRM contacts only.

NW-ADV fence: nurture must NEVER send, even when dry_run is False and
``AETHER_SALES_AGENT_DRY_RUN=false``. CRM contacts are the candidate's
professional network — Recruiter Outreach (approval-gated) is the outbound
path. Nurture may only log ``dry_run`` / ``skipped_crm_not_sales``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.agents.sales_agent import SalesAgent
from app.repositories.sales import SalesRepository


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def test_network_nurture_dry_run_logs_without_sending(client, auth_headers, test_user_id, monkeypatch):
    monkeypatch.setenv("AETHER_SALES_AGENT_ENABLED", "true")
    monkeypatch.setenv("AETHER_SALES_AGENT_DRY_RUN", "true")
    repo = SalesRepository()
    repo.seed_default_campaigns()
    shared = _email("nurture")
    client.post(
        "/networking/contacts",
        json={"name": "Pat Connector", "email": shared, "company": "Acme"},
        headers=auth_headers,
    )
    repo.create_lead(
        email=shared,
        name="Pat Connector",
        source="manual_approved",
        consent_type="existing_relationship",
        consent_evidence=(
            "LinkedIn Connections.csv export uploaded by the account owner; "
            "first-degree connection 'Pat Connector'; email shared by the "
            "connection in their LinkedIn settings."
        ),
    )
    sent: list[str] = []

    class _NoSend:
        def send(self, **kwargs):  # noqa: ANN003
            sent.append(kwargs.get("to") or "")
            raise AssertionError("live send must not run in dry_run")

    agent = SalesAgent(repo=repo, gmail_factory=lambda *_a, **_k: _NoSend())
    result: dict = {
        "dryRunLogged": 0,
        "sent": 0,
        "suppressed": 0,
        "blocked": 0,
        "networkNurtured": 0,
        "errors": [],
    }
    agent._run_network_nurture(
        test_user_id, [], dry_run=True, result=result
    )
    assert result["networkNurtured"] >= 1
    assert result["dryRunLogged"] >= 1
    assert result["sent"] == 0
    assert sent == []
    rows, _total = repo.list_outreach(limit=20)
    recipients = {(r.get("recipient") or "").lower() for r in rows}
    assert shared in recipients
    outcomes = {r["outcome"] for r in rows if (r.get("recipient") or "").lower() == shared}
    assert "dry_run" in outcomes
    assert "sent" not in outcomes


def test_network_nurture_never_sends_even_when_live_mode(
    client, auth_headers, test_user_id, monkeypatch
):
    """NW-ADV fence: dry_run=False + DRY_RUN=false still must not Gmail.send."""
    monkeypatch.setenv("AETHER_SALES_AGENT_ENABLED", "true")
    monkeypatch.setenv("AETHER_SALES_AGENT_DRY_RUN", "false")
    repo = SalesRepository()
    repo.seed_default_campaigns()
    shared = _email("nurture-live")
    client.post(
        "/networking/contacts",
        json={"name": "Live Fence", "email": shared, "company": "Acme"},
        headers=auth_headers,
    )
    repo.create_lead(
        email=shared,
        name="Live Fence",
        source="manual_approved",
        consent_type="existing_relationship",
        consent_evidence="LinkedIn Connections.csv export uploaded by the account owner.",
    )
    sent: list[str] = []

    class _Trap:
        def send(self, **kwargs):  # noqa: ANN003
            sent.append(kwargs.get("to") or "")
            return {"id": "should-not-happen", "threadId": "x"}

    agent = SalesAgent(repo=repo, gmail_factory=lambda *_a, **_k: _Trap())
    result: dict = {
        "dryRunLogged": 0,
        "sent": 0,
        "suppressed": 0,
        "blocked": 0,
        "networkNurtured": 0,
        "errors": [],
    }
    agent._run_network_nurture(
        test_user_id,
        [{"id": "acct-1"}],
        dry_run=False,
        result=result,
    )
    assert result["sent"] == 0
    assert sent == []
    assert result["networkNurtured"] >= 1
    assert result["dryRunLogged"] >= 1
    rows, _total = repo.list_outreach(limit=20)
    outcomes = {
        r["outcome"] for r in rows if (r.get("recipient") or "").lower() == shared
    }
    assert "sent" not in outcomes
    assert "dry_run" in outcomes


def test_network_nurture_skips_suppressed(client, auth_headers, test_user_id, monkeypatch):
    monkeypatch.setenv("AETHER_SALES_AGENT_ENABLED", "true")
    repo = SalesRepository()
    repo.seed_default_campaigns()
    shared = _email("nurture-sup")
    client.post(
        "/networking/contacts",
        json={"name": "Suppressed Connector", "email": shared},
        headers=auth_headers,
    )
    repo.create_lead(
        email=shared,
        name="Suppressed Connector",
        source="manual_approved",
        consent_type="existing_relationship",
        consent_evidence="LinkedIn Connections.csv export uploaded by the account owner.",
    )
    repo.suppress(shared, "user_opt_out")
    result: dict = {
        "dryRunLogged": 0,
        "sent": 0,
        "suppressed": 0,
        "blocked": 0,
        "networkNurtured": 0,
        "errors": [],
    }
    SalesAgent(repo=repo)._run_network_nurture(
        test_user_id, [], dry_run=True, result=result
    )
    assert result["networkNurtured"] == 0
    assert result["suppressed"] >= 1


def test_network_nurture_rate_limits_recent_outreach(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_SALES_AGENT_ENABLED", "true")
    repo = SalesRepository()
    repo.seed_default_campaigns()
    shared = _email("nurture-recent")
    client.post(
        "/networking/contacts",
        json={"name": "Recent Connector", "email": shared},
        headers=auth_headers,
    )
    lead = repo.create_lead(
        email=shared,
        name="Recent Connector",
        source="manual_approved",
        consent_type="existing_relationship",
        consent_evidence="LinkedIn Connections.csv export uploaded by the account owner.",
    )
    repo.record_outreach(
        channel="email",
        outcome="dry_run",
        lead_id=lead["id"],
        recipient=shared,
        subject="already nudged",
        body="already",
        sent_at=datetime.now(timezone.utc) - timedelta(days=2),
        detail="prior nurture",
    )
    result: dict = {
        "dryRunLogged": 0,
        "sent": 0,
        "suppressed": 0,
        "blocked": 0,
        "networkNurtured": 0,
        "errors": [],
    }
    SalesAgent(repo=repo)._run_network_nurture(
        test_user_id, [], dry_run=True, result=result
    )
    assert result["networkNurtured"] == 0
