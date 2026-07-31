"""BLOCKER-001 (GOLD-MASTER-V2 §15 step 2) — failing tests for the confirmed
live-production security defect: ``admin``/``admin123`` resolves to the real
operator/owner account and is granted ``isAdmin: true``.

Full root-cause verification (production, read-only):
``uat/reports/evidence/gold-master-v2/phase0/BLOCKER-admin-overpermission-verification.md``

Two independent, compounding defects (both reproduced below):

* **D1 — weak operator credential.** The production ``AETHER_ADMIN_PASSWORD_HASH``
  is a bcrypt hash of the literal string ``admin123``. ``apply_admin_rotation()``
  (``apps/api/app/repositories/admin.py:569-613``) has no check that refuses a
  known-weak password — it blindly grants ``isAdmin=true`` to whatever hash the
  environment supplies.
* **D2 — identity collision.** The operator/owner ``User`` row independently
  carries ``username='admin'``. ``apply_admin_rotation()``'s "demote the seed,
  then regrant the env admin" logic (:588-608) nets out to ``isAdmin=true`` for
  that single row, and ``UserRepository.get_by_username_or_email('admin')``
  (``apps/api/app/repositories/user.py:114-134``) resolves the literal
  identifier ``admin`` straight to it.

This module writes TESTS ONLY (§0.4 separation of duties) — no fix is
implemented here. Every test below is a reproduction of a real defect and is
expected to FAIL against current code, with ONE explicit exception (rate
limiting already exists — see the pin test at the bottom, which is expected to
PASS and says so).
"""
from __future__ import annotations

import uuid

import pytest

from app.db import get_connection
from app.repositories.admin import (
    _ensure_admin_schema,
    _reset_admin_ready_for_tests,
    apply_admin_rotation,
)
from app.repositories.user import UserRepository
from app.security import hash_password

# --------------------------------------------------------------------------- #
# Item 1 (D1) — weak-admin-credential guard
# --------------------------------------------------------------------------- #

#: Known-weak passwords that must never be accepted as an operator admin
#: credential. ``admin123`` is the literal string CONFIRMED live on production
#: (verification report §3: "OPERATOR-HASH verifies 'admin123' ==> True").
_WEAK_ADMIN_PASSWORDS = ["admin123", "admin", "password", "changeme"]


@pytest.mark.parametrize("weak_password", _WEAK_ADMIN_PASSWORDS)
def test_rotation_refuses_known_weak_admin_password_hash(
    client, monkeypatch, weak_password
):
    """BLOCKER-001 item 1 / D1.

    ``apply_admin_rotation()`` must refuse to grant admin privilege from an
    ``AETHER_ADMIN_PASSWORD_HASH`` that verifies a known-weak password, when
    ``AETHER_ENV=production`` — mirroring the fail-fast idiom already
    established by ``app.main._guard_production_replay_mode`` (raises
    ``RuntimeError`` in production; see ``apps/api/app/main.py:93-118``, which
    this test's expectation is modelled on almost verbatim).

    Today ``apply_admin_rotation`` (``apps/api/app/repositories/admin.py:596-612``)
    performs zero validation of the hash it is given — it INSERTs/UPDATEs
    ``isAdmin=true`` unconditionally whenever ``AETHER_ADMIN_EMAIL`` +
    ``AETHER_ADMIN_PASSWORD_HASH`` are both set. No RuntimeError is raised for
    any of the weak passwords above, so this test fails on the ``pytest.raises``
    context manager itself ("DID NOT RAISE") — the correct, honest failure mode
    for "the guard does not exist yet".
    """
    env_email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", env_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", hash_password(weak_password))
    monkeypatch.setenv("AETHER_ENV", "production")
    _reset_admin_ready_for_tests()

    with pytest.raises(RuntimeError, match=r"(?i)weak"):
        apply_admin_rotation()


# --------------------------------------------------------------------------- #
# Item 2 (D2) — the demo identifier must not resolve to the operator
# --------------------------------------------------------------------------- #


