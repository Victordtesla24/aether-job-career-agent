"""F-01 — the deployment-wide provider-credential store must be OPERATOR-only.

FINDING (docs/delivery/PROD-UAT-2026-08-03.md F-01, evidence
``uat/reports/evidence/prod-uat-2026-08-03/s4-credential-scope.json``): every
``/agents/providers/...`` endpoint that reads or writes the DEPLOYMENT-WIDE
``ProviderCredential`` store took a plain ``CurrentUser`` and never consulted
``isAdmin``. ``current_user`` was used solely to build the response object — it
was read but it never authorized. Because ``ProviderCredentialRepository`` takes
no user id, ANY authenticated customer could read the operator's provider rows
(status, last-4 ``secretHint``, ``lastVerifiedAt``), overwrite them, delete
them, or burn the operator's money through the real ``verify`` round-trip.

The qa-adversary's live probe showed a non-admin ``DELETE`` of an unknown
provider returning **404** (the provider-name check ran first) rather than
401/403 — proof that no authorization gate was reached at all.

These tests assert the fixed contract:

1. Every deployment-wide endpoint answers **403** (``"Admin privileges
   required"`` — the SAME gate ``/api/admin/*`` already uses via
   ``app.middleware.auth.get_admin_user``) for an ordinary authenticated user.
2. Authorization is decided BEFORE the provider-name validation, so an ungated
   caller can never probe which provider ids are configured by reading a 404
   instead of a 403.
3. An admin (the operator) retains full function on every one of them.
4. The genuinely PER-USER store (``/agents/user/providers/...``) stays reachable
   by ordinary customers — that is the correct surface for a customer's own key.
5. The per-user surface never carries any deployment-wide credential material.
6. An anonymous caller still gets 401 (authentication precedes authorization).

Test-authorship only — no fix is implemented in this file.
"""
from __future__ import annotations

import uuid

import pytest

from app.db import get_connection
from app.repositories.provider_credential import ProviderCredentialRepository
from app.services import credential_vault as vault

#: Every endpoint that reads or mutates the DEPLOYMENT-WIDE credential store,
#: as ``(method, path, json_body)``. Enumerated from the router, not from the
#: finding text: the three Anthropic OAuth routes belong to this family too —
#: ``anthropic_oauth.persist_tokens`` writes the SAME deployment-wide
#: ``ProviderCredential('anthropic')`` row the manual paste writes.
DEPLOYMENT_WIDE_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/agents/providers", None),
    (
        "PUT",
        "/agents/providers/openrouter/credential",
        {"authMode": "api_key", "secret": "sk-or-attacker-value"},
    ),
    ("DELETE", "/agents/providers/openrouter/credential", None),
    ("POST", "/agents/providers/openrouter/verify", None),
    ("POST", "/agents/providers/anthropic/oauth/start", None),
    ("POST", "/agents/providers/anthropic/oauth/exchange", {"pastedCode": "code#state"}),
    ("POST", "/agents/providers/anthropic/oauth/refresh", None),
]

#: The same family addressed with a provider id that does not exist. Before the
#: fix these answered 404 (name check first); after it they must answer 403 so
#: nothing about the configured provider set leaks to an ungated caller.
UNKNOWN_PROVIDER_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    (
        "PUT",
        "/agents/providers/not-a-real-provider/credential",
        {"authMode": "api_key", "secret": "x"},
    ),
    ("DELETE", "/agents/providers/not-a-real-provider/credential", None),
    ("POST", "/agents/providers/not-a-real-provider/verify", None),
]


# --------------------------------------------------------------------------- #
# Fixtures / helpers
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
    """``ProviderCredential`` has no FK to ``User``, so conftest never truncates
    it. Delete only the rows this module touches (never DROP the table — the
    ``aether_test`` schema is shared with other concurrently-running suites).
    """
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
    """Register + login an ordinary user; return (auth headers, user id)."""
    creds = {"email": email, "password": "Passw0rd1"}
    r = client.post("/auth/register", json=creds)
    assert r.status_code in (201, 409), r.text
    login = client.post("/auth/login", json=creds)
    assert login.status_code == 200, login.text
    body = login.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["userId"]


