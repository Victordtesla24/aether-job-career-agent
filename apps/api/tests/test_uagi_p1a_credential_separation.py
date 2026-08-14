"""U-AGI P1-A — F7/F8 structural credential separation (ADR-AGI-3 Decision 3).

The latent defect (SYNTHESIS.md §3.2, composed from verified facts F2+F6+F7+F8):
the operator's deployment-wide Anthropic row may hold a SUBSCRIPTION OAuth token,
and nothing scopes it — so the first supervisor planning call by a subscriber
with no Anthropic credential of their own would be served by the operator's
subscription, and conversely a user-content run could quietly draw on it.

This suite pins BOTH directions BEFORE any supervisor LLM call exists:

* F7 — the operator role consumes ONLY the operator-scoped credential slot
  (deployment-wide row / provider-scoped env). A user's own row is never
  reachable from it.
* F8 — user-content generation resolves the user's OWN credential first, then
  the deployment-wide row. MODEL-DEFAULT reconciliation (OWNER DIRECTIVE,
  2026-08-14): that deployment-wide row — the operator's Anthropic Pro
  subscription — IS the intended system default for user-content, so the P1-A
  wall that returned ``None`` here is lifted. A single subscriber cannot drain
  it: the EXISTING per-user quota + spend cap bounds every run. The wall itself
  is retained as a general ``resolve_credential`` capability, just no longer
  engaged by the user-content path.

Plus the operator fallback CHAIN as configuration of the existing machinery:
anthropic-first, advancing only on exhaustion signals, primary retried first on
every new plan. No new provider layer is introduced.
"""
from __future__ import annotations

import pytest

from app.repositories.user_provider_credential import UserProviderCredentialRepository
from app.services import credential_vault as vault
from app.services.llm_client import (
    OPERATOR_SCOPED_AGENT_KEYS,
    LLMClient,
    ProviderCredentialResolution,
    operator_fallback_chain,
    resolve_credential,
    resolve_user_credential,
    user_credential_context,
    user_model_context,
)

OPERATOR_ROLE = next(iter(OPERATOR_SCOPED_AGENT_KEYS))

_ENV_VARS = (
    "ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL",
    "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "ABACUS_API_KEY",
)


