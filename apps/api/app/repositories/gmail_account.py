"""GmailAccount persistence — per-user MULTI-account Gmail OAuth tokens (GAP-D2).

A user may connect several Gmail inboxes. Each connected inbox is one row in the
additive ``GmailAccount`` table, keyed by the surrogate ``id`` and carrying its
own ``accountEmail`` plus an ``isPrimary`` flag (exactly one primary per user,
enforced by a partial unique index). Connecting a second Gmail INSERTs a new row
— it never overwrites a different account's token.

Relationship to :class:`app.repositories.google_credential.GoogleCredentialRepository`
(GAP-D2 additive design):

* ``GoogleCredential`` is the LEGACY single-account table (PK ``userId``). It is
  left **completely untouched** — never altered, never written to going forward —
  so a rollback to the previous release (whose upsert does
  ``ON CONFLICT ("userId")``) keeps working. It serves only as the one-time
  backfill source and the rollback fallback.
* ``GmailAccount`` is the AUTHORITATIVE store for the multi-account world: every
  read/write of a Gmail token goes through here.

Secrets at rest: the access/refresh tokens are encrypted with the Fernet
credential vault (``accessTokenCipher`` / ``refreshTokenCipher``) — the plaintext
is only ever held in memory to mint API calls and is NEVER serialized to a
client. When the vault key is missing/rotated a token decrypts to ``None`` and
the caller degrades honestly ("reconnect") rather than serving garbage.

The table carries no FK to ``User`` — mirroring ``AgentConfig`` /
``GoogleCredential`` / ``CareerProfile`` — so the shared test-suite's
``TRUNCATE "User"`` never trips over it. First-hit DDL is serialized by a
transaction-scoped advisory lock so concurrent ``CREATE TABLE``/``CREATE INDEX``
cannot race on Postgres's ``pg_type`` index (ADR-TR-1 lazy idempotent DDL).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.db import get_connection, new_id, rows_to_dicts
from app.services import credential_vault

#: Distinct advisory-lock id (AgentConfig 711, User 712, CareerProfile 713,
#: OutreachTask 714, GoogleCredential 715, EmailThread gmail cols 716,
#: UserProviderCredential 717, GmailAccount 718).
_GMAIL_ACCOUNT_LOCK = 7420240718

#: Raw columns persisted by the table (ciphertext, never plaintext tokens).
_RAW_COLS = (
    '"id", "userId", "accountEmail", "isPrimary", "accessTokenCipher", '
    '"refreshTokenCipher", "tokenExpiry", "scopes", "syncStatus", '
    '"lastSyncedAt", "createdAt", "updatedAt"'
)

#: Guard so the (idempotent) DDL + backfill only run once per worker process.
_table_ready = False


def _mask_email(email: Optional[str]) -> Optional[str]:
    """Mask a Gmail address for client display: ``jane.doe@gmail.com`` ->
    ``j******e@gmail.com``. Presentation only — never a lookup key."""
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = local[0] + "*"
    else:
        masked = local[0] + ("*" * (len(local) - 2)) + local[-1]
    return f"{masked}@{domain}"


def _encrypt_optional(secret: Optional[str]) -> Optional[str]:
    """Encrypt a non-empty token to ciphertext; pass ``None``/empty through so an
    absent token stays absent (never a spurious ciphertext)."""
    if not secret:
        return None
    return credential_vault.encrypt(secret)


def _decrypt_optional(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a stored token cipher back to plaintext, degrading to ``None`` when
    the key is missing/rotated (honest reconnect path) rather than raising into
    the read."""
    if not ciphertext:
        return None
    try:
        return credential_vault.decrypt(ciphertext)
    except credential_vault.CredentialVaultError:
        return None


