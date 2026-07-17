"""GAP-P7-DEF-B-PERSIST: PUT /workspaces/settings returns 200 but never
persists ``profile.email`` — the UPDATE in
``app.routers.workspaces.update_settings`` (workspaces.py ~853-882) sets
``name``, ``"targetRole"``, ``"location"`` and ``"agentConfig"`` but omits
``email`` from its ``SET`` clause entirely, so any email change is silently
discarded even though the endpoint reports success.

[VERIFIED-WITH-SOURCE] Found by STEP-10 production QA (evidence
uat/reports/evidence/phase7/journey-j2-settings-save-200.json +
step10-cluster2-gates.json): saving ``someone@example.com`` returned 200 but
the DB row stayed ``admin@aether.local``. Confirmed directly against
apps/api/app/routers/workspaces.py:854-882 in this worktree (commit
01852ab / main): the ``SettingsUpdate`` -> ``SettingsProfile`` model carries
four fields (``fullName``, ``email``, ``targetRole``, ``location``); the
``UPDATE "User" SET ...`` clause only assigns ``name``, ``"targetRole"``,
``"location"`` and ``"agentConfig"`` — ``email`` is the ONLY
``SettingsProfile`` field missing from the ``SET`` list. Pre-existing bug,
newly exposed now that GAP-P7-DEF-B's allowlist validator lets
``admin@aether.local`` (and other allow-listed-domain addresses) reach this
handler at all.

Scope finding: no separate email-change/verification flow exists anywhere
in the codebase (grepped apps/api/app/routers, apps/api/app/services,
apps/api/app/repositories and apps/web/src for
email-change/verify-email/changeEmail/EmailVerif -- the only hit,
``admin.py``'s ``emailVerificationEnabled``, is an admin-configured toggle
that gates whether *self-registration* requires verification, not a
per-user email-change flow for already-registered accounts). So there is no
design reason for this endpoint to silently drop email; it must persist it
like every other ``SettingsProfile`` field.
"""
from __future__ import annotations


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


def test_settings_save_persists_new_email_and_name(
    client, auth_headers, test_user_id, db_session
):
    """Target behaviour: PUT with a new external email + a changed display
    name must actually write both to the ``User`` row, not just return 200."""
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("new.address@example.com", full_name="Changed Name"),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    # Query the repo directly -- the ground truth, independent of what the
    # handler's own response claims.
    with db_session.cursor() as cur:
        cur.execute('SELECT email, name FROM "User" WHERE id = %s', (test_user_id,))
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "new.address@example.com", (
        f"email was not persisted -- DB still has {row[0]!r}"
    )
    assert row[1] == "Changed Name", f"name was not persisted -- DB still has {row[1]!r}"

    # And the round-trip GET must reflect the same persisted values -- this
    # is the user-facing surface that actually proves the fix end-to-end.
    get_resp = client.get("/workspaces/settings", headers=auth_headers)
    assert get_resp.status_code == 200, get_resp.text
    body = get_resp.json()
    assert body["profile"]["email"] == "new.address@example.com"
    assert body["profile"]["fullName"] == "Changed Name"


def test_settings_save_persists_allowlisted_internal_email(
    client, auth_headers, test_user_id, db_session
):
    """The allow-listed internal domain (GAP-P7-DEF-B) must not just be
    *accepted* by validation -- it must actually be *persisted*, same as any
    other valid email."""
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("admin@aether.local"),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    with db_session.cursor() as cur:
        cur.execute('SELECT email FROM "User" WHERE id = %s', (test_user_id,))
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "admin@aether.local", (
        f"allow-listed email was not persisted -- DB still has {row[0]!r}"
    )

    get_resp = client.get("/workspaces/settings", headers=auth_headers)
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["profile"]["email"] == "admin@aether.local"
