"""ML-agents-cred-005 (MODELS-LIVE, LOW) — deleting the Anthropic credential
must clear/ignore a stale ``needs_reauth`` ``AnthropicOAuthToken`` row so the
provider honestly returns to ``unconfigured``, not a leftover ``warning``.

**Bug being fixed:** ``DELETE /agents/providers/{provider}/credential``
(``app/routers/agents.py`` ``delete_provider_credential``) only calls
``ProviderCredentialRepository().delete(provider)`` — it never touches the
per-user ``AnthropicOAuthToken`` row. Independently, ``_build_provider_entry``
(added by ML-agents-cred-002 to surface ``needsReauth`` honestly) reads
``_anthropic_oauth_needs_reauth(user_id)`` UNCONDITIONALLY — even when the
deployment-wide ``ProviderCredential('anthropic')`` row is now ABSENT (i.e.
``source == "none"`` / ``status == "unconfigured"`` from the DB/env branches)
— and forcibly overwrites ``status`` to ``"warning"`` whenever that stale
per-user token row is marked ``needs_reauth`` (``agents.py`` lines ~2135-2141).

Net effect: connect via OAuth -> the auto-refresh (or an explicit
``mark_needs_reauth``) fails once -> operator deletes the credential meaning
to fully disconnect -> the provider panel STILL shows the "warning" /
Reconnect-required badge instead of the honest "unconfigured" state, because
the now-orphaned ``AnthropicOAuthToken`` row outlives the credential it was
paired with.

**The fix under test (NOT implemented by this commit):** either (a) the
DELETE path also clears/marks the ``AnthropicOAuthToken`` row for that
provider, or (b) ``_build_provider_entry`` only applies the ``needs_reauth``
demotion when there is an ACTIVE (non-``none``-source) anthropic credential to
demote in the first place. Either way, the observable contract pinned below
is: after DELETE, with a stale needs_reauth token row still physically
present in the DB, the provider status must read ``unconfigured`` and
``needsReauth`` must not be true.

FAIL-BEFORE (WHY): the stale ``AnthropicOAuthToken`` row (scopes=
'needs_reauth') is untouched by DELETE and unconditionally re-applied by
``_build_provider_entry``, so status is currently ``"warning"`` with
``needsReauth: true`` post-delete, not ``"unconfigured"``.

Run under the shared test DB lock (schema=aether_test ONLY):
    flock /tmp/aether-pytest.lock python3 -m pytest \
        tests/test_ml_agents_cred_005_delete_clears_reauth.py -q
"""
from __future__ import annotations

import pytest

from app.services import credential_vault as vault

FAKE_ACCESS_1 = "sk-ant-oat01-FAKEtestACCESSvalue0000000000deadbeef"
FAKE_REFRESH_1 = "sk-ant-ort01-FAKEtestREFRESHvalue0000000000deadbeef"


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    """Deterministic Fernet key so encrypt/decrypt agree within a test."""
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch, tmp_path):
    """A credential save must NEVER touch the real repo-root ``.env`` during
    tests — default the oauth_token sync target to a per-test tmp file."""
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(tmp_path / "default.env"))


