"""Provider-config feature (PROVIDER-CONFIG-RUN) — credential vault, provider
routing / native Anthropic transport, and the credential endpoints.

These lock in the billing-separation contract (REQ-PC-2..7, ADR-PC-2/3/5):
- Fernet encryption at rest, honest failure when the key is absent;
- deterministic model -> provider routing with NO cross-provider fallback;
- Anthropic auth-header selection per authMode (native Messages API);
- the PUT -> GET credential round-trip masks the secret (last-4 hint only).

Pure-unit tests deliberately avoid the ``client``/DB fixtures so they stay
deterministic; the endpoint tests use the shared ``client``/``auth_headers``.
"""
from __future__ import annotations

import pytest

from app.services import credential_vault as vault
from app.services.llm_client import (
    LLMClient,
    anthropic_auth_headers,
    build_anthropic_request,
    parse_anthropic_response,
    resolve_credential,
    resolve_provider,
)

_ELLIPSIS = "…"


# ---------------------------------------------------------------------------
# 1. Credential vault (Fernet) — pure unit, no DB
# ---------------------------------------------------------------------------


class TestCredentialVault:
    def test_round_trip_encrypt_decrypt(self, monkeypatch):
        monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
        secret = "sk-ant-api-abcdefg1234Qz"
        token = vault.encrypt(secret)
        assert token != secret  # ciphertext, not plaintext
        assert vault.decrypt(token) == secret

    def test_missing_key_raises_honest_error_on_write(self, monkeypatch):
        monkeypatch.delenv("AETHER_CREDENTIAL_KEY", raising=False)
        assert vault.key_present() is False
        with pytest.raises(RuntimeError) as exc:
            vault.encrypt("sk-ant-api-secret")
        # Honest, specific message naming the env key — not a silent no-op.
        assert "AETHER_CREDENTIAL_KEY" in str(exc.value)

    def test_key_present_true_when_set(self, monkeypatch):
        monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
        assert vault.key_present() is True

    def test_secret_hint_is_ellipsis_plus_last_four(self):
        assert vault.secret_hint("sk-ant-api-abcd1234") == f"{_ELLIPSIS}1234"
        assert vault.secret_hint("abcdef") == f"{_ELLIPSIS}cdef"
        # never exposes more than the last 4 chars
        hint = vault.secret_hint("supersecretvalue9999")
        assert hint == f"{_ELLIPSIS}9999"
        assert "supersecret" not in hint

    def test_invalid_key_is_rejected(self, monkeypatch):
        monkeypatch.setenv("AETHER_CREDENTIAL_KEY", "not-a-valid-fernet-key")
        with pytest.raises(RuntimeError):
            vault.encrypt("sk-ant-api-secret")


# ---------------------------------------------------------------------------
# 2. Model -> provider routing (pure function)
# ---------------------------------------------------------------------------


class TestProviderRouting:
    def test_claude_prefix_routes_to_anthropic(self):
        assert resolve_provider("claude-opus-4-8") == "anthropic"
        assert resolve_provider("claude-sonnet-5") == "anthropic"
        assert resolve_provider("claude-haiku-4-5") == "anthropic"

    def test_anthropic_namespace_routes_to_openrouter(self):
        # Billing-separation fix (adversarial-review, GAP-P7-MODEL-CHOICE-001):
        # OpenRouter namespaces every model it serves as ``vendor/model`` and
        # bills them itself, so an ``anthropic/…`` id (an OpenRouter catalog entry)
        # must route to OpenRouter — NOT the direct-Anthropic account. Only a bare
        # ``claude-…`` native id (see test above) routes to direct Anthropic. The
        # app never uses an ``anthropic/`` prefix for a direct-Anthropic model.
        assert resolve_provider("anthropic/claude-3.5-sonnet") == "openrouter"
        assert resolve_provider("anthropic/claude-opus-4.8") == "openrouter"

    def test_everything_else_routes_to_openrouter(self):
        assert resolve_provider("gpt-4o") == "openrouter"
        assert resolve_provider("deepseek/deepseek-chat") == "openrouter"
        assert resolve_provider("meta-llama/llama-3.3-70b-instruct") == "openrouter"
        assert resolve_provider("") == "openrouter"


# ---------------------------------------------------------------------------
# 3. NO cross-provider fallback (the billing contract, ADR-PC-2)
# ---------------------------------------------------------------------------


def _no_db_credentials(monkeypatch):
    """Force the DB credential lookup to return nothing (deterministic)."""
    monkeypatch.setattr(
        "app.repositories.provider_credential.ProviderCredentialRepository.get_secret",
        lambda self, provider: None,
    )


