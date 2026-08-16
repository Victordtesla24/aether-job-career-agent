"""Password-reset token store (O-4, S-FIX slice D).

There is no migration runner in this repo (ADR-TR-1); ``_ensure_password_reset_table``
is the ONLY mechanism that creates ``"PasswordResetToken"`` in production. The
documentary mirror lives at ``apps/api/migrations/0028_password_reset.sql``.
Additive only: ``CREATE TABLE/INDEX IF NOT EXISTS`` — never DROP / ALTER TYPE /
rename. No FK to ``"User"`` (shared-test-DB TRUNCATE safety, matching
``Offer``/``AdminAuditLog``: a concurrent test swarm's ``TRUNCATE "User"
CASCADE`` must not silently wipe another swarm's in-flight reset tokens).

Tokens are single-use and hashed at rest (sha256): the raw value exists only
in the outbound email body and this module's return value, never persisted,
so a DB read (backup, replica, or compromise) can never itself be used to
reset an account.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

#: Distinct advisory-lock id for this table's DDL (registry: grep
#: ``pg_advisory_xact_lock`` across apps/api/app — highest in use before this
#: was 7420260805, claimed by ``db.ensure_password_reset_columns``).
_TOKEN_TABLE_LOCK = 7420260806

#: Guard so the DDL only runs once per worker process.
_token_table_ready = False

#: A reset link is valid for one hour from issuance (per the finding).
TOKEN_TTL = timedelta(hours=1)


def _ensure_password_reset_table() -> None:
    """Idempotently create the ``"PasswordResetToken"`` table on first use.

    Mirrors ``offers._ensure_offers_table`` / ``db.ensure_*_columns``: a
    lock-free existence fast-path, then a transaction-scoped advisory lock
    serialising concurrent first-hit callers around ``CREATE TABLE IF NOT
    EXISTS``. ``TRUNCATE`` never drops tables, so this survives the
    test-suite teardown.
    """
    global _token_table_ready
    if _token_table_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_name = 'PasswordResetToken'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _token_table_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TOKEN_TABLE_LOCK,))
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS "PasswordResetToken" (
                    "id"        text        PRIMARY KEY,
                    "userId"    text        NOT NULL,
                    "tokenHash" text        NOT NULL,
                    "expiresAt" timestamptz NOT NULL,
                    "usedAt"    timestamptz,
                    "createdAt" timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "idx_password_reset_token_hash"'
                ' ON "PasswordResetToken" ("tokenHash")'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_password_reset_token_userId"'
                ' ON "PasswordResetToken" ("userId")'
            )
        conn.commit()
    _token_table_ready = True


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_reset_token(user_id: str) -> str:
    """Mint a single-use reset token for ``user_id``; returns the RAW token.

    Only the sha256 hash is persisted, with a 1-hour expiry. The raw value is
    never logged — it is returned solely so the caller can embed it in the
    outbound reset-link email.
    """
    _ensure_password_reset_table()
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + TOKEN_TTL
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "PasswordResetToken" ("id","userId","tokenHash","expiresAt")'
                " VALUES (%s,%s,%s,%s)",
                (new_id(), user_id, _hash_token(raw_token), expires_at),
            )
        conn.commit()
    return raw_token


def consume_reset_token(raw_token: str) -> str | None:
    """Validate+consume ``raw_token``; returns the owning ``userId`` or ``None``.

    A token is valid exactly once: unexpired and unused. On success, every
    OTHER outstanding token for the same user is also marked used in the same
    transaction, so a leaked-but-unused sibling reset link can't be replayed
    after a successful reset.
    """
    if not raw_token or not raw_token.strip():
        return None
    _ensure_password_reset_table()
    token_hash = _hash_token(raw_token.strip())
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "userId" FROM "PasswordResetToken"'
                ' WHERE "tokenHash"=%s AND "usedAt" IS NULL AND "expiresAt" > now()',
                (token_hash,),
            )
            rows: list[dict[str, Any]] = rows_to_dicts(cur)
            if not rows:
                conn.commit()
                return None
            user_id = rows[0]["userId"]
            cur.execute(
                'UPDATE "PasswordResetToken" SET "usedAt"=now()'
                ' WHERE "userId"=%s AND "usedAt" IS NULL',
                (user_id,),
            )
        conn.commit()
    return user_id


#: The reset email's copy, in one place so the text and HTML alternatives can
#: never drift apart. The TTL sentence is load-bearing honesty: it states the
#: real :data:`TOKEN_TTL` and the real single-use rule.
_RESET_INTRO = (
    "You (or someone with access to your email) requested a password "
    "reset for your Aether account."
)
_RESET_TTL_NOTE = (
    "This link expires in 1 hour and can only be used once. If you did "
    "not request this, you can safely ignore this email — your password "
    "will not change."
)
_RESET_CTA_LABEL = "Reset your password"


def build_reset_email_body(reset_url: str) -> str:
    """Plain-text body for the reset email — one honest link, one honest TTL.

    Kept as the plain-text half of :func:`build_reset_email_bodies` so any
    caller that only wants text (and every existing test) keeps working
    unchanged.
    """
    return (
        f"{_RESET_INTRO}\n\n"
        f"{_RESET_CTA_LABEL}: {reset_url}\n\n"
        f"{_RESET_TTL_NOTE}"
    )


def build_reset_email_bodies(reset_url: str) -> tuple[str, str]:
    """``(plain_text, branded_html)`` for the reset email.

    The HTML is rendered by :mod:`app.services.email_branding` — the single
    home for Aether-owned email templates (owner directive 2026-08-16) — so
    the reset link arrives in the product's own obsidian-and-gilt identity.
    The copy is identical in both parts: same link, same honest TTL, same
    "ignore this if it wasn't you" reassurance. Nothing is added to the HTML
    that the text part does not also say.
    """
    from app.services.email_branding import (
        divider,
        paragraph,
        render_branded_email,
    )

    text_body = build_reset_email_body(reset_url)
    html_body, _branded_text = render_branded_email(
        "Reset your Aether password",
        [
            paragraph(_RESET_INTRO),
            paragraph(
                "Use the button below — or paste this link into your "
                f"browser:\n{reset_url}"
            ),
            divider(),
            paragraph(_RESET_TTL_NOTE),
        ],
        cta={"label": _RESET_CTA_LABEL, "url": reset_url},
        footer_note=(
            "Aether Career Job Agent — this is an automated security email; "
            "nobody at Aether can see or set your password."
        ),
        preheader="Your Aether password-reset link (valid for 1 hour).",
    )
    return text_body, html_body