def test_demo_identifier_must_not_resolve_to_operator_after_rotation(
    client, monkeypatch
):
    """BLOCKER-001 item 2 / D2.

    Reproduces the exact collision confirmed on production (verification
    report §3-§4.5): the operator/owner ``User`` row independently carries
    ``username='admin'`` (how it came to carry that value is not modelled here
    — only the resulting DB state, which is what production actually has).
    After ``apply_admin_rotation()`` runs, the identifier ``admin`` must NOT
    resolve to the operator's row — assert on identity (the resolved row's id),
    not merely on ``isAdmin``, per this task's explicit instruction.

    Fails today: ``apply_admin_rotation()`` only ever WRITES ``isAdmin``
    (:588-608); it never clears the colliding ``username``, so
    ``get_by_username_or_email('admin')`` still returns the operator's own row.
    """
    operator_email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    operator_password = "Str0ngOwnerPass9"
    operator = UserRepository().create(operator_email, hash_password(operator_password))

    _ensure_admin_schema()  # ensures the additive "username" column exists
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Simulate the observed production collision: the operator row
            # independently carries username='admin'.
            cur.execute(
                'UPDATE "User" SET "username"=%s WHERE "id"=%s',
                ("admin", operator["id"]),
            )
        conn.commit()

    monkeypatch.setenv("AETHER_ADMIN_EMAIL", operator_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", hash_password(operator_password))
    _reset_admin_ready_for_tests()
    apply_admin_rotation()

    resolved = UserRepository().get_by_username_or_email("admin")
    assert resolved is None or resolved["id"] != operator["id"], (
        "BLOCKER-001 D2: the demo identifier 'admin' resolved to the "
        f"operator/owner row {operator['id']!r} after rotation — the "
        "username alias was not cleared."
    )


# --------------------------------------------------------------------------- #
# Item 3 (D1+D2 end-to-end) — the demo credential must not authenticate at all
# --------------------------------------------------------------------------- #


def test_demo_identifier_admin123_login_rejected_end_to_end(client, monkeypatch):
    """BLOCKER-001 item 3 (adapted) — full end-to-end reproduction of the exact
    production exploit (verification report §1):
    ``POST /auth/login {"email":"admin","password":"admin123"}`` must return
    401, not 200. This is verbatim evidence-report §7.3 assertion 1, the most
    directly-exploitable proof of the defect.

    Adaptation note vs. the assignment's literal wording ("a genuine non-admin
    user's token must receive 403 [...] from admin endpoints"):
    ``apps/api/tests/test_gap_p6_admin.py::test_non_admin_gets_403_on_admin_routes``
    ALREADY covers exactly that scenario for a truly unprivileged registered
    user, and it ALREADY PASSES against current code (spot-checked below in
    this run's evidence — the admin gate itself is correctly implemented for
    genuine non-admins). Re-asserting it here would be a test that passes
    against current code, which this task explicitly forbids ("a 'failing'
    test that passes is a defect in your test"). The actual BLOCKER-001 defect
    is that the *demo* identifier ``admin`` is NOT a genuine non-admin — it
    resolves to the real operator row (D2) whose configured password hash
    verifies the literal weak string ``admin123`` (D1). This test reproduces
    that exact compound condition end-to-end through the public HTTP surface
    and asserts the login itself must be refused.

    Fails today: the login succeeds (200) and returns a bearer token for the
    operator's own identity.
    """
    operator_email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    operator_password = "Str0ngOwnerPass9"
    operator = UserRepository().create(operator_email, hash_password(operator_password))

    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "username"=%s WHERE "id"=%s',
                ("admin", operator["id"]),
            )
        conn.commit()

    # Mirror the confirmed production misconfiguration: the operator's own
    # configured admin password hash verifies the literal weak string
    # "admin123" (verification report §3: "OPERATOR-HASH verifies
    # 'admin123' ==> True").
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", operator_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", hash_password("admin123"))
    _reset_admin_ready_for_tests()
    apply_admin_rotation()

    resp = client.post("/auth/login", json={"email": "admin", "password": "admin123"})
    assert resp.status_code == 401, (
        "BLOCKER-001: identifier 'admin' + password 'admin123' authenticated "
        f"(HTTP {resp.status_code}) against the operator row {operator['id']!r} "
        f"— body={resp.text}"
    )


# --------------------------------------------------------------------------- #
# Item 4 — PII non-disclosure
# --------------------------------------------------------------------------- #


