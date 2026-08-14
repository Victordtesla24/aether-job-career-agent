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
import logging
import os
import sys
from typing import Any, Optional

from psycopg2.errors import UniqueViolation

from app.db import (
    ensure_admin_user_columns,
    ensure_user_profile_columns,
    get_connection,
    new_id,
    rows_to_dicts,
)
from app.repositories.billing import _ensure_billing_tables, ensure_user_billing
from app.security import verify_password

logger = logging.getLogger(__name__)

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

#: DEGRADED-ADMIN-CREDENTIAL state (BLOCKER-001 restart safety). Set by
#: :func:`apply_admin_rotation` on every run: the full operator-facing
#: explanation when the configured ``AETHER_ADMIN_PASSWORD_HASH`` is unsafe,
#: ``None`` when it is fine. Recomputed from scratch each rotation, so it can
#: never latch on stale state. It is read by:
#:   * :func:`weak_operator_credential_refused` — fail-CLOSED at auth, and
#:   * :func:`health_overview` — so an operator sees the condition in the UI.
#: NOTE (§0.5): this message is written to the process log on every boot
#: while the credential stays unrotated, so it deliberately never names the
#: matched denylist entry — on a degraded deploy that value IS the live
#: password (see ``_audit_admin_credential``). It still must never be
#: returned over HTTP regardless — see ``_DEGRADED_ADMIN_REMEDIATION`` for
#: the safe, value-free public string.
_ADMIN_CREDENTIAL_DEGRADED: Optional[str] = None

#: Public, value-free remediation text for the ``/admin/health`` payload.
#: Deliberately contains NO credential material and no denylist entry — it
#: names the variable to rotate and points at the log for the detail.
_DEGRADED_ADMIN_REMEDIATION = (
    "The configured operator admin credential was refused, so the §14.7 "
    "rotation REVOKED administrator privilege instead of granting it, and the "
    "reserved demo login identifier is rejected. Account passwords were not "
    "changed. Rotate AETHER_ADMIN_PASSWORD_HASH to a bcrypt hash of a strong, "
    "unique password and restart aether-api; privilege is restored "
    "automatically on the next boot. Full detail is in the API log (search: "
    "BLOCKER-001)."
)

_admin_ready = False


class AdminCredentialSecurityError(RuntimeError):
    """The configured operator-admin credential is unsafe to grant.

    NO LONGER RAISED by :func:`apply_admin_rotation`. An earlier draft raised
    this in production and ``app.main._lifespan`` re-raised it, which under
    ``Restart=on-failure``/``RestartSec=5`` turned an unrotated credential into
    a permanent crash loop — REFUSED by the binding ruling in
    ``docs/delivery/ADR-BLOCKER-001-ADMIN-CREDENTIAL.md`` §2 (condition C1).
    The approved disposition de-privileges instead of de-booting.

    Retained deliberately, not vestigially: ``app.main._lifespan`` still
    *catches* it (so any future edit that reintroduces the raise still cannot
    abort boot), and the BLOCKER-001 test module imports it.
    """


class AdminRotationConfigError(RuntimeError):
    """The §14.7 rotation is configured to demote and regrant the SAME row.

    NO LONGER RAISED, for the same reason and under the same ruling as
    :class:`AdminCredentialSecurityError` (ADR §3 R3: "REFUSED as currently
    written; APPROVED in de-privilege form" — a single operator typo in
    ``AETHER_ADMIN_EMAIL`` must not crash-loop production). See that class for
    why it is still defined and still caught.
    """


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