@pytest.fixture()
def _vault_key(monkeypatch):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture()
def _no_env_credentials(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _operator_row(monkeypatch, *, auth_mode: str, secret: str) -> None:
    """Install a deployment-wide (operator-scoped) ProviderCredential row."""
    monkeypatch.setattr(
        "app.repositories.provider_credential.ProviderCredentialRepository.get_secret",
        lambda self, provider: (
            {"secret": secret, "authMode": auth_mode, "baseUrl": None}
            if provider == "anthropic"
            else None
        ),
    )


def _no_operator_row(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.repositories.provider_credential.ProviderCredentialRepository.get_secret",
        lambda self, provider: None,
    )


# ---------------------------------------------------------------------------
# F7 — the operator role consumes ONLY the operator slot.
# ---------------------------------------------------------------------------


def test_f7_operator_role_never_consumes_a_users_own_credential(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    UserProviderCredentialRepository().upsert(
        test_user_id, "anthropic", auth_mode="api_key", secret="sk-ant-api-USER-OWN"
    )
    _operator_row(monkeypatch, auth_mode="api_key", secret="sk-ant-api-OPERATOR")

    res = resolve_user_credential("anthropic", test_user_id, OPERATOR_ROLE)
    assert res is not None
    assert res.secret == "sk-ant-api-OPERATOR"
    assert res.source == "database"


def test_f7_operator_role_gets_an_honest_none_when_the_operator_slot_is_empty(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    """Falling back to the user's key would bill the wrong party. An empty
    operator slot is an honest refusal, never a silent substitution."""
    UserProviderCredentialRepository().upsert(
        test_user_id, "anthropic", auth_mode="api_key", secret="sk-ant-api-USER-OWN"
    )
    _no_operator_row(monkeypatch)

    assert resolve_user_credential("anthropic", test_user_id, OPERATOR_ROLE) is None


def test_f7_operator_role_ignores_a_per_agent_credential_ref(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    """``AgentConfig.credentialRef`` is a USER seam; an operator role must not
    be re-pointable at a subscriber's key through it."""
    monkeypatch.setattr(
        "app.services.llm_client._lookup_agent_credential_ref",
        lambda user_id, agent_key: "some-user-credential-id",
    )
    monkeypatch.setattr(
        "app.repositories.user_provider_credential."
        "UserProviderCredentialRepository.get_secret_by_id",
        lambda self, ref, user_id: {
            "provider": "anthropic", "authMode": "api_key",
            "secret": "sk-ant-api-USER-PINNED", "baseUrl": None,
        },
    )
    _operator_row(monkeypatch, auth_mode="api_key", secret="sk-ant-api-OPERATOR")

    res = resolve_user_credential("anthropic", test_user_id, OPERATOR_ROLE)
    assert res is not None and res.secret == "sk-ant-api-OPERATOR"


def test_f7_operator_role_may_use_the_operator_subscription_row(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    """The owner's Max/Pro subscription IS the supervisor's intended primary
    binding (ADR-AGI-3 D3) — the wall is one-directional."""
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")

    res = resolve_user_credential("anthropic", test_user_id, OPERATOR_ROLE)
    assert res is not None
    assert res.auth_mode == "oauth_token"
    assert res.secret == "sk-ant-oat01-OPERATOR"


# ---------------------------------------------------------------------------
# F8 — user-content generation never consumes the operator SUBSCRIPTION row.
# ---------------------------------------------------------------------------


def test_f8_user_content_may_use_the_operator_subscription_metered(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    """MODEL-DEFAULT reconciliation (OWNER DIRECTIVE, 2026-08-14): user-content
    with no credential of its own resolves the operator's Anthropic subscription
    — the intended system default — instead of the old honest-``None``. The
    old ``assert res is None`` here BROKE the owner's own bare ``claude-*``
    tailoring/storyExtraction runs; per-user quota + spend caps bound it now."""
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")

    res = resolve_user_credential("anthropic", test_user_id, "tailor")
    assert res is not None
    assert res.auth_mode == "oauth_token"
    assert res.secret == "sk-ant-oat01-OPERATOR"
    assert res.source == "database"


def test_f8_user_content_still_uses_the_operator_api_key(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    """Only the SUBSCRIPTION row is walled off. A deployment API key is metered
    API billing and stays exactly as it shipped."""
    _operator_row(monkeypatch, auth_mode="api_key", secret="sk-ant-api-OPERATOR")

    res = resolve_user_credential("anthropic", test_user_id, "tailor")
    assert res is not None and res.secret == "sk-ant-api-OPERATOR"


def test_f8_user_own_credential_still_wins_over_everything(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    UserProviderCredentialRepository().upsert(
        test_user_id, "anthropic", auth_mode="api_key", secret="sk-ant-api-USER-OWN"
    )
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")

    res = resolve_user_credential("anthropic", test_user_id, "tailor")
    assert res is not None and res.secret == "sk-ant-api-USER-OWN"
    assert res.source == "user_credential"


def test_f8_operator_subscription_row_wins_over_ambient_env(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    """Post-reconciliation the configured operator subscription (DB row) is read
    DB-first and IS resolved for user-content, so it takes precedence over an
    ambient legacy ``ANTHROPIC_API_KEY`` env key (this replaces the old
    wall-falls-through-to-env assertion, since the wall no longer engages)."""
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-ENV")

    res = resolve_user_credential("anthropic", test_user_id, "tailor")
    assert res is not None
    assert res.secret == "sk-ant-oat01-OPERATOR"
    assert res.source == "database"


def test_the_legacy_no_user_context_resolver_is_unchanged(
    monkeypatch, _no_env_credentials
):
    """``resolve_credential`` itself keeps its shipped behaviour byte for byte —
    the wall lives in the user-scoped resolver, so no other caller changes."""
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")
    res = resolve_credential("anthropic")
    assert isinstance(res, ProviderCredentialResolution)
    assert res.auth_mode == "oauth_token"


def test_no_cross_provider_crossover_survives_the_new_wall(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    """The pre-existing invariant: a missing anthropic credential is NEVER
    served by an openrouter one."""
    _no_operator_row(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-KEY")

    assert resolve_user_credential("anthropic", test_user_id, "tailor") is None
    assert resolve_user_credential("anthropic", test_user_id, OPERATOR_ROLE) is None


# ---------------------------------------------------------------------------
# The operator fallback CHAIN — configuration of the EXISTING machinery.
# ---------------------------------------------------------------------------


def test_operator_fallback_chain_is_empty_unless_configured(monkeypatch):
    """No configuration means no fallback: an honest failure beats a silent
    reroute onto a payer nobody chose."""
    monkeypatch.delenv("AETHER_OPERATOR_FALLBACK_MODELS", raising=False)
    assert operator_fallback_chain() == ()


def test_operator_fallback_chain_preserves_the_configured_order(monkeypatch):
    monkeypatch.setenv(
        "AETHER_OPERATOR_FALLBACK_MODELS",
        "openai/gpt-5.5, route-llm ,google/gemini-3.5-flash",
    )
    assert operator_fallback_chain() == (
        "openai/gpt-5.5", "route-llm", "google/gemini-3.5-flash",
    )


def test_the_operator_chain_puts_the_primary_first_on_every_invocation(monkeypatch):
    """ADR-AGI-3 D3 'Anthropic is retried first on every new plan/evaluation'
    — the chain is rebuilt per call, so auto-return is structural."""
    monkeypatch.setenv(
        "AETHER_OPERATOR_FALLBACK_MODELS", "openai/gpt-5.5,route-llm"
    )
    with user_credential_context("u1", OPERATOR_ROLE):
        first = LLMClient._model_chain("claude-opus-4-8")
        second = LLMClient._model_chain("claude-opus-4-8")
    assert first == ["claude-opus-4-8", "openai/gpt-5.5", "route-llm"]
    assert second == first


def test_a_user_content_run_never_inherits_the_operator_chain(monkeypatch):
    monkeypatch.setenv(
        "AETHER_OPERATOR_FALLBACK_MODELS", "openai/gpt-5.5,route-llm"
    )
    with user_credential_context("u1", "tailor"):
        chain = LLMClient._model_chain("claude-opus-4-8")
    assert "openai/gpt-5.5" not in chain
    assert "route-llm" not in chain


def test_a_user_chosen_model_is_still_never_substituted(monkeypatch):
    """ADR-ML-3 survives the operator chain: a deliberate user pick is alone."""
    monkeypatch.setenv("AETHER_OPERATOR_FALLBACK_MODELS", "openai/gpt-5.5")
    with user_credential_context("u1", "tailor"), user_model_context("claude-sonnet-4-6"):
        assert LLMClient._model_chain("claude-sonnet-4-6") == ["claude-sonnet-4-6"]


# ---------------------------------------------------------------------------
# The chain advances on EXHAUSTION SIGNALS ONLY (ADR-AGI-3 Decision 3).
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status_code, text, payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


def _transport(monkeypatch, responder):
    import httpx

    seen: list[str] = []

    def _post(url, **kwargs):  # noqa: ANN001
        model = kwargs["json"]["model"]
        seen.append(model)
        return responder(model)

    monkeypatch.setattr(httpx, "post", _post)
    return seen


@pytest.fixture()
def _operator_chain_env(monkeypatch):
    monkeypatch.setenv("AETHER_OPERATOR_FALLBACK_MODELS", "openai/rescue-1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.delenv("AETHER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ABACUS_API_KEY", raising=False)


def test_the_operator_chain_advances_on_an_out_of_credits_signal(
    monkeypatch, tmp_path, _operator_chain_env
):
    from app.services.llm_client import LLMClient, served_model_capture

    def responder(model):
        if model == "openrouter/primary":
            return _Resp(402, '{"error":{"code":402}}', {"error": {"code": 402}})
        return _Resp(
            200, "ok",
            {"choices": [{"message": {"content": "ok"}}], "model": model},
        )

    seen = _transport(monkeypatch, responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)
    with user_credential_context("u1", OPERATOR_ROLE), served_model_capture():
        out = llm.complete(
            "p", "sys", "usr", model="openrouter/primary", fixture_key="k"
        )
    assert out == "ok"
    assert seen == ["openrouter/primary", "openai/rescue-1"]


def test_the_operator_chain_does_NOT_advance_on_a_model_failure(
    monkeypatch, tmp_path, _operator_chain_env
):
    """A 503/404 is a failure OF the chosen model. Walking to another provider
    for it is exactly the silent substitution ADR-ML-3 forbids — so the chain
    ends and the honest error surfaces."""
    from app.services.llm_client import (
        LLMClient,
        LLMUnavailableError,
        served_model_capture,
    )

    seen = _transport(monkeypatch, lambda m: _Resp(503, "upstream down", {}))
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)
    with user_credential_context("u1", OPERATOR_ROLE), served_model_capture():
        with pytest.raises(LLMUnavailableError):
            llm.complete("p", "sys", "usr", model="openrouter/primary", fixture_key="k")
    assert seen == ["openrouter/primary"], (
        "the operator chain walked past a plain model failure"
    )


def test_a_user_run_still_walks_its_chain_on_a_model_failure(
    monkeypatch, tmp_path, _operator_chain_env
):
    """PIN: the tightening above is scoped to operator runs. A user run's
    shipped one-retry resilience is byte-for-byte unchanged."""
    from app.services.llm_client import LLMClient, served_model_capture

    monkeypatch.setenv("AETHER_MODEL_FALLBACK", "openrouter/fallback")

    def responder(model):
        if model == "openrouter/primary":
            return _Resp(503, "upstream down", {})
        return _Resp(
            200, "ok",
            {"choices": [{"message": {"content": "ok"}}], "model": model},
        )

    seen = _transport(monkeypatch, responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)
    with user_credential_context("u1", "tailor"), served_model_capture():
        assert llm.complete(
            "p", "sys", "usr", model="openrouter/primary", fixture_key="k"
        ) == "ok"
    assert seen == ["openrouter/primary", "openrouter/fallback"]