def _promote(user_id: str) -> None:
    """Grant ``isAdmin``. The JWT carries no privilege claim — ``get_current_user``
    re-reads the row per request — so an already-issued token acts as admin."""
    from app.repositories.admin import _ensure_admin_schema

    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (user_id,))
        conn.commit()


@pytest.fixture()
def customer(client) -> dict[str, str]:
    """An ordinary paying customer — authenticated, NOT an admin."""
    headers, _uid = _register(client, f"f01-customer-{uuid.uuid4().hex[:8]}@example.com")
    return headers


@pytest.fixture()
def operator(client) -> dict[str, str]:
    """The deployment operator — authenticated AND ``isAdmin``."""
    headers, uid = _register(client, f"f01-operator-{uuid.uuid4().hex[:8]}@example.com")
    _promote(uid)
    return headers


def _call(client, method: str, path: str, body: dict | None, headers):
    if method == "GET":
        return client.get(path, headers=headers)
    if method == "DELETE":
        return client.delete(path, headers=headers)
    if method == "PUT":
        return client.put(path, json=body, headers=headers)
    return client.post(path, json=body, headers=headers) if body else client.post(
        path, headers=headers
    )


# --------------------------------------------------------------------------- #
# 1. Every deployment-wide endpoint is 403 for an ordinary customer
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("method", "path", "body"), DEPLOYMENT_WIDE_ENDPOINTS)
def test_non_admin_gets_403_from_deployment_wide_provider_endpoint(
    client, customer, method, path, body, _clean_provider_credentials
):
    res = _call(client, method, path, body, customer)
    assert res.status_code == 403, (
        f"{method} {path} returned {res.status_code}, not 403 — an ordinary "
        f"customer reached the operator's deployment-wide credential store. "
        f"Body: {res.text[:400]}"
    )
    assert res.json()["detail"] == "Admin privileges required", res.text


def test_non_admin_cannot_read_operator_secret_hint(
    client, customer, operator, monkeypatch, _clean_provider_credentials
):
    """The list endpoint leaked the operator's last-4 hint, source and verify
    timestamps to every signed-in user. Store a distinctive deployment secret,
    then prove a customer cannot see any of it."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    ProviderCredentialRepository().upsert(
        "openrouter", auth_mode="api_key", secret="sk-or-OPERATORONLY7391", base_url=None
    )
    # The operator can see their own credential's hint...
    admin_view = client.get("/agents/providers", headers=operator)
    assert admin_view.status_code == 200, admin_view.text
    openrouter = next(p for p in admin_view.json() if p["id"] == "openrouter")
    assert openrouter["secretHint"] == "…7391"

    # ...the customer gets nothing at all.
    res = client.get("/agents/providers", headers=customer)
    assert res.status_code == 403, res.text
    assert "7391" not in res.text


# --------------------------------------------------------------------------- #
# 2. Authorization is decided BEFORE the provider-name validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("method", "path", "body"), UNKNOWN_PROVIDER_ENDPOINTS)
def test_authz_precedes_provider_name_validation(
    client, customer, method, path, body, _clean_provider_credentials
):
    """qa-adversary's live probe: a non-admin DELETE of an unknown provider
    returned 404, not 403 — the name check ran first, so the response told the
    caller which provider ids exist. The gate must run first."""
    res = _call(client, method, path, body, customer)
    assert res.status_code == 403, (
        f"{method} {path} returned {res.status_code}; a 404 here would confirm "
        "the provider-name check runs before authorization."
    )


# --------------------------------------------------------------------------- #
# 3. The operator keeps full function
# --------------------------------------------------------------------------- #


def test_admin_retains_full_deployment_credential_function(
    client, operator, monkeypatch, _clean_provider_credentials
):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    listing = client.get("/agents/providers", headers=operator)
    assert listing.status_code == 200, listing.text
    assert {p["id"] for p in listing.json()} >= {"anthropic", "openrouter"}

    saved = client.put(
        "/agents/providers/openrouter/credential",
        json={"authMode": "api_key", "secret": "sk-or-operator-value4242"},
        headers=operator,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["source"] == "database"
    assert saved.json()["secretHint"] == "…4242"

    removed = client.delete(
        "/agents/providers/openrouter/credential", headers=operator
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["source"] == "none"


def test_admin_verify_round_trip_still_reachable(
    client, operator, monkeypatch, _clean_provider_credentials
):
    """No credential for gemini -> an honest not-ok (no network), 200 not 403."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    res = client.post("/agents/providers/gemini/verify", headers=operator)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is False


