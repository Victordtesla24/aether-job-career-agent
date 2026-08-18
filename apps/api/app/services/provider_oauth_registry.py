"""Per-user provider OAuth descriptor registry (GAP-PROVIDER-OAUTH-1).

One place that answers, per provider id: does it support an in-app OAuth
connect at all, and if so is the connect a zero-paste **app-hosted callback**
(the browser round-trips through our own server, which auto-populates the UI
via ``postMessage``) or a **code-relay** fallback (the provider's own
hosted page displays a one-time code the user pastes back)?

Consumed by ``routers/agents.py``'s ``/agents/user/providers/{provider}/
oauth/*`` routes (per-user, additive — distinct from the admin-only
deployment-wide ``/agents/providers/anthropic/oauth/*`` family those routes
sit beside). Every descriptor here writes ONLY the caller's own
``UserProviderCredential`` row — never the deployment-wide
``ProviderCredential`` store.

Flow selection (ADR-PROVIDER-OAUTH-1, honesty requirement — never claim
zero-paste for a client that cannot register our callback):

- **anthropic** — the public Claude Code CLI client id
  (``anthropic_oauth.DEFAULT_CLIENT_ID``) is a distributed constant that only
  permits Anthropic-hosted/loopback redirect URIs (see
  ``anthropic_oauth.py``'s module docstring) — it CANNOT be pointed at our
  app-hosted callback. So the default flow is ``code_relay`` (the existing,
  already-working manual-paste mechanics in ``anthropic_oauth.py``, reused
  verbatim). Setting ``ANTHROPIC_OAUTH_CLIENT_ID`` in the server environment
  to an operator-registered client whose allowed redirect URIs include
  ``ANTHROPIC_OAUTH_REDIRECT_URI`` (our app callback) switches this
  descriptor to ``app_callback`` automatically — a live config fact, not a
  hardcoded claim.
- **openrouter** — no client registration exists to reject our callback
  (verified against OpenRouter's own docs — see ``openrouter_oauth.py``), so
  ``app_callback`` is always available.
- every other provider (openai, gemini, bedrock, groq, abacus, …) —
  ``supports_oauth=False``: API-key only, by design (ADR-P7-01 non-goal).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _app_base_url() -> str:
    from app.services.stripe_gateway import app_base_url

    return app_base_url()


def _default_app_callback_url(provider_id: str) -> str:
    """The app-hosted callback route for ``provider_id`` (matches the FastAPI
    route ``GET /agents/user/providers/{provider}/oauth/callback``, served
    externally behind the ``/api`` proxy — see ``apps/web/src/lib/api/client.
    ts:apiBaseUrl``)."""
    return f"{_app_base_url()}/api/agents/user/providers/{provider_id}/oauth/callback"


def with_query_param(url: str, key: str, value: str) -> str:
    """Return ``url`` with ``key=value`` appended/replaced in its query string.

    Used to embed the PKCE ``state`` into OpenRouter's ``callback_url`` since
    OpenRouter's redirect echoes back only ``code`` — see
    ``openrouter_oauth.py``'s module docstring.
    """
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != key]
    query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass(frozen=True)
class ProviderOAuthDescriptor:
    """One provider's OAuth connect contract, resolved fresh on every call
    (lazy env reads throughout — mirrors ``anthropic_oauth.py``'s convention
    so an operator's env change takes effect without a redeploy)."""

    provider_id: str
    supports_oauth: bool
    #: Persisted as ``UserProviderCredential.authMode`` on a successful
    #: exchange — ``'oauth_token'`` for Anthropic (subscription quota),
    #: ``'api_key'`` for OpenRouter (a normal user-scoped key).
    token_auth_mode: str
    #: ``'app_callback'`` (zero-paste, auto-return) or ``'code_relay'``
    #: (the provider shows a one-time code the user pastes back).
    flow: str
    #: The exact redirect/callback URL this descriptor will send the
    #: provider, and that the exchange step must echo back for providers
    #: that verify it (Anthropic).
    redirect_uri: Callable[[], str]
    #: ``(challenge, state, redirect_uri) -> authorize_url``.
    build_authorize_url: Callable[[str, str, str], str]
    #: ``(code, verifier, state, redirect_uri) -> {access_token, refresh_token,
    #: expires_at, scope}`` — raises the provider's own ``OAuthExchangeError``
    #: subclass on an honest failure.
    exchange_code: Callable[[str, str, str, str], dict[str, Any]]


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
def _anthropic_client_id_override() -> str | None:
    return os.environ.get("ANTHROPIC_OAUTH_CLIENT_ID") or None


def _anthropic_client_id() -> str:
    from app.services import anthropic_oauth

    # Falls back through the existing AETHER_-prefixed override (if an
    # operator already set one for the admin flow) before the shared public
    # default — "the existing public client constant" (task contract).
    return _anthropic_client_id_override() or anthropic_oauth._client_id()


def _anthropic_flow() -> str:
    """``app_callback`` only when the operator has actually registered a
    client whose redirect URIs include our app callback (signalled by
    setting ``ANTHROPIC_OAUTH_CLIENT_ID``) — otherwise the honest default,
    ``code_relay``, since the public CLI client rejects our redirect."""
    return "app_callback" if _anthropic_client_id_override() else "code_relay"


def _anthropic_redirect_uri() -> str:
    if _anthropic_flow() == "app_callback":
        return os.environ.get("ANTHROPIC_OAUTH_REDIRECT_URI") or _default_app_callback_url(
            "anthropic"
        )
    from app.services import anthropic_oauth

    return anthropic_oauth.REDIRECT_URI


def _anthropic_build_authorize_url(challenge: str, state: str, redirect_uri: str) -> str:
    from app.services import anthropic_oauth

    return anthropic_oauth.build_authorize_url(
        challenge, state, redirect_uri=redirect_uri, client_id=_anthropic_client_id()
    )


def _anthropic_exchange_code(
    code: str, verifier: str, state: str, redirect_uri: str
) -> dict[str, Any]:
    from app.services import anthropic_oauth

    return anthropic_oauth.exchange_code(
        code, verifier, state, redirect_uri=redirect_uri, client_id=_anthropic_client_id()
    )


def _anthropic_descriptor() -> ProviderOAuthDescriptor:
    return ProviderOAuthDescriptor(
        provider_id="anthropic",
        supports_oauth=True,
        token_auth_mode="oauth_token",
        flow=_anthropic_flow(),
        redirect_uri=_anthropic_redirect_uri,
        build_authorize_url=_anthropic_build_authorize_url,
        exchange_code=_anthropic_exchange_code,
    )


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------
def _openrouter_redirect_uri() -> str:
    return os.environ.get("OPENROUTER_OAUTH_REDIRECT_URI") or _default_app_callback_url(
        "openrouter"
    )


def _openrouter_build_authorize_url(challenge: str, state: str, redirect_uri: str) -> str:
    from app.services import openrouter_oauth

    # OpenRouter's redirect echoes back only `code` (no `state`) — embed the
    # per-user state token into the callback_url itself (see
    # openrouter_oauth.py's module docstring).
    callback_with_state = with_query_param(redirect_uri, "state", state)
    return openrouter_oauth.build_authorize_url(challenge, callback_with_state)


def _openrouter_exchange_code(
    code: str, verifier: str, state: str, redirect_uri: str
) -> dict[str, Any]:
    from app.services import openrouter_oauth

    # redirect_uri/state are not part of OpenRouter's exchange body (its
    # docs specify only {code, code_verifier, code_challenge_method}) —
    # accepted for signature parity with every other descriptor's callable.
    return openrouter_oauth.exchange_code(code, verifier)


def _openrouter_descriptor() -> ProviderOAuthDescriptor:
    return ProviderOAuthDescriptor(
        provider_id="openrouter",
        supports_oauth=True,
        token_auth_mode="api_key",
        flow="app_callback",
        redirect_uri=_openrouter_redirect_uri,
        build_authorize_url=_openrouter_build_authorize_url,
        exchange_code=_openrouter_exchange_code,
    )


# ---------------------------------------------------------------------------
# Registry surface
# ---------------------------------------------------------------------------
_BUILDERS: dict[str, Callable[[], ProviderOAuthDescriptor]] = {
    "anthropic": _anthropic_descriptor,
    "openrouter": _openrouter_descriptor,
}


def get_oauth_descriptor(provider_id: str) -> ProviderOAuthDescriptor | None:
    """The OAuth descriptor for ``provider_id``, or ``None`` when it has no
    OAuth connect at all (API-key-only providers — openai, gemini, bedrock,
    groq, abacus, and anything unrecognised)."""
    builder = _BUILDERS.get(provider_id)
    if builder is None:
        return None
    descriptor = builder()
    return descriptor if descriptor.supports_oauth else None


def list_oauth_provider_ids() -> list[str]:
    """Every provider id with an OAuth descriptor (regardless of which flow
    it currently resolves to)."""
    return sorted(_BUILDERS.keys())
