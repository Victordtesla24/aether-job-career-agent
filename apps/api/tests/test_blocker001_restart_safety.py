"""BLOCKER-001 restart safety — the weak-credential guard must not take the
site down, and must still refuse the weak credential.

Context. ``7f82105`` added a guard that RAISED
``AdminCredentialSecurityError`` from ``apply_admin_rotation()`` when
``AETHER_ADMIN_PASSWORD_HASH`` verifies a known-weak password under
``AETHER_ENV=production``, and ``app.main._lifespan`` let it propagate — so the
API refused to boot. systemd runs the API straight out of this working tree
(``docs/delivery/DEPLOYMENT-RUNBOOK.md``), production's live hash is exactly
what that guard rejects, and ``Restart=on-failure`` is set: every restart path
(reboot, crash, deploy, ``systemctl restart``) would have taken production down
for paying customers until a human rotated a credential.

The design these tests pin is fail-SAFE at boot, fail-CLOSED at auth:

* boot SUCCEEDS, logging CRITICAL and recording a degraded flag;
* the ``isAdmin`` grant is REFUSED (the weak credential gains no privilege);
* the reserved ``admin`` identifier cannot authenticate with a denylisted
  password;
* ``GET /admin/health`` surfaces the condition without echoing any secret.

The last test pins the deliberate NARROWNESS of the auth refusal. On this
deployment ``AETHER_CRON_EMAIL`` is the same identity as ``AETHER_ADMIN_EMAIL``
and ``AETHER_CRON_PASSWORD`` is the same weak value, so the 30-minute discovery
timer authenticates with exactly that pair. Refusing by password VALUE (rather
than by the reserved identifier) would silently kill production job sourcing.
Do not widen the refusal without rotating that credential first.
"""
from __future__ import annotations

import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
from app.repositories import admin as admin_repo
from app.repositories.user import UserRepository
from app.security import hash_password

#: The literal confirmed live on production behind AETHER_ADMIN_PASSWORD_HASH.
_WEAK = "admin123"


def _make_production_env(monkeypatch) -> None:
    """Put the process in the exact production shape this guard reacts to.

    ``create_app()`` also refuses to build a production app while the LLM
    replay mode / discovery fixtures are active (``_guard_production_replay_mode``,
    ``_guard_production_discovery_fixtures``), both of which conftest pins on
    for the suite — so they are cleared here. No agent/LLM call is made by any
    test in this module, so ``live`` mode never reaches a provider.
    """
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("AETHER_LLM_MODE", "live")
    monkeypatch.delenv("AETHER_DISCOVERY_FIXTURE_DIR", raising=False)


def _seed_operator_like_production(monkeypatch) -> tuple[str, str]:
    """Recreate production's row + env state; return (email, user id).

    Mirrors what production actually has after previous boots (ADR §1 F5): the
    operator row already carries the weak password hash, the reserved ``admin``
    username alias AND ``isAdmin=true``, and the env points ``AETHER_ADMIN_*``
    at it. Starting from ``isAdmin=true`` is what makes these tests able to
    detect the "merely skipping the grant is a no-op" failure (ADR condition
    C3) rather than passing vacuously.
    """
    email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    user = UserRepository().create(email, hash_password(_WEAK))
    admin_repo._ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "username"=%s,"isAdmin"=true WHERE "id"=%s',
                ("admin", user["id"]),
            )
        conn.commit()
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", hash_password(_WEAK))
    _make_production_env(monkeypatch)
    admin_repo._reset_admin_ready_for_tests()
    admin_repo._reset_admin_credential_state_for_tests()
    return email, user["id"]


@pytest.fixture()
def degraded_client(monkeypatch):
    """A booted app whose operator credential is the known-weak production one."""
    from app.main import create_app

    email, user_id = _seed_operator_like_production(monkeypatch)
    with TestClient(create_app()) as test_client:
        yield test_client, email, user_id


def test_production_boot_with_weak_credential_succeeds_and_logs_critical(
    monkeypatch, caplog
):
    """FAIL-SAFE AT BOOT: the live outage this fix removes.

    Before the fix this raised ``AdminCredentialSecurityError`` out of the
    lifespan, so the ASGI app never came up.
    """
    from app.main import create_app

    _seed_operator_like_production(monkeypatch)

    with caplog.at_level(logging.CRITICAL, logger="app.repositories.admin"):
        with TestClient(create_app()) as test_client:
            # It BOOTS, and it SERVES: an ordinary unauthenticated request is
            # answered normally while the credential is still unrotated.
            assert test_client.get("/health").status_code == 200

    critical = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert critical, "no CRITICAL log line was emitted for the degraded credential"
    joined = "\n".join(r.getMessage() for r in critical)
    assert "AETHER_ADMIN_PASSWORD_HASH" in joined, joined  # names the exact env var
    assert "Rotate" in joined, joined  # names the operator remediation
    assert admin_repo.admin_credential_degraded() is True


