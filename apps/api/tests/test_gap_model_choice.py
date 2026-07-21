"""GAP-P7-MODEL-CHOICE-001 — user-selectable AI models (live OpenRouter catalog).

Users can pick ANY model (high-end or free/open-source) for their agents, by
budget. Two dormant per-user model-preference stores (``AgentConfig.model``,
``AgentProvider.model``) are now READ at run time and threaded into the LLM
client via ``user_model_context``, and a new ``GET /agents/providers/{p}/models``
returns the live, curated, budget-tiered catalog. These tests pin:
  * the env-vs-override resolution (generation tiers honour the choice; STRUCTURED
    stays on the tuned default; a run actually uses the chosen model);
  * the catalog curation/tiering + honest no-catalog errors;
  * the models endpoint + billing separation invariant (choice never crosses
    the anthropic/openrouter boundary — that stays a pure resolve_provider call).
"""
from __future__ import annotations

import pytest

from app.services import credential_vault as vault
from app.services import llm_client
from app.services.llm_client import (
    ModelCatalogError,
    _curate_openrouter_models,
    _model_budget_tier,
    get_model,
    resolve_provider,
    user_model_context,
)


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


# ---------------------------------------------------------------------------
# Resolution: user override wins for generation tiers, never for STRUCTURED
# ---------------------------------------------------------------------------


def test_get_model_override_applies_to_generation_tiers_only(monkeypatch):
    monkeypatch.setenv("AETHER_MODEL_REASONING", "env/reasoning")
    monkeypatch.setenv("AETHER_MODEL_HEAVY", "env/heavy")
    monkeypatch.setenv("AETHER_MODEL_FAST", "env/fast")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "env/structured")

    assert get_model("REASONING") == "env/reasoning"  # no override -> env
    with user_model_context("user/pick"):
        assert get_model("REASONING") == "user/pick"
        assert get_model("HEAVY") == "user/pick"
        assert get_model("FAST") == "user/pick"
        # STRUCTURED must stay on the tuned env default so a free-text pick can
        # never silently break structured JSON extraction.
        assert get_model("STRUCTURED") == "env/structured"
    # Context exits cleanly -> env again.
    assert get_model("REASONING") == "env/reasoning"


def test_blank_override_is_a_noop(monkeypatch):
    monkeypatch.setenv("AETHER_MODEL_REASONING", "env/reasoning")
    with user_model_context("   "):
        assert get_model("REASONING") == "env/reasoning"
    with user_model_context(None):
        assert get_model("REASONING") == "env/reasoning"


def test_openrouter_catalog_ids_route_to_openrouter_not_direct_anthropic():
    """Billing-separation fix (adversarial-review FAIL): OpenRouter namespaces
    every model as ``vendor/model`` and bills them itself — so an
    ``anthropic/claude-…`` id picked from the OpenRouter catalog MUST route to
    OpenRouter, NOT the direct-Anthropic account. Only a BARE ``claude-…`` native
    id routes to direct Anthropic."""
    # Bare native ids -> direct anthropic (unchanged).
    assert resolve_provider("claude-opus-4-8") == "anthropic"
    assert resolve_provider("claude-sonnet-4-6") == "anthropic"
    # Any vendor/model (slashed) id -> openrouter, INCLUDING anthropic/* .
    assert resolve_provider("anthropic/claude-opus-4.8") == "openrouter"
    assert resolve_provider("anthropic/claude-sonnet-4.6") == "openrouter"
    assert resolve_provider("openai/gpt-5.6-sol") == "openrouter"
    assert resolve_provider("deepseek/deepseek-v4-pro") == "openrouter"
    # End-to-end through the override context.
    with user_model_context("anthropic/claude-opus-4.8"):
        assert resolve_provider(get_model("REASONING")) == "openrouter"
    with user_model_context("claude-opus-4-8"):
        assert resolve_provider(get_model("REASONING")) == "anthropic"


def test_static_anthropic_models_are_priced_not_defaulted():
    """Spend-cap fix (adversarial-review FAIL): a premium anthropic pick from the
    static catalog must be priced at its REAL rate, not the flat default (which
    was ~15-37x under → spend-cap bypass)."""
    from app.routers.agents import _DEFAULT_PRICE, _price_for

    # claude-opus-4-8 static price $15/M in, $75/M out -> $0.015/$0.075 per 1K.
    assert _price_for("claude-opus-4-8") == pytest.approx((0.015, 0.075))
    assert _price_for("claude-opus-4-8") != _DEFAULT_PRICE


# ---------------------------------------------------------------------------
# Catalog curation + budget tiering
# ---------------------------------------------------------------------------


def test_budget_tier_buckets():
    assert _model_budget_tier(0) == "free"
    assert _model_budget_tier(0.0000004) == "budget"
    assert _model_budget_tier(0.000002) == "standard"
    assert _model_budget_tier(0.00001) == "premium"


