"""Thin Stripe SDK wrapper (ADR-P6-STRIPE-MOCK).

ALL Stripe SDK access funnels through here so:
  * the router never imports ``stripe`` directly and unit tests inject mocks by
    monkeypatching these module functions;
  * secrets are read from ``os.environ`` ONLY and never logged/echoed;
  * a missing ``STRIPE_SECRET_KEY`` / ``STRIPE_WEBHOOK_SECRET`` yields an honest
    error the router maps to 503 — it NEVER fabricates a session/customer/event.

``stripe`` is imported lazily inside each function so a deploy without the SDK
installed degrades to an honest 503 instead of crashing the whole API at import
time (do-not-crash requirement).
"""
from __future__ import annotations

import os
import re
from typing import Any


class StripeNotConfiguredError(RuntimeError):
    """Raised when a required Stripe secret (or the SDK) is unavailable."""


def _secret_key() -> str | None:
    return os.environ.get("STRIPE_SECRET_KEY")


def is_configured() -> bool:
    """True only when a server-side Stripe secret key is present."""
    return bool(_secret_key())


def webhook_secret() -> str | None:
    return os.environ.get("STRIPE_WEBHOOK_SECRET")


#: Production origin. The Abacus VM was decommissioned 2026-08-17; a missing
#: or retired ``APP_BASE_URL`` must never put that host into checkout, mail,
#: or sales copy.
LIVE_APP_BASE_URL = "https://aether.srv1356245.hstgr.cloud"
_RETIRED_APP_HOST_MARKERS = ("5cb5f0620.abacusai.cloud", "abacusai.cloud")
_RETIRED_PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:5cb5f0620\.)?abacusai\.cloud",
    re.IGNORECASE,
)


def app_base_url() -> str:
    """Public origin for checkout, mail and sales copy.

    Honours an explicit non-retired ``APP_BASE_URL`` (dev/test hosts). A
    missing value, or any value still pointing at the decommissioned Abacus
    VM, resolves to the live Hostinger origin instead of a dead link.
    """
    raw = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
    if not raw or any(marker in raw for marker in _RETIRED_APP_HOST_MARKERS):
        return LIVE_APP_BASE_URL
    return raw


def rewrite_retired_product_urls(text: str) -> str:
    """Replace decommissioned Abacus hosts with the live product origin.

    Path suffixes are kept (``/pricing`` stays ``/pricing``). Used at send
    time, preview time, and when persisting campaign / LinkedIn copy so the
    operator never copies a dead URL out of the admin console.
    """
    return _RETIRED_PRODUCT_URL_RE.sub(app_base_url(), text or "")


def _stripe() -> Any:
    key = _secret_key()
    if not key:
        raise StripeNotConfiguredError("STRIPE_SECRET_KEY is not configured")
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover - SDK absent on a stripped deploy
        raise StripeNotConfiguredError("stripe SDK is not installed") from exc
    stripe.api_key = key
    return stripe


