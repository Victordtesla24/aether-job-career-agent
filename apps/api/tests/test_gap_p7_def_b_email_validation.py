"""GAP-P7-DEF-B: PUT /workspaces/settings rejects a stored internal-use email
(e.g. ``admin@aether.local``) with 422.

[VERIFIED-WITH-SOURCE] Root cause confirmed directly against the installed
``email-validator==2.3.0`` + pydantic ``EmailStr`` in this environment
(2026-07-17): ``SPECIAL_USE_DOMAIN_NAMES`` is
``['arpa', 'invalid', 'local', 'localhost', 'onion', 'test']`` and
``email_validator/syntax.py::validate_email_domain_name`` rejects any domain
that equals, or ends with ``"." + d``, for ``d`` in that list — independent of
``check_deliverability`` (see apps/api/app/routers/workspaces.py:625,
``SettingsProfile.email: EmailStr``). ``admin@aether.local`` ends with
``.local`` -> rejected. ``user@localhost`` fails a DIFFERENT, earlier check
("no period in domain") that has nothing to do with
``SPECIAL_USE_DOMAIN_NAMES`` -> always rejected regardless of any allowlist.
``user@foo.test`` ends with ``.test`` -> rejected and stays rejected unless
"test" itself is discarded (out of scope: only "aether.local" is
allow-listed by default). ``valid.person@example.com`` and garbage strings
are unaffected either way.

Approved fix (§15.2 operator brief / ADR-P7-02, Option 3 — NOT YET
IMPLEMENTED as of this commit, which is the TDD fail-before state): at app
startup, read ``AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS`` (default
``"aether.local"``) and discard the corresponding entry/entries from
``email_validator.SPECIAL_USE_DOMAIN_NAMES`` so EmailStr accepts the
configured internal domain(s) while every OTHER special-use domain remains
rejected. No DB migration; no change to what update_settings() persists.

[INFERRED-FROM-PROMPT] This test file assumes the startup hook will be a
standalone, idempotent, re-callable function named
``app.main.apply_email_domain_allowlist`` (mirroring the existing
``apply_admin_rotation()`` §14.7 pattern already wired into ``_lifespan`` in
apps/api/app/main.py). The gap record does not name the function explicitly;
the fixer implementing §15.2 may rename it, but must update this test file in
the SAME change if it does — the name is this test's assumption, not a
contract handed down from the operator brief.

FAIL-BEFORE STATUS (recorded 2026-07-17, pre-fix; see
uat/reports/evidence/phase7/gap-def-b-tdd-fail.txt for the actual pytest
run):
  - test_settings_save_aether_local_returns_200            -> FAILS (422 today)
  - test_settings_save_valid_external_email_returns_200     -> PASSES already (unaffected by the gap; kept as a regression guard)
  - test_settings_save_garbage_email_returns_422             -> PASSES already (garbage fails a syntax check unrelated to SPECIAL_USE_DOMAIN_NAMES)
  - test_settings_save_localhost_still_rejected               -> PASSES already ("no period" check fires before special-use check either way)
  - test_other_special_use_domains_still_rejected              -> PASSES already (only "aether.local" is allow-listed; "foo.test" stays rejected)
  - test_allowed_domains_configurable_via_env                   -> FAILS (apply_email_domain_allowlist does not exist yet -> ImportError)
  - test_email_not_changed_unrelated_field_save_succeeds          -> FAILS (422, same root cause as the base case)
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, EmailStr


def _settings_payload(email: str, full_name: str = "Test User") -> dict:
    """A minimally valid SettingsUpdate body (see workspaces.py SettingsUpdate)."""
    return {
        "profile": {
            "fullName": full_name,
            "email": email,
            "targetRole": "Software Engineer",
            "location": "Remote",
        },
        "agentConfig": {
            "autoApply": False,
            "approvalGate": True,
            "matchThreshold": 80,
        },
    }


def test_settings_save_aether_local_returns_200(client, auth_headers):
    """Target behaviour (§15): the default-allow-listed internal domain
    round-trips through PUT /workspaces/settings as 200, not 422."""
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("admin@aether.local"),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


def test_settings_save_valid_external_email_returns_200(client, auth_headers):
    """Guard: an ordinary external email must keep working (already true
    today — "example.com" is not in SPECIAL_USE_DOMAIN_NAMES)."""
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("valid.person@example.com"),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


def test_settings_save_garbage_email_returns_422(client, auth_headers):
    """Guard: syntactically invalid input must still 422 — the allowlist only
    ever discards specific special-use domain suffixes, it never disables
    email syntax validation."""
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("not-an-email"),
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


def test_settings_save_localhost_still_rejected(client, auth_headers):
    """Guard: "user@localhost" has no period in the domain part, which
    email-validator rejects on a syntax check that fires BEFORE the
    SPECIAL_USE_DOMAIN_NAMES check the allowlist touches — it must remain
    422 both before and after the §15 fix."""
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("user@localhost"),
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


def test_other_special_use_domains_still_rejected(client, auth_headers):
    """Guard: the allowlist opens ONLY the configured domain(s)
    (default "aether.local" -> discards "local"). Every other reserved TLD —
    proven here with ".test" — must stay rejected."""
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("someone@foo.test"),
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


def test_allowed_domains_configurable_via_env(monkeypatch):
    """§15.2 target: the allowlist is env-driven, not hardcoded to
    "aether.local" — re-running the startup hook after changing
    AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS allow-lists a DIFFERENT domain.

    Uses the reserved name "onion" (Tor .onion addresses) as the probe:
    it is untouched by the default "aether.local" configuration and by
    every other test in this file, so this test cannot leak a false pass/
    fail into its neighbours. The module-level SPECIAL_USE_DOMAIN_NAMES
    list is snapshotted and restored so this test also cannot leak into
    other test files run in the same pytest session.
    """
    import email_validator

    original = list(email_validator.SPECIAL_USE_DOMAIN_NAMES)
    try:
        class _Probe(BaseModel):
            email: EmailStr

        # Sanity: "onion" is special-use before any allow-listing.
        with pytest.raises(Exception):
            _Probe(email="node@example.onion")

        monkeypatch.setenv("AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS", "example.onion")

        # NOT YET IMPLEMENTED — this import is expected to fail until §15.2
        # lands (TDD fail-before for this test).
        from app.main import apply_email_domain_allowlist

        apply_email_domain_allowlist()

        # "onion" must now be allowed.
        _Probe(email="node@example.onion")
    finally:
        email_validator.SPECIAL_USE_DOMAIN_NAMES[:] = original


def test_email_not_changed_unrelated_field_save_succeeds(client, auth_headers, test_user_id, db_session):
    """Reproduces the exact production shape (probe-p7-09a/09c): a user row
    already has an @aether.local email stored, and the settings save that
    fails is one that keeps the email unchanged but edits an unrelated field
    (display name). Must be 200, not 422."""
    with db_session.cursor() as cur:
        cur.execute('UPDATE "User" SET email = %s WHERE id = %s', ("admin@aether.local", test_user_id))
    db_session.commit()

    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("admin@aether.local", full_name="New Display Name"),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
