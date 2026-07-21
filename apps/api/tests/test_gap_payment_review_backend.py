"""Payment-review remediation — backend correctness fixes.

Covers the LIVE-Stripe billing defects filed under
``uat/reports/evidence/payment-review`` (CONSOLIDATED-FINDINGS.json):

- PAY-R1-01  plan/quota sync from the subscription's PRICE ID on
             customer.subscription.updated (real portal upgrade/downgrade),
             price-id preferred over frozen metadata.
- PAY-R1-02/R3-01  no double-billing: POST /billing/checkout switches an
             existing active subscription's price IN PLACE instead of creating a
             second subscription.
- PAY-R2-02  charge.refunded (full) / charge.dispute.created revoke to Free +
             cancel the Stripe subscription; a partial refund does not.
- PAY-R3-04  admin-only POST /billing/admin/refund refunds the latest paid
             charge, downgrades to Free, audit-logs the action.
- PAY-R1-03/R2-04  invoice.paid resets the run/spend quota to the paid billing
             period; a non-renewal invoice does not.
- PAY-R1-04/R2-01/R1-05  past_due & trialing count as entitled (dunning grace /
             trial) end-to-end through the agent gate.

Mocked Stripe (ADR-P6-STRIPE-MOCK): the webhook signature is generated locally
with a test ``STRIPE_WEBHOOK_SECRET`` and verified through the real
``stripe.Webhook.construct_event`` (offline HMAC); all Stripe SDK write calls are
monkeypatched on ``app.services.stripe_gateway``.

NB: the ``Subscription`` / ``UsageQuota`` tables carry no FK to ``User`` and are
NOT truncated between tests (shared ``aether_test``), so every seeded row uses a
GLOBALLY-UNIQUE ``stripeCustomerId`` / ``stripeSubscriptionId`` (``new_id()``) —
otherwise a fixed id would collide with, or resolve back to, an orphaned row from
a prior run.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi import HTTPException

from app.db import get_connection, new_id
from app.repositories.billing import (
    PlanRepository,
    SubscriptionRepository,
    UsageQuotaRepository,
    ensure_user_billing,
)
from app.routers.agents import _record_run

WEBHOOK_SECRET = "whsec_test_payment_review_secret"


@pytest.fixture(autouse=True)
def _model_env(monkeypatch):
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")


def _tailor_stub():
    return {"resume_id": "r1", "changes": [], "rejected": []}


def _sign(payload: bytes, secret: str = WEBHOOK_SECRET, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    signed = f"{ts}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def _post_event(client, payload: bytes):
    return client.post(
        "/billing/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": _sign(payload)},
    )


def _seed_sub(
    user_id: str,
    *,
    plan_id: str,
    status: str = "active",
    interval: str = "month",
    runs_allowed: int = 100,
    runs_used: int = 0,
    spend_cap: float = 15.0,
) -> tuple[str, str]:
    """Force a user's Subscription + UsageQuota to a known paid state.

    Returns the GLOBALLY-UNIQUE ``(customer_id, subscription_id)`` it stamped, so
    the caller can build matching webhook payloads / assertions.
    """
    ensure_user_billing(user_id)
    customer_id = "cus_" + new_id()
    subscription_id = "sub_" + new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=%s,'
                '"billingInterval"=%s,"stripeCustomerId"=%s,'
                '"stripeSubscriptionId"=%s,"updatedAt"=now() WHERE "userId"=%s',
                (plan_id, status, interval, customer_id, subscription_id, user_id),
            )
            cur.execute(
                'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=%s,"runsUsed"=%s,'
                '"spendCapUsd"=%s,"updatedAt"=now() WHERE "userId"=%s',
                (plan_id, runs_allowed, runs_used, spend_cap, user_id),
            )
        conn.commit()
    return customer_id, subscription_id


# ---------------------------------------------------------------------------
# PAY-R1-01 — plan/quota sync from the subscription's price id
# ---------------------------------------------------------------------------


def _subscription_updated_event(
    subscription_id: str, price_id: str, *, metadata: dict | None = None
) -> bytes:
    return json.dumps(
        {
            "id": "evt_" + new_id(),
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": subscription_id,
                    "status": "active",
                    "cancel_at_period_end": False,
                    "current_period_start": 1_800_000_000,
                    "current_period_end": 1_802_592_000,
                    "metadata": metadata or {},
                    "items": {"data": [{"id": "si_x", "price": {"id": price_id}}]},
                }
            },
        }
    ).encode()


def test_subscription_updated_syncs_plan_from_price_id(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    PlanRepository().set_stripe_ids("power", price_monthly="price_power_month_pr01")
    # User is on Starter (30 runs); a portal upgrade to Power carries the POWER
    # price id but only STALE metadata (plan_id=starter).
    _cust, subid = _seed_sub(
        test_user_id, plan_id="starter", runs_allowed=30, spend_cap=5.0
    )
    payload = _subscription_updated_event(
        subid, "price_power_month_pr01", metadata={"plan_id": "starter"}
    )
    r = _post_event(client, payload)
    assert r.status_code == 200, r.text

    sub = SubscriptionRepository().get_by_user(test_user_id)
    assert sub["planId"] == "power"  # price id WON over the stale metadata
    assert sub["billingInterval"] == "month"
    quota = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(quota["runsAllowed"]) == 300
    assert float(quota["spendCapUsd"]) == 40.0


def test_subscription_updated_downgrade_from_price_id(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    PlanRepository().set_stripe_ids("starter", price_monthly="price_starter_month_pr01")
    _cust, subid = _seed_sub(
        test_user_id, plan_id="power", runs_allowed=300, spend_cap=40.0
    )
    payload = _subscription_updated_event(subid, "price_starter_month_pr01")
    r = _post_event(client, payload)
    assert r.status_code == 200, r.text
    quota = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(quota["runsAllowed"]) == 30  # downgrade reduced the ceiling


# ---------------------------------------------------------------------------
# PAY-R1-02 / R3-01 — checkout switches an existing sub instead of duplicating
# ---------------------------------------------------------------------------


def _mock_gateway(monkeypatch):
    import app.services.stripe_gateway as gw

    calls = {"switch": [], "create_session": 0, "cancel": []}

    def _switch(**kwargs):
        calls["switch"].append(kwargs)
        return {"id": kwargs.get("subscription_id")}

    def _create_session(**kwargs):
        calls["create_session"] += 1
        return {"id": "cs_x", "url": "https://checkout.stripe.com/c/pay/cs_x"}

    monkeypatch.setattr(gw, "is_configured", lambda: True)
    monkeypatch.setattr(gw, "switch_subscription_price", _switch)
    monkeypatch.setattr(gw, "create_checkout_session", _create_session)
    monkeypatch.setattr(
        gw, "create_customer", lambda *, email, user_id: "cus_new_" + user_id[:8]
    )
    monkeypatch.setattr(gw, "cancel_subscription", lambda sid: calls["cancel"].append(sid))
    return calls


def test_checkout_switches_existing_subscription_no_double_billing(
    client, auth_headers, test_user_id, monkeypatch
):
    PlanRepository().set_stripe_ids("power", price_monthly="price_power_month_sw")
    _cust, subid = _seed_sub(
        test_user_id, plan_id="pro", runs_allowed=100, runs_used=10
    )
    calls = _mock_gateway(monkeypatch)

    r = client.post(
        "/billing/checkout",
        json={"planId": "power", "interval": "month"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["switched"] is True
    assert body["planId"] == "power"
    assert "checkoutUrl" not in body
    # Switched IN PLACE — no new Checkout Session was created.
    assert calls["create_session"] == 0
    assert len(calls["switch"]) == 1
    assert calls["switch"][0]["subscription_id"] == subid
    assert calls["switch"][0]["new_price_id"] == "price_power_month_sw"

    sub = SubscriptionRepository().get_by_user(test_user_id)
    assert sub["planId"] == "power"
    quota = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(quota["runsAllowed"]) == 300
    # In-place switch keeps the current period's usage (no free quota reset).
    assert int(quota["runsUsed"]) == 10


def test_checkout_same_plan_switch_is_noop_ack(
    client, auth_headers, test_user_id, monkeypatch
):
    PlanRepository().set_stripe_ids("pro", price_monthly="price_pro_month_sw")
    _seed_sub(test_user_id, plan_id="pro")
    calls = _mock_gateway(monkeypatch)
    r = client.post(
        "/billing/checkout",
        json={"planId": "pro", "interval": "month"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["switched"] is True
    # Already on this plan+interval — no Stripe call at all.
    assert calls["create_session"] == 0
    assert calls["switch"] == []


def test_checkout_free_user_still_gets_checkout_url(
    client, auth_headers, test_user_id, monkeypatch
):
    PlanRepository().set_stripe_ids("pro", price_monthly="price_pro_month_new")
    ensure_user_billing(test_user_id)  # Free, no stripeSubscriptionId
    calls = _mock_gateway(monkeypatch)
    r = client.post(
        "/billing/checkout",
        json={"planId": "pro", "interval": "month"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checkoutUrl"].startswith("https://checkout.stripe.com/")
    assert calls["create_session"] == 1
    assert calls["switch"] == []


# ---------------------------------------------------------------------------
# PAY-R2-02 — refund / dispute revoke to Free + cancel subscription
# ---------------------------------------------------------------------------


def _charge_refunded_event(
    customer_id: str, *, refunded: bool, amount: int, refunded_amt: int
) -> bytes:
    return json.dumps(
        {
            "id": "evt_" + new_id(),
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_" + new_id(),
                    "customer": customer_id,
                    "refunded": refunded,
                    "amount": amount,
                    "amount_refunded": refunded_amt,
                }
            },
        }
    ).encode()


def test_full_refund_revokes_to_free_and_cancels_subscription(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    calls = _mock_gateway(monkeypatch)
    cust, subid = _seed_sub(test_user_id, plan_id="power", runs_allowed=300)
    payload = _charge_refunded_event(cust, refunded=True, amount=6900, refunded_amt=6900)
    r = _post_event(client, payload)
    assert r.status_code == 200, r.text

    sub = SubscriptionRepository().get_by_user(test_user_id)
    assert sub["planId"] == "free"
    assert sub["status"] == "canceled"
    assert sub["stripeSubscriptionId"] is None
    quota = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(quota["runsAllowed"]) == 5
    # The Stripe subscription was canceled so billing stops.
    assert calls["cancel"] == [subid]


def test_partial_refund_does_not_revoke(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    _mock_gateway(monkeypatch)
    cust, _subid = _seed_sub(test_user_id, plan_id="power", runs_allowed=300)
    payload = _charge_refunded_event(cust, refunded=False, amount=6900, refunded_amt=1000)
    r = _post_event(client, payload)
    assert r.status_code == 200, r.text
    sub = SubscriptionRepository().get_by_user(test_user_id)
    assert sub["planId"] == "power"  # partial refund left entitlement intact


def test_dispute_created_revokes_to_free(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    calls = _mock_gateway(monkeypatch)
    cust, subid = _seed_sub(test_user_id, plan_id="pro", runs_allowed=100)
    payload = json.dumps(
        {
            "id": "evt_" + new_id(),
            "type": "charge.dispute.created",
            "data": {
                "object": {
                    "id": "dp_" + new_id(),
                    "charge": "ch_disp",
                    "customer": cust,
                    "reason": "fraudulent",
                }
            },
        }
    ).encode()
    r = _post_event(client, payload)
    assert r.status_code == 200, r.text
    sub = SubscriptionRepository().get_by_user(test_user_id)
    assert sub["planId"] == "free"
    assert sub["status"] == "canceled"
    assert calls["cancel"] == [subid]


# ---------------------------------------------------------------------------
# PAY-R1-03 / R2-04 — invoice.paid resets the quota to the billing period
# ---------------------------------------------------------------------------


def _invoice_paid_event(
    subscription_id: str, customer_id: str, billing_reason: str
) -> bytes:
    return json.dumps(
        {
            "id": "evt_" + new_id(),
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_" + new_id(),
                    "subscription": subscription_id,
                    "customer": customer_id,
                    "billing_reason": billing_reason,
                    "lines": {
                        "data": [
                            {"period": {"start": 1_800_000_000, "end": 1_802_592_000}}
                        ]
                    },
                }
            },
        }
    ).encode()


def test_invoice_paid_renewal_resets_quota_and_restores_active(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    # A failed charge left them past_due; the retry paid.
    cust, subid = _seed_sub(
        test_user_id, plan_id="pro", status="past_due", runs_allowed=100, runs_used=50
    )
    payload = _invoice_paid_event(subid, cust, "subscription_cycle")
    r = _post_event(client, payload)
    assert r.status_code == 200, r.text

    quota = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(quota["runsUsed"]) == 0  # reset for the new paid period
    assert int(quota["periodEnd"].timestamp()) == 1_802_592_000
    sub = SubscriptionRepository().get_by_user(test_user_id)
    assert sub["status"] == "active"  # successful renewal restored active


def test_invoice_paid_non_renewal_does_not_reset(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    cust, subid = _seed_sub(
        test_user_id, plan_id="pro", runs_allowed=100, runs_used=50
    )
    payload = _invoice_paid_event(subid, cust, "manual")
    r = _post_event(client, payload)
    assert r.status_code == 200, r.text
    quota = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(quota["runsUsed"]) == 50  # untouched — not a subscription renewal


# ---------------------------------------------------------------------------
# PAY-R1-04 / R2-01 / R1-05 — dunning grace + trialing entitled through the gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["past_due", "trialing"])
def test_gate_allows_dunning_and_trialing(
    client, auth_headers, test_user_id, monkeypatch, status
):
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _seed_sub(test_user_id, plan_id="pro", status=status, runs_allowed=100)
    # Entitled during dunning / trial — the agent gate must let the run through.
    out = _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    assert out["resume_id"] == "r1"
    q = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(q["runsUsed"]) == 1


# ---------------------------------------------------------------------------
# PAY-R3-04 — admin refund endpoint
# ---------------------------------------------------------------------------


def _register(client, email: str, password: str = "Passw0rd1") -> tuple[str, str]:
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (201, 409), r.text
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    body = login.json()
    return body["access_token"], body["userId"]


def _admin_headers(client) -> tuple[dict[str, str], str]:
    from app.repositories.admin import _ensure_admin_schema

    token, uid = _register(client, f"admin-{uuid.uuid4().hex[:8]}@example.com")
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (uid,))
        conn.commit()
    return {"Authorization": f"Bearer {token}"}, uid


def _mock_refund_gateway(monkeypatch):
    import app.services.stripe_gateway as gw

    calls = {"cancel": [], "refund_charge": None}
    monkeypatch.setattr(gw, "is_configured", lambda: True)
    monkeypatch.setattr(gw, "latest_paid_charge", lambda cid: "ch_admin_x")

    def _refund(charge_id):
        calls["refund_charge"] = charge_id
        return {"id": "re_admin_x", "status": "succeeded"}

    monkeypatch.setattr(gw, "create_refund", _refund)
    monkeypatch.setattr(gw, "cancel_subscription", lambda sid: calls["cancel"].append(sid))
    return calls


def test_admin_refund_downgrades_and_audits(client, monkeypatch):
    admin_headers, _admin_id = _admin_headers(client)
    target_email = f"target-{uuid.uuid4().hex[:8]}@example.com"
    _token, target_id = _register(client, target_email)
    _cust, subid = _seed_sub(target_id, plan_id="power", runs_allowed=300)
    calls = _mock_refund_gateway(monkeypatch)

    r = client.post(
        "/billing/admin/refund", json={"userId": target_id}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refundId"] == "re_admin_x"
    assert body["status"] == "succeeded"
    assert body["planId"] == "free"
    assert calls["refund_charge"] == "ch_admin_x"
    assert calls["cancel"] == [subid]

    sub = SubscriptionRepository().get_by_user(target_id)
    assert sub["planId"] == "free" and sub["status"] == "canceled"
    quota = UsageQuotaRepository().get_by_user(target_id)
    assert int(quota["runsAllowed"]) == 5

    # An immutable audit row was written for the refund.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "AdminAuditLog" '
                "WHERE \"action\"='billing_refund' AND \"targetId\"=%s",
                (target_id,),
            )
            assert cur.fetchone()[0] == 1


def test_admin_refund_by_email(client, monkeypatch):
    admin_headers, _admin_id = _admin_headers(client)
    target_email = f"target-{uuid.uuid4().hex[:8]}@example.com"
    _token, target_id = _register(client, target_email)
    _seed_sub(target_id, plan_id="pro")
    _mock_refund_gateway(monkeypatch)
    r = client.post(
        "/billing/admin/refund", json={"email": target_email}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["planId"] == "free"


def test_admin_refund_requires_admin(client, auth_headers, monkeypatch):
    # A normal (non-admin) authenticated user must get 403.
    r = client.post(
        "/billing/admin/refund", json={"userId": "whoever"}, headers=auth_headers
    )
    assert r.status_code == 403, r.text


def test_admin_refund_no_paid_charge_is_404(client, monkeypatch):
    admin_headers, _admin_id = _admin_headers(client)
    _token, target_id = _register(client, f"target-{uuid.uuid4().hex[:8]}@example.com")
    _seed_sub(target_id, plan_id="pro")
    import app.services.stripe_gateway as gw

    monkeypatch.setattr(gw, "is_configured", lambda: True)
    monkeypatch.setattr(gw, "latest_paid_charge", lambda cid: None)
    r = client.post(
        "/billing/admin/refund", json={"userId": target_id}, headers=admin_headers
    )
    assert r.status_code == 404, r.text