@pytest.fixture(autouse=True)
def _clear_anthropic_env(monkeypatch):
    """Remove every env var that could resolve an Anthropic credential so the
    stored DB rows (or their absence) are the ONLY source under test."""
    for var in (
        "ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY", "ABACUS_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def _clean_anthropic_oauth_state():
    """None of ProviderCredential / AnthropicOAuthState / AnthropicOAuthToken /
    UserProviderCredential carry an FK to ``User``, so conftest's per-test
    ``_truncate_tables`` never touches them — self-clean after each test."""
    from app.db import get_connection
    from app.repositories import provider_credential as pc_module
    from app.repositories import user_provider_credential as upc_module

    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS "ProviderCredential"')
            cur.execute('DROP TABLE IF EXISTS "AnthropicOAuthState"')
            cur.execute('DROP TABLE IF EXISTS "AnthropicOAuthToken"')
            cur.execute('DROP TABLE IF EXISTS "UserProviderCredential"')
        conn.commit()
    pc_module._table_ready = False
    upc_module._reset_ready_for_tests()


def _seed_deployment_anthropic_credential(secret: str) -> None:
    from app.repositories.provider_credential import ProviderCredentialRepository

    ProviderCredentialRepository().upsert("anthropic", auth_mode="oauth_token", secret=secret)


def _seed_needs_reauth_token_row(user_id: str) -> None:
    from app.repositories.user_provider_credential import AnthropicOAuthTokenRepository

    repo = AnthropicOAuthTokenRepository()
    repo.upsert(
        user_id,
        access_ciphertext=vault.encrypt(FAKE_ACCESS_1),
        refresh_ciphertext=vault.encrypt(FAKE_REFRESH_1),
        secret_hint=vault.secret_hint(FAKE_ACCESS_1),
        expires_at="2020-01-01T00:00:00Z",
        scopes="user:inference",
    )
    repo.mark_needs_reauth(user_id)


# ===========================================================================
# 1. Sanity precondition (pass-before-and-after): a needs_reauth token row
#    WITH a live credential shows "warning" — this is the EXISTING, correct
#    ML-agents-cred-002 behaviour and must be unaffected by this fix.
# ===========================================================================


def test_precondition_needs_reauth_with_live_credential_shows_warning(
    client, auth_headers, test_user_id, _clean_anthropic_oauth_state
):
    _seed_deployment_anthropic_credential(FAKE_ACCESS_1)
    _seed_needs_reauth_token_row(test_user_id)

    resp = client.get("/agents/providers", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    anthropic = next(p for p in resp.json() if p["id"] == "anthropic")
    assert anthropic["status"] == "warning", anthropic
    assert anthropic.get("needsReauth") is True, anthropic


# ===========================================================================
# 2. THE FIX: DELETE the credential while the needs_reauth token row is still
#    physically present -> the DELETE response itself must report
#    "unconfigured", NOT a leftover "warning".
# FAIL-BEFORE (WHY): delete_provider_credential() never touches
# AnthropicOAuthToken, and _build_provider_entry() unconditionally re-applies
# the needs_reauth demotion regardless of whether a credential still exists.
# ===========================================================================


def test_delete_credential_with_stale_needs_reauth_row_returns_unconfigured(
    client, auth_headers, test_user_id, _clean_anthropic_oauth_state
):
    _seed_deployment_anthropic_credential(FAKE_ACCESS_1)
    _seed_needs_reauth_token_row(test_user_id)

    # Sanity: the stale row is really there before we delete anything.
    from app.repositories.user_provider_credential import AnthropicOAuthTokenRepository

    pre = AnthropicOAuthTokenRepository().get(test_user_id)
    assert pre is not None and pre["scopes"] == "needs_reauth"

    delete_resp = client.delete(
        "/agents/providers/anthropic/credential", headers=auth_headers
    )
    assert delete_resp.status_code == 200, delete_resp.text
    deleted_entry = delete_resp.json()

    assert deleted_entry["status"] == "unconfigured", (
        "DELETE must return the provider to an honest 'unconfigured' status — "
        f"a stale needs_reauth AnthropicOAuthToken row must not leak a "
        f"'warning' badge for a credential that no longer exists: {deleted_entry}"
    )
    assert not deleted_entry.get("needsReauth"), (
        f"needsReauth must not be true once the credential has been deleted: "
        f"{deleted_entry}"
    )
    assert FAKE_ACCESS_1 not in delete_resp.text
    assert FAKE_REFRESH_1 not in delete_resp.text


# ===========================================================================
# 3. Same assertion via a FRESH GET (not just the DELETE response itself) —
#    guards against a fix that only patches the DELETE handler's own return
#    value without actually fixing the read-path / stale-row problem.
# ===========================================================================


def test_get_providers_after_delete_with_stale_needs_reauth_row_shows_unconfigured(
    client, auth_headers, test_user_id, _clean_anthropic_oauth_state
):
    _seed_deployment_anthropic_credential(FAKE_ACCESS_1)
    _seed_needs_reauth_token_row(test_user_id)

    delete_resp = client.delete(
        "/agents/providers/anthropic/credential", headers=auth_headers
    )
    assert delete_resp.status_code == 200, delete_resp.text

    resp = client.get("/agents/providers", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    anthropic = next(p for p in resp.json() if p["id"] == "anthropic")
    assert anthropic["status"] == "unconfigured", anthropic
    assert not anthropic.get("needsReauth"), anthropic
    assert anthropic["source"] == "none", anthropic


# ===========================================================================
# 4. Regression guard: deleting a HEALTHY (non-needs_reauth) credential keeps
#    working exactly as before (pass-before-and-after).
# ===========================================================================


def test_delete_healthy_credential_still_returns_unconfigured(
    client, auth_headers, test_user_id, _clean_anthropic_oauth_state
):
    _seed_deployment_anthropic_credential(FAKE_ACCESS_1)

    delete_resp = client.delete(
        "/agents/providers/anthropic/credential", headers=auth_headers
    )
    assert delete_resp.status_code == 200, delete_resp.text
    entry = delete_resp.json()
    assert entry["status"] == "unconfigured", entry
    assert not entry.get("needsReauth"), entry
