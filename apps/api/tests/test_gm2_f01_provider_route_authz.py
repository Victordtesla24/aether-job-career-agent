"""GOLD-MASTER-V2 F-01 (§15 STEP 2) — deployment-wide provider-credential
routes must be OPERATOR-only.

Orchestrator finding (2026-08-04T02:1xZ "first-hand code probe"):
``apps/api/app/routers/agents.py`` gated the deployment-wide
``/agents/providers/*`` family inconsistently — some routes took ``AdminUser``,
others took a plain ``CurrentUser`` and never checked ``isAdmin``. Because
``ProviderCredentialRepository`` carries no user id, an ungated route let ANY
authenticated customer read/overwrite/delete the OPERATOR's shared LLM
credential — the one every agent run on the deployment bills against.

SUPERSEDED-BY-EVENTS NOTICE (test-author, same session): by the time this
file was authored the working tree already had ~24 uncommitted files from a
concurrent session (this task's own SHARED TREE HAZARD warning). That
concurrent work landed as commit ``eb03989`` ("fix(F-01): require admin for
deployment-wide provider-credential routes") WHILE this file was being
authored, followed by an explicit orchestrator ruling in commit ``5b6711d``
(``docs/delivery/ADR-F01-PROVIDER-CREDENTIAL-AUTHZ.md`` "ORCHESTRATOR
RULINGS — 2026-08-04T03:05Z") that named this exact file and its
``test_non_admin_put_providers_status_model_gets_403`` test and ruled:

    "Ruling 1 — PUT /agents/providers/{provider}: OPTION A. Keep
    CurrentUser. Do NOT gate it. ... This route is therefore already
    correctly per-user. Gating it would 403 every customer's model-picker
    save ... Action: delete or correct
    test_gm2_f01_provider_route_authz.py::test_non_admin_put_providers_status_model_gets_403."

That ruling reaches the SAME conclusion this file's own first draft had
independently flagged as a concern before the ruling existed (see git
history / TESTS-FAIL-BEFORE.md §3 for the original flag). Per that explicit
instruction the test below has been CORRECTED (inverted + renamed), not
deleted, so it stands as a permanent regression pin for the ruling rather
than silently vanishing.

Current on-disk (and now committed, HEAD) state of the family:

  * ``GET  /providers``                       -> AdminUser  (F-01 fix)
  * ``PUT  /providers/{provider}/credential``  -> AdminUser  (F-01 fix)
  * ``DELETE /providers/{provider}/credential``-> AdminUser  (F-01 fix)
  * ``POST /providers/{provider}/verify``      -> AdminUser  (F-01 fix)
  * ``PUT  /providers/{provider}``             -> CurrentUser (DELIBERATE —
    per-user ``AgentProvider`` row, Ruling 1 above; NOT part of F-01)

F-01 is CLOSED (``docs/delivery/GOLD-MASTER-V2-STATE.json``, commit
``765f954``) and deployed (ruling doc's "Deploy record", API restarted
2026-08-04T02:58Z, verified live). This file is therefore no longer a
"fails before fix, passes after" suite — the fix already shipped — it is a
regression-pin suite that PINS the fix (and Ruling 1's deliberate
non-fix) so a future change cannot silently reopen either. The original
fail-before run (1 failed, 8 passed, captured before this correction) is
preserved verbatim in TESTS-FAIL-BEFORE.md as historical evidence; the
corrected, fully-green re-run is recorded alongside it.

Test-authorship only — no fix is implemented in this file.
"""
from __future__ import annotations

import uuid

import pytest

from app.db import get_connection
from app.repositories.provider_credential import ProviderCredentialRepository
from app.repositories.user_provider_credential import UserProviderCredentialRepository
from app.services import credential_vault as vault


# --------------------------------------------------------------------------- #
# Fixtures / helpers (mirrors the conventions already used by sibling F-01
# suites in this repo — auth_headers-style register+login, isolate the vault
# key + the repo-root .env sync target, wipe only the rows this file touches).
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch, tmp_path):
    """A credential save must NEVER touch the real repo-root ``.env`` during
    tests — point the oauth_token sync target at a per-test tmp file."""
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(tmp_path / "default.env"))


@pytest.fixture()
def _clean_provider_credentials():
    """``ProviderCredential`` has no FK to ``User``, so conftest's blanket
    truncation never touches it. Wipe only the rows this module writes (never
    DROP the table — ``aether_test`` is shared with other concurrent runs)."""

    def _wipe() -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_name = 'ProviderCredential'"
                    " AND table_schema = ANY(current_schemas(false))"
                )
                row = cur.fetchone()
                if row and row[0] == 1:
                    cur.execute(
                        'DELETE FROM "ProviderCredential" WHERE "provider" = ANY(%s)',
                        (["openrouter", "anthropic", "gemini"],),
                    )
            conn.commit()

    _wipe()
    yield
    _wipe()


