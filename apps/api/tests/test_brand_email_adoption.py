"""Where the branded template is adopted — and where it is DELIBERATELY not.

Adoption (owner directive 2026-08-16, extended 2026-08-17): Aether-OWNED email —
the founder daily digest, the password-reset link, the subscriber welcome,
Stripe lifecycle notices, inbound auto-reply, and the notification-digest
chrome — renders through ``app.services.email_branding``, with the plain-text
alternative carrying the identical information. Every kind is previewable on
the admin Brand tab; preview HTML is the live renderer.

Carve-outs (design ruling, pinned here so a future "brand everything" sweep
has to argue with a red test):

* **User-authored APPLICATION emails** (``application_submission`` →
  ``GmailService.send``) are the CANDIDATE's own voice sent from the
  CANDIDATE's own mailbox. Aether branding there would misrepresent the
  applicant to an employer and leak the fact that a tool was used — it
  sabotages the user. Those messages stay plain text.
* **Sales OUTREACH** to prospects stays text-first for deliverability and
  keeps only its existing compliance footer; it must not pick up this
  template.
"""
from __future__ import annotations

import base64
import smtplib
from email import message_from_bytes
from pathlib import Path

import pytest

from app.services import email_sender

APP_DIR = Path(__file__).resolve().parents[1] / "app"


# --------------------------------------------------- email_sender multipart
class _FakeSMTP:
    """Captures the EmailMessage handed to ``send_message``."""

    last_message = None

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        return None

    def login(self, user, password):
        return None

    def send_message(self, msg):
        _FakeSMTP.last_message = msg


class _FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.text = ""


