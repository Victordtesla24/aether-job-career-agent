"""Google OAuth 2.0 flow for the Email Agent (in-app Gmail connect).

The app-user identity cannot ride the OAuth callback via the app's own Bearer
JWT (Google redirects the browser with no ``Authorization`` header), so it
travels inside the OAuth ``state`` parameter as a short-lived, signed token
(:func:`encode_state` / :func:`decode_state`). That token is single-purpose and
CANNOT be replayed as an app session token — three independent barriers:

1. **Distinct signing key** — signed with a namespaced secret
   (:func:`_state_secret`) that can never equal the session secret
   (``JWT_SECRET``/``NEXTAUTH_SECRET`` used by ``app.security``), so
   ``decode_access_token`` rejects it on the signature before anything else.
2. **Distinct audience** — ``aud="google-oauth-state"`` (session tokens carry
   no ``aud``); :func:`decode_state` requires that audience.
3. **Distinct identity claim** — the user id rides in ``uid``, not the
   ``userId``/``sub`` that ``get_current_user`` reads, so even a decoded state
   token yields no session user.

**PKCE code_verifier (ADR-PC-1)** — ``state`` also carries the PKCE
``code_verifier`` (claim ``cv``) that was used to build the ``code_challenge``
in the consent URL. This is required because ``google-auth-oauthlib``'s
``Flow`` generates its ``code_verifier`` in-memory on the ``Flow`` instance
that builds the consent URL (:func:`build_consent_url`); the callback handles
the exchange on a brand-new ``Flow`` instance (:func:`_build_flow` called again
in :func:`exchange_code`) that never saw that verifier, so without carrying it
across, Google's token endpoint rejects the exchange with
``(invalid_grant) Missing code verifier``. The state JWT is the only
cross-request channel available (see above), so the verifier rides alongside
``uid``. This is defense-in-depth, not a new secret to protect: the verifier
alone cannot complete a token exchange without the ``client_secret``, and the
state token keeps its existing security properties (signed, single audience,
5-minute TTL).

It is signed here with PyJWT rather than importing ``app.security`` so this
module stays decoupled from the auth layer, and expires in 5 minutes.

Env (read directly from ``os.environ``, matching the llm_client convention):
``GOOGLE_OAUTH_CLIENT_ID``, ``GOOGLE_OAUTH_CLIENT_SECRET``,
``GOOGLE_OAUTH_REDIRECT_URI``. The state secret derives from
``GOOGLE_OAUTH_STATE_SECRET`` (or ``NEXTAUTH_SECRET``) but is namespaced so it is
never byte-equal to the session-signing secret.
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Any, NamedTuple

import jwt

#: Gmail + identity scopes the product requests (Gmail API enabled by the user).
GOOGLE_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.labels",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

#: Google's fixed OAuth endpoints.
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"

#: State token audience + lifetime (seconds). 5-minute window: long enough for a
#: human to complete Google's consent screen, short enough to blunt replay.
_STATE_AUD = "google-oauth-state"
_STATE_TTL = 300


class OAuthError(RuntimeError):
    """Any failure building the consent URL or exchanging the auth code."""


class StateClaims(NamedTuple):
    """Decoded ``state`` JWT payload the callback needs."""

    user_id: str
    #: PKCE code_verifier carried from build_consent_url, or None for a state
    #: token that predates ADR-PC-1 (never issued by this build, but decoding
    #: stays lenient rather than hard-failing on the missing claim).
    code_verifier: str | None


def _client_id() -> str:
    return os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()


def get_redirect_uri() -> str:
    return os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()


#: Namespace suffix mixed into the state-signing key so it can never be
#: byte-equal to the app session secret (``JWT_SECRET``/``NEXTAUTH_SECRET``).
#: A state token therefore fails signature verification in
#: ``app.security.decode_access_token`` and can never be replayed as a session.
_STATE_SECRET_NAMESPACE = "::google-oauth-state::v1"


def _state_secret() -> str:
    base = (
        os.environ.get("GOOGLE_OAUTH_STATE_SECRET")
        or os.environ.get("NEXTAUTH_SECRET")
        or "dev-oauth-state-secret"
    )
    return base + _STATE_SECRET_NAMESPACE


def oauth_configured() -> bool:
    """True only when the client id, secret AND redirect URI are all present."""
    return bool(_client_id() and _client_secret() and get_redirect_uri())


def _generate_code_verifier() -> str:
    """A cryptographically random PKCE code_verifier (RFC 7636 S4.1: 43-128
    chars from the unreserved URL-safe alphabet). ``token_urlsafe(96)`` yields
    exactly 128 base64url characters (96 bytes, no padding)."""
    return secrets.token_urlsafe(96)


def encode_state(user_id: str, code_verifier: str | None = None) -> str:
    """Sign a short-lived state token carrying the app user id and, per
    ADR-PC-1, the PKCE ``code_verifier`` that matches the consent URL's
    ``code_challenge`` (see module docstring)."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "uid": user_id,
        "aud": _STATE_AUD,
        "iat": now,
        "exp": now + _STATE_TTL,
    }
    if code_verifier:
        payload["cv"] = code_verifier
    return jwt.encode(payload, _state_secret(), algorithm="HS256")


