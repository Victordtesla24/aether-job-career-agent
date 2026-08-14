"""O-4 — self-service password reset (S-FIX slice D).

RED first: written against endpoints/tables/columns that do not exist yet.

Covers:
- POST /auth/forgot-password: always-200 anti-enumeration, honest
  ``emailSendingEnabled`` flag, single-use hashed token with a 1h expiry,
  additive ``PasswordResetToken`` table.
- POST /auth/reset-password: token+new-password, invalidates prior sessions
  (login must be re-established with the new password), rejects
  invalid/expired/reused tokens, enforces the existing password policy.
- Both endpoints are rate-limited (reuse SlidingWindowRateLimiter).
- The email-provider abstraction (SMTP env vars OR API-key env vars) is
  exercised via monkeypatched send functions so no real network call is made.
"""
from __future__ import annotations

import time


def _register(client, email="reset-target@example.com", password="OldPassw0rd"):
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return email, password


class TestForgotPasswordHonestAntiEnumeration:
    def test_unknown_email_returns_200(self, client):
        resp = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert "emailSendingEnabled" in body

    def test_known_email_returns_identical_200_shape(self, client):
        email, _ = _register(client)
        resp = client.post("/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert "emailSendingEnabled" in body

    def test_no_provider_configured_reports_honest_false_flag(self, client, monkeypatch):
        monkeypatch.delenv("AETHER_SMTP_HOST", raising=False)
        monkeypatch.delenv("AETHER_EMAIL_API_KEY", raising=False)
        email, _ = _register(client, email="honest-flag@example.com")
        resp = client.post("/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200, resp.text
        assert resp.json()["emailSendingEnabled"] is False

    def test_provider_configured_reports_true_flag_and_attempts_send(self, client, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "test-key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@aether.local")
        sent_to = []

        def _fake_send(to_email, subject, text_body):
            sent_to.append(to_email)
            return True

        from app.services import email_sender

        monkeypatch.setattr(email_sender, "send_email", _fake_send)
        email, _ = _register(client, email="provider-on@example.com")
        resp = client.post("/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200, resp.text
        assert resp.json()["emailSendingEnabled"] is True
        assert sent_to == [email]


class TestPasswordResetTokenLifecycle:
    def test_token_is_hashed_at_rest_never_the_raw_value(self, client, db_session, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "test-key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@aether.local")
        captured = {}

        def _fake_send(to_email, subject, text_body):
            captured["body"] = text_body
            return True

        from app.services import email_sender

        monkeypatch.setattr(email_sender, "send_email", _fake_send)

        email, _ = _register(client, email="hash-check@example.com")
        resp = client.post("/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200, resp.text

        # "PasswordResetToken" has no FK to "User" (shared-test-DB TRUNCATE
        # safety, matching "Offer") and is therefore NOT truncated between
        # tests — rows from earlier tests/runs persist in the shared schema,
        # so the query must scope to THIS test's user, never assume the
        # table starts empty.
        with db_session.cursor() as cur:
            cur.execute('SELECT id FROM "User" WHERE email=%s', (email,))
            user_id = cur.fetchone()[0]
            cur.execute(
                'SELECT "tokenHash", "expiresAt", "usedAt" FROM "PasswordResetToken"'
                ' WHERE "userId"=%s',
                (user_id,),
            )
            rows = cur.fetchall()
        assert len(rows) == 1
        token_hash, expires_at, used_at = rows[0]
        assert used_at is None
        assert token_hash not in captured["body"]
        # sha256 hex digest length
        assert len(token_hash) == 64

    def test_reset_with_valid_token_changes_password_and_allows_new_login(
        self, client, db_session, monkeypatch
    ):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "test-key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@aether.local")
        captured = {}

        def _fake_send(to_email, subject, text_body):
            captured["body"] = text_body
            return True

        from app.services import email_sender

        monkeypatch.setattr(email_sender, "send_email", _fake_send)

        email, old_password = _register(client, email="valid-reset@example.com")
        resp = client.post("/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200, resp.text

        # Extract the raw token the "email" would have carried — the test
        # double captures the exact text body handed to the provider, and the
        # reset URL always carries ?token=<raw>.
        import re

        match = re.search(r"token=([A-Za-z0-9_\-]+)", captured["body"])
        assert match, captured["body"]
        raw_token = match.group(1)

        reset_resp = client.post(
            "/auth/reset-password",
            json={"token": raw_token, "password": "NewPassw0rd1"},
        )
        assert reset_resp.status_code == 200, reset_resp.text
        assert reset_resp.json()["ok"] is True

        # Old password no longer works.
        old_login = client.post("/auth/login", json={"email": email, "password": old_password})
        assert old_login.status_code == 401, old_login.text

        # New password works.
        new_login = client.post("/auth/login", json={"email": email, "password": "NewPassw0rd1"})
        assert new_login.status_code == 200, new_login.text

    def test_token_is_single_use(self, client, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "test-key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@aether.local")
        captured = {}

        def _fake_send(to_email, subject, text_body):
            captured["body"] = text_body
            return True

        from app.services import email_sender

        monkeypatch.setattr(email_sender, "send_email", _fake_send)

        email, _ = _register(client, email="single-use@example.com")
        client.post("/auth/forgot-password", json={"email": email})

        import re

        raw_token = re.search(r"token=([A-Za-z0-9_\-]+)", captured["body"]).group(1)

        first = client.post(
            "/auth/reset-password", json={"token": raw_token, "password": "FirstNew1"}
        )
        assert first.status_code == 200, first.text

        second = client.post(
            "/auth/reset-password", json={"token": raw_token, "password": "SecondNew1"}
        )
        assert second.status_code == 400, second.text

    def test_expired_token_is_rejected(self, client, db_session, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "test-key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@aether.local")

        from app.services.password_reset import create_reset_token

        email, _ = _register(client, email="expired-token@example.com")
        with db_session.cursor() as cur:
            cur.execute('SELECT id FROM "User" WHERE email=%s', (email,))
            user_id = cur.fetchone()[0]
        raw_token = create_reset_token(user_id)
        # Force it into the past directly. Scoped to THIS test's userId only:
        # "PasswordResetToken" has no FK to "User" and is never truncated
        # (shared-test-DB TRUNCATE safety, matching "Offer"), so it can hold
        # live rows from OTHER, concurrently-running suites against the same
        # shared aether_test schema — an unscoped UPDATE here would expire
        # every one of them.
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "PasswordResetToken" SET "expiresAt" = now() - interval \'1 hour\''
                ' WHERE "userId"=%s',
                (user_id,),
            )
        db_session.commit()

        resp = client.post(
            "/auth/reset-password", json={"token": raw_token, "password": "WontWork1"}
        )
        assert resp.status_code == 400, resp.text

    def test_garbage_token_is_rejected(self, client):
        resp = client.post(
            "/auth/reset-password", json={"token": "not-a-real-token", "password": "WontWork1"}
        )
        assert resp.status_code == 400, resp.text

    def test_reset_rejects_weak_password(self, client, monkeypatch):
        from app.services.password_reset import create_reset_token

        email, _ = _register(client, email="weak-reset@example.com")

        # Look up the user id via the API (no direct import of UserRepository
        # needed beyond what create_reset_token already takes).
        from app.repositories.user import UserRepository

        user = UserRepository().get_by_email(email)
        raw_token = create_reset_token(user["id"])

        resp = client.post(
            "/auth/reset-password", json={"token": raw_token, "password": "short"}
        )
        assert resp.status_code == 422, resp.text


class TestPasswordResetInvalidatesSessions:
    def test_old_jwt_rejected_after_reset(self, client, monkeypatch):
        monkeypatch.setenv("AETHER_EMAIL_API_KEY", "test-key")
        monkeypatch.setenv("AETHER_EMAIL_FROM", "noreply@aether.local")
        captured = {}

        def _fake_send(to_email, subject, text_body):
            captured["body"] = text_body
            return True

        from app.services import email_sender

        monkeypatch.setattr(email_sender, "send_email", _fake_send)

        email, old_password = _register(client, email="session-invalidate@example.com")
        login = client.post("/auth/login", json={"email": email, "password": old_password})
        assert login.status_code == 200, login.text
        old_token = login.json()["access_token"]
        old_headers = {"Authorization": f"Bearer {old_token}"}

        # The old token works before the reset.
        assert client.get("/auth/me", headers=old_headers).status_code == 200

        # Ensure the reset's ``now()`` timestamp clears the login's ``iat``
        # claim by more than get_current_user's 1s grace window (JWT ``iat``
        # has 1-second granularity; the grace absorbs that truncation so an
        # immediate post-reset relogin isn't itself falsely invalidated —
        # this sleep only needs to put the OLD token outside that window).
        time.sleep(2.2)

        client.post("/auth/forgot-password", json={"email": email})
        import re

        raw_token = re.search(r"token=([A-Za-z0-9_\-]+)", captured["body"]).group(1)
        reset_resp = client.post(
            "/auth/reset-password", json={"token": raw_token, "password": "BrandNew1"}
        )
        assert reset_resp.status_code == 200, reset_resp.text

        # The pre-reset token must now be rejected.
        stale = client.get("/auth/me", headers=old_headers)
        assert stale.status_code == 401, stale.text

        # A fresh login with the new password mints a token that works.
        relogin = client.post("/auth/login", json={"email": email, "password": "BrandNew1"})
        assert relogin.status_code == 200, relogin.text
        fresh_headers = {"Authorization": f"Bearer {relogin.json()['access_token']}"}
        assert client.get("/auth/me", headers=fresh_headers).status_code == 200


class TestPasswordResetRateLimiting:
    def test_forgot_password_is_rate_limited_per_email(self, client):
        email = "rate-limited-forgot@example.com"
        statuses = [
            client.post("/auth/forgot-password", json={"email": email}).status_code
            for _ in range(10)
        ]
        assert 429 in statuses, statuses
        blocked_index = statuses.index(429)
        assert all(s == 200 for s in statuses[:blocked_index]), statuses

    def test_reset_password_is_rate_limited_per_token(self, client):
        statuses = [
            client.post(
                "/auth/reset-password",
                json={"token": "guess-the-same-wrong-token", "password": "WontWork1"},
            ).status_code
            for _ in range(10)
        ]
        assert 429 in statuses, statuses
        # Every attempt before the cap kicks in is a clean 400 (invalid token),
        # never anything else.
        blocked_index = statuses.index(429)
        assert all(s == 400 for s in statuses[:blocked_index]), statuses
