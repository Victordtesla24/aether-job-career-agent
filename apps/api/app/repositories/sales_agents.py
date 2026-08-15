"""ADMIN-2.0 BE-2 — sales agents, signup attribution and the commission report.

Its own module (like ``admin_billing``) so the growth surface adds no edits to
the billing spine or the user repository every other feature depends on.

WHAT THIS OWNS
    * ``SalesAgent`` — a human reseller/affiliate with a unique referral code and
      a commission percentage. Never hard-deleted: a code that has been handed
      out lives on in links and in the attribution history of every account it
      brought in, so "removing" an agent means ``status='inactive'`` (the code
      stops attributing) and nothing else.
    * ``User.referredBy`` — nullable ``SalesAgent.id`` stamped at signup when
      ``?ref=<code>`` matches an ACTIVE agent. NULL for every pre-existing row
      and for every signup without a code, which is why nothing about the
      existing registration path changes.
    * The commission report — attributed accounts, what they REALLY paid, and
      pct x that. It is a REPORT: it moves no money, writes no row, and creates
      no payout obligation in any system.

WHERE "REAL PAYMENTS" COME FROM
    There is no local Payment/Invoice table in this repo. The authoritative
    local record of money that actually arrived is ``StripeEvent`` — the
    signature-verified webhook payloads the billing spine persists inside the
    same transaction as their side effects (``routers/billing.py``). This module
    reads ``invoice.paid`` (money in) and ``charge.refunded`` (money back) from
    those payloads and NOTHING else: a plan price, a local Subscription row or a
    Stripe subscription id is a claim about what SHOULD be charged, not evidence
    that anyone paid.

MONEY SEMANTICS
    * Subscription money is AUD; ``amount_paid``/``amount_refunded`` arrive in
      MINOR units (cents). A payment in any other currency is reported under
      ``otherCurrencies`` in its own minor units and is NEVER converted into the
      AUD total — no FX rate is invented anywhere in this file.
    * ``charge.refunded`` carries a CUMULATIVE ``amount_refunded`` per charge, so
      refunds are reduced with MAX-per-charge, never summed (two partial refunds
      of one charge are one running total, not two refunds).
    * The operator is not GST-registered, so no GST component is computed.

Schema is additive only, applied by lazy idempotent DDL under a transaction-
scoped advisory lock (ADR-TR-1 — there is no migration runner). The documentary
mirror is ``apps/api/migrations/0030_sales_agents.sql``.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from app.db import ensure_user_lifecycle_columns, get_connection, new_id, rows_to_dicts
from app.repositories.admin_billing import BILLABLE_STATUSES
from app.repositories.billing import _ensure_billing_tables

#: Distinct advisory-lock id for the BE-2 growth schema (BE-1 used ...810/...811).
_SALES_AGENT_LOCK = 7420260812

#: The only two lifecycle states an agent has. There is deliberately no
#: 'deleted': see the module docstring.
SALES_AGENT_STATUSES: tuple[str, ...] = ("active", "inactive")

#: Referral codes are uppercase, URL-safe and unambiguous in a printed link:
#: A-Z, 0-9 and '-', 2..32 chars, never leading with '-'.
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")

#: Alphabet for a generated code — no 0/O or 1/I/L, because a human retypes
#: these from a business card.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

#: The platform's billing currency. Anything else is reported separately.
PLATFORM_CURRENCY = "aud"

#: Stripe event types that record real money movement.
_PAID_EVENT = "invoice.paid"
_REFUND_EVENT = "charge.refunded"

#: Below this many attributed accounts a CONVERSION RATE is not a number worth
#: reading (the totals themselves stay exact at any N — see ``commission_report``).
RATE_SAMPLE_FLOOR = 20

_sales_agent_schema_ready = False

_AGENT_COLUMNS = (
    '"id","name","email","referralCode","commissionPct","status","notes",'
    '"createdAt","updatedAt","createdBy"'
)


class InvalidReferralCodeError(ValueError):
    """The supplied referral code is not a legal code."""


class DuplicateReferralCodeError(Exception):
    """Another agent already owns this referral code."""


class SalesAgentNotFoundError(LookupError):
    """No agent with that id."""


# --------------------------------------------------------------------------- #
# Schema (lazy, idempotent, additive)
# --------------------------------------------------------------------------- #


def ensure_sales_agent_schema() -> None:
    """Create ``SalesAgent`` and add ``User.referredBy`` — idempotently.

    ``CREATE TABLE IF NOT EXISTS`` + ``ADD COLUMN IF NOT EXISTS``: no DROP, no
    rename, no ALTER TYPE, and no backfill UPDATE — ``referredBy`` is nullable
    with no default, so every pre-existing account reads correctly as "not
    referred", which is exactly what it is.

    No FK from ``SalesAgent`` to ``User`` and none from ``User.referredBy`` to
    ``SalesAgent``: the whole schema deliberately avoids cross-table FKs so the
    shared ``aether_test`` schema's ``TRUNCATE ... CASCADE`` cannot reach across
    them (the same rule the billing spine follows).

    A transaction-scoped advisory lock serialises concurrent first-hit callers
    so the DDL cannot race; ``TRUNCATE`` never drops tables or columns, so the
    process-wide latch survives the test suite's teardown.

    MUST be called by every path that reads or writes ``SalesAgent`` or
    ``User.referredBy``, before the statement that names them.
    """
    global _sales_agent_schema_ready
    if _sales_agent_schema_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path once both objects exist (production / warm test
            # schema): skips the ACCESS EXCLUSIVE ALTER on every later call.
            cur.execute(
                "SELECT"
                " (SELECT count(*) FROM information_schema.tables"
                "   WHERE table_name='SalesAgent'"
                "   AND table_schema = ANY(current_schemas(false))),"
                " (SELECT count(*) FROM information_schema.columns"
                "   WHERE table_name='User' AND column_name='referredBy'"
                "   AND table_schema = ANY(current_schemas(false)))"
            )
            row = cur.fetchone()
            if row and row[0] == 1 and row[1] == 1:
                _sales_agent_schema_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SALES_AGENT_LOCK,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "SalesAgent" (
                    "id"            text PRIMARY KEY,
                    "name"          text        NOT NULL,
                    "email"         text,
                    "referralCode"  text        NOT NULL,
                    "commissionPct" numeric     NOT NULL DEFAULT 0,
                    "status"        text        NOT NULL DEFAULT 'active',
                    "notes"         text,
                    "createdAt"     timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"     timestamptz NOT NULL DEFAULT now(),
                    "createdBy"     text
                )
                '''
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "SalesAgent_referralCode_key"'
                ' ON "SalesAgent" ("referralCode")'
            )
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "referredBy" text'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "User_referredBy_idx"'
                ' ON "User" ("referredBy")'
            )
        conn.commit()
    _sales_agent_schema_ready = True


# --------------------------------------------------------------------------- #
# Referral codes
# --------------------------------------------------------------------------- #


def normalize_referral_code(raw: Any) -> str:
    """Uppercase + trim a submitted code, or raise :class:`InvalidReferralCodeError`.

    Normalisation is what makes ``?ref=jane-2026`` and ``?ref=JANE-2026`` the
    same agent: the stored form is canonical, so lookup never has to guess.
    """
    if not isinstance(raw, str):
        raise InvalidReferralCodeError("referralCode must be a string.")
    code = raw.strip().upper()
    if not _CODE_RE.match(code):
        raise InvalidReferralCodeError(
            "referralCode must be 2-32 characters of A-Z, 0-9 or '-', and may "
            "not start with '-'."
        )
    return code


def _slugify_for_code(name: str) -> str:
    slug = re.sub(r"[^A-Z0-9]", "", (name or "").upper())[:8]
    return slug or "REF"


def generate_referral_code(name: str) -> str:
    """A random, unambiguous code seeded from the agent's name.

    ``secrets`` (never ``random``): a guessable referral code is an attribution
    someone else can claim.
    """
    suffix = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return normalize_referral_code(f"{_slugify_for_code(name)}-{suffix}")


def referral_code_taken(code: str, cur: Any = None) -> bool:
    def _run(c: Any) -> bool:
        c.execute('SELECT 1 FROM "SalesAgent" WHERE "referralCode"=%s', (code,))
        return c.fetchone() is not None

    if cur is not None:
        return _run(cur)
    ensure_sales_agent_schema()
    with get_connection() as conn:
        with conn.cursor() as c:
            return _run(c)


def allocate_referral_code(name: str, attempts: int = 5) -> str:
    """A generated code that is free RIGHT NOW.

    The unique index is still the authority — this only avoids handing the
    caller a code we already know is taken. A genuine race still surfaces as an
    honest duplicate error from the INSERT rather than a silent overwrite.
    """
    ensure_sales_agent_schema()
    for _ in range(max(1, attempts)):
        candidate = generate_referral_code(name)
        if not referral_code_taken(candidate):
            return candidate
    raise DuplicateReferralCodeError(
        "Could not allocate a free referral code; supply one explicitly."
    )


# --------------------------------------------------------------------------- #
# Wire shape
# --------------------------------------------------------------------------- #


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _agent_view(row: dict[str, Any], counts: Optional[dict[str, int]] = None) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "email": row.get("email"),
        "referralCode": row["referralCode"],
        "commissionPct": round(float(row["commissionPct"]), 4),
        "status": row["status"],
        "notes": row.get("notes"),
        "createdAt": _iso(row.get("createdAt")),
        "updatedAt": _iso(row.get("updatedAt")),
        "createdBy": row.get("createdBy"),
    }
    if counts is not None:
        view["attributedSignups"] = counts.get("signups", 0)
        view["convertedPaid"] = counts.get("converted", 0)
    return view


# --------------------------------------------------------------------------- #
# Attribution counts (shared with the executive dashboard)
# --------------------------------------------------------------------------- #

#: A referred account counts as CONVERTED under exactly the rule the billing
#: summary counts as revenue: a non-free plan, a billable status AND a real
#: Stripe subscription behind it. A local paid-looking row with nothing at
#: Stripe is stale data, not a conversion.
_CONVERTED_PREDICATE = (
    's."stripeSubscriptionId" IS NOT NULL'
    " AND COALESCE(s.\"planId\",'free') <> 'free'"
    ' AND s."status" = ANY(%s)'
)


def attribution_counts(cur: Any = None) -> dict[str, dict[str, int]]:
    """``{agentId: {"signups": n, "converted": n}}`` from real rows.

    Soft-deleted accounts still count: they really did sign up through the
    agent's link, and (if they paid) the money really arrived. Hiding them would
    silently shrink an agent's earned commission.
    """

    def _run(c: Any) -> dict[str, dict[str, int]]:
        c.execute(
            'SELECT u."referredBy" AS "agentId", count(*) AS signups,'
            f" count(*) FILTER (WHERE {_CONVERTED_PREDICATE}) AS converted"
            ' FROM "User" u'
            ' LEFT JOIN "Subscription" s ON s."userId" = u."id"'
            ' WHERE u."referredBy" IS NOT NULL'
            ' GROUP BY u."referredBy"',
            (list(BILLABLE_STATUSES),),
        )
        return {
            r["agentId"]: {
                "signups": int(r["signups"]),
                "converted": int(r["converted"]),
            }
            for r in rows_to_dicts(c)
        }

    if cur is not None:
        return _run(cur)
    ensure_sales_agent_schema()
    _ensure_billing_tables()
    with get_connection() as conn:
        with conn.cursor() as c:
            return _run(c)


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


def create_agent(
    cur: Any,
    *,
    name: str,
    email: Optional[str],
    referral_code: str,
    commission_pct: float,
    notes: Optional[str],
    actor_user_id: str,
) -> dict[str, Any]:
    """Insert one agent on the CALLER'S cursor, so the row and its
    ``AdminAuditLog`` entry commit together or not at all.

    ``ON CONFLICT DO NOTHING`` + an explicit raise keeps a duplicate code an
    honest 409 instead of a silently-ignored write.
    """
    cur.execute(
        f'INSERT INTO "SalesAgent" ("id","name","email","referralCode",'
        f'"commissionPct","status","notes","createdBy")'
        f" VALUES (%s,%s,%s,%s,%s,'active',%s,%s)"
        f' ON CONFLICT ("referralCode") DO NOTHING'
        f" RETURNING {_AGENT_COLUMNS}",
        (
            new_id(),
            name,
            email,
            referral_code,
            commission_pct,
            notes,
            actor_user_id,
        ),
    )
    rows = rows_to_dicts(cur)
    if not rows:
        raise DuplicateReferralCodeError(referral_code)
    return rows[0]


def get_agent(agent_id: str, cur: Any = None) -> Optional[dict[str, Any]]:
    def _run(c: Any) -> Optional[dict[str, Any]]:
        c.execute(
            f'SELECT {_AGENT_COLUMNS} FROM "SalesAgent" WHERE "id"=%s', (agent_id,)
        )
        rows = rows_to_dicts(c)
        return rows[0] if rows else None

    if cur is not None:
        return _run(cur)
    ensure_sales_agent_schema()
    with get_connection() as conn:
        with conn.cursor() as c:
            return _run(c)


#: Columns an admin may change after creation. ``referralCode`` is deliberately
#: absent: the code is already in the wild on distributed links, and rewriting
#: it would silently break every one of them.
_UPDATABLE = ("name", "email", "commissionPct", "status", "notes")


def update_agent(cur: Any, agent_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Apply a validated partial update on the caller's cursor.

    Raises :class:`SalesAgentNotFoundError` when the id does not exist, so the
    router can answer 404 rather than reporting a no-op as a success.

    Column names are interpolated into the UPDATE (psycopg2 cannot parameterise
    an identifier), so they are checked against :data:`_UPDATABLE` HERE and not
    only at the router: this function must be safe to call from anywhere, and a
    whitelist enforced at the single point of interpolation cannot be bypassed
    by a future caller that forgets to sanitise. Values stay parameterised.
    """
    unknown = sorted(set(changes) - set(_UPDATABLE))
    if unknown:
        raise ValueError(f"not an updatable SalesAgent column: {', '.join(unknown)}")
    if not changes:
        existing = get_agent(agent_id, cur=cur)
        if existing is None:
            raise SalesAgentNotFoundError(agent_id)
        return existing
    assignments = ", ".join(f'"{col}"=%s' for col in changes)
    params = [changes[col] for col in changes]
    params.append(agent_id)
    cur.execute(
        f'UPDATE "SalesAgent" SET {assignments}, "updatedAt"=now() WHERE "id"=%s'
        f" RETURNING {_AGENT_COLUMNS}",
        params,
    )
    rows = rows_to_dicts(cur)
    if not rows:
        raise SalesAgentNotFoundError(agent_id)
    return rows[0]


