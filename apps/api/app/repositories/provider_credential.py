"""ProviderCredential persistence — encrypted LLM provider secrets (ADR-PC-3).

One row per PROVIDER (deployment-wide, not per-user): the credential a model's
resolved provider is billed against. The secret is stored only as Fernet
ciphertext plus a last-4 ``secretHint``; the plaintext is reconstructed
server-side exclusively via :meth:`get_secret`, which the LLM client calls to
mint the outbound Authorization/x-api-key header. It is NEVER serialized to an
API response — the router uses :meth:`get_masked` / :meth:`list_masked`.

The table is additive and carries no FK to ``User`` — mirroring
``GoogleCredential``/``AgentProvider`` — so the shared test-suite's
``TRUNCATE "User"`` never trips over it. First-hit creation is serialized by a
transaction-scoped advisory lock so concurrent ``CREATE TABLE IF NOT EXISTS``
cannot race on Postgres's ``pg_type`` index.
"""
from __future__ import annotations

from typing import Any, Optional

from app.db import get_connection, rows_to_dicts
from app.services import credential_vault

#: Distinct advisory-lock id (AgentConfig 7420240711, User 7420240712,
#: CareerProfile 7420240713, OutreachTask 7420240714, GoogleCredential
#: 7420240715 — ProviderCredential takes the next id).
_CRED_TABLE_LOCK = 7420240716

#: Client-safe columns (NO ciphertext, NO plaintext) returned to API surfaces.
_MASKED_COLS = (
    '"provider", "authMode", "secretHint", "baseUrl", '
    '"lastVerifiedAt", "lastVerifyStatus", "createdAt", "updatedAt"'
)

#: Guard so table creation only runs once per worker process.
_table_ready = False


class ProviderCredentialRepository:
    """Read/write access to the encrypted ``ProviderCredential`` store."""

    def _ensure_table(self) -> None:
        if _table_ready:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Fast path: skip the ACCESS EXCLUSIVE-taking DDL when the table
                # already exists (mirrors GoogleCredential / agent config tables).
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_name = 'ProviderCredential'"
                    " AND table_schema = ANY(current_schemas(false))"
                )
                row = cur.fetchone()
                if row and row[0] == 1:
                    self._mark_ready()
                    return
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (_CRED_TABLE_LOCK,))
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS "ProviderCredential" (
                        "provider"          text PRIMARY KEY,
                        "authMode"          text NOT NULL,
                        "ciphertext"        text NOT NULL,
                        "secretHint"        text,
                        "baseUrl"           text,
                        "lastVerifiedAt"    timestamptz,
                        "lastVerifyStatus"  text,
                        "createdAt"         timestamptz NOT NULL DEFAULT now(),
                        "updatedAt"         timestamptz NOT NULL DEFAULT now()
                    )
                    '''
                )
            conn.commit()
        self._mark_ready()

    @staticmethod
    def _mark_ready() -> None:
        global _table_ready
        _table_ready = True

    def upsert(
        self,
        provider: str,
        *,
        auth_mode: str,
        secret: str,
        base_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """Encrypt + store the credential for ``provider``; return the masked row.

        Storing a new secret invalidates any prior verification result
        (``lastVerifiedAt``/``lastVerifyStatus`` reset to NULL) — the old key may
        have been replaced, so a stale "verified" badge would be dishonest.
        Raises :class:`credential_vault.CredentialVaultError` (a ``RuntimeError``)
        when ``AETHER_CREDENTIAL_KEY`` is missing/invalid — the router maps that
        to an honest 503 rather than writing a plaintext or fake row.
        """
        ciphertext = credential_vault.encrypt(secret)
        hint = credential_vault.secret_hint(secret)
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "ProviderCredential"
                        ("provider", "authMode", "ciphertext", "secretHint",
                         "baseUrl", "lastVerifiedAt", "lastVerifyStatus",
                         "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, NULL, NULL, now(), now())
                    ON CONFLICT ("provider") DO UPDATE SET
                        "authMode" = EXCLUDED."authMode",
                        "ciphertext" = EXCLUDED."ciphertext",
                        "secretHint" = EXCLUDED."secretHint",
                        "baseUrl" = EXCLUDED."baseUrl",
                        "lastVerifiedAt" = NULL,
                        "lastVerifyStatus" = NULL,
                        "updatedAt" = now()
                    RETURNING {_MASKED_COLS}
                    ''',
                    (provider, auth_mode, ciphertext, hint, base_url),
                )
                row = rows_to_dicts(cur)[0]
            conn.commit()
        return row

    def get(self, provider: str) -> Optional[dict[str, Any]]:
        """Raw stored row INCLUDING ciphertext but NOT the plaintext secret.

        Internal use only — the plaintext lives behind :meth:`get_secret`.
        """
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_MASKED_COLS}, "ciphertext" FROM "ProviderCredential" '
                    'WHERE "provider" = %s',
                    (provider,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def get_secret(self, provider: str) -> Optional[dict[str, Any]]:
        """Decrypt and return ``{authMode, secret, baseUrl}`` for the LLM client.

        This is the ONLY path that returns plaintext; it decrypts on demand and
        must never feed an API response. Returns ``None`` when no row exists (so
        the caller falls back to a legacy env credential). Raises
        :class:`credential_vault.CredentialVaultError` when a row exists but the
        key is missing/rotated — the caller degrades to the env source.
        """
        row = self.get(provider)
        if not row:
            return None
        secret = credential_vault.decrypt(row["ciphertext"])
        return {
            "authMode": row["authMode"],
            "secret": secret,
            "baseUrl": row.get("baseUrl"),
        }

    def get_masked(self, provider: str) -> Optional[dict[str, Any]]:
        """Client-safe projection (no ciphertext, no plaintext) or ``None``."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_MASKED_COLS} FROM "ProviderCredential" '
                    'WHERE "provider" = %s',
                    (provider,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def list_masked(self) -> list[dict[str, Any]]:
        """All stored credentials as client-safe masked rows."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_MASKED_COLS} FROM "ProviderCredential" ORDER BY "provider"'
                )
                return rows_to_dicts(cur)

    def delete(self, provider: str) -> bool:
        """Remove the stored credential; return True if a row was deleted."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "ProviderCredential" WHERE "provider" = %s',
                    (provider,),
                )
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    def mark_verified(self, provider: str, status: str) -> Optional[dict[str, Any]]:
        """Record the honest result of a real verify round-trip.

        Updates ``lastVerifiedAt``/``lastVerifyStatus`` on the stored row (if
        one exists) and returns the masked row. A no-op when the credential is
        env-sourced (no DB row to stamp).
        """
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'UPDATE "ProviderCredential" SET "lastVerifiedAt" = now(), '
                    f'"lastVerifyStatus" = %s, "updatedAt" = now() '
                    f'WHERE "provider" = %s RETURNING {_MASKED_COLS}',
                    (status, provider),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None