def _register(client, email: str) -> tuple[dict[str, str], str]:
    creds = {"email": email, "password": "Passw0rd1"}
    r = client.post("/auth/register", json=creds)
    assert r.status_code in (201, 409), r.text
    login = client.post("/auth/login", json=creds)
    assert login.status_code == 200, login.text
    body = login.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["userId"]


def _promote(user_id: str) -> None:
    """Grant ``isAdmin``. ``get_current_user`` re-reads the row per request, so
    promoting after token issuance still takes effect on the next call."""
    from app.repositories.admin import _ensure_admin_schema

    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (user_id,))
        conn.commit()


@pytest.fixture()
def customer(client) -> dict[str, str]:
    """An ordinary paying customer — authenticated, NOT an admin."""
    headers, _uid = _register(client, f"gm2f01-cust-{uuid.uuid4().hex[:8]}@example.com")
    return headers


@pytest.fixture()
def operator(client) -> dict[str, str]:
    """The deployment operator — authenticated AND ``isAdmin``."""
    headers, uid = _register(client, f"gm2f01-op-{uuid.uuid4().hex[:8]}@example.com")
    _promote(uid)
    return headers


# =========================================================================== #
# 1. Non-admin MUST get 403 on the three routes named by the orchestrator
# =========================================================================== #


def test_non_admin_put_providers_status_model_intentionally_stays_ungated(client, customer):
    """PUT /agents/providers/{provider} (connect/disconnect/switch-model) —
    CORRECTED per orchestrator Ruling 1 (5b6711d,
    ADR-F01-PROVIDER-CREDENTIAL-AUTHZ.md "ORCHESTRATOR RULINGS —
    2026-08-04T03:05Z"), which named this test by its original name
    (``test_non_admin_put_providers_status_model_gets_403``, then asserting
    403) and ruled: "Keep CurrentUser. Do NOT gate it. ... Gating it would
    403 every customer's model-picker save ... Action: delete or correct."

    This is now a REGRESSION PIN, not a fail-before test: a non-admin
    customer MUST continue to reach this route with 200, because it writes
    only their OWN ``AgentProvider`` row (PK ``("userId","provider")``),
    never the deployment-wide ``ProviderCredential`` store F-01 protects,
    and is the sole write path behind the live ``ModelPicker`` UI every
    signed-in customer uses on ``/dashboard/agents``. Matches the sibling
    ``test_f01_provider_credential_authz.py::
    test_non_admin_keeps_the_live_model_catalog_and_own_default_model``
    pin, which is why the two files no longer contradict each other.
    """
    res = client.put(
        "/agents/providers/openrouter",
        json={"model": "vendor/customer-pick"},
        headers=customer,
    )
    assert res.status_code == 200, (
        f"PUT /agents/providers/openrouter returned {res.status_code}, not "
        f"200 — a non-admin customer could no longer save their own "
        f"model-picker preference. Body: {res.text[:400]}"
    )
    assert res.json()["model"] == "vendor/customer-pick", res.text


def test_non_admin_delete_provider_credential_gets_403(client, customer, _clean_provider_credentials):
    """DELETE /agents/providers/{provider}/credential — REGRESSION PIN.

    The orchestrator's finding table lists this as CurrentUser (broken); the
    on-disk code as of this test-authoring session already reads AdminUser
    (see agents.py:3736's docstring — 'AdminUser now resolves first, so the
    answer is 403'), so this assertion currently PASSES. Kept as a
    regression pin per task item 5's explicit license ('if it already
    passes, keep it as a regression pin and say so') — recorded honestly
    rather than manufactured as a fake-red test.
    """
    res = client.delete("/agents/providers/openrouter/credential", headers=customer)
    assert res.status_code == 403, (
        f"DELETE /agents/providers/openrouter/credential returned "
        f"{res.status_code}, not 403. Body: {res.text[:400]}"
    )
    assert res.json()["detail"] == "Admin privileges required", res.text


def test_non_admin_verify_provider_gets_403(client, customer, _clean_provider_credentials):
    """POST /agents/providers/{provider}/verify — REGRESSION PIN.

    Same discrepancy as the DELETE case above: current on-disk code already
    reads AdminUser here, so this currently PASSES. Recorded as a regression
    pin rather than forced red.
    """
    res = client.post("/agents/providers/openrouter/verify", headers=customer)
    assert res.status_code == 403, (
        f"POST /agents/providers/openrouter/verify returned {res.status_code}, "
        f"not 403. Body: {res.text[:400]}"
    )
    assert res.json()["detail"] == "Admin privileges required", res.text


