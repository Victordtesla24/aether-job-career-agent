"""User repository — raw psycopg2 against the Prisma ``User`` table (P2-S01)."""
from __future__ import annotations

import re
import time
from typing import Any

from app.db import (
    ensure_admin_user_columns,
    ensure_password_reset_columns,
    ensure_user_lifecycle_columns,
    ensure_user_profile_columns,
    get_connection,
    new_id,
    rows_to_dicts,
)
from app.security import BCRYPT_MAX_PASSWORD_BYTES

#: Columns returned to callers. ``passwordHash`` is included so the auth layer
#: can verify credentials — routers must never serialize it outward.
_USER_COLUMNS = '"id", "email", "name", "image", "passwordHash", "createdAt", "updatedAt"'

#: Password policy: at least 8 characters, at least one digit, and at most
#: ``BCRYPT_MAX_PASSWORD_BYTES`` (72) UTF-8 bytes. The upper bound closes
#: MV-signup-001: bcrypt silently truncates past 72 bytes, so without it a
#: different password sharing only the first 72 bytes would authenticate.
MIN_PASSWORD_LENGTH = 8
_DIGIT_RE = re.compile(r"\d")


class DuplicateEmailError(Exception):
    """Raised when registering an email that already exists."""


def validate_password_policy(password: str) -> list[str]:
    """Return a list of human-readable policy violations (empty == valid)."""
    problems: list[str] = []
    # GOLD-MASTER-V2 §15 / signup-nul-500-fix: bcrypt's C extension refuses a
    # NUL byte (\x00) with a raw ``passlib.exc.PasswordValueError`` at HASH
    # TIME, not at the DB layer — a password never reaches the DB cursor as a
    # raw string, so the blanket ``_NulByteGuardCursor`` in app/db.py never
    # sees it and ``POST /auth/register`` 500'd. Checked here, at the SAME
    # validation layer already used for the length/digit/max-byte checks
    # below, so the contract matches how ``EmailStr`` already rejects a NUL
    # byte in the email field: a clean 422 before the handler ever runs, never
    # a 500 from an uncaught bcrypt exception.
    if "\x00" in password:
        problems.append("password must not contain a NUL byte")
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        problems.append(
            f"password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes"
        )
    if not _DIGIT_RE.search(password):
        problems.append("password must contain at least one digit")
    return problems