class GmailAccountRepository:
    """Read/write access to the multi-account ``GmailAccount`` store."""

    # ------------------------------------------------------------------ DDL
    def _ensure_table(self) -> None:
        if _table_ready:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Fast path: the one-primary partial index is the marker that the
                # full migration has run in this schema.
                cur.execute(
                    "SELECT count(*) FROM pg_indexes"
                    " WHERE indexname = 'uq_gmailaccount_one_primary'"
                    " AND schemaname = ANY(current_schemas(false))"
                )
                row = cur.fetchone()
                if row and row[0] == 1:
                    self._mark_ready()
                    return
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s)", (_GMAIL_ACCOUNT_LOCK,)
                )
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS "GmailAccount" (
                        "id"                 text PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        "userId"             text NOT NULL,
                        "accountEmail"       text,
                        "accessTokenCipher"  text,
                        "refreshTokenCipher" text,
                        "tokenExpiry"        timestamptz,
                        "scopes"             text,
                        "isPrimary"          boolean NOT NULL DEFAULT false,
                        "syncStatus"         text,
                        "lastSyncedAt"       timestamptz,
                        "createdAt"          timestamptz NOT NULL DEFAULT now(),
                        "updatedAt"          timestamptz NOT NULL DEFAULT now()
                    )
                    '''
                )
                cur.execute(
                    'CREATE UNIQUE INDEX IF NOT EXISTS uq_gmailaccount_user_email'
                    ' ON "GmailAccount"("userId","accountEmail")'
                )
                cur.execute(
                    'CREATE UNIQUE INDEX IF NOT EXISTS uq_gmailaccount_one_primary'
                    ' ON "GmailAccount"("userId") WHERE "isPrimary"'
                )
            conn.commit()
        # One-time idempotent backfill from the legacy single-account table.
        self._backfill_from_google_credential()
        self._mark_ready()

    def _backfill_from_google_credential(self) -> None:
        """Copy any legacy ``GoogleCredential`` rows into ``GmailAccount`` that do
        not already have a matching ``(userId, accountEmail)`` account. Tokens are
        encrypted into the cipher columns; the backfilled row is primary only when
        the user has no primary yet. Safe to run repeatedly (WHERE-NOT-EXISTS)."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_name = 'GoogleCredential'"
                    " AND table_schema = ANY(current_schemas(false))"
                )
                exists = cur.fetchone()
                if not exists or exists[0] == 0:
                    return
                cur.execute(
                    'SELECT "userId", "googleEmail", "refreshToken", "accessToken",'
                    ' "accessTokenExpiresAt", "scopes", "connectedAt"'
                    ' FROM "GoogleCredential"'
                )
                legacy = cur.fetchall()
                for (
                    uid,
                    gemail,
                    refresh_token,
                    access_token,
                    expires_at,
                    scopes,
                    connected_at,
                ) in legacy:
                    cur.execute(
                        'SELECT 1 FROM "GmailAccount"'
                        ' WHERE "userId" = %s'
                        ' AND "accountEmail" IS NOT DISTINCT FROM %s LIMIT 1',
                        (uid, gemail),
                    )
                    if cur.fetchone():
                        continue
                    cur.execute(
                        'SELECT 1 FROM "GmailAccount"'
                        ' WHERE "userId" = %s AND "isPrimary" LIMIT 1',
                        (uid,),
                    )
                    is_primary = cur.fetchone() is None
                    cur.execute(
                        '''
                        INSERT INTO "GmailAccount"
                            ("id", "userId", "accountEmail", "accessTokenCipher",
                             "refreshTokenCipher", "tokenExpiry", "scopes",
                             "isPrimary", "syncStatus", "createdAt", "updatedAt")
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                COALESCE(%s, now()), now())
                        ON CONFLICT DO NOTHING
                        ''',
                        (
                            new_id(),
                            uid,
                            gemail,
                            _encrypt_optional(access_token),
                            _encrypt_optional(refresh_token),
                            expires_at,
                            scopes,
                            is_primary,
                            "backfilled",
                            connected_at,
                        ),
                    )
            conn.commit()

    @staticmethod
    def _mark_ready() -> None:
        global _table_ready
        _table_ready = True

    # ---------------------------------------------------------------- mapping
    @staticmethod
    def _to_internal(raw: dict[str, Any]) -> dict[str, Any]:
        """Map a raw ``GmailAccount`` row to the internal dict shape the rest of
        the code expects (decrypted tokens; legacy key aliases so
        ``GmailService`` / the OAuth callback keep working unchanged).

        WARNING: the returned dict contains plaintext ``refreshToken`` /
        ``accessToken`` — these are secrets, never serialize them to a client."""
        return {
            "id": raw.get("id"),
            "userId": raw.get("userId"),
            "accountEmail": raw.get("accountEmail"),
            # Legacy alias kept so callers that historically read ``googleEmail``
            # (settings connected-accounts surface) keep resolving.
            "googleEmail": raw.get("accountEmail"),
            "isPrimary": bool(raw.get("isPrimary")),
            "refreshToken": _decrypt_optional(raw.get("refreshTokenCipher")),
            "accessToken": _decrypt_optional(raw.get("accessTokenCipher")),
            "accessTokenExpiresAt": raw.get("tokenExpiry"),
            "tokenExpiry": raw.get("tokenExpiry"),
            "scopes": raw.get("scopes"),
            "syncStatus": raw.get("syncStatus"),
            "lastSyncedAt": raw.get("lastSyncedAt"),
            "connectedAt": raw.get("createdAt"),
            "createdAt": raw.get("createdAt"),
            "updatedAt": raw.get("updatedAt"),
        }

    # --------------------------------------------------------------- reads
    def get(
        self, user_id: str, account_id: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Full stored account row (decrypted tokens).

        With ``account_id`` returns that specific account (scoped to ``user_id``).
        Without it returns the user's PRIMARY account (falling back to the oldest
        connected) — the identity every existing single-account caller expects.

        WARNING: the returned dict contains ``refreshToken``/``accessToken``.
        These are secrets — never include them in an API response.
        """
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                if account_id is not None:
                    cur.execute(
                        f'SELECT {_RAW_COLS} FROM "GmailAccount"'
                        ' WHERE "id" = %s AND "userId" = %s',
                        (account_id, user_id),
                    )
                else:
                    cur.execute(
                        f'SELECT {_RAW_COLS} FROM "GmailAccount"'
                        ' WHERE "userId" = %s'
                        ' ORDER BY "isPrimary" DESC, "createdAt" ASC LIMIT 1',
                        (user_id,),
                    )
                rows = rows_to_dicts(cur)
        return self._to_internal(rows[0]) if rows else None

    def get_by_email(
        self, user_id: str, account_email: Optional[str]
    ) -> Optional[dict[str, Any]]:
        """The row for ``(user_id, account_email)`` if present, else ``None``.
        ``account_email`` may be ``None`` — matched with ``IS NOT DISTINCT FROM``
        so NULL matches NULL."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_RAW_COLS} FROM "GmailAccount"'
                    ' WHERE "userId" = %s AND "accountEmail" IS NOT DISTINCT FROM %s'
                    ' LIMIT 1',
                    (user_id, account_email),
                )
                rows = rows_to_dicts(cur)
        return self._to_internal(rows[0]) if rows else None

    def list_accounts(self, user_id: str) -> list[dict[str, Any]]:
        """All accounts for ``user_id`` (primary first, then oldest), decrypted.

        WARNING: rows contain secret tokens — use :meth:`list_public` for any
        client-facing surface.
        """
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_RAW_COLS} FROM "GmailAccount"'
                    ' WHERE "userId" = %s'
                    ' ORDER BY "isPrimary" DESC, "createdAt" ASC',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return [self._to_internal(r) for r in rows]

    def list_public(self, user_id: str) -> list[dict[str, Any]]:
        """Client-safe, masked projection of every connected account (NO tokens)."""
        return [
            {
                "id": row.get("id"),
                "accountEmail": _mask_email(row.get("accountEmail")),
                "isPrimary": bool(row.get("isPrimary")),
                "scopes": row.get("scopes"),
                "connectedAt": row.get("connectedAt"),
                "updatedAt": row.get("updatedAt"),
            }
            for row in self.list_accounts(user_id)
        ]

    def public_view(self, user_id: str) -> Optional[dict[str, Any]]:
        """Client-safe projection of the PRIMARY account (NO tokens).

        Preserved for existing single-account callers (settings
        connected-accounts). Never exposes the refresh/access tokens. Returns the
        UNMASKED ``googleEmail`` to match the legacy ``public_view`` contract that
        settings renders verbatim."""
        row = self.get(user_id)
        if not row:
            return None
        return {
            "googleEmail": row.get("accountEmail"),
            "scopes": row.get("scopes"),
            "connectedAt": row.get("connectedAt"),
            "updatedAt": row.get("updatedAt"),
        }

    def is_connected(self, user_id: str) -> bool:
        """Cheap existence check — the single source of truth for "is Gmail
        connected?" used by the inbox status and the send-gate on every call.
        True when the user has AT LEAST ONE connected account."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT 1 FROM "GmailAccount" WHERE "userId" = %s LIMIT 1',
                    (user_id,),
                )
                return cur.fetchone() is not None

    # --------------------------------------------------------------- writes
    def upsert_account(
        self,
        user_id: str,
        *,
        account_email: Optional[str],
        refresh_token: Optional[str],
        access_token: Optional[str] = None,
        access_token_expires_at: Optional[datetime] = None,
        scopes: Optional[str] = None,
    ) -> dict[str, Any]:
        """Link a Gmail account to ``user_id`` by ``account_email``.

        If a row already exists for ``(user_id, account_email)`` the tokens are
        ROTATED in place (refresh token preserved when Google withholds a new
        one). Otherwise a NEW row is INSERTed — a second, different account can
        never overwrite the first. The new row is primary only when the user has
        no primary yet.
        """
        self._ensure_table()
        refresh_cipher = _encrypt_optional(refresh_token)
        access_cipher = _encrypt_optional(access_token)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "id" FROM "GmailAccount"'
                    ' WHERE "userId" = %s AND "accountEmail" IS NOT DISTINCT FROM %s'
                    ' LIMIT 1',
                    (user_id, account_email),
                )
                existing = cur.fetchone()
                if existing:
                    # Rotate: keep the stored refresh cipher when Google returns
                    # no new refresh token (COALESCE on the incoming cipher).
                    cur.execute(
                        f'''
                        UPDATE "GmailAccount" SET
                            "refreshTokenCipher" = COALESCE(%s, "refreshTokenCipher"),
                            "accessTokenCipher" = %s,
                            "tokenExpiry" = %s,
                            "scopes" = COALESCE(%s, "scopes"),
                            "updatedAt" = now()
                        WHERE "id" = %s
                        RETURNING {_RAW_COLS}
                        ''',
                        (
                            refresh_cipher,
                            access_cipher,
                            access_token_expires_at,
                            scopes,
                            existing[0],
                        ),
                    )
                else:
                    cur.execute(
                        'SELECT 1 FROM "GmailAccount"'
                        ' WHERE "userId" = %s AND "isPrimary" LIMIT 1',
                        (user_id,),
                    )
                    is_primary = cur.fetchone() is None
                    cur.execute(
                        f'''
                        INSERT INTO "GmailAccount"
                            ("id", "userId", "accountEmail", "accessTokenCipher",
                             "refreshTokenCipher", "tokenExpiry", "scopes",
                             "isPrimary", "createdAt", "updatedAt")
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                        RETURNING {_RAW_COLS}
                        ''',
                        (
                            new_id(),
                            user_id,
                            account_email,
                            access_cipher,
                            refresh_cipher,
                            access_token_expires_at,
                            scopes,
                            is_primary,
                        ),
                    )
                row = rows_to_dicts(cur)[0]
            conn.commit()
        return self._to_internal(row)

    def set_primary(self, user_id: str, account_id: str) -> bool:
        """Make ``account_id`` the user's primary inbox (unique). Returns False
        when the account does not belong to the user."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT 1 FROM "GmailAccount"'
                    ' WHERE "id" = %s AND "userId" = %s',
                    (account_id, user_id),
                )
                if cur.fetchone() is None:
                    return False
                # Clear the old primary first, then set the new one — both in the
                # same transaction so the partial unique index is never violated.
                cur.execute(
                    'UPDATE "GmailAccount" SET "isPrimary" = false,'
                    ' "updatedAt" = now() WHERE "userId" = %s AND "isPrimary"',
                    (user_id,),
                )
                cur.execute(
                    'UPDATE "GmailAccount" SET "isPrimary" = true,'
                    ' "updatedAt" = now() WHERE "id" = %s AND "userId" = %s',
                    (account_id, user_id),
                )
            conn.commit()
        return True

    def update_access_token(
        self,
        user_id: str,
        access_token: str,
        expires_at: Optional[datetime],
        account_id: Optional[str] = None,
    ) -> None:
        """Persist a freshly refreshed access token (called after auto-refresh).
        Targets ``account_id`` when given, else the user's primary account."""
        self._ensure_table()
        access_cipher = _encrypt_optional(access_token)
        with get_connection() as conn:
            with conn.cursor() as cur:
                if account_id is not None:
                    cur.execute(
                        'UPDATE "GmailAccount" SET "accessTokenCipher" = %s,'
                        ' "tokenExpiry" = %s, "updatedAt" = now()'
                        ' WHERE "id" = %s AND "userId" = %s',
                        (access_cipher, expires_at, account_id, user_id),
                    )
                else:
                    cur.execute(
                        'UPDATE "GmailAccount" SET "accessTokenCipher" = %s,'
                        ' "tokenExpiry" = %s, "updatedAt" = now()'
                        ' WHERE "id" = ('
                        '   SELECT "id" FROM "GmailAccount" WHERE "userId" = %s'
                        '   ORDER BY "isPrimary" DESC, "createdAt" ASC LIMIT 1)',
                        (access_cipher, expires_at, user_id),
                    )
            conn.commit()

    def mark_synced(self, account_id: str) -> None:
        """Record a successful sync timestamp/status for one account (best-effort
        UI signal; never gates sending)."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "GmailAccount" SET "syncStatus" = %s,'
                    ' "lastSyncedAt" = now(), "updatedAt" = now()'
                    ' WHERE "id" = %s',
                    ("synced", account_id),
                )
            conn.commit()

    def delete_account(
        self, user_id: str, account_id: str
    ) -> Optional[dict[str, Any]]:
        """Remove ONE account (scoped to the user) and return the deleted row
        (decrypted, server-side, for token revocation) or ``None`` when not
        found. Other accounts are untouched; if the removed row was primary
        another account is promoted so the user always keeps a primary."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_RAW_COLS} FROM "GmailAccount"'
                    ' WHERE "id" = %s AND "userId" = %s',
                    (account_id, user_id),
                )
                rows = rows_to_dicts(cur)
                if not rows:
                    return None
                deleted = self._to_internal(rows[0])
                cur.execute(
                    'DELETE FROM "GmailAccount"'
                    ' WHERE "id" = %s AND "userId" = %s',
                    (account_id, user_id),
                )
                if deleted.get("isPrimary"):
                    cur.execute(
                        'UPDATE "GmailAccount" SET "isPrimary" = true,'
                        ' "updatedAt" = now() WHERE "id" = ('
                        '   SELECT "id" FROM "GmailAccount" WHERE "userId" = %s'
                        '   ORDER BY "createdAt" ASC LIMIT 1)',
                        (user_id,),
                    )
            conn.commit()
        return deleted

    def disconnect(self, user_id: str) -> None:
        """Remove ALL of the user's connected accounts (full Gmail disconnect)."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "GmailAccount" WHERE "userId" = %s', (user_id,)
                )
            conn.commit()
