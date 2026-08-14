"""§14.7 — an env-managed admin password may never be silently accept-then-reverted.

ADJUDICATION (owner-relevant, ADMIN-FULL finish): ``apply_admin_rotation`` runs
on EVERY app construction and UPSERTs the ``AETHER_ADMIN_EMAIL`` row's
``passwordHash`` from ``AETHER_ADMIN_PASSWORD_HASH``. So for that ONE identity,
any in-app password change — self-service reset or an admin acting through
``POST /admin/users/{id}/password`` — is silently undone at the next API
restart: the user is told "your password has been reset", signs in happily, and
is locked out again after the next deploy with nothing anywhere saying why.

The honest behaviour is to REFUSE, naming the mechanism and the real remedy
(rotate the env var and restart), rather than accept a write the next boot will
throw away. These specs pin exactly that, and pin that ordinary accounts are
completely unaffected while the env admin is configured.

SAFETY: no password or hash VALUE is ever asserted on, printed or logged here —
only that the refusal message names the variable, and that the stored hash is
unchanged.
"""
from __future__ import annotations

import uuid

from app.db import get_connection
from app.repositories.admin import _ensure_admin_schema
from app.security import hash_password
from app.services.password_reset import create_reset_token

ENV_ADMIN_PASSWORD = "0perat0r-Str0ng-Pass"


def _register(client, email: str, password: str = "Passw0rd1") -> str:
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (201, 409), r.text
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["userId"]


def _promote(user_id: str) -> None:
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (user_id,))
        conn.commit()


def _admin_headers(client) -> dict[str, str]:
    email = f"adm-{uuid.uuid4().hex[:8]}@example.com"
    uid = _register(client, email)
    _promote(uid)
    login = client.post("/auth/login", json={"email": email, "password": "Passw0rd1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _stored_hash(user_id: str) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "passwordHash" FROM "User" WHERE "id"=%s', (user_id,))
            return cur.fetchone()[0]


def _configure_env_admin(monkeypatch, email: str) -> None:
    """Point the §14.7 rotation at ``email``.

    Set AFTER the ``client`` fixture has constructed the app, so no rotation
    actually runs in-test — these specs are about the routes' own honesty, not
    about re-running the rotation.
    """
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", hash_password(ENV_ADMIN_PASSWORD))


# --------------------------------------------------------------------------- #
# Self-service reset (POST /auth/reset-password)
# --------------------------------------------------------------------------- #


def test_reset_password_refuses_an_env_managed_admin_identity(client, monkeypatch):
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    user_id = _register(client, email)
    _configure_env_admin(monkeypatch, email)
    before = _stored_hash(user_id)

    token = create_reset_token(user_id)
    r = client.post(
        "/auth/reset-password", json={"token": token, "password": "BrandNewOne1"}
    )

    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    # Honest: names the mechanism and the real remedy, never the hash value.
    assert "AETHER_ADMIN_PASSWORD_HASH" in detail
    assert "restart" in detail.lower()
    assert ENV_ADMIN_PASSWORD not in detail
    # And it really refused: nothing was written for the next boot to revert.
    assert _stored_hash(user_id) == before


def test_reset_password_still_works_for_everyone_else(client, monkeypatch):
    """The refusal is scoped to the ONE configured identity, not to resets."""
    _configure_env_admin(monkeypatch, f"owner-{uuid.uuid4().hex[:8]}@example.com")
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    user_id = _register(client, email)
    before = _stored_hash(user_id)

    token = create_reset_token(user_id)
    r = client.post(
        "/auth/reset-password", json={"token": token, "password": "BrandNewOne1"}
    )

    assert r.status_code == 200, r.text
    assert _stored_hash(user_id) != before
    assert (
        client.post(
            "/auth/login", json={"email": email, "password": "BrandNewOne1"}
        ).status_code
        == 200
    )


def test_forgot_password_stays_byte_identical_for_the_env_managed_identity(
    client, monkeypatch
):
    """The refusal lives at COMPLETION, never at request time.

    /auth/forgot-password is anti-enumeration: it answers identically for every
    address. Softening it for the operator identity would hand an attacker an
    oracle for which address is the admin — so the response must not move, even
    though the link it mints can only end in the 409 above.
    """
    owner_email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    other_email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    _register(client, owner_email)
    _register(client, other_email)
    _configure_env_admin(monkeypatch, owner_email)

    owner = client.post("/auth/forgot-password", json={"email": owner_email})
    other = client.post("/auth/forgot-password", json={"email": other_email})

    assert owner.status_code == 200 and other.status_code == 200
    assert owner.json() == other.json()


def test_reset_password_is_unaffected_when_no_env_admin_is_configured(client):
    """No AETHER_ADMIN_* in the environment => nothing is env-managed."""
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    user_id = _register(client, email)
    token = create_reset_token(user_id)
    r = client.post(
        "/auth/reset-password", json={"token": token, "password": "BrandNewOne1"}
    )
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# Admin-forced change (POST /admin/users/{id}/password)
# --------------------------------------------------------------------------- #


def test_admin_set_password_refuses_an_env_managed_admin_identity(
    client, monkeypatch
):
    headers = _admin_headers(client)
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    user_id = _register(client, email)
    _configure_env_admin(monkeypatch, email)
    before = _stored_hash(user_id)

    r = client.post(
        f"/admin/users/{user_id}/password",
        json={"newPassword": "An0therPassw0rd"},
        headers=headers,
    )

    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "AETHER_ADMIN_PASSWORD_HASH" in detail
    assert ENV_ADMIN_PASSWORD not in detail
    assert _stored_hash(user_id) == before
    # A refused change is NOT an audited change (nothing happened to record).
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "AdminAuditLog" WHERE "targetId"=%s'
                " AND \"action\"='set_user_password'",
                (user_id,),
            )
            assert cur.fetchone()[0] == 0


def test_admin_set_password_matches_the_env_identity_case_insensitively(
    client, monkeypatch
):
    """The rotation's own de-privilege step compares ``lower(email)``; an
    uppercase spelling must not slip past the refusal into a write the next
    boot reverts."""
    headers = _admin_headers(client)
    # Mixed case in the local part only — pydantic's EmailStr already
    # lowercases the domain, so this is the spelling difference that can
    # actually survive into the stored row.
    email = f"Owner-{uuid.uuid4().hex[:8]}@example.com"
    user_id = _register(client, email)
    _configure_env_admin(monkeypatch, email.lower())

    r = client.post(
        f"/admin/users/{user_id}/password",
        json={"newPassword": "An0therPassw0rd"},
        headers=headers,
    )
    assert r.status_code == 409, r.text


def test_admin_set_password_still_works_for_everyone_else(client, monkeypatch):
    _configure_env_admin(monkeypatch, f"owner-{uuid.uuid4().hex[:8]}@example.com")
    headers = _admin_headers(client)
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    user_id = _register(client, email)
    before = _stored_hash(user_id)

    r = client.post(
        f"/admin/users/{user_id}/password",
        json={"newPassword": "An0therPassw0rd"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert _stored_hash(user_id) != before