def _field(obj: Any, name: str) -> Any:
    """Read a field from a Stripe object (dict-like) or a mock dict."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def create_customer(*, email: str | None, user_id: str) -> str:
    """Create a Stripe Customer carrying ``user_id`` metadata; return its id.

    NB: identity travels via ``metadata.user_id`` (never ``customer_email=`` —
    a prohibited pattern); ``email`` is passed only as the contact address.
    """
    stripe = _stripe()
    customer = stripe.Customer.create(email=email, metadata={"user_id": user_id})
    return _field(customer, "id")


def create_checkout_session(
    *,
    customer_id: str,
    price_id: str,
    user_id: str,
    plan_id: str,
    plan_name: str,
    description: str,
    amount_aud: float,
    interval: str,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    """Create a subscription Checkout Session; return ``{id, url}``.

    CR-P0-2 (RUN-20260818T0223Z): the line item is built from ``price_data`` —
    an inline Price + Product created for THIS session — rather than by
    referencing the pre-existing catalog ``price_id``. A bare ``price=`` line
    item makes Stripe render that Price's PRODUCT-level ``name``/
    ``description`` verbatim from whatever is configured in the Stripe
    DASHBOARD, which is exactly how a stale "Full model access" / "Standard
    model tier" / "Everything in Pro" overclaim survived on the live Checkout
    page after the same claims were scrubbed from ``/pricing`` (CLI-D3) and
    ``GET /billing/plans`` (AUD-MON-1) — neither of those fixes could reach
    Stripe's own catalog. Building the Product/Price inline from the caller's
    ``plan_name``/``description`` (the router sources both from the SAME
    ``_enforced_facts`` helper /pricing and /billing/plans use) means Checkout
    can never re-drift from what the backend actually enforces: there is
    nothing left in the Dashboard for a future edit to silently disagree with.
    See docs/delivery/evidence/RUN-20260818T0223Z/COMMERCIAL-READINESS/fixes/
    cr-p0-2-checkout.md.

    The catalog ``price_id`` is still required (a plan without one is not
    purchasable — ``_resolve_price_id``) and is preserved in Checkout Session
    metadata as ``catalog_price_id`` for financial reconciliation; it is used
    directly (not the inline price) by ``switch_subscription_price`` /
    ``set_subscription_price`` for an EXISTING subscriber, which modifies a
    subscription in place and never renders a Checkout page — unaffected by
    this change.
    """
    stripe = _stripe()
    kwargs: dict[str, Any] = {}
    if idempotency_key:
        kwargs["idempotency_key"] = idempotency_key
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=user_id,
        line_items=[
            {
                "price_data": {
                    "currency": "aud",
                    "unit_amount": int(round(float(amount_aud) * 100)),
                    "recurring": {"interval": interval},
                    "product_data": {
                        "name": plan_name,
                        "description": description,
                    },
                },
                "quantity": 1,
            }
        ],
        # Managed Payments (enabled by default on this account) selects the
        # payment methods AND handles taxes automatically — Stripe rejects
        # payment_method_types and automatic_tax when it's on, so we omit both.
        metadata={
            "user_id": user_id,
            "plan_id": plan_id,
            "interval": interval,
            "catalog_price_id": price_id,
        },
        # Stamp plan_id + interval onto the SUBSCRIPTION metadata too (not just the
        # Checkout Session) so later customer.subscription.* events can resolve the
        # plan even if the price-id reverse lookup ever comes up empty (PAY-R1-01)
        # — which it always will for THIS subscription's initial price, since it is
        # inline/ad hoc rather than one of the catalog ids ``_plan_by_price_id``
        # recognises. This metadata IS that fallback, by design.
        subscription_data={
            "metadata": {
                "user_id": user_id,
                "plan_id": plan_id,
                "interval": interval,
            }
        },
        success_url=f"{app_base_url()}/dashboard/settings?checkout=success",
        cancel_url=f"{app_base_url()}/pricing?checkout=cancel",
        **kwargs,
    )
    return {"id": _field(session, "id"), "url": _field(session, "url")}


def create_portal_session(*, customer_id: str) -> dict[str, str]:
    """Create a Billing Portal Session; return ``{url}``."""
    stripe = _stripe()
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{app_base_url()}/dashboard/settings",
    )
    return {"url": _field(session, "url")}


def construct_event(payload: bytes, sig_header: str) -> Any:
    """Verify a Stripe webhook signature and return the parsed event.

    Offline HMAC via ``stripe.Webhook.construct_event`` — no network. Raises
    ``StripeNotConfiguredError`` when the webhook secret is missing; otherwise
    propagates ``SignatureVerificationError`` / ``ValueError`` on a bad
    signature/payload for the router to map to 400.
    """
    secret = webhook_secret()
    if not secret:
        raise StripeNotConfiguredError("STRIPE_WEBHOOK_SECRET is not configured")
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover
        raise StripeNotConfiguredError("stripe SDK is not installed") from exc
    return stripe.Webhook.construct_event(payload, sig_header, secret)


def _subscription_item_id(subscription: Any) -> str | None:
    """First line-item id of a retrieved Subscription (``items.data[0].id``)."""
    items = _field(subscription, "items")
    data = items.get("data") if isinstance(items, dict) else _field(items, "data")
    if not data:
        return None
    return _field(data[0], "id")


def switch_subscription_price(
    *,
    subscription_id: str,
    new_price_id: str,
    user_id: str,
    plan_id: str,
    interval: str,
) -> dict[str, str]:
    """Switch an EXISTING subscription to ``new_price_id`` IN PLACE, with
    proration (PAY-R1-02 / PAY-R3-01). This avoids creating a second live
    subscription (double-billing) when a subscriber changes plan.

    Retrieves the subscription to find its current line-item id, then
    ``Subscription.modify`` swaps that item's price and re-stamps the plan
    metadata so future ``customer.subscription.*`` events keep resolving.
    """
    stripe = _stripe()
    current = stripe.Subscription.retrieve(subscription_id)
    item_id = _subscription_item_id(current)
    if not item_id:
        raise StripeNotConfiguredError(
            f"subscription {subscription_id} has no line item to switch"
        )
    updated = stripe.Subscription.modify(
        subscription_id,
        items=[{"id": item_id, "price": new_price_id}],
        proration_behavior="create_prorations",
        metadata={"user_id": user_id, "plan_id": plan_id, "interval": interval},
    )
    return {"id": _field(updated, "id") or subscription_id}


def cancel_subscription(subscription_id: str) -> None:
    """Cancel a Stripe subscription immediately so no further invoices are
    raised (used on refund/dispute revoke and admin refund)."""
    stripe = _stripe()
    stripe.Subscription.cancel(subscription_id)


def set_cancel_at_period_end(subscription_id: str, value: bool) -> dict[str, Any]:
    """Schedule (or un-schedule) cancellation at the END of the paid period.

    The gentle counterpart to :func:`cancel_subscription`: the customer keeps the
    access they have already paid for and no further invoice is raised. Stripe
    remains the source of truth — the caller mirrors the returned flag locally
    and the ``customer.subscription.updated`` webhook reconciles either way, so
    billing state is never hand-invented on our side.
    """
    stripe = _stripe()
    updated = stripe.Subscription.modify(
        subscription_id, cancel_at_period_end=bool(value)
    )
    return {
        "id": _field(updated, "id") or subscription_id,
        "cancelAtPeriodEnd": bool(_field(updated, "cancel_at_period_end")),
    }


def get_charge_customer(charge_id: str) -> str | None:
    """Resolve the customer id behind a charge (dispute payloads carry a charge
    id but not always a customer id)."""
    stripe = _stripe()
    charge = stripe.Charge.retrieve(charge_id)
    return _field(charge, "customer")


def latest_paid_charge(customer_id: str) -> str | None:
    """Id of the customer's most recent PAID, un-refunded, succeeded charge, or
    ``None`` when there is nothing refundable."""
    stripe = _stripe()
    charges = stripe.Charge.list(customer=customer_id, limit=10)
    data = _field(charges, "data") or []
    for charge in data:
        if (
            _field(charge, "paid")
            and not _field(charge, "refunded")
            and _field(charge, "status") == "succeeded"
        ):
            return _field(charge, "id")
    return None


def create_refund(charge_id: str) -> dict[str, str]:
    """Issue a full refund for ``charge_id``; return ``{id, status}``."""
    stripe = _stripe()
    refund = stripe.Refund.create(charge=charge_id)
    return {"id": _field(refund, "id"), "status": _field(refund, "status")}


# --------------------------------------------------------------------------- #
# ADMIN-2.0 — read helpers + safe (charge-free) object creation.
#
# Everything below returns PLAIN DICTS with camelCase keys, so the admin router
# never leaks a raw Stripe object outward and the shapes are stable across SDK
# versions. Amounts are AUD; Stripe stores minor units, so they are converted
# here exactly once (``/100``) and never re-scaled downstream.
#
# MONEY SAFETY: not one function here can move money. The reads are reads; the
# only writes are (1) a Price object — a catalogue entry that charges nobody,
# (2) an IN-PLACE subscription price switch with ``proration_behavior="none"``
# (Stripe raises no invoice for it; the new amount applies from the next
# renewal), and (3) Coupon / PromotionCode objects, which are discounts nobody
# is charged for until a customer redeems one at their own checkout.
# --------------------------------------------------------------------------- #

#: Stripe subscription statuses that mean "this customer is really on the hook".
#: Used by the reconcile guard: if Stripe reports ANY of these, the local row is
#: not stale and must not be cleared.
LIVE_SUBSCRIPTION_STATUSES: tuple[str, ...] = (
    "active",
    "trialing",
    "past_due",
    "unpaid",
    "incomplete",
    "paused",
)


def _aud(minor_units: Any) -> float | None:
    """Stripe minor units -> AUD major units, or ``None`` when absent."""
    if minor_units is None:
        return None
    try:
        return round(int(minor_units) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def _iso(epoch: Any) -> str | None:
    """Stripe epoch seconds -> ISO-8601 UTC, or ``None``."""
    if epoch is None:
        return None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def retrieve_customer(customer_id: str) -> dict[str, Any] | None:
    """A masked summary of one Stripe Customer, or ``None`` when it is gone.

    A customer id that no longer resolves is REAL information (the local row
    points at nothing), so a Stripe ``InvalidRequestError`` is translated to
    ``None`` rather than propagated as a 500.
    """
    stripe = _stripe()
    try:
        customer = stripe.Customer.retrieve(customer_id)
    except Exception:  # noqa: BLE001 - a missing/deleted customer is a real answer
        return None
    if customer is None or _field(customer, "deleted"):
        return None
    return {
        "id": _field(customer, "id"),
        "email": _field(customer, "email"),
        "name": _field(customer, "name"),
        "delinquent": bool(_field(customer, "delinquent")),
        "created": _iso(_field(customer, "created")),
    }


def _subscription_summary(subscription: Any) -> dict[str, Any] | None:
    if subscription is None:
        return None
    items = _field(subscription, "items")
    data = (items.get("data") if isinstance(items, dict) else _field(items, "data")) or []
    price = _field(data[0], "price") if data else None
    recurring = _field(price, "recurring") if price is not None else None
    return {
        "id": _field(subscription, "id"),
        "status": _field(subscription, "status"),
        "cancelAtPeriodEnd": bool(_field(subscription, "cancel_at_period_end")),
        "currentPeriodEnd": _iso(_field(subscription, "current_period_end")),
        "amountAud": _aud(_field(price, "unit_amount")) if price is not None else None,
        "interval": _field(recurring, "interval") if recurring is not None else None,
        "priceId": _field(price, "id") if price is not None else None,
    }


def retrieve_subscription(subscription_id: str) -> dict[str, Any] | None:
    """A summary of one Stripe Subscription, or ``None`` when it does not exist."""
    stripe = _stripe()
    try:
        subscription = stripe.Subscription.retrieve(subscription_id)
    except Exception:  # noqa: BLE001 - "no such subscription" is a real answer
        return None
    return _subscription_summary(subscription)


def list_subscriptions(customer_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Every subscription Stripe holds for this customer (any status)."""
    stripe = _stripe()
    result = stripe.Subscription.list(customer=customer_id, status="all", limit=limit)
    data = _field(result, "data") or []
    summaries = [_subscription_summary(s) for s in data]
    return [s for s in summaries if s is not None]