def _audit_admin_credential(email: str, pw_hash: str) -> Optional[str]:
    """Operator-facing explanation of why ``pw_hash`` is unsafe, else ``None``.

    Pure and side-effect-free apart from the memoized bcrypt audit: it decides
    NOTHING about boot or privilege, it only describes the condition. The
    policy built on top of it lives in :func:`apply_admin_rotation`
    (de-privilege instead of grant), so the "what is wrong" and the "what do we
    do about it" halves can be reasoned about — and tested — separately.

    ADR condition C4: the returned text names ``AETHER_ADMIN_PASSWORD_HASH``
    and, at most, the matched denylist entry (public by construction). It never
    contains the configured hash value itself.
    """
    if not pw_hash.startswith(_BCRYPT_PREFIXES):
        return (
            "BLOCKER-001: AETHER_ADMIN_PASSWORD_HASH is not a bcrypt hash "
            f"(expected one of {', '.join(_BCRYPT_PREFIXES)}). It looks like a "
            "PLAINTEXT password was pasted into the hash variable — that would "
            "both break admin login and bypass the known-weak-password check. "
            "Generate it with: python -c \"from passlib.context import "
            "CryptContext; print(CryptContext(schemes=['bcrypt']).hash('<your "
            'password>\'))"'
        )
    weak = _weak_password_matching(pw_hash)
    if weak is None:
        return None
    # §0.5 VALUE DISCIPLINE: this string is written to the process log on
    # EVERY boot while the credential stays unrotated (_record_admin_credential_state
    # -> logger.critical + stderr -> journalctl / /var/log/aether/api.log).
    # It must therefore never interpolate the matched denylist entry: today
    # that value happens to already be public (the confirmed live production
    # password), but the guard runs unconditionally, so the SAME code path
    # would print a real operator's freshly-rotated strong password in
    # plaintext, forever, on every restart, the moment they reused (or
    # mistyped into) a value this denylist happens to also contain. Naming
    # the failure mode and the variable to rotate is fully actionable without
    # the value: the remediation ("pick a new strong, unique password") is
    # identical no matter which denylist entry matched. See
    # ``_KNOWN_WEAK_ADMIN_PASSWORDS`` in this module for the full list, which
    # is safe to read in source (public by construction) but must never be
    # echoed back with the LIVE match highlighted.
    return (
        "BLOCKER-001: refusing to grant admin privilege to "
        f"{email!r} — its AETHER_ADMIN_PASSWORD_HASH hashes a well-known "
        "default/weak password (it matches an entry on this deployment's "
        "known-weak-password denylist; the matched value is deliberately not "
        "printed here — see _KNOWN_WEAK_ADMIN_PASSWORDS in "
        "app/repositories/admin.py for the list — because this diagnostic is "
        "written to the log on every boot and must never echo a live "
        "credential value). An admin account can read every user's email "
        "address, change spend caps and issue real refunds; a guessable "
        "password on it is a full compromise of the platform. Rotate "
        "AETHER_ADMIN_PASSWORD_HASH to a bcrypt hash of a strong, unique "
        "password (not a common default) and restart."
    )


def _self_cancel_problem(email: str) -> str:
    """Explanation for the ``AETHER_ADMIN_EMAIL == seeded demo identity`` case.

    ADR §3 R3. The §14.7 demote (keyed on the seed email) and the regrant
    (keyed on ``AETHER_ADMIN_EMAIL``) would select the SAME row and net out to
    ``isAdmin=true`` for the seeded demo credential. Because email is UNIQUE,
    that collision happens if and only if the two addresses are equal — which
    is decidable here, BEFORE any write (condition C6).
    """
    return (
        "BLOCKER-001: AETHER_ADMIN_EMAIL is set to the seeded demo admin "
        f"identity ({email!r}). The §14.7 rotation demotes that identity and "
        "would immediately regrant it, so the two writes cancel out and the "
        "seeded demo credential ends up with isAdmin=true. The grant is "
        "refused and the identity is de-privileged instead. Point "
        "AETHER_ADMIN_EMAIL at a real operator mailbox that is not the demo "
        "account, and restart."
    )


def _record_admin_credential_state(problem: Optional[str]) -> None:
    """Publish (or clear) the degraded-admin-credential state for this process.

    Called on EVERY :func:`apply_admin_rotation`, with the freshly computed
    audit result, so the flag is a recomputation rather than a latch: fixing
    the environment and restarting clears it, and nothing else can set it.

    When the state is bad this logs at CRITICAL *and* writes the same line to
    stderr. Both, deliberately: the API is started by systemd through
    ``scripts/start-api.sh`` (see docs/delivery/DEPLOYMENT-RUNBOOK.md), so
    stderr is guaranteed to reach ``journalctl``/the log file even if nothing
    has configured a logging handler for this process, while the ``logging``
    call is what any future structured-log shipper will pick up.
    """
    global _ADMIN_CREDENTIAL_DEGRADED
    _ADMIN_CREDENTIAL_DEGRADED = problem
    if problem is None:
        return
    banner = (
        "CRITICAL: DEGRADED ADMIN CREDENTIAL — the API is starting NORMALLY, "
        "but administrator privilege has been REVOKED from the configured "
        "operator row and the reserved demo login identifier is REJECTED, "
        "until an operator fixes this. Every /admin/* route will return 403. "
        "The account's password is NOT changed: ordinary login, the scheduled "
        "discovery cron and all normal users are unaffected. " + problem
    )
    logger.critical(banner)
    print(banner, file=sys.stderr, flush=True)


