"""Billing router — plans, checkout, Stripe webhook, subscription, portal
(GAP-P6-BILL-001 / PRICING-001, Cluster D).

Mounted at prefix ``/billing`` in ``app.main``; the platform ingress maps the
external ``/api/*`` onto the API service, so the public contract is
``/api/billing/...``. All Stripe SDK access goes through
``app.services.stripe_gateway`` (mocked in unit tests, ADR-P6-STRIPE-MOCK).
Secrets are read from ``os.environ`` only; a missing ``STRIPE_SECRET_KEY`` yields
an honest 503 — never a fabricated success.
"""
from __future__ import annotations

import json
import os
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.db import get_connection
from app.middleware.auth import AdminUser, CurrentUser
from app.repositories import admin as admin_repo
from app.repositories.billing import (
    PlanRepository,
    SubscriptionRepository,
    UsageQuotaRepository,
    _ensure_billing_tables,
    ensure_user_billing,
    gst_breakdown,
    subscription_gate_enabled,
)
from app.repositories.user import UserRepository
from app.services import stripe_gateway

router = APIRouter()

#: Presentation copy for /pricing (design §3.1 features[] is presentation only).
_PLAN_FEATURES: dict[str, list[str]] = {
    "free": [
        "5 tailored agent runs / month",
        "Light model tier",
        "Resume tailoring + ATS scoring",
        "Community support",
    ],
    "starter": [
        "30 tailored agent runs / month",
        "Standard model tier",
        "Cover letters + story bank",
        "Email agent (triage + drafts)",
    ],
    "pro": [
        "100 tailored agent runs / month",
        "Advanced model tier",
        "Everything in Starter",
        "Priority email agent",
    ],
    "power": [
        "300 tailored agent runs / month",
        "Full model access",
        "Everything in Pro",
        "Highest monthly run ceiling",
    ],
}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    planId: str = Field(min_length=1)
    interval: Literal["month", "year"] = "month"


# ---------------------------------------------------------------------------
# GET /billing/plans (public)
# ---------------------------------------------------------------------------


@router.get("/plans")
def list_plans() -> dict[str, Any]:
    """Active plans with the GST breakdown pre-computed server-side."""
    plans = []
    for p in PlanRepository().list_active():
        monthly_total = float(p["priceAudMonthly"])
        annual = None
        if p["priceAudAnnual"] is not None:
            annual = gst_breakdown(p["priceAudAnnual"])
        plans.append(
            {
                "id": p["id"],
                "name": p["name"],
                "modelTier": p["modelTier"],
                "runsPerMonth": int(p["runsPerMonth"]),
                "monthly": gst_breakdown(monthly_total),
                "annual": annual,
                "features": _PLAN_FEATURES.get(p["id"], []),
                "purchasable": p["id"] != "free",
            }
        )
    return {"currency": "AUD", "gstIncluded": True, "plans": plans}


# ---------------------------------------------------------------------------
# POST /billing/checkout (auth; 5/hr/user)
# ---------------------------------------------------------------------------


def _resolve_price_id(plan: dict[str, Any], interval: str) -> Optional[str]:
    """Price id from the Plan row, or an env fallback (§5.4). The Plan columns
    are the durable store; env lets a live deploy work before a DB write."""
    col = "stripePriceIdMonthly" if interval == "month" else "stripePriceIdAnnual"
    price_id = plan.get(col)
    if price_id:
        return price_id
    suffix = "MONTH" if interval == "month" else "YEAR"
    return os.environ.get(f"STRIPE_PRICE_{plan['id'].upper()}_{suffix}")


