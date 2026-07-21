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


def automatic_tax_enabled() -> bool:
    """Stripe Tax toggle — defaults OFF (§1.5; requires the paid Stripe Tax
    product, which launch does not use)."""
    return os.environ.get("STRIPE_AUTOMATIC_TAX", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def app_base_url() -> str:
    return os.environ.get(
        "APP_BASE_URL", "https://5cb5f0620.abacusai.cloud"
    ).rstrip("/")


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
    interval: str,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    """Create a subscription Checkout Session; return ``{id, url}``."""
    stripe = _stripe()
    kwargs: dict[str, Any] = {}
    if idempotency_key:
        kwargs["idempotency_key"] = idempotency_key
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=user_id,
        line_items=[{"price": price_id, "quantity": 1}],
        # Managed Payments (enabled by default on this account) selects the
        # payment methods AND handles taxes automatically — Stripe rejects
        # payment_method_types and automatic_tax when it's on, so we omit both.
        metadata={"user_id": user_id, "plan_id": plan_id, "interval": interval},
        # Stamp plan_id + interval onto the SUBSCRIPTION metadata too (not just the
        # Checkout Session) so later customer.subscription.* events can resolve the
        # plan even if the price-id reverse lookup ever comes up empty (PAY-R1-01).
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