def test_admin_unknown_provider_still_404(client, operator, _clean_provider_credentials):
    """Gating must not swallow the honest 404 the operator should still see."""
    res = client.delete(
        "/agents/providers/not-a-real-provider/credential", headers=operator
    )
    assert res.status_code == 404, res.text


# --------------------------------------------------------------------------- #
# 4. The PER-USER store stays reachable by ordinary customers
# --------------------------------------------------------------------------- #


def test_non_admin_per_user_credential_store_still_works(client, customer):
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

    removed = client.delete(
        "/agents/user/providers/openrouter/credential", headers=customer
    )
    assert removed.status_code == 200, removed.text
    assert client.get("/agents/user/providers", headers=customer).json() == []


def test_non_admin_keeps_the_live_model_catalog_and_own_default_model(client, customer):
    """The customer-facing model-choice surfaces are per-user and must NOT be
    gated: the per-agent picker's catalog read, and the per-user
    ``AgentProvider`` default-model write the ModelPicker performs."""
    saved = client.put(
        "/agents/providers/openrouter",
        json={"model": "vendor/customer-pick"},
        headers=customer,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["model"] == "vendor/customer-pick"


# --------------------------------------------------------------------------- #
# 5. The per-user surface carries NO deployment-wide credential material
# --------------------------------------------------------------------------- #


def test_user_provider_catalog_is_per_user_only(
    client, customer, monkeypatch, _clean_provider_credentials
):
    """The panel a non-admin is shown must be built from THEIR OWN credential
    store — never the operator's. Seed a distinctive deployment credential and
    an env key, then prove neither shows up."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-operator-8888")
    ProviderCredentialRepository().upsert(
        "openrouter", auth_mode="api_key", secret="sk-or-OPERATORONLY7391", base_url=None
    )

    res = client.get("/agents/user/providers/catalog", headers=customer)
    assert res.status_code == 200, res.text
    body = res.json()
    ids = [p["id"] for p in body]
    assert "openrouter" in ids
    # Not one byte of the operator's credential state.
    assert "7391" not in res.text
    assert "8888" not in res.text
    openrouter = next(p for p in body if p["id"] == "openrouter")
    assert openrouter["source"] == "none"
    assert openrouter["status"] == "unconfigured"
    assert openrouter["secretHint"] is None

    # Once the CUSTOMER stores their own key, their own panel reflects it.
    client.put(
        "/agents/user/providers/openrouter/credential",
        json={"authMode": "api_key", "secret": "sk-or-customer-own-key5150"},
        headers=customer,
    )
    after = client.get("/agents/user/providers/catalog", headers=customer)
    assert after.status_code == 200, after.text
    mine = next(p for p in after.json() if p["id"] == "openrouter")
    assert mine["source"] == "database"
    assert mine["secretHint"] == "…5150"
    assert "7391" not in after.text


# --------------------------------------------------------------------------- #
# 6. Authentication still precedes authorization
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("method", "path", "body"), DEPLOYMENT_WIDE_ENDPOINTS)
def test_anonymous_caller_still_gets_401_not_403(client, method, path, body):
    res = _call(client, method, path, body, None)
    assert res.status_code == 401, res.text