@router.post("/checkout")
def create_checkout(
    body: CheckoutRequest, current_user: CurrentUser, request: Request
) -> dict[str, Any]:
    user_id = current_user["id"]
    limiter = getattr(request.app.state, "checkout_rate_limiter", None)
    if limiter is not None and not limiter.allow(user_id):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many checkout attempts, retry later",
            headers={"Retry-After": str(limiter.retry_after(user_id))},
        )

    plan = PlanRepository().get(body.planId)
    if plan is None or not plan["active"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or inactive plan")
    if plan["id"] == "free":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The Free plan does not require checkout"
        )
    price_id = _resolve_price_id(plan, body.interval)
    if not price_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This plan is not yet available for purchase (no Stripe price configured)",
        )
    if not stripe_gateway.is_configured():
        # Honest 503 — never a fabricated checkout URL (ADR-P6-STRIPE-MOCK).
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Billing is not configured on this deployment yet",
        )

    # Create-or-reuse the Stripe Customer (NOT customer_email=).
    sub = SubscriptionRepository().get_by_user(user_id)
    customer_id = sub.get("stripeCustomerId") if sub else None
    if not customer_id:
        customer_id = stripe_gateway.create_customer(
            email=current_user.get("email"), user_id=user_id
        )
        SubscriptionRepository().set_customer_id(user_id, customer_id)

    # PAY-R1-02 / PAY-R3-01 — NEVER create a SECOND live subscription. If the
    # caller already holds an active Stripe subscription (a real
    # stripeSubscriptionId whose status is still billable), switch that
    # subscription's price IN PLACE (with proration) instead of opening a new
    # Checkout Session. A second subscription-mode session would double-bill the
    # customer AND orphan the first subscription (the DB tracks only one row per
    # user), so the ONLY safe in-app plan change is an in-place price switch.
    existing_sub_id = sub.get("stripeSubscriptionId") if sub else None
    existing_status = sub.get("status") if sub else None
    if existing_sub_id and existing_status in ("active", "trialing", "past_due"):
        current_interval = (sub.get("billingInterval") or "month") if sub else "month"
        if sub and sub.get("planId") == plan["id"] and current_interval == body.interval:
            # Already on exactly this plan+interval — no Stripe call, honest ack.
            return {
                "switched": True,
                "planId": plan["id"],
                "message": f"You are already on {plan['name']}.",
            }
        stripe_gateway.switch_subscription_price(
            subscription_id=existing_sub_id,
            new_price_id=price_id,
            user_id=user_id,
            plan_id=plan["id"],
            interval=body.interval,
        )
        _sync_plan_and_quota(user_id, plan["id"], body.interval)
        return {
            "switched": True,
            "planId": plan["id"],
            "message": f"Your plan was updated to {plan['name']}.",
        }

    session = stripe_gateway.create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        user_id=user_id,
        plan_id=plan["id"],
        interval=body.interval,
    )
    return {"checkoutUrl": session["url"], "sessionId": session["id"]}


# ---------------------------------------------------------------------------
# POST /billing/webhooks/stripe (public, Stripe-signed) — the critical handler
# ---------------------------------------------------------------------------


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> Response:
    # 1. RAW BODY FIRST — never a Pydantic body model (that would re-encode the
    #    bytes and invalidate the signature).
    payload: bytes = await request.body()
    # 2. SIGNATURE SECOND.
    sig_header = request.headers.get("stripe-signature")
    if not sig_header:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing stripe-signature header")
    try:
        event = stripe_gateway.construct_event(payload, sig_header)
    except stripe_gateway.StripeNotConfiguredError:
        # Server misconfig — we cannot verify, so we must not accept. 503 => retry.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Stripe webhook secret is not configured",
        )
    except Exception:  # SignatureVerificationError / ValueError (bad payload)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature")

    # 3. PARSE THIRD — only now touch the event contents.
    event_id = event["id"]
    event_type = event["type"]
    obj = event["data"]["object"]

    _ensure_billing_tables()
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                # 4. Transaction-safe idempotency: record the event as
                #    'processing' in the SAME txn as its side effects.
                cur.execute(
                    'INSERT INTO "StripeEvent" ("id","type","status","payloadJson","receivedAt") '
                    "VALUES (%s,%s,'processing',%s::jsonb,now()) "
                    'ON CONFLICT ("id") DO NOTHING RETURNING "id"',
                    (event_id, event_type, payload.decode("utf-8")),
                )
                if cur.fetchone() is None:
                    # Already seen — idempotent replay, no-op.
                    conn.commit()
                    return _json_response({"received": True, "status": "already_processed"})

                _dispatch_stripe_event(cur, event_type, obj)

                cur.execute(
                    'UPDATE "StripeEvent" SET "status"=\'processed\',"processedAt"=now() '
                    'WHERE "id"=%s',
                    (event_id,),
                )
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            # Handler failed — roll the WHOLE txn back (StripeEvent insert too),
            # so the event is NOT recorded as processed and Stripe retries later.
            conn.rollback()
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "Webhook handler failed"
            )
    return _json_response({"received": True, "status": "processed"})


