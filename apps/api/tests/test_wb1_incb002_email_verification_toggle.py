"""INC-B-002 / FE-D-002 (GOLD-MASTER-V2 W-B wave 1, merged row) —
``emailVerificationEnabled`` is persisted by the admin settings endpoint but
never enforced anywhere, and the endpoint applies no real validation to the
field's value.

[VERIFIED-WITH-SOURCE] ``docs/delivery/INCOMPLETE-FEATURE-INVENTORY.md``
merged row (INC-B-002 = FE-D-002): the DB-persisted ``emailVerificationEnabled``
flag is never read by ``apps/api/app/routers/auth.py``'s ``register()``/
``login()`` -- unlike its sibling ``signupEnabled``, which IS enforced
(``auth.py`` ~line 85-87, ``signup_enabled()`` gate -> 403 before
registration proceeds). ``POST /admin/settings`` (``admin.py`` ~172-222)
accepts and persists the field via a plain ``Optional[bool]`` Pydantic field
with no additional server-side guard.

Two tests, mirroring the finding's own (a)/(b) split:

(a) ``test_email_verification_enabled_blocks_login_for_unverified_user`` --
    with the flag ON, a self-registered user (who by construction has never
    completed any verification step, because none exists) must be refused
    at login, the same way ``signupEnabled=false`` refuses at registration.
    Today the flag has literally zero effect -- login succeeds unconditionally.

(b) ``test_admin_settings_rejects_non_boolean_email_verification_value`` --
    [VERIFIED-WITH-SOURCE, empirically probed against the installed pydantic
    in this environment] a JSON boolean has exactly two literal values,
    ``true``/``false``. Pydantic's default LAX bool coercion silently accepts
    a materially wider set of non-boolean JSON types -- bare integers ``1``/
    ``0`` and the strings ``"yes"``/``"on"``/``"TRUE"`` -- and
    ``SettingsRequest`` (``admin.py``) applies no ``strict=True``/custom
    validator to narrow that, so ``POST /admin/settings`` silently coerces
    and PERSISTS these non-boolean values today (200, not 422) -- literally
    "persisting garbage" per the finding's own wording. (Clearly-malformed
    values like the string ``"banana"`` or a JSON array already 422 via
    pydantic's own ``bool_parsing``/``bool_type`` errors; those are NOT part
    of this reproduction and are covered separately below as a passing
    regression guard, not a failing case.)

A companion control test locks in the boundary of what already works, so a
future change can't accidentally regress it while fixing the loose-coercion
gap above.
"""
from __future__ import annotations

import uuid

import pytest

from app.db import get_connection
from app.repositories.admin import _ensure_admin_schema


# --------------------------------------------------------------------------- #
# Admin helpers (mirrors tests/test_gap_p6_admin.py's local pattern -- each
# test file in this suite owns its own copy rather than importing across
# files).
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


# --------------------------------------------------------------------------- #
# (a) enforcement parity with signupEnabled
# --------------------------------------------------------------------------- #


def test_email_verification_enabled_blocks_login_for_unverified_user(client):
    headers, _ = _admin(client)

    on = client.post(
        "/admin/settings", json={"emailVerificationEnabled": True}, headers=headers
    )
    assert on.status_code == 200, on.text
    assert on.json()["emailVerificationEnabled"] is True

    email = f"unverified-{uuid.uuid4().hex[:8]}@example.com"
    password = "Passw0rd1"
    register = client.post("/auth/register", json={"email": email, "password": password})
    # Registration itself is not the gated step (mirrors the finding: there
    # is no verification flow to complete, so the account is permanently
    # unverified) -- it must still succeed so there is an account to gate at
    # login.
    assert register.status_code == 201, register.text

    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code in (401, 403), (
        "emailVerificationEnabled=true must block login for an account that "
        "has never verified its email -- the SAME enforcement contract "
        "signupEnabled already gets at registration (auth.py: "
        "'Public registration is currently disabled', 403). Got "
        f"{login.status_code}: {login.text}"
    )

    # Regression guard within the same test: turning the flag back OFF must
    # restore login -- proves any fix is a real gate, not a permanent lockout.
    off = client.post(
        "/admin/settings", json={"emailVerificationEnabled": False}, headers=headers
    )
    assert off.status_code == 200 and off.json()["emailVerificationEnabled"] is False
    login2 = client.post("/auth/login", json={"email": email, "password": password})
    assert login2.status_code == 200, (
        f"turning emailVerificationEnabled back OFF must restore login, got "
        f"{login2.status_code}: {login2.text}"
    )


# --------------------------------------------------------------------------- #
# (b) reject non-boolean ("garbage") values instead of silently coercing
# --------------------------------------------------------------------------- #


#: JSON types that are NOT the boolean type but that pydantic's default lax
#: coercion currently accepts anyway -- see module docstring.
GARBAGE_BUT_CURRENTLY_ACCEPTED = [1, 0, "yes", "no", "on", "off", "TRUE"]


@pytest.mark.parametrize("garbage", GARBAGE_BUT_CURRENTLY_ACCEPTED)
def test_admin_settings_rejects_non_boolean_email_verification_value(client, garbage):
    headers, _ = _admin(client)
    resp = client.post(
        "/admin/settings", json={"emailVerificationEnabled": garbage}, headers=headers
    )
    assert resp.status_code == 422, (
        "POST /admin/settings must reject a non-boolean (garbage) value for "
        "emailVerificationEnabled with 422 rather than silently coercing and "
        f"persisting it, got {resp.status_code} for {garbage!r}: {resp.text[:500]!r}"
    )


#: Genuinely malformed values pydantic ALREADY rejects today -- a control
#: group, expected to PASS now and after any fix. Included so the evidence
#: file has a complete acceptance-boundary map, not to reproduce the defect.
ALREADY_REJECTED_CONTROL = ["banana", 123, [1, 2], {"a": 1}]


@pytest.mark.parametrize("bad_value", ALREADY_REJECTED_CONTROL)
def test_admin_settings_already_rejects_structurally_invalid_values(client, bad_value):
    """Control/regression-guard -- expected to PASS today. Locks in the part
    of the contract that already works so a future fix for the loose-
    coercion gap above doesn't accidentally loosen this instead."""
    headers, _ = _admin(client)
    resp = client.post(
        "/admin/settings", json={"emailVerificationEnabled": bad_value}, headers=headers
    )
    assert resp.status_code == 422, (
        f"expected 422 for structurally-invalid {bad_value!r}, got "
        f"{resp.status_code}: {resp.text[:500]!r}"
    )
