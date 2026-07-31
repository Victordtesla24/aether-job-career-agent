"""ML-settings-006 (GOLD-MASTER-V2 W-B wave 1) — a NUL byte (0x00) in a
``PUT /workspaces/settings`` profile string field crashes with a raw 500
instead of an honest 422.

[VERIFIED-WITH-SOURCE] ``apps/api/app/routers/workspaces.py::update_settings``
(~line 1092) passes ``payload.profile.fullName`` / ``.targetRole`` /
``.location`` straight into a parameterized ``cur.execute(...)`` with no
NUL-byte guard. psycopg2 raises
``ValueError: A string literal cannot contain NUL (0x00) characters.``
BEFORE the SQL ever reaches Postgres — nothing in ``app.main`` registers an
exception handler for a bare ``ValueError``, so it propagates out of the
route as an unhandled server error.

Live evidence (production, fresh this run):
``uat/reports/evidence/gold-master-v2/runtime/RUNTIME-MONITOR-REPORT-2-500-correlation.md``
— full traceback captured 2026-07-30T23:50:46Z pointing at exactly
``workspaces.py:1092`` inside ``update_settings``.

Reproduction technique: the default ``TestClient`` (``raise_server_exceptions
=True``) would re-raise the ``ValueError`` straight into the test process
rather than surfacing the real HTTP response a production uvicorn deployment
sends. We use a SEPARATE ``TestClient(client.app, raise_server_exceptions=
False)`` bound to the SAME app/DB (the same technique already established in
``tests/test_ml_signup_001.py::test_entitlement_endpoint_200s_even_when_a_
concurrent_insert_is_in_flight``) so ``resp.status_code`` reflects the real
500 a caller would see.

``email`` is included in the parametrize for completeness of the stated
contract ("must return 422 ... across the fields") but is expected to
ALREADY pass today: ``SettingsProfile.email`` runs through
``_validate_settings_email`` (an ``AfterValidator`` backed by
``email_validator``) BEFORE the DB layer, and ``email_validator`` already
rejects a NUL byte in the local-part as an invalid character — confirmed
empirically against the installed ``email-validator`` in this environment
(see WB1 evidence file). That parametrize id is a REGRESSION GUARD, not a
reproduction of this defect.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

NUL = "\x00"


def _settings_payload(**profile_overrides: str) -> dict:
    """A minimally valid SettingsUpdate body (see workspaces.py SettingsUpdate)."""
    profile = {
        "fullName": "Test User",
        "email": f"wb1-nul-{uuid.uuid4().hex[:8]}@example.com",
        "targetRole": "Software Engineer",
        "location": "Remote",
    }
    profile.update(profile_overrides)
    return {
        "profile": profile,
        "agentConfig": {"autoApply": False, "approvalGate": True, "matchThreshold": 80},
    }


def _nul_value_for(field: str) -> str:
    if field == "email":
        # A syntactically-plausible address with a NUL embedded in the
        # local-part -- exercises the SAME "NUL byte in a profile string
        # field" class of input the finding describes, on the field that
        # goes through the pydantic email validator instead of straight to
        # the DB layer.
        return f"wb1nul{NUL}user@example.com"
    return f"Bad{NUL}Value"


def _assert_honest_422(resp, field: str) -> None:
    assert resp.status_code == 422, (
        f"NUL byte in profile.{field} must be rejected with 422 (honest, "
        f"specific validation error) — never 500. Got {resp.status_code}. "
        f"Body: {resp.text[:2000]!r}"
    )
    body_text = resp.text
    assert "Traceback" not in body_text, f"raw traceback leaked into response: {body_text[:500]!r}"
    assert "ValueError" not in body_text, f"raw exception class leaked into response: {body_text[:500]!r}"
    assert "psycopg2" not in body_text, f"raw driver internals leaked into response: {body_text[:500]!r}"


def test_nul_byte_in_full_name_returns_422_not_500(client, auth_headers):
    prod_like_client = TestClient(client.app, raise_server_exceptions=False)
    payload = _settings_payload(fullName=_nul_value_for("fullName"))
    resp = prod_like_client.put("/workspaces/settings", json=payload, headers=auth_headers)
    _assert_honest_422(resp, "fullName")


def test_nul_byte_in_target_role_returns_422_not_500(client, auth_headers):
    prod_like_client = TestClient(client.app, raise_server_exceptions=False)
    payload = _settings_payload(targetRole=_nul_value_for("targetRole"))
    resp = prod_like_client.put("/workspaces/settings", json=payload, headers=auth_headers)
    _assert_honest_422(resp, "targetRole")


def test_nul_byte_in_location_returns_422_not_500(client, auth_headers):
    prod_like_client = TestClient(client.app, raise_server_exceptions=False)
    payload = _settings_payload(location=_nul_value_for("location"))
    resp = prod_like_client.put("/workspaces/settings", json=payload, headers=auth_headers)
    _assert_honest_422(resp, "location")


def test_nul_byte_in_email_returns_422_regression_guard(client, auth_headers):
    """Expected to ALREADY pass -- see module docstring. Kept in the same
    file (not skipped) so the full profile-field contract from the finding
    is asserted in one place; the evidence file documents this id's PASS
    explicitly and explains why it is not itself a reproduction of the
    defect."""
    prod_like_client = TestClient(client.app, raise_server_exceptions=False)
    payload = _settings_payload(email=_nul_value_for("email"))
    resp = prod_like_client.put("/workspaces/settings", json=payload, headers=auth_headers)
    _assert_honest_422(resp, "email")
