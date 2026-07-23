"""Per-user agent credential + Anthropic OAuth persistence (GAP-D1/D3/E5/NEW-001).

This module owns ALL the additive DDL introduced for per-user credentials,
per-user agent configuration, subscription-OAuth billing separation and quota
tracking. Every table is created by LAZY IDEMPOTENT DDL (ADR-TR-1) — there is
no migration runner in this repo, so ``_ensure_user_agent_tables()`` is the ONLY
mechanism that actually executes in production. The documentary mirror lives at
``apps/api/migrations/0020_per_user_agent_creds.sql`` (record only).

Secrets are stored exclusively as Fernet ciphertext plus a last-4 ``secretHint``
(see :mod:`app.services.credential_vault`); the plaintext is reconstructed
server-side only via :meth:`UserProviderCredentialRepository.get_secret` and is
NEVER serialized to an API response.

No table carries an FK to ``User`` — mirroring ``ProviderCredential`` /
``AgentProvider`` — so the shared test-suite's ``TRUNCATE "User"`` never trips
over them. First-hit creation is serialized by ONE transaction-scoped advisory
lock so concurrent ``CREATE TABLE IF NOT EXISTS`` cannot race on Postgres's
``pg_type`` index.
"""
from __future__ import annotations

from typing import Any, Optional

from app.db import get_connection, new_id, rows_to_dicts
from app.services import credential_vault

#: Distinct advisory-lock id for the per-user agent-credentials bundle.
#: (AgentConfig/AgentProvider 7420240711 … ProviderCredential 7420240716 —
#: this bundle takes the next id.)
_USER_AGENT_LOCK = 7420240717

#: Client-safe columns of ``UserProviderCredential`` (NO ciphertext / plaintext).
_UPC_MASKED = (
    '"id", "userId", "provider", "authMode", "secretHint", "baseUrl", '
    '"oauthScopes", "expiresAt", "lastVerifiedAt", "lastVerifyStatus", '
    '"createdAt", "updatedAt"'
)

#: Guard so the DDL only runs once per worker process.
_tables_ready = False


def _reset_ready_for_tests() -> None:
    """Test hook: force the DDL to re-run (used after a table DROP)."""
    global _tables_ready
    _tables_ready = False


