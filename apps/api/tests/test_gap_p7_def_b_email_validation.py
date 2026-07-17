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

ORIGINAL fix (§15.2 operator brief / ADR-P7-02, Option 3 — as first
implemented, commit 58dd77e): at app startup, read
``AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS`` (default ``"aether.local"``) and
discard the corresponding entry/entries from
``email_validator.SPECIAL_USE_DOMAIN_NAMES``. An adversarial review
(uat/reports/evidence/phase7/review-def-b.json, cycle 1, verdict FAIL)
empirically proved this OPENED EVERY ``*.local`` ADDRESS —
``attacker@evil.local``, ``foo.local``, ``x@random-internal-host.local`` all
validated, not just ``admin@aether.local`` — because
``SPECIAL_USE_DOMAIN_NAMES`` only ever holds bare TLD-like labels (e.g.
``"local"``), so "discarding" one is inherently a wholesale, process-wide
opening — exactly the "globally-scoped" Option 1 behaviour §15.1 explicitly
rejected. fable-5 overrode §15.2's sample pseudocode as flawed.

REVISED fix (cycle 2, this commit): ``app.main.apply_email_domain_allowlist()``
is now a pure, side-effect-free loader — it no longer touches
``email_validator`` global state at all. It reads
``AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS`` fresh from ``os.environ`` on every
call (default ``{"aether.local"}``) and returns it as a ``frozenset``. The
actual accept/reject decision moved to a custom Pydantic validator
(``app.routers.workspaces._validate_settings_email``, wired via
``Annotated[str, AfterValidator(...)]``) applied ONLY to
``SettingsProfile.email`` — the gap's named surface
(``/dashboard/settings`` + ``PUT /api/workspaces/settings``).
``RegisterRequest.email`` (apps/api/app/routers/auth.py) stays strict
``EmailStr`` — the reviewer flagged the register-surface reach of the prior
global-mutation approach as blocking. The validator requires an EXACT,
case-insensitive domain match against the allowlist (never a suffix/TLD
match), so ``evil.local`` stays rejected while ``aether.local`` is accepted.
No DB migration; no change to what update_settings() persists.

FAIL-BEFORE STATUS (recorded 2026-07-17, pre-ANY-fix; see
uat/reports/evidence/phase7/gap-def-b-tdd-fail.txt for the actual pytest
run against commit 9987fdf, before 58dd77e or this cycle-2 commit existed):
  - test_settings_save_aether_local_returns_200            -> FAILED (422 then)
  - test_settings_save_valid_external_email_returns_200     -> PASSED already (unaffected by the gap; kept as a regression guard)
  - test_settings_save_garbage_email_returns_422             -> PASSED already (garbage fails a syntax check unrelated to SPECIAL_USE_DOMAIN_NAMES)
  - test_settings_save_localhost_still_rejected               -> PASSED already ("no period" check fires before special-use check either way)
  - test_other_special_use_domains_still_rejected              -> PASSED already (only "aether.local" is allow-listed; "foo.test" stays rejected)
  - test_allowed_domains_configurable_via_env                   -> FAILED (apply_email_domain_allowlist did not exist yet -> ImportError)
  - test_email_not_changed_unrelated_field_save_succeeds          -> FAILED (422, same root cause as the base case)

``test_allowed_domains_configurable_via_env`` is REWRITTEN in this cycle-2
commit to exercise the new exact-domain mechanism through the live endpoint
(the OLD version poked ``email_validator.SPECIAL_USE_DOMAIN_NAMES``
directly via a raw ``EmailStr`` probe model — that internal, now-overridden
mechanism no longer exists to poke). Its behavioural GOAL is unchanged and,
if anything, stronger: prove the allowlist is env-driven (not hardcoded),
that ``apply_email_domain_allowlist()`` is re-callable and reads the env
fresh, AND that the env var fully replaces the default (not additive) — via
the actual ``PUT /workspaces/settings`` endpoint rather than a bypassed
internal probe. Every other test's assertions are BYTE-FOR-BYTE unchanged
from the original TDD commit (9987fdf) — they exercise the real endpoint
and never depended on which internal mechanism satisfies them. A new guard
test, ``test_settings_save_nonconfigured_local_subdomain_rejected``, pins
the cycle-1 review finding closed.
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


def test_allowed_domains_configurable_via_env(monkeypatch, client, auth_headers):
    """§15.2 target (REVISED cycle 2): the exact-domain allowlist is
    env-driven, not hardcoded to "aether.local" — ``apply_email_domain_allowlist()``
    re-reads ``AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS`` fresh on every call
    (no caching), so reconfiguring the env var and calling it again allows a
    DIFFERENT domain immediately, through the live endpoint.

    Uses "example.onion" (a ``.onion`` special-use address, unrelated to the
    default "aether.local") as the probe — it is rejected by BOTH the
    default allowlist AND the standard special-use-domain check, so a flip
    to 200 after reconfiguration can only be explained by the env change
    actually taking effect. No global state is touched (unlike the
    overridden cycle-1 approach), so there is nothing to snapshot/restore —
    ``monkeypatch.setenv`` reverts itself automatically at test teardown.
    """
    # Baseline: with the default config (only "aether.local" allow-listed),
    # a different reserved-use domain is rejected.
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("node@example.onion"),
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text

    monkeypatch.setenv("AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS", "example.onion")

    from app.main import apply_email_domain_allowlist

    # Re-callable: reflects the just-changed env immediately, no caching.
    reloaded = apply_email_domain_allowlist()
    assert reloaded == frozenset({"example.onion"}), reloaded

    # Now allow-listed: the SAME endpoint, the SAME validator, accepts it.
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("node@example.onion"),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    # The env var REPLACES the default set, it is not additive — the
    # previously-default "aether.local" is no longer allow-listed. Proves
    # this reads the env fresh rather than merging with a hardcoded
    # fallback.
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("admin@aether.local"),
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


def test_settings_save_nonconfigured_local_subdomain_rejected(client, auth_headers):
    """Regression guard for review-def-b.json cycle-1 FAIL: a DIFFERENT
    domain that merely shares the allow-listed domain's reserved TLD/label
    must stay rejected — proves the allowlist is an EXACT domain match, not
    a wholesale opening of every ".local" address. Adversarial review
    empirically proved a prior implementation accepted
    ``attacker@evil.local`` (and ``foo.local``, and
    ``x@random-internal-host.local``) once "local" was discarded from
    ``email_validator.SPECIAL_USE_DOMAIN_NAMES``; this test pins that
    regression closed."""
    resp = client.put(
        "/workspaces/settings",
        json=_settings_payload("attacker@evil.local"),
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


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
