"""INC-B-001 (GOLD-MASTER-V2 W-B wave 1) — the Stripe
``customer.subscription.trial_will_end`` webhook handler is a bare ``pass``
(``apps/api/app/routers/billing.py:298``): trial users approaching their
first charge receive no reminder, and the event leaves no trace beyond the
generic ``StripeEvent`` idempotency row every event type gets regardless of
its handler (so "was this event even seen" is indistinguishable from "was
it handled").

[VERIFIED-WITH-SOURCE]
```
elif event_type == "customer.subscription.trial_will_end":
    pass  # hook point for a reminder notification; no state change
```
Grepped this codebase for any outbound-system-email mechanism (smtplib /
EmailMessage / sendgrid / postmark / resend) -- zero hits outside
``app/services/gmail_service.py``, which is the USER's own OAuth-connected
inbox, not something Aether can send FROM. No "Notification" or reminder-
tracking table/column exists anywhere in the schema either. So "notify" (an
actual outbound email) is not a buildable minimal fix without new
infrastructure; "record" is.

Test-author's chosen minimal, defensible contract (same latitude the
finding text grants BLOCKER-002 -- "choose a defensible ... rule and assert
it" -- applied here to "record/notify"): mirror the sibling handlers'
Subscription-row-mutation pattern. Every other stateful handler in this
file (``_handle_payment_failed``, ``_handle_subscription_updated``,
``_handle_charge_refunded``, ``_handle_dispute_created``, ...) resolves the
affected user via ``_user_by_subscription``/``_user_by_customer`` and then
``UPDATE``s the ``"Subscription"`` row. The smallest additive analogue that
makes "a reminder was recorded" durably observable is a new nullable
``Subscription."trialEndNotifiedAt"`` timestamptz column, stamped to
``now()`` for the resolved user when a ``trial_will_end`` event is
processed. This is additive-only (fits this repo's established
``ADD COLUMN IF NOT EXISTS`` migration discipline -- see
``apps/api/app/repositories/billing.py``'s own ``CREATE TABLE IF NOT EXISTS``
/ ``ADD COLUMN`` pattern) and requires no new notification infrastructure.
A fixer is free to ALSO wire a real outbound reminder on top; this test only
requires the durable record to exist and be stamped.

The test queries ``information_schema.columns`` before touching the column
so a not-yet-existing column produces a clean, readable assertion failure
(matching today's bare-``pass`` reality) instead of a raw
``psycopg2.errors.UndefinedColumn`` DB error.

Do NOT send anything to real Stripe: the signature is generated locally
with a test ``STRIPE_WEBHOOK_SECRET`` and verified through the real
``stripe.Webhook.construct_event`` (offline HMAC) -- the exact technique
already established in ``tests/test_gap_p6_billing.py``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Optional

from app.db import get_connection, new_id

WEBHOOK_SECRET = "whsec_test_wb1_incb001_secret"


def _sign(payload: bytes, secret: str = WEBHOOK_SECRET, ts: int | None = None) -> str:
    """Build a Stripe-Signature header over the EXACT raw bytes (offline HMAC) --
    same technique as tests/test_gap_p6_billing.py::_sign."""
    ts = ts or int(time.time())
    signed = f"{ts}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def _checkout_event(
    user_id: str, plan_id: str, evt_id: str, customer_id: str, subscription_id: str
) -> bytes:
    """A minimal checkout.session.completed event -- establishes a real
    Subscription row with KNOWN Stripe customer/subscription ids, so the
    later trial_will_end event can resolve to the same user the same way
    Stripe's real webhooks would (via stripeCustomerId/stripeSubscriptionId)."""
    return json.dumps(
        {
            "id": evt_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_" + new_id(),
                    "customer": customer_id,
                    "subscription": subscription_id,
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


def _trial_will_end_event(customer_id: str, subscription_id: str, evt_id: str) -> bytes:
    """A minimal customer.subscription.trial_will_end event. For a
    ``customer.subscription.*`` event the payload's ``data.object`` IS the
    Subscription object itself (its own ``id`` is the Stripe subscription
    id) -- mirrors how ``_handle_subscription_updated``/
    ``_handle_subscription_deleted`` already resolve the user via
    ``_obj_get(obj, "id")`` -> ``_user_by_subscription``."""
    return json.dumps(
        {
            "id": evt_id,
            "type": "customer.subscription.trial_will_end",
            "data": {
                "object": {
                    "id": subscription_id,
                    "customer": customer_id,
                    "status": "trialing",
                    "trial_end": int(time.time()) + 3 * 86400,
                }
            },
        }
    ).encode()


def _trial_notified_at(user_id: str) -> Optional[Any]:
    """The test-author's chosen contract's observable state, or None if the
    column doesn't exist yet (today's reality) or is still NULL for this
    user."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'Subscription' AND column_name = 'trialEndNotifiedAt'"
            )
            if cur.fetchone() is None:
                return None
            cur.execute(
                'SELECT "trialEndNotifiedAt" FROM "Subscription" WHERE "userId" = %s',
                (user_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None


def test_trial_will_end_webhook_records_something_not_silently_discarded(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)

    customer_id = "cus_test_" + new_id()
    subscription_id = "sub_test_" + new_id()

    # Establish a real Subscription row with known Stripe ids first.
    checkout_payload = _checkout_event(
        test_user_id, "pro", "evt_" + new_id(), customer_id, subscription_id
    )
    checkout_resp = client.post(
        "/billing/webhooks/stripe",
        content=checkout_payload,
        headers={"stripe-signature": _sign(checkout_payload)},
    )
    assert checkout_resp.status_code == 200 and checkout_resp.json()["status"] == "processed", (
        checkout_resp.text
    )

    before = _trial_notified_at(test_user_id)

    trial_payload = _trial_will_end_event(customer_id, subscription_id, "evt_" + new_id())
    trial_resp = client.post(
        "/billing/webhooks/stripe",
        content=trial_payload,
        headers={"stripe-signature": _sign(trial_payload)},
    )
    # The webhook envelope itself already "succeeds" today (the shared
    # idempotency wrapper always marks the StripeEvent row 'processed' even
    # when the per-type handler is a no-op) -- this is NOT the discriminating
    # assertion, kept only as a sanity precondition for the real check below.
    assert trial_resp.status_code == 200 and trial_resp.json()["status"] == "processed", (
        trial_resp.text
    )

    after = _trial_notified_at(test_user_id)
    assert after is not None, (
        "customer.subscription.trial_will_end must leave a durable, queryable "
        "record that the reminder was handled (this test's chosen contract: "
        "Subscription.trialEndNotifiedAt stamped to now()) -- not silently "
        "discard the event. billing.py:298 is currently a bare `pass`, so "
        "no such record exists (before=%r, after=%r)." % (before, after)
    )
    assert after != before, (
        "trialEndNotifiedAt must actually be STAMPED by processing this "
        f"event, not merely pre-existing/unchanged (before={before!r}, after={after!r})"
    )
