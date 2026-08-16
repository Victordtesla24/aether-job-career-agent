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
import time
from typing import Any, Optional

from psycopg2.errors import UniqueViolation

from app.db import (
    ensure_admin_user_columns,
    ensure_user_lifecycle_columns,
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
    # ADMIN-2.0: ``deletedAt`` (soft delete) + ``mustChangePassword`` (admin-created
    # accounts) are read by the user list/detail projections below.
    ensure_user_lifecycle_columns()
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


#: ADMIN-MGMT E1 — lifecycle views for ``list_users``. The predicate for each is
#: written once here so the list filter, the tab counts and the front end can
#: never disagree about what "deleted" means.
USER_VIEWS: dict[str, Optional[str]] = {
    "active": 'u."deletedAt" IS NULL',
    "suspended": 'u."suspended" = true AND u."deletedAt" IS NULL',
    "deleted": 'u."deletedAt" IS NOT NULL',
    "all": None,
}


def list_users(
    *,
    query: Optional[str] = None,
    plan: Optional[str] = None,
    suspended: Optional[bool] = None,
    view: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """List users with plan, signup date, last login and LLM spend (USD).

    ``view`` (ADMIN-MGMT E1) selects a lifecycle slice — ``active`` (the
    default), ``suspended``, ``deleted`` or ``all``. The default matters: before
    this change a soft-deleted account stayed mixed into the ordinary list, so
    an operator reading the user table could not tell "this platform has N
    customers" from "N customers plus the wreckage of past ones."

    BACKWARD COMPATIBILITY is explicit rather than incidental: when the caller
    supplies the legacy ``suspended`` boolean and NO ``view``, no lifecycle
    predicate is applied at all — that call returns exactly the rows it returned
    before this parameter existed. The ``active`` default only engages for a
    caller that asked for neither.

    ``counts`` is additive and deliberately NOT scoped to the selected view: it
    reports every lifecycle bucket under the SAME ``q``/``plan`` search, which is
    what a tab strip needs (the badge on the tab you are not looking at).
    """
    _ensure_admin_schema()
    ensure_user_billing_backfill()
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    view_key: Optional[str] = None
    if view is not None:
        view_key = str(view).strip().lower()
        if view_key not in USER_VIEWS:
            raise ValueError(
                "view must be one of: " + ", ".join(sorted(USER_VIEWS))
            )
    elif suspended is None:
        view_key = "active"

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

    # The search filters (q/plan/suspended) WITHOUT the lifecycle predicate —
    # this is what the per-bucket counts are computed over.
    search_where = list(where)
    search_params = list(params)

    view_predicate = USER_VIEWS.get(view_key or "all")
    if view_predicate:
        where.append(view_predicate)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    search_where_sql = (
        (" WHERE " + " AND ".join(search_where)) if search_where else ""
    )

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
               u."deletedAt", u."mustChangePassword",
               u."createdAt", u."lastLoginAt",
               COALESCE(s."planId", 'free') AS plan, s."status" AS "subStatus",
               COALESCE(sp.spend, 0) AS spend, COALESCE(sp.runs, 0) AS runs
        {from_sql}
        LEFT JOIN ({_SPEND_SUBQUERY}) sp ON sp."userId" = u."id"
        {where_sql}
        ORDER BY u."createdAt" DESC
        LIMIT %s OFFSET %s
    '''
    counts_sql = f'''
        SELECT
          count(*) FILTER (WHERE {USER_VIEWS["active"]})    AS active,
          count(*) FILTER (WHERE {USER_VIEWS["suspended"]}) AS suspended,
          count(*) FILTER (WHERE {USER_VIEWS["deleted"]})   AS deleted
        {from_sql}{search_where_sql}
    '''
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT count(*) {from_sql}{where_sql}', params)
            total = int(cur.fetchone()[0])
            cur.execute(counts_sql, search_params)
            crow = cur.fetchone()
            counts = {
                "active": int(crow[0] or 0),
                "suspended": int(crow[1] or 0),
                "deleted": int(crow[2] or 0),
            }
            cur.execute(sql, [*params, limit, offset])
            rows = rows_to_dicts(cur)
    users = [_user_row(r) for r in rows]
    return {
        "users": users,
        "total": total,
        "limit": limit,
        "offset": offset,
        # Additive (ADMIN-MGMT E1). Existing keys above are untouched.
        "view": view_key,
        "counts": counts,
    }


def _user_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "email": r["email"],
        "name": r.get("name"),
        "username": r.get("username"),
        "isAdmin": bool(r.get("isAdmin")),
        "suspended": bool(r.get("suspended")),
        # ADMIN-2.0: soft-delete state is admin-only truth — a deleted account is
        # still listed (its work and audit trail survive), visibly flagged.
        "deletedAt": (
            r["deletedAt"].isoformat() if r.get("deletedAt") else None
        ),
        "mustChangePassword": bool(r.get("mustChangePassword")),
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
                ' u."suspended", u."deletedAt", u."mustChangePassword",'
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
# ADMIN-2.0 — account lifecycle (create / soft-delete / restore) + the
# PROTECTED-ACCOUNT guard that no admin surface may bypass.
# --------------------------------------------------------------------------- #


#: Refusal text for a destructive action aimed at a privileged account. Names
#: WHICH protection applies so the refusal is actionable, and carries no
#: credential material.
PROTECTED_ADMIN_MESSAGE = (
    "This account holds admin privileges. Aether refuses to delete or suspend "
    "an administrator: revoke the privilege first (a deliberate, separate act), "
    "then repeat this action."
)
PROTECTED_OWNER_MESSAGE = (
    "This is the owner identity that server configuration owns "
    "(AETHER_ADMIN_EMAIL). Deleting or suspending it would lock the operator out "
    "of the platform, and §14.7 rotation re-creates it on the next restart "
    "anyway. The action was refused instead of accepted-then-reverted."
)


class DuplicateUserError(Exception):
    """Raised when an admin-created account collides with an existing email."""


def account_guard_context(user_id: str, cur: Any = None) -> Optional[dict[str, Any]]:
    """The fields every destructive admin action must consult before acting.

    Read on the CALLER'S cursor when one is supplied, so the guard decision and
    the mutation it gates cannot straddle a concurrent privilege change.
    """

    def _run(c: Any) -> Optional[dict[str, Any]]:
        c.execute(
            'SELECT "id","email","name","isAdmin","suspended","deletedAt"'
            ' FROM "User" WHERE "id"=%s',
            (user_id,),
        )
        rows = rows_to_dicts(c)
        return rows[0] if rows else None

    if cur is not None:
        return _run(cur)
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as c:
            return _run(c)


def protected_account_reason(target: dict[str, Any]) -> Optional[str]:
    """Why this account may NOT be deleted or suspended, or ``None``.

    SERVER-SIDE by design: hiding the button is a UI convenience, not a
    protection. Both rules are absolute — an admin account and the §14.7 owner
    identity are the two ways an operator can lock themselves (and every other
    operator) out of the platform.
    """
    if bool(target.get("isAdmin")):
        return PROTECTED_ADMIN_MESSAGE
    if password_is_env_managed(target.get("email")):
        return PROTECTED_OWNER_MESSAGE
    return None


def create_user(
    cur: Any,
    *,
    email: str,
    name: Optional[str],
    password_hash: str,
    must_change_password: bool = True,
) -> dict[str, Any]:
    """Insert an admin-created ``User`` row on the CALLER'S cursor.

    Deliberately NOT ``UserRepository.create``: that helper commits its own
    transaction, which would leave a durable account creation the audit row
    could still fail to record. Writing here, on the caller's cursor, keeps the
    account and its ``AdminAuditLog`` row atomic — the same discipline every
    other ADMIN-FULL mutation follows.

    ``isAdmin`` is NEVER settable through this path: an admin-created account is
    an ordinary account. Privilege is granted by a separate, deliberate act.
    ``ON CONFLICT DO NOTHING`` + a raise keeps the duplicate-email case an honest
    409 rather than a silently-ignored write.

    ``passwordChangedAt`` is stamped from the API's clock (``to_timestamp``),
    not DB ``now()`` — same reasoning as ``UserRepository.set_password``: the
    O-4 iat comparison must not span two clocks, or DB-ahead skew can falsely
    401 the account's very first login.
    """
    cur.execute(
        '''
        INSERT INTO "User" ("id","email","name","passwordHash","mustChangePassword",
                            "passwordChangedAt","updatedAt")
        VALUES (%s,%s,%s,%s,%s,to_timestamp(%s),now())
        ON CONFLICT ("email") DO NOTHING
        RETURNING "id","email","name","createdAt","mustChangePassword"
        ''',
        (new_id(), email, name, password_hash, bool(must_change_password),
         time.time()),
    )
    rows = rows_to_dicts(cur)
    if not rows:
        raise DuplicateUserError(email)
    return rows[0]


def soft_delete_user(cur: Any, user_id: str) -> dict[str, Any]:
    """Stamp ``deletedAt`` and suspend, on the caller's cursor.

    SUSPENSION IS THE TEETH. ``deletedAt`` alone is a label; the auth dependency
    already 403s a ``suspended`` user on every authenticated route, so setting
    both makes "deleted" mean the account genuinely cannot be used — without
    inventing a second enforcement path that could drift from the first.

    Reversible by :func:`restore_user`, and every child row (jobs, resumes,
    applications, runs, audit history) is left exactly where it is.
    """
    cur.execute(
        'UPDATE "User" SET "deletedAt"=now(),"suspended"=true,"updatedAt"=now()'
        ' WHERE "id"=%s AND "deletedAt" IS NULL'
        ' RETURNING "deletedAt","suspended"',
        (user_id,),
    )
    rows = rows_to_dicts(cur)
    if not rows:
        raise LookupError("user is already deleted")
    return rows[0]


def restore_user(cur: Any, user_id: str) -> dict[str, Any]:
    """Clear ``deletedAt`` on the caller's cursor.

    Deliberately does NOT lift the suspension the delete applied. Restoring an
    account and handing it back its access are two different decisions, and
    silently un-suspending would also erase a suspension that predated the
    delete. The caller reports the surviving ``suspended`` flag so the admin can
    see exactly what is still in force.
    """
    cur.execute(
        'UPDATE "User" SET "deletedAt"=NULL,"updatedAt"=now()'
        ' WHERE "id"=%s AND "deletedAt" IS NOT NULL'
        ' RETURNING "suspended"',
        (user_id,),
    )
    rows = rows_to_dicts(cur)
    if not rows:
        raise LookupError("user is not deleted")
    return rows[0]


# --------------------------------------------------------------------------- #
# ADMIN-MGMT E1 — HARD purge (the step soft-delete deliberately stops short of)
#
# Derived from the 41-table census in
# ``docs/delivery/PROD-PRISTINE-WIPE-MANIFEST-2026-08-15.md`` §1/§3, with every
# table's key column re-verified against ``information_schema`` rather than
# trusted from the document (the live schema has already drifted past that
# census: ``AgentDirective``/``SalesAgent`` exist in production, ``RunPlan``/
# ``NotificationDigest`` exist in the test schema).
#
# THREE DELIBERATE CHOICES, each of which would be a defect if made silently:
#
# 1. EXPLICIT per-table deletes, never FK cascade. ``ADR-PROD-TESTDATA-PURGE``
#    C3 records cascade-reliance silently orphaning 40 rows on this exact
#    schema, and 17 of these tables carry NO foreign key to ``User`` at all —
#    cascade could not reach them even in principle.
# 2. ORDERED children-before-parents. Only one constraint can actually abort a
#    statement (``Application_resumeId_fkey`` is ``ON DELETE RESTRICT``), but the
#    order below is child-first throughout so the transaction never depends on
#    which constraints happen to be RESTRICT this month.
# 3. SCHEMA-ADAPTIVE. Each entry declares the columns it needs and is SKIPPED
#    when the running schema lacks them. A hard delete that crashes half-way
#    because one lazy-DDL table was never created on this deployment is worse
#    than one that reports honestly which tables it touched.
#
# ``AdminAuditLog`` is NOT in this list — the trail outlives the account, by
# design. ``SalesLead`` is not deleted either: it is unlinked (see below).
# --------------------------------------------------------------------------- #

#: ``(table, required_columns, delete_sql)`` — ordered, children first. Every
#: statement takes exactly one parameter: the target ``userId``.
PURGE_CASCADE: tuple[tuple[str, tuple[str, ...], str], ...] = (
    # --- keyed to a parent row rather than to the user directly ---------------
    (
        "ApplicationStatusEvent",
        ("applicationId",),
        'DELETE FROM "ApplicationStatusEvent" WHERE "applicationId" IN'
        ' (SELECT "id" FROM "Application" WHERE "userId"=%s)',
    ),
    (
        "JobEmbedding",
        ("jobId",),
        'DELETE FROM "JobEmbedding" WHERE "jobId" IN'
        ' (SELECT "id" FROM "Job" WHERE "userId"=%s)',
    ),
    # --- user-keyed children of Application / Job / Contact -------------------
    ("AnswerBankUsage", ("userId",), 'DELETE FROM "AnswerBankUsage" WHERE "userId"=%s'),
    ("ApprovalRequest", ("userId",), 'DELETE FROM "ApprovalRequest" WHERE "userId"=%s'),
    (
        "InterviewSchedule",
        ("userId",),
        'DELETE FROM "InterviewSchedule" WHERE "userId"=%s',
    ),
    ("EmailThread", ("userId",), 'DELETE FROM "EmailThread" WHERE "userId"=%s'),
    ("OutreachTask", ("userId",), 'DELETE FROM "OutreachTask" WHERE "userId"=%s'),
    ("Offer", ("userId",), 'DELETE FROM "Offer" WHERE "userId"=%s'),
    ("AgentRun", ("userId",), 'DELETE FROM "AgentRun" WHERE "userId"=%s'),
    ("BackgroundJob", ("userId",), 'DELETE FROM "BackgroundJob" WHERE "userId"=%s'),
    # --- Application MUST precede Resume (the one RESTRICT constraint) --------
    ("Application", ("userId",), 'DELETE FROM "Application" WHERE "userId"=%s'),
    ("Resume", ("userId",), 'DELETE FROM "Resume" WHERE "userId"=%s'),
    ("Job", ("userId",), 'DELETE FROM "Job" WHERE "userId"=%s'),
    ("Contact", ("userId",), 'DELETE FROM "Contact" WHERE "userId"=%s'),
    # --- standalone user-owned product data -----------------------------------
    ("AnswerBankItem", ("userId",), 'DELETE FROM "AnswerBankItem" WHERE "userId"=%s'),
    (
        "EvidenceCorpusItem",
        ("userId",),
        'DELETE FROM "EvidenceCorpusItem" WHERE "userId"=%s',
    ),
    ("StoryEntry", ("userId",), 'DELETE FROM "StoryEntry" WHERE "userId"=%s'),
    ("CareerProfile", ("userId",), 'DELETE FROM "CareerProfile" WHERE "userId"=%s'),
    ("JobSourceStatus", ("userId",), 'DELETE FROM "JobSourceStatus" WHERE "userId"=%s'),
    ("AgentConfig", ("userId",), 'DELETE FROM "AgentConfig" WHERE "userId"=%s'),
    ("AgentProvider", ("userId",), 'DELETE FROM "AgentProvider" WHERE "userId"=%s'),
    ("AgentQuotaBlock", ("userId",), 'DELETE FROM "AgentQuotaBlock" WHERE "userId"=%s'),
    ("AgentDirective", ("userId",), 'DELETE FROM "AgentDirective" WHERE "userId"=%s'),
    ("RunPlan", ("userId",), 'DELETE FROM "RunPlan" WHERE "userId"=%s'),
    (
        "NotificationDigest",
        ("userId",),
        'DELETE FROM "NotificationDigest" WHERE "userId"=%s',
    ),
    # --- connected accounts + credentials (nothing here may outlive the user) --
    ("GmailAccount", ("userId",), 'DELETE FROM "GmailAccount" WHERE "userId"=%s'),
    ("GoogleCredential", ("userId",), 'DELETE FROM "GoogleCredential" WHERE "userId"=%s'),
    (
        "UserProviderCredential",
        ("userId",),
        'DELETE FROM "UserProviderCredential" WHERE "userId"=%s',
    ),
    (
        "AnthropicOAuthState",
        ("userId",),
        'DELETE FROM "AnthropicOAuthState" WHERE "userId"=%s',
    ),
    (
        "AnthropicOAuthToken",
        ("userId",),
        'DELETE FROM "AnthropicOAuthToken" WHERE "userId"=%s',
    ),
    (
        "PasswordResetToken",
        ("userId",),
        'DELETE FROM "PasswordResetToken" WHERE "userId"=%s',
    ),
    (
        "UserEntitlementOverride",
        ("userId",),
        'DELETE FROM "UserEntitlementOverride" WHERE "userId"=%s',
    ),
    # --- billing spine last: these have NO FK to User, so nothing else moves it -
    ("UsageQuota", ("userId",), 'DELETE FROM "UsageQuota" WHERE "userId"=%s'),
    ("Subscription", ("userId",), 'DELETE FROM "Subscription" WHERE "userId"=%s'),
)

#: Local ``Subscription.status`` values that mean money can still move. A row in
#: one of these states WITH a ``stripeSubscriptionId`` is a live Stripe object
#: this VM does not own; deleting the local row would strand it billing forever.
BILLABLE_SUBSCRIPTION_STATUSES = ("active", "past_due", "trialing")

CANCEL_FIRST_MESSAGE = (
    "This account still has a live Stripe subscription "
    "({status}). Cancel the Stripe subscription first "
    "(POST /api/admin/users/{{id}}/subscription/cancel), then repeat this "
    "action — deleting the local record would leave Stripe billing a customer "
    "Aether can no longer see."
)


def _schema_columns(cur: Any) -> dict[str, set[str]]:
    """``{table: {column, ...}}`` for the schemas on this connection's path.

    The purge is driven off THIS, not off a hardcoded table list: the census the
    cascade was derived from is already stale (see the module comment above), and
    a stale list would either crash on a missing table or silently leave a
    drifted-in table's rows behind. Both failure modes are invisible to the
    caller; asking the database is not.
    """
    cur.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = ANY(current_schemas(false))"
    )
    out: dict[str, set[str]] = {}
    for table, column in cur.fetchall():
        out.setdefault(table, set()).add(column)
    return out


def billable_subscription(cur: Any, user_id: str) -> Optional[dict[str, Any]]:
    """The user's live-billing ``Subscription`` row, or ``None``.

    "Live" means BOTH a ``stripeSubscriptionId`` and a money-moving status: a
    free-tier row, or a canceled one, or a row that only ever held a Stripe
    *customer* object (the F5 case in the wipe manifest) carries no billing
    obligation and must not block an admin from cleaning it up.
    """
    cur.execute(
        'SELECT "id","planId","status","stripeSubscriptionId","stripeCustomerId"'
        ' FROM "Subscription" WHERE "userId"=%s',
        (user_id,),
    )
    for row in rows_to_dicts(cur):
        if not row.get("stripeSubscriptionId"):
            continue
        if str(row.get("status") or "").strip().lower() in (
            BILLABLE_SUBSCRIPTION_STATUSES
        ):
            return row
    return None


def purge_user_cascade(cur: Any, user_id: str) -> dict[str, int]:
    """Delete every child row keyed to ``user_id``, on the CALLER'S cursor.

    Returns ``{table: rows_deleted}`` for the tables that exist on this schema —
    the per-table receipt the audit row and the API response both carry, so
    "purged" is a countable claim rather than an assertion.

    Does NOT delete the ``User`` row (see :func:`delete_user_row`) and does NOT
    touch ``AdminAuditLog``.
    """
    columns = _schema_columns(cur)
    counts: dict[str, int] = {}
    for table, required, sql in PURGE_CASCADE:
        present = columns.get(table)
        if not present or not set(required).issubset(present):
            continue
        cur.execute(sql, (user_id,))
        counts[table] = int(cur.rowcount or 0)

    # SalesLead is UNLINKED, never deleted. Its rows carry consent evidence and
    # unsubscribe/suppression obligations that outlive any account (the wipe
    # manifest's F3 reasoning) — destroying them to tidy up a user record would
    # discard exactly the proof those obligations rest on. The ``userId`` link is
    # a convenience backfill by email match, so dropping it loses nothing.
    sales_lead = columns.get("SalesLead")
    if sales_lead and "userId" in sales_lead:
        cur.execute(
            'UPDATE "SalesLead" SET "userId"=NULL WHERE "userId"=%s', (user_id,)
        )
        counts["SalesLead(unlinked)"] = int(cur.rowcount or 0)
    return counts


def delete_user_row(cur: Any, user_id: str) -> int:
    """Hard-delete the ``User`` row itself. Returns rows removed (0 or 1)."""
    cur.execute('DELETE FROM "User" WHERE "id"=%s', (user_id,))
    return int(cur.rowcount or 0)


def delete_billing_records(cur: Any, user_id: str) -> dict[str, int]:
    """Delete the local ``Subscription`` + ``UsageQuota`` rows for one userId.

    Deliberately keyed on ``userId`` ALONE and never joined to ``User``: the
    single most useful case is the orphan — a billing pair whose owner was
    deleted by some earlier process (the manifest's F4). Requiring the user to
    exist would make this route useless for exactly the mess it exists to clear.
    """
    cur.execute('DELETE FROM "Subscription" WHERE "userId"=%s', (user_id,))
    subscriptions = int(cur.rowcount or 0)
    cur.execute('DELETE FROM "UsageQuota" WHERE "userId"=%s', (user_id,))
    quotas = int(cur.rowcount or 0)
    return {"subscription": subscriptions, "usageQuota": quotas}


# --------------------------------------------------------------------------- #
# ADMIN-MGMT E1 — hygiene report (read-only) + orphan purge
# --------------------------------------------------------------------------- #

#: Sample size returned alongside each hygiene count. Small on purpose: the
#: report is a pointer to work, not a data export.
_HYGIENE_SAMPLE = 10


#: ``userId``s holding a ``Subscription``/``UsageQuota`` row with NO ``User`` row.
#: Neither billing table carries a foreign key to ``User`` (17 tables share that
#: gap on this schema), so a user deleted by any path that predates
#: :func:`purge_user_cascade` leaves this pair behind — invisible to every
#: user-facing screen and still counted by billing reads.
_ORPHAN_BILLING_FROM = (
    ' FROM ('
    '   SELECT "userId", max("createdAt") AS ts FROM ('
    '     SELECT "userId","createdAt" FROM "Subscription"'
    '     UNION ALL SELECT "userId","createdAt" FROM "UsageQuota"'
    "   ) x GROUP BY \"userId\""
    ' ) b LEFT JOIN "User" u ON u."id" = b."userId"'
    ' WHERE u."id" IS NULL'
)


def orphan_billing_count(cur: Any) -> int:
    """How many distinct userIds hold owner-less billing rows."""
    cur.execute("SELECT count(*)" + _ORPHAN_BILLING_FROM)
    return int(cur.fetchone()[0])


def orphan_billing_sample(cur: Any, limit: int) -> list[str]:
    """Up to ``limit`` orphaned userIds, MOST RECENT FIRST.

    Ordering is load-bearing rather than cosmetic: on a long-lived database the
    orphan set can run to tens of thousands of rows accumulated over years, and
    a sample sorted by id would show the same ancient ten forever while the
    orphan created this morning — the one an operator is actually looking for —
    stayed invisible.
    """
    cur.execute(
        'SELECT b."userId"' + _ORPHAN_BILLING_FROM + " ORDER BY b.ts DESC LIMIT %s",
        (int(limit),),
    )
    return [r[0] for r in cur.fetchall()]


def hygiene_report() -> dict[str, Any]:
    """Read-only stale-data report. Counts + small samples, cheap SQL only.

    Writes nothing and recommends nothing implicitly: every class it names has a
    matching explicit route an admin must choose to call.
    """
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "User" WHERE "deletedAt" IS NOT NULL')
            soft_count = int(cur.fetchone()[0])
            cur.execute(
                'SELECT "id","email","deletedAt" FROM "User"'
                ' WHERE "deletedAt" IS NOT NULL'
                ' ORDER BY "deletedAt" DESC LIMIT %s',
                (_HYGIENE_SAMPLE,),
            )
            soft_sample = [
                {
                    "id": r[0],
                    "email": r[1],
                    "deletedAt": r[2].isoformat() if r[2] else None,
                }
                for r in cur.fetchall()
            ]

            orphan_count = orphan_billing_count(cur)
            orphan_sample = orphan_billing_sample(cur, _HYGIENE_SAMPLE)

            cur.execute(
                'SELECT count(*) FROM "Subscription" WHERE "status"=%s', ("canceled",)
            )
            canceled = int(cur.fetchone()[0])

            cur.execute(
                'SELECT count(*) FROM "User" WHERE "lastLoginAt" IS NULL'
                ' AND "createdAt" < now() - interval \'30 days\''
                ' AND "deletedAt" IS NULL'
            )
            never_logged_in = int(cur.fetchone()[0])

    return {
        "softDeletedUsers": {"count": soft_count, "sample": soft_sample},
        "orphanedBillingPairs": {"count": orphan_count, "sample": orphan_sample},
        "canceledSubscriptions": {"count": canceled},
        "neverLoggedIn30d": {"count": never_logged_in},
    }


def purge_orphan_billing(cur: Any) -> dict[str, Any]:
    """Delete ONLY the owner-less ``Subscription``/``UsageQuota`` rows.

    Scoped by the "no ``User`` row exists" predicate and nothing else — it can
    never reach a row belonging to a live account, whatever that account's plan,
    status or Stripe state. Runs on the caller's cursor so the deletion and its
    audit row commit together.
    """
    cur.execute(
        'DELETE FROM "Subscription" s'
        ' WHERE NOT EXISTS (SELECT 1 FROM "User" u WHERE u."id" = s."userId")'
        ' RETURNING s."userId"'
    )
    removed: set[str] = {r[0] for r in cur.fetchall()}
    subscriptions = len(removed)
    cur.execute(
        'DELETE FROM "UsageQuota" q'
        ' WHERE NOT EXISTS (SELECT 1 FROM "User" u WHERE u."id" = q."userId")'
        ' RETURNING q."userId"'
    )
    quota_ids = [r[0] for r in cur.fetchall()]
    quotas = len(quota_ids)
    removed.update(quota_ids)
    # The ids are SAMPLED, not enumerated: this set can run to tens of thousands
    # on a long-lived database, and neither an HTTP response nor an audit row is
    # the right place for a bulk export. The counts are exact; the sample is a
    # handle for eyeballing what went.
    sample = sorted(removed)[:_HYGIENE_SAMPLE]
    return {
        "userIds": sample,
        "userIdCount": len(removed),
        "subscription": subscriptions,
        "usageQuota": quotas,
    }


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


#: Refusal text for an in-app password change on the identity §14.7 owns.
#: RT-001 (runtime-defect, owner report 2026-08-16): the previous text named
#: the internal env variable and its rotation runbook IN THE HTTP RESPONSE —
#: deployment internals do not belong in an account-level flow's error. The
#: user-facing message is now professional and internal-free; the full
#: operator remedy lives in :data:`ENV_MANAGED_PASSWORD_OPS_DETAIL`, which the
#: refusing route writes to the SERVER LOG (where operators look), never to
#: HTTP. Neither carries credential material.
ENV_MANAGED_PASSWORD_MESSAGE = (
    "This account's password is managed at the deployment level and cannot be "
    "changed from the admin console. The change was refused rather than "
    "accepted and silently reverted. Please contact your operator to rotate "
    "this credential."
)

#: Operator-only detail for the same refusal — server logs only, never HTTP.
ENV_MANAGED_PASSWORD_OPS_DETAIL = (
    "Password change refused for the env-managed admin identity: "
    "AETHER_ADMIN_PASSWORD_HASH is re-applied on every API boot "
    "(apply_admin_rotation), so an in-app change would be silently reverted. "
    "To rotate for real: set AETHER_ADMIN_PASSWORD_HASH to a bcrypt hash of "
    "the new password and restart the API."
)


def env_managed_admin_email() -> Optional[str]:
    """The email address whose password §14.7 owns, or ``None``.

    :func:`apply_admin_rotation` runs on EVERY app construction and, for
    ``AETHER_ADMIN_EMAIL``, UPSERTs ``passwordHash`` from
    ``AETHER_ADMIN_PASSWORD_HASH``. For that ONE identity the environment — not
    the database — is the source of truth, so any in-app password change is
    undone at the next restart. Both variables must be present: with no
    configured hash there is nothing to re-apply and nothing to revert.

    Deliberately NOT conditioned on ``_admin_credential_problem``. A refused
    credential leaves ``passwordHash`` untouched TODAY (condition C2), but the
    operator's fix is to rotate the variable — at which point the env value is
    applied and an in-app change made in the meantime disappears. The
    environment owns this password in both dispositions.

    Reads ``os.environ`` on every call (never a module-level snapshot), so
    unsetting the variables takes effect without a code change, and returns
    only the ADDRESS — never the configured hash.
    """
    email = (os.environ.get("AETHER_ADMIN_EMAIL") or "").strip()
    pw_hash = (os.environ.get("AETHER_ADMIN_PASSWORD_HASH") or "").strip()
    if not email or not pw_hash:
        return None
    return email


def password_is_env_managed(email: Optional[str]) -> bool:
    """Is ``email`` the identity whose password §14.7 re-applies on every boot?

    Compared case-insensitively, matching the rotation's own de-privilege step
    (``lower("email")=lower(%s)``) and erring toward refusing a change that
    would be reverted rather than accepting one silently.
    """
    managed = env_managed_admin_email()
    if managed is None or not email:
        return False
    return email.strip().lower() == managed.lower()


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
