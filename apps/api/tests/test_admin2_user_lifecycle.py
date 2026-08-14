"""ADMIN-2.0 BE-1 — admin user CREATE / soft-DELETE / RESTORE + protected-account guards.

Contract under test (all routes ``AdminUser``-gated, every mutation audited):

* ``POST   /admin/users``                  — create a user with a generated temp
  password returned EXACTLY ONCE (never logged, never stored in plaintext,
  never written to the audit row) and ``mustChangePassword`` recorded.
* ``DELETE /admin/users/{id}``             — SOFT delete (the scout's ratified
  strategy: every child FK cascades, so a hard delete would destroy real work
  and the audit trail). Requires a body ``{"confirmEmail": "<target email>"}``
  that matches the target, and REFUSES admins / the §14.7 owner SERVER-SIDE.
* ``POST   /admin/users/{id}/restore``     — reverse the soft delete.
* ``POST   /admin/users/{id}/suspend``     — must ALSO refuse admins / the owner
  (program rule: "never delete/suspend admins or the owner — server-side guard
  required, not just UI").

MONEY SAFETY: nothing in this file touches Stripe.
"""
from __future__ import annotations

import uuid

import pytest

from app.db import get_connection
from app.repositories.admin import _ensure_admin_schema
from app.security import verify_password

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _register(client, email: str, password: str = "Passw0rd1") -> tuple[str, str]:
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (201, 409), r.text
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    body = login.json()
    return body["access_token"], body["userId"]


def _promote(user_id: str) -> None:
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (user_id,))
        conn.commit()


def _admin(client) -> tuple[dict[str, str], str]:
    token, uid = _register(client, f"admin-{uuid.uuid4().hex[:8]}@example.com")
    _promote(uid)
    return {"Authorization": f"Bearer {token}"}, uid


def _target(client) -> tuple[dict[str, str], str, str]:
    email = f"target-{uuid.uuid4().hex[:8]}@example.com"
    token, uid = _register(client, email)
    return {"Authorization": f"Bearer {token}"}, uid, email


def _audit_rows(target_id: str) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "action","detailJson","actorUserId" FROM "AdminAuditLog"'
                ' WHERE "targetId"=%s ORDER BY "createdAt" DESC',
                (target_id,),
            )
            return [
                {"action": r[0], "detail": r[1], "actor": r[2]} for r in cur.fetchall()
            ]


def _user_row(user_id: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "email","passwordHash","suspended","deletedAt",'
                '"mustChangePassword" FROM "User" WHERE "id"=%s',
                (user_id,),
            )
            r = cur.fetchone()
    assert r is not None, "user row missing"
    return {
        "email": r[0],
        "passwordHash": r[1],
        "suspended": bool(r[2]),
        "deletedAt": r[3],
        "mustChangePassword": bool(r[4]),
    }


# --------------------------------------------------------------------------- #
# Gating — every new route is AdminUser-gated (401 anon, 403 non-admin)
# --------------------------------------------------------------------------- #


def test_create_user_route_is_admin_gated(client, auth_headers):
    body = {"email": f"x-{uuid.uuid4().hex[:6]}@example.com"}
    assert client.post("/admin/users", json=body).status_code == 401
    assert client.post("/admin/users", json=body, headers=auth_headers).status_code == 403


def test_delete_user_route_is_admin_gated(client, auth_headers):
    body = {"confirmEmail": "nobody@example.com"}
    assert client.request("DELETE", "/admin/users/x", json=body).status_code == 401
    assert (
        client.request(
            "DELETE", "/admin/users/x", json=body, headers=auth_headers
        ).status_code
        == 403
    )


def test_restore_user_route_is_admin_gated(client, auth_headers):
    assert client.post("/admin/users/x/restore", json={}).status_code == 401
    assert (
        client.post("/admin/users/x/restore", json={}, headers=auth_headers).status_code
        == 403
    )


# --------------------------------------------------------------------------- #
# (a) CREATE
# --------------------------------------------------------------------------- #


