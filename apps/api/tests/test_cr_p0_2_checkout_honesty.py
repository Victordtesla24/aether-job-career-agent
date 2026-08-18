"""CR-P0-2 (RUN-20260818T0223Z) — the live Stripe Checkout page must show the
SAME honest, quota-only per-plan facts /pricing and GET /billing/plans show —
never the scrubbed "Full model access" / "Standard model tier" / "Everything
in Pro" feature-ladder overclaims.

Audit evidence: docs/delivery/evidence/RUN-20260818T0223Z/COMMERCIAL-READINESS/
billing-entitlement/audit.md (P0 — "The actual Stripe Checkout page (point of
sale) still shows the exact 'unenforced feature ladder' claims engineering
ruled dishonest and scrubbed everywhere else"). The auditor found the
Stripe-rendered description under the product name on Checkout is the
PRODUCT's own ``description`` field. When ``create_checkout_session`` built
its line item as ``line_items=[{"price": price_id}]`` (a bare reference to a
pre-existing catalog Price), Stripe rendered whatever that Price's Product
``description`` says in the Stripe DASHBOARD — a field this codebase never
wrote and two earlier scrubbing passes (MV-pricing-002/CLI-D3 on /pricing,
AUD-MON-1 on GET /billing/plans) never touched.

Fix (CR-P0-2): ``create_checkout_session`` now builds the line item from
``price_data`` — an inline Price + Product created for THIS session — whose
``product_data.name``/``product_data.description`` are supplied by the
caller (the router), sourced from the SAME ``_enforced_facts`` helper
``/pricing`` and ``GET /billing/plans`` already use (ruling D4: a plan
enforces EXACTLY the monthly run quota and the monthly AI spend cap).
Checkout can therefore never re-drift from what the backend enforces — there
is nothing left in the Stripe Dashboard for a future edit to silently
disagree with.
"""
from __future__ import annotations

import re

from app.repositories.billing import PlanRepository
from app.routers.billing import _enforced_facts

#: Same vocabulary as tests/test_aud_mon_1_plans_payload.py::_UNENFORCED_CLAIM_RE
#: — the exact banned phrases the live Stripe Checkout page still showed
#: ("Standard model tier", "Full model access", "Cover letters + story bank",
#: "Everything in Pro", "Email agent (triage + drafts)", per the audit).
_UNENFORCED_CLAIM_RE = re.compile(
    r"model tier|model access|story bank|email agent|everything in "
    r"(starter|pro)|community support|ats scoring|priority|feature access",
    re.I,
)