def admin_credential_degraded() -> bool:
    """Whether this process is running with a known-unsafe operator credential."""
    return _ADMIN_CREDENTIAL_DEGRADED is not None


def _reset_admin_credential_state_for_tests() -> None:
    """Test hook: clear the degraded-credential flag between tests."""
    global _ADMIN_CREDENTIAL_DEGRADED
    _ADMIN_CREDENTIAL_DEGRADED = None


def weak_operator_credential_refused(identifier: str, password: str) -> bool:
    """Whether this login attempt must be refused as a weak operator credential.

    Defence in depth ON TOP OF the ADR-approved set (which closes the
    *privilege* hole by de-privileging, not by refusing logins). While the
    process is in the degraded state, the reserved demo/operator identifier
    ``admin`` may not authenticate with any password on the known-weak
    denylist, even if that password verifies against the stored hash. That
    makes the *published* ``admin``/``admin123`` credential dead on arrival
    rather than merely un-privileged, and it holds even if a future edit drops
    the username reclaim in ``apply_admin_rotation``.

    SCOPE — read before widening. The check keys on the reserved IDENTIFIER,
    not on the password value alone, and deliberately does NOT cover the
    ``AETHER_ADMIN_EMAIL`` address itself. ``AETHER_CRON_EMAIL`` is the SAME
    identity as ``AETHER_ADMIN_EMAIL`` and ``AETHER_CRON_PASSWORD`` is the same
    weak value (ADR §1 F3), so the every-30-minutes discovery timer
    (``scripts/discovery_cron.sh`` -> ``POST /auth/login``) authenticates as
    that address with that password. Refusing by password value, or by the
    operator email, would silently kill production job sourcing — trading one
    defect for another, and it is also what ADR condition C2 forbids in spirit
    (do not break the owner's ordinary login or cron). Closing the
    email-identifier path is the operator's credential rotation (ADR §4
    O1/O2), not a code change.

    The caller MUST fold the result into the existing constant-shaped 401 (and
    the same failed-attempt counter) so a refusal is indistinguishable from any
    other bad password — no user-enumeration signal.
    """
    if _ADMIN_CREDENTIAL_DEGRADED is None:
        return False
    if identifier.strip().lower() != _SEED_ADMIN_USERNAME:
        return False
    return password in _KNOWN_WEAK_ADMIN_PASSWORDS


def _admin_credential_problem(email: str, pw_hash: str) -> Optional[str]:
    """The single reason the configured operator admin must NOT be granted.

    Combines every disposition-changing condition the ADR approved
    (R1 known-weak password, R2 malformed/non-bcrypt hash, R3 self-cancelling
    ``AETHER_ADMIN_EMAIL``) into one value, evaluated entirely from the
    environment BEFORE any database write (condition C6).

    Deliberately NOT gated on ``AETHER_ENV``. The disposition is "no admin"
    rather than "no service" in every environment, so there is no environment
    in which a weak operator credential silently keeps its privileges — and no
    ``_is_production()`` branch that could relocate a failure instead of
    removing it (ADR §3 R3).
    """
    if email and email.lower() == _SEED_ADMIN_EMAIL:
        return _self_cancel_problem(email)
    if email and pw_hash:
        return _audit_admin_credential(email, pw_hash)
    return None


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