class UserRepository:
    """CRUD over the ``User`` table using short-lived psycopg2 connections."""

    def create(
        self, email: str, password_hash: str, name: str | None = None
    ) -> dict[str, Any]:
        """Insert a user; raise ``DuplicateEmailError`` on an email collision.

        ``name`` is an optional display name persisted on the row (NULL when
        omitted); the parameter defaults so existing two-argument callers stay
        source-compatible.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "User" ("id", "email", "name", "passwordHash", "updatedAt")
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT ("email") DO NOTHING
                    RETURNING {_USER_COLUMNS}
                    ''',
                    (new_id(), email, name, password_hash),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        if not rows:
            raise DuplicateEmailError(email)
        return rows[0]

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        return self._get_one('"email" = %s', (email,))

    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        return self._get_one('"id" = %s', (user_id,))

    def get_auth_context(self, user_id: str) -> dict[str, Any] | None:
        """User row plus the additive admin/security flags for the auth guard.

        Projects ``isAdmin`` + ``suspended`` (default ``false``) so the auth
        dependency can enforce suspension (403) and admin gating in one query,
        plus ``passwordChangedAt`` (O-4) so it can invalidate any session token
        minted before the user's last password reset. ``ensure_admin_user_columns``
        / ``ensure_password_reset_columns`` keep the read safe on the older test
        schema that predates these columns.
        """
        ensure_admin_user_columns()
        ensure_password_reset_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_USER_COLUMNS}, "isAdmin", "suspended", "passwordChangedAt" '
                    'FROM "User" WHERE "id" = %s',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def set_password(
        self,
        user_id: str,
        password_hash: str,
        cur: Any = None,
        *,
        must_change: bool = False,
    ) -> None:
        """Set a new password hash and stamp ``passwordChangedAt`` (O-4).

        Used by ``POST /auth/reset-password``. Stamping the timestamp is the
        session-invalidation mechanism: every JWT issued before this moment
        carries an ``iat`` earlier than the new value and is rejected by
        ``app.middleware.auth.get_current_user`` on its next use, forcing a
        fresh ``/login`` with the new password.

        ``cur`` (optional) writes inside the caller's OPEN transaction and does
        NOT commit, so an admin route can commit the change together with the
        ``AdminAuditLog`` row that records it — otherwise a failure between the
        two leaves a durable, unaudited password change (and a target whose
        sessions were silently invalidated). The caller must have run
        ``ensure_password_reset_columns()`` AND
        ``ensure_user_lifecycle_columns()`` before opening that transaction.

        ``must_change`` (ADMIN-2.0) writes ``User.mustChangePassword``. It
        defaults to ``False`` so setting a password CLEARS a pending
        "temporary credential" flag — which is what makes the flag truthful:
        an admin-created account carries ``mustChangePassword=true`` until its
        owner actually chooses a password, and not one request longer. Only
        ``POST /admin/users`` passes ``True``.
        """

        def _run(c: Any) -> None:
            # ``passwordChangedAt`` is stamped from THIS process's clock
            # (``to_timestamp``), NOT the database's ``now()``: the O-4 check in
            # ``get_current_user`` compares this stamp against a JWT ``iat``
            # minted by this same process, and comparing timestamps from two
            # different clocks re-introduces their skew into the grace window.
            # A DB clock observed ~0.8s ahead of the API clock falsely 401'd a
            # login made immediately AFTER the change — for the token's whole
            # TTL. Same-clock stamping makes the comparison exact; ``updatedAt``
            # stays on DB ``now()`` (nothing compares it to an API timestamp).
            c.execute(
                'UPDATE "User" SET "passwordHash"=%s,'
                ' "passwordChangedAt"=to_timestamp(%s),'
                ' "mustChangePassword"=%s, "updatedAt"=now() WHERE "id"=%s',
                (password_hash, time.time(), bool(must_change), user_id),
            )

        if cur is not None:
            _run(cur)
            return
        ensure_password_reset_columns()
        ensure_user_lifecycle_columns()
        with get_connection() as conn:
            with conn.cursor() as c:
                _run(c)
            conn.commit()

    def touch_last_login(self, user_id: str) -> None:
        """Best-effort stamp of the user's last successful login (§15 list).

        Additive column write; a failure must never block login, so callers
        guard this. ``ensure_admin_user_columns`` guarantees the column exists.
        """
        ensure_admin_user_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "User" SET "lastLoginAt"=now() WHERE "id"=%s', (user_id,)
                )
            conn.commit()

    def get_by_username_or_email(self, identifier: str) -> dict[str, Any] | None:
        """Resolve a user by exact ``email`` or case-insensitive ``username``.

        Login accepts a single identifier that may be either credential. Both
        columns are UNIQUE, so at most one row matches per column; when a value
        happens to match one user's email and another's username, the exact
        email match wins (deterministic ``ORDER BY``). ``username`` is an
        additive column, so ``ensure_user_profile_columns`` is invoked first to
        keep the lookup safe on the older test schema that predates it.
        """
        ensure_user_profile_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_USER_COLUMNS} FROM "User"'
                    ' WHERE "email" = %s OR lower("username") = lower(%s)'
                    ' ORDER BY ("email" = %s) DESC LIMIT 1',
                    (identifier, identifier, identifier),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def get_target_role(self, user_id: str) -> str:
        """The user's configured workspace ``targetRole`` (``''`` when unset).

        ``targetRole`` is an additive profile column that the default
        ``_USER_COLUMNS`` projection deliberately omits (login/auth never need
        it), so it is read here with its own guarded SELECT — mirroring
        ``_user_search_defaults`` in the agents router.
        ``ensure_user_profile_columns`` keeps the read safe on the older test
        schema that predates the column.
        """
        ensure_user_profile_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "targetRole" FROM "User" WHERE "id" = %s', (user_id,)
                )
                rows = rows_to_dicts(cur)
        return (rows[0].get("targetRole") or "").strip() if rows else ""

    def _get_one(self, where: str, params: tuple) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT {_USER_COLUMNS} FROM "User" WHERE {where}', params)
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None
