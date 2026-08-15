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

Gmail is a fake injected via the agent's ``gmail_factory`` seam. The pipeline
tests inject an always-unavailable LLM stub, so personalization falls back to
the deterministic template substitution — asserted explicitly (that fallback
is part of the honesty contract, not an accident).
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
from app.services.llm_client import LLMUnavailableError


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

    def send(self, to, subject, body, in_reply_to=None, thread_id=None, attachments=None, html_body=None):
        self.sent.append(
            {"to": to, "subject": subject, "body": body, "threadId": thread_id,
             "html_body": html_body}
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


class _UnavailableLLM:
    """LLM stub that is always down — forces the deterministic template
    fallback the pipeline tests assert. Injecting it (instead of relying on
    "replay mode has no sales fixtures") keeps these tests honest even when a
    captured ``sales_reply`` fixture happens to exist on disk."""

    def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise LLMUnavailableError("test stub: LLM intentionally unavailable")


def _agent_with(repo: SalesRepository, fake: FakeGmail, monkeypatch) -> SalesAgent:
    """Agent wired to the fake Gmail and one fake flagged sending account."""
    agent = SalesAgent(
        repo=repo,
        gmail_factory=lambda uid, aid: fake,
        llm=_UnavailableLLM(),  # type: ignore[arg-type]
    )
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
    # LLM stub is unavailable → honest template fallback, personalized.
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
    ("POST", "/admin/sales-agent/generate"),
    ("GET", "/admin/sales-agent/campaigns/some-id/preview"),
    ("GET", "/admin/sales-agent/brand/documents"),
    ("GET", "/admin/sales-agent/brand/documents/invoice/preview"),
    ("GET", "/admin/sales-agent/brand/templates"),
    ("PUT", "/admin/sales-agent/brand/templates/auto_reply"),
    ("POST", "/admin/sales-agent/brand/artifacts"),
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



# ------------------------------------------------------- branding + generate
def test_branded_email_preserves_compliance_footer_verbatim():
    """§6 hard gate survives templating: the branded HTML must contain the
    full compliance footer text (escaped), and never the raw placeholder."""
    from app.services.sales_branding import render_branded_email, split_compliance_footer

    body = append_compliance_footer(
        personalize_template("Hi {{name}},\n\nTry Aether today.", "Alex")
    )
    html = render_branded_email("Welcome", body)
    assert "{{name}}" not in html
    assert "Hi Alex," in html
    assert "operated by Vikram Sarkar" in html
    assert "Reply &#x27;unsubscribe&#x27; to stop receiving these emails." in html or (
        "Reply 'unsubscribe' to stop receiving these emails." in html
    )
    assert "Aether Career Job Agent" in html
    assert "AB Entertainment" not in html  # visual tokens only, never the DS name
    main, footer = split_compliance_footer(body)
    assert "unsubscribe" in footer.lower()
    assert "unsubscribe" not in main.lower()


def test_gmail_html_body_is_multipart_alternative_with_plain_first():
    """html_body must never REPLACE the compliance-footed plain body."""
    import base64
    from email import message_from_bytes

    from app.services.gmail_service import GmailService

    svc = GmailService.__new__(GmailService)  # no credentials needed for _raw_message
    raw = svc._raw_message(
        "to@example.com", "Subj", "plain body with footer",
        html_body="<html><body>branded</body></html>",
    )
    msg = message_from_bytes(base64.urlsafe_b64decode(raw))
    assert msg.get_content_type() == "multipart/alternative"
    parts = msg.get_payload()
    assert parts[0].get_content_type() == "text/plain"
    assert "plain body with footer" in parts[0].get_payload(decode=True).decode()
    assert parts[1].get_content_type() == "text/html"
    assert "branded" in parts[1].get_payload(decode=True).decode()


def test_grounding_guard_rejects_fabrications():
    agent = SalesAgent(repo=SalesRepository())
    assert agent._grounding_guard("Starter is A$19/month.") is None
    assert agent._grounding_guard("Only $499 today!") is not None
    assert agent._grounding_guard("87% of users succeed") is not None
    assert agent._grounding_guard("Join 10,000 users") is not None
    assert agent._grounding_guard("5 agent runs per month, free.") is None


def test_campaign_preview_route_renders_branded_html(client, admin_headers):
    campaigns = client.get(
        "/admin/sales-agent/campaigns", headers=admin_headers
    ).json()["campaigns"]
    resp = client.get(
        f"/admin/sales-agent/campaigns/{campaigns[0]['id']}/preview",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["campaignId"] == campaigns[0]["id"]
    assert "<!DOCTYPE html>" in data["html"]
    assert "{{name}}" not in data["html"]
    assert "unsubscribe" in data["html"].lower()
    missing = client.get(
        "/admin/sales-agent/campaigns/nope/preview", headers=admin_headers
    )
    assert missing.status_code == 404


def test_admin_creates_branded_poster_and_identical_request_reuses_it(
    client, admin_headers
):
    payload = {
        "title": "Human-approved job search",
        "message": "Every outbound action waits for your explicit yes.",
        "cta": "Explore Aether Career Job Agent",
    }
    first = client.post(
        "/admin/sales-agent/brand/artifacts", headers=admin_headers, json=payload
    )
    assert first.status_code == 201
    created = first.json()
    assert created["reused"] is False
    assert created["kind"] == "poster"
    assert created["inputHash"]
    assert created["svg"].startswith("<svg")
    # Aether design-system grounding: canonical mark plus its ink/gilt palette.
    assert "/brand/aether-mark.svg" in created["svg"]
    assert "#08080A" in created["svg"]
    assert "#C9A84C" in created["svg"]
    assert "Aether Career Job Agent" in created["svg"]

    second = client.post(
        "/admin/sales-agent/brand/artifacts", headers=admin_headers, json=payload
    )
    assert second.status_code == 200
    reused = second.json()
    assert reused["reused"] is True
    assert reused["id"] == created["id"]
    assert reused["inputHash"] == created["inputHash"]


class _FakeLLM:
    """Deterministic stand-in — generate tests must not depend on live LLMs."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, prompt_name, system, user, *, model, temperature,
                 fixture_key=None, validate=None):
        self.calls.append(prompt_name)
        if prompt_name == "sales_agent_campaign":
            return (
                "Hi {{name}},\n\nYou are close to your 5 free runs. Starter is "
                "A$19/month.\n\nhttps://5cb5f0620.abacusai.cloud"
            )
        return (
            "Post one about the anti-fabrication guard. A$19/month.\n"
            "https://5cb5f0620.abacusai.cloud\n===\n"
            "Post two about the approval queue.\nhttps://5cb5f0620.abacusai.cloud\n"
            "===\nPost three, founder reflection.\nhttps://5cb5f0620.abacusai.cloud"
        )


def test_generate_marketing_content_creates_inactive_campaigns_and_drafts(
    repo, sales_env, monkeypatch
):
    # The test DB persists for the whole session — clear any earlier copies so
    # the "creates" assertion is about THIS run.
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM "SalesCampaign" WHERE "name" LIKE %s',
                ("%(agent-generated)",),
            )
        conn.commit()
    fake_llm = _FakeLLM()
    agent = SalesAgent(repo=repo, llm=fake_llm)  # type: ignore[arg-type]
    result = agent.generate_marketing_content(trigger="test")
    assert result["ran"] is True
    created = {c["name"] for c in result["campaignsCreated"]}
    assert "Free→Starter Nudge v2 (agent-generated)" in created
    assert "Welcome Reply v2 (agent-generated)" in created
    # Approval-queue philosophy: agent copy starts INACTIVE.
    for c in result["campaignsCreated"]:
        assert c["active"] is False
    assert result["linkedinDrafts"] == 3
    # Idempotent by name: a second run skips, never duplicates.
    again = SalesAgent(repo=repo, llm=_FakeLLM()).generate_marketing_content()  # type: ignore[arg-type]
    assert not again["campaignsCreated"]
    assert set(again["campaignsSkipped"]) == created


def test_generate_is_honest_when_llm_fails(repo, sales_env):
    class _BrokenLLM:
        def complete(self, *a, **k):
            raise RuntimeError("provider down")

    result = SalesAgent(repo=repo, llm=_BrokenLLM()).generate_marketing_content()  # type: ignore[arg-type]
    assert result["ran"] is True
    assert result["errors"]  # the failure is recorded, nothing fabricated
    assert not result["campaignsCreated"]


# ------------------------------------------------------------ brand documents
def test_brand_documents_registry_lists_kinds_plans_and_assets(
    client, admin_headers
):
    resp = client.get("/admin/sales-agent/brand/documents", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    kinds = {d["kind"] for d in data["documents"]}
    assert kinds == {
        "invoice", "auto_reply", "subscription_confirmed",
        "payment_failed", "cancellation_confirmed",
    }
    plan_ids = {p["id"] for p in data["plans"]}
    assert {"free", "starter", "pro", "power"} <= plan_ids
    asset_paths = {a["path"] for a in data["assets"]}
    assert "/brand/aether-mark.png" in asset_paths
    assert "/brand/aether-mark.svg" in asset_paths


def test_brand_invoice_preview_uses_live_plan_price_and_gst(
    client, admin_headers
):
    resp = client.get(
        "/admin/sales-agent/brand/documents/invoice/preview"
        "?plan=starter&interval=monthly",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    html = resp.json()["html"]
    # Live catalog price (Starter A$19/mo) + single-source GST split (÷11).
    assert "A$19.00" in html
    assert "A$1.73" in html      # GST component
    assert "A$17.27" in html     # net
    # Honest merge fields, correct brand name, no legacy brand.
    assert "{{customer_name}}" in html
    assert "Aether Career Job Agent" in html
    assert "AB Entertainment" not in html


def test_brand_document_preview_rejects_unknown_kind_and_plan(
    client, admin_headers
):
    assert client.get(
        "/admin/sales-agent/brand/documents/nope/preview",
        headers=admin_headers,
    ).status_code == 404
    assert client.get(
        "/admin/sales-agent/brand/documents/invoice/preview?plan=nope",
        headers=admin_headers,
    ).status_code == 404
    assert client.get(
        "/admin/sales-agent/brand/documents/invoice/preview?interval=weekly",
        headers=admin_headers,
    ).status_code == 422


# ----------------------------------------------------- persistent brand editor
def test_brand_template_editor_persists_copy_footnote_and_audit(client, admin_headers):
    listed = client.get("/admin/sales-agent/brand/templates", headers=admin_headers)
    assert listed.status_code == 200
    original = next(t for t in listed.json()["templates"] if t["kind"] == "auto_reply")
    assert original["body"]
    assert original["footer"]

    updated = client.put(
        "/admin/sales-agent/brand/templates/auto_reply",
        headers=admin_headers,
        json={
            "body": "Hello {{name}},\n\nThanks for contacting us.",
            "footnote": "Support replies are reviewed in Melbourne time.",
            "footer": "Aether Career Job Agent — Operated by Vikram Sarkar\nhttps://example.test/unsubscribe",
        },
    )
    assert updated.status_code == 200
    data = updated.json()
    assert data["body"].startswith("Hello {{name}}")
    assert data["footnote"] == "Support replies are reviewed in Melbourne time."
    assert "unsubscribe" in data["footer"].lower()
    assert data["updatedAt"]

    persisted = client.get("/admin/sales-agent/brand/templates", headers=admin_headers)
    saved = next(t for t in persisted.json()["templates"] if t["kind"] == "auto_reply")
    assert saved["body"] == data["body"]
    assert saved["footnote"] == data["footnote"]

    preview = client.get(
        "/admin/sales-agent/brand/documents/auto_reply/preview", headers=admin_headers
    )
    assert preview.status_code == 200
    html = preview.json()["html"]
    assert "Thanks for contacting us." in html
    assert "Support replies are reviewed in Melbourne time." in html
    assert "https://example.test/unsubscribe" in html

    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "action", "targetType", "targetId" FROM "AdminAuditLog" '
                'WHERE "targetType"=%s AND "targetId"=%s ORDER BY "createdAt" DESC LIMIT 1',
                ("brand_template", "auto_reply"),
            )
            audit = cur.fetchone()
    assert audit == ("brand_template.updated", "brand_template", "auto_reply")


def test_brand_template_editor_rejects_empty_or_non_compliant_footer(client, admin_headers):
    for footer in ("", "   ", "Aether Career Job Agent — Operated by Vikram Sarkar"):
        response = client.put(
            "/admin/sales-agent/brand/templates/auto_reply",
            headers=admin_headers,
            json={
                "body": "Hello {{name}},",
                "footnote": "A footnote.",
                "footer": footer,
            },
        )
        assert response.status_code == 422
