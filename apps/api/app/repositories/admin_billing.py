"""ADMIN-2.0 billing data access — custom per-user pricing, the local billing
row, and the executive billing summary.

Owned deliberately by its OWN module (not ``repositories/billing.py``) so the
ADMIN-2.0 surface adds no edits to the billing spine every other feature depends
on. The additive columns below hang off the existing ``Subscription`` table via
lazy idempotent DDL (ADR-TR-1 — there is no migration runner); the documentary
mirror is ``apps/api/migrations/0029_admin2.sql``.

MONEY SEMANTICS
    * Subscription prices are AUD. LLM spend is USD and lives elsewhere
      (``AgentRun.costUsd``) — the two are never added together.
    * The operator is NOT GST-registered, so nothing here computes or claims a
      GST component.
    * Every figure the summary returns is derived from a real row. Where a
      number CANNOT be known from local data (a local row with no Stripe
      subscription behind it, an admin's exempt row), it is EXCLUDED from
      revenue and reported as its own count instead of being quietly folded in.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.db import ensure_user_lifecycle_columns, get_connection, rows_to_dicts
from app.repositories.billing import _ensure_billing_tables

#: Distinct advisory-lock id for the ADMIN-2.0 subscription columns.
_ADMIN_BILLING_LOCK = 7420260811

#: Subscription statuses that mean the customer is currently billable. Mirrors
#: ``SubscriptionRepository._ENTITLED_STATUSES`` — imported by value rather than
#: by reference so a change there is a deliberate decision here too.
BILLABLE_STATUSES: tuple[str, ...] = ("active", "trialing", "past_due")

#: The ADMIN-2.0 columns added to ``Subscription`` (all nullable / additive).
_CUSTOM_PRICE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("customPriceAud", "numeric"),
    ("customPriceInterval", "text"),
    ("customPriceStripeId", "text"),
    ("customPriceSetAt", "timestamptz"),
    ("customPriceSetBy", "text"),
)

_custom_price_columns_ready = False


def ensure_custom_price_columns() -> None:
    """Idempotently add the ADMIN-2.0 custom-price mirror to ``Subscription``.

    Stripe stays the source of truth for what the customer is actually charged;
    these columns are the LOCAL MIRROR of the negotiated amount an admin set, so
    the admin surface and the billing summary can show it without a Stripe round
    trip per row. NULL — the value for every pre-existing row — means "no custom
    price", i.e. the plan's catalogue price applies, which is exactly the
    pre-ADMIN-2.0 behaviour.

    Additive only: ``ADD COLUMN IF NOT EXISTS``, no DROP / rename / ALTER TYPE.
    A transaction-scoped advisory lock serialises concurrent first-hit callers;
    ``TRUNCATE`` never drops columns, so the process latch survives test
    teardown.
    """
    global _custom_price_columns_ready
    if _custom_price_columns_ready:
        return
    _ensure_billing_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Subscription'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = ANY(%s)",
                ([name for name, _type in _CUSTOM_PRICE_COLUMNS],),
            )
            row = cur.fetchone()
            if row and row[0] == len(_CUSTOM_PRICE_COLUMNS):
                _custom_price_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ADMIN_BILLING_LOCK,))
            for name, col_type in _CUSTOM_PRICE_COLUMNS:
                cur.execute(
                    f'ALTER TABLE "Subscription" ADD COLUMN IF NOT EXISTS "{name}"'
                    f" {col_type}"
                )
        conn.commit()
    _custom_price_columns_ready = True


_LOCAL_COLUMNS = (
    '"userId","planId","status","billingInterval","stripeCustomerId",'
    '"stripeSubscriptionId","currentPeriodStart","currentPeriodEnd",'
    '"cancelAtPeriodEnd","customPriceAud","customPriceInterval",'
    '"customPriceStripeId","customPriceSetAt","customPriceSetBy","updatedAt"'
)


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def local_billing_row(user_id: str, cur: Any = None) -> Optional[dict[str, Any]]:
    """The user's local ``Subscription`` row in the admin surface's wire shape."""

    def _run(c: Any) -> Optional[dict[str, Any]]:
        c.execute(
            f'SELECT {_LOCAL_COLUMNS} FROM "Subscription" WHERE "userId"=%s',
            (user_id,),
        )
        rows = rows_to_dicts(c)
        return rows[0] if rows else None

    if cur is not None:
        row = _run(cur)
    else:
        ensure_custom_price_columns()
        with get_connection() as conn:
            with conn.cursor() as c:
                row = _run(c)
    if row is None:
        return None
    custom = None
    if row.get("customPriceAud") is not None:
        custom = {
            "amountAud": round(float(row["customPriceAud"]), 2),
            "interval": row.get("customPriceInterval"),
            "stripePriceId": row.get("customPriceStripeId"),
            "setAt": _iso(row.get("customPriceSetAt")),
            "setBy": row.get("customPriceSetBy"),
        }
    return {
        "planId": row["planId"],
        "status": row["status"],
        "billingInterval": row["billingInterval"],
        "stripeCustomerId": row["stripeCustomerId"],
        "stripeSubscriptionId": row["stripeSubscriptionId"],
        "currentPeriodStart": _iso(row["currentPeriodStart"]),
        "currentPeriodEnd": _iso(row["currentPeriodEnd"]),
        "cancelAtPeriodEnd": bool(row["cancelAtPeriodEnd"]),
        "customPrice": custom,
        "updatedAt": _iso(row["updatedAt"]),
    }


def set_custom_price(
    cur: Any,
    user_id: str,
    *,
    amount_aud: float,
    interval: str,
    stripe_price_id: str,
    actor_user_id: str,
) -> None:
    """Mirror the negotiated amount locally, on the caller's cursor.

    ``billingInterval`` is re-stamped alongside it so the local row cannot claim
    a monthly cadence for a price Stripe now bills annually.
    """
    cur.execute(
        'UPDATE "Subscription" SET "customPriceAud"=%s,"customPriceInterval"=%s,'
        '"customPriceStripeId"=%s,"customPriceSetAt"=now(),"customPriceSetBy"=%s,'
        '"billingInterval"=%s,"updatedAt"=now() WHERE "userId"=%s',
        (amount_aud, interval, stripe_price_id, actor_user_id, interval, user_id),
    )


def clear_custom_price(cur: Any, user_id: str) -> None:
    """Drop the local custom-price mirror (used when the row is reconciled to
    Free — a negotiated amount for a subscription that no longer exists would be
    a figure with nothing behind it)."""
    cur.execute(
        'UPDATE "Subscription" SET "customPriceAud"=NULL,"customPriceInterval"=NULL,'
        '"customPriceStripeId"=NULL,"customPriceSetAt"=NULL,"customPriceSetBy"=NULL,'
        '"updatedAt"=now() WHERE "userId"=%s',
        (user_id,),
    )


def _monthly_equivalent_aud(row: dict[str, Any]) -> Optional[float]:
    """Monthly-equivalent AUD for one subscription row, or ``None`` if unknowable.

    A custom price wins over the catalogue (it IS what the customer is billed).
    An annual cadence is divided by 12 — an explicitly stated normalisation, not
    a hidden assumption, which is why the summary labels itself an estimate.
    """
    amount = row.get("customPriceAud")
    interval = row.get("customPriceInterval") or row.get("billingInterval") or "month"
    if amount is None:
        interval = row.get("billingInterval") or "month"
        if interval == "year":
            amount = row.get("priceAudAnnual")
            if amount is None:
                # No annual price on the catalogue row: fall back to the monthly
                # figure rather than inventing one, and say so via the caller's
                # ``estimate`` flag.
                amount = row.get("priceAudMonthly")
                interval = "month"
        else:
            amount = row.get("priceAudMonthly")
    if amount is None:
        return None
    value = float(amount)
    return round(value / 12.0, 2) if interval == "year" else round(value, 2)


def billing_summary() -> dict[str, Any]:
    """Platform revenue totals for the executive dashboard.

    HONESTY RULES (why the headline number is smaller than a naive query's):
      * only rows with a REAL ``stripeSubscriptionId`` count as revenue — a
        paid-looking local row with nothing behind it at Stripe is stale data,
        not money, and is reported separately as ``unbackedPaidRows``;
      * admin/owner rows are excluded — admins are exempt from plans
        (``entitlements.resolve`` is admin-wins), so their Subscription row is
        never a charge; the count is surfaced as ``excludedAdminRows``;
      * soft-deleted accounts are excluded and counted separately.

    ``estimate: true`` is not modesty: annual subscriptions are normalised to a
    monthly figure by dividing by 12, and the source is the local mirror rather
    than Stripe's own revenue reporting.
    """
    ensure_custom_price_columns()
    # This query names ``User."deletedAt"`` directly, so its lazy DDL must be
    # guaranteed here too — a cold worker whose FIRST admin request is the
    # dashboard summary would otherwise hit a missing column.
    ensure_user_lifecycle_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT s."userId", s."planId", s."status", s."billingInterval",'
                ' s."stripeSubscriptionId", s."customPriceAud", s."customPriceInterval",'
                ' p."name" AS "planName", p."priceAudMonthly", p."priceAudAnnual",'
                ' u."isAdmin", u."deletedAt"'
                ' FROM "Subscription" s'
                ' JOIN "User" u ON u."id" = s."userId"'
                ' LEFT JOIN "Plan" p ON p."id" = s."planId"'
            )
            rows = rows_to_dicts(cur)

    mrr = 0.0
    paid = 0
    custom_priced = 0
    unbacked = 0
    excluded_admin = 0
    excluded_deleted = 0
    by_status: dict[str, int] = {}
    by_plan: dict[str, dict[str, Any]] = {}

    for row in rows:
        is_admin = bool(row.get("isAdmin"))
        is_deleted = row.get("deletedAt") is not None
        status = row.get("status") or "unknown"
        if not is_admin and not is_deleted:
            by_status[status] = by_status.get(status, 0) + 1

        billable = status in BILLABLE_STATUSES and (row.get("planId") or "free") != "free"
        if not billable:
            continue
        if is_admin:
            excluded_admin += 1
            continue
        if is_deleted:
            excluded_deleted += 1
            continue
        if not row.get("stripeSubscriptionId"):
            unbacked += 1
            continue

        monthly = _monthly_equivalent_aud(row)
        if monthly is None:
            # A plan id with no catalogue row: countable as a subscriber, but its
            # revenue is genuinely unknown, so it contributes 0 rather than a guess.
            unbacked += 1
            continue
        paid += 1
        mrr += monthly
        if row.get("customPriceAud") is not None:
            custom_priced += 1
        plan_id = row["planId"]
        bucket = by_plan.setdefault(
            plan_id,
            {
                "planId": plan_id,
                "name": row.get("planName") or plan_id,
                "count": 0,
                "mrrAud": 0.0,
            },
        )
        bucket["count"] += 1
        bucket["mrrAud"] = round(bucket["mrrAud"] + monthly, 2)

    mrr = round(mrr, 2)
    return {
        "currency": "AUD",
        "asOf": datetime.now(tz=timezone.utc).isoformat(),
        "source": (
            "local Subscription rows joined to the Plan catalogue; only rows with "
            "a Stripe subscription id are counted as revenue"
        ),
        "estimate": True,
        "gstRegistered": False,
        "mrrAud": mrr,
        "arrAud": round(mrr * 12, 2),
        "paidSubscribers": paid,
        "customPricedCount": custom_priced,
        "unbackedPaidRows": unbacked,
        "excludedAdminRows": excluded_admin,
        "excludedDeletedRows": excluded_deleted,
        "byPlan": sorted(by_plan.values(), key=lambda b: -float(b["mrrAud"])),
        "byStatus": by_status,
    }