# =========================================================================== #
# 2. The destructive consequence, not just the status code
# =========================================================================== #


def test_non_admin_delete_attempt_does_not_remove_the_credential(
    client, customer, _clean_provider_credentials
):
    """A status-code-only test would still pass against a fix that deletes
    the row and THEN returns 403 (or against a handler ordering bug where
    the delete happens before the dependency resolves). Seed a real
    deployment-wide credential directly via the repository (the write path
    itself is admin-gated, so we can't use the API to seed it in a
    non-admin test), attempt the DELETE as a non-admin, and assert the row
    is provably still present and unchanged afterwards.
    """
    repo = ProviderCredentialRepository()
    repo.upsert(
        "openrouter", auth_mode="api_key", secret="sk-or-OPERATORCRED9999", base_url=None
    )
    before = repo.get_masked("openrouter")
    assert before is not None and before["secretHint"] == "…9999"

    res = client.delete("/agents/providers/openrouter/credential", headers=customer)
    assert res.status_code == 403, res.text

    after = repo.get_masked("openrouter")
    assert after is not None, (
        "the operator's deployment-wide credential was REMOVED by a "
        "non-admin's DELETE call, even though the response was 403 — the "
        "destructive side effect happened before/despite the auth gate."
    )
    assert after["secretHint"] == "…9999", (
        f"credential row was mutated by a rejected non-admin call: {after}"
    )


# =========================================================================== #
# 3. Regression pins: the operator keeps full function on all three routes
# =========================================================================== #


