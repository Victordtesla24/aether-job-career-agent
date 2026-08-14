"""app/services/email_sender.py — direct unit coverage (S-FIX slice D, MF-2).

Prior to this file, EVERY test that touched password reset monkeypatched
``email_sender.send_email`` wholesale (see ``test_password_reset.py``), so
the actual transport code — ``_send_via_smtp``, ``_send_via_api``,
``active_provider``'s SMTP-wins tie-break, and ``is_configured``'s
sender-address requirement — was never executed by any test. These tests
exercise that code directly: ``smtplib.SMTP`` and ``httpx.post`` are the
ONLY things faked (no real network call is made), everything above them is
real.
"""
from __future__ import annotations

import smtplib

import pytest

from app.services import email_sender


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every provider env var starts unset; each test opts in explicitly."""
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
    yield


# ---------------------------------------------------------------------------
# active_provider() — SMTP-wins tie-break
# ---------------------------------------------------------------------------


class TestActiveProvider:
    def test_neither_configured_returns_none(self):
        assert email_sender.active_provider() is None

    def test_smtp_only_returns_smtp(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        assert email_sender.active_provider() == "smtp"

    def test_api_only_returns_api(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        assert email_sender.active_provider() == "api"

    def test_both_configured_smtp_wins(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        assert email_sender.active_provider() == "smtp"

    def test_blank_smtp_host_does_not_count_as_configured(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "   ")
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        assert email_sender.active_provider() == "api"


# ---------------------------------------------------------------------------
# is_configured() — sender-address requirement
# ---------------------------------------------------------------------------


class TestIsConfigured:
    def test_no_provider_is_not_configured(self):
        assert email_sender.is_configured() is False

    def test_smtp_host_without_any_sender_address_is_not_configured(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        # No AETHER_SMTP_USER and no AETHER_SMTP_FROM — no way to know who
        # mail would be sent "from".
        assert email_sender.is_configured() is False

    def test_smtp_host_with_user_as_from_fallback_is_configured(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_SMTP_USER", "ops@example.com")
        # AETHER_SMTP_FROM unset — falls back to AETHER_SMTP_USER.
        assert email_sender.is_configured() is True

    def test_smtp_host_with_explicit_from_is_configured(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_SMTP_FROM", "noreply@example.com")
        assert email_sender.is_configured() is True

    def test_api_key_without_from_address_is_not_configured(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        assert email_sender.is_configured() is False

    def test_api_key_with_from_address_is_configured(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@example.com")
        assert email_sender.is_configured() is True


# ---------------------------------------------------------------------------
# _send_via_smtp() — real function, fake smtplib.SMTP
# ---------------------------------------------------------------------------


class _FakeSMTP:
    """Stands in for ``smtplib.SMTP`` as a context manager."""

    last_instance: "_FakeSMTP | None" = None
    raise_on: str | None = None  # "starttls" | "login" | "send_message"

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in_as = None
        self.sent_message = None
        _FakeSMTP.last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        if _FakeSMTP.raise_on == "starttls":
            raise OSError("connection refused")
        self.started_tls = True

    def login(self, user, password):
        if _FakeSMTP.raise_on == "login":
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.logged_in_as = (user, password)

    def send_message(self, msg):
        if _FakeSMTP.raise_on == "send_message":
            raise smtplib.SMTPException("send failed")
        self.sent_message = msg


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    _FakeSMTP.last_instance = None
    _FakeSMTP.raise_on = None
    yield
    _FakeSMTP.last_instance = None
    _FakeSMTP.raise_on = None


class TestSendViaSmtp:
    def test_missing_sender_address_returns_false_without_connecting(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        # No user, no from — is_configured() would already be False, but
        # _send_via_smtp is exercised directly here regardless of that gate.
        monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
        result = email_sender._send_via_smtp("dest@example.com", "Subject", "Body")
        assert result is False
        assert _FakeSMTP.last_instance is None  # never even tried to connect

    def test_successful_send_returns_true_and_uses_starttls_and_login(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_SMTP_PORT", "2525")
        monkeypatch.setenv("AETHER_SMTP_USER", "ops@example.com")
        monkeypatch.setenv("AETHER_SMTP_PASS", "s3cret")
        monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

        result = email_sender._send_via_smtp("dest@example.com", "Reset link", "body text")

        assert result is True
        instance = _FakeSMTP.last_instance
        assert instance is not None
        assert instance.host == "smtp.example.com"
        assert instance.port == 2525
        assert instance.started_tls is True
        assert instance.logged_in_as == ("ops@example.com", "s3cret")
        assert instance.sent_message["To"] == "dest@example.com"
        assert instance.sent_message["From"] == "ops@example.com"
        assert instance.sent_message["Subject"] == "Reset link"

    def test_no_auth_when_credentials_absent(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_SMTP_FROM", "noreply@example.com")
        monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

        result = email_sender._send_via_smtp("dest@example.com", "Subj", "body")

        assert result is True
        assert _FakeSMTP.last_instance.logged_in_as is None

    def test_transport_failure_returns_false(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_SMTP_FROM", "noreply@example.com")
        _FakeSMTP.raise_on = "send_message"
        monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

        result = email_sender._send_via_smtp("dest@example.com", "Subj", "body")
        assert result is False

    def test_auth_failure_returns_false(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_SMTP_USER", "ops@example.com")
        monkeypatch.setenv("AETHER_SMTP_PASS", "wrong")
        _FakeSMTP.raise_on = "login"
        monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

        result = email_sender._send_via_smtp("dest@example.com", "Subj", "body")
        assert result is False

    def test_invalid_port_falls_back_to_587(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_SMTP_PORT", "not-a-number")
        monkeypatch.setenv("AETHER_SMTP_FROM", "noreply@example.com")
        monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

        result = email_sender._send_via_smtp("dest@example.com", "Subj", "body")
        assert result is True
        assert _FakeSMTP.last_instance.port == 587


# ---------------------------------------------------------------------------
# _send_via_api() — real function, fake httpx.post
# ---------------------------------------------------------------------------


class _FakeHttpResponse:
    def __init__(self, status_code, text="", body_json=None):
        self.status_code = status_code
        self.text = text
        self._body_json = body_json or {}

    def json(self):
        return self._body_json


class TestSendViaApi:
    def test_missing_from_address_returns_false_without_network_call(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        calls = []

        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append((a, k)))

        result = email_sender._send_via_api("dest@example.com", "Subject", "Body")
        assert result is False
        assert calls == []

    def test_successful_send_returns_true_with_correct_payload(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@example.com")
        captured = {}

        import httpx

        def _fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeHttpResponse(202)

        monkeypatch.setattr(httpx, "post", _fake_post)

        result = email_sender._send_via_api("dest@example.com", "Reset link", "body text")

        assert result is True
        assert captured["url"] == "https://api.resend.com/emails"
        assert captured["headers"]["Authorization"] == "Bearer re_test_key"
        assert captured["json"] == {
            "from": "noreply@example.com",
            "to": ["dest@example.com"],
            "subject": "Reset link",
            "text": "body text",
        }

    def test_http_error_status_returns_false(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@example.com")

        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeHttpResponse(401, "unauthorized"))

        result = email_sender._send_via_api("dest@example.com", "Subj", "body")
        assert result is False

    def test_network_exception_returns_false(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@example.com")

        import httpx

        def _raise(*a, **k):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "post", _raise)

        result = email_sender._send_via_api("dest@example.com", "Subj", "body")
        assert result is False


# ---------------------------------------------------------------------------
# send_email() — orchestration + delivery_degraded() state
# ---------------------------------------------------------------------------


class TestSendEmailOrchestration:
    def test_no_provider_returns_false_and_does_not_mark_degraded(self):
        result = email_sender.send_email("dest@example.com", "Subj", "body")
        assert result is False
        # "Not configured" is a distinct honest state from "configured but
        # failing" — it must not flip delivery_degraded().
        assert email_sender.delivery_degraded() is False

    def test_dispatches_to_smtp_when_smtp_configured(self, monkeypatch):
        monkeypatch.setenv("AETHER_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AETHER_SMTP_FROM", "noreply@example.com")
        monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

        result = email_sender.send_email("dest@example.com", "Subj", "body")

        assert result is True
        assert _FakeSMTP.last_instance is not None
        assert email_sender.delivery_degraded() is False

    def test_dispatches_to_api_when_only_api_configured(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@example.com")

        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeHttpResponse(200))

        result = email_sender.send_email("dest@example.com", "Subj", "body")
        assert result is True
        assert email_sender.delivery_degraded() is False

    def test_failed_attempt_marks_delivery_degraded(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@example.com")

        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeHttpResponse(500, "boom"))

        result = email_sender.send_email("dest@example.com", "Subj", "body")
        assert result is False
        assert email_sender.delivery_degraded() is True

    def test_subsequent_success_clears_degraded_state(self, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "re_test_key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@example.com")

        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeHttpResponse(500, "boom"))
        email_sender.send_email("dest@example.com", "Subj", "body")
        assert email_sender.delivery_degraded() is True

        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeHttpResponse(200))
        email_sender.send_email("dest@example.com", "Subj", "body")
        assert email_sender.delivery_degraded() is False