def decode_state(state: str) -> StateClaims:
    """Return the app user id (and PKCE code_verifier, if any) from a valid
    state token, else raise OAuthError."""
    try:
        payload = jwt.decode(
            state,
            _state_secret(),
            algorithms=["HS256"],
            audience=_STATE_AUD,
        )
    except jwt.PyJWTError as exc:  # expired, bad signature, wrong audience …
        raise OAuthError(f"Invalid or expired OAuth state: {exc}") from exc
    uid = payload.get("uid")
    if not uid:
        raise OAuthError("OAuth state missing user id")
    return StateClaims(user_id=str(uid), code_verifier=payload.get("cv"))


def _client_config() -> dict[str, Any]:
    return {
        "web": {
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": [get_redirect_uri()],
        }
    }


def _build_flow() -> Any:
    """Construct a google-auth-oauthlib Flow bound to our redirect URI."""
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=GOOGLE_SCOPES)
    flow.redirect_uri = get_redirect_uri()
    return flow


def build_consent_url(user_id: str) -> str:
    """Google consent-screen URL. ``access_type=offline`` + ``prompt=consent``
    force a refresh token on every grant so a re-connect can never come back
    without one.

    Per ADR-PC-1, the PKCE ``code_verifier`` is generated explicitly (rather
    than relying on ``Flow.authorization_url``'s autogeneration) so it is
    known *before* the state JWT is built and can be carried in it — the
    ``Flow`` instance handling the callback is a different object
    (:func:`_build_flow` runs again in :func:`exchange_code`) that would
    otherwise never see it, producing Google's
    ``(invalid_grant) Missing code verifier`` error.
    """
    if not oauth_configured():
        raise OAuthError("Google OAuth is not configured on the server")
    flow = _build_flow()
    code_verifier = _generate_code_verifier()
    flow.code_verifier = code_verifier
    flow.autogenerate_code_verifier = False
    url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=encode_state(user_id, code_verifier),
    )
    return url


def _resolve_email(creds: Any) -> str | None:
    """Best-effort resolution of the connected Google account's email."""
    try:
        from googleapiclient.discovery import build

        info = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        return info.userinfo().get().execute().get("email")
    except Exception:  # noqa: BLE001 — email is nice-to-have, never fatal
        return None


def exchange_code(code: str, state: str) -> dict[str, Any]:
    """Validate ``state``, exchange ``code`` for tokens, and return a normalized
    credential dict (including the app ``user_id`` recovered from state)."""
    claims = decode_state(state)
    user_id = claims.user_id
    if not oauth_configured():
        raise OAuthError("Google OAuth is not configured on the server")
    try:
        flow = _build_flow()
        if claims.code_verifier:
            # ADR-PC-1 defense-in-depth: this Flow is a brand-new instance
            # that never generated a code_verifier of its own (see
            # build_consent_url) — without setting it here, fetch_token sends
            # no verifier and Google rejects the exchange with
            # "(invalid_grant) Missing code verifier". The verifier is not a
            # long-term secret; token exchange still requires client_secret.
            flow.code_verifier = claims.code_verifier
        flow.fetch_token(code=code)
        creds = flow.credentials
    except OAuthError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface as a clean OAuthError
        raise OAuthError(f"Token exchange failed: {exc}") from exc
    return {
        "user_id": user_id,
        "google_email": _resolve_email(creds),
        "refresh_token": creds.refresh_token,
        "access_token": creds.token,
        "expires_at": creds.expiry,
        "scopes": " ".join(creds.scopes or GOOGLE_SCOPES),
    }