def test_curation_projects_prices_skips_sentinels_and_sorts():
    raw = [
        {"id": "a/premium", "name": "Prem", "pricing": {"prompt": "0.00001", "completion": "0.00003"}, "context_length": 2000, "reasoning": True},
        {"id": "b/free", "name": "Free", "pricing": {"prompt": "0", "completion": "0"}, "context_length": 1000},
        {"id": "c/auto", "pricing": {"prompt": "-1", "completion": "-1"}},  # dynamic -> skipped
        {"id": "d/budget", "name": "Bud", "pricing": {"prompt": "0.0000002", "completion": "0.0000004"}, "context_length": 500},
        {"pricing": {"prompt": "0"}},  # no id -> skipped
    ]
    out = _curate_openrouter_models(raw)
    ids = [m["id"] for m in out]
    assert "c/auto" not in ids  # negative sentinel skipped
    assert len(out) == 3
    # sorted free -> budget -> ... -> premium
    assert ids == ["b/free", "d/budget", "a/premium"]
    prem = next(m for m in out if m["id"] == "a/premium")
    assert prem["tier"] == "premium"
    assert prem["promptPerM"] == pytest.approx(10.0)  # 0.00001 * 1e6
    assert prem["completionPerM"] == pytest.approx(30.0)
    assert prem["reasoning"] is True


# ---------------------------------------------------------------------------
# list_provider_models: static anthropic, honest errors, openrouter fetch+cache
# ---------------------------------------------------------------------------


def test_anthropic_returns_static_curated_list():
    models = llm_client.list_provider_models("anthropic")
    assert models and all("claude" in m["id"] for m in models)
    assert {m["tier"] for m in models} <= {"free", "budget", "standard", "premium"}


def test_unknown_provider_raises_honest_error():
    with pytest.raises(ModelCatalogError):
        llm_client.list_provider_models("groq")


def test_openrouter_no_credential_raises_not_fabricates(monkeypatch):
    llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)
    monkeypatch.setattr(llm_client, "resolve_user_credential", lambda *a, **k: None)
    monkeypatch.setattr(llm_client, "resolve_credential", lambda *a, **k: None)
    with pytest.raises(ModelCatalogError):
        llm_client.list_provider_models("openrouter", user_id="u1")


def test_openrouter_fetches_curates_and_caches(monkeypatch):
    llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)

    class _Cred:
        secret = "sk-test"
        base_url = "https://openrouter.ai/api/v1"

    monkeypatch.setattr(llm_client, "resolve_user_credential", lambda *a, **k: _Cred())

    calls = {"n": 0}

    class _Resp:
        status_code = 200

        def json(self):
            return {"data": [
                {"id": "x/free", "name": "X", "pricing": {"prompt": "0", "completion": "0"}, "context_length": 1000},
                {"id": "y/prem", "name": "Y", "pricing": {"prompt": "0.00001", "completion": "0.00002"}, "context_length": 2000},
            ]}

    def _fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        assert url.endswith("/models")
        assert headers["Authorization"] == "Bearer sk-test"
        return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "get", _fake_get)

    first = llm_client.list_provider_models("openrouter", user_id="u1")
    assert [m["id"] for m in first] == ["x/free", "y/prem"]
    assert calls["n"] == 1
    # second call within TTL -> served from cache, no new fetch
    second = llm_client.list_provider_models("openrouter", user_id="u1")
    assert second == first
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# HTTP endpoint + end-to-end "a run uses the user's chosen model"
# ---------------------------------------------------------------------------


