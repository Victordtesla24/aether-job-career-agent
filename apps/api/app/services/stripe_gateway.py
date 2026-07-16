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
        payment_method_types=["card", "au_becs_debit"],
        automatic_tax={"enabled": automatic_tax_enabled()},
        metadata={"user_id": user_id, "plan_id": plan_id, "interval": interval},
        subscription_data={"metadata": {"user_id": user_id, "plan_id": plan_id}},
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
