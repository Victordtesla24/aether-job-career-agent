"""Anthropic subscription OAuth (PKCE) — GAP-D1.

Implements the authorization-code-with-PKCE flow that lets a user connect their
Claude Max/Pro subscription so their agent runs bill against THAT subscription
(``authMode='subscription_oauth'``) instead of a metered API key. The access +
refresh tokens are encrypted at rest via the Fernet vault; the plaintext token
is NEVER returned to the client or logged.

Configuration (server env):
- ``AETHER_ANTHROPIC_OAUTH_CLIENT_ID``   — required; absent → honest 501.
- ``AETHER_ANTHROPIC_OAUTH_REDIRECT_URI`` — the registered callback URL.
- ``AETHER_ANTHROPIC_OAUTH_SCOPE``        — space-separated scopes (has a default).

The token exchange performs a real outbound POST to api.anthropic.com; tests
monkeypatch :func:`_post_token` so no network I/O occurs.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.security import JWT_ALGORITHM, get_jwt_secret

#: Where the user is sent to grant consent (Claude subscription OAuth).
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
#: Token endpoint for the authorization-code + refresh exchanges.
TOKEN_URL = "https://api.anthropic.com/oauth/token"
#: Default scopes if the deployment does not override them.
_DEFAULT_SCOPE = "org:create_api_key user:profile user:inference"
#: State JWT lifetime — the user has 10 minutes to complete consent.
_STATE_TTL = timedelta(minutes=10)
#: Refresh the access token when it is within this window of expiring.
REFRESH_SKEW = timedelta(minutes=5)


class OAuthNotConfiguredError(RuntimeError):
    """Raised when ``AETHER_ANTHROPIC_OAUTH_CLIENT_ID`` is not set."""


class OAuthExchangeError(RuntimeError):
    """Raised when the token endpoint returns a non-2xx / malformed response."""


def client_id() -> str:
    cid = os.environ.get("AETHER_ANTHROPIC_OAUTH_CLIENT_ID", "").strip()
    if not cid:
        raise OAuthNotConfiguredError(
            "Anthropic OAuth is not configured on this server "
            "(AETHER_ANTHROPIC_OAUTH_CLIENT_ID is unset)."
        )
    return cid


def is_configured() -> bool:
    return bool(os.environ.get("AETHER_ANTHROPIC_OAUTH_CLIENT_ID", "").strip())


def redirect_uri() -> str:
    return os.environ.get(
        "AETHER_ANTHROPIC_OAUTH_REDIRECT_URI", ""
    ).strip() or "https://5cb5f0620.abacusai.cloud/agents/auth/anthropic/callback"


def scope() -> str:
    return os.environ.get("AETHER_ANTHROPIC_OAUTH_SCOPE", "").strip() or _DEFAULT_SCOPE


# ---------------------------------------------------------------------------
# PKCE + signed state
# ---------------------------------------------------------------------------


def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for an S256 PKCE exchange."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def sign_state(user_id: str) -> str:
    """Sign a short-lived state JWT binding the callback to ``user_id``."""
    now = datetime.now(timezone.utc)
    payload = {
        "userId": user_id,
        "nonce": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + _STATE_TTL,
        "purpose": "anthropic_oauth_state",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def verify_state(state_token: str) -> str:
    """Verify a state JWT and return its ``userId``; raises ``jwt.PyJWTError``."""
    payload = jwt.decode(state_token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    if payload.get("purpose") != "anthropic_oauth_state" or not payload.get("userId"):
        raise jwt.InvalidTokenError("not an anthropic oauth state token")
    return str(payload["userId"])


def build_authorize_url(code_challenge: str, state_token: str) -> str:
    """Assemble the claude.ai consent URL the client is redirected to."""
    from urllib.parse import urlencode

    params = {
        "client_id": client_id(),
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "scope": scope(),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state_token,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Token exchange (real outbound HTTP; monkeypatched in tests)
# ---------------------------------------------------------------------------


def _post_token(data: dict[str, str], *, timeout: float = 15.0) -> dict[str, Any]:
    """POST ``data`` to the Anthropic token endpoint and return parsed JSON.

    Isolated so tests can monkeypatch it without any network I/O.
    """
    import httpx

    resp = httpx.post(TOKEN_URL, data=data, timeout=timeout)
    if resp.status_code >= 400:
        raise OAuthExchangeError(
            f"Anthropic token endpoint HTTP {resp.status_code}: {resp.text[:200]}"
        )
    return resp.json()


def _normalize_token(body: dict[str, Any]) -> dict[str, Any]:
    access = body.get("access_token")
    if not access:
        raise OAuthExchangeError("Token response missing access_token")
    expires_in = int(body.get("expires_in") or 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return {
        "access_token": access,
        "refresh_token": body.get("refresh_token"),
        "expires_at": expires_at,
        "scope": body.get("scope") or scope(),
    }


def exchange_code(code: str, code_verifier: str) -> dict[str, Any]:
    """Exchange an authorization ``code`` for tokens (authorization_code grant)."""
    body = _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
            "client_id": client_id(),
            "code_verifier": code_verifier,
        }
    )
    return _normalize_token(body)


def refresh_tokens(refresh_token: str) -> dict[str, Any]:
    """Exchange a ``refresh_token`` for a fresh access token (refresh grant)."""
    body = _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id(),
        }
    )
    return _normalize_token(body)


def _is_expiring(expires_at: Any) -> bool:
    """True when ``expires_at`` is missing or within :data:`REFRESH_SKEW`."""
    if expires_at is None:
        return True
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except ValueError:
            return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc) + REFRESH_SKEW


def refresh_if_needed(user_id: str) -> None:
    """Refresh this user's Anthropic subscription token if it is expiring.

    On refresh success the new access token is re-encrypted into BOTH the
    ``AnthropicOAuthToken`` store (with the refresh token) and the
    ``UserProviderCredential`` row the live path resolves. On refresh failure
    the token is marked ``needs_reauth`` (never silently reused past expiry).
    Best-effort: any error is swallowed so a live run degrades honestly to the
    next credential source rather than 500-ing.
    """
    from app.repositories.user_provider_credential import (
        AnthropicOAuthTokenRepository,
    )
    from app.services import credential_vault

    tokens = AnthropicOAuthTokenRepository()
    row = tokens.get(user_id)
    if not row or not _is_expiring(row.get("expiresAt")):
        return
    refresh_cipher = row.get("refreshCipher")
    if not refresh_cipher or not is_configured():
        tokens.mark_needs_reauth(user_id)
        return
    try:
        refresh_secret = credential_vault.decrypt(refresh_cipher)
        fresh = refresh_tokens(refresh_secret)
    except Exception:  # noqa: BLE001 — degrade honestly, mark for re-auth
        tokens.mark_needs_reauth(user_id)
        return
    persist_tokens(user_id, fresh)


def persist_tokens(user_id: str, tok: dict[str, Any]) -> dict[str, Any]:
    """Encrypt + store a token bundle in both stores; return the masked hint.

    ``tok`` is the shape returned by :func:`exchange_code` / :func:`refresh_tokens`.
    Never returns the plaintext token — only a last-4 hint.
    """
    from app.repositories.user_provider_credential import (
        AnthropicOAuthTokenRepository,
        UserProviderCredentialRepository,
    )
    from app.services import credential_vault

    access = tok["access_token"]
    refresh = tok.get("refresh_token")
    hint = credential_vault.secret_hint(access)
    access_cipher = credential_vault.encrypt(access)
    refresh_cipher = credential_vault.encrypt(refresh) if refresh else None

    AnthropicOAuthTokenRepository().upsert(
        user_id,
        access_ciphertext=access_cipher,
        refresh_ciphertext=refresh_cipher,
        secret_hint=hint,
        expires_at=tok["expires_at"],
        scopes=tok.get("scope"),
    )
    UserProviderCredentialRepository().upsert(
        user_id,
        "anthropic",
        auth_mode="subscription_oauth",
        secret=access,
        oauth_scopes=tok.get("scope"),
        expires_at=tok["expires_at"],
    )
    return {"authMode": "subscription_oauth", "hint": hint}