def _clear_all_provider_env(monkeypatch):
    for var in (
        "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL", "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "ABACUS_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


class TestNoCrossProviderFallback:
    def test_anthropic_model_with_only_openrouter_creds_raises(self, monkeypatch):
        _no_db_credentials(monkeypatch)
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-only")

        # anthropic has no credential -> must raise, naming the provider.
        assert resolve_credential("anthropic") is None
        or_res = resolve_credential("openrouter")
        assert or_res is not None and or_res.secret == "sk-or-only"

    def test_call_live_never_routes_anthropic_traffic_to_openrouter(self, monkeypatch):
        """A claude-* model with only an OpenRouter key must FAIL, and must not
        fire a single HTTP request (no silent cross-provider billing)."""
        import httpx

        _no_db_credentials(monkeypatch)
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-only")

        called = {"n": 0}

        def _boom_post(*a, **k):
            called["n"] += 1
            raise AssertionError("no HTTP call should be made without a credential")

        monkeypatch.setattr(httpx, "post", _boom_post)
        llm = LLMClient(mode="live")
        with pytest.raises(RuntimeError) as exc:
            llm._call_live("sys", "usr", model="claude-opus-4-8", temperature=0.0)
        assert "anthropic" in str(exc.value).lower()
        assert called["n"] == 0

    def test_openrouter_model_with_only_anthropic_env_gets_no_credential(
        self, monkeypatch
    ):
        """Mirror crossover (GAP-PC-006): a NON-claude model with ONLY the legacy
        Anthropic env pair set (AETHER_LLM_API_KEY=sk-ant-… +
        AETHER_LLM_BASE_URL=…anthropic.com…) and NO OpenRouter key must NOT be
        handed the Anthropic secret. resolve_credential('openrouter') MUST be
        None so the Anthropic key/host is never used for OpenRouter traffic."""
        _no_db_credentials(monkeypatch)
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("AETHER_LLM_API_KEY", "sk-ant-api-LEGACYanthropicKEY")
        monkeypatch.setenv("AETHER_LLM_BASE_URL", "https://api.anthropic.com/v1")

        # The Anthropic-pointed generic pair must NOT resolve for openrouter.
        assert resolve_credential("openrouter") is None
        # And the anthropic-direction guard must still resolve for anthropic.
        anth = resolve_credential("anthropic")
        assert anth is not None and anth.provider == "anthropic"

    def test_call_live_never_sends_anthropic_secret_to_openrouter(self, monkeypatch):
        """The live path for a non-claude model (e.g. the auto-mode fallback
        model) with ONLY the legacy Anthropic env pair must raise an honest
        'no credential for openrouter' error and fire ZERO HTTP — never POST the
        Anthropic secret to the OpenRouter path (ADR-PC-2)."""
        import httpx

        _no_db_credentials(monkeypatch)
        _clear_all_provider_env(monkeypatch)
        monkeypatch.setenv("AETHER_LLM_API_KEY", "sk-ant-api-LEGACYanthropicKEY")
        monkeypatch.setenv("AETHER_LLM_BASE_URL", "https://api.anthropic.com/v1")

        called = {"n": 0}

        def _boom_post(*a, **k):
            called["n"] += 1
            raise AssertionError("no HTTP call should be made without a credential")

        monkeypatch.setattr(httpx, "post", _boom_post)
        llm = LLMClient(mode="live")
        with pytest.raises(RuntimeError) as exc:
            llm._call_live(
                "sys", "usr", model="openai/gpt-oss-20b:free", temperature=0.0
            )
        assert "openrouter" in str(exc.value).lower()
        assert called["n"] == 0


# ---------------------------------------------------------------------------
# 4. Native Anthropic transport — header selection per authMode
# ---------------------------------------------------------------------------


class TestAnthropicTransport:
    def test_subscription_oauth_mode_is_rejected(self):
        # Consumer subscription OAuth transport was removed (GAP-AUTH-001):
        # x-api-key is the ONLY supported Anthropic auth, so this is a hard error.
        with pytest.raises(RuntimeError):
            anthropic_auth_headers("subscription_oauth", "sk-ant-oat-token")

    def test_api_key_uses_x_api_key_no_bearer(self):
        headers = anthropic_auth_headers("api_key", "sk-ant-api-key")
        assert headers["x-api-key"] == "sk-ant-api-key"
        assert headers["anthropic-version"] == "2023-06-01"
        assert "Authorization" not in headers
        assert "anthropic-beta" not in headers

    def test_build_request_targets_native_messages_endpoint(self):
        req = build_anthropic_request(
            "claude-opus-4-8", "be brief", "hi",
            auth_mode="api_key", secret="sk-ant-api-key", max_tokens=7,
        )
        assert req["url"].endswith("/v1/messages")
        assert req["json"]["model"] == "claude-opus-4-8"
        assert req["json"]["max_tokens"] == 7  # required int
        assert req["json"]["system"] == "be brief"
        assert req["json"]["messages"] == [{"role": "user", "content": "hi"}]
        # Anthropic 400s on temperature/top_p for current models — must be absent.
        assert "temperature" not in req["json"]
        assert "top_p" not in req["json"]

    def test_build_request_normalises_base_url_with_v1(self):
        req = build_anthropic_request(
            "claude-sonnet-5", None, "hi",
            auth_mode="api_key", secret="sk-ant-api-key",
            base_url="https://api.anthropic.com/v1", max_tokens=1,
        )
        assert req["url"] == "https://api.anthropic.com/v1/messages"
        assert "system" not in req["json"]  # omitted when empty

    def test_parse_response_concatenates_text_blocks(self):
        body = {
            "stop_reason": "end_turn",
            "content": [
                {"type": "text", "text": "Hello "},
                {"type": "thinking", "text": "IGNORED"},
                {"type": "text", "text": "world"},
            ],
        }
        assert parse_anthropic_response(body) == "Hello world"

    def test_parse_response_refusal_is_honest_error(self):
        body = {"stop_reason": "refusal", "content": []}
        with pytest.raises(RuntimeError):
            parse_anthropic_response(body)


# ---------------------------------------------------------------------------
# 5. Credential endpoints — PUT -> GET masks the secret (needs DB + auth)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_provider_credentials():
    """ProviderCredential has no FK to User, so it is NOT in conftest's cleanup
    list — self-clean it and reset the repo's process-level table-ready cache."""
    from app.db import get_connection
    from app.repositories import provider_credential as pc_module

    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS "ProviderCredential"')
        conn.commit()
    pc_module._table_ready = False


class TestCredentialEndpoints:
    def test_put_then_get_masks_secret_not_plaintext(
        self, client, auth_headers, monkeypatch, _clean_provider_credentials
    ):
        monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
        secret = "sk-ant-api-TOPSECRETvalue1234"
        put = client.put(
            "/agents/providers/anthropic/credential",
            json={"authMode": "api_key", "secret": secret},
            headers=auth_headers,
        )
        assert put.status_code == 200, put.text
        row = put.json()
        assert row["secretHint"] == f"{_ELLIPSIS}1234"
        assert secret not in put.text  # plaintext NEVER echoed back

        providers = client.get("/agents/providers", headers=auth_headers)
        assert providers.status_code == 200
        assert secret not in providers.text  # not leaked in the list either
        anthropic = next(p for p in providers.json() if p["id"] == "anthropic")
        assert anthropic["source"] == "database"
        assert anthropic["status"] == "connected"
        assert anthropic["authMode"] == "api_key"
        assert anthropic["secretHint"] == f"{_ELLIPSIS}1234"

    def test_put_credential_missing_key_returns_503(
        self, client, auth_headers, monkeypatch, _clean_provider_credentials
    ):
        monkeypatch.delenv("AETHER_CREDENTIAL_KEY", raising=False)
        res = client.put(
            "/agents/providers/openrouter/credential",
            json={"authMode": "api_key", "secret": "sk-or-value"},
            headers=auth_headers,
        )
        assert res.status_code == 503, res.text

    def test_put_rejects_mismatched_anthropic_prefix(
        self, client, auth_headers, monkeypatch, _clean_provider_credentials
    ):
        monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
        # api_key mode but an oauth-shaped token -> 422
        bad = client.put(
            "/agents/providers/anthropic/credential",
            json={"authMode": "api_key", "secret": "sk-ant-oat-oops"},
            headers=auth_headers,
        )
        assert bad.status_code == 422, bad.text
        # openrouter only supports api_key
        bad2 = client.put(
            "/agents/providers/openrouter/credential",
            json={"authMode": "subscription_oauth", "secret": "sk-or-x"},
            headers=auth_headers,
        )
        assert bad2.status_code == 422, bad2.text

    def test_anthropic_subscription_oauth_write_is_rejected(
        self, client, auth_headers, monkeypatch, _clean_provider_credentials
    ):
        # GAP-AUTH-001: saving an Anthropic subscription_oauth credential is no
        # longer allowed — the write-path rejects it (422), never stores it.
        monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
        put = client.put(
            "/agents/providers/anthropic/credential",
            json={"authMode": "subscription_oauth", "secret": "sk-ant-oat-abcd1234"},
            headers=auth_headers,
        )
        assert put.status_code == 422, put.text

    def test_delete_credential_falls_back_to_env_source(
        self, client, auth_headers, monkeypatch, _clean_provider_credentials
    ):
        monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-fallback")
        client.put(
            "/agents/providers/openrouter/credential",
            json={"authMode": "api_key", "secret": "sk-or-db-value"},
            headers=auth_headers,
        )
        db_state = next(
            p for p in client.get("/agents/providers", headers=auth_headers).json()
            if p["id"] == "openrouter"
        )
        assert db_state["source"] == "database"

        deleted = client.delete(
            "/agents/providers/openrouter/credential", headers=auth_headers
        )
        assert deleted.status_code == 200, deleted.text
        # Env key is still present -> status stays connected, source degrades to env.
        assert deleted.json()["source"] == "environment"
        assert deleted.json()["status"] == "connected"

    def test_read_degrades_to_env_when_vault_key_missing(
        self, client, auth_headers, monkeypatch, _clean_provider_credentials
    ):
        # Store a DB credential while the key is present...
        monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
        client.put(
            "/agents/providers/openrouter/credential",
            json={"authMode": "api_key", "secret": "sk-or-db-value"},
            headers=auth_headers,
        )
        # ...then remove the key: the ciphertext is now un-decryptable, so the
        # status must NOT claim source='database' (ADR-PC-3 read degradation).
        monkeypatch.delenv("AETHER_CREDENTIAL_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
        openrouter = next(
            p for p in client.get("/agents/providers", headers=auth_headers).json()
            if p["id"] == "openrouter"
        )
        assert openrouter["source"] == "environment"

    def test_verify_without_any_credential_is_not_ok(
        self, client, auth_headers, monkeypatch, _clean_provider_credentials
    ):
        # No DB row and no env key for gemini -> honest not-ok, never faked.
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        res = client.post("/agents/providers/gemini/verify", headers=auth_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is False
        assert body["status"] != "ok"

    def test_credential_endpoints_unknown_provider_404(
        self, client, auth_headers, _clean_provider_credentials
    ):
        assert client.put(
            "/agents/providers/abacus/credential",
            json={"authMode": "api_key", "secret": "x"},
            headers=auth_headers,
        ).status_code == 404

    def test_expired_credential_is_not_shown_connected(
        self, client, auth_headers, monkeypatch, _clean_provider_credentials
    ):
        # MV-agents-004: a stored credential ROW EXISTING is not proof it
        # still works — only a genuine last verify result is. Simulate an
        # expired/revoked Anthropic credential the exact way the real
        # POST /providers/{p}/verify round-trip records a failure
        # (ProviderCredentialRepository.mark_verified(provider, "failed")),
        # then confirm the providers panel demotes it off the green
        # "Connected" badge instead of showing a false-positive connection.
        monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
        client.put(
            "/agents/providers/anthropic/credential",
            json={"authMode": "api_key", "secret": "sk-ant-api-EXPIREDvalue1234"},
            headers=auth_headers,
        )
        from app.repositories.provider_credential import ProviderCredentialRepository

        ProviderCredentialRepository().mark_verified("anthropic", "failed")

        providers = client.get("/agents/providers", headers=auth_headers)
        assert providers.status_code == 200, providers.text
        anthropic = next(p for p in providers.json() if p["id"] == "anthropic")
        assert anthropic["lastVerifyStatus"] == "failed"
        assert anthropic["status"] != "connected"
        assert anthropic["status"] == "warning"
        assert "failed" in anthropic["detail"]
        # Still honestly sourced from the DB — only the badge is demoted.
        assert anthropic["source"] == "database"

    def test_credential_with_ok_last_verify_still_shown_connected(
        self, client, auth_headers, monkeypatch, _clean_provider_credentials
    ):
        # A credential that genuinely passed its last verify keeps the
        # legitimate "Connected" badge — the fix must not blanket-demote
        # every DB-backed credential, only ones with a known failure.
        monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())
        client.put(
            "/agents/providers/anthropic/credential",
            json={"authMode": "api_key", "secret": "sk-ant-api-VALIDvalue1234"},
            headers=auth_headers,
        )
        from app.repositories.provider_credential import ProviderCredentialRepository

        ProviderCredentialRepository().mark_verified("anthropic", "ok")

        providers = client.get("/agents/providers", headers=auth_headers)
        anthropic = next(p for p in providers.json() if p["id"] == "anthropic")
        assert anthropic["lastVerifyStatus"] == "ok"
        assert anthropic["status"] == "connected"
