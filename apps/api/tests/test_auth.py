"""P2-S01 — user registration, login (bcrypt + JWT), and route protection.

RED first: these tests are written against endpoints and repositories that do
not exist yet.
"""
from __future__ import annotations

VALID_CREDENTIALS = {"email": "casey@example.com", "password": "hunter2024"}


def _register(client, credentials=None):
    return client.post("/auth/register", json=credentials or VALID_CREDENTIALS)


class TestRegister:
    def test_register_creates_user(self, client):
        response = _register(client)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["email"] == VALID_CREDENTIALS["email"]
        assert body["id"]
        assert "createdAt" in body
        # The password (or any hash of it) must never leak in the response.
        serialized = response.text.lower()
        assert "password" not in serialized
        assert VALID_CREDENTIALS["password"] not in response.text

    def test_password_is_hashed_in_db(self, client, db_session):
        response = _register(client)
        assert response.status_code == 201, response.text
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "passwordHash" FROM "User" WHERE email = %s',
                (VALID_CREDENTIALS["email"],),
            )
            row = cur.fetchone()
        assert row is not None
        password_hash = row[0]
        assert password_hash != VALID_CREDENTIALS["password"]
        # bcrypt hashes start with the $2 modular-crypt prefix.
        assert password_hash.startswith("$2")

    def test_register_duplicate_email_conflict(self, client):
        assert _register(client).status_code == 201
        assert _register(client).status_code == 409

    def test_register_weak_password_rejected(self, client):
        # Too short (< 8 characters).
        short = {"email": "weak1@example.com", "password": "a1b2c3"}
        assert _register(client, short).status_code == 422
        # No digit.
        no_digit = {"email": "weak2@example.com", "password": "abcdefghij"}
        assert _register(client, no_digit).status_code == 422


class TestLogin:
    def test_login_returns_jwt(self, client):
        assert _register(client).status_code == 201
        response = client.post("/auth/login", json=VALID_CREDENTIALS)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["email"] == VALID_CREDENTIALS["email"]
        assert body["userId"]
        assert len(body["access_token"]) > 40

    def test_login_wrong_password_rejected(self, client):
        assert _register(client).status_code == 201
        response = client.post(
            "/auth/login",
            json={"email": VALID_CREDENTIALS["email"], "password": "wrongpass1"},
        )
        assert response.status_code == 401

    def test_login_unknown_email_rejected(self, client):
        response = client.post(
            "/auth/login",
            json={"email": "ghost@example.com", "password": "hunter2024"},
        )
        assert response.status_code == 401


class TestProtectedRoutes:
    def test_protected_route_rejects_no_token(self, client):
        response = client.get("/jobs")
        assert response.status_code == 401

    def test_protected_route_rejects_garbage_token(self, client):
        response = client.get("/jobs", headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401

    def test_protected_route_accepts_valid_token(self, client, auth_headers):
        response = client.get("/jobs", headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json() == []