def list_invoices(customer_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """The customer's most recent invoices (amounts in AUD)."""
    stripe = _stripe()
    result = stripe.Invoice.list(customer=customer_id, limit=limit)
    data = _field(result, "data") or []
    return [
        {
            "id": _field(inv, "id"),
            "number": _field(inv, "number"),
            "status": _field(inv, "status"),
            "amountDueAud": _aud(_field(inv, "amount_due")),
            "amountPaidAud": _aud(_field(inv, "amount_paid")),
            "created": _iso(_field(inv, "created")),
            "hostedInvoiceUrl": _field(inv, "hosted_invoice_url"),
        }
        for inv in data
    ]


def payment_method_summary(customer_id: str) -> dict[str, Any] | None:
    """MASKED card summary for the customer's default payment method.

    Brand + last4 + expiry ONLY — the fields Stripe itself exposes. A full PAN
    never exists on our side, and nothing here widens that.
    """
    stripe = _stripe()
    try:
        customer = stripe.Customer.retrieve(
            customer_id, expand=["invoice_settings.default_payment_method"]
        )
    except Exception:  # noqa: BLE001 - missing customer is a real answer
        return None
    settings = _field(customer, "invoice_settings")
    pm = (
        settings.get("default_payment_method")
        if isinstance(settings, dict)
        else _field(settings, "default_payment_method")
    )
    if pm is None:
        return None
    if isinstance(pm, str):
        try:
            pm = stripe.PaymentMethod.retrieve(pm)
        except Exception:  # noqa: BLE001
            return None
    card = _field(pm, "card")
    if card is None:
        return {"brand": None, "last4": None, "expMonth": None, "expYear": None}
    return {
        "brand": _field(card, "brand"),
        "last4": _field(card, "last4"),
        "expMonth": _field(card, "exp_month"),
        "expYear": _field(card, "exp_year"),
    }


def create_price(
    *,
    amount_aud: float,
    interval: str,
    user_id: str,
    product_id: str | None = None,
    product_name: str = "Aether (custom price)",
) -> dict[str, Any]:
    """Create a recurring AUD Price. Charges nobody — this is a catalogue entry.

    No tax behaviour is set: the operator is not GST-registered, so no GST line
    is added to anything (and none is claimed in the response).
    """
    stripe = _stripe()
    kwargs: dict[str, Any] = {
        "currency": "aud",
        "unit_amount": int(round(float(amount_aud) * 100)),
        "recurring": {"interval": interval},
        "metadata": {"user_id": user_id, "source": "aether_admin_custom_price"},
    }
    if product_id:
        kwargs["product"] = product_id
    else:
        kwargs["product_data"] = {"name": product_name}
    price = stripe.Price.create(**kwargs)
    return {
        "id": _field(price, "id"),
        "amountAud": _aud(_field(price, "unit_amount")) or float(amount_aud),
        "interval": interval,
    }


def set_subscription_price(
    *,
    subscription_id: str,
    new_price_id: str,
    user_id: str,
    plan_id: str,
    interval: str,
) -> dict[str, Any]:
    """Point an EXISTING subscription at ``new_price_id`` with NO proration.

    The deliberate difference from :func:`switch_subscription_price` (which
    prorates, because a self-service plan change should settle the difference
    for the period already paid): an ADMIN setting a negotiated amount must not
    raise an immediate invoice or credit off the back of an admin click. With
    ``proration_behavior="none"`` Stripe writes no invoice items at all, so the
    new amount simply takes effect at the next renewal — nobody is charged
    twice, and nobody is charged at all by this call.

    Never creates a second subscription (that is the double-billing failure
    PAY-R1-02 exists to prevent) — it modifies the one that already exists.
    """
    stripe = _stripe()
    current = stripe.Subscription.retrieve(subscription_id)
    item_id = _subscription_item_id(current)
    if not item_id:
        raise StripeNotConfiguredError(
            f"subscription {subscription_id} has no line item to reprice"
        )
    updated = stripe.Subscription.modify(
        subscription_id,
        items=[{"id": item_id, "price": new_price_id}],
        proration_behavior="none",
        metadata={
            "user_id": user_id,
            "plan_id": plan_id,
            "interval": interval,
            "custom_price": "true",
        },
    )
    return {
        "id": _field(updated, "id") or subscription_id,
        "priceId": new_price_id,
        "prorationBehavior": "none",
    }


def create_coupon(
    *,
    name: str | None = None,
    percent_off: float | None = None,
    amount_off_aud: float | None = None,
    duration: str = "once",
    duration_in_months: int | None = None,
) -> dict[str, Any]:
    """Create a Stripe Coupon. A discount definition — it charges nobody."""
    stripe = _stripe()
    kwargs: dict[str, Any] = {"duration": duration}
    if name:
        kwargs["name"] = name
    if percent_off is not None:
        kwargs["percent_off"] = float(percent_off)
    if amount_off_aud is not None:
        kwargs["amount_off"] = int(round(float(amount_off_aud) * 100))
        kwargs["currency"] = "aud"
    if duration == "repeating" and duration_in_months is not None:
        kwargs["duration_in_months"] = int(duration_in_months)
    coupon = stripe.Coupon.create(**kwargs)
    return {
        "id": _field(coupon, "id"),
        "name": _field(coupon, "name"),
        "percentOff": _field(coupon, "percent_off"),
        "amountOffAud": _aud(_field(coupon, "amount_off")),
        "duration": _field(coupon, "duration"),
        "durationInMonths": _field(coupon, "duration_in_months"),
    }


def _promotion_code_summary(pc: Any) -> dict[str, Any]:
    # Stripe's PromotionCode object nests the coupon under `.promotion.coupon`
    # (the `type: "coupon"` / `promotion` shape) — there is no top-level
    # `.coupon` field on the current API version. Reading the old top-level
    # field silently returned None for every listed code (LIVE-VERIFY ADMIN-2.0
    # VERIFY(d) caught this: the create call below hit the same shape mismatch
    # as a hard Stripe 400, which is what actually surfaced it).
    promotion = _field(pc, "promotion")
    coupon = _field(promotion, "coupon") if promotion is not None else None
    return {
        "id": _field(pc, "id"),
        "code": _field(pc, "code"),
        "active": bool(_field(pc, "active")),
        "couponId": _field(coupon, "id") if coupon is not None else None,
        "percentOff": _field(coupon, "percent_off") if coupon is not None else None,
        "amountOffAud": (
            _aud(_field(coupon, "amount_off")) if coupon is not None else None
        ),
        "duration": _field(coupon, "duration") if coupon is not None else None,
        "timesRedeemed": _field(pc, "times_redeemed"),
        "maxRedemptions": _field(pc, "max_redemptions"),
        "expiresAt": _iso(_field(pc, "expires_at")),
    }


def create_promotion_code(
    *,
    coupon_id: str,
    code: str | None = None,
    max_redemptions: int | None = None,
    expires_at: int | None = None,
) -> dict[str, Any]:
    """Create the customer-facing PromotionCode for a Coupon. Charges nobody."""
    stripe = _stripe()
    # Stripe SDK v13 / current API version: PromotionCode.create takes a
    # nested `promotion={"type": "coupon", "coupon": <id>}`, not a top-level
    # `coupon=` kwarg. The flat shape is REJECTED server-side with "Received
    # unknown parameter: coupon" — reproduced live in ADMIN-2.0 VERIFY(d)
    # (the existing unit tests mock this function itself, so they never
    # exercised the real `stripe.PromotionCode.create` call shape).
    kwargs: dict[str, Any] = {"promotion": {"type": "coupon", "coupon": coupon_id}}
    if code:
        kwargs["code"] = code
    if max_redemptions is not None:
        kwargs["max_redemptions"] = int(max_redemptions)
    if expires_at is not None:
        kwargs["expires_at"] = int(expires_at)
    # `promotion.coupon` is an ExpandableField — without expansion Stripe
    # returns just the coupon's id string, so percentOff/amountOff/duration
    # would silently read as None. Expand it so the response this function
    # returns is immediately useful without a second round trip.
    kwargs["expand"] = ["promotion.coupon"]
    pc = stripe.PromotionCode.create(**kwargs)
    return _promotion_code_summary(pc)


def list_promotion_codes(limit: int = 50) -> list[dict[str, Any]]:
    """Existing promotion codes (Stripe is the source of truth, not our DB)."""
    stripe = _stripe()
    # Same expansion as create_promotion_code — list items are ExpandableFields
    # too, and the "data." prefix is required for expanding fields nested
    # inside a list response's items.
    result = stripe.PromotionCode.list(limit=limit, expand=["data.promotion.coupon"])
    return [_promotion_code_summary(pc) for pc in (_field(result, "data") or [])]


def deactivate_promotion_code(promotion_code_id: str) -> dict[str, Any]:
    """Deactivate a promotion code (``active=false``).

    Deliberately NOT a coupon delete: deactivation is reversible and leaves the
    redemption history of anyone who already used the code intact.
    """
    stripe = _stripe()
    pc = stripe.PromotionCode.modify(promotion_code_id, active=False)
    return {"id": _field(pc, "id") or promotion_code_id, "active": bool(_field(pc, "active"))}