def test_admin_retains_full_function_on_all_three_routes(
    client, operator, monkeypatch, _clean_provider_credentials
):
    """After the fix, ``PUT /providers/{provider}``, ``DELETE
    .../credential`` and ``POST .../verify`` must all still work for an
    admin. This is ALREADY true today for the two credential routes
    (already AdminUser); ``PUT /providers/{provider}`` passes today too
    because it currently accepts any ``CurrentUser`` (which an admin
    satisfies) — so this whole test is green now AND must stay green once
    PUT is correctly gated, since ``AdminUser`` is ``CurrentUser`` + an
    ``isAdmin`` check, never a narrower set of callers.
    """
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    put_status = client.put(
        "/agents/providers/openrouter",
        json={"model": "vendor/operator-pick"},
        headers=operator,
    )
    assert put_status.status_code == 200, put_status.text
    assert put_status.json()["model"] == "vendor/operator-pick"

    saved = client.put(
        "/agents/providers/openrouter/credential",
        json={"authMode": "api_key", "secret": "sk-or-operator-value4242"},
        headers=operator,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["secretHint"] == "…4242"

    verified = client.post("/agents/providers/openrouter/verify", headers=operator)
    assert verified.status_code == 200, verified.text

    removed = client.delete("/agents/providers/openrouter/credential", headers=operator)
    assert removed.status_code == 200, removed.text
    assert ProviderCredentialRepository().get_masked("openrouter") is None


# =========================================================================== #
# 4. Regression pin: /user/providers/* stays reachable by ordinary customers
# =========================================================================== #


def test_non_admin_user_providers_full_crud_still_works(client, customer):
    """The genuinely per-user store must NOT be collaterally gated by an F-01
    fix. Exercises list/put/list/verify/delete on the customer's OWN key."""
    listing = client.get("/agents/user/providers", headers=customer)
    assert listing.status_code == 200, listing.text
    assert listing.json() == []

    saved = client.put(
        "/agents/user/providers/openrouter/credential",
        json={"authMode": "api_key", "secret": "sk-or-customer-own-key1234"},
        headers=customer,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["secretHint"] == "…1234"

    after = client.get("/agents/user/providers", headers=customer)
    assert after.status_code == 200, after.text
    assert [r["provider"] for r in after.json()] == ["openrouter"]

    verify = client.post("/agents/user/providers/openrouter/verify", headers=customer)
    assert verify.status_code == 200, verify.text

    removed = client.delete("/agents/user/providers/openrouter/credential", headers=customer)
    assert removed.status_code == 200, removed.text
    assert client.get("/agents/user/providers", headers=customer).json() == []


# =========================================================================== #
# 5. YOUR RULING — GET .../models and POST .../models/refresh stay CurrentUser
# =========================================================================== #


def test_ruling_non_admin_can_still_read_the_live_model_catalog(client, customer):
    """RULING (test-author, this session): ``GET /providers/{provider}/models``
    should NOT be admin-gated.

    Reasoning:
      1. The response carries no credential material — only model
         id/name/pricing/context-length/tier, i.e. public catalog metadata.
      2. Its own docstring (agents.py:3783-3791) says it "Uses the signed-in
         user's OWN provider key when configured, else the deployment key" —
         it is explicitly designed to be called by ordinary signed-in users,
         not just operators.
      3. It is the live data source behind ``ModelPicker`` /
         ``AgentModelPicker`` (apps/web/src/components/agents/ModelPicker.tsx,
         AgentModelPicker.tsx) rendered on the everyday ``/dashboard/agents``
         page for every customer — admin-gating it would break the core
         "pick a model by budget" feature (GAP-P7-MODEL-CHOICE-001) for
         every non-admin user, with no security benefit (nothing secret is
         returned).
    Using the STATIC anthropic catalog (not openrouter) so this assertion
    needs no network mock and can't be confused with a live-fetch flake.
    Orchestrator: overturn by deleting/inverting this test if you disagree.
    """
    res = client.get("/agents/providers/anthropic/models", headers=customer)
    assert res.status_code == 200, (
        f"expected a non-admin customer to read the model catalog (200), got "
        f"{res.status_code}: {res.text[:300]}"
    )
    assert res.json()["provider"] == "anthropic"


def test_ruling_non_admin_can_still_force_refresh_the_model_catalog(
    client, customer, monkeypatch
):
    """RULING companion to the test above: ``POST
    /providers/{provider}/models/refresh`` should also stay ``CurrentUser``
    for the same reasons — it is the manual-refresh button behind the same
    customer-facing picker, not a deployment-credential mutation. Uses the
    static anthropic catalog so no network mock is required (the refresh
    endpoint for a provider without a live catalog still returns 200 with
    the static list, matching the GET behaviour)."""
    res = client.post("/agents/providers/anthropic/models/refresh", headers=customer)
    assert res.status_code == 200, (
        f"expected a non-admin customer to force-refresh the model catalog "
        f"(200), got {res.status_code}: {res.text[:300]}"
    )
    assert res.json()["provider"] == "anthropic"


# =========================================================================== #
# 6. Cross-tenant pin: user A's /user/providers row is invisible/untouchable
#    to user B
# =========================================================================== #


def test_cross_tenant_user_a_credential_is_isolated_from_user_b(client):
    """user B must never be able to read, overwrite, or delete user A's
    ``/user/providers`` credential. Structurally this SHOULD already pass —
    every ``/user/providers/*`` route derives the target row exclusively
    from the caller's own JWT-resolved ``current_user['id']`` (there is no
    path-or-body user-id parameter an attacker could substitute) — but it is
    tested explicitly here rather than assumed, and kept as a regression pin
    (already passing) per task item 5's guidance."""
    a_headers, _a_id = _register(client, f"gm2f01-a-{uuid.uuid4().hex[:8]}@example.com")
    b_headers, b_id = _register(client, f"gm2f01-b-{uuid.uuid4().hex[:8]}@example.com")

    saved_a = client.put(
        "/agents/user/providers/openrouter/credential",
        json={"authMode": "api_key", "secret": "sk-or-user-A-secret0001"},
        headers=a_headers,
    )
    assert saved_a.status_code == 200, saved_a.text
    assert saved_a.json()["secretHint"] == "…0001"

    # B's own listing must be empty — A's row must not leak into it.
    b_listing = client.get("/agents/user/providers", headers=b_headers)
    assert b_listing.status_code == 200, b_listing.text
    assert b_listing.json() == [], "user B can see user A's provider row"
    assert "0001" not in b_listing.text

    # B writes their OWN row with a distinct secret — must not overwrite A's.
    saved_b = client.put(
        "/agents/user/providers/openrouter/credential",
        json={"authMode": "api_key", "secret": "sk-or-user-B-secret0002"},
        headers=b_headers,
    )
    assert saved_b.status_code == 200, saved_b.text
    assert saved_b.json()["secretHint"] == "…0002"

    a_listing_after = client.get("/agents/user/providers", headers=a_headers)
    assert a_listing_after.status_code == 200, a_listing_after.text
    assert a_listing_after.json()[0]["secretHint"] == "…0001", (
        "user A's stored credential changed after user B wrote their own row "
        f"— cross-tenant leak: {a_listing_after.json()}"
    )

    # B deletes their OWN row — A's must survive untouched.
    removed_b = client.delete(
        "/agents/user/providers/openrouter/credential", headers=b_headers
    )
    assert removed_b.status_code == 200, removed_b.text
    assert UserProviderCredentialRepository().get_masked(b_id, "openrouter") is None

    a_listing_final = client.get("/agents/user/providers", headers=a_headers)
    assert a_listing_final.status_code == 200, a_listing_final.text
    assert a_listing_final.json()[0]["secretHint"] == "…0001", (
        "user A's credential was deleted by user B's DELETE call — "
        f"cross-tenant destructive leak: {a_listing_final.json()}"
    )