@pytest.fixture(autouse=True)
def _clean_email_env(monkeypatch):
    for key in (
        "AETHER_SMTP_HOST",
        "AETHER_SMTP_PORT",
        "AETHER_SMTP_USER",
        "AETHER_SMTP_PASS",
        "AETHER_SMTP_FROM",
        "AETHER_EMAIL_API_KEY",
        "AETHER_EMAIL_FROM",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(email_sender, "_last_attempted_send_ok", None)
    _FakeSMTP.last_message = None
    yield


class TestSendEmailHtmlBody:
    def test_default_smtp_path_stays_plain_text(self, monkeypatch):
        """No ``html_body`` → byte-for-byte the previous behaviour."""
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_SMTP_FROM", "noreply@example.com")
        monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

        assert email_sender.send_email("dest@example.com", "Subj", "plain body") is True

        msg = _FakeSMTP.last_message
        assert msg.get_content_type() == "text/plain"
        assert msg.get_content().strip() == "plain body"

    def test_html_body_makes_it_multipart_alternative_text_first(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_SMTP_FROM", "noreply@example.com")
        monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

        ok = email_sender.send_email(
            "dest@example.com",
            "Subj",
            "plain body",
            html_body="<!doctype html><html><body>branded</body></html>",
        )
        assert ok is True

        msg = _FakeSMTP.last_message
        assert msg.get_content_type() == "multipart/alternative"
        parts = msg.get_payload()
        assert parts[0].get_content_type() == "text/plain"
        assert "plain body" in parts[0].get_payload(decode=True).decode()
        assert parts[1].get_content_type() == "text/html"
        assert "branded" in parts[1].get_payload(decode=True).decode()

    def test_api_path_omits_html_key_by_default(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@example.com")
        captured: dict = {}

        import httpx

        def _post(url, **kwargs):
            captured.update(kwargs.get("json") or {})
            return _FakeResponse(200)

        monkeypatch.setattr(httpx, "post", _post)
        assert email_sender.send_email("dest@example.com", "Subj", "plain body") is True
        assert captured["text"] == "plain body"
        assert "html" not in captured

    def test_api_path_sends_html_when_supplied(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@example.com")
        captured: dict = {}

        import httpx

        def _post(url, **kwargs):
            captured.update(kwargs.get("json") or {})
            return _FakeResponse(200)

        monkeypatch.setattr(httpx, "post", _post)
        assert (
            email_sender.send_email(
                "dest@example.com", "Subj", "plain body", html_body="<html>x</html>"
            )
            is True
        )
        assert captured["text"] == "plain body"
        assert captured["html"] == "<html>x</html>"


# ------------------------------------------------------------ reset email
class TestPasswordResetEmail:
    def test_build_reset_email_bodies_returns_text_and_branded_html(self):
        from app.services.password_reset import build_reset_email_bodies

        url = "https://5cb5f0620.abacusai.cloud/reset-password?token=abc123"
        text, html = build_reset_email_bodies(url)

        assert url in text
        assert url in html
        assert "Reset your password" in html, "gold CTA label"
        assert "expires in 1 hour" in text
        assert "expires in 1 hour" in html
        assert "#c9a84c" in html.lower()
        assert "<img" not in html.lower()

    def test_legacy_plain_builder_still_works_unchanged(self):
        from app.services.password_reset import (
            build_reset_email_bodies,
            build_reset_email_body,
        )

        url = "https://example.test/reset-password?token=t"
        assert build_reset_email_body(url) == build_reset_email_bodies(url)[0]
        assert "<" not in build_reset_email_body(url)

    def test_forgot_password_route_sends_both_parts(self, monkeypatch, client):
        """The live caller must hand the HTML alternative to the sender."""
        import uuid

        from app.services import email_sender as sender_mod

        email = f"reset-brand-{uuid.uuid4().hex[:10]}@example.com"
        reg = client.post(
            "/auth/register", json={"email": email, "password": "OldPassw0rd"}
        )
        assert reg.status_code == 201, reg.text

        captured: dict = {}

        def _fake_send(to_email, subject, text_body, html_body=None):
            captured.update(
                {"to": to_email, "subject": subject, "text": text_body, "html": html_body}
            )
            return True

        monkeypatch.setattr(sender_mod, "is_configured", lambda: True)
        monkeypatch.setattr(sender_mod, "send_email", _fake_send)

        resp = client.post("/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200

        assert captured["to"] == email
        assert captured["subject"] == "Reset your Aether password"
        assert "/reset-password?token=" in captured["text"]
        assert captured["html"], "the branded HTML alternative must be sent"
        assert "/reset-password?token=" in captured["html"]
        assert "#c9a84c" in captured["html"].lower()


# ----------------------------------------------------------- founder digest
class _DigestRepo:
    def __init__(self):
        self.recorded: list[dict] = []

    def overview(self):
        return {
            "signups": 42,
            "paidConversions": 7,
            "mrrAud": 123.45,
            "leads": 9,
            "emailsSent": 3,
            "dryRunLogged": 11,
            "replyRate": 0.25,
            "linkedinDraftsQueued": 4,
            "suppressionCount": 2,
        }

    def list_outreach(self, since=None, limit=1):
        return [], 5

    def record_outreach(self, **kwargs):
        self.recorded.append(kwargs)


class _DigestGmail:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, **kwargs):
        self.sent.append(kwargs)
        return {"id": "m-1", "threadId": "t-1"}


@pytest.fixture
def digest_agent(monkeypatch):
    from app.agents.sales_agent import SalesAgent

    repo = _DigestRepo()
    gmail = _DigestGmail()
    agent = SalesAgent(repo=repo, gmail_factory=lambda *a, **k: gmail)  # type: ignore[arg-type]

    state: dict = {}
    monkeypatch.setattr("app.repositories.admin.get_setting", lambda k, d=None: state.get(k, d))
    monkeypatch.setattr(
        "app.repositories.admin.set_setting", lambda k, v: state.__setitem__(k, v)
    )
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", "founder@example.com")
    return agent, repo, gmail, state


class TestFounderDigestBranding:
    def test_digest_sends_branded_html_and_text_with_every_stat(self, digest_agent):
        agent, repo, gmail, _state = digest_agent
        result = {"sent": 0, "dryRunLogged": 0, "errors": []}

        agent._run_digest("admin-1", [{"id": "acct-1"}], dry_run=False, result=result)

        assert len(gmail.sent) == 1
        call = gmail.sent[0]
        assert call["subject"].startswith("Aether sales digest — ")
        html = call["html_body"]
        text = call["body"]

        assert html, "the founder digest must carry the branded HTML alternative"
        assert "#c9a84c" in html.lower()
        assert "#08080a" in html.lower()
        assert "AETHER" in html
        assert "<img" not in html.lower() and "<script" not in html.lower()

        for value in ("42", "7", "123.45", "9", "3", "11", "25.0%", "4", "2", "5", "LIVE"):
            assert value in html, f"{value!r} missing from the branded digest HTML"
            assert value in text, f"{value!r} missing from the digest plain text"

        assert result["sent"] == 1
        assert repo.recorded and repo.recorded[0]["body"] == text

    def test_digest_dry_run_logs_the_same_plain_text(self, digest_agent):
        agent, repo, gmail, _state = digest_agent
        result = {"sent": 0, "dryRunLogged": 0, "errors": []}

        agent._run_digest("admin-1", [{"id": "acct-1"}], dry_run=True, result=result)

        assert gmail.sent == []
        assert result["dryRunLogged"] == 1
        body = repo.recorded[0]["body"]
        assert "DRY-RUN (shadow)" in body
        assert "42" in body
        assert "<" not in body, "the logged body stays plain text"

    def test_digest_still_gated_to_once_per_day(self, digest_agent):
        agent, repo, gmail, _state = digest_agent
        result = {"sent": 0, "dryRunLogged": 0, "errors": []}

        agent._run_digest("admin-1", [{"id": "acct-1"}], dry_run=False, result=result)
        agent._run_digest("admin-1", [{"id": "acct-1"}], dry_run=False, result=result)

        assert len(gmail.sent) == 1
        assert result["sent"] == 1


# ------------------------------------------------------------- carve-outs
class TestBrandingCarveOuts:
    def test_application_email_body_is_the_candidates_own_voice(self):
        from app.services.application_submission import build_submission_message

        subject, body = build_submission_message(
            {"name": "Alex Candidate", "email": "alex@example.com"},
            {
                "jobTitle": "Staff Engineer",
                "company": "Northwind",
                "coverLetter": "Dear hiring team,\n\nI led the payments rewrite.",
            },
        )

        assert "Application: Staff Engineer — Northwind (Alex Candidate)" == subject
        assert body.startswith("Dear hiring team,")
        # No template markup, no brand tokens, no Aether wordmark: an employer
        # must see only the candidate's letter.
        for marker in ("<table", "<!doctype", "#c9a84c", "#08080a", "AETHER", "style="):
            assert marker.lower() not in body.lower(), (
                f"application email leaked branding marker {marker!r} — this email "
                "is the candidate's own voice"
            )

    def test_submission_path_never_imports_the_branded_template(self):
        source = (APP_DIR / "services" / "application_submission.py").read_text()
        assert "email_branding" not in source
        assert "html_body" not in source, (
            "the application email must be sent plain-text only — no HTML alternative"
        )

    def test_submission_control_never_imports_the_branded_template(self):
        source = (APP_DIR / "services" / "submission_control.py").read_text()
        assert "email_branding" not in source

    def test_sales_outreach_does_not_use_the_branded_template(self):
        """Outreach keeps its own text-first path + compliance footer."""
        source = (APP_DIR / "agents" / "sales_agent.py").read_text()
        assert "def _handle_interest" in source  # the prospect-outreach path
        assert "sales_branding" in source, "outreach keeps its own text-first renderer"
        # email_branding may only be referenced by the founder digest.
        for line_no, line in enumerate(source.splitlines(), start=1):
            if "email_branding" in line:
                assert "digest" in line or line.strip().startswith("from app.services"), (
                    f"line {line_no} references email_branding outside the digest: {line!r}"
                )

    def test_gmail_raw_message_still_plain_when_no_html(self):
        """Regression guard for the carve-out transport: no html → text/plain."""
        from app.services.gmail_service import GmailService

        svc = GmailService.__new__(GmailService)
        raw = svc._raw_message("to@example.com", "Subj", "plain only")
        msg = message_from_bytes(base64.urlsafe_b64decode(raw))
        assert msg.get_content_type() == "text/plain"
