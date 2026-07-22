"""Admin Tier 1 data access + §14.7 credential rotation (Cluster F).

Owns the additive admin schema NOT already provided by the billing spine:
- ``AdminSetting`` (key/value store for the signup + email-verification toggles),
- the ``ip`` column on ``AdminAuditLog`` (billing created the table; §15 wants the
  request IP recorded on each admin action).
The ``User.isAdmin`` / ``User.suspended`` columns live in ``app.db``
(``ensure_admin_user_columns``) alongside the other additive User columns.

There is no migration runner in this repo (ADR-TR-1), so ``_ensure_admin_schema``
is the ONLY mechanism that creates these in production; the documentary mirror
lives at ``apps/api/migrations/0023_admin.sql``. Additive only:
``CREATE TABLE IF NOT EXISTS`` / ``ADD COLUMN IF NOT EXISTS`` — never DROP /
ALTER TYPE / rename. No FK to ``User`` (shared-test-DB TRUNCATE safety).

Spend is genuine: per-user LLM spend is ``SUM("AgentRun"."costUsd")``. Amounts
are USD (LLM providers bill USD) — never AUD.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from app.db import (
    ensure_admin_user_columns,
    ensure_user_profile_columns,
    get_connection,
    new_id,
    rows_to_dicts,
)
from app.repositories.billing import _ensure_billing_tables, ensure_user_billing

#: Distinct advisory-lock id for the admin schema (next free after billing's 719).
_ADMIN_LOCK = 7420240721

#: Setting keys (§15 settings).
SIGNUP_ENABLED_KEY = "signup_enabled"
EMAIL_VERIFICATION_KEY = "email_verification_enabled"

#: Seeded credential that must never hold admin privileges post-Cluster-F
#: (GAP-P6-SEC-001 / GATE-31). Kept in sync with ``scripts.seed_demo``.
_SEED_ADMIN_USERNAME = "admin"
_SEED_ADMIN_EMAIL = "admin@aether.local"

_admin_ready = False


def _reset_admin_ready_for_tests() -> None:
    """Test hook: force ``_ensure_admin_schema`` to re-run."""
    global _admin_ready
    _admin_ready = False


def _ensure_admin_schema() -> None:
    """Create the additive admin schema on first use (ADR-TR-1).

    Idempotent + additive. Reuses the billing spine (``AdminAuditLog`` /
    ``UsageQuota`` already created there) and the User admin columns.
    """
    global _admin_ready
    if _admin_ready:
        return
    # Billing owns AdminAuditLog + UsageQuota; ensure them first.
    _ensure_billing_tables()
    ensure_admin_user_columns()
    # ``username`` (used by the §14.7 rotation demote) is an additive User column
    # from the other lazy-DDL family — ensure it so rotation never references a
    # missing column on the older test schema.
    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ADMIN_LOCK,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "AdminSetting" (
                    "key"       text PRIMARY KEY,
                    "value"     jsonb       NOT NULL,
                    "updatedAt" timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            # §15 wants the request IP on each admin action; AdminAuditLog was
            # created by the billing spine without it — add it additively.
            cur.execute(
                'ALTER TABLE "AdminAuditLog" ADD COLUMN IF NOT EXISTS "ip" text'
            )
        conn.commit()
    _admin_ready = True


# --------------------------------------------------------------------------- #
# Append-only audit log (ADMIN-003)
# --------------------------------------------------------------------------- #


def write_audit(
    actor_user_id: str,
    action: str,
    *,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    ip: Optional[str] = None,
    cur: Any = None,
) -> None:
    """Append one immutable ``AdminAuditLog`` row. Never updates/deletes.

    When ``cur`` is supplied the insert joins the caller's transaction (so the
    audit row commits atomically with the mutation it records); otherwise it
    opens its own short-lived connection.
    """

    def _run(c: Any) -> None:
        c.execute(
            'INSERT INTO "AdminAuditLog" '
            '("id","actorUserId","action","targetType","targetId","detailJson","ip") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                new_id(),
                actor_user_id,
                action,
                target_type,
                target_id,
                json.dumps(detail) if detail is not None else None,
                ip,
            ),
        )

    if cur is not None:
        _run(cur)
        return
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as c:
            _run(c)
        conn.commit()


def list_audit(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Paginated append-only audit log, newest first."""
    _ensure_admin_schema()
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "AdminAuditLog"')
            total = int(cur.fetchone()[0])
            cur.execute(
                'SELECT "id","actorUserId","action","targetType","targetId",'
                '"detailJson","ip","createdAt" FROM "AdminAuditLog" '
                'ORDER BY "createdAt" DESC, "id" DESC LIMIT %s OFFSET %s',
                (limit, offset),
            )
            rows = rows_to_dicts(cur)
    entries = [
        {
            "id": r["id"],
            "actorUserId": r["actorUserId"],
            "action": r["action"],
            "targetType": r["targetType"],
            "targetId": r["targetId"],
            "detail": r["detailJson"],
            "ip": r["ip"],
            "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
        }
        for r in rows
    ]
    return {"entries": entries, "total": total, "limit": limit, "offset": offset}


