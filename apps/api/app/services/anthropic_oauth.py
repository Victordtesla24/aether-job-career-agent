"""In-app "Connect with Anthropic" (subscription) OAuth — authorize/exchange/refresh.

ML-agents-cred-002 (MODELS-LIVE, BLOCKER, operator-mandated ADR-ML-1). Governing
rulings: ADR-ML-2 + ADR-ML-2a in ``docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md``.

Flow (compliant, manual-redirect + code-paste-back + backend exchange):
the operator clicks "Connect with Anthropic"; the app opens Anthropic's OWN
authorize page (their Pro/Max subscription consent); Anthropic displays a
one-time ``code#state``; the operator pastes it back; this module exchanges it
server-side (PKCE) for an access + refresh token and stores them encrypted.

This is a COMPLIANT RE-AUTHORING — it deliberately does NOT copy the deleted
``anthropic_oauth.py`` (which POSTed a form body to ``api.anthropic.com``). The
token endpoint here is ``platform.claude.com/v1/oauth/token`` with a JSON body
that includes ``state`` (ADR-ML-2a, VERIFIED from the CLI binary extraction).

Token-store wiring (ADR-ML-2a DECISION-1, binding): the USED access token is the
SINGLE source of truth in the deployment-wide ``ProviderCredential('anthropic')``
row that ``llm_client.resolve_credential`` already reads (same seam the manual
``oauth_token`` paste uses), so a bare ``claude-*`` run resolves it deployment-wide
including CRON/BACKGROUND context. The refresh token + expiry + scope/status live
in the per-user ``AnthropicOAuthToken`` row; the refresh hook updates BOTH so
there is no split-brain.

Honesty invariants (never weakened):
- Secrets ONLY via env (:mod:`credential_vault` Fernet key from ``os.environ``);
  token values are NEVER logged or placed in an error message.
- The authorize host / client_id / scope are env-overridable constants read
  LAZILY from ``os.environ`` on every call (mirrors
  ``llm_client.get_anthropic_max_tokens``) so the INFERRED authorize host can be
  corrected without a redeploy (ADR-ML-2a) and so tests can monkeypatch them.
- An unexpected / missing-field token-endpoint response is an honest error —
  NEVER a fake success, NEVER a stored garbage token.
- On refresh failure: ``mark_needs_reauth`` + raise honestly — NO stale-token
  reuse, NO cross-provider fallthrough.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from app.repositories.provider_credential import ProviderCredentialRepository
from app.repositories.user_provider_credential import AnthropicOAuthTokenRepository
from app.services import credential_vault as vault

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (ADR-ML-2a RULING). Defaults = the ``claude setup-token`` SUBSCRIPTION
# inference flow (scope centred on ``user:inference``), NOT Blueprint B's
# ``org:create_api_key`` console/API-key-creation flow. The authorize host,
# client id and scope are env-overridable so the operator's first live consent
# click can correct the INFERRED host WITHOUT a code change / redeploy.
# ---------------------------------------------------------------------------
DEFAULT_AUTHORIZE_URL = "https://claude.com/cai/oauth/authorize"
# PUBLIC Claude Code PKCE client id — a distributed constant in the CLI binary,
# NOT a secret (ADR-ML-2a). Env-overridable via AETHER_ANTHROPIC_OAUTH_CLIENT_ID.
DEFAULT_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
DEFAULT_SCOPE = "user:inference"

#: Token exchange + refresh endpoint (JSON body incl. ``state``). The old
#: ``api.anthropic.com/oauth/token`` now 404s (ADR-ML-2a, VERIFIED).
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
#: Anthropic-hosted manual code-display redirect (NOT one of ours — the public
#: client only permits Anthropic-hosted / loopback redirect URIs).
REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"

#: Requested access-token lifetime (seconds) — 1 year, mirrors the CLI.
REQUESTED_EXPIRES_IN = 31536000

# Env-override names (ADR-ML-2a — pinned by the test contract).
_ENV_AUTHORIZE_URL = "AETHER_ANTHROPIC_OAUTH_AUTHORIZE_URL"
_ENV_CLIENT_ID = "AETHER_ANTHROPIC_OAUTH_CLIENT_ID"
_ENV_SCOPE = "AETHER_ANTHROPIC_OAUTH_SCOPE"
_ENV_REFRESH_SKEW_SECONDS = "AETHER_ANTHROPIC_OAUTH_REFRESH_SKEW_SECONDS"

#: Refresh-before-expiry window (seconds). A token within this of expiry is
#: refreshed on the next resolution; farther than this makes zero HTTP calls.
_DEFAULT_REFRESH_SKEW_SECONDS = 300  # 5 minutes


def _authorize_url() -> str:
    """The authorize endpoint, env-overridable (lazy read — ADR-ML-2a)."""
    return os.environ.get(_ENV_AUTHORIZE_URL) or DEFAULT_AUTHORIZE_URL


def _client_id() -> str:
    """The public OAuth client id, env-overridable (lazy read)."""
    return os.environ.get(_ENV_CLIENT_ID) or DEFAULT_CLIENT_ID


def _scope() -> str:
    """The requested scope, env-overridable (lazy read)."""
    return os.environ.get(_ENV_SCOPE) or DEFAULT_SCOPE


def _refresh_skew_seconds() -> int:
    try:
        return int(os.environ.get(_ENV_REFRESH_SKEW_SECONDS, _DEFAULT_REFRESH_SKEW_SECONDS))
    except (TypeError, ValueError):
        return _DEFAULT_REFRESH_SKEW_SECONDS


#: Module-level "constants" (surface required by the test contract). The
#: authorize-URL builder uses the lazy helpers above, so a test that
#: ``monkeypatch.setenv`` (without reload) OR ``importlib.reload`` both pick up
#: the override.
AUTHORIZE_URL = _authorize_url()
CLIENT_ID = _client_id()
SCOPE = _scope()


class OAuthExchangeError(RuntimeError):
    """An Anthropic token-endpoint call failed honestly (bad grant, unexpected
    response shape, network error). The message NEVER contains a token."""


# ---------------------------------------------------------------------------
# PKCE + state
# ---------------------------------------------------------------------------
def generate_pkce() -> tuple[str, str]:
    """Return ``(verifier, challenge)`` for a fresh S256 PKCE pair.

    ``challenge == base64url(sha256(verifier))`` with no ``=`` padding.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def generate_state() -> str:
    """An opaque, url-safe single-use CSRF state token (verifier is held
    server-side in ``AnthropicOAuthState``, so no signed state is needed)."""
    return secrets.token_urlsafe(32)


