"""U-AGI MODEL-DEFAULT — the system default is the operator's Anthropic Pro
subscription, NEVER OpenRouter (OWNER DIRECTIVE, 2026-08-14).

Owner directive, verbatim intent: "do not use openrouter api key other than the
22 ai agents; the system default must be anthropic pro subs quota (token saved
in env)." Ground truth before this slice: every ``AETHER_MODEL_<TIER>`` default
and the hardcoded ``FALLBACK_MODEL`` pointed at OpenRouter (deepseek/qwen/nvidia)
— so OpenRouter was the SILENT system default. This slice flips the defaults to
bare ``claude-*`` ids the operator's Anthropic subscription serves, and
RECONCILES P1-A F7/F8 (``test_uagi_p1a_credential_separation.py``): user-content
generation MAY draw on the operator's Anthropic subscription — it is the
intended default — bounded per-user by the EXISTING quota + spend cap, not by a
credential wall.

Four pins, one decision:
  1. every tier default (env-unset) is a bare ``claude-*`` that routes to the
     ``anthropic`` subscription — no path silently defaults to OpenRouter;
  2. OpenRouter is reached ONLY via an explicit per-agent slash-model pick;
  3. F8 softened — a bare ``claude-*`` user-content run with no user credential
     of its own resolves the operator subscription (metered), not ``None``;
  4. a runaway user-content run on that subscription is STILL 429-capped.

No new provider path is introduced; ``resolve_provider`` semantics are untouched.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db import get_connection
from app.repositories.billing import UsageQuotaRepository, ensure_user_billing
from app.repositories.user_provider_credential import UserProviderCredentialRepository
from app.routers.agents import _record_run
from app.services import credential_vault as vault
from app.services.llm_client import (
    FALLBACK_MODEL,
    LLMClient,
    get_fallback_model,
    get_model,
    resolve_credential,
    resolve_provider,
    resolve_user_credential,
    user_model_context,
)

# The six tier vars ``get_model`` reads, plus the D-0014 fallback var.
_TIER_VARS = ("REASONING", "HEAVY", "STRUCTURED", "FAST", "LIGHT")
_ALL_MODEL_VARS = tuple(f"AETHER_MODEL_{t}" for t in _TIER_VARS) + (
    "AETHER_MODEL_FALLBACK",
)

#: The scout-recommended tier -> id mapping (MODEL-DEFAULT-SCOUT D1): each id is
#: in the app's static anthropic catalog and proven live on the subscription.
#:
#: AUD-ECON-2 (RUN-20260818T0223Z) SUPERSEDES the REASONING entry below,
#: 2026-08-14's own value at the time this file was written. The provider
#: rule this file pins (bare claude-*, never OpenRouter) is untouched; only
#: the PRICE TIER moved, because measured prod reality showed every real
#: tailor/coverLetter run being served by claude-haiku-4-5 (the fallback
#: chain), never the configured claude-opus-4-8 — see the decision memo
#: (docs/delivery/evidence/RUN-20260818T0223Z/05-decision-memos/
#: AUD-ECON-2.md) and llm_client._DEFAULT_MODEL_BY_TIER's own comment.
_EXPECTED_TIER_DEFAULT = {
    "REASONING": "claude-haiku-4-5",
    "HEAVY": "claude-opus-4-8",
    "STRUCTURED": "claude-sonnet-4-6",
    "FAST": "claude-haiku-4-5",
    "LIGHT": "claude-haiku-4-5",
}


@pytest.fixture()
def _no_model_env(monkeypatch):
    """Env-unset: the CODE defaults must be correct on their own (the served
    ``.env`` flip is a documented config edit applied at land time)."""
    for var in _ALL_MODEL_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def _no_env_credentials(monkeypatch):
    for var in (
        "ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL",
        "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "ABACUS_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def _vault_key(monkeypatch):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


def _operator_row(monkeypatch, *, auth_mode: str, secret: str) -> None:
    """Install the deployment-wide (operator) ProviderCredential row."""
    monkeypatch.setattr(
        "app.repositories.provider_credential.ProviderCredentialRepository.get_secret",
        lambda self, provider: (
            {"secret": secret, "authMode": auth_mode, "baseUrl": None}
            if provider == "anthropic"
            else None
        ),
    )


# ---------------------------------------------------------------------------
# 1. Every tier default is a bare claude-* that routes to the anthropic sub.
# ---------------------------------------------------------------------------


def test_fallback_model_constant_is_a_bare_anthropic_id():
    """The D-0014 last-resort retry is now the operator's Anthropic subscription
    (a bare ``claude-*``), never a silent OpenRouter free model."""
    assert "/" not in FALLBACK_MODEL
    assert FALLBACK_MODEL.startswith("claude-")
    assert resolve_provider(FALLBACK_MODEL) == "anthropic"


def test_every_tier_default_routes_to_anthropic(_no_model_env):
    for tier in _TIER_VARS:
        model = get_model(tier)
        assert "/" not in model, (tier, model)
        assert resolve_provider(model) == "anthropic", (tier, model)


def test_no_tier_silently_defaults_to_openrouter(_no_model_env):
    for tier in _TIER_VARS:
        assert resolve_provider(get_model(tier)) != "openrouter", tier


def test_tier_defaults_match_the_scout_recommended_ids(_no_model_env):
    for tier, expected in _EXPECTED_TIER_DEFAULT.items():
        assert get_model(tier) == expected, tier


def test_get_fallback_model_default_routes_to_anthropic(_no_model_env):
    fb = get_fallback_model()
    assert "/" not in fb
    assert resolve_provider(fb) == "anthropic"


# ---------------------------------------------------------------------------
# 2. OpenRouter is reached ONLY via an explicit per-agent slash-model pick.
# ---------------------------------------------------------------------------


def test_a_slash_model_pick_still_routes_openrouter(_no_model_env):
    """The 22-agent per-agent picker (slash id) is the ONE way to OpenRouter —
    binding scope §2. resolve_provider is untouched."""
    with user_model_context("deepseek/deepseek-v4-pro"):
        assert resolve_provider(get_model("REASONING")) == "openrouter"
    # A bare claude-* pick still routes to the anthropic subscription.
    with user_model_context("claude-opus-4-8"):
        assert resolve_provider(get_model("REASONING")) == "anthropic"


def test_the_system_default_retry_chain_stays_on_anthropic(_no_model_env):
    """A system-default (un-chosen) run keeps its one-retry resilience, and both
    hops are the operator's Anthropic subscription — never a cross-provider
    substitution."""
    chain = LLMClient._model_chain("claude-opus-4-8")
    assert chain == ["claude-opus-4-8", "claude-haiku-4-5"]
    assert all(resolve_provider(m) == "anthropic" for m in chain)


# ---------------------------------------------------------------------------
# 3. F8 softened — user-content resolves the operator subscription (metered).
# ---------------------------------------------------------------------------


def test_user_content_may_use_the_operator_subscription(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    """RECONCILES P1-A F8: the owner's bare ``claude-*`` tailoring run, with no
    Anthropic credential of its own, resolves the operator's subscription — the
    intended default — instead of the old honest-``None`` that broke it."""
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")

    res = resolve_user_credential("anthropic", test_user_id, "tailor")
    assert res is not None, "user-content still walled off the operator subscription"
    assert res.auth_mode == "oauth_token"
    assert res.secret == "sk-ant-oat01-OPERATOR"
    assert res.source == "database"


def test_user_own_credential_still_wins_over_the_operator_subscription(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    """Softening F8 does not change precedence: a user's OWN key is still used
    ahead of the operator subscription."""
    UserProviderCredentialRepository().upsert(
        test_user_id, "anthropic", auth_mode="api_key", secret="sk-ant-api-USER-OWN"
    )
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")

    res = resolve_user_credential("anthropic", test_user_id, "tailor")
    assert res is not None and res.secret == "sk-ant-api-USER-OWN"
    assert res.source == "user_credential"


def test_the_operator_subscription_never_crosses_to_an_openrouter_run(
    client, auth_headers, test_user_id, monkeypatch, _vault_key, _no_env_credentials
):
    """No-cross-provider invariant survives the softened wall: a slash-model
    (OpenRouter) run with no OpenRouter credential is an honest ``None`` — the
    anthropic subscription is NEVER handed to it."""
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")

    assert resolve_user_credential("openrouter", test_user_id, "tailor") is None


def test_resolve_credential_retains_the_wall_off_capability(
    monkeypatch, _no_env_credentials
):
    """The ``allow_operator_subscription`` mechanism is RETAINED as a general
    capability of ``resolve_credential`` (a deployment can still scope the
    subscription off); the user-content path just no longer engages it, because
    per-user metering now bounds subscription use."""
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")
    assert (
        resolve_credential("anthropic", allow_operator_subscription=False) is None
    )
    # Default (allow) resolves the subscription, as user-content now does.
    got = resolve_credential("anthropic")
    assert got is not None and got.auth_mode == "oauth_token"


# ---------------------------------------------------------------------------
# 4. A runaway user-content run on the subscription is STILL 429-capped.
# ---------------------------------------------------------------------------


def _tailor_stub():
    return {"resume_id": "r1", "changes": [], "rejected": []}


def test_a_runaway_is_still_capped_by_the_per_user_run_quota(
    client, auth_headers, test_user_id, monkeypatch, _no_model_env
):
    """Even with the operator subscription now resolvable for user-content, the
    per-user run-count quota still bounds a runaway — the credential wall is
    replaced by metering, not removed."""
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-opus-4-8")
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")
    repo = UsageQuotaRepository()
    ensure_user_billing(test_user_id)
    for _ in range(5):  # Free tier = 5 runs
        repo.reserve(test_user_id)

    with pytest.raises(HTTPException) as ei:
        _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    assert ei.value.status_code == 429
    assert ei.value.detail["code"] == "quota_exceeded"


def test_a_runaway_is_still_capped_by_the_per_user_spend_cap(
    client, auth_headers, test_user_id, monkeypatch, _no_model_env
):
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-opus-4-8")
    _operator_row(monkeypatch, auth_mode="oauth_token", secret="sk-ant-oat01-OPERATOR")
    ensure_user_billing(test_user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "UsageQuota" SET "spendUsedUsd" = "spendCapUsd" '
                'WHERE "userId" = %s',
                (test_user_id,),
            )
        conn.commit()

    with pytest.raises(HTTPException) as ei:
        _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    assert ei.value.status_code == 429
    assert ei.value.detail["code"] == "spend_cap_exceeded"
    # The reserved run was refunded — a capped run is never billed.
    assert int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"]) == 0