def _ensure_user_agent_tables() -> None:
    """Create/patch the per-user agent-credential tables on first use (ADR-TR-1).

    Idempotent and additive only: ``CREATE TABLE IF NOT EXISTS`` +
    ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``. Serialized by a
    transaction-scoped advisory lock so concurrent first-hit callers can't race.
    """
    global _tables_ready
    if _tables_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_USER_AGENT_LOCK,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "UserProviderCredential" (
                    "id"                text PRIMARY KEY,
                    "userId"            text NOT NULL,
                    "provider"          text NOT NULL,
                    "authMode"          text NOT NULL
                        CHECK ("authMode" IN ('api_key', 'subscription_oauth', 'oauth_token')),
                    "ciphertext"        text NOT NULL,
                    "secretHint"        text,
                    "baseUrl"           text,
                    "oauthScopes"       text,
                    "expiresAt"         timestamptz,
                    "lastVerifiedAt"    timestamptz,
                    "lastVerifyStatus"  text,
                    "createdAt"         timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"         timestamptz NOT NULL DEFAULT now(),
                    UNIQUE ("userId", "provider")
                )
                '''
            )
            # GAP-P7-DEF-A §3.2: widen the authMode CHECK additively so a pasted
            # Claude Code OAuth token ('oauth_token') can be stored per-user. A
            # strict superset — zero existing rows invalidated, zero data loss.
            # ONLY run the ALTER when the constraint is not already widened, so we
            # do NOT take an ACCESS EXCLUSIVE lock on every process first-hit (that
            # would serialize/contend with concurrent API callers and the shared
            # test schema). A short lock_timeout makes even the one-time widening
            # fail fast rather than block indefinitely; it is retried next first-hit.
            cur.execute(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'UserProviderCredential_authMode_check'"
            )
            _crow = cur.fetchone()
            _cdef = _crow[0] if _crow else None
            if not _cdef or "oauth_token" not in _cdef:
                cur.execute("SET LOCAL lock_timeout = '4s'")
                cur.execute(
                    'ALTER TABLE "UserProviderCredential" '
                    'DROP CONSTRAINT IF EXISTS "UserProviderCredential_authMode_check"'
                )
                cur.execute(
                    'ALTER TABLE "UserProviderCredential" '
                    'ADD CONSTRAINT "UserProviderCredential_authMode_check" '
                    'CHECK ("authMode" IN (\'api_key\', \'subscription_oauth\', \'oauth_token\'))'
                )
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "AnthropicOAuthState" (
                    "stateToken"   text PRIMARY KEY,
                    "userId"       text NOT NULL,
                    "codeVerifier" text NOT NULL,
                    "createdAt"    timestamptz NOT NULL DEFAULT now(),
                    "expiresAt"    timestamptz NOT NULL DEFAULT (now() + interval '10 minutes')
                )
                '''
            )
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "AnthropicOAuthToken" (
                    "userId"        text PRIMARY KEY,
                    "ciphertext"    text NOT NULL,
                    "refreshCipher" text,
                    "secretHint"    text,
                    "expiresAt"     timestamptz,
                    "scopes"        text,
                    "createdAt"     timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"     timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            # Carries an ``id`` column and an explicit UNIQUE index on
            # (userId, provider) so it coexists with any pre-existing table of
            # the same name (a sibling feature may already own one with an
            # ``id`` primary key) while still supporting the per-user upsert.
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "AgentQuotaBlock" (
                    "id"        text PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    "userId"    text NOT NULL,
                    "provider"  text NOT NULL,
                    "expiresAt" timestamptz NOT NULL,
                    "reason"    text,
                    "createdAt" timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            cur.execute(
                'ALTER TABLE "AgentQuotaBlock" ADD COLUMN IF NOT EXISTS "expiresAt" timestamptz'
            )
            cur.execute(
                'ALTER TABLE "AgentQuotaBlock" ADD COLUMN IF NOT EXISTS "reason" text'
            )
            cur.execute(
                'ALTER TABLE "AgentQuotaBlock" ADD COLUMN IF NOT EXISTS '
                '"createdAt" timestamptz DEFAULT now()'
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "AgentQuotaBlock_user_provider_key" '
                'ON "AgentQuotaBlock" ("userId", "provider")'
            )
            # NB: the AgentConfig per-user columns (credentialRef/provider/
            # authMode/temperature/thinkingEffort) are added authoritatively in
            # ``agents._ensure_agents_tables`` — co-located with the AgentConfig
            # CREATE so they survive that table being dropped/recreated in tests.
            # AgentRun is Prisma-managed and always exists; add the audit column.
            cur.execute(
                'ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "billingAuditJson" jsonb'
            )
        conn.commit()
    _tables_ready = True


class UserProviderCredentialRepository:
    """Encrypted per-user provider credential store (UNIQUE per user+provider)."""

    def upsert(
        self,
        user_id: str,
        provider: str,
        *,
        auth_mode: str,
        secret: str,
        base_url: Optional[str] = None,
        oauth_scopes: Optional[str] = None,
        expires_at: Any = None,
    ) -> dict[str, Any]:
        """Encrypt + store this user's credential for ``provider``; masked row.

        Storing a new secret invalidates any prior verification result so a
        stale "verified" badge is never shown. Raises
        :class:`credential_vault.CredentialVaultError` when the vault key is
        missing/invalid — the router maps that to an honest 503.
        """
        ciphertext = credential_vault.encrypt(secret)
        hint = credential_vault.secret_hint(secret)
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "UserProviderCredential"
                        ("id", "userId", "provider", "authMode", "ciphertext",
                         "secretHint", "baseUrl", "oauthScopes", "expiresAt",
                         "lastVerifiedAt", "lastVerifyStatus", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, now(), now())
                    ON CONFLICT ("userId", "provider") DO UPDATE SET
                        "authMode" = EXCLUDED."authMode",
                        "ciphertext" = EXCLUDED."ciphertext",
                        "secretHint" = EXCLUDED."secretHint",
                        "baseUrl" = EXCLUDED."baseUrl",
                        "oauthScopes" = EXCLUDED."oauthScopes",
                        "expiresAt" = EXCLUDED."expiresAt",
                        "lastVerifiedAt" = NULL,
                        "lastVerifyStatus" = NULL,
                        "updatedAt" = now()
                    RETURNING {_UPC_MASKED}
                    ''',
                    (
                        new_id(), user_id, provider, auth_mode, ciphertext, hint,
                        base_url, oauth_scopes, expires_at,
                    ),
                )
                row = rows_to_dicts(cur)[0]
            conn.commit()
        return row

    def _row(self, user_id: str, provider: str) -> Optional[dict[str, Any]]:
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_UPC_MASKED}, "ciphertext" FROM "UserProviderCredential" '
                    'WHERE "userId" = %s AND "provider" = %s',
                    (user_id, provider),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def get_secret(self, user_id: str, provider: str) -> Optional[dict[str, Any]]:
        """Decrypt ``{authMode, secret, baseUrl}`` for the LLM client, or None.

        The ONLY path returning plaintext — never feed it to an API response.
        """
        row = self._row(user_id, provider)
        if not row:
            return None
        return {
            "authMode": row["authMode"],
            "secret": credential_vault.decrypt(row["ciphertext"]),
            "baseUrl": row.get("baseUrl"),
        }

    def get_secret_by_id(
        self, cred_id: str, user_id: str
    ) -> Optional[dict[str, Any]]:
        """Decrypt ``{provider, authMode, secret, baseUrl}`` for a credentialRef.

        Scoped to ``user_id`` so one user's ``credentialRef`` can never resolve
        another user's stored secret.
        """
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "provider", "authMode", "ciphertext", "baseUrl" '
                    'FROM "UserProviderCredential" WHERE "id" = %s AND "userId" = %s',
                    (cred_id, user_id),
                )
                rows = rows_to_dicts(cur)
        if not rows:
            return None
        row = rows[0]
        return {
            "provider": row["provider"],
            "authMode": row["authMode"],
            "secret": credential_vault.decrypt(row["ciphertext"]),
            "baseUrl": row.get("baseUrl"),
        }

    def get_masked(self, user_id: str, provider: str) -> Optional[dict[str, Any]]:
        row = self._row(user_id, provider)
        if not row:
            return None
        row.pop("ciphertext", None)
        return row

    def list_masked(self, user_id: str) -> list[dict[str, Any]]:
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_UPC_MASKED} FROM "UserProviderCredential" '
                    'WHERE "userId" = %s ORDER BY "provider"',
                    (user_id,),
                )
                return rows_to_dicts(cur)

    def delete(self, user_id: str, provider: str) -> bool:
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "UserProviderCredential" '
                    'WHERE "userId" = %s AND "provider" = %s',
                    (user_id, provider),
                )
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    def mark_verified(
        self, user_id: str, provider: str, status: str
    ) -> Optional[dict[str, Any]]:
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'UPDATE "UserProviderCredential" SET "lastVerifiedAt" = now(), '
                    f'"lastVerifyStatus" = %s, "updatedAt" = now() '
                    f'WHERE "userId" = %s AND "provider" = %s RETURNING {_UPC_MASKED}',
                    (status, user_id, provider),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None


class AnthropicOAuthStateRepository:
    """Short-lived PKCE state rows for the Anthropic OAuth authorize round-trip."""

    def create(self, state_token: str, user_id: str, code_verifier: str) -> None:
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "AnthropicOAuthState" '
                    '("stateToken", "userId", "codeVerifier") VALUES (%s, %s, %s)',
                    (state_token, user_id, code_verifier),
                )
            conn.commit()

    def consume(self, state_token: str) -> Optional[dict[str, Any]]:
        """Atomically fetch-and-delete a NON-expired state row (single use).

        Returns ``None`` when the token is unknown or already expired — the
        caller then rejects the callback. Deleting in the same statement means a
        state token can never be replayed.
        """
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "AnthropicOAuthState" '
                    'WHERE "stateToken" = %s AND "expiresAt" > now() '
                    'RETURNING "userId", "codeVerifier"',
                    (state_token,),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

class AnthropicOAuthTokenRepository:
    """Encrypted subscription OAuth access/refresh token store (one per user)."""

    def upsert(
        self,
        user_id: str,
        *,
        access_ciphertext: str,
        refresh_ciphertext: Optional[str],
        secret_hint: Optional[str],
        expires_at: Any,
        scopes: Optional[str],
    ) -> None:
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "AnthropicOAuthToken"
                        ("userId", "ciphertext", "refreshCipher", "secretHint",
                         "expiresAt", "scopes", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT ("userId") DO UPDATE SET
                        "ciphertext" = EXCLUDED."ciphertext",
                        "refreshCipher" = EXCLUDED."refreshCipher",
                        "secretHint" = EXCLUDED."secretHint",
                        "expiresAt" = EXCLUDED."expiresAt",
                        "scopes" = EXCLUDED."scopes",
                        "updatedAt" = now()
                    ''',
                    (
                        user_id, access_ciphertext, refresh_ciphertext,
                        secret_hint, expires_at, scopes,
                    ),
                )
            conn.commit()

    def get(self, user_id: str) -> Optional[dict[str, Any]]:
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "userId", "ciphertext", "refreshCipher", "secretHint", '
                    '"expiresAt", "scopes" FROM "AnthropicOAuthToken" '
                    'WHERE "userId" = %s',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def mark_needs_reauth(self, user_id: str) -> None:
        """Clear the stored expiry so the next resolve treats it as unusable."""
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "AnthropicOAuthToken" SET "scopes" = \'needs_reauth\', '
                    '"updatedAt" = now() WHERE "userId" = %s',
                    (user_id,),
                )
            conn.commit()


class AgentQuotaBlockRepository:
    """Per-user, per-provider quota-exhaustion cooldown (subscription 429s)."""

    def set_block(
        self, user_id: str, provider: str, *, expires_at: Any, reason: str
    ) -> None:
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "AgentQuotaBlock"
                        ("id", "userId", "provider", "expiresAt", "reason", "createdAt")
                    VALUES (%s, %s, %s, %s, %s, now())
                    ON CONFLICT ("userId", "provider") DO UPDATE SET
                        "expiresAt" = EXCLUDED."expiresAt",
                        "reason" = EXCLUDED."reason",
                        "createdAt" = now()
                    ''',
                    (new_id(), user_id, provider, expires_at, reason),
                )
            conn.commit()

    def get_active(self, user_id: str, provider: str) -> Optional[dict[str, Any]]:
        """The active (non-expired) block for user+provider, or ``None``."""
        _ensure_user_agent_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "userId", "provider", "expiresAt", "reason" '
                    'FROM "AgentQuotaBlock" '
                    'WHERE "userId" = %s AND "provider" = %s AND "expiresAt" > now()',
                    (user_id, provider),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None
