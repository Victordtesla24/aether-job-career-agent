"""Billing spine — Plan / Subscription / UsageQuota / StripeEvent / AdminAuditLog
(GAP-P6-BILL-001 / BILL-002, Cluster D).

This module owns ALL the additive DDL for the subscription/billing spine. There
is no migration runner in this repo (ADR-TR-1), so ``_ensure_billing_tables()``
is the ONLY mechanism that actually creates these tables in production; the
documentary mirror lives at ``apps/api/migrations/0022_billing.sql`` (record
only). Every read/write path calls ``_ensure_billing_tables()`` first, mirroring
``user_provider_credential._ensure_user_agent_tables``.

Design authority: ``docs/subscription/billing-architecture.md`` +
``docs/subscription/BILLING-ARCH-APPROVAL.md``. The **ratified** tiers
(ADR-P6-PRICING) are seeded here — NOT the design's proposed quotas:

    Free    A$0    / —      / 5   runs   / spend cap USD $1
    Starter A$19   / A$179  / 30  runs   / spend cap USD $5
    Pro     A$39   / A$359  / 100 runs   / spend cap USD $15
    Power   A$69   / A$649  / 300 runs   / spend cap USD $40

No billing table carries an FK to ``User`` — so the shared test-suite's
``TRUNCATE "User"`` never trips over them. ``userId`` columns are ``text`` to
match ``User.id`` (cuid). First-hit creation is serialized by ONE
transaction-scoped advisory lock (``7420240719``) so concurrent
``CREATE TABLE IF NOT EXISTS`` cannot race on Postgres's ``pg_type`` index.

Additive only: ``CREATE TABLE IF NOT EXISTS`` / ``ADD COLUMN IF NOT EXISTS`` /
``CREATE UNIQUE INDEX IF NOT EXISTS`` — never DROP / ALTER TYPE / rename.
"""
from __future__ import annotations

from typing import Any, Optional

from app.db import get_connection, rows_to_dicts

#: Distinct advisory-lock id for the billing spine (next free after 718).
_BILLING_LOCK = 7420240719

#: The RATIFIED tier catalog (ADR-P6-PRICING). Tuple order:
#: (id, name, priceAudMonthly, priceAudAnnual, runsPerMonth, modelTier,
#:  spendCapUsdMonthly, sortOrder).
RATIFIED_PLANS: tuple[tuple[Any, ...], ...] = (
    ("free", "Free", 0, None, 5, "light", 1.00, 0),
    ("starter", "Starter", 19, 179, 30, "standard", 5.00, 1),
    ("pro", "Pro", 39, 359, 100, "advanced", 15.00, 2),
    ("power", "Power", 69, 649, 300, "premium", 40.00, 3),
)

#: Guard so the DDL + seed + backfill only run once per worker process.
_billing_ready = False


def _reset_billing_ready_for_tests() -> None:
    """Test hook: force the DDL/seed/backfill to re-run (used after seeding
    raw users to verify the GATE-34 backfill)."""
    global _billing_ready
    _billing_ready = False


def gst_breakdown(total: Any) -> dict[str, float]:
    """Split a GST-inclusive AUD total into ``{total, gst, net}``.

    GST is embedded 10% in a GST-inclusive price, so ``gst = round(total/11, 2)``
    and ``net = total - gst`` (§1.1 of the billing architecture / §14.2 of the
    prompt). The frontend never does tax math; this is the single source.
    """
    value = float(total)
    gst = round(value / 11, 2)
    net = round(value - gst, 2)
    return {"total": round(value, 2), "gst": gst, "net": net}


