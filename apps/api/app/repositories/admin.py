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
import sys
from typing import Any, Optional

from app.db import (
    ensure_admin_user_columns,
    ensure_user_profile_columns,
    get_connection,
    new_id,
    rows_to_dicts,
)
from app.repositories.billing import _ensure_billing_tables, ensure_user_billing
from app.security import verify_password

#: Distinct advisory-lock id for the admin schema (next free after billing's 719).
_ADMIN_LOCK = 7420240721

#: Setting keys (§15 settings).
SIGNUP_ENABLED_KEY = "signup_enabled"
EMAIL_VERIFICATION_KEY = "email_verification_enabled"

#: Seeded credential that must never hold admin privileges post-Cluster-F
#: (GAP-P6-SEC-001 / GATE-31). Kept in sync with ``scripts.seed_demo``.
_SEED_ADMIN_USERNAME = "admin"
_SEED_ADMIN_EMAIL = "admin@aether.local"

#: DENYLIST — passwords that must never protect an operator/admin account
#: (BLOCKER-001 / D1). These literals are *rejection patterns*, not
#: credentials: the only thing this module does with them is refuse a
#: configured ``AETHER_ADMIN_PASSWORD_HASH`` that verifies one of them.
#: ``admin123`` heads the list because it is the exact string that was found
#: live on production protecting the owner account with ``isAdmin=true``
#: (``uat/reports/evidence/gold-master-v2/phase0/BLOCKER-admin-overpermission-verification.md``).
_KNOWN_WEAK_ADMIN_PASSWORDS: tuple[str, ...] = (
    "admin123",
    "admin",
    "password",
    "changeme",
    "admin1234",
    "administrator",
    "password123",
    "letmein",
    "123456",
    "12345678",
    "qwerty",
    "secret",
    "aether",
    "aether123",
)

#: bcrypt hash prefixes (modular crypt format). A configured
#: ``AETHER_ADMIN_PASSWORD_HASH`` that does not start with one of these is not
#: a hash at all — most likely a PLAINTEXT password pasted into the wrong
#: variable, which would silently defeat the denylist check below (bcrypt
#: cannot verify anything against a non-hash, so every candidate would return
#: False and the weak credential would sail through).
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2x$", "$2y$")

#: Memoized denylist audit, keyed by the exact hash string so any change to
#: ``AETHER_ADMIN_PASSWORD_HASH`` re-runs the check. Rotation executes on every
#: app construction; without this, each boot would spend a full bcrypt verify
#: per denylist entry. Bounded (see ``_weak_password_matching``) so a process
#: that cycles many hashes cannot grow it without limit.
_WEAK_HASH_AUDIT_CACHE: dict[str, Optional[str]] = {}
_WEAK_HASH_AUDIT_CACHE_MAX = 64

_admin_ready = False


class AdminCredentialSecurityError(RuntimeError):
    """The configured operator-admin credential is unsafe to grant.

    Raised by :func:`apply_admin_rotation`. A distinct type (rather than a bare
    ``RuntimeError``) so ``app.main._lifespan`` can let it propagate and abort
    boot while still tolerating a transient DB failure — see the ``except``
    ladder there. Never catch this to "keep the app up": booting anyway would
    mean serving with a known-compromised administrator login.
    """


class AdminRotationConfigError(RuntimeError):
    """The §14.7 rotation is configured to demote and regrant the SAME row.

    Raised by :func:`apply_admin_rotation` when ``AETHER_ADMIN_EMAIL`` names the
    seeded demo admin identity. Step 1 demotes that identity and step 2 would
    immediately regrant it, so the two writes cancel out and the net effect is
    ``isAdmin=true`` for the seeded credential — the exact condition that made
    BLOCKER-001 exploitable. Fail loudly instead of silently netting to admin.
    """


def _is_production() -> bool:
    """Whether this process is running as production (``AETHER_ENV``).

    Mirrors ``app.main._guard_production_replay_mode`` verbatim so every
    fail-fast guard in the codebase agrees on what "production" means.
    """
    return os.environ.get("AETHER_ENV", "development").strip().lower() == "production"


def _weak_password_matching(pw_hash: str) -> Optional[str]:
    """The known-weak password ``pw_hash`` verifies, or ``None`` if it is safe.

    Pure read-only audit of an ALREADY-HASHED credential; it never hashes or
    stores anything. Returns the matched denylist entry so the caller can name
    it in the error (the operator needs to know *which* default they left in
    place; the value is already known to anyone reading this denylist).
    """
    if pw_hash in _WEAK_HASH_AUDIT_CACHE:
        return _WEAK_HASH_AUDIT_CACHE[pw_hash]
    match: Optional[str] = None
    for candidate in _KNOWN_WEAK_ADMIN_PASSWORDS:
        if verify_password(candidate, pw_hash):
            match = candidate
            break
    if len(_WEAK_HASH_AUDIT_CACHE) >= _WEAK_HASH_AUDIT_CACHE_MAX:
        _WEAK_HASH_AUDIT_CACHE.clear()
    _WEAK_HASH_AUDIT_CACHE[pw_hash] = match
    return match