def list_audit(
    limit: int = 50,
    offset: int = 0,
    *,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
) -> dict[str, Any]:
    """Paginated append-only audit log, newest first.

    ``target_type``/``target_id`` narrow the log to ONE subject (ADMIN-FULL: the
    per-user audit trail the admin user panel renders). Both default to None, so
    the existing platform-wide call is byte-identical to before.
    """
    _ensure_admin_schema()
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    where: list[str] = []
    filter_params: list[Any] = []
    if target_type:
        where.append('a."targetType" = %s')
        filter_params.append(target_type)
    if target_id:
        where.append('a."targetId" = %s')
        filter_params.append(target_id)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT count(*) FROM "AdminAuditLog" a{where_sql}', filter_params
            )
            total = int(cur.fetchone()[0])
            # QA M-05: join the actor's display name/email so the UI can show
            # a human-readable actor instead of a raw CUID. LEFT JOIN keeps
            # entries whose actor row was deleted (actorName/actorEmail null).
            cur.execute(
                'SELECT a."id",a."actorUserId",a."action",a."targetType",a."targetId",'
                'a."detailJson",a."ip",a."createdAt",u."name" AS "actorName",'
                'u."email" AS "actorEmail" FROM "AdminAuditLog" a '
                'LEFT JOIN "User" u ON u."id" = a."actorUserId"'
                f"{where_sql} "
                'ORDER BY a."createdAt" DESC, a."id" DESC LIMIT %s OFFSET %s',
                [*filter_params, limit, offset],
            )
            rows = rows_to_dicts(cur)
    entries = [
        {
            "id": r["id"],
            "actorUserId": r["actorUserId"],
            "actorName": r.get("actorName"),
            "actorEmail": r.get("actorEmail"),
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
        # ADMIN-FULL: username is a real login identity (``get_by_username_or_email``),
        # so an admin searching for the credential a user actually types must find
        # them. ``ensure_user_profile_columns`` (called by ``_ensure_admin_schema``)
        # guarantees the column exists on the older test schema.
        where.append(
            '(u."email" ILIKE %s OR u."name" ILIKE %s OR u."username" ILIKE %s)'
        )
        params.extend([f"%{query}%", f"%{query}%", f"%{query}%"])
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
        SELECT u."id", u."email", u."name", u."username", u."isAdmin", u."suspended",
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
        "username": r.get("username"),
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
                'SELECT u."id", u."email", u."name", u."username", u."isAdmin",'
                ' u."suspended", u."createdAt", u."lastLoginAt",'
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
        # ADMIN-FULL: the ONE resolver's verdict for THIS user, so the panel
        # shows why they are (or are not) restricted — including an admin grant
        # sitting VISIBLY on top of whatever the Subscription row says. Detail
        # only, never the list: one resolve per page, not per row.
        "entitlement": _entitlement_view(user_id),
    }


def _entitlement_view(user_id: str) -> dict[str, Any]:
    """The ONE resolver's verdict, in the admin panel's wire shape."""
    from app.services import entitlements

    return entitlements.resolve(user_id).as_dict()


class IdentityConflictError(Exception):
    """Raised when an admin identity change would collide with another account."""


def update_user_identity(
    user_id: str,
    *,
    email: Optional[str] = None,
    username: Optional[str] = None,
    name: Optional[str] = None,
    cur: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Change a user's login/display identity; return ``(before, after)``.

    Uniqueness is enforced BEFORE the write (and again by the ``User_email_key`` /
    ``User_username_key`` unique indexes, which turn a lost race into a
    ``IdentityConflictError`` rather than a duplicate account). ``username`` is
    matched case-insensitively because ``get_by_username_or_email`` resolves it
    that way — otherwise "Bob" and "bob" would be two logins for one name.

    Only the fields the caller passed are touched; ``None`` means "leave alone".
    The returned pair is exactly what the audit row records (before -> after).

    ``cur`` (optional) runs the whole read-check-write inside the caller's OPEN
    transaction and does NOT commit, so the caller can commit it together with
    the ``AdminAuditLog`` row that records it. The caller must have run
    :func:`_ensure_admin_schema` before opening that transaction.
    """
    fields: dict[str, Any] = {}
    if email is not None:
        fields["email"] = email
    if username is not None:
        fields["username"] = username or None
    if name is not None:
        fields["name"] = name or None

    def _run(c: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        c.execute(
            'SELECT "id","email","username","name" FROM "User" WHERE "id"=%s',
            (user_id,),
        )
        rows = rows_to_dicts(c)
        if not rows:
            raise LookupError(user_id)
        before = {
            "email": rows[0]["email"],
            "username": rows[0].get("username"),
            "name": rows[0].get("name"),
        }
        if "email" in fields:
            c.execute(
                'SELECT 1 FROM "User" WHERE "email"=%s AND "id"<>%s',
                (fields["email"], user_id),
            )
            if c.fetchone():
                raise IdentityConflictError("email")
        if fields.get("username"):
            c.execute(
                'SELECT 1 FROM "User" WHERE lower("username")=lower(%s)'
                ' AND "id"<>%s',
                (fields["username"], user_id),
            )
            if c.fetchone():
                raise IdentityConflictError("username")
        if fields:
            assignments = ", ".join(f'"{col}"=%s' for col in fields)
            try:
                c.execute(
                    f'UPDATE "User" SET {assignments}, "updatedAt"=now()'
                    ' WHERE "id"=%s',
                    (*fields.values(), user_id),
                )
            except UniqueViolation as exc:  # lost race against a concurrent write
                # Name the FIELD, not the index: the message is shown to an
                # admin. ``constraint_name`` can be absent on some servers,
                # so fall back to the honest generic rather than "None".
                constraint = (exc.diag.constraint_name or "").lower()
                if "username" in constraint:
                    field = "username"
                elif "email" in constraint:
                    field = "email"
                else:
                    field = "identity"
                raise IdentityConflictError(field) from exc
        c.execute(
            'SELECT "email","username","name" FROM "User" WHERE "id"=%s',
            (user_id,),
        )
        after_rows = rows_to_dicts(c)
        return before, {
            "email": after_rows[0]["email"],
            "username": after_rows[0].get("username"),
            "name": after_rows[0].get("name"),
        }

    if cur is not None:
        return _run(cur)

    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as c:
            before, after = _run(c)
        conn.commit()
    return before, after


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
        # BLOCKER-001 restart safety: a degraded admin credential no longer
        # aborts boot, so it would otherwise be invisible outside the API log.
        # Surfaced here as a boolean plus a fixed, value-free remediation
        # string — never the matched denylist entry, which on a degraded deploy
        # is the live password.
        #
        # HONEST LIMITATION: /admin/health is AdminUser-gated, and the degraded
        # disposition revokes isAdmin — so on a deployment whose only admin was
        # the configured operator (ADR §1 F5: production has exactly one), this
        # field is unreachable precisely when it is true. It is useful to a
        # second, independently-privileged admin and as a post-rotation
        # confirmation; the operative channel while degraded is the CRITICAL
        # line in the API log. Do NOT "fix" this by exposing the flag on the
        # unauthenticated /health endpoint — that would advertise to the
        # internet that this host has a weak admin credential.
        "security": {
            "adminCredentialDegraded": admin_credential_degraded(),
            "remediation": (
                _DEGRADED_ADMIN_REMEDIATION if admin_credential_degraded() else None
            ),
        },
    }


# --------------------------------------------------------------------------- #
# §14.7 credential rotation (GATE-31 / SEC-001)
# --------------------------------------------------------------------------- #


def apply_admin_rotation() -> dict[str, Any]:
    """Apply §14.7 admin-credential rotation. Idempotent; safe on every load.

    0. EVALUATE the configured operator credential (``_admin_credential_problem``)
       and publish the result as this process's degraded-state flag. Everything
       that can change the disposition is decided HERE, from the environment
       alone, before any write (ADR condition C6).
    1. RECLAIM the reserved demo username ``admin`` from every row that is not
       the seeded demo account, so the bare identifier ``admin`` can never
       resolve to a real operator/owner account through
       ``UserRepository.get_by_username_or_email`` (BLOCKER-001 / D2, ADR R4).
    2. DEMOTE the seeded demo account (``admin@aether.local``) to
       ``isAdmin=false`` — the seeded demo credential must never hold
       privileges (GATE-31).
    3. Then EITHER:
       * no problem — create/update ``AETHER_ADMIN_EMAIL`` with ``isAdmin=true``
         and the given (already hashed) password; or
       * a problem — **de-privilege**: force ``isAdmin=false`` on that row and
         leave ``passwordHash`` untouched.
       Secrets come from ``os.environ`` only — never a plaintext literal here.

    DISPOSITION: DE-PRIVILEGE, NOT DE-BOOT (binding ruling,
    ``docs/delivery/ADR-BLOCKER-001-ADMIN-CREDENTIAL.md``). This function never
    raises for a credential problem, in any environment. An earlier draft
    raised in production and ``app.main._lifespan`` re-raised, which under
    ``Restart=on-failure``/``RestartSec=5`` converted an unrotated credential
    into a permanent crash loop (ADR §2). Two details are load-bearing and must
    not be "simplified" away:

    * Step 3's de-privilege is an EXPLICIT ``isAdmin=false`` write, not an
      early return. Production's operator row is ALREADY ``isAdmin=true`` from
      previous boots, so merely skipping the grant would leave the hole wide
      open while reporting success (ADR condition C3 — "the single most likely
      way to get R1 wrong").
    * It must NEVER touch ``passwordHash`` (condition C2). Changing it would
      lock the owner out of their own product account and break
      ``scripts/discovery_cron.sh``, which authenticates as that same identity
      every 30 minutes. The de-privilege removes privilege only; ordinary
      login, agent runs and scheduled discovery are unaffected.

    Recovery is automatic and needs no code change: rotation runs on every app
    construction, so the first restart after the operator rotates
    ``AETHER_ADMIN_PASSWORD_HASH`` to a strong, well-formed hash re-grants
    ``isAdmin`` (ADR operator step O5).

    Steps 2 and 3 select on mutually exclusive predicates (``email`` equal to
    the seed address vs. ``email`` equal to a configured address proven NOT to
    be the seed address — step 0 routes the equal case to de-privilege), so the
    demote can never be silently undone by the regrant. Because ``email`` is
    UNIQUE, equality of the two addresses is the ONLY way both predicates can
    select one row; deciding it at step 0 is therefore a complete
    pre-condition, and no post-commit check is needed (ADR §2.1 / C6).
    """
    _ensure_admin_schema()

    email = (os.environ.get("AETHER_ADMIN_EMAIL") or "").strip()
    pw_hash = (os.environ.get("AETHER_ADMIN_PASSWORD_HASH") or "").strip()

    # --- step 0: decide the disposition, before any write ------------------- #
    # Recomputed every run (never latched), so a rotation + restart clears it.
    problem = _admin_credential_problem(email, pw_hash)
    _record_admin_credential_state(problem)

    result: dict[str, Any] = {
        "reclaimed_usernames": [],
        "demoted_seed": False,
        "env_admin": None,
        "deprivileged": None,
    }
    granted_id: Optional[str] = None

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

            # --- step 3: grant, or de-privilege ----------------------------- #
            # Same transaction as steps 1-2 so a mid-rotation failure can never
            # leave the reserved alias cleared but the privilege untouched (or
            # vice versa), and so no post-condition has to be evaluated after a
            # commit (ADR §2.1 / condition C6).
            if email and pw_hash and problem is None:
                cur.execute(
                    'INSERT INTO "User" ("id","email","passwordHash","isAdmin",'
                    '"suspended","updatedAt") VALUES (%s,%s,%s,true,false,now()) '
                    'ON CONFLICT ("email") DO UPDATE SET '
                    '"passwordHash"=EXCLUDED."passwordHash","isAdmin"=true,'
                    '"suspended"=false,"updatedAt"=now() RETURNING "id"',
                    (new_id(), email, pw_hash),
                )
                granted_id = cur.fetchone()[0]
                result["env_admin"] = email
            elif problem is not None and email:
                # DE-PRIVILEGE (ADR R1/R2/R3, condition C3). An explicit write,
                # because the row is already isAdmin=true from earlier boots —
                # skipping the grant would be a no-op that reports success.
                # ``isAdmin`` is re-read from the DB on every request
                # (middleware/auth.py), so this revokes admin power from tokens
                # ALREADY issued, immediately. Only this one column changes:
                # ``passwordHash`` is untouched (condition C2), and no row is
                # created if the configured address has never signed up.
                cur.execute(
                    'UPDATE "User" SET "isAdmin"=false,"updatedAt"=now() '
                    'WHERE lower("email")=lower(%s) RETURNING "id"',
                    (email,),
                )
                result["deprivileged"] = [row[0] for row in cur.fetchall()]
        conn.commit()

    if result["deprivileged"]:
        print(
            "CRITICAL: §14.7 rotation REVOKED isAdmin from "
            f"{len(result['deprivileged'])} account(s) configured via "
            "AETHER_ADMIN_EMAIL because the configured credential was refused "
            "(see the diagnostic above). Their password was NOT changed. "
            "/admin/* will return 403 until AETHER_ADMIN_PASSWORD_HASH is "
            "rotated and the API restarted.",
            file=sys.stderr,
            flush=True,
        )

    if reclaimed:
        print(
            "WARNING: §14.7 rotation reclaimed the reserved demo username "
            f"'{_SEED_ADMIN_USERNAME}' from {len(reclaimed)} non-demo "
            f"account(s) (ids: {', '.join(reclaimed)}). Those accounts can no "
            "longer be reached by that identifier at login and must sign in "
            "with their email address (BLOCKER-001 / D2).",
            file=sys.stderr,
        )

    if granted_id is not None:
        ensure_user_billing(granted_id)  # give the env admin a Free plan + quota
    return result