# --------------------------------------------------------------------------- #
# Settings (§15 signup / email-verification toggles)
# --------------------------------------------------------------------------- #


def get_setting(key: str, default: Any) -> Any:
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "value" FROM "AdminSetting" WHERE "key"=%s', (key,))
            row = cur.fetchone()
    if row is None:
        return default
    return row[0]


def set_setting(key: str, value: Any) -> None:
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "AdminSetting" ("key","value","updatedAt") '
                "VALUES (%s,%s,now()) "
                'ON CONFLICT ("key") DO UPDATE SET '
                '"value"=EXCLUDED."value","updatedAt"=now()',
                (key, json.dumps(value)),
            )
        conn.commit()


def signup_enabled() -> bool:
    """Public registration toggle (default ON when unset)."""
    return bool(get_setting(SIGNUP_ENABLED_KEY, True))


def get_settings() -> dict[str, bool]:
    return {
        "signupEnabled": bool(get_setting(SIGNUP_ENABLED_KEY, True)),
        "emailVerificationEnabled": bool(get_setting(EMAIL_VERIFICATION_KEY, False)),
    }


# --------------------------------------------------------------------------- #
# Users + spend (GATE-17). Spend == SUM("AgentRun"."costUsd") in USD.
# --------------------------------------------------------------------------- #

_SPEND_SUBQUERY = (
    'SELECT "userId", COALESCE(SUM("costUsd"),0) AS spend, count(*) AS runs '
    'FROM "AgentRun" GROUP BY "userId"'
)


def list_users(
    *,
    query: Optional[str] = None,
    plan: Optional[str] = None,
    suspended: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """List users with plan, signup date, last login and LLM spend (USD)."""
    _ensure_admin_schema()
    ensure_user_billing_backfill()
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    where: list[str] = []
    params: list[Any] = []
    if query:
        where.append('(u."email" ILIKE %s OR u."name" ILIKE %s)')
        params.extend([f"%{query}%", f"%{query}%"])
    if plan:
        where.append('s."planId" = %s')
        params.append(plan)
    if suspended is not None:
        where.append('u."suspended" = %s')
        params.append(suspended)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    # Shared FROM+JOIN so the COUNT and row-fetch queries can never drift out
    # of sync (ML-admin-001): the `plan` filter references the joined alias
    # `s."planId"` in where_sql, so both queries need the same "Subscription"
    # JOIN in scope regardless of which filters are active.
    from_sql = (
        ' FROM "User" u'
        ' LEFT JOIN "Subscription" s ON s."userId" = u."id"'
    )

    sql = f'''
        SELECT u."id", u."email", u."name", u."isAdmin", u."suspended",
               u."createdAt", u."lastLoginAt",
               COALESCE(s."planId", 'free') AS plan, s."status" AS "subStatus",
               COALESCE(sp.spend, 0) AS spend, COALESCE(sp.runs, 0) AS runs
        {from_sql}
        LEFT JOIN ({_SPEND_SUBQUERY}) sp ON sp."userId" = u."id"
        {where_sql}
        ORDER BY u."createdAt" DESC
        LIMIT %s OFFSET %s
    '''
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT count(*) {from_sql}{where_sql}', params)
            total = int(cur.fetchone()[0])
            cur.execute(sql, [*params, limit, offset])
            rows = rows_to_dicts(cur)
    users = [_user_row(r) for r in rows]
    return {"users": users, "total": total, "limit": limit, "offset": offset}


def _user_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "email": r["email"],
        "name": r.get("name"),
        "isAdmin": bool(r.get("isAdmin")),
        "suspended": bool(r.get("suspended")),
        "plan": r.get("plan"),
        "subStatus": r.get("subStatus"),
        "signupAt": r["createdAt"].isoformat() if r.get("createdAt") else None,
        "lastLoginAt": r["lastLoginAt"].isoformat() if r.get("lastLoginAt") else None,
        "spendUsd": round(float(r.get("spend") or 0), 6),
        "runCount": int(r.get("runs") or 0),
        "currency": "USD",
    }