def test_models_endpoint_returns_curated_catalog(client, auth_headers, monkeypatch):
    # The endpoint does `from app.services.llm_client import list_provider_models`
    # at call time, so patching it on that module is what the route resolves.
    monkeypatch.setattr(
        "app.services.llm_client.list_provider_models",
        lambda provider, user_id, **k: [
            {"id": "z/cheap", "name": "Z", "promptPerM": 0.1, "completionPerM": 0.2,
             "contextLength": 8000, "tier": "budget", "reasoning": False},
        ],
    )
    r = client.get("/agents/providers/openrouter/models", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "openrouter"
    assert body["count"] == 1
    assert body["models"][0]["id"] == "z/cheap"


def test_models_endpoint_honest_400_when_no_catalog(client, auth_headers, monkeypatch):
    def _boom(provider, user_id, **k):
        raise ModelCatalogError("Add an OpenRouter API key to browse models.")

    monkeypatch.setattr("app.services.llm_client.list_provider_models", _boom)
    r = client.get("/agents/providers/openrouter/models", headers=auth_headers)
    assert r.status_code == 400
    assert "OpenRouter API key" in r.json()["detail"]


def test_run_uses_user_chosen_model_end_to_end(client, auth_headers, monkeypatch):
    """The keystone: a stored per-agent model choice is READ and threaded so the
    deep LLM path's get_model('REASONING') returns THAT model during the run."""
    monkeypatch.setenv("AETHER_MODEL_REASONING", "env/default-model")

    # User picks a model for the coverLetter agent (the dormant store, now live).
    put = client.put(
        "/agents/config/coverLetter",
        json={"model": "user/chosen-model"}, headers=auth_headers,
    )
    assert put.status_code == 200, put.text

    from app.routers.agents import _record_run

    # A metered coverLetter run whose body records what get_model('REASONING')
    # resolves to — this is exactly what the real cover agent calls.
    def _capture():
        return {"resolved_model": get_model("REASONING")}

    user_id = client.get("/auth/me", headers=auth_headers).json()["id"]
    out = _record_run(user_id, "coverLetter", {}, _capture)
    assert out["resolved_model"] == "user/chosen-model", out


def test_model_for_agent_reflects_override_for_costing():
    """The costing model MUST be the one that actually ran: the override for
    generation tiers, the env default for STRUCTURED."""
    from app.routers.agents import _model_for_agent

    # coverLetter = REASONING -> override reflected
    assert _model_for_agent("coverLetter", override="x/chosen") == "x/chosen"
    # storyExtractor = STRUCTURED -> override NOT reflected (env default)
    assert _model_for_agent("storyExtractor", override="x/chosen") != "x/chosen"
    # deterministic agent -> None regardless
    assert _model_for_agent("scout", override="x/chosen") is None


def test_price_uses_cached_catalog_for_chosen_model(monkeypatch):
    """A user-chosen model absent from the static table is priced from the live
    catalog cache (budget accuracy), not the flat default."""
    from app.routers.agents import _DEFAULT_PRICE, _price_for

    llm_client._MODEL_CATALOG_CACHE["openrouter"] = (
        1.0,
        [{"id": "vendor/cheap", "promptPerM": 0.5, "completionPerM": 1.0}],
    )
    try:
        # $0.5/M in -> $0.0005/1K; $1.0/M out -> $0.001/1K
        assert _price_for("vendor/cheap") == pytest.approx((0.0005, 0.001))
        # a model not in the static table AND not cached -> bounded default
        assert _price_for("vendor/totally-unknown") == _DEFAULT_PRICE
    finally:
        llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)


def test_phantom_seeded_default_is_ignored(client, auth_headers):
    """SAFETY: a stored model EQUAL to the agent's seeded ``recommended`` default
    (``claude-sonnet-4``) is a write-only phantom, NOT a choice — it must be
    ignored so it can't silently route runs to the (expired) anthropic path. A
    value that DIFFERS is a real selection and IS honoured."""
    from app.routers.agents import _user_model_override

    uid = client.get("/auth/me", headers=auth_headers).json()["id"]
    client.put(
        "/agents/config/coverLetter",
        json={"model": "claude-sonnet-4"}, headers=auth_headers,  # == default seed
    )
    assert _user_model_override(uid, "coverLetter") is None
    client.put(
        "/agents/config/coverLetter",
        json={"model": "moonshotai/kimi-k2.5"}, headers=auth_headers,  # real change
    )
    assert _user_model_override(uid, "coverLetter") == "moonshotai/kimi-k2.5"


def test_backend_to_ui_key_namespace_mapping(client, auth_headers):
    """backend ``tailor`` is stored under UI key ``resumeTailoring`` — the
    override must bridge the two namespaces."""
    from app.routers.agents import _user_model_override

    uid = client.get("/auth/me", headers=auth_headers).json()["id"]
    client.put(
        "/agents/config/resumeTailoring",
        json={"model": "x/tailor-pick"}, headers=auth_headers,
    )
    assert _user_model_override(uid, "tailor") == "x/tailor-pick"


def test_provider_default_used_when_no_per_agent_choice(client, auth_headers):
    """With no deliberate per-agent model, the user's provider-level default
    (their global choice) applies."""
    from app.routers.agents import _user_model_override

    uid = client.get("/auth/me", headers=auth_headers).json()["id"]
    client.put(
        "/agents/providers/openrouter",
        json={"model": "x/provider-default"}, headers=auth_headers,
    )
    assert _user_model_override(uid, "coverLetter") == "x/provider-default"


def test_provider_default_scoped_to_openrouter_only(client, auth_headers):
    """FIX (adversarial-review): a model saved on a NON-openrouter provider card
    (openai/gemini/groq legacy <select>) must NOT silently become a run override —
    only the openrouter provider default (set by the ModelPicker) counts."""
    from app.routers.agents import _user_model_override

    uid = client.get("/auth/me", headers=auth_headers).json()["id"]
    # A historic click on the OpenAI card's model select — must be ignored.
    client.put(
        "/agents/providers/openai",
        json={"model": "gpt-4o"}, headers=auth_headers,
    )
    assert _user_model_override(uid, "coverLetter") is None
    # The openrouter default IS honoured.
    client.put(
        "/agents/providers/openrouter",
        json={"model": "vendor/real-choice"}, headers=auth_headers,
    )
    assert _user_model_override(uid, "coverLetter") == "vendor/real-choice"
