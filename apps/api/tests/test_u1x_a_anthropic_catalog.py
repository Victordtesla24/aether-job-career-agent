"""U1X-a CATALOG — failing tests for the Anthropic provider-card gap.

RCA (agents-uplift discovery, wf_b360c9f2-1a6, u1x-discovery scout
"anthropic-card"; full evidence at
uat/reports/evidence/agents-uplift/u1x-discovery/RCA-anthropic-no-models.md):
a working, credential-independent 3-model Anthropic catalog already exists
(``llm_client._STATIC_MODEL_CATALOG["anthropic"]``, served unconditionally by
``GET /agents/providers/anthropic/models``) but NOTHING wires it into the two
listing endpoints the provider CARDS actually render from:

  * ``PROVIDER_SEED["anthropic"]["models"]`` hardcodes ``[]`` (agents.py) —
    every other credentialed seed (openai/gemini/groq) carries a non-empty
    static list.
  * ``_build_provider_entry`` (agents.py) sets
    ``"models": env_models`` unconditionally — ``env_models`` comes from
    ``_provider_env_state``, which NEVER reads the DB-stored
    ``ProviderCredential`` row (only raw env vars), so a genuinely
    connected+verified DB credential (the prod deployment's real state —
    ``source=database``, ``authMode=oauth_token``, ``lastVerifyStatus=ok``)
    still renders ``models: []``.
  * ``_build_user_provider_entry`` (the per-user
    ``GET /agents/user/providers/catalog`` twin) reads ``seed["models"]``
    directly, so it inherits the SAME empty list regardless of whether the
    calling customer has their own verified anthropic credential.

PINNED CONTRACT for the fixer:
  * ``PROVIDER_SEED["anthropic"]["models"]`` becomes non-empty — the static
    catalog's ids (``["claude-opus-4-8", "claude-sonnet-4-6",
    "claude-haiku-4-5"]``), matching the wire shape every other seed already
    uses (``list[str]`` — ``ProviderSchema.models`` on the FE is
    ``z.array(z.string())``, unchanged).
  * ``GET /agents/providers`` (operator) and
    ``GET /agents/user/providers/catalog`` (customer) both populate
    anthropic's ``models`` with those ids WHENEVER a VERIFIED credential is
    resolvable for that scope (deployment-wide DB/env for the operator
    endpoint; the CALLING USER's own verified credential for the per-user
    endpoint — never the deployment's, per F-01/ADR-F01-PROVIDER-CREDENTIAL-
    AUTHZ isolation).
  * An UNCONFIGURED anthropic provider keeps the existing honest empty-list
    behaviour — a catalog must never be fabricated for a provider nobody can
    actually call (D-0020).

Test-authorship only — no fix is implemented in this file.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import get_connection
from app.repositories.provider_credential import ProviderCredentialRepository
from app.repositories.user_provider_credential import UserProviderCredentialRepository
from app.services import credential_vault as vault
from app.services.llm_client import _STATIC_MODEL_CATALOG

_ANTHROPIC_STATIC_IDS = {m["id"] for m in _STATIC_MODEL_CATALOG["anthropic"]}


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch, tmp_path):
    """A credential save must never touch the real repo-root ``.env``."""
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(tmp_path / "default.env"))


@pytest.fixture(autouse=True)
def _clear_anthropic_env(monkeypatch):
    """Default every test to a genuinely UNCONFIGURED anthropic env so the
    "connected" tests below are attributable ONLY to what they explicitly set
    (DB row or env var), never an ambient credential in the real .env."""
    for var in ("ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def _clean_provider_credentials():
    """``ProviderCredential`` has no FK to ``User`` and is not in conftest's
    truncation list (deployment-wide, shared across concurrently-running
    suites) — delete only the ``anthropic`` row this module touches."""

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
                        'DELETE FROM "ProviderCredential" WHERE "provider" = %s',
                        ("anthropic",),
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


@pytest.fixture()
def admin_headers(client, promote_user_to_admin) -> dict[str, str]:
    headers, uid = _register(client, f"u1x-admin-{uuid.uuid4().hex[:8]}@example.com")
    promote_user_to_admin(uid)
    return headers


# --------------------------------------------------------------------------- #
# PROVIDER_SEED itself
# --------------------------------------------------------------------------- #


def test_provider_seed_anthropic_no_longer_hardcodes_empty_models():
    """FAILS NOW: ``PROVIDER_SEED["anthropic"]["models"] == []``."""
    from app.routers.agents import PROVIDER_SEED

    seed = next(p for p in PROVIDER_SEED if p["id"] == "anthropic")
    assert seed["models"], (
        "PROVIDER_SEED['anthropic']['models'] is still the hardcoded empty "
        "list, even though a working credential-independent 3-model static "
        "catalog exists at llm_client._STATIC_MODEL_CATALOG['anthropic']"
    )
    assert set(seed["models"]) == _ANTHROPIC_STATIC_IDS


# --------------------------------------------------------------------------- #
# GET /agents/providers (operator / deployment-wide scope)
# --------------------------------------------------------------------------- #


def test_admin_providers_anthropic_models_populated_by_db_verified_credential(
    client, admin_headers, _clean_provider_credentials
):
    """FAILS NOW: ``_build_provider_entry`` sets ``models: env_models``, and
    ``_provider_env_state`` never reads the DB ``ProviderCredential`` row at
    all — a genuinely connected+verified DB credential (the prod deployment's
    real state) still renders ``models: []``."""
    ProviderCredentialRepository().upsert(
        "anthropic", auth_mode="oauth_token", secret="sk-ant-oat01-testverified1234"
    )
    ProviderCredentialRepository().mark_verified("anthropic", "ok")

    r = client.get("/agents/providers", headers=admin_headers)
    assert r.status_code == 200, r.text
    anthropic = next(p for p in r.json() if p["id"] == "anthropic")
    assert anthropic["status"] == "connected", anthropic
    assert anthropic["source"] == "database", anthropic
    assert set(anthropic["models"]) == _ANTHROPIC_STATIC_IDS, (
        f"anthropic is connected+verified (source=database) but 'models' is "
        f"{anthropic['models']!r}, expected the static catalog ids "
        f"{_ANTHROPIC_STATIC_IDS!r}"
    )


def test_admin_providers_anthropic_models_populated_by_env_credential(
    client, admin_headers, monkeypatch, _clean_provider_credentials
):
    """FAILS NOW: same gap via the legacy env-credential path (no DB row at
    all — ``ANTHROPIC_API_KEY`` set directly in the server environment)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-testenvkey1234567890")

    r = client.get("/agents/providers", headers=admin_headers)
    assert r.status_code == 200, r.text
    anthropic = next(p for p in r.json() if p["id"] == "anthropic")
    assert anthropic["status"] == "connected", anthropic
    assert anthropic["source"] == "environment", anthropic
    assert set(anthropic["models"]) == _ANTHROPIC_STATIC_IDS, (
        f"anthropic is connected via the server env but 'models' is "
        f"{anthropic['models']!r}, expected {_ANTHROPIC_STATIC_IDS!r}"
    )


