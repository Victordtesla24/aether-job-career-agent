"""Every Aether-owned artefact lives in the Brand tab and uses gilt chrome.

Preview HTML is the same renderer the live send path uses. Carve-outs
(candidate → employer application mail, recruiter outreach from the
candidate's Gmail) stay unbranded — pinned in test_brand_email_adoption.
"""
from __future__ import annotations

import pytest

from app.db import new_id
from app.services.email_branding import (
    PALETTE,
    build_cancellation_confirmed_bodies,
    build_notification_digest_bodies,
    build_payment_failed_bodies,
    build_subscription_confirmed_bodies,
    build_trial_ending_bodies,
)

EXPECTED_KINDS = {
    "invoice",
    "auto_reply",
    "subscription_confirmed",
    "payment_failed",
    "cancellation_confirmed",
    "subscriber_welcome",
    "password_reset",
    "founder_digest",
    "notification_digest",
    "trial_ending",
    "sales_outreach",
    "ops_alert",
    "business_card",
    "document",
}

WEBHOOK_SECRET = "whsec_test_brand_lifecycle"


@pytest.fixture()
def admin_headers(client, auth_headers, promote_user_to_admin, monkeypatch):
    promote_user_to_admin(client._test_user_id)
    me = client.get("/auth/me", headers=auth_headers).json()
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", me["email"])
    return auth_headers


def _assert_gilt_bulletproof(html: str) -> None:
    lowered = html.lower()
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert PALETTE["gold"] in lowered
    assert PALETTE["ink0"] in lowered
    assert "<img" not in lowered
    assert "<style" not in lowered
    assert "<link" not in lowered
    assert "aether" in lowered


_CATALOGUE_PLAN = {
    "id": "starter",
    "name": "Starter",
    "priceAudMonthly": 19,
    "priceAudAnnual": 190,
    "runsPerMonth": 25,
}


def test_catalogue_kinds_are_exactly_document_kinds() -> None:
    from app.services.brand_documents import DOCUMENT_KINDS

    assert set(DOCUMENT_KINDS) == EXPECTED_KINDS


def test_every_catalogue_kind_renders_gilt_and_honours_img_allow_list() -> None:
    from app.services.brand_documents import DOCUMENT_KINDS, render_document

    for kind, meta in DOCUMENT_KINDS.items():
        html = render_document(
            kind, plan=_CATALOGUE_PLAN if meta["needsPlan"] else None
        )
        lowered = html.lower()
        assert "#c9a84c" in lowered, kind
        assert "#08080a" in lowered, kind
        assert "<style" not in lowered, kind
        assert "<link" not in lowered, kind
        if meta.get("allowsImg"):
            assert "<img" in lowered, (
                f"{kind} is on the img allow-list but rendered no <img>"
            )
        else:
            assert "<img" not in lowered, (
                f"{kind} is not on the img allow-list but rendered an <img>"
            )


def test_sales_outreach_preview_is_the_live_gmail_wrapper() -> None:
    from app.agents.sales_agent import append_compliance_footer
    from app.services.brand_documents import render_document
    from app.services.sales_branding import render_sales_outreach_html

    html = render_document("sales_outreach")
    live = render_sales_outreach_html(
        "{{subject}}",
        append_compliance_footer("Hi {{name}},\n\n{{body}}"),
    )
    assert html == live
    assert "{{name}}" in html
    assert "{{subject}}" in html
    assert "{{body}}" in html
    assert "unsubscribe" in html.lower()
    assert "<img" in html.lower()


