"""Auth tests — register / login / protected routes (P2-S01).

Acceptance criterion: a POST to ``/auth/register`` with valid credentials
creates a ``User`` row with a bcrypt-hashed password, and a subsequent POST to
``/auth/login`` returns a signed JWT that authorises access to protected
routes. The password hash must never be exposed over the wire.
"""
from __future__ import annotations


def test_register_creates_user(client, db_session):
    r = client.post(
        "/auth/register", json={"email": "test@aether.dev", "password": "Hunter2!"}
    )
    assert r.status_code == 201
    assert "id" in r.json()
    assert "password" not in r.json()  # never expose hash


def test_password_is_hashed_in_db(client, db_session):
    client.post(
        "/auth/register", json={"email": "bob@aether.dev", "password": "Secret99"}
    )
    from app.repositories.user import UserRepository

    user = UserRepository(db_session).get_by_email("bob@aether.dev")
    assert user.password_hash != "Secret99"  # must be bcrypt


def test_login_returns_jwt(client, db_session):
    client.post(
        "/auth/register", json={"email": "alice@aether.dev", "password": "Passw0rd"}
    )
    r = client.post(
        "/auth/login", json={"email": "alice@aether.dev", "password": "Passw0rd"}
    )
    assert r.status_code == 200
    token = r.json().get("access_token")
    assert token and len(token) > 40


def test_protected_route_rejects_no_token(client):
    r = client.get("/jobs")
    assert r.status_code == 401


def test_protected_route_accepts_valid_token(client, auth_headers):
    r = client.get("/jobs", headers=auth_headers)
    assert r.status_code == 200  # empty list, not 401


# --- REFACTOR: shared password policy (min 8 chars, at least 1 digit) --------


def test_register_weak_password_rejected(client, db_session):
    # Too short and/or missing a digit must be rejected before any user is made.
    r = client.post(
        "/auth/register", json={"email": "weak@aether.dev", "password": "short"}
    )
    assert r.status_code == 422
    from app.repositories.user import UserRepository

    assert UserRepository(db_session).get_by_email("weak@aether.dev") is None


def test_register_password_without_digit_rejected(client, db_session):
    r = client.post(
        "/auth/register",
        json={"email": "nodigit@aether.dev", "password": "NoDigitsHere"},
    )
    assert r.status_code == 422