def test_admin_users_endpoint_never_leaks_pii_via_demo_credential(client, monkeypatch):
    """BLOCKER-001 item 4.

    ``GET /admin/users`` must never disclose another user's email address to a
    principal reached via the demo identifier ``admin`` + a known-weak
    password. Confirmed live on production (verification report §2):
    ``GET /admin/users`` returned real other-users' email addresses
    (``gm2-phase0-probe-...@example.com``, ``qa-deepsweep-...@example.com``)
    to this exact credential.

    Fails today: the login below succeeds (same D1+D2 compound condition as
    item 3) and the subsequent ``GET /admin/users`` returns 200 with the
    planted victim's email address in the body.
    """
    # A distinct, distinguishable "other user" whose email must never leak to
    # a principal that reached admin only through the demo-credential defect.
    victim_email = f"pii-victim-{uuid.uuid4().hex[:8]}@example.com"
    UserRepository().create(victim_email, hash_password("Passw0rd1"))

    operator_email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    operator_password = "Str0ngOwnerPass9"
    operator = UserRepository().create(operator_email, hash_password(operator_password))

    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "username"=%s WHERE "id"=%s',
                ("admin", operator["id"]),
            )
        conn.commit()

    monkeypatch.setenv("AETHER_ADMIN_EMAIL", operator_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", hash_password("admin123"))
    _reset_admin_ready_for_tests()
    apply_admin_rotation()

    login = client.post("/auth/login", json={"email": "admin", "password": "admin123"})
    assert login.status_code == 200, (
        "setup precondition failed (this itself would be good news — it means "
        f"item 3's defect is already fixed): got {login.status_code} {login.text}"
    )
    token = login.json()["access_token"]

    resp = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert victim_email not in resp.text, (
        "BLOCKER-001: GET /admin/users disclosed another user's email address "
        f"({victim_email}) to a principal reached via the demo identifier "
        f"'admin' + a known-weak password — HTTP {resp.status_code} "
        f"body={resp.text}"
    )


# --------------------------------------------------------------------------- #
# Item 5 — login throttling: ALREADY EXISTS. Pin test, not a defect repro.
# --------------------------------------------------------------------------- #


def test_login_rate_limiting_already_exists_pin(client):
    """BLOCKER-001 item 5 — rate-limiting audit.

    Source review (``apps/api/app/rate_limit.py``,
    ``apps/api/app/routers/auth.py:108-131``) plus existing coverage in
    ``apps/api/tests/test_auth.py`` (``TestLoginRateLimit`` — e.g.
    ``test_failed_logins_lock_a_single_identifier``) confirms login IS already
    rate-limited: 5 failed attempts per normalized identifier per 15-minute
    sliding window (``DEFAULT_LOGIN_MAX_FAILURES`` /
    ``DEFAULT_LOGIN_WINDOW_SECONDS``), keyed on the submitted identifier (never
    client IP; see ``rate_limit.py`` module docstring / ADR D-0033). A correct
    password is never throttled, and a successful login clears the
    identifier's counter.

    Per this task's explicit instruction ("If throttling DOES already exist,
    write a test that pins the existing behaviour and say so honestly instead
    of inventing a gap"): THIS TEST IS EXPECTED TO PASS against current code.
    It is a regression pin, not a BLOCKER-001 defect reproduction — do not
    count it toward "all tests fail before the fix". See
    ``uat/reports/evidence/gold-master-v2/phase0/BLOCKER-001-failing-tests.md``
    for the honest accounting (``rate_limiting_exists=true``).

    Honest residual NOT asserted here (out of scope for a non-mutating test,
    recorded for the fixer instead): because the identifier ``admin`` and the
    operator's real email resolve to the SAME row (D2), an unauthenticated
    caller can send 5 wrong passwords for identifier ``admin`` and lock out
    that identifier's bucket for 15 minutes, repeatably — a denial-of-service
    against the documented demo login path. See verification report §5b
    "Secondary observation".
    """
    identifier = f"ratelimit-pin-{uuid.uuid4().hex[:8]}@example.com"
    password = "Correct1Horse"
    register = client.post(
        "/auth/register", json={"email": identifier, "password": password}
    )
    assert register.status_code == 201, register.text

    statuses = [
        client.post(
            "/auth/login",
            json={"email": identifier, "password": "wrong-password-1"},
        ).status_code
        for _ in range(5)
    ]
    assert statuses == [401, 401, 401, 401, 401], statuses

    # The 6th attempt, even with the CORRECT password, is throttled.
    blocked = client.post(
        "/auth/login", json={"email": identifier, "password": password}
    )
    assert blocked.status_code == 429, blocked.text
    assert "Retry-After" in blocked.headers
