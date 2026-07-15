"""P4 — Google OAuth login + callback (in-app Gmail connect).

Covers state signing round-trip, the config-gated /login endpoint, and the
callback's honest redirect behaviour (never a 500 to the browser). Most tests
here mock the token exchange (no live Google call is ever made), but the PKCE
tests below exercise the REAL build_consent_url -> decode_state ->
exchange_code handoff — only google-auth-oauthlib's ``Flow.fetch_token`` (the
actual network boundary) and email resolution are monkeypatched — as a
regression guard for the "(invalid_grant) Missing code verifier" bug
(ADR-PC-1).
"""
from __future__ import annotations

import time
import urllib.parse
from typing import Any

import pytest

from app.repositories.gmail_account import GmailAccountRepository
from app.services import google_oauth


def _configure_oauth_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "https://example.abacusai.cloud/api/auth/google/callback",
    )


# --------------------------------------------------------------- state tokens
def test_encode_decode_state_roundtrip():
    token = google_oauth.encode_state("user-123")
    claims = google_oauth.decode_state(token)
    assert claims.user_id == "user-123"


def test_decode_state_rejects_garbage():
    with pytest.raises(google_oauth.OAuthError):
        google_oauth.decode_state("not-a-real-jwt")


# ------------------------------------------------ SECURITY: state ≠ session
def test_state_token_is_not_a_valid_session_token():
    """A single-purpose OAuth ``state`` token MUST NOT verify as an app session
    token. It is signed with a namespaced key distinct from the session secret,
    so ``decode_access_token`` rejects it on the signature."""
    import jwt as pyjwt

    from app.security import decode_access_token

    state = google_oauth.encode_state("user-123")
    with pytest.raises(pyjwt.PyJWTError):
        decode_access_token(state)


def test_state_token_rejected_as_bearer_on_protected_route(client):
    """End-to-end: ``get_current_user`` cannot be satisfied by an OAuth state
    token presented as a Bearer credential — the protected route 401s."""
    state = google_oauth.encode_state("user-123")
    resp = client.get("/agents", headers={"Authorization": f"Bearer {state}"})
    assert resp.status_code == 401


def test_state_token_expires_in_five_minutes():
    """Short replay window: the state token's lifetime is 5 minutes."""
    import jwt as pyjwt

    state = google_oauth.encode_state("user-123")
    claims = pyjwt.decode(
        state,
        google_oauth._state_secret(),
        algorithms=["HS256"],
        audience=google_oauth._STATE_AUD,
    )
    assert claims["exp"] - claims["iat"] == 300
    assert claims["aud"] == "google-oauth-state"
    assert claims["uid"] == "user-123"
    # The identity rides in `uid`, never the `userId`/`sub` a session reads.
    assert "userId" not in claims and "sub" not in claims


# --------------------------------------------------------- PKCE (ADR-PC-1)
def test_build_consent_url_carries_pkce_verifier_in_state(monkeypatch):
    """RCA regression guard: build_consent_url must produce a state token
    whose decoded payload carries a non-empty PKCE code_verifier ('cv'), and
    the consent URL itself must carry the matching code_challenge."""
    _configure_oauth_env(monkeypatch)

    url = google_oauth.build_consent_url("user-123")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    assert query.get("code_challenge"), "consent URL missing code_challenge"
    assert query["code_challenge_method"][0] == "S256"

    state = query["state"][0]
    claims = google_oauth.decode_state(state)
    assert claims.user_id == "user-123"
    assert claims.code_verifier, "state JWT missing PKCE code_verifier ('cv')"


