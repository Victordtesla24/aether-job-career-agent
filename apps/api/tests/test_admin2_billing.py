"""ADMIN-2.0 BE-1 — custom pricing, the local-vs-Stripe billing surface, the
local-only reconcile, the executive billing summary, and Stripe promo objects.

MONEY SAFETY (absolute, enforced by this file):
  * a module-scoped autouse fixture replaces ``stripe_gateway._stripe`` with a
    detonator, so NO test here can reach the live Stripe SDK even by accident —
    every Stripe interaction is an explicitly monkeypatched stub;
  * the custom-pricing path is asserted to modify the EXISTING subscription in
    place with ``proration_behavior="none"`` (no immediate invoice, no second
    subscription) — the no-double-billing invariant, not a new charge;
  * the reconcile path is asserted to perform ZERO Stripe mutations.

All prices are AUD. The operator is NOT GST-registered, so no GST line is added
to a custom price (the response never claims one).
"""
from __future__ import annotations

import uuid

import pytest

from app.db import get_connection, new_id
from app.repositories.admin import _ensure_admin_schema
from app.repositories.billing import SubscriptionRepository, ensure_user_billing

# --------------------------------------------------------------------------- #
# Money safety: the live Stripe SDK is unreachable from this module.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _no_live_stripe(monkeypatch):
    import app.services.stripe_gateway as gw

    def _detonate(*_a, **_k):
        raise AssertionError(
            "MONEY SAFETY: a test attempted to reach the live Stripe SDK"
        )

    monkeypatch.setattr(gw, "_stripe", _detonate)
    return gw


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _register(client, email: str, password: str = "Passw0rd1") -> tuple[str, str]:
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (201, 409), r.text
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["access_token"], login.json()["userId"]


def _promote(user_id: str) -> None:
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (user_id,))
        conn.commit()


def _admin(client) -> tuple[dict[str, str], str]:
    token, uid = _register(client, f"admin-{uuid.uuid4().hex[:8]}@example.com")
    _promote(uid)
    return {"Authorization": f"Bearer {token}"}, uid


def _target(client) -> tuple[dict[str, str], str, str]:
    email = f"target-{uuid.uuid4().hex[:8]}@example.com"
    token, uid = _register(client, email)
    ensure_user_billing(uid)
    return {"Authorization": f"Bearer {token}"}, uid, email


def _seed_paid_sub(
    user_id: str,
    *,
    plan_id: str = "pro",
    with_stripe_subscription: bool = True,
    interval: str = "month",
    status: str = "active",
) -> tuple[str, str | None]:
    ensure_user_billing(user_id)
    customer_id = "cus_" + new_id()
    subscription_id = ("sub_" + new_id()) if with_stripe_subscription else None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=%s,'
                '"billingInterval"=%s,"stripeCustomerId"=%s,'
                '"stripeSubscriptionId"=%s,"updatedAt"=now() WHERE "userId"=%s',
                (plan_id, status, interval, customer_id, subscription_id, user_id),
            )
        conn.commit()
    return customer_id, subscription_id


def _audit_rows(target_id: str) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "action","detailJson","actorUserId" FROM "AdminAuditLog"'
                ' WHERE "targetId"=%s ORDER BY "createdAt" DESC',
                (target_id,),
            )
            return [
                {"action": r[0], "detail": r[1], "actor": r[2]} for r in cur.fetchall()
            ]


def _stub_configured(monkeypatch, gw, configured: bool = True) -> None:
    monkeypatch.setattr(gw, "is_configured", lambda: configured)


# --------------------------------------------------------------------------- #
# Gating
# --------------------------------------------------------------------------- #

_ADMIN2_BILLING_ROUTES = [
    ("POST", "/admin/users/some-id/subscription/price", {"amountAud": 10, "interval": "month"}),
    ("GET", "/admin/users/some-id/billing", None),
    ("POST", "/admin/users/some-id/billing/reconcile-local", {}),
    ("GET", "/admin/billing/summary", None),
    ("GET", "/admin/promos", None),
    ("POST", "/admin/promos", {"percentOff": 10, "duration": "once"}),
    ("DELETE", "/admin/promos/promo_x", None),
]


