"""Sales Agent tests (build brief §9) — hard compliance gates + pipeline.

Covers, against the REAL test database (no mocked SQL):
* consent provenance is enforced at the repository (unratified type, empty
  evidence, inbound lead without a real thread id → ConsentViolationError);
* DB send-idempotency (second 'sent' on a thread → DuplicateSendError);
* suppression blocks a send (agent logs outcome 'blocked', Gmail never called);
* inbound "unsubscribe" → permanent suppression, no reply;
* integration: inbound interest → lead → reply drafted from the human-authored
  template → compliance footer appended server-side → DRY-RUN logged verbatim,
  nothing sent;
* live mode sends exactly once (re-run does not re-send the same thread);
* lifecycle rate limit reads the log;
* API surface is AdminUser-gated: anonymous 401, non-admin 403, admin 200.

Gmail is a fake injected via the agent's ``gmail_factory`` seam. The LLM runs
in replay mode with no sales fixtures, so personalization falls back to the
deterministic template substitution — asserted explicitly (that fallback is
part of the honesty contract, not an accident).
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.sales_agent import (
    SalesAgent,
    append_compliance_footer,
    personalize_template,
)
from app.repositories.sales import (
    ConsentViolationError,
    DuplicateSendError,
    SalesRepository,
)


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


class FakeGmail:
    """Injected via ``gmail_factory`` — records sends, serves canned inbound."""

    def __init__(self, messages: list[dict] | None = None) -> None:
        self.messages = messages or []
        self.sent: list[dict] = []

    def list_message_headers(self, query=None, max_results=100):
        return [
            {
                "id": m["id"],
                "threadId": m["threadId"],
                "from": m["from"],
                "subject": m["subject"],
                "date": "",
            }
            for m in self.messages
        ]

    def get_message_bodies(self, message_id):
        m = next(m for m in self.messages if m["id"] == message_id)
        return {
            "id": m["id"],
            "threadId": m["threadId"],
            "from": m["from"],
            "subject": m["subject"],
            "date": "",
            "text": m["text"],
            "html": "",
        }

    def send(self, to, subject, body, in_reply_to=None, thread_id=None, attachments=None):
        self.sent.append(
            {"to": to, "subject": subject, "body": body, "threadId": thread_id}
        )
        # Thread/message ids must be globally unique: the test DB persists
        # across the whole pytest session, so per-instance counters would
        # collide with rows recorded by earlier tests.
        suffix = uuid.uuid4().hex[:12]
        return {"id": f"sent-{suffix}", "threadId": thread_id or f"t-{suffix}"}


@pytest.fixture()
def repo() -> SalesRepository:
    return SalesRepository()


@pytest.fixture()
def admin_headers(client, auth_headers, promote_user_to_admin, monkeypatch):
    """Promote the fixture user AND point AETHER_ADMIN_EMAIL at them so
    ``resolve_admin_user_id`` finds the operator account."""
    promote_user_to_admin(client._test_user_id)
    me = client.get("/auth/me", headers=auth_headers).json()
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", me["email"])
    return auth_headers


@pytest.fixture()
def sales_env(monkeypatch, admin_headers):
    monkeypatch.setenv("AETHER_SALES_AGENT_ENABLED", "true")
    monkeypatch.setenv("AETHER_SALES_AGENT_DRY_RUN", "true")
    return admin_headers


def _agent_with(repo: SalesRepository, fake: FakeGmail, monkeypatch) -> SalesAgent:
    """Agent wired to the fake Gmail and one fake flagged sending account."""
    agent = SalesAgent(repo=repo, gmail_factory=lambda uid, aid: fake)
    monkeypatch.setattr(
        repo,
        "sales_sending_accounts",
        lambda user_id: [
            {"id": "acct-test", "accountEmail": "sales-test@aether.local", "isPrimary": True}
        ],
    )
    # Lifecycle sweep touches unrelated seeded users — keep these tests focused
    # on the inbound pipeline (lifecycle rate-limit has its own test below).
    monkeypatch.setattr(agent, "_lifecycle_candidates", lambda: [])
    return agent


# --------------------------------------------------------------------- gates
def test_lead_requires_ratified_consent(repo):
    with pytest.raises(ConsentViolationError):
        repo.create_lead(
            email=_email("bad-consent"),
            consent_type="cold_scrape",  # NOT ratified
            consent_evidence="scraped from the internet",
            source="inbound_email",
            source_thread_id="t1",
        )
    with pytest.raises(ConsentViolationError):
        repo.create_lead(
            email=_email("no-evidence"),
            consent_type="inbound_signal",
            consent_evidence="   ",
            source="inbound_email",
            source_thread_id="t1",
        )
    with pytest.raises(ConsentViolationError):
        repo.create_lead(
            email=_email("no-thread"),
            consent_type="inbound_signal",
            consent_evidence="gmail message abc",
            source="inbound_email",  # inbound REQUIRES the real thread id
        )


def test_send_idempotency_is_a_db_constraint(repo):
    thread = f"thread-{uuid.uuid4().hex[:12]}"
    repo.record_outreach(
        channel="email", outcome="sent", gmail_thread_id=thread,
        gmail_message_id=f"m-{uuid.uuid4().hex[:12]}", recipient=_email("idem"),
    )
    with pytest.raises(DuplicateSendError):
        repo.record_outreach(
            channel="email", outcome="sent", gmail_thread_id=thread,
            gmail_message_id=f"m-{uuid.uuid4().hex[:12]}", recipient=_email("idem"),
        )
    assert repo.thread_already_sent(thread) is True


def test_suppression_is_permanent_and_case_insensitive(repo):
    email = _email("Suppressed").lower()
    repo.suppress(email.upper(), "inbound_unsubscribe_request")
    assert repo.is_suppressed(email) is True
    assert repo.is_suppressed(email.upper()) is True


def test_footer_is_appended_server_side_and_idempotent():
    body = append_compliance_footer("Hello there")
    assert "unsubscribe" in body.lower()
    assert "Aether Career Agent" in body
    # A second append never duplicates the footer.
    assert append_compliance_footer(body) == body


def test_personalize_template_is_deterministic():
    assert personalize_template("Hi {{name}},", "Jane Doe") == "Hi Jane,"
    assert personalize_template("Hi {{name}},", None) == "Hi there,"


# ------------------------------------------------------------- agent pipeline
def test_disabled_agent_is_an_honest_noop(monkeypatch):
    monkeypatch.delenv("AETHER_SALES_AGENT_ENABLED", raising=False)
    result = SalesAgent().run(trigger="manual")
    assert result["ran"] is False
    assert "AETHER_SALES_AGENT_ENABLED" in result["reason"]


def test_inbound_interest_to_dry_run_pipeline(repo, sales_env, monkeypatch):
    sender = _email("prospect")
    thread = f"t-{uuid.uuid4().hex[:12]}"
    fake = FakeGmail([
        {
            "id": f"m-{uuid.uuid4().hex[:12]}",
            "threadId": thread,
            "from": f"Pat Prospect <{sender}>",
            "subject": "Question about pricing",
            "text": "Hi, I'm interested in Aether — how does the pricing work?",
        }
    ])
    agent = _agent_with(repo, fake, monkeypatch)
    result = agent.run(trigger="manual")

    assert result["ran"] is True and result["dryRun"] is True
    assert result["leadsCreated"] == 1
    assert fake.sent == []  # shadow mode: NOTHING leaves the machine

    lead = repo.get_lead_by_email(sender)
    assert lead is not None
    assert lead["consentType"] == "inbound_signal"
    assert lead["sourceThreadId"] == thread
    assert "gmail message" in lead["consentEvidence"]

    rows, _ = repo.list_outreach(outcome="dry_run", limit=200)
    row = next(r for r in rows if (r["recipient"] or "") == sender)
    assert row["gmailThreadId"] == thread
    body = row["body"] or ""
    # Server-side compliance footer (Spam Act): identity + unsubscribe.
    assert "Aether Career Agent" in body
    assert "unsubscribe" in body.lower()
    # Replay mode has no sales fixtures → honest template fallback, personalized.
    assert "Pat" in body
    assert "{{name}}" not in body


def test_suppressed_sender_is_blocked_not_emailed(repo, sales_env, monkeypatch):
    sender = _email("blocked")
    repo.suppress(sender, "inbound_unsubscribe_request")
    fake = FakeGmail([
        {
            "id": f"m-{uuid.uuid4().hex[:12]}",
            "threadId": f"t-{uuid.uuid4().hex[:12]}",
            "from": f"Blocked Person <{sender}>",
            "subject": "interested in a demo",
            "text": "I'd love a demo of Aether.",
        }
    ])
    agent = _agent_with(repo, fake, monkeypatch)
    result = agent.run(trigger="manual")

    assert result["blocked"] == 1
    assert fake.sent == []
    rows, _ = repo.list_outreach(outcome="blocked", limit=200)
    assert any((r["recipient"] or "") == sender for r in rows)


def test_inbound_unsubscribe_permanently_suppresses(repo, sales_env, monkeypatch):
    sender = _email("optout")
    fake = FakeGmail([
        {
            "id": f"m-{uuid.uuid4().hex[:12]}",
            "threadId": f"t-{uuid.uuid4().hex[:12]}",
            "from": f"Opt Out <{sender}>",
            "subject": "please unsubscribe me",
            "text": "unsubscribe",
        }
    ])
    agent = _agent_with(repo, fake, monkeypatch)
    result = agent.run(trigger="manual")

    assert result["suppressed"] == 1
    assert repo.is_suppressed(sender) is True
    assert fake.sent == []  # an unsubscribe NEVER gets a reply


def test_live_mode_sends_exactly_once(repo, sales_env, monkeypatch):
    sender = _email("live")
    thread = f"t-{uuid.uuid4().hex[:12]}"
    message = {
        "id": f"m-{uuid.uuid4().hex[:12]}",
        "threadId": thread,
        "from": f"Live Prospect <{sender}>",
        "subject": "how does Aether work?",
        "text": "Interested — how does it work?",
    }
    fake = FakeGmail([message])
    agent = _agent_with(repo, fake, monkeypatch)

    result = agent.run(trigger="manual", dry_run=False)
    assert result["sent"] >= 1
    # Exactly ONE send to the prospect (the daily digest to the founder may
    # also go out in live mode — that is correct behaviour, not a duplicate).
    to_prospect = [s for s in fake.sent if s["to"] == sender]
    assert len(to_prospect) == 1
    assert "unsubscribe" in to_prospect[0]["body"].lower()
    assert repo.thread_already_sent(thread) is True
    lead = repo.get_lead_by_email(sender)
    assert lead is not None and lead["status"] == "contacted"

    # Second run over the SAME inbound message: idempotency gates hold —
    # the fresh fake never sends to the prospect again.
    fake2 = FakeGmail([message])
    agent2 = _agent_with(repo, fake2, monkeypatch)
    agent2.run(trigger="manual", dry_run=False)
    assert [s for s in fake2.sent if s["to"] == sender] == []
    rows, total = repo.list_outreach(outcome="sent", limit=200)
    assert sum(1 for r in rows if r["gmailThreadId"] == thread) == 1


def test_lifecycle_rate_limit_reads_the_log(repo):
    from datetime import datetime, timedelta, timezone

    email = _email("cycle")
    campaign = repo.active_campaign_by_type("free_to_paid_nudge") or repo.create_campaign(
        name="nudge", ctype="free_to_paid_nudge", template_body="Hi {{name}},"
    )
    cycle_start = datetime.now(timezone.utc) - timedelta(days=3)
    assert repo.lifecycle_email_sent_since(email, cycle_start) is False
    repo.record_outreach(
        channel="email", outcome="dry_run", campaign_id=campaign["id"],
        recipient=email,
    )
    assert repo.lifecycle_email_sent_since(email, cycle_start) is True


# ------------------------------------------------------------------ API gate
ROUTES = [
    ("GET", "/admin/sales-agent/overview"),
    ("GET", "/admin/sales-agent/leads"),
    ("GET", "/admin/sales-agent/campaigns"),
    ("GET", "/admin/sales-agent/outreach-log"),
    ("GET", "/admin/sales-agent/suppressions"),
    ("GET", "/admin/sales-agent/health"),
    ("POST", "/admin/sales-agent/run-now"),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_anonymous_gets_401(client, method, path):
    resp = client.request(method, path)
    assert resp.status_code == 401


@pytest.mark.parametrize("method,path", ROUTES)
def test_non_admin_gets_403(client, auth_headers, method, path):
    resp = client.request(method, path, headers=auth_headers)
    assert resp.status_code == 403


def test_admin_overview_and_health(client, admin_headers, monkeypatch):
    monkeypatch.delenv("AETHER_SALES_AGENT_ENABLED", raising=False)
    ov = client.get("/admin/sales-agent/overview", headers=admin_headers)
    assert ov.status_code == 200
    data = ov.json()
    # Honest metrics: replyRate is null (not 0) when not observable.
    for key in ("signups", "paidConversions", "mrrAud", "suppressionCount"):
        assert key in data
    assert "replyRate" in data

    he = client.get("/admin/sales-agent/health", headers=admin_headers)
    assert he.status_code == 200
    hd = he.json()
    assert hd["enabled"] is False
    assert hd["dryRun"] is True  # shadow mode is the DEFAULT
    assert hd["intervalMinutes"] == 30

    # Seeded campaigns exist and templates NEVER embed the footer (it is
    # appended server-side at send time).
    ca = client.get("/admin/sales-agent/campaigns", headers=admin_headers)
    assert ca.status_code == 200
    campaigns = ca.json()["campaigns"]
    assert len(campaigns) >= 5
    types = {c["type"] for c in campaigns}
    assert {"welcome", "free_to_paid_nudge", "reengagement",
            "demo_response", "linkedin_draft"} <= types
    for c in campaigns:
        assert "Reply 'unsubscribe'" not in c["templateBody"]


def test_run_now_disabled_is_honest_noop(client, admin_headers, monkeypatch):
    monkeypatch.delenv("AETHER_SALES_AGENT_ENABLED", raising=False)
    resp = client.post("/admin/sales-agent/run-now", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ran"] is False
    assert "AETHER_SALES_AGENT_ENABLED" in body["reason"]


def test_campaign_crud(client, admin_headers):
    created = client.post(
        "/admin/sales-agent/campaigns",
        headers=admin_headers,
        json={
            "name": f"test campaign {uuid.uuid4().hex[:6]}",
            "type": "welcome",
            "templateBody": "Hi {{name}}, test body.",
            "active": False,
        },
    )
    assert created.status_code == 201
    cid = created.json()["id"]
    updated = client.put(
        f"/admin/sales-agent/campaigns/{cid}",
        headers=admin_headers,
        json={"active": True, "templateBody": "Hi {{name}}, updated."},
    )
    assert updated.status_code == 200
    assert updated.json()["active"] is True
    assert updated.json()["templateBody"] == "Hi {{name}}, updated."
    bad = client.post(
        "/admin/sales-agent/campaigns",
        headers=admin_headers,
        json={"name": "x", "type": "cold_blast", "templateBody": "y"},
    )
    assert bad.status_code == 422