def _json_response(payload: dict[str, Any]) -> Response:
    return Response(content=json.dumps(payload), media_type="application/json")


# ---------------------------------------------------------------------------
# Webhook handlers — each operates on the SHARED cursor (one txn)
# ---------------------------------------------------------------------------


def _dispatch_stripe_event(cur: Any, event_type: str, obj: dict[str, Any]) -> None:
    if event_type == "checkout.session.completed":
        _handle_checkout_completed(cur, obj)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(cur, obj)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(cur, obj)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(cur, obj)
    elif event_type == "invoice.paid":
        _handle_invoice_paid(cur, obj)
    elif event_type == "charge.refunded":
        _handle_charge_refunded(cur, obj)
    elif event_type == "charge.dispute.created":
        _handle_dispute_created(cur, obj)
    elif event_type == "customer.subscription.trial_will_end":
        pass  # hook point for a reminder notification; no state change
    # Unknown types: no-op but still marked 'processed' (idempotent ack).


def _plan_limits(cur: Any, plan_id: str) -> tuple[int, float]:
    cur.execute(
        'SELECT "runsPerMonth","spendCapUsdMonthly" FROM "Plan" WHERE "id"=%s',
        (plan_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"unknown plan '{plan_id}'")
    return int(row[0]), float(row[1])


def _obj_get(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _interval_span(interval: str) -> str:
    return "1 year" if interval == "year" else "1 month"


def _subscription_price_id(obj: Any) -> Optional[str]:
    """First line-item price id from a subscription object.

    Tolerates the real Stripe shape (``items.data[0].price.id``), the flattened
    list shape (``items[0].price``), and a price passed as a bare string.
    """
    items = _obj_get(obj, "items")
    if isinstance(items, dict):
        data = items.get("data")
    elif isinstance(items, list):
        data = items
    else:
        data = _obj_get(items, "data")
    if not data:
        return None
    price = _obj_get(data[0], "price")
    if isinstance(price, str):
        return price
    return _obj_get(price, "id")


def _plan_by_price_id(cur: Any, price_id: Optional[str]) -> Optional[tuple[str, str]]:
    """Reverse-map a Stripe price id to ``(plan_id, interval)`` (PAY-R1-01).

    Prefers the durable ``Plan.stripePriceId*`` columns, then falls back to the
    ``STRIPE_PRICE_<PLAN>_<MONTH|YEAR>`` env ids that ``_resolve_price_id`` uses,
    so a live deploy that configured prices via env (before a DB write) still
    resolves. ``interval`` is derived from WHICH column/env matched. Returns
    ``None`` when the price id matches no plan.
    """
    if not price_id:
        return None
    cur.execute(
        'SELECT "id","stripePriceIdMonthly","stripePriceIdAnnual" FROM "Plan"'
    )
    rows = cur.fetchall()
    for plan_id, monthly, annual in rows:
        if monthly and monthly == price_id:
            return plan_id, "month"
        if annual and annual == price_id:
            return plan_id, "year"
    for plan_id, _monthly, _annual in rows:
        if os.environ.get(f"STRIPE_PRICE_{plan_id.upper()}_MONTH") == price_id:
            return plan_id, "month"
        if os.environ.get(f"STRIPE_PRICE_{plan_id.upper()}_YEAR") == price_id:
            return plan_id, "year"
    return None


def _sync_plan_and_quota(user_id: str, plan_id: str, interval: str) -> None:
    """Point a user's Subscription + UsageQuota at ``plan_id`` (runsAllowed /
    spendCap from the plan) WITHOUT resetting the in-period ``runsUsed`` — an
    in-place plan switch keeps the current period's usage (mirrors the webhook's
    ``_handle_subscription_updated`` plan sync). Router-level (own connection);
    the webhook path uses the shared cursor instead.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            runs_allowed, spend_cap = _plan_limits(cur, plan_id)
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"billingInterval"=%s,'
                '"updatedAt"=now() WHERE "userId"=%s',
                (plan_id, interval, user_id),
            )
            cur.execute(
                'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=%s,'
                '"spendCapUsd"=%s,"updatedAt"=now() WHERE "userId"=%s',
                (plan_id, runs_allowed, spend_cap, user_id),
            )
        conn.commit()


def _handle_checkout_completed(cur: Any, obj: dict[str, Any]) -> None:
    metadata = _obj_get(obj, "metadata") or {}
    user_id = metadata.get("user_id") or _obj_get(obj, "client_reference_id")
    plan_id = metadata.get("plan_id")
    interval = metadata.get("interval") or "month"
    if not user_id or not plan_id:
        raise ValueError("checkout.session.completed missing user_id/plan_id metadata")
    customer_id = _obj_get(obj, "customer")
    subscription_id = _obj_get(obj, "subscription")
    runs_allowed, spend_cap = _plan_limits(cur, plan_id)

    cur.execute(
        f'''
        INSERT INTO "Subscription" ("userId","planId","status","billingInterval",
            "stripeCustomerId","stripeSubscriptionId","currentPeriodStart",
            "currentPeriodEnd","createdAt","updatedAt")
        VALUES (%s,%s,'active',%s,%s,%s, now(), now() + interval '{_interval_span(interval)}',
                now(), now())
        ON CONFLICT ("userId") DO UPDATE SET
            "planId"=EXCLUDED."planId",
            "status"='active',
            "billingInterval"=EXCLUDED."billingInterval",
            "stripeCustomerId"=COALESCE(EXCLUDED."stripeCustomerId","Subscription"."stripeCustomerId"),
            "stripeSubscriptionId"=EXCLUDED."stripeSubscriptionId",
            "currentPeriodStart"=EXCLUDED."currentPeriodStart",
            "currentPeriodEnd"=EXCLUDED."currentPeriodEnd",
            "updatedAt"=now()
        ''',
        (user_id, plan_id, interval, customer_id, subscription_id),
    )
    _reset_quota(cur, user_id, plan_id, runs_allowed, spend_cap)


def _handle_subscription_updated(cur: Any, obj: dict[str, Any]) -> None:
    metadata = _obj_get(obj, "metadata") or {}
    subscription_id = _obj_get(obj, "id")
    user_id = metadata.get("user_id") or _user_by_subscription(cur, subscription_id)
    if not user_id:
        # PAY-R2-06: an out-of-order customer.subscription.updated for a user with
        # no local Subscription row resolves to no user. We intentionally ack it
        # idempotently (return) rather than INSERT here — checkout.session.completed
        # is the authoritative row-creation event, and it carries the plan/customer
        # linkage this partial update lacks. (Lowest-priority; no behaviour change.)
        return  # unknown subscription — nothing to sync (still acked idempotently)
    new_status = _obj_get(obj, "status") or "active"
    cancel_at_end = bool(_obj_get(obj, "cancel_at_period_end"))
    period_start = _obj_get(obj, "current_period_start")
    period_end = _obj_get(obj, "current_period_end")

    # PAY-R1-01: derive the plan from the subscription's LINE-ITEM PRICE first — a
    # real Billing-Portal upgrade/downgrade (or any price swap) carries the new
    # price id but stale/absent app metadata, so metadata.plan_id alone silently
    # missed the change. Prefer the price-id-derived plan; fall back to metadata
    # only when the price matches no plan.
    price_id = _subscription_price_id(obj)
    resolved = _plan_by_price_id(cur, price_id)
    if resolved is not None:
        plan_id, interval = resolved
    else:
        plan_id = metadata.get("plan_id")
        interval = metadata.get("interval")

    cur.execute(
        '''
        UPDATE "Subscription" SET
            "status"=%s,
            "cancelAtPeriodEnd"=%s,
            "currentPeriodStart"=CASE WHEN %s IS NULL THEN "currentPeriodStart"
                                      ELSE to_timestamp(%s) END,
            "currentPeriodEnd"=CASE WHEN %s IS NULL THEN "currentPeriodEnd"
                                    ELSE to_timestamp(%s) END,
            "stripeSubscriptionId"=COALESCE(%s,"stripeSubscriptionId"),
            "updatedAt"=now()
        WHERE "userId"=%s
        ''',
        (
            new_status, cancel_at_end,
            period_start, period_start,
            period_end, period_end,
            subscription_id, user_id,
        ),
    )
    if plan_id:
        runs_allowed, spend_cap = _plan_limits(cur, plan_id)
        cur.execute(
            'UPDATE "Subscription" SET "planId"=%s,'
            '"billingInterval"=COALESCE(%s,"billingInterval"),"updatedAt"=now() '
            'WHERE "userId"=%s',
            (plan_id, interval, user_id),
        )
        cur.execute(
            'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=%s,"spendCapUsd"=%s,'
            '"updatedAt"=now() WHERE "userId"=%s',
            (plan_id, runs_allowed, spend_cap, user_id),
        )


def _revoke_to_free(cur: Any, user_id: str, *, cancel_stripe: bool) -> None:
    """Downgrade a user to Free + reset their quota (shared by
    subscription.deleted, charge.refunded, charge.dispute.created, and the admin
    refund endpoint). When ``cancel_stripe`` is set, first cancel the live Stripe
    subscription so no further invoices are raised — best-effort: a Stripe cancel
    failure (already canceled / not configured) must NOT block the local revoke.
    """
    if cancel_stripe:
        cur.execute(
            'SELECT "stripeSubscriptionId" FROM "Subscription" WHERE "userId"=%s',
            (user_id,),
        )
        row = cur.fetchone()
        sub_id = row[0] if row else None
        if sub_id:
            try:
                stripe_gateway.cancel_subscription(sub_id)
            except Exception:  # noqa: BLE001 — best-effort; revoke must still land
                pass
    runs_allowed, spend_cap = _plan_limits(cur, "free")
    cur.execute(
        'UPDATE "Subscription" SET "planId"=\'free\',"status"=\'canceled\','
        '"stripeSubscriptionId"=NULL,"billingInterval"=NULL,"cancelAtPeriodEnd"=false,'
        '"updatedAt"=now() WHERE "userId"=%s',
        (user_id,),
    )
    _reset_quota(cur, user_id, "free", runs_allowed, spend_cap)


def _handle_subscription_deleted(cur: Any, obj: dict[str, Any]) -> None:
    metadata = _obj_get(obj, "metadata") or {}
    subscription_id = _obj_get(obj, "id")
    user_id = metadata.get("user_id") or _user_by_subscription(cur, subscription_id)
    if not user_id:
        return
    # The subscription is already gone at Stripe — no cancel call needed.
    _revoke_to_free(cur, user_id, cancel_stripe=False)


def _handle_payment_failed(cur: Any, obj: dict[str, Any]) -> None:
    subscription_id = _obj_get(obj, "subscription")
    customer_id = _obj_get(obj, "customer")
    user_id = _user_by_subscription(cur, subscription_id) or _user_by_customer(
        cur, customer_id
    )
    if not user_id:
        return
    # PAY-R1-04 / PAY-R2-01: mark past_due for DISPLAY only. It no longer instantly
    # revokes access — ``has_active_paid_subscription`` treats past_due as entitled
    # during Stripe's dunning/retry window. Hard revoke happens on the terminal
    # customer.subscription.deleted, which downgrades to Free.
    cur.execute(
        'UPDATE "Subscription" SET "status"=\'past_due\',"updatedAt"=now() '
        'WHERE "userId"=%s',
        (user_id,),
    )


def _invoice_period(obj: Any) -> tuple[Optional[int], Optional[int]]:
    """(period_start, period_end) epoch seconds from an invoice — prefer the
    subscription line item's period, fall back to the invoice-level period."""
    lines = _obj_get(obj, "lines")
    if isinstance(lines, dict):
        data = lines.get("data")
    elif isinstance(lines, list):
        data = lines
    else:
        data = _obj_get(lines, "data")
    if data:
        period = _obj_get(data[0], "period")
        if period is not None:
            start = _obj_get(period, "start")
            end = _obj_get(period, "end")
            if start is not None or end is not None:
                return start, end
    return _obj_get(obj, "period_start"), _obj_get(obj, "period_end")


#: invoice.paid billing_reasons that represent a paid subscription period we
#: reconcile the run/spend quota against.
_RENEWAL_BILLING_REASONS = frozenset(
    {"subscription_cycle", "subscription_update", "subscription_create"}
)


def _handle_invoice_paid(cur: Any, obj: dict[str, Any]) -> None:
    """invoice.paid — align the run/spend quota to the PAID billing period and
    restore active status (PAY-R1-03 / PAY-R1-04 / PAY-R2-04).

    On a subscription renewal/creation invoice, reset ``runsUsed``/``spendUsedUsd``
    to 0 and set the quota period to the invoice's own period, so the quota rolls
    on the true Stripe billing anniversary (not the lazy calendar-month rollover),
    and a successful renewal after a failed charge restores ``active``. Idempotent
    via the StripeEvent dedupe (replays are a no-op before this runs).
    """
    if _obj_get(obj, "billing_reason") not in _RENEWAL_BILLING_REASONS:
        return  # not a subscription renewal/creation invoice — nothing to reset
    subscription_id = _obj_get(obj, "subscription")
    customer_id = _obj_get(obj, "customer")
    user_id = _user_by_subscription(cur, subscription_id) or _user_by_customer(
        cur, customer_id
    )
    if not user_id:
        return
    period_start, period_end = _invoice_period(obj)
    cur.execute(
        '''
        UPDATE "Subscription" SET
            "status"='active',
            "currentPeriodStart"=CASE WHEN %s IS NULL THEN "currentPeriodStart"
                                      ELSE to_timestamp(%s) END,
            "currentPeriodEnd"=CASE WHEN %s IS NULL THEN "currentPeriodEnd"
                                    ELSE to_timestamp(%s) END,
            "updatedAt"=now()
        WHERE "userId"=%s
        ''',
        (period_start, period_start, period_end, period_end, user_id),
    )
    cur.execute(
        '''
        UPDATE "UsageQuota" SET
            "runsUsed"=0,
            "spendUsedUsd"=0,
            "periodStart"=CASE WHEN %s IS NULL THEN "periodStart"
                               ELSE to_timestamp(%s) END,
            "periodEnd"=CASE WHEN %s IS NULL THEN "periodEnd"
                             ELSE to_timestamp(%s) END,
            "updatedAt"=now()
        WHERE "userId"=%s
        ''',
        (period_start, period_start, period_end, period_end, user_id),
    )


def _charge_fully_refunded(obj: Any) -> bool:
    """True when a charge object represents a FULL refund (partial refunds keep
    entitlement)."""
    if bool(_obj_get(obj, "refunded")):
        return True
    amount = _obj_get(obj, "amount")
    refunded = _obj_get(obj, "amount_refunded")
    try:
        return (
            amount is not None
            and refunded is not None
            and int(amount) > 0
            and int(refunded) >= int(amount)
        )
    except (TypeError, ValueError):
        return False


def _charge_customer_id(charge_id: Optional[str]) -> Optional[str]:
    """Resolve a charge's customer id via Stripe (dispute payloads carry a charge
    id but not always a customer id). Best-effort — returns None on any failure."""
    if not charge_id:
        return None
    try:
        return stripe_gateway.get_charge_customer(charge_id)
    except Exception:  # noqa: BLE001 — resolution is best-effort
        return None


def _handle_charge_refunded(cur: Any, obj: dict[str, Any]) -> None:
    """charge.refunded — on a FULL refund, revoke paid entitlement (downgrade to
    Free) and cancel the Stripe subscription so billing stops (PAY-R2-02). A
    partial refund leaves entitlement intact."""
    if not _charge_fully_refunded(obj):
        return
    customer_id = _obj_get(obj, "customer") or _charge_customer_id(
        _obj_get(obj, "id")
    )
    user_id = _user_by_customer(cur, customer_id)
    if not user_id:
        return
    _revoke_to_free(cur, user_id, cancel_stripe=True)


def _handle_dispute_created(cur: Any, obj: dict[str, Any]) -> None:
    """charge.dispute.created — a chargeback. Freeze paid access immediately
    (downgrade to Free) and cancel the subscription (PAY-R2-02)."""
    customer_id = _obj_get(obj, "customer") or _charge_customer_id(
        _obj_get(obj, "charge")
    )
    user_id = _user_by_customer(cur, customer_id)
    if not user_id:
        return
    _revoke_to_free(cur, user_id, cancel_stripe=True)


def _reset_quota(
    cur: Any, user_id: str, plan_id: str, runs_allowed: int, spend_cap: float
) -> None:
    cur.execute(
        '''
        INSERT INTO "UsageQuota" ("userId","planId","periodStart","periodEnd",
            "runsAllowed","runsUsed","spendCapUsd","spendUsedUsd","createdAt","updatedAt")
        VALUES (%s,%s, date_trunc('month',now()),
                date_trunc('month',now()) + interval '1 month', %s, 0, %s, 0, now(), now())
        ON CONFLICT ("userId") DO UPDATE SET
            "planId"=EXCLUDED."planId",
            "runsAllowed"=EXCLUDED."runsAllowed",
            "runsUsed"=0,
            "spendCapUsd"=EXCLUDED."spendCapUsd",
            "spendUsedUsd"=0,
            "periodStart"=EXCLUDED."periodStart",
            "periodEnd"=EXCLUDED."periodEnd",
            "updatedAt"=now()
        ''',
        (user_id, plan_id, runs_allowed, spend_cap),
    )


def _user_by_subscription(cur: Any, subscription_id: Optional[str]) -> Optional[str]:
    if not subscription_id:
        return None
    cur.execute(
        'SELECT "userId" FROM "Subscription" WHERE "stripeSubscriptionId"=%s',
        (subscription_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _user_by_customer(cur: Any, customer_id: Optional[str]) -> Optional[str]:
    if not customer_id:
        return None
    cur.execute(
        'SELECT "userId" FROM "Subscription" WHERE "stripeCustomerId"=%s',
        (customer_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# GET /billing/subscription (auth)
# ---------------------------------------------------------------------------


@router.get("/subscription")
def get_subscription(current_user: CurrentUser) -> dict[str, Any]:
    user_id = current_user["id"]
    ensure_user_billing(user_id)
    sub = SubscriptionRepository().get_by_user(user_id)
    quota = UsageQuotaRepository().get_by_user(user_id)
    plan = PlanRepository().get(sub["planId"]) if sub else None

    def _iso(value: Any) -> Optional[str]:
        return value.isoformat() if value is not None else None

    return {
        "plan": {
            "id": plan["id"],
            "name": plan["name"],
            "modelTier": plan["modelTier"],
        }
        if plan
        else None,
        "status": sub["status"] if sub else None,
        "interval": sub["billingInterval"] if sub else None,
        "currentPeriodEnd": _iso(sub["currentPeriodEnd"]) if sub else None,
        "cancelAtPeriodEnd": bool(sub["cancelAtPeriodEnd"]) if sub else False,
        "quota": {
            "runsUsed": int(quota["runsUsed"]),
            "runsAllowed": int(quota["runsAllowed"]),
            "spendUsedUsd": float(quota["spendUsedUsd"]),
            "spendCapUsd": float(quota["spendCapUsd"]),
            "periodEnd": _iso(quota["periodEnd"]),
        }
        if quota
        else None,
    }


# ---------------------------------------------------------------------------
# GET /billing/entitlement (auth) — subscription wall state (GAP-P6-PAYWALL)
# ---------------------------------------------------------------------------


@router.get("/entitlement")
def get_entitlement(current_user: CurrentUser) -> dict[str, Any]:
    """Whether the user may use Aether's actionable features.

    ``active_paid`` mirrors the backend gate (``status='active'`` AND
    ``planId != 'free'``); ``requiresSubscription`` reflects the operator flag so
    the dashboard shows its paywall IFF the gate is enforced. Lightweight, cached
    by no one — the frontend calls it on dashboard load.
    """
    user_id = current_user["id"]
    ensure_user_billing(user_id)
    repo = SubscriptionRepository()
    sub = repo.get_by_user(user_id)
    return {
        "active_paid": repo.has_active_paid_subscription(user_id),
        "plan": {"id": sub["planId"], "status": sub["status"]} if sub else None,
        "requiresSubscription": subscription_gate_enabled(),
    }


# ---------------------------------------------------------------------------
# POST /billing/portal (auth; 10/hr/user)
# ---------------------------------------------------------------------------


@router.post("/portal")
def create_portal(current_user: CurrentUser, request: Request) -> dict[str, str]:
    user_id = current_user["id"]
    limiter = getattr(request.app.state, "portal_rate_limiter", None)
    if limiter is not None and not limiter.allow(user_id):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many portal requests, retry later",
            headers={"Retry-After": str(limiter.retry_after(user_id))},
        )
    sub = SubscriptionRepository().get_by_user(user_id)
    customer_id = sub.get("stripeCustomerId") if sub else None
    if not customer_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No billing account yet — subscribe first"
        )
    if not stripe_gateway.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Billing is not configured on this deployment yet",
        )
    session = stripe_gateway.create_portal_session(customer_id=customer_id)
    return {"portalUrl": session["url"]}


# ---------------------------------------------------------------------------
# POST /billing/admin/refund (admin-only) — PAY-R3-04
# ---------------------------------------------------------------------------


async def _parse_refund_body(request: Request) -> dict[str, Any]:
    """Decode the refund body AFTER the AdminUser dependency has resolved, so a
    malformed/anonymous request is auth-gated (401/403) before any 422 — the same
    body-before-auth hazard the admin router's ``_parse_*_body`` guards against.
    """
    try:
        raw = await request.json()
    except Exception as exc:  # noqa: BLE001 — malformed / non-JSON body
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Request body is not valid JSON."
        ) from exc
    if not isinstance(raw, dict):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Request body must be an object."
        )
    return raw


@router.post("/admin/refund")
async def admin_refund(admin: AdminUser, request: Request) -> dict[str, Any]:
    """Refund a user's latest paid charge, then downgrade them to Free + cancel
    their subscription (PAY-R3-04). Admin-only; every call is audit-logged.

    Body: ``{"userId": <id>}`` OR ``{"email": <email>}``. Issues
    ``stripe.Refund.create(charge=<latest paid charge>)`` and returns the refund
    id/status.
    """
    body = await _parse_refund_body(request)
    target_user_id = (body.get("userId") or "").strip() or None
    email = (body.get("email") or "").strip() or None
    if not target_user_id and not email:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Provide a userId or an email."
        )
    if target_user_id is None and email is not None:
        user = UserRepository().get_by_email(email)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        target_user_id = user["id"]
    if not admin_repo.user_exists(target_user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if not stripe_gateway.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Billing is not configured on this deployment yet",
        )

    sub = SubscriptionRepository().get_by_user(target_user_id)
    customer_id = sub.get("stripeCustomerId") if sub else None
    if not customer_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This user has no billing account to refund"
        )

    charge_id = stripe_gateway.latest_paid_charge(customer_id)
    if not charge_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No paid charge found to refund for this user"
        )
    refund = stripe_gateway.create_refund(charge_id)

    # Downgrade to Free + cancel the subscription so no further invoices are raised.
    _ensure_billing_tables()
    admin_repo._ensure_admin_schema()  # guarantee AdminAuditLog.ip exists for the audit row
    with get_connection() as conn:
        with conn.cursor() as cur:
            _revoke_to_free(cur, target_user_id, cancel_stripe=True)
            admin_repo.write_audit(
                admin["id"],
                "billing_refund",
                target_type="user",
                target_id=target_user_id,
                detail={
                    "chargeId": charge_id,
                    "refundId": refund.get("id"),
                    "refundStatus": refund.get("status"),
                },
                cur=cur,
            )
        conn.commit()

    return {
        "userId": target_user_id,
        "refundId": refund.get("id"),
        "status": refund.get("status"),
        "chargeId": charge_id,
        "planId": "free",
    }