def _ensure_billing_tables() -> None:
    """Create/seed/backfill the billing spine on first use (ADR-TR-1).

    Runs inside a single advisory-locked transaction: DDL -> Plan seed ->
    GATE-34 backfill (all existing users -> Free Subscription + initialized
    UsageQuota). Idempotent and additive; safe on every worker start.
    """
    global _billing_ready
    if _billing_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_BILLING_LOCK,))

            # ---- Plan (catalog) ----
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "Plan" (
                    "id"                   text PRIMARY KEY,
                    "name"                 text        NOT NULL,
                    "priceAudMonthly"      numeric     NOT NULL DEFAULT 0,
                    "priceAudAnnual"       numeric,
                    "runsPerMonth"         integer     NOT NULL,
                    "modelTier"            text        NOT NULL
                        CHECK ("modelTier" IN ('light','standard','advanced','premium')),
                    "spendCapUsdMonthly"   numeric     NOT NULL,
                    "stripeProductId"      text,
                    "stripePriceIdMonthly" text,
                    "stripePriceIdAnnual"  text,
                    "active"               boolean     NOT NULL DEFAULT true,
                    "sortOrder"            integer     NOT NULL DEFAULT 0,
                    "createdAt"            timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"            timestamptz NOT NULL DEFAULT now()
                )
                '''
            )

            # ---- Subscription (per user) ----
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "Subscription" (
                    "id"                   text PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    "userId"               text        NOT NULL,
                    "planId"               text        NOT NULL,
                    "status"               text        NOT NULL DEFAULT 'active'
                        CHECK ("status" IN ('active','trialing','past_due','canceled',
                                            'incomplete','incomplete_expired','unpaid','paused')),
                    "billingInterval"      text
                        CHECK ("billingInterval" IN ('month','year')),
                    "stripeCustomerId"     text,
                    "stripeSubscriptionId" text,
                    "currentPeriodStart"   timestamptz,
                    "currentPeriodEnd"     timestamptz,
                    "cancelAtPeriodEnd"    boolean     NOT NULL DEFAULT false,
                    "createdAt"            timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"            timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "Subscription_userId_key" '
                'ON "Subscription" ("userId")'
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "Subscription_stripeSubscriptionId_key" '
                'ON "Subscription" ("stripeSubscriptionId") '
                'WHERE "stripeSubscriptionId" IS NOT NULL'
            )

            # ---- UsageQuota (per user, rolling) ----
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "UsageQuota" (
                    "id"            text PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    "userId"        text        NOT NULL,
                    "planId"        text        NOT NULL,
                    "periodStart"   timestamptz NOT NULL,
                    "periodEnd"     timestamptz NOT NULL,
                    "runsAllowed"   integer     NOT NULL,
                    "runsUsed"      integer     NOT NULL DEFAULT 0,
                    "spendCapUsd"   numeric     NOT NULL,
                    "spendUsedUsd"  numeric     NOT NULL DEFAULT 0,
                    "createdAt"     timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"     timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "UsageQuota_userId_key" '
                'ON "UsageQuota" ("userId")'
            )

            # ---- StripeEvent (transaction-safe idempotency) ----
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "StripeEvent" (
                    "id"          text PRIMARY KEY,
                    "type"        text        NOT NULL,
                    "status"      text        NOT NULL DEFAULT 'processing'
                        CHECK ("status" IN ('processing','processed','failed','ignored')),
                    "payloadJson" jsonb,
                    "receivedAt"  timestamptz NOT NULL DEFAULT now(),
                    "processedAt" timestamptz
                )
                '''
            )

            # ---- AdminAuditLog (Cluster F sink; ships now) ----
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "AdminAuditLog" (
                    "id"          text PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    "actorUserId" text        NOT NULL,
                    "action"      text        NOT NULL,
                    "targetType"  text,
                    "targetId"    text,
                    "detailJson"  jsonb,
                    "createdAt"   timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "AdminAuditLog_actor_idx" '
                'ON "AdminAuditLog" ("actorUserId")'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "AdminAuditLog_target_idx" '
                'ON "AdminAuditLog" ("targetType","targetId")'
            )

            # ---- Plan seed (idempotent; price/quota refreshed, Stripe ids kept) ----
            cur.executemany(
                '''
                INSERT INTO "Plan" ("id","name","priceAudMonthly","priceAudAnnual",
                                    "runsPerMonth","modelTier","spendCapUsdMonthly","sortOrder")
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT ("id") DO UPDATE SET
                    "name"=EXCLUDED."name",
                    "priceAudMonthly"=EXCLUDED."priceAudMonthly",
                    "priceAudAnnual"=EXCLUDED."priceAudAnnual",
                    "runsPerMonth"=EXCLUDED."runsPerMonth",
                    "modelTier"=EXCLUDED."modelTier",
                    "spendCapUsdMonthly"=EXCLUDED."spendCapUsdMonthly",
                    "sortOrder"=EXCLUDED."sortOrder",
                    "updatedAt"=now()
                ''',
                list(RATIFIED_PLANS),
            )

            # ---- GATE-34 backfill (idempotent, additive, WHERE NOT EXISTS) ----
            cur.execute(
                '''
                INSERT INTO "Subscription" ("userId","planId","status","billingInterval",
                                            "createdAt","updatedAt")
                SELECT u."id", 'free', 'active', NULL, now(), now()
                FROM "User" u
                WHERE NOT EXISTS (
                    SELECT 1 FROM "Subscription" s WHERE s."userId" = u."id"
                )
                '''
            )
            cur.execute(
                '''
                INSERT INTO "UsageQuota" ("userId","planId","periodStart","periodEnd",
                                         "runsAllowed","runsUsed","spendCapUsd",
                                         "spendUsedUsd","createdAt","updatedAt")
                SELECT u."id", 'free',
                       date_trunc('month', now()),
                       date_trunc('month', now()) + interval '1 month',
                       (SELECT "runsPerMonth"       FROM "Plan" WHERE "id"='free'),
                       0,
                       (SELECT "spendCapUsdMonthly" FROM "Plan" WHERE "id"='free'),
                       0, now(), now()
                FROM "User" u
                WHERE NOT EXISTS (
                    SELECT 1 FROM "UsageQuota" q WHERE q."userId" = u."id"
                )
                '''
            )
        conn.commit()
    _billing_ready = True