def test_ops_alert_preview_is_the_live_gilt_builder() -> None:
    from app.services.brand_documents import render_document
    from app.services.email_branding import PALETTE, PRODUCT_NAME, build_ops_alert_bodies

    html = render_document("ops_alert")
    live, text = build_ops_alert_bodies(
        unit="{{unit}}",
        timestamp="{{timestamp}}",
        log_excerpt="{{log_excerpt}}",
        log_path="{{log_path}}",
    )
    assert html == live
    assert PALETTE["gold"] in html.lower()
    assert PALETTE["ink0"] in html.lower()
    assert "<img" not in html.lower()
    assert "{{unit}}" in html
    assert "{{log_excerpt}}" in html
    assert PRODUCT_NAME in html
    assert PRODUCT_NAME in text
    assert "!" not in text


def test_ops_alert_script_posts_the_gilt_html_field() -> None:
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[3] / "scripts" / "ops_alert.sh"
    ).read_text()
    assert "build_ops_alert_bodies" in script
    assert 'payload["html"] = html' in script


def test_founder_digest_preview_and_live_share_one_builder() -> None:
    from app.services.email_branding import (
        FOUNDER_DIGEST_STATS,
        build_founder_digest_bodies,
        build_founder_digest_preview_bodies,
    )

    preview_html, _preview_text = build_founder_digest_preview_bodies()
    values = {key: f"v-{key}" for _label, key in FOUNDER_DIGEST_STATS}
    live_html, live_text = build_founder_digest_bodies(
        date="2026-08-17",
        values=values,
        admin_url="https://example.test/admin",
    )
    for label, key in FOUNDER_DIGEST_STATS:
        assert label in preview_html
        assert label in live_html
        token = "{{" + key + "}}"
        assert token in preview_html
        assert f"v-{key}" in live_html
        assert f"v-{key}" in live_text
    assert "<img" not in preview_html.lower()
    assert "<img" not in live_html.lower()