def build_authorize_url(challenge: str, state: str) -> str:
    """Build Anthropic's authorize URL for the subscription setup-token flow."""
    params = {
        "code": "true",
        "client_id": _client_id(),
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": _scope(),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{_authorize_url()}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Token endpoint (THE monkeypatch seam) + defensive parsing
# ---------------------------------------------------------------------------
def _post_token(body: dict) -> dict:
    """POST a JSON body to the token endpoint; return the parsed JSON dict.

    Isolated so unit tests monkeypatch exactly this seam (no live network).
    A non-2xx status or non-JSON body is an honest :class:`OAuthExchangeError`
    — the status code is surfaced, the token/body content is NOT.
    """
    import httpx

    try:
        resp = httpx.post(TOKEN_URL, json=body, timeout=30.0)
    except httpx.HTTPError as exc:  # network failure — never leak the body
        raise OAuthExchangeError(
            f"Could not reach the Anthropic token endpoint: {type(exc).__name__}."
        ) from exc
    if resp.status_code // 100 != 2:
        raise OAuthExchangeError(
            f"Anthropic token endpoint returned HTTP {resp.status_code}."
        )
    try:
        parsed = resp.json()
    except Exception as exc:  # noqa: BLE001 — non-JSON body
        raise OAuthExchangeError(
            "Anthropic token endpoint returned a non-JSON response."
        ) from exc
    if not isinstance(parsed, dict):
        raise OAuthExchangeError(
            "Anthropic token endpoint returned an unexpected response shape."
        )
    return parsed


def _normalize_token_response(raw: Any) -> dict:
    """Defensively normalise a token-endpoint body to
    ``{access_token, refresh_token, expires_at, scope}``.

    A missing / non-string ``access_token`` is an honest error — an unexpected
    shape must NEVER be treated as a fake success (ADR-ML-2 ruling #4).
    """
    if not isinstance(raw, dict):
        raise OAuthExchangeError("Anthropic token response was not a JSON object.")
    access = raw.get("access_token")
    if not isinstance(access, str) or not access:
        raise OAuthExchangeError(
            "Anthropic token response did not include an access token."
        )
    refresh = raw.get("refresh_token")
    refresh = refresh if isinstance(refresh, str) and refresh else None
    expires_in = raw.get("expires_in")
    try:
        expires_in = int(expires_in) if expires_in is not None else REQUESTED_EXPIRES_IN
    except (TypeError, ValueError):
        expires_in = REQUESTED_EXPIRES_IN
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    scope = raw.get("scope")
    scope = scope if isinstance(scope, str) and scope else None
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": expires_at,
        "scope": scope,
    }


