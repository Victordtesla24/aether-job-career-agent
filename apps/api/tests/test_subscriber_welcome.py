"""Subscriber welcome — the Aether-owned onboarding email.

Two surfaces, one renderer:

* Admin portal preview (``brand_documents`` kind ``subscriber_welcome``) so
  operators see the exact obsidian-and-gilt HTML a new account receives.
* ``POST /auth/register`` sends that same template when outbound email is
  configured. A send failure MUST NOT fail registration.
"""
from __future__ import annotations

import uuid

import pytest

from app.services.email_branding import (
    PALETTE,
    build_subscriber_welcome_bodies,
)

DASHBOARD = "https://5cb5f0620.abacusai.cloud/dashboard"


@pytest.fixture()
def admin_headers(client, auth_headers, promote_user_to_admin, monkeypatch):
    """Promote the fixture user so Brand-tab preview routes authorize."""
    promote_user_to_admin(client._test_user_id)
    me = client.get("/auth/me", headers=auth_headers).json()
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", me["email"])
    return auth_headers


class TestWelcomeBodies:
    def test_gilt_bulletproof_html_and_complete_plain_text(self) -> None:
        html, text = build_subscriber_welcome_bodies(
            name="Ada Lovelace",
            plan_name="Free",
            runs_per_month=5,
            dashboard_url=DASHBOARD,
        )
        lowered = html.lower()
        assert html.lstrip().lower().startswith("<!doctype html>")
        assert PALETTE["gold"] in lowered
        assert PALETTE["ink0"] in lowered
        assert "<img" not in lowered
        assert "<style" not in lowered
        assert "<link" not in lowered
        assert "Ada Lovelace" in html and "Ada Lovelace" in text
        assert "Free" in html and "Free" in text
        assert "5" in html and "5" in text
        assert DASHBOARD in html and DASHBOARD in text
        assert "<" not in text
        assert "AETHER" in html

    def test_missing_name_does_not_invent_a_greeting(self) -> None:
        html, text = build_subscriber_welcome_bodies(
            name=None,
            plan_name="Free",
            runs_per_month=5,
            dashboard_url=DASHBOARD,
        )
        assert "Hi," in html
        assert "Hi," in text
        assert "None" not in html
        assert "there" not in text.lower()


class TestAdminPreview:
    def test_registry_lists_subscriber_welcome(self, client, admin_headers) -> None:
        resp = client.get(
            "/admin/sales-agent/brand/documents", headers=admin_headers
        )
        assert resp.status_code == 200
        kinds = {d["kind"] for d in resp.json()["documents"]}
        assert "subscriber_welcome" in kinds

    def test_preview_uses_live_free_plan_quota_and_gilt(self, client, admin_headers) -> None:
        resp = client.get(
            "/admin/sales-agent/brand/documents/subscriber_welcome/preview"
            "?plan=free&interval=monthly",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        html = resp.json()["html"]
        assert PALETTE["gold"] in html.lower()
        assert "{{name}}" in html
        assert "Free" in html
        # Live catalog: Free plan is 5 runs/month.
        assert "5" in html
        assert "AB Entertainment" not in html


class TestRegisterSendsWelcome:
    def test_register_sends_branded_welcome_when_email_configured(
        self, client, monkeypatch
    ) -> None:
        from app.services import email_sender as sender_mod

        captured: dict = {}

        def _fake_send(to_email, subject, text_body, html_body=None):
            captured.update(
                {
                    "to": to_email,
                    "subject": subject,
                    "text": text_body,
                    "html": html_body,
                }
            )
            return True

        monkeypatch.setattr(sender_mod, "is_configured", lambda: True)
        monkeypatch.setattr(sender_mod, "send_email", _fake_send)

        email = f"welcome-{uuid.uuid4().hex[:10]}@example.com"
        resp = client.post(
            "/auth/register",
            json={"email": email, "password": "Passw0rd1", "name": "Ada Lovelace"},
        )
        assert resp.status_code == 201, resp.text
        assert captured["to"] == email
        assert captured["html"]
        assert PALETTE["gold"] in captured["html"].lower()
        assert "Ada Lovelace" in captured["text"]
        assert "/dashboard" in captured["html"]

    def test_register_still_succeeds_when_welcome_send_raises(
        self, client, monkeypatch
    ) -> None:
        from app.services import email_sender as sender_mod

        def _boom(*_args, **_kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr(sender_mod, "is_configured", lambda: True)
        monkeypatch.setattr(sender_mod, "send_email", _boom)

        email = f"welcome-fail-{uuid.uuid4().hex[:10]}@example.com"
        resp = client.post(
            "/auth/register",
            json={"email": email, "password": "Passw0rd1"},
        )
        assert resp.status_code == 201, resp.text

    def test_register_does_not_send_when_email_unconfigured(
        self, client, monkeypatch
    ) -> None:
        from app.services import email_sender as sender_mod

        monkeypatch.setattr(sender_mod, "is_configured", lambda: False)
        called = {"n": 0}

        def _should_not_run(*_args, **_kwargs):
            called["n"] += 1
            return True

        monkeypatch.setattr(sender_mod, "send_email", _should_not_run)
        email = f"welcome-silent-{uuid.uuid4().hex[:10]}@example.com"
        resp = client.post(
            "/auth/register",
            json={"email": email, "password": "Passw0rd1"},
        )
        assert resp.status_code == 201, resp.text
        assert called["n"] == 0