def _guard_admin_credential_strength(email: str, pw_hash: str) -> None:
    """Fail fast if the configured operator admin uses a known-weak password.

    BLOCKER-001 / D1. ``apply_admin_rotation`` grants ``isAdmin=true`` — full
    access to every user's PII, spend caps and refunds — to whatever
    ``AETHER_ADMIN_PASSWORD_HASH`` the environment supplies. Production was
    found serving that grant behind a bcrypt hash of ``admin123``. This guard
    refuses the grant.

    Same idiom as ``app.main._guard_production_replay_mode``: a production
    deploy RAISES (the app must not come up behind a compromised admin login);
    outside production it prints a loud stderr warning and continues, so local
    dev and the test-suite stay usable. The secret itself is never logged —
    only the denylist entry it matched, which is public by construction.
    """
    if not pw_hash.startswith(_BCRYPT_PREFIXES):
        message = (
            "BLOCKER-001: AETHER_ADMIN_PASSWORD_HASH is not a bcrypt hash "
            f"(expected one of {', '.join(_BCRYPT_PREFIXES)}). It looks like a "
            "PLAINTEXT password was pasted into the hash variable — that would "
            "both break admin login and bypass the known-weak-password check. "
            "Generate it with: python -c \"from passlib.context import "
            "CryptContext; print(CryptContext(schemes=['bcrypt']).hash('<your "
            'password>\'))"'
        )
        if _is_production():
            raise AdminCredentialSecurityError(message)
        print(f"WARNING: {message}", file=sys.stderr)
        return

    weak = _weak_password_matching(pw_hash)
    if weak is None:
        return
    message = (
        "BLOCKER-001: refusing to grant admin privilege to "
        f"{email!r} — its AETHER_ADMIN_PASSWORD_HASH verifies the known-weak "
        f"password {weak!r}. An admin account can read every user's email "
        "address, change spend caps and issue real refunds; a guessable "
        "password on it is a full compromise of the platform. Rotate "
        "AETHER_ADMIN_PASSWORD_HASH to a bcrypt hash of a strong, unique "
        "password and restart."
    )
    if _is_production():
        raise AdminCredentialSecurityError(message)
    print(
        f"WARNING: {message} (AETHER_ENV is not 'production', so rotation "
        "continues — this WOULD abort a production boot.)",
        file=sys.stderr,
    )


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


def _cron_status() -> dict[str, Any]:
    """P1-9: honest scheduler status derived from the scout run ledger.

    The discovery scheduler is a systemd timer (``aether-discovery.timer``,
    fires every 30 min) whose runs land in ``AgentRun`` as ``agentName='scout'``.
    Rather than hardcoding "not configured", report from that ledger:
    - no scout runs at all      → not_configured
    - last run within 90 min    → ok (3 missed 30-min fires is the alarm line)
    - older than 90 min         → stale
    - ledger unreadable         → error
    """
    from datetime import datetime, timezone

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT MAX("startedAt") FROM "AgentRun" WHERE "agentName" = %s',
                    ("scout",),
                )
                row = cur.fetchone()
        last = row[0] if row else None
    except Exception:  # noqa: BLE001 — DB probe failure is itself the signal
        return {"status": "error", "detail": "Could not read the scheduler run ledger."}
    if last is None:
        return {
            "status": "not_configured",
            "detail": "No discovery (scout) runs recorded yet.",
        }
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age_min = int((datetime.now(timezone.utc) - last).total_seconds() // 60)
    if age_min <= 90:
        return {
            "status": "ok",
            "detail": (
                f"Discovery scheduler live — last scout run {age_min} min ago "
                "(systemd timer fires every 30 min)."
            ),
            "lastRunAt": last.isoformat(),
        }
    return {
        "status": "stale",
        "detail": (
            f"Discovery scheduler has not run in {age_min} min "
            "(expected every 30 min)."
        ),
        "lastRunAt": last.isoformat(),
    }


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
        "cron": _cron_status(),
        "providers": {"configuredTiers": configured_tiers, "count": len(configured_tiers)},
    }


# --------------------------------------------------------------------------- #
# §14.7 credential rotation (GATE-31 / SEC-001)
# --------------------------------------------------------------------------- #