def ensure_user_billing(user_id: str, cur: Any = None) -> None:
    """Idempotently guarantee a Free Subscription + UsageQuota for one user.

    The process-level GATE-34 backfill only sees users that existed when
    ``_ensure_billing_tables()`` first ran; a user registered later (very common
    in tests, and possible in prod between worker restarts) would have no quota
    row. This per-user, on-demand backfill closes that gap before any reserve.
    Additive ``WHERE NOT EXISTS`` inserts — never resets an existing row.
    """
    _ensure_billing_tables()
    _free_runs, _free_cap = _free_plan_limits()

    def _run(c: Any) -> None:
        c.execute(
            '''
            INSERT INTO "Subscription" ("userId","planId","status","billingInterval",
                                        "createdAt","updatedAt")
            SELECT %s, 'free', 'active', NULL, now(), now()
            WHERE NOT EXISTS (SELECT 1 FROM "Subscription" WHERE "userId" = %s)
            ''',
            (user_id, user_id),
        )
        c.execute(
            '''
            INSERT INTO "UsageQuota" ("userId","planId","periodStart","periodEnd",
                                     "runsAllowed","runsUsed","spendCapUsd",
                                     "spendUsedUsd","createdAt","updatedAt")
            SELECT %s, 'free',
                   date_trunc('month', now()),
                   date_trunc('month', now()) + interval '1 month',
                   %s, 0, %s, 0, now(), now()
            WHERE NOT EXISTS (SELECT 1 FROM "UsageQuota" WHERE "userId" = %s)
            ''',
            (user_id, _free_runs, _free_cap, user_id),
        )

    if cur is not None:
        _run(cur)
        return
    with get_connection() as conn:
        with conn.cursor() as c:
            _run(c)
        conn.commit()


def _free_plan_limits() -> tuple[int, float]:
    for pid, _n, _m, _a, runs, _t, cap, _s in RATIFIED_PLANS:
        if pid == "free":
            return int(runs), float(cap)
    return 5, 1.00


class PlanRepository:
    """Read the plan catalog + human-populated Stripe id writes."""

    _COLS = (
        '"id","name","priceAudMonthly","priceAudAnnual","runsPerMonth","modelTier",'
        '"spendCapUsdMonthly","stripeProductId","stripePriceIdMonthly",'
        '"stripePriceIdAnnual","active","sortOrder"'
    )

    def list_active(self) -> list[dict[str, Any]]:
        _ensure_billing_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {self._COLS} FROM "Plan" WHERE "active" = true '
                    'ORDER BY "sortOrder"'
                )
                return rows_to_dicts(cur)

    def get(self, plan_id: str) -> Optional[dict[str, Any]]:
        _ensure_billing_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {self._COLS} FROM "Plan" WHERE "id" = %s', (plan_id,)
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def set_stripe_ids(
        self,
        plan_id: str,
        *,
        product_id: Optional[str] = None,
        price_monthly: Optional[str] = None,
        price_annual: Optional[str] = None,
    ) -> None:
        """Persist Stripe ids for a plan (COALESCE — a NULL arg never clears an
        existing id). Used by the one-time admin/human write after Stripe setup."""
        _ensure_billing_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "Plan" SET '
                    '"stripeProductId"=COALESCE(%s,"stripeProductId"),'
                    '"stripePriceIdMonthly"=COALESCE(%s,"stripePriceIdMonthly"),'
                    '"stripePriceIdAnnual"=COALESCE(%s,"stripePriceIdAnnual"),'
                    '"updatedAt"=now() WHERE "id"=%s',
                    (product_id, price_monthly, price_annual, plan_id),
                )
            conn.commit()