def test_admin_create_user_returns_a_working_temp_password_exactly_once(client):
    admin_headers, admin_id = _admin(client)
    email = f"created-{uuid.uuid4().hex[:8]}@example.com"

    r = client.post(
        "/admin/users", json={"email": email, "name": "Created User"}, headers=admin_headers
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == email
    assert body["name"] == "Created User"
    assert body["mustChangePassword"] is True
    temp = body["tempPassword"]
    assert isinstance(temp, str) and len(temp) >= 16

    # The password WORKS (it is the real credential, not a decorative string).
    login = client.post("/auth/login", json={"email": email, "password": temp})
    assert login.status_code == 200, login.text

    # Stored HASHED, never plaintext.
    row = _user_row(body["userId"])
    assert row["passwordHash"] != temp
    assert verify_password(temp, row["passwordHash"])
    assert row["mustChangePassword"] is True

    # Audited — with the actor and the email, and NEVER any password material.
    rows = _audit_rows(body["userId"])
    assert [a["action"] for a in rows] == ["create_user"]
    assert rows[0]["actor"] == admin_id
    detail = rows[0]["detail"] or {}
    assert detail.get("email") == email
    assert temp not in str(detail)
    assert "password" not in str(detail).lower() or "mustChangePassword" in str(detail)


def test_admin_create_user_seeds_billing_and_shows_up_in_the_admin_list(client):
    admin_headers, _ = _admin(client)
    email = f"created-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/admin/users", json={"email": email}, headers=admin_headers)
    assert r.status_code == 201, r.text
    user_id = r.json()["userId"]

    detail = client.get(f"/admin/users/{user_id}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["subscription"] is not None
    assert payload["subscription"]["planId"] == "free"
    assert payload["user"]["mustChangePassword"] is True
    assert payload["user"]["deletedAt"] is None


def test_admin_create_user_rejects_a_duplicate_email_with_409(client):
    admin_headers, _ = _admin(client)
    _, _, existing = _target(client)
    r = client.post("/admin/users", json={"email": existing}, headers=admin_headers)
    assert r.status_code == 409, r.text


@pytest.mark.parametrize("bad", ["", "   ", "not-an-email", "a b@example.com", 12])
def test_admin_create_user_rejects_a_malformed_email_with_422(client, bad):
    admin_headers, _ = _admin(client)
    r = client.post("/admin/users", json={"email": bad}, headers=admin_headers)
    assert r.status_code == 422, f"{bad!r}: {r.status_code} {r.text}"


def test_admin_create_user_cannot_mint_another_admin(client):
    """Privilege escalation surface: the create route never grants isAdmin."""
    admin_headers, _ = _admin(client)
    email = f"created-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/admin/users", json={"email": email, "isAdmin": True}, headers=admin_headers
    )
    assert r.status_code == 201, r.text
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "isAdmin" FROM "User" WHERE "id"=%s', (r.json()["userId"],))
            assert bool(cur.fetchone()[0]) is False


# --------------------------------------------------------------------------- #
# (b) DELETE — soft, confirmed, and server-side-guarded
# --------------------------------------------------------------------------- #


def test_admin_delete_user_soft_deletes_and_revokes_access(client):
    admin_headers, admin_id = _admin(client)
    target_headers, target_id, target_email = _target(client)

    # The target can use the API before the delete.
    assert client.get("/auth/me", headers=target_headers).status_code == 200

    r = client.request(
        "DELETE",
        f"/admin/users/{target_id}",
        json={"confirmEmail": target_email},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] is True
    assert body["mode"] == "soft"
    assert body["deletedAt"]
    assert body["suspended"] is True

    row = _user_row(target_id)
    assert row["deletedAt"] is not None
    assert row["suspended"] is True

    # Access is REALLY revoked (not merely flagged).
    assert client.get("/auth/me", headers=target_headers).status_code == 403

    actions = [a["action"] for a in _audit_rows(target_id)]
    assert "delete_user" in actions
    assert _audit_rows(target_id)[0]["actor"] == admin_id


def test_admin_delete_user_requires_a_matching_confirm_email(client):
    admin_headers, _ = _admin(client)
    _, target_id, target_email = _target(client)

    for body in ({}, {"confirmEmail": ""}, {"confirmEmail": "someone-else@example.com"}):
        r = client.request(
            "DELETE", f"/admin/users/{target_id}", json=body, headers=admin_headers
        )
        assert r.status_code == 422, f"{body}: {r.status_code} {r.text}"

    assert _user_row(target_id)["deletedAt"] is None
    assert [a["action"] for a in _audit_rows(target_id)] == []

    # Case-insensitive match is accepted (email comparison is case-insensitive).
    r = client.request(
        "DELETE",
        f"/admin/users/{target_id}",
        json={"confirmEmail": target_email.upper()},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text


def test_admin_delete_refuses_an_admin_account_server_side(client):
    admin_headers, _ = _admin(client)
    other_headers, other_admin_id = _admin(client)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "email" FROM "User" WHERE "id"=%s', (other_admin_id,))
            other_email = cur.fetchone()[0]

    r = client.request(
        "DELETE",
        f"/admin/users/{other_admin_id}",
        json={"confirmEmail": other_email},
        headers=admin_headers,
    )
    assert r.status_code == 409, r.text
    assert _user_row(other_admin_id)["deletedAt"] is None
    # Still an admin, still able to use the API.
    assert client.get("/auth/me", headers=other_headers).status_code == 200


def test_admin_delete_refuses_the_env_managed_owner(client, monkeypatch):
    admin_headers, _ = _admin(client)
    _, target_id, target_email = _target(client)
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", target_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", "$2b$12$" + "x" * 53)

    r = client.request(
        "DELETE",
        f"/admin/users/{target_id}",
        json={"confirmEmail": target_email},
        headers=admin_headers,
    )
    assert r.status_code == 409, r.text
    assert _user_row(target_id)["deletedAt"] is None


