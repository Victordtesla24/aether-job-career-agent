"""THE single server-side entitlement resolver (ADMIN-FULL).

USER MANDATE (2026-08-14): admins/owners have NO subscriptions or plans of their
own and NO restrictions anywhere in the app. ORCHESTRATOR SCOPE RULING (binding):
"restrictions" means quotas, run limits, spend caps, paywalls / entitlement
gates, tier & feature gates, and per-user rate limits (only DoS-sane transport
limits survive). It explicitly does NOT mean the honesty machinery (fabrication
guard, transmission proof, completeness verification), auth itself, or AUDIT —
those stay universal and are untouched by this module.

WHY ONE MODULE. Before this, the enforcement decision was re-derived at five
separate seams (``agents._require_active_subscription``, the sync reserve in
``agents._record_run``, the enqueue reserve in ``agents._enqueue_single_agent``,
``board_sweep._spend_cap_stop``, the billing rate limiters). Five copies of a
privilege rule is five chances to disagree, and a frontend-only exemption is not
an exemption at all. :func:`resolve` is now the ONLY place that decides, and
every one of those seams calls it.

PRECEDENCE — highest first:

1. ``isAdmin`` on the User row -> unlimited, entitled, source ``admin``.
2. An ``UserEntitlementOverride`` row an admin wrote -> ``comp`` / ``tier``
   (entitled at the named plan's limits) or ``unlimited``.
3. The user's real subscription (Stripe truth via
   ``SubscriptionRepository.has_active_paid_subscription``) -> source ``plan``.

BILLING INVARIANT (sacred). An override is an IN-APP entitlement grant. It never
touches the ``Subscription`` row, never calls Stripe, and never rewrites
``active_paid`` — which keeps reporting the real billing truth. So a paying
customer's Stripe state can never be silently contradicted: the override is a
separate, visible fact (``overrideActive``) that the admin UI renders and the
audit log records. The only thing an override writes is the ``UsageQuota``
CEILING (``runsAllowed`` / ``spendCapUsd``), which is the product's own
allowance, not a billing record — and :func:`reapply_override_limits` re-asserts
it after a Stripe webhook re-syncs the quota, so the grant can never silently
evaporate.

SCHEMA is additive + lazily created (ADR-TR-1): ``UserEntitlementOverride`` is a
new table created with ``CREATE TABLE IF NOT EXISTS`` under a transaction-scoped
advisory lock, exactly like the other lazy-DDL families. Nothing is dropped,
renamed or backfilled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.db import ensure_admin_user_columns, get_connection, new_id, rows_to_dicts

#: Override kinds an admin may grant.
OVERRIDE_COMP = "comp"
OVERRIDE_TIER = "tier"
OVERRIDE_UNLIMITED = "unlimited"
OVERRIDE_KINDS: tuple[str, ...] = (OVERRIDE_COMP, OVERRIDE_TIER, OVERRIDE_UNLIMITED)

#: Where an entitlement verdict came from (reported to the admin UI + the user's
#: own /billing surfaces so nothing is ever a silent grant).
SOURCE_ADMIN = "admin"
SOURCE_OVERRIDE = "override"
SOURCE_PLAN = "plan"

#: Advisory-lock key for this module's lazy DDL (distinct from every other
#: ``ensure_*`` family's key so the first-hit callers cannot deadlock).
_ENTITLEMENT_LOCK = 7420240814

_schema_ready = False


def _reset_schema_for_tests() -> None:
    """Test hook: force :func:`ensure_entitlement_schema` to re-run."""
    global _schema_ready
    _schema_ready = False


def ensure_entitlement_schema() -> None:
    """Idempotently create the additive ``UserEntitlementOverride`` table.

    ``CREATE TABLE IF NOT EXISTS`` under a transaction-scoped advisory lock —
    additive only, safe to run on every cold path, and it survives the test
    suite's ``TRUNCATE`` teardown (which never drops tables).
    """
    global _schema_ready
    if _schema_ready:
        return
    ensure_admin_user_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ENTITLEMENT_LOCK,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "UserEntitlementOverride" (
                    "id"        text PRIMARY KEY,
                    "userId"    text        NOT NULL UNIQUE,
                    "kind"      text        NOT NULL,
                    "planId"    text,
                    "note"      text,
                    "setBy"     text        NOT NULL,
                    "createdAt" timestamptz NOT NULL DEFAULT now(),
                    "updatedAt" timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
        conn.commit()
    _schema_ready = True


@dataclass(frozen=True)
class Entitlement:
    """The one verdict every enforcement point reads.

    ``unlimited`` — no run quota, no USD ceiling, no paywall, no per-user rate
    limit. ``entitled`` — passes the subscription paywall (a superset of
    ``unlimited``). ``active_paid`` — the REAL billing truth, never rewritten by
    an override, so the admin UI can show a grant sitting visibly on top of it.
    """

    user_id: str
    is_admin: bool
    unlimited: bool
    entitled: bool
    source: str
    plan_id: Optional[str]
    override_active: bool
    override_kind: Optional[str]
    override_plan_id: Optional[str]
    override_note: Optional[str]
    override_set_by: Optional[str]
    override_set_at: Optional[str]
    active_paid: bool

    def as_dict(self) -> dict[str, Any]:
        """Wire shape shared by /billing/* and /admin/users/* (camelCase)."""
        return {
            "unlimited": self.unlimited,
            "entitled": self.entitled,
            "source": self.source,
            "isAdmin": self.is_admin,
            "planId": self.plan_id,
            "activePaid": self.active_paid,
            "overrideActive": self.override_active,
            "overrideKind": self.override_kind,
            "overridePlanId": self.override_plan_id,
            "overrideNote": self.override_note,
            "overrideSetBy": self.override_set_by,
            "overrideSetAt": self.override_set_at,
        }


def is_admin(user_id: str) -> bool:
    """Whether this user id carries the platform admin flag.

    Read from the ``User`` row on every call — deliberately NOT cached and
    deliberately NOT taken from the JWT: a demotion must take effect on the very
    next request, exactly like ``get_current_user`` already re-reads ``isAdmin``.
    """
    if not user_id:
        return False
    ensure_admin_user_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COALESCE("isAdmin", false) FROM "User" WHERE "id"=%s',
                (user_id,),
            )
            row = cur.fetchone()
    return bool(row[0]) if row else False


def get_override(user_id: str) -> Optional[dict[str, Any]]:
    """The admin-written entitlement override for this user, or None."""
    if not user_id:
        return None
    ensure_entitlement_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "userId","kind","planId","note","setBy","updatedAt"'
                ' FROM "UserEntitlementOverride" WHERE "userId"=%s',
                (user_id,),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def _plan_limits(plan_id: str) -> Optional[tuple[int, float]]:
    """``(runsPerMonth, spendCapUsdMonthly)`` for a plan id, or None if unknown."""
    from app.repositories.billing import _ensure_billing_tables

    _ensure_billing_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "runsPerMonth","spendCapUsdMonthly" FROM "Plan" WHERE "id"=%s',
                (plan_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return int(row[0]), float(row[1])


def _apply_override_quota(user_id: str, kind: str, plan_id: Optional[str], cur: Any = None) -> None:
    """Point the user's ``UsageQuota`` CEILING at the override's plan.

    Only the allowance columns (``runsAllowed`` / ``spendCapUsd``) move, and only
    for ``comp``/``tier``. ``planId`` on the quota row is left alone so the
    billing side keeps reporting what the user actually pays for; the override is
    reported separately. Usage counters are never reset — an override grants
    headroom, it does not launder consumption.
    """
    if kind == OVERRIDE_UNLIMITED or not plan_id:
        return
    limits = _plan_limits(plan_id)
    if limits is None:
        return
    runs_allowed, spend_cap = limits

    def _run(c: Any) -> None:
        c.execute(
            'UPDATE "UsageQuota" SET "runsAllowed"=%s,"spendCapUsd"=%s,'
            '"updatedAt"=now() WHERE "userId"=%s',
            (runs_allowed, spend_cap, user_id),
        )

    if cur is not None:
        _run(cur)
        return
    from app.repositories.billing import ensure_user_billing

    ensure_user_billing(user_id)
    with get_connection() as conn:
        with conn.cursor() as c:
            _run(c)
        conn.commit()


def reapply_override_limits(user_id: str, cur: Any = None) -> None:
    """Re-assert an active override's ceiling after a plan/quota re-sync.

    A Stripe webhook (``_sync_plan_and_quota`` / ``_reset_quota``) rewrites
    ``UsageQuota.runsAllowed``/``spendCapUsd`` from the paid plan. Without this,
    an admin grant would silently evaporate on the next billing event — the exact
    class of silent divergence this work exists to remove. A user with no
    override is a no-op.
    """
    override = get_override(user_id)
    if override is None:
        return
    _apply_override_quota(user_id, str(override["kind"]), override.get("planId"), cur=cur)


def set_override(
    user_id: str,
    *,
    kind: str,
    plan_id: Optional[str] = None,
    note: Optional[str] = None,
    actor_id: str,
) -> dict[str, Any]:
    """Write (or replace) the admin entitlement override for ``user_id``.

    Raises ``ValueError`` for an unknown ``kind`` or a ``comp``/``tier`` grant
    without a real plan id — never a silent partial grant.
    """
    if kind not in OVERRIDE_KINDS:
        raise ValueError(f"unknown entitlement override kind: {kind!r}")
    if kind in (OVERRIDE_COMP, OVERRIDE_TIER):
        if not plan_id:
            raise ValueError(f"a {kind} override requires a planId")
        if _plan_limits(plan_id) is None:
            raise ValueError(f"unknown plan id: {plan_id!r}")
    else:
        plan_id = None
    ensure_entitlement_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "UserEntitlementOverride"'
                ' ("id","userId","kind","planId","note","setBy")'
                " VALUES (%s,%s,%s,%s,%s,%s)"
                ' ON CONFLICT ("userId") DO UPDATE SET'
                ' "kind"=EXCLUDED."kind","planId"=EXCLUDED."planId",'
                ' "note"=EXCLUDED."note","setBy"=EXCLUDED."setBy",'
                ' "updatedAt"=now()',
                (new_id(), user_id, kind, plan_id, note, actor_id),
            )
        conn.commit()
    _apply_override_quota(user_id, kind, plan_id)
    return dict(get_override(user_id) or {})


def clear_override(user_id: str) -> bool:
    """Remove the override. True when a row was actually removed.

    The quota ceiling is deliberately NOT rolled back here: silently dropping a
    user's allowance mid-period would be a restriction applied without a billing
    event. The next Stripe sync (or an explicit admin spend-cap edit) sets it,
    and the admin UI shows the live numbers either way.
    """
    ensure_entitlement_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM "UserEntitlementOverride" WHERE "userId"=%s', (user_id,)
            )
            removed = cur.rowcount > 0
        conn.commit()
    return removed


def resolve(user_id: str) -> Entitlement:
    """THE entitlement verdict for ``user_id``. Every enforcement point calls this."""
    from app.repositories.billing import SubscriptionRepository

    admin = is_admin(user_id)
    override = get_override(user_id)
    # Deliberately NOT wrapped in a try/except. If the billing store cannot be
    # read, "unknown" is not "unpaid": swallowing the error here would paywall a
    # paying customer (402) and blame them for an outage on our side. The error
    # propagates so the caller fails honestly — ``get_connection`` already turns
    # a saturated pool into a 503, which is the truthful answer.
    active_paid = SubscriptionRepository().has_active_paid_subscription(user_id)

    override_kind = str(override["kind"]) if override else None
    override_plan = (override.get("planId") if override else None) or None
    set_at = override.get("updatedAt") if override else None

    if admin:
        source = SOURCE_ADMIN
    elif override_kind is not None:
        source = SOURCE_OVERRIDE
    else:
        source = SOURCE_PLAN

    unlimited = admin or override_kind == OVERRIDE_UNLIMITED
    entitled = unlimited or override_kind in (OVERRIDE_COMP, OVERRIDE_TIER) or active_paid

    if admin:
        plan_id = None  # admins/owners hold no plan of their own
    elif override_plan:
        plan_id = override_plan
    else:
        plan_id = None
        sub = SubscriptionRepository().get_by_user(user_id)
        if sub:
            plan_id = sub["planId"]

    return Entitlement(
        user_id=user_id,
        is_admin=admin,
        unlimited=unlimited,
        entitled=bool(entitled),
        source=source,
        plan_id=plan_id,
        override_active=override_kind is not None,
        override_kind=override_kind,
        override_plan_id=override_plan,
        override_note=(override.get("note") if override else None),
        override_set_by=(override.get("setBy") if override else None),
        override_set_at=set_at.isoformat() if set_at is not None else None,
        active_paid=bool(active_paid),
    )


def unlimited(user_id: str) -> bool:
    """Fast path for the hot reserve seams: is this user exempt from every
    quota / cap / rate limit? Same rule as :func:`resolve`, one query cheaper on
    the common (non-override) path.
    """
    if is_admin(user_id):
        return True
    override = get_override(user_id)
    return bool(override and override["kind"] == OVERRIDE_UNLIMITED)