def test_exchange_code_sets_verifier_from_state_before_fetch_token(monkeypatch):
    """Regression guard for the exact shipped bug: exchange_code builds a NEW
    Flow (a different object than the one build_consent_url used), so it must
    thread the code_verifier carried in ``state`` onto that new Flow BEFORE
    calling fetch_token — otherwise Google rejects the exchange with
    "(invalid_grant) Missing code verifier"."""
    _configure_oauth_env(monkeypatch)
    monkeypatch.setattr(google_oauth, "_resolve_email", lambda creds: "me@gmail.com")

    # Step 1: consent URL + its state carry the real verifier.
    url = google_oauth.build_consent_url("user-123")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
    expected_verifier = google_oauth.decode_state(state).code_verifier
    assert expected_verifier

    # Step 2: capture what exchange_code's (new) Flow actually sends.
    captured: dict[str, Any] = {}

    def fake_fetch_token(self, **kwargs):
        captured["code_verifier"] = self.code_verifier
        # Simulate a successful token response so exchange_code can proceed
        # to build its return dict without ever hitting the network.
        self.oauth2session.token = {
            "access_token": "access-xyz",
            "refresh_token": "refresh-xyz",
            "expires_at": time.time() + 3600,
            "scope": "gmail.modify",
        }
        self.oauth2session.scope = ["gmail.modify"]

    from google_auth_oauthlib.flow import Flow

    monkeypatch.setattr(Flow, "fetch_token", fake_fetch_token)

    result = google_oauth.exchange_code("auth-code-from-google", state)

    assert captured["code_verifier"] == expected_verifier
    assert result["refresh_token"] == "refresh-xyz"
    assert result["user_id"] == "user-123"


# --------------------------------------------------------------- /login gate
def test_login_requires_server_config(client, auth_headers, monkeypatch):
    for var in (
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
    ):
        monkeypatch.delenv(var, raising=False)
    resp = client.get("/auth/google/login", headers=auth_headers)
    assert resp.status_code == 503, resp.text


def test_login_returns_consent_url_when_configured(client, auth_headers, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "https://example.abacusai.cloud/api/auth/google/callback",
    )
    resp = client.get("/auth/google/login", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    url = resp.json()["authUrl"]
    assert "accounts.google.com" in url
    assert "state=" in url
    assert "access_type=offline" in url


def test_login_requires_auth(client):
    assert client.get("/auth/google/login").status_code == 401


# --------------------------------------------------------------- /callback
def test_callback_missing_params_redirects_failure(client):
    resp = client.get("/auth/google/callback", follow_redirects=False)
    assert resp.status_code == 302
    assert "gmail_connected=0" in resp.headers["location"]


def test_callback_invalid_state_redirects_failure(client):
    resp = client.get(
        "/auth/google/callback?code=abc&state=bad", follow_redirects=False
    )
    assert resp.status_code == 302
    assert "gmail_connected=0" in resp.headers["location"]


def test_callback_success_persists_credential(
    client, auth_headers, test_user_id, monkeypatch
):
    def fake_exchange(code: str, state: str):
        return {
            "user_id": test_user_id,
            "google_email": "me@gmail.com",
            "refresh_token": "refresh-xyz",
            "access_token": "access-xyz",
            "expires_at": None,
            "scopes": "gmail.modify gmail.send",
        }

    monkeypatch.setattr(
        "app.routers.google_oauth.exchange_code", fake_exchange
    )
    repo = GmailAccountRepository()
    try:
        resp = client.get(
            "/auth/google/callback?code=good&state=whatever", follow_redirects=False
        )
        assert resp.status_code == 302
        assert "gmail_connected=1" in resp.headers["location"]
        # GAP-D2: the callback persists to the authoritative GmailAccount store.
        stored = repo.get(test_user_id)
        assert stored is not None
        assert stored["accountEmail"] == "me@gmail.com"
        assert stored["refreshToken"] == "refresh-xyz"
        # public_view never leaks the secret token.
        pub = repo.public_view(test_user_id)
        assert pub["googleEmail"] == "me@gmail.com"
        assert "refreshToken" not in pub
    finally:
        repo.disconnect(test_user_id)


def test_callback_without_refresh_token_fails_honestly(
    client, test_user_id, monkeypatch
):
    def fake_exchange(code: str, state: str):
        return {
            "user_id": test_user_id,
            "google_email": "me@gmail.com",
            "refresh_token": None,  # Google withheld it (prior grant)
            "access_token": "access-xyz",
            "expires_at": None,
            "scopes": "",
        }

    monkeypatch.setattr("app.routers.google_oauth.exchange_code", fake_exchange)
    resp = client.get(
        "/auth/google/callback?code=good&state=whatever", follow_redirects=False
    )
    assert resp.status_code == 302
    assert "gmail_connected=0" in resp.headers["location"]
    assert GmailAccountRepository().get(test_user_id) is None