def test_admin_providers_anthropic_models_empty_when_unconfigured(
    client, admin_headers, _clean_provider_credentials
):
    """Contrast guard: an UNCONFIGURED anthropic (no DB row, no env var — the
    autouse ``_clear_anthropic_env``/``_clean_provider_credentials`` fixtures
    guarantee this) must keep the honest empty-models behaviour. Already true
    today; pinned here so the fix above cannot regress it into fabricating a
    catalog for a provider nobody can actually call (D-0020)."""
    r = client.get("/agents/providers", headers=admin_headers)
    assert r.status_code == 200, r.text
    anthropic = next(p for p in r.json() if p["id"] == "anthropic")
    assert anthropic["status"] == "unconfigured", anthropic
    assert anthropic["models"] == [], anthropic


# --------------------------------------------------------------------------- #
# GET /agents/user/providers/catalog (customer / per-user scope, F-01)
# --------------------------------------------------------------------------- #


def test_customer_catalog_anthropic_models_populated_by_own_verified_credential(
    client, auth_headers, test_user_id
):
    """FAILS NOW: ``_build_user_provider_entry`` reads ``seed["models"]``
    directly (never the calling user's own verified credential state), so a
    customer with their OWN verified anthropic key still sees ``models: []``
    on the per-user catalog panel."""
    UserProviderCredentialRepository().upsert(
        test_user_id, "anthropic", auth_mode="oauth_token", secret="sk-ant-oat01-mytoken12345"
    )
    UserProviderCredentialRepository().mark_verified(test_user_id, "anthropic", "ok")

    r = client.get("/agents/user/providers/catalog", headers=auth_headers)
    assert r.status_code == 200, r.text
    anthropic = next(p for p in r.json() if p["id"] == "anthropic")
    assert anthropic["status"] == "connected", anthropic
    assert set(anthropic["models"]) == _ANTHROPIC_STATIC_IDS, (
        f"a customer with their OWN verified anthropic credential still sees "
        f"models={anthropic['models']!r} on GET /agents/user/providers/catalog"
    )


def test_customer_catalog_anthropic_models_empty_when_no_own_credential(
    client, auth_headers
):
    """Contrast guard: a customer with NO anthropic credential of their own
    must keep seeing an honest empty list — never the operator's deployment
    credential state (F-01) and never a fabricated catalog (D-0020)."""
    r = client.get("/agents/user/providers/catalog", headers=auth_headers)
    assert r.status_code == 200, r.text
    anthropic = next(p for p in r.json() if p["id"] == "anthropic")
    assert anthropic["status"] == "unconfigured", anthropic
    assert anthropic["models"] == [], anthropic