@pytest.mark.parametrize("method,path,body", _ADMIN2_BILLING_ROUTES)
def test_admin2_billing_routes_require_authentication(client, method, path, body):
    r = client.request(method, path, json=body)
    assert r.status_code == 401, f"{method} {path}: {r.status_code}"


@pytest.mark.parametrize("method,path,body", _ADMIN2_BILLING_ROUTES)
def test_admin2_billing_routes_reject_non_admins(client, auth_headers, method, path, body):
    r = client.request(method, path, json=body, headers=auth_headers)
    assert r.status_code == 403, f"{method} {path}: {r.status_code} {r.text}"


# --------------------------------------------------------------------------- #
# (c) CUSTOM PRICING
# --------------------------------------------------------------------------- #


def test_custom_price_switches_the_existing_subscription_without_prorating(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    admin_headers, admin_id = _admin(client)
    _, target_id, _ = _target(client)
    _cust, sub_id = _seed_paid_sub(target_id, plan_id="pro")

    created: dict = {}
    applied: dict = {}
    forbidden: list[str] = []

    _stub_configured(monkeypatch, gw)

    def _create_price(**kwargs):
        created.update(kwargs)
        return {"id": "price_custom_1", "unitAmountAud": kwargs["amount_aud"]}

    def _set_price(**kwargs):
        applied.update(kwargs)
        return {
            "id": kwargs["subscription_id"],
            "prorationBehavior": "none",
            "priceId": kwargs["new_price_id"],
        }

    monkeypatch.setattr(gw, "create_price", _create_price, raising=False)
    monkeypatch.setattr(gw, "set_subscription_price", _set_price, raising=False)
    # A second subscription (double billing) must never be opened.
    monkeypatch.setattr(
        gw,
        "create_checkout_session",
        lambda **k: forbidden.append("checkout"),
        raising=False,
    )

    r = client.post(
        f"/admin/users/{target_id}/subscription/price",
        json={"amountAud": 24.5, "interval": "month"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amountAud"] == 24.5
    assert body["interval"] == "month"
    assert body["currency"] == "AUD"
    assert body["stripePriceId"] == "price_custom_1"
    assert body["stripeSubscriptionId"] == sub_id
    assert body["prorationBehavior"] == "none"

    assert created["amount_aud"] == 24.5
    assert created["interval"] == "month"
    assert applied["subscription_id"] == sub_id
    assert applied["new_price_id"] == "price_custom_1"
    assert forbidden == []

    # Local mirror persisted so the billing surface can show the custom amount.
    surface = client.get(f"/admin/users/{target_id}/billing", headers=admin_headers)
    assert surface.status_code == 200, surface.text
    custom = surface.json()["local"]["customPrice"]
    assert custom["amountAud"] == 24.5
    assert custom["interval"] == "month"
    assert custom["stripePriceId"] == "price_custom_1"

    rows = _audit_rows(target_id)
    assert "set_custom_price" in [a["action"] for a in rows]
    detail = rows[0]["detail"] or {}
    assert detail["after"]["amountAud"] == 24.5
    assert rows[0]["actor"] == admin_id


def test_custom_price_without_a_live_stripe_subscription_is_an_honest_409(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    _stub_configured(monkeypatch, gw)
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    # Local row says "pro/active" but there is no Stripe subscription behind it.
    _seed_paid_sub(target_id, plan_id="pro", with_stripe_subscription=False)

    r = client.post(
        f"/admin/users/{target_id}/subscription/price",
        json={"amountAud": 15, "interval": "month"},
        headers=admin_headers,
    )
    assert r.status_code == 409, r.text
    assert "entitlement" in r.json()["detail"].lower()


def test_custom_price_is_503_when_stripe_is_not_configured(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    _stub_configured(monkeypatch, gw, configured=False)
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    _seed_paid_sub(target_id)
    r = client.post(
        f"/admin/users/{target_id}/subscription/price",
        json={"amountAud": 15, "interval": "month"},
        headers=admin_headers,
    )
    assert r.status_code == 503, r.text


@pytest.mark.parametrize(
    "body",
    [
        {"amountAud": 0, "interval": "month"},
        {"amountAud": -5, "interval": "month"},
        {"amountAud": "ten", "interval": "month"},
        {"amountAud": True, "interval": "month"},
        {"amountAud": 10},
        {"amountAud": 10, "interval": "week"},
        {"amountAud": 10_000_000, "interval": "month"},
        {"interval": "month"},
    ],
)
def test_custom_price_validates_amount_and_interval(
    client, monkeypatch, _no_live_stripe, body
):
    gw = _no_live_stripe
    _stub_configured(monkeypatch, gw)
    called: list[str] = []
    monkeypatch.setattr(
        gw, "create_price", lambda **k: called.append("create"), raising=False
    )
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    _seed_paid_sub(target_id)
    r = client.post(
        f"/admin/users/{target_id}/subscription/price", json=body, headers=admin_headers
    )
    assert r.status_code == 422, f"{body}: {r.status_code} {r.text}"
    assert called == []


# --------------------------------------------------------------------------- #
# (d) BILLING SURFACE — local vs Stripe, side by side
# --------------------------------------------------------------------------- #


def _stub_stripe_reads(
    monkeypatch,
    gw,
    *,
    customer=None,
    subscription=None,
    subscriptions=None,
    invoices=None,
    payment_method=None,
):
    _stub_configured(monkeypatch, gw)
    monkeypatch.setattr(gw, "retrieve_customer", lambda cid: customer, raising=False)
    monkeypatch.setattr(
        gw, "retrieve_subscription", lambda sid: subscription, raising=False
    )
    monkeypatch.setattr(
        gw, "list_subscriptions", lambda cid, limit=10: subscriptions or [], raising=False
    )
    monkeypatch.setattr(
        gw, "list_invoices", lambda cid, limit=5: invoices or [], raising=False
    )
    monkeypatch.setattr(
        gw, "payment_method_summary", lambda cid: payment_method, raising=False
    )


def test_billing_surface_shows_local_and_stripe_side_by_side(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    admin_headers, _ = _admin(client)
    _, target_id, target_email = _target(client)
    cust, sub_id = _seed_paid_sub(target_id, plan_id="pro")
    _stub_stripe_reads(
        monkeypatch,
        gw,
        customer={"id": cust, "email": target_email, "delinquent": False},
        subscription={
            "id": sub_id,
            "status": "active",
            "cancelAtPeriodEnd": False,
            "currentPeriodEnd": "2026-09-14T00:00:00+00:00",
            "amountAud": 39.0,
            "interval": "month",
        },
        subscriptions=[{"id": sub_id, "status": "active"}],
        invoices=[
            {
                "id": "in_1",
                "status": "paid",
                "amountPaidAud": 39.0,
                "created": "2026-08-14T00:00:00+00:00",
                "hostedInvoiceUrl": None,
            }
        ],
        payment_method={"brand": "visa", "last4": "4242", "expMonth": 12, "expYear": 2030},
    )

    r = client.get(f"/admin/users/{target_id}/billing", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["local"]["planId"] == "pro"
    assert body["local"]["stripeSubscriptionId"] == sub_id
    assert body["stripe"]["available"] is True
    assert body["stripe"]["subscription"]["status"] == "active"
    assert body["stripe"]["invoices"][0]["id"] == "in_1"
    # Payment method is a MASKED summary — last4 only, never a full number.
    pm = body["stripe"]["paymentMethod"]
    assert pm["last4"] == "4242" and pm["brand"] == "visa"
    assert "number" not in pm
    assert body["mismatch"]["evaluated"] is True
    assert body["mismatch"]["hasMismatch"] is False


def test_billing_surface_flags_a_stale_local_row_against_stripe(
    client, monkeypatch, _no_live_stripe
):
    """The OWNER's real state: local says pro/active, Stripe has nothing."""
    gw = _no_live_stripe
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    _seed_paid_sub(target_id, plan_id="pro", with_stripe_subscription=False)
    _stub_stripe_reads(monkeypatch, gw, customer=None, subscription=None, subscriptions=[])

    r = client.get(f"/admin/users/{target_id}/billing", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["local"]["planId"] == "pro"
    assert body["stripe"]["subscription"] is None
    assert body["mismatch"]["evaluated"] is True
    assert body["mismatch"]["hasMismatch"] is True
    assert any("stripe" in reason.lower() for reason in body["mismatch"]["reasons"])


def test_billing_surface_is_honest_when_stripe_is_not_configured(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    _stub_configured(monkeypatch, gw, configured=False)
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    _seed_paid_sub(target_id)

    r = client.get(f"/admin/users/{target_id}/billing", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stripe"]["available"] is False
    assert body["stripe"]["reason"]
    # Never claims a comparison it could not make.
    assert body["mismatch"]["evaluated"] is False
    assert body["mismatch"]["hasMismatch"] is False


# --------------------------------------------------------------------------- #
# reconcile-local — clears a stale LOCAL row, never touches Stripe
# --------------------------------------------------------------------------- #


def test_reconcile_local_clears_a_stale_row_with_zero_stripe_mutations(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    admin_headers, admin_id = _admin(client)
    _, target_id, _ = _target(client)
    _seed_paid_sub(target_id, plan_id="pro", with_stripe_subscription=False)
    _stub_stripe_reads(monkeypatch, gw, customer=None, subscriptions=[])

    mutations: list[str] = []
    for name in (
        "cancel_subscription",
        "set_cancel_at_period_end",
        "create_refund",
        "set_subscription_price",
        "switch_subscription_price",
    ):
        monkeypatch.setattr(
            gw, name, lambda *a, **k: mutations.append(name), raising=False
        )

    r = client.post(
        f"/admin/users/{target_id}/billing/reconcile-local", json={}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reconciled"] is True
    assert body["stripeMutated"] is False
    assert body["before"]["planId"] == "pro"
    assert body["after"]["planId"] == "free"
    assert mutations == []

    sub = SubscriptionRepository().get_by_user(target_id)
    assert sub["planId"] == "free"
    assert sub["status"] == "canceled"
    assert sub["stripeSubscriptionId"] is None

    rows = _audit_rows(target_id)
    assert "reconcile_local_subscription" in [a["action"] for a in rows]
    assert rows[0]["actor"] == admin_id


def test_reconcile_local_refuses_when_stripe_shows_a_live_subscription(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    _cust, sub_id = _seed_paid_sub(target_id, plan_id="pro")
    _stub_stripe_reads(
        monkeypatch,
        gw,
        customer={"id": _cust},
        subscription={"id": sub_id, "status": "active"},
        subscriptions=[{"id": sub_id, "status": "active"}],
    )
    r = client.post(
        f"/admin/users/{target_id}/billing/reconcile-local", json={}, headers=admin_headers
    )
    assert r.status_code == 409, r.text
    assert SubscriptionRepository().get_by_user(target_id)["planId"] == "pro"


def test_reconcile_local_on_a_clean_row_is_an_honest_409(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    _stub_stripe_reads(monkeypatch, gw)
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)  # free/active, nothing stale
    r = client.post(
        f"/admin/users/{target_id}/billing/reconcile-local", json={}, headers=admin_headers
    )
    assert r.status_code == 409, r.text


# --------------------------------------------------------------------------- #
# GET /admin/billing/summary — executive totals, honestly derived
# --------------------------------------------------------------------------- #


def test_billing_summary_counts_only_stripe_backed_non_admin_subscribers(
    client, monkeypatch, _no_live_stripe
):
    admin_headers, admin_id = _admin(client)

    # Two REAL paying subscribers (Stripe-backed local rows).
    _, paid_monthly, _ = _target(client)
    _seed_paid_sub(paid_monthly, plan_id="pro", interval="month")
    _, paid_annual, _ = _target(client)
    _seed_paid_sub(paid_annual, plan_id="starter", interval="year")

    # A paid-LOOKING local row with no Stripe subscription behind it.
    _, unbacked, _ = _target(client)
    _seed_paid_sub(unbacked, plan_id="power", with_stripe_subscription=False)

    # The admin's own stale pro row must never be counted as revenue.
    _seed_paid_sub(admin_id, plan_id="pro", with_stripe_subscription=False)

    r = client.get("/admin/billing/summary", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "AUD"
    assert body["paidSubscribers"] == 2
    # pro monthly A$39 + starter annual A$179/12 = 39 + 14.92 = 53.92
    assert body["mrrAud"] == pytest.approx(53.92, abs=0.02)
    assert body["unbackedPaidRows"] >= 1
    assert body["excludedAdminRows"] >= 1
    assert body["estimate"] is True
    assert body["source"]
    by_plan = {p["planId"]: p for p in body["byPlan"]}
    assert by_plan["pro"]["count"] == 1
    assert by_plan["starter"]["count"] == 1
    assert "power" not in by_plan  # unbacked row is not revenue


def test_billing_summary_uses_a_custom_price_when_one_is_set(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    _seed_paid_sub(target_id, plan_id="pro", interval="month")

    _stub_configured(monkeypatch, gw)
    monkeypatch.setattr(
        gw, "create_price", lambda **k: {"id": "price_custom_2"}, raising=False
    )
    monkeypatch.setattr(
        gw,
        "set_subscription_price",
        lambda **k: {"id": k["subscription_id"], "prorationBehavior": "none"},
        raising=False,
    )
    assert (
        client.post(
            f"/admin/users/{target_id}/subscription/price",
            json={"amountAud": 12.0, "interval": "month"},
            headers=admin_headers,
        ).status_code
        == 200
    )

    body = client.get("/admin/billing/summary", headers=admin_headers).json()
    assert body["mrrAud"] == pytest.approx(12.0, abs=0.01)
    assert body["customPricedCount"] == 1


def test_billing_summary_is_honest_with_no_subscribers(client):
    admin_headers, _ = _admin(client)
    body = client.get("/admin/billing/summary", headers=admin_headers).json()
    assert body["paidSubscribers"] == 0
    assert body["mrrAud"] == 0.0
    assert body["byPlan"] == []


# --------------------------------------------------------------------------- #
# (e) PROMOS — Stripe Coupon + PromotionCode (safe objects, no charges)
# --------------------------------------------------------------------------- #


def _stub_promos(monkeypatch, gw, *, created=None, listed=None, deactivated=None):
    _stub_configured(monkeypatch, gw)
    calls: dict = {"coupon": [], "code": [], "deactivate": []}

    def _create_coupon(**kwargs):
        calls["coupon"].append(kwargs)
        return {"id": "coupon_1", **{k: v for k, v in kwargs.items() if k != "name"}}

    def _create_code(**kwargs):
        calls["code"].append(kwargs)
        return {
            "id": "promo_1",
            "code": kwargs.get("code") or "AETHER10",
            "couponId": kwargs["coupon_id"],
            "active": True,
            "maxRedemptions": kwargs.get("max_redemptions"),
            "expiresAt": None,
            "timesRedeemed": 0,
        }

    def _deactivate(promotion_code_id):
        calls["deactivate"].append(promotion_code_id)
        return {"id": promotion_code_id, "active": False}

    monkeypatch.setattr(gw, "create_coupon", _create_coupon, raising=False)
    monkeypatch.setattr(gw, "create_promotion_code", _create_code, raising=False)
    monkeypatch.setattr(
        gw, "list_promotion_codes", lambda limit=50: listed or [], raising=False
    )
    monkeypatch.setattr(gw, "deactivate_promotion_code", _deactivate, raising=False)
    return calls


def test_create_promo_makes_a_coupon_and_a_promotion_code_and_audits_it(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    calls = _stub_promos(monkeypatch, gw)
    admin_headers, admin_id = _admin(client)

    r = client.post(
        "/admin/promos",
        json={
            "name": "Launch 20",
            "percentOff": 20,
            "duration": "repeating",
            "durationInMonths": 3,
            "code": "LAUNCH20",
            "maxRedemptions": 50,
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["couponId"] == "coupon_1"
    assert body["promotionCodeId"] == "promo_1"
    assert body["code"] == "LAUNCH20"
    assert body["percentOff"] == 20
    assert body["active"] is True

    assert calls["coupon"][0]["percent_off"] == 20
    assert calls["coupon"][0]["duration"] == "repeating"
    assert calls["coupon"][0]["duration_in_months"] == 3
    assert calls["code"][0]["coupon_id"] == "coupon_1"

    # AdminAuditLog is append-only and deliberately NOT truncated between tests
    # (conftest: "tests filter by actor id"), so scope the assertion to THIS
    # test's freshly-created admin.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "action","targetId" FROM "AdminAuditLog"'
                " WHERE \"targetType\"='promo' AND \"actorUserId\"=%s",
                (admin_id,),
            )
            rows = cur.fetchall()
    assert rows == [("create_promo", "promo_1")]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"duration": "once"},
        {"percentOff": 20, "amountOffAud": 5, "duration": "once"},
        {"percentOff": 0, "duration": "once"},
        {"percentOff": 101, "duration": "once"},
        {"percentOff": 20, "duration": "forever-and-ever"},
        {"percentOff": 20, "duration": "repeating"},
        {"amountOffAud": -1, "duration": "once"},
    ],
)
def test_create_promo_validates_its_body(client, monkeypatch, _no_live_stripe, body):
    gw = _no_live_stripe
    calls = _stub_promos(monkeypatch, gw)
    admin_headers, _ = _admin(client)
    r = client.post("/admin/promos", json=body, headers=admin_headers)
    assert r.status_code == 422, f"{body}: {r.status_code} {r.text}"
    assert calls["coupon"] == []


def test_list_promos_returns_stripe_truth(client, monkeypatch, _no_live_stripe):
    gw = _no_live_stripe
    _stub_promos(
        monkeypatch,
        gw,
        listed=[
            {
                "id": "promo_1",
                "code": "LAUNCH20",
                "active": True,
                "couponId": "coupon_1",
                "percentOff": 20,
                "amountOffAud": None,
                "duration": "once",
                "timesRedeemed": 3,
                "maxRedemptions": 50,
                "expiresAt": None,
            }
        ],
    )
    admin_headers, _ = _admin(client)
    r = client.get("/admin/promos", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["promos"][0]["code"] == "LAUNCH20"
    assert body["promos"][0]["timesRedeemed"] == 3


def test_deactivate_promo_deactivates_and_audits(client, monkeypatch, _no_live_stripe):
    gw = _no_live_stripe
    calls = _stub_promos(monkeypatch, gw)
    admin_headers, admin_id = _admin(client)
    r = client.request("DELETE", "/admin/promos/promo_1", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"promotionCodeId": "promo_1", "active": False}
    assert calls["deactivate"] == ["promo_1"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "action","targetId" FROM "AdminAuditLog"'
                ' WHERE "targetType"=\'promo\' AND "actorUserId"=%s',
                (admin_id,),
            )
            assert cur.fetchall() == [("deactivate_promo", "promo_1")]


def test_promo_routes_are_503_when_stripe_is_not_configured(
    client, monkeypatch, _no_live_stripe
):
    gw = _no_live_stripe
    _stub_configured(monkeypatch, gw, configured=False)
    admin_headers, _ = _admin(client)
    assert client.get("/admin/promos", headers=admin_headers).status_code == 503
    assert (
        client.post(
            "/admin/promos",
            json={"percentOff": 10, "duration": "once"},
            headers=admin_headers,
        ).status_code
        == 503
    )
    assert (
        client.request(
            "DELETE", "/admin/promos/promo_1", headers=admin_headers
        ).status_code
        == 503
    )


# --------------------------------------------------------------------------- #
# (e-1) PROMOS — stripe_gateway's OWN Stripe-call shape (regression: ADMIN-2.0
# LIVE VERIFY caught that this file's higher-level tests above mock
# ``gw.create_promotion_code``/``gw.list_promotion_codes`` themselves, so they
# never exercised the actual ``stripe.PromotionCode.create``/``.list`` request
# shape. Live Stripe (SDK v13 / current API version) rejects a top-level
# ``coupon=`` kwarg outright ("Received unknown parameter: coupon") and nests
# it under ``promotion={"type": "coupon", "coupon": <id>}`` instead; the read
# side moved the same way (``PromotionCode.coupon`` -> ``.promotion.coupon``).
# These tests patch ``gw._stripe`` with a minimal fake SDK — one level BELOW
# the wrapper functions — so they fail if the shape regresses again, without
# ever reaching the live Stripe SDK (money-safe, same as every other test in
# this file).
# --------------------------------------------------------------------------- #


class _FakeStripeObject:
    """Minimal stand-in for a Stripe SDK object: dict-like AND attribute-like
    access, matching how ``stripe_gateway._field`` reads real SDK objects."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def get(self, key, default=None):  # pragma: no cover — dict-path parity
        return self.__dict__.get(key, default)


class _FakePromotionCodeResource:
    def __init__(self, calls):
        self._calls = calls

    def create(self, **kwargs):
        self._calls["create"].append(kwargs)
        promo = kwargs.get("promotion") or {}
        return _FakePromotionCodeResource._object(promo.get("coupon"), kwargs)

    def list(self, **kwargs):
        self._calls["list"].append(kwargs)
        return _FakeStripeObject(
            data=[_FakePromotionCodeResource._object("coupon_live_1", {"code": "LIVE1"})]
        )

    @staticmethod
    def _object(coupon_id, kwargs):
        coupon_obj = (
            _FakeStripeObject(id=coupon_id, percent_off=15.0, amount_off=None, duration="once")
            if coupon_id
            else None
        )
        return _FakeStripeObject(
            id="promo_live_1",
            code=kwargs.get("code") or "AUTO1",
            active=True,
            promotion=_FakeStripeObject(type="coupon", coupon=coupon_obj),
            times_redeemed=0,
            max_redemptions=kwargs.get("max_redemptions"),
            expires_at=None,
        )


def test_create_promotion_code_sends_the_nested_promotion_shape_to_stripe(
    monkeypatch,
):
    """The exact defect live verification caught: a flat ``coupon=`` kwarg is
    REJECTED by the real Stripe API. Assert the nested shape is what actually
    goes out, and that the coupon fields expanded in the response round-trip
    back out correctly (``couponId``/``percentOff``/``duration`` — not None)."""
    import app.services.stripe_gateway as gw

    calls = {"create": [], "list": []}
    fake = _FakeStripeObject(PromotionCode=_FakePromotionCodeResource(calls))
    monkeypatch.setattr(gw, "_stripe", lambda: fake)

    result = gw.create_promotion_code(coupon_id="coupon_live_1", code="LAUNCH20")

    sent = calls["create"][0]
    assert "coupon" not in sent, "must NOT send the old flat coupon= kwarg"
    assert sent["promotion"] == {"type": "coupon", "coupon": "coupon_live_1"}
    assert sent["expand"] == ["promotion.coupon"], (
        "must expand promotion.coupon or couponId/percentOff/duration silently "
        "come back None (an ExpandableField collapses to a bare id string)"
    )
    assert result["couponId"] == "coupon_live_1"
    assert result["percentOff"] == 15.0
    assert result["duration"] == "once"


def test_list_promotion_codes_expands_and_reads_the_nested_coupon(monkeypatch):
    import app.services.stripe_gateway as gw

    calls = {"create": [], "list": []}
    fake = _FakeStripeObject(PromotionCode=_FakePromotionCodeResource(calls))
    monkeypatch.setattr(gw, "_stripe", lambda: fake)

    result = gw.list_promotion_codes(limit=5)

    sent = calls["list"][0]
    assert sent["expand"] == ["data.promotion.coupon"]
    assert len(result) == 1
    assert result[0]["couponId"] == "coupon_live_1"
    assert result[0]["percentOff"] == 15.0
