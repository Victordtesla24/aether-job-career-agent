"""GoogleCredential persistence — per-user Gmail OAuth tokens (Email Agent).

One row per user holding the long-lived Google **refresh token** plus the most
recent short-lived access token. The refresh token is a secret: it is read only
server-side (by :class:`app.services.gmail_service.GmailService` and the OAuth
callback) and must NEVER be serialized to a client.

The table is additive and carries no FK to ``User`` — mirroring
``AgentConfig``/``AgentProvider``/``CareerProfile`` — so the shared test-suite's
``TRUNCATE "User"`` never trips over it. First-hit creation is serialized by a
transaction-scoped advisory lock so concurrent ``CREATE TABLE IF NOT EXISTS``
cannot race on Postgres's ``pg_type`` index.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.db import get_connection, rows_to_dicts

#: Distinct advisory-lock id (see AgentConfig 7420240711, User 7420240712,
#: CareerProfile 7420240713, OutreachTask 7420240714).
_CRED_TABLE_LOCK = 7420240715

#: Columns returned by internal reads. ``refreshToken`` is included because the
#: server needs it to mint access tokens — callers MUST NOT serialize it.
_SELECT_COLS = (
    '"userId", "googleEmail", "refreshToken", "accessToken", '
    '"accessTokenExpiresAt", "scopes", "connectedAt", "updatedAt"'
)

#: Guard so table creation only runs once per worker process.
_table_ready = False


class GoogleCredentialRepository:
    """Read/write access to the ``GoogleCredential`` store."""

    def _ensure_table(self) -> None:
        if _table_ready:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Fast path: skip the ACCESS EXCLUSIVE-taking DDL when the table
                # already exists (mirrors ensure_user_profile_columns / networking).
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_name = 'GoogleCredential'"
                    " AND table_schema = ANY(current_schemas(false))"
                )
                row = cur.fetchone()
                if row and row[0] == 1:
                    self._mark_ready()
                    return
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (_CRED_TABLE_LOCK,))
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS "GoogleCredential" (
                        "userId"                text PRIMARY KEY,
                        "googleEmail"           text,
                        "refreshToken"          text NOT NULL,
                        "accessToken"           text,
                        "accessTokenExpiresAt"  timestamptz,
                        "scopes"                text,
                        "connectedAt"           timestamptz NOT NULL DEFAULT now(),
                        "updatedAt"             timestamptz NOT NULL DEFAULT now()
                    )
                    '''
                )
            conn.commit()
        self._mark_ready()

    @staticmethod
    def _mark_ready() -> None:
        global _table_ready
        _table_ready = True

    def get(self, user_id: str) -> Optional[dict[str, Any]]:
        """Full stored credential row for ``user_id`` (or ``None``).

        WARNING: the returned dict contains ``refreshToken``/``accessToken``.
        These are secrets — never include them in an API response.
        """
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_SELECT_COLS} FROM "GoogleCredential" WHERE "userId" = %s',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def public_view(self, user_id: str) -> Optional[dict[str, Any]]:
        """Client-safe projection of the credential (NO tokens).

        Returned to UI surfaces (inbox account bar, settings connected-accounts)
        so the connected Google address can be shown without ever exposing the
        refresh/access tokens.
        """
        row = self.get(user_id)
        if not row:
            return None
        return {
            "googleEmail": row.get("googleEmail"),
            "scopes": row.get("scopes"),
            "connectedAt": row.get("connectedAt"),
            "updatedAt": row.get("updatedAt"),
        }

    def is_connected(self, user_id: str) -> bool:
        """Cheap existence check — the single source of truth for "is Gmail
        connected?" used by the inbox status and the send-gate on every call."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT 1 FROM "GoogleCredential" WHERE "userId" = %s LIMIT 1',
                    (user_id,),
                )
                return cur.fetchone() is not None

    def upsert(
        self,
        user_id: str,
        *,
        google_email: Optional[str],
        refresh_token: Optional[str],
        access_token: Optional[str] = None,
        access_token_expires_at: Optional[datetime] = None,
        scopes: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert or update the credential row for ``user_id``.

        Google only returns a ``refresh_token`` on the FIRST consent (unless
        ``prompt=consent`` forces it); a subsequent exchange may carry an empty
        refresh token. ``COALESCE(NULLIF(EXCLUDED, ''), existing)`` therefore
        preserves the stored refresh token rather than nulling it — so a
        re-auth never silently breaks sending.
        """
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "GoogleCredential"
                        ("userId", "googleEmail", "refreshToken", "accessToken",
                         "accessTokenExpiresAt", "scopes", "connectedAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT ("userId") DO UPDATE SET
                        "googleEmail" = COALESCE(EXCLUDED."googleEmail",
                                                 "GoogleCredential"."googleEmail"),
                        "refreshToken" = COALESCE(NULLIF(EXCLUDED."refreshToken", ''),
                                                  "GoogleCredential"."refreshToken"),
                        "accessToken" = EXCLUDED."accessToken",
                        "accessTokenExpiresAt" = EXCLUDED."accessTokenExpiresAt",
                        "scopes" = COALESCE(EXCLUDED."scopes", "GoogleCredential"."scopes"),
                        "updatedAt" = now()
                    RETURNING {_SELECT_COLS}
                    ''',
                    (
                        user_id,
                        google_email,
                        refresh_token,
                        access_token,
                        access_token_expires_at,
                        scopes,
                    ),
                )
                row = rows_to_dicts(cur)[0]
            conn.commit()
        return row

    def update_access_token(
        self, user_id: str, access_token: str, expires_at: Optional[datetime]
    ) -> None:
        """Persist a freshly refreshed access token (called after auto-refresh)."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "GoogleCredential" SET "accessToken" = %s, '
                    '"accessTokenExpiresAt" = %s, "updatedAt" = now() '
                    'WHERE "userId" = %s',
                    (access_token, expires_at, user_id),
                )
            conn.commit()

    def disconnect(self, user_id: str) -> None:
        """Remove the stored credential (user disconnected Gmail)."""
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "GoogleCredential" WHERE "userId" = %s', (user_id,)
                )
            conn.commit()
