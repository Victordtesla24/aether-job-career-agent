"""RT-001 — account-level password flows never leak deployment internals.

Owner-reported runtime defect (2026-08-16): the admin set-password 409 for the
env-managed identity returned the internal env-var name
(``AETHER_ADMIN_PASSWORD_HASH``) plus its rotation runbook to the CLIENT. The
class rule (Architect ruling): deployment internals may appear only in
operator-scoped deployment-config diagnostics and in SERVER LOGS — never in an
account-level flow's HTTP response. Additionally the admin user-detail payload
now carries ``passwordManaged`` so the UI can suppress the dead affordance
upfront instead of offering an action that 409s on submit.
"""
from __future__ import annotations

import re

_INTERNALS = re.compile(r"AETHER_[A-Z_]+|bcrypt|restart the api", re.IGNORECASE)


def _make_env_managed(monkeypatch, email: str) -> None:
    """Point §14.7 at this email so password_is_env_managed(email) is True."""
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", email)
    # Any syntactically-valid bcrypt prefix satisfies the config-shape check.
    monkeypatch.setenv(
        "AETHER_ADMIN_PASSWORD_HASH",
        "$2b$12$C6UzMDM.H6dfI/f/IKcEeO7ZBpMR1I1B1eGz0/0eXn0mW8kXlYQfa",
    )


def test_admin_set_password_409_carries_no_internals(
    client, auth_headers, promote_user_to_admin, test_user_id, monkeypatch
):
    promote_user_to_admin(test_user_id)
    me = client.get("/auth/me", headers=auth_headers).json()
    _make_env_managed(monkeypatch, me["email"])

    r = client.post(
        f"/admin/users/{test_user_id}/password",
        json={"newPassword": "BrandNewPassw0rd1!"},
        headers=auth_headers,
    )
    assert r.status_code == 409, r.text
    detail = str(r.json().get("detail") or "")
    assert detail, "409 must carry a human-readable reason"
    assert not _INTERNALS.search(detail), (
        f"deployment internals leaked into an account-level error: {detail!r}"
    )
    assert "operator" in detail.lower(), "message should direct to the operator"


def test_reset_completion_409_carries_no_internals(
    client, auth_headers, test_user_id, monkeypatch
):
    from app.services.password_reset import create_reset_token

    me = client.get("/auth/me", headers=auth_headers).json()
    _make_env_managed(monkeypatch, me["email"])
    token = create_reset_token(test_user_id)

    r = client.post(
        "/auth/reset-password",
        json={"token": token, "password": "BrandNewPassw0rd1!"},
    )
    assert r.status_code == 409, r.text
    detail = str(r.json().get("detail") or "")
    assert not _INTERNALS.search(detail), (
        f"deployment internals leaked to an UNAUTHENTICATED flow: {detail!r}"
    )


def test_user_detail_carries_password_managed_flag(
    client, auth_headers, promote_user_to_admin, test_user_id, monkeypatch
):
    promote_user_to_admin(test_user_id)
    me = client.get("/auth/me", headers=auth_headers).json()

    # Not env-managed -> False (the control may be offered).
    monkeypatch.delenv("AETHER_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("AETHER_ADMIN_PASSWORD_HASH", raising=False)
    r = client.get(f"/admin/users/{test_user_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json().get("passwordManaged") is False

    # Env-managed -> True (the UI must suppress the dead affordance).
    _make_env_managed(monkeypatch, me["email"])
    r = client.get(f"/admin/users/{test_user_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json().get("passwordManaged") is True