def exchange_code(code: str, verifier: str, state: str) -> dict:
    """Exchange an authorization ``code`` (+ server-held ``verifier`` + ``state``)
    for tokens. JSON body, ``state`` included. Returns the normalised token dict.
    """
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": _client_id(),
        "code_verifier": verifier,
        "state": state,
        "expires_in": REQUESTED_EXPIRES_IN,
    }
    return _normalize_token_response(_post_token(body))


def refresh_tokens(refresh_token: str) -> dict:
    """Exchange a refresh token for a fresh access (+ rotated refresh) token."""
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _client_id(),
    }
    return _normalize_token_response(_post_token(body))


# ---------------------------------------------------------------------------
# Persistence — ONE source of truth for the USED token (ProviderCredential),
# refresh material in AnthropicOAuthToken (ADR-ML-2a DECISION-1).
# ---------------------------------------------------------------------------
def persist_tokens(user_id: str, tok: dict) -> None:
    """Store a freshly-minted/refreshed token set.

    1. The USED access token → deployment-wide ``ProviderCredential('anthropic')``
       (``oauth_token``) — the row ``resolve_credential`` reads DB-first, so bare
       ``claude-*`` runs resolve it across the WHOLE deployment (incl. cron).
    2. Refresh material + expiry + scope → per-user ``AnthropicOAuthToken``.
    3. Best-effort ``.env`` sync (restart survival); token never logged.
    """
    access = tok["access_token"]
    refresh = tok.get("refresh_token")
    expires_at = tok.get("expires_at")
    scope = tok.get("scope") or _scope()

    # 1. Single authoritative USED-token source wired into the live resolver.
    ProviderCredentialRepository().upsert(
        "anthropic", auth_mode="oauth_token", secret=access, base_url=None
    )
    # 2. Refresh material (encrypted) keyed by the operator's user id.
    AnthropicOAuthTokenRepository().upsert(
        user_id,
        access_ciphertext=vault.encrypt(access),
        refresh_ciphertext=vault.encrypt(refresh) if refresh else None,
        secret_hint=vault.secret_hint(access),
        expires_at=expires_at,
        scopes=scope,
    )
    # 3. Restart survival — best-effort, DB row is source of truth, never logged.
    try:
        from app.services import env_file_writer

        env_file_writer.sync_oauth_token_env(access)
    except Exception as exc:  # noqa: BLE001 — a sync failure must not fail the save
        logger.debug("oauth_token .env sync skipped: %s", exc)


# ---------------------------------------------------------------------------
# Refresh-before-expiry
# ---------------------------------------------------------------------------
def _coerce_dt(value: Any) -> "datetime | None":
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _is_expiring(expires_at: Any) -> bool:
    """True when ``expires_at`` is unknown or within the refresh-skew window."""
    dt = _coerce_dt(expires_at)
    if dt is None:
        return True
    skew = timedelta(seconds=_refresh_skew_seconds())
    return dt - datetime.now(timezone.utc) <= skew


def force_refresh(user_id: str) -> str:
    """Refresh unconditionally (the "Renew now" / /refresh endpoint path).

    On failure: ``mark_needs_reauth`` + raise :class:`OAuthExchangeError` — the
    stored token is NEVER silently reused and NEVER swapped for another provider.
    """
    repo = AnthropicOAuthTokenRepository()
    row = repo.get(user_id)
    if not row or not row.get("refreshCipher"):
        raise OAuthExchangeError(
            "No Anthropic OAuth session to refresh — connect with Anthropic first."
        )
    refresh_token = vault.decrypt(row["refreshCipher"])
    try:
        tok = refresh_tokens(refresh_token)
    except OAuthExchangeError:
        repo.mark_needs_reauth(user_id)
        raise
    persist_tokens(user_id, tok)
    return tok["access_token"]


def refresh_if_needed(user_id: str) -> "str | None":
    """Auto-refresh-before-expiry hook (ADR-ML-2 ruling #3 / ADR-ML-2a DECISION-1b).

    - No stored OAuth session → ``None`` (caller falls through to manual paste /
      env, same-provider only).
    - ``needs_reauth`` status → ``None`` (a broken session is never silently used).
    - Far from expiry → the stored access token, ZERO HTTP.
    - Near/after expiry → refresh, propagate the new access token into the SAME
      deployment-wide ``ProviderCredential`` row the resolver reads, and return it.
    - Refresh failure → ``mark_needs_reauth`` + raise; NEVER a stale token, NEVER
      a cross-provider fallthrough.
    """
    repo = AnthropicOAuthTokenRepository()
    row = repo.get(user_id)
    if not row:
        return None
    if row.get("scopes") == "needs_reauth":
        return None
    if not _is_expiring(row.get("expiresAt")):
        return vault.decrypt(row["ciphertext"])
    # Near/after expiry — refresh (honest failure marks needs_reauth + raises).
    return force_refresh(user_id)
