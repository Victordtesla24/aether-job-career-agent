"""P4 — Email Agent tests.

Unit tests (dependency-injected fakes, no DB) cover the send-gate discipline,
fabrication-guarded drafting and honest degradation. Integration tests
(client + auth + DB) cover the /agents/email/run endpoint end-to-end in replay
mode (email_triage fixture).
"""
from __future__ import annotations

import pytest

from app.agents.email_agent import EmailAgent, EmailAgentError


class _FakeApprovals:
    def __init__(self):
        self.created = []

    def create(self, user_id, type_, payload, application_id=None):
        self.created.append((user_id, type_, payload))
        return {"id": "appr-1", "status": "pending"}


class _FakeCreds:
    def __init__(self, connected=False):
        self._connected = connected

    def is_connected(self, user_id):
        return self._connected


class _FakeLLM:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def complete_json(self, prompt_name, system, user, **kwargs):
        self.calls += 1
        return self._payload


# ------------------------------------------------------------------ send mode
def test_send_mode_creates_pending_approval_without_sending():
    approvals = _FakeApprovals()
    agent = EmailAgent(approvals=approvals, credentials=_FakeCreds())
    res = agent.run(
        "u1", mode="send", to="r@x.com", subject="Re: role", body="Thanks!"
    )
    assert res.mode == "send"
    assert res.approval_id == "appr-1"
    assert res.approval_status == "pending"
    # It created an email_send approval and sent nothing.
    assert approvals.created[0][1] == "email_send"
    assert approvals.created[0][2]["to"] == "r@x.com"


def test_send_mode_requires_fields():
    agent = EmailAgent(approvals=_FakeApprovals(), credentials=_FakeCreds())
    with pytest.raises(EmailAgentError):
        agent.run("u1", mode="send", to="r@x.com")  # missing subject/body


def test_unknown_mode_raises():
    agent = EmailAgent(credentials=_FakeCreds())
    with pytest.raises(EmailAgentError):
        agent.run("u1", mode="totally-unknown")


def test_draft_requires_thread_id():
    agent = EmailAgent(credentials=_FakeCreds())
    with pytest.raises(EmailAgentError):
        agent.run("u1", mode="draft_reply")


# ---------------------------------------------------------- draft_follow_up
def test_draft_follow_up_requires_thread_id():
    agent = EmailAgent(credentials=_FakeCreds())
    with pytest.raises(EmailAgentError):
        agent.run("u1", mode="draft_follow_up")


def test_draft_follow_up_returns_follow_up_mode_and_guards():
    """The subsumed Follow-up capability: a silence-triggered nudge on an
    existing thread, grounded in the same evidence corpus + FabricationGuard."""
    clean = (
        "just following up on my earlier note about the delivery role. "
        "i remain available for a quick call this week whenever it helps."
    )
    fake_llm = _FakeLLM({"body": clean})
    agent = EmailAgent(llm=fake_llm, credentials=_FakeCreds())
    agent._thread = lambda user_id, thread_id: {  # type: ignore[assignment]
        "id": thread_id,
        "subject": "Delivery role",
        "messages": [{"body": "Thanks for applying — we'll be in touch."}],
    }
    agent._resume_text = lambda: "Experienced delivery lead and program manager."  # type: ignore[assignment]
    res = agent.run("u1", mode="draft_follow_up", thread_id="t9")
    assert res.mode == "draft_follow_up"
    assert res.thread_id == "t9"
    assert res.draft.startswith("just following up")
    # Nothing fabricated → no flags.
    assert res.flagged == []


# ---------------------------------------------------------------- draft guard
def test_draft_flags_fabricated_claims():
    """A drafted reply that invents a metric/entity absent from the resume and
    the incoming email is flagged by the FabricationGuard."""
    fake_llm = _FakeLLM({"body": "I led the GCP migration achieving 99.99% uptime."})
    agent = EmailAgent(llm=fake_llm, credentials=_FakeCreds())
    # Bypass DB/PDF reads with grounded, GCP-free evidence.
    agent._thread = lambda user_id, thread_id: {  # type: ignore[assignment]
        "id": thread_id,
        "subject": "Delivery role",
        "messages": [{"body": "We have an opening for a delivery lead."}],
    }
    agent._resume_text = lambda: "Experienced delivery lead and program manager."  # type: ignore[assignment]
    res = agent.run("u1", mode="draft_reply", thread_id="t1")
    assert res.mode == "draft_reply"
    # GCP (acronym) and 99.99 (metric) are not in the evidence corpus.
    assert res.flagged, "expected fabricated tokens to be flagged"


# ------------------------------------------------------------- honest degrade
def test_apply_labels_degrades_when_not_connected():
    agent = EmailAgent(credentials=_FakeCreds(connected=False))
    res = agent.run("u1", mode="apply_labels", thread_id=None)
    assert res.degraded is True
    assert res.connected is False
    assert "Connect Gmail" in res.message


# ------------------------------------------------------------- integration
def _make_draft(client, auth_headers, subject):
    resp = client.post(
        "/emails/draft",
        json={"subject": subject, "body": f"Body for {subject}"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_email_run_triage_classifies_local_threads(client, auth_headers):
    _make_draft(client, auth_headers, "Recruiter A")
    _make_draft(client, auth_headers, "Recruiter B")
    resp = client.post(
        "/agents/email/run", json={"mode": "triage"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mode"] == "triage"
    assert data["triaged"] == 2
    # No Gmail connected → honest degraded flag, but local threads still triaged.
    assert data["connected"] is False
    assert data["categories"]


def test_email_run_records_agent_run(client, auth_headers):
    _make_draft(client, auth_headers, "Recruiter C")
    client.post("/agents/email/run", json={"mode": "triage"}, headers=auth_headers)
    runs = client.get("/agents/runs", headers=auth_headers).json()
    assert any(r["agentName"] == "emailAgent" for r in runs)


def test_email_run_send_opens_pending_approval(client, auth_headers):
    resp = client.post(
        "/agents/email/run",
        json={
            "mode": "send",
            "to": "recruiter@acme.com",
            "subject": "Re: role",
            "body": "Thanks, let's talk.",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["approval_status"] == "pending"
    pending = client.get("/approvals?status=pending", headers=auth_headers).json()
    assert any(a["type"] == "email_send" for a in pending)


def test_email_run_draft_without_thread_is_422(client, auth_headers):
    resp = client.post(
        "/agents/email/run", json={"mode": "draft_reply"}, headers=auth_headers
    )
    assert resp.status_code == 422, resp.text