def get_user_detail(user_id: str) -> Optional[dict[str, Any]]:
    """Full admin detail for one user: profile, subscription, quota, runs, spend."""
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT u."id", u."email", u."name", u."isAdmin", u."suspended",'
                ' u."createdAt", u."lastLoginAt",'
                ' COALESCE(s."planId", \'free\') AS plan, s."status" AS "subStatus",'
                ' COALESCE(sp.spend,0) AS spend, COALESCE(sp.runs,0) AS runs'
                ' FROM "User" u'
                ' LEFT JOIN "Subscription" s ON s."userId" = u."id"'
                f' LEFT JOIN ({_SPEND_SUBQUERY}) sp ON sp."userId" = u."id"'
                ' WHERE u."id" = %s',
                (user_id,),
            )
            rows = rows_to_dicts(cur)
            if not rows:
                return None
            r = rows[0]
            cur.execute(
                'SELECT "id","userId","planId","status","billingInterval",'
                '"stripeCustomerId","currentPeriodEnd","cancelAtPeriodEnd"'
                ' FROM "Subscription" WHERE "userId"=%s',
                (user_id,),
            )
            sub_rows = rows_to_dicts(cur)
            cur.execute(
                'SELECT "userId","planId","runsUsed","runsAllowed","spendUsedUsd",'
                '"spendCapUsd","periodEnd" FROM "UsageQuota" WHERE "userId"=%s',
                (user_id,),
            )
            quota_rows = rows_to_dicts(cur)
            cur.execute(
                'SELECT "id","agentName","status","costUsd","createdAt"'
                ' FROM "AgentRun" WHERE "userId"=%s'
                ' ORDER BY "createdAt" DESC LIMIT 25',
                (user_id,),
            )
            run_rows = rows_to_dicts(cur)

    def _iso(v: Any) -> Optional[str]:
        return v.isoformat() if v is not None else None

    sub = sub_rows[0] if sub_rows else None
    quota = quota_rows[0] if quota_rows else None
    return {
        "user": _user_row(r),
        "subscription": {
            "planId": sub["planId"],
            "status": sub["status"],
            "billingInterval": sub["billingInterval"],
            "currentPeriodEnd": _iso(sub["currentPeriodEnd"]),
            "cancelAtPeriodEnd": bool(sub["cancelAtPeriodEnd"]),
        }
        if sub
        else None,
        "quota": {
            "planId": quota["planId"],
            "runsUsed": int(quota["runsUsed"]),
            "runsAllowed": int(quota["runsAllowed"]),
            "spendUsedUsd": round(float(quota["spendUsedUsd"]), 6),
            "spendCapUsd": round(float(quota["spendCapUsd"]), 6),
            "periodEnd": _iso(quota["periodEnd"]),
            "currency": "USD",
        }
        if quota
        else None,
        "recentRuns": [
            {
                "id": run["id"],
                "agentName": run["agentName"],
                "status": run["status"],
                "costUsd": round(float(run["costUsd"] or 0), 6),
                "createdAt": _iso(run["createdAt"]),
            }
            for run in run_rows
        ],
        "spendUsd": round(float(r.get("spend") or 0), 6),
        "runCount": int(r.get("runs") or 0),
        "currency": "USD",
    }


def spend_overview() -> dict[str, Any]:
    """Platform-wide + per-user LLM spend in USD (SUM of AgentRun.costUsd)."""
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COALESCE(SUM("costUsd"),0) FROM "AgentRun"')
            total = float(cur.fetchone()[0] or 0)
            cur.execute(
                'SELECT r."userId", u."email", u."name",'
                ' COALESCE(SUM(r."costUsd"),0) AS spend, count(*) AS runs'
                ' FROM "AgentRun" r'
                ' LEFT JOIN "User" u ON u."id" = r."userId"'
                ' GROUP BY r."userId", u."email", u."name"'
                ' ORDER BY spend DESC',
            )
            rows = rows_to_dicts(cur)
    per_user = [
        {
            "userId": r["userId"],
            "email": r.get("email"),
            "name": r.get("name"),
            "spendUsd": round(float(r["spend"] or 0), 6),
            "runCount": int(r["runs"] or 0),
        }
        for r in rows
    ]
    return {"totalUsd": round(total, 6), "perUser": per_user, "currency": "USD"}


def set_spend_cap(user_id: str, cap_usd: float) -> float:
    """Set the per-user USD spend cap on the shared ``UsageQuota`` row.

    The billing reserve at ``agents._record_run`` reads ``spendCapUsd`` from the
    same row before every metered run, so an admin-set cap gates the LLM call.
    """
    _ensure_admin_schema()
    ensure_user_billing(user_id)  # guarantee a quota row exists first
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "UsageQuota" SET "spendCapUsd"=%s,"updatedAt"=now() '
                'WHERE "userId"=%s RETURNING "spendCapUsd"',
                (cap_usd, user_id),
            )
            row = cur.fetchone()
        conn.commit()
    return round(float(row[0]), 6) if row else float(cap_usd)


def user_exists(user_id: str) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM "User" WHERE "id"=%s', (user_id,))
            return cur.fetchone() is not None


