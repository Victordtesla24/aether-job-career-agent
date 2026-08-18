"""OpenRouter third-party PKCE OAuth — app-hosted connect (GAP-PROVIDER-OAUTH-1).

Endpoints and shapes verified live against OpenRouter's published docs
(https://openrouter.ai/docs/use-cases/oauth-pkce, fetched 2026-08-18):

- Authorize: ``GET https://openrouter.ai/auth`` with ``callback_url``,
  ``code_challenge`` and ``code_challenge_method`` query params. **No
  ``client_id`` or app registration is required** — OpenRouter honours any
  ``https://`` (or ``localhost``) ``callback_url`` directly, unlike
  Anthropic's public CLI client which only permits its own hosted / loopback
  redirect URIs (see ``anthropic_oauth.py``'s module docstring). This is why
  OpenRouter's descriptor in ``provider_oauth_registry.py`` can always offer
  the zero-paste ``app_callback`` flow.
- Callback: OpenRouter redirects to ``callback_url`` with a single query
  param, ``code`` — it does NOT echo back a ``state`` value, so the CSRF/
  per-user binding must ride inside ``callback_url`` itself (the registry
  appends ``?state=...`` to our own app-hosted callback URL before handing
  it to OpenRouter as ``callback_url``).
- Exchange: ``POST https://openrouter.ai/api/v1/auth/keys`` with
  ``{code, code_verifier, code_challenge_method}``; the response is
  ``{"key": "<user-scoped API key>"}`` — a normal, non-expiring OpenRouter
  API key scoped to the authenticating OpenRouter account, not a
  short-lived OAuth access token. Normalised here to the same
  ``{access_token, refresh_token, expires_at, scope}`` shape
  ``anthropic_oauth.exchange_code`` returns so the callback route in
  ``routers/agents.py`` can treat every provider identically.

Honesty invariants (mirrors ``anthropic_oauth.py``):
- The key is NEVER logged or placed in an error message.
- An unexpected / missing-field token-endpoint response is an honest error —
  NEVER a fake success, NEVER a stored garbage credential.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

#: OpenRouter's fixed OAuth endpoints (no operator override needed — no
#: client_id/app registration exists to override; see module docstring).
AUTHORIZE_URL = "https://openrouter.ai/auth"
TOKEN_URL = "https://openrouter.ai/api/v1/auth/keys"


class OAuthExchangeError(RuntimeError):
    """An OpenRouter token-endpoint call failed honestly. The message NEVER
    contains the issued key.

    ``upstream_status`` mirrors ``anthropic_oauth.OAuthExchangeError``: set
    only when a real HTTP response reached us (its non-2xx status code),
    distinguishing an honest upstream rejection from a network/gateway
    failure where no response arrived at all (``None``).
    """

    def __init__(self, message: str, *, upstream_status: int | None = None) -> None:
        super().__init__(message)
        self.upstream_status = upstream_status


def build_authorize_url(challenge: str, callback_url: str) -> str:
    """Build OpenRouter's authorize URL. No ``client_id`` — see module docs."""
    params = {
        "callback_url": callback_url,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _post_exchange(body: dict) -> dict:
    """POST the exchange body; return the parsed JSON dict.

    Isolated so unit tests monkeypatch exactly this seam (no live network) —
    mirrors ``anthropic_oauth._post_token``.
    """
    import httpx

    try:
        resp = httpx.post(TOKEN_URL, json=body, timeout=30.0)
    except httpx.HTTPError as exc:  # network failure — never leak the body
        raise OAuthExchangeError(
            f"Could not reach the OpenRouter token endpoint: {type(exc).__name__}."
        ) from exc
    if resp.status_code // 100 != 2:
        raise OAuthExchangeError(
            f"OpenRouter token endpoint returned HTTP {resp.status_code}.",
            upstream_status=resp.status_code,
        )
    try:
        parsed = resp.json()
    except Exception as exc:  # noqa: BLE001 — non-JSON body
        raise OAuthExchangeError(
            "OpenRouter token endpoint returned a non-JSON response."
        ) from exc
    if not isinstance(parsed, dict):
        raise OAuthExchangeError(
            "OpenRouter token endpoint returned an unexpected response shape."
        )
    return parsed


def exchange_code(code: str, verifier: str) -> dict[str, Any]:
    """Exchange an authorization ``code`` (+ server-held PKCE ``verifier``)
    for a user-scoped OpenRouter API key.

    Returns the same normalised shape ``anthropic_oauth.exchange_code`` does:
    ``{"access_token", "refresh_token", "expires_at", "scope"}`` — here
    ``access_token`` carries the OpenRouter key and ``refresh_token``/
    ``expires_at`` are always ``None`` (OpenRouter keys do not expire and
    have no refresh flow). A missing/non-string ``key`` in the response is an
    honest error — never treated as a fake success.
    """
    body = {
        "code": code,
        "code_verifier": verifier,
        "code_challenge_method": "S256",
    }
    raw = _post_exchange(body)
    key = raw.get("key")
    if not isinstance(key, str) or not key:
        raise OAuthExchangeError(
            "OpenRouter token response did not include an API key."
        )
    return {
        "access_token": key,
        "refresh_token": None,
        "expires_at": None,
        "scope": None,
    }