def apply_admin_rotation() -> dict[str, Any]:
    """Apply §14.7 admin-credential rotation. Idempotent; safe on every load.

    0. VALIDATE the configured operator credential BEFORE touching any row, so
       a misconfigured deploy changes nothing (BLOCKER-001):
       * ``_guard_admin_credential_strength`` refuses a known-weak password;
       * ``AETHER_ADMIN_EMAIL`` may not name the seeded demo identity, because
         that would make steps 2 and 3 write to the SAME row.
    1. RECLAIM the reserved demo username ``admin`` from every row that is not
       the seeded demo account, so the bare identifier ``admin`` can never
       resolve to a real operator/owner account through
       ``UserRepository.get_by_username_or_email`` (BLOCKER-001 / D2).
    2. DEMOTE the seeded demo account (``admin@aether.local``) to
       ``isAdmin=false`` — the seeded demo credential must never hold
       privileges (GATE-31).
    3. If ``AETHER_ADMIN_EMAIL`` + ``AETHER_ADMIN_PASSWORD_HASH`` are set,
       create/update that user with ``isAdmin=true`` and the given (already
       hashed) password. Secrets come from ``os.environ`` only — never a
       plaintext literal in source.

    Steps 2 and 3 now select on mutually exclusive predicates (``email`` equal
    to the seed address vs. ``email`` equal to a configured address proven NOT
    to be the seed address), so the demote can never be silently undone by the
    regrant. The pre-BLOCKER-001 code demoted on ``lower(username)='admin' OR
    email='admin@aether.local'`` and regranted on ``email=<env>``; on production
    both predicates selected the same row and the pair netted out to
    ``isAdmin=true`` for a row reachable as ``admin``.

    Raises:
        AdminCredentialSecurityError: production boot with a known-weak or
            malformed ``AETHER_ADMIN_PASSWORD_HASH``.
        AdminRotationConfigError: ``AETHER_ADMIN_EMAIL`` names the seeded demo
            identity (demote/regrant self-cancel).
    """
    _ensure_admin_schema()

    email = (os.environ.get("AETHER_ADMIN_EMAIL") or "").strip()
    pw_hash = (os.environ.get("AETHER_ADMIN_PASSWORD_HASH") or "").strip()

    # --- step 0: validate before mutating anything -------------------------- #
    if email and pw_hash:
        _guard_admin_credential_strength(email, pw_hash)
    if email and email.lower() == _SEED_ADMIN_EMAIL:
        raise AdminRotationConfigError(
            "BLOCKER-001: AETHER_ADMIN_EMAIL is set to the seeded demo admin "
            f"identity ({_SEED_ADMIN_EMAIL!r}). The §14.7 rotation demotes that "
            "identity and would immediately regrant it, so the two writes "
            "cancel out and the seeded demo credential ends up with "
            "isAdmin=true. Point AETHER_ADMIN_EMAIL at a real operator mailbox "
            "that is not the demo account."
        )

    result: dict[str, Any] = {
        "reclaimed_usernames": [],
        "demoted_seed": False,
        "env_admin": None,
    }

    with get_connection() as conn:
        with conn.cursor() as cur:
            # --- step 1: reclaim the reserved demo username ----------------- #
            # ``admin`` is a documented demo identifier. Any OTHER account that
            # carries it is reachable by that identifier at login, which is how
            # the production owner account became loggable as `admin` (D2).
            # Clearing the alias is additive-safe: ``username`` is a nullable
            # UNIQUE column, the row keeps its own email identity, and login by
            # email is unaffected.
            cur.execute(
                'UPDATE "User" SET "username"=NULL,"updatedAt"=now() '
                'WHERE lower("username")=%s AND lower("email")<>%s '
                'RETURNING "id"',
                (_SEED_ADMIN_USERNAME, _SEED_ADMIN_EMAIL),
            )
            reclaimed = [row[0] for row in cur.fetchall()]
            result["reclaimed_usernames"] = reclaimed

            # --- step 2: demote the seeded demo account --------------------- #
            # Predicate is now EXACTLY the seed identity. After step 1 no other
            # row can still carry the ``admin`` username, so dropping the old
            # ``lower("username")=...`` disjunct loses no coverage while making
            # the mutual exclusion with step 3 provable from the SQL alone.
            cur.execute(
                'UPDATE "User" SET "isAdmin"=false,"updatedAt"=now() '
                'WHERE lower("email")=%s RETURNING "id"',
                (_SEED_ADMIN_EMAIL,),
            )
            demoted_ids = [row[0] for row in cur.fetchall()]
            result["demoted_seed"] = bool(demoted_ids)
        conn.commit()

    if reclaimed:
        print(
            "WARNING: §14.7 rotation reclaimed the reserved demo username "
            f"'{_SEED_ADMIN_USERNAME}' from {len(reclaimed)} non-demo "
            f"account(s) (ids: {', '.join(reclaimed)}). Those accounts can no "
            "longer be reached by that identifier at login and must sign in "
            "with their email address (BLOCKER-001 / D2).",
            file=sys.stderr,
        )

    # --- step 3: grant the configured operator admin ------------------------ #
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
        # Post-condition, defence in depth: the row we just granted must not be
        # a row we demoted a moment ago. Step 0 already makes that impossible
        # via the email predicates; if it ever happens anyway (e.g. a future
        # edit to either predicate) the net effect would be a silently
        # re-privileged demo account, so refuse rather than return success.
        if admin_id in demoted_ids:
            raise AdminRotationConfigError(
                "BLOCKER-001: §14.7 rotation demoted and then regranted the "
                f"same user row ({admin_id!r}) — the demote/regrant pair "
                "self-cancelled and left the seeded demo identity with "
                "isAdmin=true. Refusing to report success."
            )
        ensure_user_billing(admin_id)  # give the env admin a Free plan + quota
        result["env_admin"] = email
    return result
