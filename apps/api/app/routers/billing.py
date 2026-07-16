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
from app.middleware.auth import CurrentUser
from app.repositories.billing import (
    PlanRepository,
    SubscriptionRepository,
    UsageQuotaRepository,
    _ensure_billing_tables,
    ensure_user_billing,
    gst_breakdown,
)
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
) -> dict[str, str]:
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
        return  # unknown subscription — nothing to sync (still acked idempotently)
    new_status = _obj_get(obj, "status") or "active"
    cancel_at_end = bool(_obj_get(obj, "cancel_at_period_end"))
    period_start = _obj_get(obj, "current_period_start")
    period_end = _obj_get(obj, "current_period_end")
    plan_id = metadata.get("plan_id")

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
            'UPDATE "Subscription" SET "planId"=%s,"updatedAt"=now() WHERE "userId"=%s',
            (plan_id, user_id),
        )
        cur.execute(
            'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=%s,"spendCapUsd"=%s,'
            '"updatedAt"=now() WHERE "userId"=%s',
            (plan_id, runs_allowed, spend_cap, user_id),
        )


def _handle_subscription_deleted(cur: Any, obj: dict[str, Any]) -> None:
    metadata = _obj_get(obj, "metadata") or {}
    subscription_id = _obj_get(obj, "id")
    user_id = metadata.get("user_id") or _user_by_subscription(cur, subscription_id)
    if not user_id:
        return
    runs_allowed, spend_cap = _plan_limits(cur, "free")
    cur.execute(
        'UPDATE "Subscription" SET "planId"=\'free\',"status"=\'canceled\','
        '"stripeSubscriptionId"=NULL,"billingInterval"=NULL,"cancelAtPeriodEnd"=false,'
        '"updatedAt"=now() WHERE "userId"=%s',
        (user_id,),
    )
    _reset_quota(cur, user_id, "free", runs_allowed, spend_cap)


def _handle_payment_failed(cur: Any, obj: dict[str, Any]) -> None:
    subscription_id = _obj_get(obj, "subscription")
    customer_id = _obj_get(obj, "customer")
    user_id = _user_by_subscription(cur, subscription_id) or _user_by_customer(
        cur, customer_id
    )
    if not user_id:
        return
    cur.execute(
        'UPDATE "Subscription" SET "status"=\'past_due\',"updatedAt"=now() '
        'WHERE "userId"=%s',
        (user_id,),
    )


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