def list_agents(*, status: Optional[str] = None) -> dict[str, Any]:
    """All agents (optionally one status) with their REAL attributed counts."""
    ensure_sales_agent_schema()
    _ensure_billing_tables()
    where = ""
    params: list[Any] = []
    if status:
        where = ' WHERE "status"=%s'
        params.append(status)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_AGENT_COLUMNS} FROM "SalesAgent"{where}'
                ' ORDER BY "createdAt" DESC, "id" DESC',
                params,
            )
            rows = rows_to_dicts(cur)
            counts = attribution_counts(cur)
    agents = [_agent_view(r, counts.get(r["id"], {})) for r in rows]
    return {"agents": agents, "total": len(agents)}


# --------------------------------------------------------------------------- #
# Attribution at signup
# --------------------------------------------------------------------------- #


def attribute_signup(user_id: str, raw_code: Optional[str]) -> Optional[str]:
    """Stamp ``User.referredBy`` when ``raw_code`` matches an ACTIVE agent.

    Returns the agent id when attribution happened, ``None`` otherwise. The
    ``None`` cases are all legitimate, not failures: no code supplied, a
    malformed code, a code nobody owns, or an INACTIVE agent's code (which is
    what "deactivate" has to mean — the link stops earning).

    A falsy ``raw_code`` returns before touching the database at all, so a
    signup without ``?ref=`` performs exactly the same work it did before this
    feature existed.
    """
    if not raw_code or not str(raw_code).strip():
        return None
    try:
        code = normalize_referral_code(raw_code)
    except InvalidReferralCodeError:
        return None
    ensure_sales_agent_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id" FROM "SalesAgent" WHERE "referralCode"=%s'
                " AND \"status\"='active'",
                (code,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            agent_id = row[0]
            cur.execute(
                'UPDATE "User" SET "referredBy"=%s WHERE "id"=%s'
                ' AND "referredBy" IS NULL',
                (agent_id, user_id),
            )
            updated = cur.rowcount
        conn.commit()
    # First attribution wins: a later code cannot re-assign an account that has
    # already been credited to someone.
    return agent_id if updated else None


# --------------------------------------------------------------------------- #
# Real payment totals (from the locally-recorded Stripe webhook payloads)
# --------------------------------------------------------------------------- #


def _to_int(value: Any) -> Optional[int]:
    """Minor-unit parse that refuses to guess: a non-numeric payload field
    yields ``None`` (skipped + counted) rather than a fabricated 0 total."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class PaymentTotals:
    """Per-customer money that really moved, split by currency.

    ``gross``/``refunded`` are MINOR units keyed by lowercase currency code.
    Nothing here converts between currencies.
    """

    __slots__ = ("gross", "refunded", "counts", "_refund_by_charge")

    def __init__(self) -> None:
        self.gross: dict[str, int] = {}
        self.refunded: dict[str, int] = {}
        #: number of paid invoices, per currency (never mixed across currencies)
        self.counts: dict[str, int] = {}
        # charge id -> (currency, cumulative amount_refunded)
        self._refund_by_charge: dict[str, tuple[str, int]] = {}

    def add_payment(self, currency: str, amount_minor: int) -> None:
        self.gross[currency] = self.gross.get(currency, 0) + amount_minor
        self.counts[currency] = self.counts.get(currency, 0) + 1

    def observe_refund(self, charge_id: str, currency: str, cumulative_minor: int) -> None:
        """Record a charge's CUMULATIVE refunded amount (max wins)."""
        current = self._refund_by_charge.get(charge_id)
        if current is None or cumulative_minor > current[1]:
            self._refund_by_charge[charge_id] = (currency, cumulative_minor)

    def finalize(self) -> None:
        self.refunded = {}
        for currency, amount in self._refund_by_charge.values():
            self.refunded[currency] = self.refunded.get(currency, 0) + amount


def _payment_event_rows(
    cur: Any,
    *,
    customer_ids: Optional[list[str]] = None,
    since: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Raw money-movement rows from ``StripeEvent``, as plain text fields.

    Every numeric field is pulled as text and parsed in Python: a malformed
    payload must be skipped and counted, not crash the report with a SQL cast
    error nor be silently coerced to zero.
    """
    where = ['e."type" = ANY(%s)']
    params: list[Any] = [[_PAID_EVENT, _REFUND_EVENT]]
    if customer_ids is not None:
        if not customer_ids:
            return []
        where.append("e.\"payloadJson\"->'data'->'object'->>'customer' = ANY(%s)")
        params.append(customer_ids)
    if since is not None:
        where.append('e."receivedAt" >= %s')
        params.append(since)
    cur.execute(
        'SELECT e."type" AS "eventType",'
        " e.\"payloadJson\"->'data'->'object'->>'id'              AS \"objectId\","
        " e.\"payloadJson\"->'data'->'object'->>'customer'        AS \"customerId\","
        " e.\"payloadJson\"->'data'->'object'->>'currency'        AS \"currency\","
        " e.\"payloadJson\"->'data'->'object'->>'amount_paid'     AS \"amountPaid\","
        " e.\"payloadJson\"->'data'->'object'->>'amount_refunded' AS \"amountRefunded\""
        ' FROM "StripeEvent" e WHERE ' + " AND ".join(where),
        params,
    )
    return rows_to_dicts(cur)


def _accumulate(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, PaymentTotals], int, int]:
    """Fold raw event rows into per-customer totals.

    Returns ``(by_customer, unparsable_amounts, unattributed_refunds)`` — the
    two counters exist so a payload we could not read is DISCLOSED rather than
    quietly dropped out of the total.
    """
    by_customer: dict[str, PaymentTotals] = {}
    unparsable = 0
    unattributed_refunds = 0
    for row in rows:
        customer = row.get("customerId")
        currency = (row.get("currency") or "").strip().lower() or "unknown"
        if row["eventType"] == _PAID_EVENT:
            amount = _to_int(row.get("amountPaid"))
            # A zero-amount paid invoice (a 100%-off coupon, say) is a real
            # invoice but not money, so it is skipped WITHOUT being counted as
            # unreadable: only a field we genuinely could not parse increments
            # the disclosure counter.
            if amount is None or amount <= 0:
                if amount is None:
                    unparsable += 1
                continue
            if not customer:
                unparsable += 1
                continue
            by_customer.setdefault(customer, PaymentTotals()).add_payment(currency, amount)
        else:  # charge.refunded
            amount = _to_int(row.get("amountRefunded"))
            if amount is None or amount <= 0:
                if amount is None:
                    unparsable += 1
                continue
            if not customer:
                unattributed_refunds += 1
                continue
            charge_id = row.get("objectId") or f"{customer}:{amount}"
            by_customer.setdefault(customer, PaymentTotals()).observe_refund(
                charge_id, currency, amount
            )
    for totals in by_customer.values():
        totals.finalize()
    return by_customer, unparsable, unattributed_refunds


def _minor_to_major(minor: int) -> float:
    return round(minor / 100.0, 2)


def _other_bucket(
    other: dict[str, dict[str, int]], currency: str
) -> dict[str, int]:
    """The non-AUD bucket for ``currency``, in MINOR units.

    Foreign-currency money is reported in its own units and never converted:
    applying an FX rate we do not have would turn a real figure into a guess.
    """
    return other.setdefault(
        currency,
        {"grossMinorUnits": 0, "refundedMinorUnits": 0, "paymentCount": 0},
    )


# --------------------------------------------------------------------------- #
# Commission report
# --------------------------------------------------------------------------- #


def commission_report(agent_id: str) -> dict[str, Any]:
    """Attributed accounts, what they REALLY paid, and pct x that.

    REPORT-ONLY, and the payload says so (``reportOnly``/``payoutPerformed``):
    this function performs no write of any kind, creates no Stripe object, and
    schedules no payout. Paying an agent remains a deliberate act performed
    outside the product.

    The totals are EXACT at any N — a commission is arithmetic on real payments,
    not a sample. ``insufficientData`` therefore governs only the derived
    CONVERSION RATE, which is meaningless below a handful of accounts and is
    reported as ``null`` there instead of as a precise-looking percentage.
    """
    ensure_sales_agent_schema()
    ensure_user_lifecycle_columns()
    _ensure_billing_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            agent_row = get_agent(agent_id, cur=cur)
            if agent_row is None:
                raise SalesAgentNotFoundError(agent_id)
            cur.execute(
                'SELECT u."id",u."email",u."name",u."createdAt",u."deletedAt",'
                ' s."planId",s."status" AS "subStatus",s."stripeCustomerId",'
                ' s."stripeSubscriptionId"'
                ' FROM "User" u'
                ' LEFT JOIN "Subscription" s ON s."userId" = u."id"'
                ' WHERE u."referredBy" = %s'
                ' ORDER BY u."createdAt" ASC, u."id" ASC',
                (agent_id,),
            )
            users = rows_to_dicts(cur)
            customer_ids = [
                u["stripeCustomerId"] for u in users if u.get("stripeCustomerId")
            ]
            event_rows = _payment_event_rows(cur, customer_ids=customer_ids)
            cur.execute(
                'SELECT count(*) FROM "StripeEvent" e WHERE e."type"=%s'
                " AND e.\"payloadJson\"->'data'->'object'->>'customer' IS NULL",
                (_REFUND_EVENT,),
            )
            orphan_refunds = int(cur.fetchone()[0])

    by_customer, unparsable, unattributed = _accumulate(event_rows)

    commission_pct = float(agent_row["commissionPct"])
    gross_minor = 0
    refunded_minor = 0
    payment_count = 0
    paying_users = 0
    converted_users = 0
    other: dict[str, dict[str, int]] = {}
    entries: list[dict[str, Any]] = []
    # One Stripe customer's payments belong to ONE account here. Two local rows
    # pointing at the same stripeCustomerId is a real (if rare) data state, and
    # crediting the same money to both would inflate the commission owed. The
    # first account by signup date keeps the payments; the later one is reported
    # with A$0 and ``sharesStripeCustomerWith`` so the collision is visible
    # rather than netted out in silence.
    claimed_customers: dict[str, str] = {}
    shared_customer_accounts = 0

    for user in users:
        customer_id = user.get("stripeCustomerId") or ""
        shares_with: Optional[str] = None
        if customer_id:
            owner = claimed_customers.setdefault(customer_id, user["id"])
            if owner != user["id"]:
                shares_with = owner
                shared_customer_accounts += 1
        totals = None if shares_with else by_customer.get(customer_id)
        user_gross = totals.gross.get(PLATFORM_CURRENCY, 0) if totals else 0
        user_refunded = totals.refunded.get(PLATFORM_CURRENCY, 0) if totals else 0
        user_payments = totals.counts.get(PLATFORM_CURRENCY, 0) if totals else 0
        if totals:
            for currency, amount in totals.gross.items():
                if currency == PLATFORM_CURRENCY:
                    continue
                bucket = _other_bucket(other, currency)
                bucket["grossMinorUnits"] += amount
                bucket["paymentCount"] += totals.counts.get(currency, 0)
            for currency, amount in totals.refunded.items():
                if currency == PLATFORM_CURRENCY:
                    continue
                _other_bucket(other, currency)["refundedMinorUnits"] += amount

        converted = bool(
            user.get("stripeSubscriptionId")
            and (user.get("planId") or "free") != "free"
            and (user.get("subStatus") in BILLABLE_STATUSES)
        )
        if converted:
            converted_users += 1
        if user_gross > 0:
            paying_users += 1

        gross_minor += user_gross
        refunded_minor += user_refunded
        payment_count += user_payments

        entries.append(
            {
                "userId": user["id"],
                "email": user["email"],
                "name": user.get("name"),
                "signedUpAt": _iso(user.get("createdAt")),
                "deleted": user.get("deletedAt") is not None,
                "planId": user.get("planId"),
                "subStatus": user.get("subStatus"),
                "stripeCustomerId": user.get("stripeCustomerId"),
                "sharesStripeCustomerWith": shares_with,
                "converted": converted,
                "paymentCount": user_payments,
                "grossPaidAud": _minor_to_major(user_gross),
                "refundedAud": _minor_to_major(user_refunded),
                "netPaidAud": _minor_to_major(user_gross - user_refunded),
            }
        )

    net_minor = gross_minor - refunded_minor
    attributed = len(users)
    rate_known = attributed >= RATE_SAMPLE_FLOOR
    return {
        "agent": _agent_view(
            agent_row, {"signups": attributed, "converted": converted_users}
        ),
        "asOf": datetime.now(tz=timezone.utc).isoformat(),
        "currency": "AUD",
        "commissionPct": round(commission_pct, 4),
        # This endpoint is a REPORT. It writes nothing and pays nobody.
        "reportOnly": True,
        "payoutPerformed": False,
        "gstRegistered": False,
        "source": (
            "signature-verified Stripe webhook payloads recorded locally in "
            "StripeEvent (invoice.paid for money in, charge.refunded for money "
            "back); plan prices and local Subscription rows are NOT used as "
            "evidence of payment"
        ),
        "attributedUsers": entries,
        "totals": {
            "attributedUsers": attributed,
            "convertedUsers": converted_users,
            "payingUsers": paying_users,
            "paymentCount": payment_count,
            "grossPaidAud": _minor_to_major(gross_minor),
            "refundedAud": _minor_to_major(refunded_minor),
            "netPaidAud": _minor_to_major(net_minor),
            "commissionAud": round(
                _minor_to_major(net_minor) * commission_pct / 100.0, 2
            ),
        },
        "otherCurrencies": other,
        "conversionRate": (
            round(converted_users / attributed, 4) if rate_known and attributed else None
        ),
        "sampleSize": attributed,
        "rateSampleFloor": RATE_SAMPLE_FLOOR,
        # True while there are too few attributed accounts for the CONVERSION
        # RATE to mean anything. The money figures above stay exact regardless.
        "insufficientData": not rate_known,
        # Disclosure counters — a record this report could not read is SHOWN,
        # never quietly dropped out of the totals above.
        "unparsablePaymentEvents": unparsable + unattributed,
        "refundEventsWithNoCustomer": orphan_refunds,
        "sharedStripeCustomerAccounts": shared_customer_accounts,
    }
