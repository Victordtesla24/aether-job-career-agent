"""P4 — Google OAuth login + callback (in-app Gmail connect).

Covers state signing round-trip, the config-gated /login endpoint, and the
callback's honest redirect behaviour (never a 500 to the browser). The token
exchange itself is mocked — no live Google call is ever made.
"""
from __future__ import annotations

import pytest

from app.repositories.google_credential import GoogleCredentialRepository
from app.services import google_oauth


# --------------------------------------------------------------- state tokens
def test_encode_decode_state_roundtrip():
    token = google_oauth.encode_state("user-123")
    assert google_oauth.decode_state(token) == "user-123"


def test_decode_state_rejects_garbage():
    with pytest.raises(google_oauth.OAuthError):
        google_oauth.decode_state("not-a-real-jwt")


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
    repo = GoogleCredentialRepository()
    try:
        resp = client.get(
            "/auth/google/callback?code=good&state=whatever", follow_redirects=False
        )
        assert resp.status_code == 302
        assert "gmail_connected=1" in resp.headers["location"]
        stored = repo.get(test_user_id)
        assert stored is not None
        assert stored["googleEmail"] == "me@gmail.com"
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
    assert GoogleCredentialRepository().get(test_user_id) is None
