"""GAP-P6-BILL-001 / BILL-002 / PRICING-001 — billing spine (Cluster D).

Mocked-Stripe unit coverage (ADR-P6-STRIPE-MOCK): no live Stripe keys are used.
The webhook signature is generated locally with a test ``STRIPE_WEBHOOK_SECRET``
and verified through the real ``stripe.Webhook.construct_event`` (offline HMAC),
so the raw-body-before-parse + signature + idempotency contract is exercised
end-to-end without any network.

Covers:
- GET /billing/plans returns the RATIFIED tiers (ADR-P6-PRICING) with the GST
  breakdown pre-computed as ``round(total/11, 2)``.
- Webhook: raw-body FIRST, signature SECOND, parse THIRD; bad/missing signature
  -> 400; a valid event is processed once; a duplicate event is a 200 no-op
  (no second entitlement); a handler that raises rolls the whole txn back so the
  StripeEvent row is absent (Stripe retry-safe).
- Checkout create-or-reuse Stripe Customer (mocked gateway).
- Quota: atomic reserve-before-run, 429 on exhaustion (upgradeUrl + quotaReset),
  USD spend-cap refund + 429, refund on a failed run, spend recorded on success.
- GATE-34 backfill assigns every existing user a Free Subscription + initialized
  UsageQuota.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException

from app.db import get_connection, new_id
from app.repositories.billing import (
    PlanRepository,
    SubscriptionRepository,
    UsageQuotaRepository,
    _ensure_billing_tables,
    _reset_billing_ready_for_tests,
    ensure_user_billing,
    gst_breakdown,
)
from app.routers.agents import _record_run

WEBHOOK_SECRET = "whsec_test_p6_billing_secret"


@pytest.fixture(autouse=True)
def _model_env(monkeypatch):
    # Metered agents resolve a model for cost computation; pin it so the
    # quota/spend path is deterministic (mirrors test_gap_d3_agent_config).
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")


def _tailor_stub():
    return {"resume_id": "r1", "changes": [], "rejected": []}


def _sign(payload: bytes, secret: str = WEBHOOK_SECRET, ts: int | None = None) -> str:
    """Build a Stripe-Signature header over the EXACT raw bytes (offline HMAC)."""
    ts = ts or int(time.time())
    signed = f"{ts}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def _checkout_event(user_id: str, plan_id: str, evt_id: str) -> bytes:
    """A minimal checkout.session.completed event payload (raw JSON bytes)."""
    return json.dumps(
        {
            "id": evt_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_" + new_id(),
                    "customer": "cus_test_" + new_id(),
                    "subscription": "sub_test_" + new_id(),
                    "client_reference_id": user_id,
                    "metadata": {
                        "user_id": user_id,
                        "plan_id": plan_id,
                        "interval": "month",
                    },
                }
            },
        }
    ).encode()


# ---------------------------------------------------------------------------
# GET /billing/plans + GST math (GAP-P6-PRICING-001 / ADR-P6-PRICING)
# ---------------------------------------------------------------------------


def test_plans_endpoint_is_public_and_returns_ratified_tiers(client):
    r = client.get("/billing/plans")  # no auth header — public
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "AUD"
    assert body["gstIncluded"] is True
    plans = {p["id"]: p for p in body["plans"]}
    assert set(plans) == {"free", "starter", "pro", "power"}
    # Ratified prices (ADR-P6-PRICING), NOT the design's proposals.
    assert plans["free"]["monthly"]["total"] == 0
    assert plans["free"]["runsPerMonth"] == 5
    assert plans["starter"]["monthly"]["total"] == 19
    assert plans["starter"]["annual"]["total"] == 179
    assert plans["starter"]["runsPerMonth"] == 30
    assert plans["pro"]["monthly"]["total"] == 39
    assert plans["pro"]["annual"]["total"] == 359
    assert plans["pro"]["runsPerMonth"] == 100
    assert plans["power"]["monthly"]["total"] == 69
    assert plans["power"]["annual"]["total"] == 649
    assert plans["power"]["runsPerMonth"] == 300
    # Free has no annual price.
    assert plans["free"]["annual"] is None


def test_gst_breakdown_is_round_total_over_11_for_each_tier():
    # Monthly (ratified)
    assert gst_breakdown(19) == {"total": 19.0, "gst": 1.73, "net": 17.27}
    assert gst_breakdown(39) == {"total": 39.0, "gst": 3.55, "net": 35.45}
    assert gst_breakdown(69) == {"total": 69.0, "gst": 6.27, "net": 62.73}
    # Annual (ratified)
    assert gst_breakdown(179)["gst"] == round(179 / 11, 2)
    assert gst_breakdown(359)["gst"] == round(359 / 11, 2)
    assert gst_breakdown(649)["gst"] == round(649 / 11, 2)
    for total in (0, 19, 39, 69, 179, 359, 649):
        b = gst_breakdown(total)
        assert b["gst"] == round(total / 11, 2)
        assert b["net"] == round(total - b["gst"], 2)


def test_plans_endpoint_gst_line_matches_helper(client):
    body = client.get("/billing/plans").json()
    for p in body["plans"]:
        assert p["monthly"]["gst"] == round(p["monthly"]["total"] / 11, 2)
        if p["annual"] is not None:
            assert p["annual"]["gst"] == round(p["annual"]["total"] / 11, 2)


# ---------------------------------------------------------------------------
# Webhook: raw body FIRST -> signature SECOND -> parse THIRD (GAP-P6-BILL-001)
# ---------------------------------------------------------------------------


def test_webhook_missing_signature_header_is_400(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    payload = _checkout_event("u1", "pro", "evt_" + new_id())
    r = client.post("/billing/webhooks/stripe", content=payload)
    assert r.status_code == 400


def test_webhook_bad_signature_is_400_and_writes_nothing(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    evt_id = "evt_" + new_id()
    payload = _checkout_event("u1", "pro", evt_id)
    r = client.post(
        "/billing/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": "t=1,v1=deadbeef"},
    )
    assert r.status_code == 400
    # Nothing parsed, nothing written.
    _ensure_billing_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "StripeEvent" WHERE "id" = %s', (evt_id,))
            assert cur.fetchone()[0] == 0


def test_webhook_valid_signature_processes_and_grants_entitlement(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    evt_id = "evt_" + new_id()
    payload = _checkout_event(test_user_id, "pro", evt_id)
    r = client.post(
        "/billing/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": _sign(payload)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "processed"
    sub = SubscriptionRepository().get_by_user(test_user_id)
    assert sub["planId"] == "pro"
    assert sub["status"] == "active"
    quota = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(quota["runsAllowed"]) == 100  # Pro ratified quota
    assert int(quota["runsUsed"]) == 0


def test_webhook_duplicate_event_is_idempotent_no_second_entitlement(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    evt_id = "evt_" + new_id()
    payload = _checkout_event(test_user_id, "pro", evt_id)
    headers = {"stripe-signature": _sign(payload)}

    first = client.post("/billing/webhooks/stripe", content=payload, headers=headers)
    assert first.status_code == 200 and first.json()["status"] == "processed"

    # Burn a run so we can detect an illegitimate quota reset on replay.
    UsageQuotaRepository().reserve(test_user_id)
    before = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    assert before == 1

    second = client.post("/billing/webhooks/stripe", content=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "already_processed"

    # Replay did NOT re-apply the entitlement (no quota reset back to 0).
    after = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    assert after == before == 1
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "StripeEvent" WHERE "id" = %s', (evt_id,))
            assert cur.fetchone()[0] == 1  # exactly one record


def test_webhook_handler_exception_rolls_back_stripe_event(
    client, auth_headers, test_user_id, monkeypatch
):
    """A handler that raises must roll the txn back so the StripeEvent row is
    absent — Stripe then retries. Idempotency is committed IFF side effects are."""
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    import app.routers.billing as billing_router

    def _boom(cur, obj):
        raise RuntimeError("handler failure")

    monkeypatch.setattr(billing_router, "_handle_checkout_completed", _boom)
    evt_id = "evt_" + new_id()
    payload = _checkout_event(test_user_id, "pro", evt_id)
    r = client.post(
        "/billing/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": _sign(payload)},
    )
    assert r.status_code >= 500  # Stripe retries
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "StripeEvent" WHERE "id" = %s', (evt_id,))
            assert cur.fetchone()[0] == 0  # rolled back, retry-safe


# ---------------------------------------------------------------------------
# Checkout create-or-reuse Customer (mocked Stripe gateway) (GAP-P6-BILL-001)
# ---------------------------------------------------------------------------


def test_checkout_creates_customer_once_then_reuses(
    client, auth_headers, test_user_id, monkeypatch
):
    import app.services.stripe_gateway as gw

    calls = {"create_customer": 0, "create_session": 0}

    def _fake_create_customer(*, email, user_id):
        calls["create_customer"] += 1
        return "cus_reuse_" + user_id[:8]

    def _fake_create_session(**kwargs):
        calls["create_session"] += 1
        return {"id": "cs_test_123", "url": "https://checkout.stripe.com/c/pay/cs_test_123"}

    monkeypatch.setattr(gw, "is_configured", lambda: True)
    monkeypatch.setattr(gw, "create_customer", _fake_create_customer)
    monkeypatch.setattr(gw, "create_checkout_session", _fake_create_session)

    # A purchasable price id must exist for the plan.
    PlanRepository().set_stripe_ids("pro", price_monthly="price_pro_month_test")

    body = {"planId": "pro", "interval": "month"}
    r1 = client.post("/billing/checkout", json=body, headers=auth_headers)
    assert r1.status_code == 200, r1.text
    assert r1.json()["checkoutUrl"].startswith("https://checkout.stripe.com/")
    assert calls["create_customer"] == 1

    r2 = client.post("/billing/checkout", json=body, headers=auth_headers)
    assert r2.status_code == 200, r2.text
    # Customer reused: NOT created a second time.
    assert calls["create_customer"] == 1
    assert calls["create_session"] == 2


def test_checkout_free_plan_is_rejected(client, auth_headers, monkeypatch):
    import app.services.stripe_gateway as gw

    monkeypatch.setattr(gw, "is_configured", lambda: True)
    r = client.post(
        "/billing/checkout", json={"planId": "free", "interval": "month"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_checkout_without_stripe_key_is_honest_503(
    client, auth_headers, monkeypatch
):
    import app.services.stripe_gateway as gw

    monkeypatch.setattr(gw, "is_configured", lambda: False)
    PlanRepository().set_stripe_ids("pro", price_monthly="price_pro_month_test")
    r = client.post(
        "/billing/checkout", json={"planId": "pro", "interval": "month"},
        headers=auth_headers,
    )
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# Quota reserve-before-run / spend cap / refund (GAP-P6-BILL-002)
# ---------------------------------------------------------------------------


def test_reserve_is_atomic_and_429_on_exhaustion(client, auth_headers, test_user_id):
    repo = UsageQuotaRepository()
    ensure_user_billing(test_user_id)
    # Free tier = 5 runs. Five reserves succeed, the sixth returns None.
    for i in range(5):
        assert repo.reserve(test_user_id) is not None, i
    assert repo.reserve(test_user_id) is None
    q = repo.get_by_user(test_user_id)
    assert int(q["runsUsed"]) == 5 and int(q["runsAllowed"]) == 5


def test_record_run_429_quota_exceeded_has_upgrade_url(
    client, auth_headers, test_user_id
):
    # Exhaust the Free quota, then a metered run must 429 with an upgrade CTA.
    repo = UsageQuotaRepository()
    ensure_user_billing(test_user_id)
    for _ in range(5):
        repo.reserve(test_user_id)
    with pytest.raises(HTTPException) as ei:
        _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    assert ei.value.status_code == 429
    detail = ei.value.detail
    assert detail["code"] == "quota_exceeded"
    assert detail["upgradeUrl"] == "/pricing"
    assert detail["quotaReset"] is not None


def test_spend_cap_reached_refunds_reserved_run_and_429(
    client, auth_headers, test_user_id
):
    ensure_user_billing(test_user_id)
    # Push accumulated spend to the Free USD cap ($1.00).
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "UsageQuota" SET "spendUsedUsd" = "spendCapUsd" '
                'WHERE "userId" = %s',
                (test_user_id,),
            )
        conn.commit()
    with pytest.raises(HTTPException) as ei:
        _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    assert ei.value.status_code == 429
    assert ei.value.detail["code"] == "spend_cap_exceeded"
    # The reserved run was refunded — runsUsed is back to 0.
    q = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(q["runsUsed"]) == 0


def test_failed_run_refunds_reserved_run(client, auth_headers, test_user_id):
    ensure_user_billing(test_user_id)

    def _boom():
        raise ValueError("agent blew up")

    with pytest.raises(Exception):
        _record_run(test_user_id, "tailor", {"job_id": "j"}, _boom)
    q = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(q["runsUsed"]) == 0  # reserved then refunded


def test_successful_run_records_spend_and_consumes_one_run(
    client, auth_headers, test_user_id
):
    ensure_user_billing(test_user_id)
    out = _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    q = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(q["runsUsed"]) == 1
    assert float(q["spendUsedUsd"]) == pytest.approx(float(out["costUsd"]), abs=1e-9)
    assert float(q["spendUsedUsd"]) > 0


def test_deterministic_agent_does_not_consume_quota(
    client, auth_headers, test_user_id
):
    ensure_user_billing(test_user_id)
    _record_run(test_user_id, "scout", {}, lambda: {"persisted": 0, "updated": 0, "errors": []})
    q = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(q["runsUsed"]) == 0  # scout is deterministic — unmetered


# ---------------------------------------------------------------------------
# GATE-34 backfill (GAP-P6-BILL-001)
# ---------------------------------------------------------------------------


def test_backfill_assigns_free_plan_and_quota_to_existing_users(client, auth_headers):
    # Seed a couple of raw users with NO billing rows.
    ids = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            for n in range(3):
                uid = new_id()
                ids.append(uid)
                cur.execute(
                    'INSERT INTO "User" ("id","email","passwordHash","updatedAt") '
                    "VALUES (%s,%s,'x',NOW())",
                    (uid, f"backfill-{uid}@example.com"),
                )
        conn.commit()
    # Re-run the lazy DDL + GATE-34 backfill from a clean 'ready' state.
    _reset_billing_ready_for_tests()
    _ensure_billing_tables()
    for uid in ids:
        sub = SubscriptionRepository().get_by_user(uid)
        assert sub is not None and sub["planId"] == "free" and sub["status"] == "active"
        quota = UsageQuotaRepository().get_by_user(uid)
        assert quota is not None
        assert int(quota["runsAllowed"]) == 5  # Free ratified quota
        assert int(quota["runsUsed"]) == 0
