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

    def test_register_persists_name(self, client):
        # The /signup form submits a display name; it must survive to the row
        # and be retrievable via /auth/me (contract register body {email,
        # password, name}).
        creds = {
            "email": "named@example.com",
            "password": "Passw0rd1",
            "name": "Jane Doe",
        }
        assert _register(client, creds).status_code == 201
        login = client.post(
            "/auth/login",
            json={"email": "named@example.com", "password": "Passw0rd1"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200, me.text
        assert me.json()["name"] == "Jane Doe"


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
    """Auth rate limiting is keyed on the normalized REQUEST IDENTIFIER
    (submitted email / username), never on the client IP.

    Why not IP: in this deployment the API sits behind Envoy -> nginx ->
    uvicorn. nginx forwards no ``X-Forwarded-For`` and uvicorn's
    ``ProxyHeadersMiddleware`` trusts the loopback peer, so an IP-keyed limiter
    is either bypassable (a forged ``X-Forwarded-For`` mints a fresh bucket per
    request) or collapses every user into one global bucket (a site-wide auth
    DoS). The client IP is therefore not trustworthy and is deliberately NOT
    used as a key. See ADR D-0033.

    The previous ``test_rate_limit_not_bypassable_via_x_forwarded_for`` was
    DELETED on purpose: ``TestClient`` never runs uvicorn's proxy middleware, so
    that test could not exercise the real IP-trust bug it claimed to guard —
    it gave false confidence. Body-identifier keying, by contrast, IS fully
    exercisable through ``TestClient`` (the identifier travels in the JSON body,
    not the transport), which is what the tests below do.
    """

    def test_failed_logins_lock_a_single_identifier(self, client):
        # Register so the identifier resolves to a real user; the wrong password
        # then drives genuine 401s that the failure limiter counts.
        assert (
            client.post(
                "/auth/register",
                json={"email": "brute@example.com", "password": "Passw0rd1"},
            ).status_code
            == 201
        )
        # Default cap: 5 failed attempts / identifier / window. The first five
        # wrong-password logins return 401; the sixth is throttled with 429.
        statuses = [
            client.post(
                "/auth/login",
                json={"email": "brute@example.com", "password": "wrongpass9"},
            ).status_code
            for _ in range(6)
        ]
        assert statuses[:5] == [401, 401, 401, 401, 401], statuses
        assert statuses[5] == 429, statuses
        # The 429 must advertise a Retry-After so clients back off honestly.
        blocked = client.post(
            "/auth/login",
            json={"email": "brute@example.com", "password": "wrongpass9"},
        )
        assert blocked.status_code == 429
        assert blocked.headers.get("Retry-After")

    def test_login_lockout_is_per_identifier(self, client):
        # Two independent accounts; hammering one must never affect the other.
        for email in ("victim@example.com", "bystander@example.com"):
            assert (
                client.post(
                    "/auth/register", json={"email": email, "password": "Passw0rd1"}
                ).status_code
                == 201
            )
        # Lock the victim identifier out entirely.
        for _ in range(6):
            client.post(
                "/auth/login",
                json={"email": "victim@example.com", "password": "nope12345"},
            )
        assert (
            client.post(
                "/auth/login",
                json={"email": "victim@example.com", "password": "nope12345"},
            ).status_code
            == 429
        )
        # A DIFFERENT identifier is on its own bucket and can still log in.
        ok = client.post(
            "/auth/login",
            json={"email": "bystander@example.com", "password": "Passw0rd1"},
        )
        assert ok.status_code == 200, ok.text

    def test_successful_login_resets_failure_counter(self, client):
        assert (
            client.post(
                "/auth/register",
                json={"email": "reset@example.com", "password": "Passw0rd1"},
            ).status_code
            == 201
        )
        # Four near-miss failures — one shy of the cap of five.
        for _ in range(4):
            assert (
                client.post(
                    "/auth/login",
                    json={"email": "reset@example.com", "password": "wrongpass9"},
                ).status_code
                == 401
            )
        # A correct login must succeed AND clear the failure counter so a legit
        # user who finally remembers their password is not locked out.
        assert (
            client.post(
                "/auth/login",
                json={"email": "reset@example.com", "password": "Passw0rd1"},
            ).status_code
            == 200
        )
        # Because the counter reset, four more failures are all 401 (no 429).
        # A limiter that did not reset would 429 on the second failure here.
        for _ in range(4):
            assert (
                client.post(
                    "/auth/login",
                    json={"email": "reset@example.com", "password": "wrongpass9"},
                ).status_code
                == 401
            )

    def test_login_failure_key_is_case_insensitive(self, client):
        # Mixed-case variants of one email share ONE normalized failure bucket,
        # so an attacker cannot dodge the cap by toggling case.
        assert (
            client.post(
                "/auth/register",
                json={"email": "casey@example.com", "password": "Passw0rd1"},
            ).status_code
            == 201
        )
        variants = ["casey@example.com", "CASEY@example.com", "Casey@Example.com"]
        statuses = [
            client.post(
                "/auth/login",
                json={"email": variants[i % len(variants)], "password": "wrongpass9"},
            ).status_code
            for i in range(6)
        ]
        assert statuses[:5] == [401, 401, 401, 401, 401], statuses
        assert statuses[5] == 429, statuses

    def test_register_spam_on_one_email_is_capped(self, client):
        # Default cap: 3 register attempts / email / window. The first creates
        # the account (201); the next two collide (409 duplicate) but STILL
        # count; the fourth attempt on the same email is throttled with 429.
        first = client.post(
            "/auth/register", json={"email": "spam@example.com", "password": "Passw0rd1"}
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/auth/register", json={"email": "spam@example.com", "password": "Passw0rd1"}
        )
        third = client.post(
            "/auth/register", json={"email": "spam@example.com", "password": "Passw0rd1"}
        )
        assert second.status_code == 409
        assert third.status_code == 409
        fourth = client.post(
            "/auth/register", json={"email": "spam@example.com", "password": "Passw0rd1"}
        )
        assert fourth.status_code == 429, fourth.text
        assert fourth.headers.get("Retry-After")

    def test_register_cap_is_per_email(self, client):
        # Exhaust one email's registration budget...
        for _ in range(4):
            client.post(
                "/auth/register",
                json={"email": "capped@example.com", "password": "Passw0rd1"},
            )
        assert (
            client.post(
                "/auth/register",
                json={"email": "capped@example.com", "password": "Passw0rd1"},
            ).status_code
            == 429
        )
        # ...a DIFFERENT email is on its own bucket and still registers.
        fresh = client.post(
            "/auth/register",
            json={"email": "brandnew@example.com", "password": "Passw0rd1"},
        )
        assert fresh.status_code == 201, fresh.text


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