def test_registry_is_the_single_brand_catalogue(client, admin_headers) -> None:
    resp = client.get("/admin/sales-agent/brand/documents", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    kinds = {d["kind"] for d in resp.json()["documents"]}
    assert kinds == EXPECTED_KINDS


def test_password_reset_preview_is_the_live_gilt_template(
    client, admin_headers
) -> None:
    resp = client.get(
        "/admin/sales-agent/brand/documents/password_reset/preview",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    html = resp.json()["html"]
    _assert_gilt_bulletproof(html)
    assert "{{reset_url}}" in html


def test_founder_digest_preview_uses_merge_fields_not_invented_metrics(
    client, admin_headers
) -> None:
    resp = client.get(
        "/admin/sales-agent/brand/documents/founder_digest/preview",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    html = resp.json()["html"]
    _assert_gilt_bulletproof(html)
    assert "{{signups}}" in html
    assert "{{mrr_aud}}" in html


def test_notification_digest_preview_is_gilt(client, admin_headers) -> None:
    resp = client.get(
        "/admin/sales-agent/brand/documents/notification_digest/preview",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    html = resp.json()["html"]
    _assert_gilt_bulletproof(html)
    assert "{{digest_body}}" in html


def test_stripe_lifecycle_previews_are_sendable_gilt_not_logo_chrome(
    client, admin_headers
) -> None:
    for kind in (
        "subscription_confirmed",
        "payment_failed",
        "cancellation_confirmed",
        "trial_ending",
    ):
        resp = client.get(
            f"/admin/sales-agent/brand/documents/{kind}/preview"
            "?plan=starter&interval=monthly",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        html = resp.json()["html"]
        _assert_gilt_bulletproof(html)
        assert "{{name}}" in html
        if kind != "cancellation_confirmed":
            assert "A$19.00" in html or "Starter" in html


def test_auto_reply_preview_is_gilt_bulletproof(client, admin_headers) -> None:
    resp = client.get(
        "/admin/sales-agent/brand/documents/auto_reply/preview",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    _assert_gilt_bulletproof(resp.json()["html"])
    assert "{{name}}" in resp.json()["html"]


def test_business_card_preview_is_obsidian_and_gilt(client, admin_headers) -> None:
    resp = client.get(
        "/admin/sales-agent/brand/documents/business_card/preview",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    html = resp.json()["html"]
    lowered = html.lower()
    assert "<svg" in lowered
    assert "#c9a84c" in lowered or "#C9A84C" in html
    assert "#08080a" in lowered or "#08080A" in html
    assert "{{name}}" in html
    assert "<img" not in lowered


def test_document_preview_uses_branded_artefact_chrome(
    client, admin_headers
) -> None:
    resp = client.get(
        "/admin/sales-agent/brand/documents/document/preview",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    html = resp.json()["html"]
    _assert_gilt_bulletproof(html)
    assert "{{title}}" in html
    assert "{{body}}" in html


def test_lifecycle_builders_are_pure_and_bulletproof() -> None:
    plan = {
        "name": "Pro",
        "priceAudMonthly": 39,
        "priceAudAnnual": 359,
        "runsPerMonth": 100,
    }
    html, text = build_subscription_confirmed_bodies(
        "Ada", plan, "monthly", "https://example.test/dashboard"
    )
    _assert_gilt_bulletproof(html)
    assert "Ada" in html and "Ada" in text
    assert "Pro" in html and "A$39.00" in text
    assert "<" not in text

    html, text = build_payment_failed_bodies(
        None, plan, "monthly", "https://example.test/settings"
    )
    _assert_gilt_bulletproof(html)
    assert "Hi," in html
    assert "A$39.00" in text

    html, text = build_cancellation_confirmed_bodies(
        "Ada", plan, "31 August 2026", "https://example.test/pricing"
    )
    _assert_gilt_bulletproof(html)
    assert "31 August 2026" in html and "31 August 2026" in text
    assert "Free plan" in text

    html, text = build_trial_ending_bodies(
        "Ada", plan, "monthly", "https://example.test/settings"
    )
    _assert_gilt_bulletproof(html)
    assert "trial" in html.lower()
    assert "Pro" in text

    html, text = build_notification_digest_bodies(
        "Your Aether digest",
        "Status updates this window:\n- Acme — interview",
    )
    _assert_gilt_bulletproof(html)
    assert "Acme — interview" in html
    assert "Acme — interview" in text


def test_checkout_webhook_sends_branded_mail_after_commit(
    client, auth_headers, test_user_id, monkeypatch
) -> None:
    import hashlib
    import hmac
    import json
    import time

    from app.repositories.billing import SubscriptionRepository

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    captured: list[dict[str, object]] = []

    def _fake_send(to_email, subject, text_body, html_body=None):
        captured.append(
            {
                "to": to_email,
                "subject": subject,
                "text": text_body,
                "html": html_body,
            }
        )
        return True

    monkeypatch.setattr("app.services.email_sender.is_configured", lambda: True)
    monkeypatch.setattr("app.services.email_sender.send_email", _fake_send)

    me = client.get("/auth/me", headers=auth_headers).json()
    payload = json.dumps(
        {
            "id": "evt_" + new_id(),
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_" + new_id(),
                    "customer": "cus_test_" + new_id(),
                    "subscription": "sub_test_" + new_id(),
                    "client_reference_id": test_user_id,
                    "metadata": {
                        "user_id": test_user_id,
                        "plan_id": "pro",
                        "interval": "month",
                    },
                }
            },
        }
    ).encode()
    ts = int(time.time())
    digest = hmac.new(
        WEBHOOK_SECRET.encode(), f"{ts}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    resp = client.post(
        "/billing/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": f"t={ts},v1={digest}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "processed"
    sub = SubscriptionRepository().get_by_user(test_user_id)
    assert sub["planId"] == "pro"
    assert len(captured) == 1
    call = captured[0]
    assert call["to"] == me["email"]
    html = str(call["html"])
    _assert_gilt_bulletproof(html)
    assert "Pro" in html
    assert "A$39.00" in str(call["text"])


def test_checkout_webhook_send_failure_does_not_roll_back_entitlement(
    client, auth_headers, test_user_id, monkeypatch
) -> None:
    import hashlib
    import hmac
    import json
    import time

    from app.repositories.billing import SubscriptionRepository

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setattr("app.services.email_sender.is_configured", lambda: True)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.services.email_sender.send_email", _boom)
    payload = json.dumps(
        {
            "id": "evt_" + new_id(),
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_" + new_id(),
                    "customer": "cus_test_" + new_id(),
                    "subscription": "sub_test_" + new_id(),
                    "client_reference_id": test_user_id,
                    "metadata": {
                        "user_id": test_user_id,
                        "plan_id": "starter",
                        "interval": "month",
                    },
                }
            },
        }
    ).encode()
    ts = int(time.time())
    digest = hmac.new(
        WEBHOOK_SECRET.encode(), f"{ts}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    resp = client.post(
        "/billing/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": f"t={ts},v1={digest}"},
    )
    assert resp.status_code == 200, resp.text
    assert SubscriptionRepository().get_by_user(test_user_id)["planId"] == "starter"


def test_notification_digest_execute_sends_gilt_html(
    client, auth_headers, test_user_id, monkeypatch
) -> None:
    from app.repositories.approval import ApprovalRepository
    from app.repositories.gmail_account import GmailAccountRepository
    from app.services import credential_vault as vault

    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
    repo = GmailAccountRepository()
    repo.upsert_account(
        test_user_id,
        account_email="me@gmail.com",
        refresh_token="r-digest",
        scopes="gmail.send",
    )
    captured: dict[str, object] = {}

    def _fake_send(self, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return {"id": "gmail-digest-1", "threadId": "T"}

    monkeypatch.setattr("app.services.gmail_service.GmailService.send", _fake_send)
    try:
        digest_body = "Status updates this window:\n- Northwind — interview"
        approval = ApprovalRepository().create(
            test_user_id,
            "email_send",
            {
                "kind": "notification_digest",
                "to": "me@gmail.com",
                "subject": "Your Aether digest",
                "body": digest_body,
            },
        )
        assert client.post(
            f"/approvals/{approval['id']}/approve", headers=auth_headers
        ).status_code == 200
        executed = client.post(
            f"/approvals/{approval['id']}/execute", headers=auth_headers
        )
        assert executed.status_code == 200, executed.text
        assert captured["body"] == digest_body
        html = str(captured["html_body"])
        _assert_gilt_bulletproof(html)
        assert "Northwind — interview" in html
    finally:
        repo.disconnect(test_user_id)


def test_candidate_gmail_send_stays_unbranded(
    client, auth_headers, test_user_id, monkeypatch
) -> None:
    from app.repositories.gmail_account import GmailAccountRepository
    from app.services import credential_vault as vault

    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
    repo = GmailAccountRepository()
    repo.upsert_account(
        test_user_id,
        account_email="me@gmail.com",
        refresh_token="r-outreach",
        scopes="gmail.send",
    )
    captured: dict[str, object] = {}

    def _fake_send(self, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return {"id": "gmail-out-1", "threadId": "T"}

    monkeypatch.setattr("app.services.gmail_service.GmailService.send", _fake_send)
    try:
        run = client.post(
            "/agents/email/run",
            json={
                "mode": "send",
                "to": "recruiter@acme.com",
                "subject": "Following up",
                "body": "Dear hiring team,\n\nI led the payments rewrite.",
            },
            headers=auth_headers,
        )
        assert run.status_code == 200, run.text
        approval_id = run.json()["approval_id"]
        assert client.post(
            f"/approvals/{approval_id}/approve", headers=auth_headers
        ).status_code == 200
        executed = client.post(
            f"/approvals/{approval_id}/execute", headers=auth_headers
        )
        assert executed.status_code == 200, executed.text
        assert captured.get("html_body") in (None, "")
        assert "AETHER" not in str(captured["body"])
    finally:
        repo.disconnect(test_user_id)