def test_degraded_state_revokes_isadmin_end_to_end_through_boot(degraded_client):
    """FAIL-CLOSED ON PRIVILEGE, through the real boot path.

    The row starts ``isAdmin=true`` (production's actual state), so this fails
    if rotation merely SKIPS the grant. Asserted here after a full
    ``TestClient(create_app())`` startup — i.e. through ``_lifespan``, not by
    calling ``apply_admin_rotation`` directly — so it also pins that the
    lifespan handler cannot swallow the revoke.
    """
    client, email, _user_id = degraded_client
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "isAdmin" FROM "User" WHERE "email"=%s', (email,))
            row = cur.fetchone()
    assert row is not None
    assert row[0] is False, (
        "BLOCKER-001: the §14.7 rotation left isAdmin=true for a known-weak "
        "AETHER_ADMIN_PASSWORD_HASH after a full application boot."
    )

    # ...and the privilege is gone at the HTTP layer too, for a session minted
    # with the (unchanged) password — isAdmin is re-read from the row per
    # request, so this also covers tokens issued before the revoke.
    login = client.post("/auth/login", json={"email": email, "password": _WEAK})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/admin/users", headers=headers).status_code == 403
    assert client.get("/admin/health", headers=headers).status_code == 403


def test_degraded_state_rejects_published_admin_credential(degraded_client):
    """FAIL-CLOSED AT AUTH: ``admin``/``admin123`` gets neither admin nor a session."""
    client, _email, user_id = degraded_client

    resp = client.post("/auth/login", json={"email": "admin", "password": _WEAK})
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "Invalid email or password"  # no enumeration

    # ...and the identifier no longer resolves to the operator row at all.
    resolved = UserRepository().get_by_username_or_email("admin")
    assert resolved is None or resolved["id"] != user_id


def test_degraded_state_is_surfaced_on_admin_health_without_leaking_secrets():
    """An operator can SEE the condition; the payload carries no credential."""
    admin_repo._reset_admin_credential_state_for_tests()
    clean = admin_repo.health_overview()
    assert clean["security"] == {"adminCredentialDegraded": False, "remediation": None}

    admin_repo._record_admin_credential_state(
        admin_repo._audit_admin_credential("owner@aether.io", hash_password(_WEAK))
    )
    try:
        degraded = admin_repo.health_overview()
        assert degraded["security"]["adminCredentialDegraded"] is True
        remediation = degraded["security"]["remediation"]
        assert "AETHER_ADMIN_PASSWORD_HASH" in remediation
        # The matched denylist entry IS the live production password on a
        # degraded deploy — it belongs in the log, never in an HTTP payload.
        # The payload is a fixed constant that quotes no denylist entry and
        # never contains the confirmed live literal.
        assert remediation == admin_repo._DEGRADED_ADMIN_REMEDIATION
        assert _WEAK not in remediation
        for weak in admin_repo._KNOWN_WEAK_ADMIN_PASSWORDS:
            assert f"'{weak}'" not in remediation
            assert f'"{weak}"' not in remediation
    finally:
        admin_repo._reset_admin_credential_state_for_tests()


def test_degraded_state_does_not_break_the_scheduled_discovery_login(degraded_client):
    """SCOPE PIN — do not widen the auth refusal without rotating the credential.

    ``scripts/discovery_cron.sh`` logs in with ``AETHER_CRON_EMAIL`` /
    ``AETHER_CRON_PASSWORD``, which on this deployment are the operator's email
    and the same weak password. A refusal keyed on the password value would 401
    this login and silently stop all scheduled job sourcing. The refusal is
    keyed on the reserved ``admin`` identifier instead, so the email-identifier
    login still authenticates.
    """
    client, email, _user_id = degraded_client
    resp = client.post("/auth/login", json={"email": email, "password": _WEAK})
    assert resp.status_code == 200, (
        "the scheduled discovery login was refused — this change would kill "
        f"production job sourcing: {resp.text}"
    )
    token = resp.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    # It is a NON-admin session: the cron keeps working, the privilege is gone.
    assert me.json()["isAdmin"] is False
