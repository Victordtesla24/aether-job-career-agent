"""User repository — raw psycopg2 against the Prisma ``User`` table (P2-S01)."""
from __future__ import annotations

import re
from typing import Any

from app.db import (
    ensure_admin_user_columns,
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
        dependency can enforce suspension (403) and admin gating in one query.
        ``ensure_admin_user_columns`` keeps the read safe on the older test
        schema that predates the columns.
        """
        ensure_admin_user_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_USER_COLUMNS}, "isAdmin", "suspended" '
                    'FROM "User" WHERE "id" = %s',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

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