def set_suspended(user_id: str, suspended: bool) -> bool:
    """Suspend/unsuspend a user (the auth dependency 403s a suspended user)."""
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "suspended"=%s,"updatedAt"=now() '
                'WHERE "id"=%s RETURNING "suspended"',
                (suspended, user_id),
            )
            row = cur.fetchone()
        conn.commit()
    return bool(row[0]) if row else suspended


def ensure_user_billing_backfill() -> None:
    """Guarantee every existing user has a Subscription/UsageQuota row so the
    admin list shows a plan for everyone (idempotent, additive)."""
    _ensure_billing_tables()  # runs the GATE-34 WHERE-NOT-EXISTS backfill


# --------------------------------------------------------------------------- #
# Health overview (§15)
# --------------------------------------------------------------------------- #


def health_overview() -> dict[str, Any]:
    """Genuine service / agent / LLM status snapshot (no fabricated metrics)."""
    _ensure_admin_schema()
    db_status = "ok"
    counts = {"total": 0, "completed": 0, "failed": 0, "running": 0, "queued": 0}
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "status", count(*) FROM "AgentRun" GROUP BY "status"'
                )
                for status_val, n in cur.fetchall():
                    counts[str(status_val)] = int(n)
                    counts["total"] += int(n)
    except Exception:  # noqa: BLE001 — DB probe failure is itself the signal
        db_status = "error"

    finished = counts["completed"] + counts["failed"]
    success_rate = round(counts["completed"] / finished, 4) if finished else None

    from app.services.llm_client import get_mode

    configured_tiers = [
        tier
        for tier, env in (
            ("REASONING", "AETHER_MODEL_REASONING"),
            ("STRUCTURED", "AETHER_MODEL_STRUCTURED"),
            ("FAST", "AETHER_MODEL_FAST"),
            ("LIGHT", "AETHER_MODEL_LIGHT"),
            ("HEAVY", "AETHER_MODEL_HEAVY"),
        )
        if os.environ.get(env)
    ]

    return {
        "services": {"api": "ok", "database": db_status},
        "agents": {
            "totalRuns": counts["total"],
            "succeeded": counts["completed"],
            "failed": counts["failed"],
            "running": counts["running"],
            "queued": counts["queued"],
            "successRate": success_rate,
        },
        "llm": {"mode": get_mode()},
        "cron": {
            "status": "not_configured",
            "detail": "No scheduled jobs are configured in this deployment.",
        },
        "providers": {"configuredTiers": configured_tiers, "count": len(configured_tiers)},
    }


# --------------------------------------------------------------------------- #
# §14.7 credential rotation (GATE-31 / SEC-001)
# --------------------------------------------------------------------------- #


def apply_admin_rotation() -> dict[str, Any]:
    """Apply §14.7 admin-credential rotation. Idempotent; safe on every load.

    1. ALWAYS demote the seeded ``admin`` / ``admin@aether.local`` account to
       ``isAdmin=false`` — the seeded ``admin/admin123`` credential must never
       hold privileges (GATE-31).
    2. If ``AETHER_ADMIN_EMAIL`` + ``AETHER_ADMIN_PASSWORD_HASH`` are set,
       create/update that user with ``isAdmin=true`` and the given (already
       hashed) password. Secrets come from ``os.environ`` only — never a
       plaintext literal in source.

    The env admin is applied AFTER the demotion so an operator who deliberately
    points ``AETHER_ADMIN_EMAIL`` at the seed address still gets an admin (their
    explicit choice); with no env configured the seed stays non-admin.
    """
    _ensure_admin_schema()
    result: dict[str, Any] = {"demoted_seed": False, "env_admin": None}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "isAdmin"=false,"updatedAt"=now() '
                'WHERE lower("username")=%s OR "email"=%s',
                (_SEED_ADMIN_USERNAME, _SEED_ADMIN_EMAIL),
            )
            result["demoted_seed"] = cur.rowcount > 0
        conn.commit()

    email = (os.environ.get("AETHER_ADMIN_EMAIL") or "").strip()
    pw_hash = (os.environ.get("AETHER_ADMIN_PASSWORD_HASH") or "").strip()
    if email and pw_hash:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "User" ("id","email","passwordHash","isAdmin",'
                    '"suspended","updatedAt") VALUES (%s,%s,%s,true,false,now()) '
                    'ON CONFLICT ("email") DO UPDATE SET '
                    '"passwordHash"=EXCLUDED."passwordHash","isAdmin"=true,'
                    '"suspended"=false,"updatedAt"=now() RETURNING "id"',
                    (new_id(), email, pw_hash),
                )
                admin_id = cur.fetchone()[0]
            conn.commit()
        ensure_user_billing(admin_id)  # give the env admin a Free plan + quota
        result["env_admin"] = email
    return result