def test_admin_delete_is_not_silently_repeatable(client):
    admin_headers, _ = _admin(client)
    _, target_id, target_email = _target(client)
    body = {"confirmEmail": target_email}
    assert (
        client.request(
            "DELETE", f"/admin/users/{target_id}", json=body, headers=admin_headers
        ).status_code
        == 200
    )
    r = client.request(
        "DELETE", f"/admin/users/{target_id}", json=body, headers=admin_headers
    )
    assert r.status_code == 409, r.text


def test_admin_delete_404s_for_an_unknown_user(client):
    admin_headers, _ = _admin(client)
    r = client.request(
        "DELETE",
        "/admin/users/no-such-user",
        json={"confirmEmail": "nobody@example.com"},
        headers=admin_headers,
    )
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# RESTORE
# --------------------------------------------------------------------------- #


def test_admin_restore_reverses_the_soft_delete_without_silently_unsuspending(client):
    admin_headers, _ = _admin(client)
    target_headers, target_id, target_email = _target(client)
    client.request(
        "DELETE",
        f"/admin/users/{target_id}",
        json={"confirmEmail": target_email},
        headers=admin_headers,
    )

    r = client.post(f"/admin/users/{target_id}/restore", json={}, headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] is False
    assert body["deletedAt"] is None
    # The suspension the delete applied is NOT silently lifted — an admin must
    # unsuspend deliberately, and the response says so instead of implying access.
    assert body["suspended"] is True
    assert client.get("/auth/me", headers=target_headers).status_code == 403

    assert client.post(
        f"/admin/users/{target_id}/unsuspend", headers=admin_headers
    ).status_code == 200
    assert client.get("/auth/me", headers=target_headers).status_code == 200
    assert "restore_user" in [a["action"] for a in _audit_rows(target_id)]


def test_admin_restore_on_a_live_user_is_an_honest_409(client):
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    r = client.post(f"/admin/users/{target_id}/restore", json={}, headers=admin_headers)
    assert r.status_code == 409, r.text


# --------------------------------------------------------------------------- #
# Protected accounts — suspend must be guarded too (not just the UI)
# --------------------------------------------------------------------------- #


def test_admin_suspend_refuses_an_admin_account_server_side(client):
    admin_headers, _ = _admin(client)
    other_headers, other_admin_id = _admin(client)
    r = client.post(f"/admin/users/{other_admin_id}/suspend", headers=admin_headers)
    assert r.status_code == 409, r.text
    assert _user_row(other_admin_id)["suspended"] is False
    assert client.get("/auth/me", headers=other_headers).status_code == 200


def test_admin_suspend_refuses_the_env_managed_owner(client, monkeypatch):
    admin_headers, _ = _admin(client)
    _, target_id, target_email = _target(client)
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", target_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", "$2b$12$" + "x" * 53)
    r = client.post(f"/admin/users/{target_id}/suspend", headers=admin_headers)
    assert r.status_code == 409, r.text
    assert _user_row(target_id)["suspended"] is False


def test_admin_suspend_still_works_for_an_ordinary_user(client):
    admin_headers, _ = _admin(client)
    target_headers, target_id, _ = _target(client)
    assert client.post(
        f"/admin/users/{target_id}/suspend", headers=admin_headers
    ).status_code == 200
    assert client.get("/auth/me", headers=target_headers).status_code == 403


# --------------------------------------------------------------------------- #
# mustChangePassword is TRUTHFUL: a self-service reset clears it
# --------------------------------------------------------------------------- #


def test_self_service_password_reset_clears_must_change_password(client):
    admin_headers, _ = _admin(client)
    email = f"created-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/admin/users", json={"email": email}, headers=admin_headers)
    assert r.status_code == 201, r.text
    user_id = r.json()["userId"]
    assert _user_row(user_id)["mustChangePassword"] is True

    from app.repositories.user import UserRepository
    from app.security import hash_password

    UserRepository().set_password(user_id, hash_password("Ch0senByTheUser"))
    assert _user_row(user_id)["mustChangePassword"] is False
