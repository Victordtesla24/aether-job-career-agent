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


def _register_with_username(client, db_session, username, email, password):
    """Register a user via the public endpoint, then stamp a username on it.

    Registration itself never sets a username (there is no public field for
    it), so tests that exercise login-by-username set it directly in the DB —
    mirroring how the admin seed populates the column.
    """
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    with db_session.cursor() as cur:
        cur.execute(
            'UPDATE "User" SET "username" = %s WHERE "email" = %s', (username, email)
        )
    db_session.commit()


class TestLoginByIdentifier:
    def test_login_by_username_succeeds(self, client, db_session):
        _register_with_username(
            client, db_session, "neo", "neo@example.com", "Matrix2024"
        )
        response = client.post(
            "/auth/login", json={"email": "neo", "password": "Matrix2024"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["email"] == "neo@example.com"
        assert body["token_type"] == "bearer"
        assert len(body["access_token"]) > 40

    def test_login_by_username_is_case_insensitive(self, client, db_session):
        _register_with_username(
            client, db_session, "Trinity", "trinity@example.com", "Matrix2024"
        )
        response = client.post(
            "/auth/login", json={"email": "TRINITY", "password": "Matrix2024"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["email"] == "trinity@example.com"

    def test_login_by_email_still_succeeds(self, client):
        assert _register(client).status_code == 201
        response = client.post("/auth/login", json=VALID_CREDENTIALS)
        assert response.status_code == 200, response.text
        assert response.json()["email"] == VALID_CREDENTIALS["email"]

    def test_login_wrong_password_is_constant_shape_401(self, client, db_session):
        _register_with_username(
            client, db_session, "cypher", "cypher@example.com", "Steak2024"
        )
        # Wrong password for a valid username, and an unknown identifier, must
        # both return the identical 401 body — no oracle leaking which existed.
        by_username = client.post(
            "/auth/login", json={"email": "cypher", "password": "wrongpass1"}
        )
        by_unknown = client.post(
            "/auth/login", json={"email": "nobody-here", "password": "wrongpass1"}
        )
        assert by_username.status_code == 401
        assert by_unknown.status_code == 401
        assert by_username.json() == {"detail": "Invalid email or password"}
        assert by_username.json() == by_unknown.json()


class TestAuthRateLimiting:
    def test_register_is_rate_limited_after_threshold(self, client):
        # The default limiter allows 5 auth calls / IP / window; the 6th 429s.
        statuses = [
            client.post(
                "/auth/register",
                json={"email": f"rl{i}@example.com", "password": "Passw0rd1"},
            ).status_code
            for i in range(7)
        ]
        assert statuses[-1] == 429
        assert 429 in statuses

    def test_login_is_rate_limited_after_threshold(self, client):
        assert (
            client.post(
                "/auth/register",
                json={"email": "brute@example.com", "password": "Passw0rd1"},
            ).status_code
            == 201
        )
        # One register already consumed a slot; hammer login until throttled.
        last = None
        for _ in range(7):
            last = client.post(
                "/auth/login",
                json={"email": "brute@example.com", "password": "Passw0rd1"},
            )
        assert last.status_code == 429


class TestAdminSeed:
    def test_admin_seed_is_idempotent(self, client, db_session):
        from scripts.seed_demo import seed_admin_user

        first = seed_admin_user()
        second = seed_admin_user()
        assert first == second
        with db_session.cursor() as cur:
            cur.execute('SELECT count(*) FROM "User" WHERE "username" = %s', ("admin",))
            count = cur.fetchone()[0]
        assert count == 1

    def test_admin_can_login_by_username(self, client):
        from scripts.seed_demo import seed_admin_user

        seed_admin_user()
        response = client.post(
            "/auth/login", json={"email": "admin", "password": "admin123"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["email"] == "admin@aether.local"