class SubscriptionRepository:
    """Per-user subscription row (one live row per user; Free by default)."""

    _COLS = (
        '"id","userId","planId","status","billingInterval","stripeCustomerId",'
        '"stripeSubscriptionId","currentPeriodStart","currentPeriodEnd",'
        '"cancelAtPeriodEnd","createdAt","updatedAt"'
    )

    def get_by_user(self, user_id: str) -> Optional[dict[str, Any]]:
        _ensure_billing_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {self._COLS} FROM "Subscription" WHERE "userId" = %s',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def set_customer_id(self, user_id: str, customer_id: str) -> None:
        """Attach a Stripe customer id to the user's Subscription (create the
        Free row first if absent) — idempotent, never resets the plan."""
        ensure_user_billing(user_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "Subscription" SET "stripeCustomerId"=%s,"updatedAt"=now() '
                    'WHERE "userId"=%s',
                    (customer_id, user_id),
                )
            conn.commit()


class UsageQuotaRepository:
    """Per-user rolling run/spend quota (atomic reserve-before-run)."""

    _COLS = (
        '"id","userId","planId","periodStart","periodEnd","runsAllowed",'
        '"runsUsed","spendCapUsd","spendUsedUsd","createdAt","updatedAt"'
    )

    def get_by_user(self, user_id: str) -> Optional[dict[str, Any]]:
        _ensure_billing_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {self._COLS} FROM "UsageQuota" WHERE "userId" = %s',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def reserve(self, user_id: str) -> Optional[dict[str, Any]]:
        """Atomically reserve ONE run against the run quota (rolling over an
        expired period). Returns the post-reserve quota row, or ``None`` when the
        run cap is exhausted. The USD spend cap is checked by the caller against
        the returned ``spendUsedUsd``/``spendCapUsd`` (§4.1).

        The single conditional UPDATE makes check-and-increment atomic — no
        read-modify-write race across concurrent runs.
        """
        ensure_user_billing(user_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    UPDATE "UsageQuota" SET
                      "periodStart"  = CASE WHEN now() >= "periodEnd"
                          THEN date_trunc('month', now()) ELSE "periodStart" END,
                      "periodEnd"    = CASE WHEN now() >= "periodEnd"
                          THEN date_trunc('month', now()) + interval '1 month'
                          ELSE "periodEnd" END,
                      "runsUsed"     = CASE WHEN now() >= "periodEnd"
                          THEN 1 ELSE "runsUsed" + 1 END,
                      "spendUsedUsd" = CASE WHEN now() >= "periodEnd"
                          THEN 0 ELSE "spendUsedUsd" END,
                      "updatedAt"    = now()
                    WHERE "userId" = %s
                      AND ( now() >= "periodEnd" OR "runsUsed" < "runsAllowed" )
                    RETURNING "runsUsed","runsAllowed","spendUsedUsd","spendCapUsd",
                              "periodEnd","planId"
                    ''',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def record_spend(self, user_id: str, cost_usd: float) -> None:
        """Accumulate realized USD spend after a completed (200) run."""
        _ensure_billing_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "UsageQuota" SET "spendUsedUsd"="spendUsedUsd"+%s,'
                    '"updatedAt"=now() WHERE "userId"=%s',
                    (cost_usd, user_id),
                )
            conn.commit()

    def refund_run(self, user_id: str) -> None:
        """Refund a reserved run that produced no billable output (failure /
        spend-cap block). ``GREATEST(...,0)`` keeps the counter non-negative."""
        _ensure_billing_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "UsageQuota" SET "runsUsed"=GREATEST("runsUsed"-1,0),'
                    '"updatedAt"=now() WHERE "userId"=%s',
                    (user_id,),
                )
            conn.commit()