class _FakeStripeObject:
    """Minimal stand-in for a Stripe SDK object: dict-like AND attribute-like
    access (mirrors tests/test_admin2_billing.py::_FakeStripeObject)."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


class _FakeSessionResource:
    def __init__(self, calls: list[dict]):
        self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        return _FakeStripeObject(
            id="cs_test_fake", url="https://checkout.stripe.com/c/pay/cs_test_fake"
        )


class _FakeCheckoutNamespace:
    def __init__(self, calls: list[dict]):
        self.Session = _FakeSessionResource(calls)


def _fake_stripe_sdk(calls: list[dict]) -> _FakeStripeObject:
    return _FakeStripeObject(checkout=_FakeCheckoutNamespace(calls))


# ---------------------------------------------------------------------------
# Gateway level — the ACTUAL request shape sent to Stripe (root-cause proof).
# One level BELOW the router, exactly like the promotion-code shape tests in
# test_admin2_billing.py — this fails if the fix regresses back to a bare
# catalog ``price=`` reference, without ever reaching the live Stripe SDK.
# ---------------------------------------------------------------------------


def test_create_checkout_session_uses_inline_price_data_not_a_catalog_price(
    monkeypatch,
):
    """CR-P0-2 root cause: a bare ``price=price_id`` line item renders whatever
    Product description is configured in the Stripe DASHBOARD (uncontrolled by
    this codebase). The fix must send ``price_data`` with an inline
    ``product_data`` instead, so the rendered description is the honest text
    this call passes in."""
    import app.services.stripe_gateway as gw

    calls: list[dict] = []
    monkeypatch.setattr(gw, "_stripe", lambda: _fake_stripe_sdk(calls))

    result = gw.create_checkout_session(
        customer_id="cus_test_1",
        price_id="price_starter_month_catalog",
        user_id="user_1",
        plan_id="starter",
        plan_name="Starter",
        description="30 tailored agent runs / month · US$5.00 monthly AI spend cap",
        amount_aud=19.0,
        interval="month",
    )

    assert result == {
        "id": "cs_test_fake",
        "url": "https://checkout.stripe.com/c/pay/cs_test_fake",
    }
    sent = calls[0]
    line_item = sent["line_items"][0]
    assert "price" not in line_item, (
        "checkout still references a bare catalog price id — Stripe will "
        "render whatever Product description is configured in the DASHBOARD, "
        "not anything this codebase controls (the CR-P0-2 defect)."
    )
    price_data = line_item["price_data"]
    assert price_data["currency"] == "aud"
    assert price_data["unit_amount"] == 1900
    assert price_data["recurring"] == {"interval": "month"}
    product_data = price_data["product_data"]
    assert product_data["name"] == "Starter"
    assert product_data["description"] == (
        "30 tailored agent runs / month · US$5.00 monthly AI spend cap"
    )
    assert not _UNENFORCED_CLAIM_RE.search(product_data["description"])
    # The catalog price id is preserved for financial reconciliation, but is
    # no longer what Stripe renders to the customer.
    assert sent["metadata"]["catalog_price_id"] == "price_starter_month_catalog"
    # Existing behaviour (idempotency/subscription metadata/urls) unchanged.
    assert sent["mode"] == "subscription"
    assert sent["customer"] == "cus_test_1"
    assert sent["client_reference_id"] == "user_1"
    assert sent["subscription_data"]["metadata"] == {
        "user_id": "user_1",
        "plan_id": "starter",
        "interval": "month",
    }


def test_create_checkout_session_annual_amount_matches_recurring_interval(
    monkeypatch,
):
    import app.services.stripe_gateway as gw

    calls: list[dict] = []
    monkeypatch.setattr(gw, "_stripe", lambda: _fake_stripe_sdk(calls))

    gw.create_checkout_session(
        customer_id="cus_test_2",
        price_id="price_power_year_catalog",
        user_id="user_2",
        plan_id="power",
        plan_name="Power",
        description="300 tailored agent runs / month · US$40.00 monthly AI spend cap",
        amount_aud=649.0,
        interval="year",
    )
    price_data = calls[0]["line_items"][0]["price_data"]
    assert price_data["unit_amount"] == 64900
    assert price_data["recurring"] == {"interval": "year"}


# ---------------------------------------------------------------------------
# Router level — /billing/checkout wires the SAME honest facts /pricing uses.
# ---------------------------------------------------------------------------


def test_checkout_endpoint_passes_the_same_enforced_facts_pricing_uses(
    client, auth_headers, monkeypatch
):
    import app.services.stripe_gateway as gw

    captured: dict = {}

    def _fake_create_session(**kwargs):
        captured.update(kwargs)
        return {"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"}

    monkeypatch.setattr(gw, "is_configured", lambda: True)
    monkeypatch.setattr(
        gw, "create_customer", lambda *, email, user_id: "cus_" + user_id[:8]
    )
    monkeypatch.setattr(gw, "create_checkout_session", _fake_create_session)

    PlanRepository().set_stripe_ids(
        "starter", price_monthly="price_starter_month_test"
    )
    plan = PlanRepository().get("starter")

    r = client.post(
        "/billing/checkout",
        json={"planId": "starter", "interval": "month"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    expected_description = " · ".join(_enforced_facts(plan))
    assert captured["description"] == expected_description
    assert captured["plan_name"] == plan["name"]
    assert captured["amount_aud"] == float(plan["priceAudMonthly"])
    assert not _UNENFORCED_CLAIM_RE.search(captured["description"])


def test_checkout_endpoint_never_asserts_a_banned_claim_for_any_purchasable_plan(
    client, auth_headers, monkeypatch
):
    """Every purchasable plan (both intervals covered across plans) the
    checkout endpoint can build a session for must be scrubbed — not just
    Starter/month. Kept to 4 calls/user (below the 5/hr checkout rate limit,
    billing §3) so this test does not trip its own 429."""
    import app.services.stripe_gateway as gw

    captured: list[dict] = []

    def _fake_create_session(**kwargs):
        captured.append(dict(kwargs))
        return {"id": "cs_x", "url": "https://checkout.stripe.com/c/pay/cs_x"}

    monkeypatch.setattr(gw, "is_configured", lambda: True)
    monkeypatch.setattr(
        gw, "create_customer", lambda *, email, user_id: "cus_" + user_id[:8]
    )
    monkeypatch.setattr(gw, "create_checkout_session", _fake_create_session)

    repo = PlanRepository()
    for plan_id in ("starter", "pro", "power"):
        repo.set_stripe_ids(
            plan_id,
            price_monthly=f"price_{plan_id}_month_test",
            price_annual=f"price_{plan_id}_year_test",
        )

    combos = [
        ("starter", "month"),
        ("pro", "month"),
        ("power", "month"),
        ("power", "year"),
    ]
    for plan_id, interval in combos:
        r = client.post(
            "/billing/checkout",
            json={"planId": plan_id, "interval": interval},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

    assert len(captured) == len(combos)
    for kwargs in captured:
        assert not _UNENFORCED_CLAIM_RE.search(kwargs["description"]), kwargs
        assert not _UNENFORCED_CLAIM_RE.search(kwargs["plan_name"]), kwargs
