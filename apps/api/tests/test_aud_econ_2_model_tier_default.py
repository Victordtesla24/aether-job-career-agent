"""AUD-ECON-2 (RUN-20260818T0223Z) — decision memo:
``docs/delivery/evidence/RUN-20260818T0223Z/05-decision-memos/AUD-ECON-2.md``.

DECISION (binding, no repricing this run): align the configured default model
tier for the tailoring/letter path with measured serving reality, not a
repriced product. Today ``_LLM_TIER_BY_BACKEND`` puts ``tailor``/``coverLetter``
on the REASONING tier and the code (+ prod .env) default pins
``AETHER_MODEL_REASONING=claude-opus-4-8`` — but EVERY real tailor run in prod
(n=5) was actually served by ``claude-haiku-4-5-20251001`` via the existing
one-retry fallback chain (``FALLBACK_MODEL``), never the configured Opus tier
(AUD-ECON-2 scout, 01-scout-reproduction.log (a)). At the CONFIGURED Opus-tier
price the same measured token volumes would cost ~$1.70/application — a figure
that blows the Free plan's spend cap on a SINGLE tailoring run and leaves every
paid plan delivering only 16-20% of its advertised runsPerMonth once the spend
cap (not the run quota) binds first. The fix makes the REASONING tier's
DEFAULT (env-unset) resolve to the model serving reality already lands on —
the SAME id already used for the FAST/LIGHT tiers and the D-0014 fallback
(``claude-haiku-4-5``) — while preserving the env-override mechanism (an Owner
can still re-pin Opus by setting ``AETHER_MODEL_REASONING`` with no code
change) and the served-model disclosure, untouched.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Default tier resolution for the affected backends (tailor/coverLetter,
#    both REASONING) now matches measured serving reality.
# ---------------------------------------------------------------------------


def test_reasoning_tier_default_matches_measured_serving_reality(monkeypatch):
    """FAILS NOW: the env-unset REASONING default is ``claude-opus-4-8`` — the
    model NONE of the 5 real prod tailor runs were actually served by. The new
    default must be the model serving reality already lands on."""
    from app.services.llm_client import get_model

    monkeypatch.delenv("AETHER_MODEL_REASONING", raising=False)
    assert get_model("REASONING") == "claude-haiku-4-5"


def test_reasoning_default_is_still_a_bare_anthropic_id(monkeypatch):
    """The OWNER DIRECTIVE (MODEL-DEFAULT, 2026-08-14) invariant this
    supersedes only the PRICE TIER of, not the provider rule, must still hold:
    the system default is never OpenRouter, always a bare ``claude-*`` id
    that routes to the operator's Anthropic subscription."""
    from app.services.llm_client import get_model, resolve_provider

    monkeypatch.delenv("AETHER_MODEL_REASONING", raising=False)
    model = get_model("REASONING")
    assert "/" not in model
    assert resolve_provider(model) == "anthropic"


def test_reasoning_default_is_now_the_same_id_as_fast_and_fallback(monkeypatch):
    """The new default is not a NEW price point invented for this fix — it is
    literally the same id the FAST/LIGHT tiers and the D-0014 fallback already
    use, i.e. the tier the fallback chain already lands on becomes the
    configured default (the decision memo's exact framing)."""
    from app.services.llm_client import FALLBACK_MODEL, get_model

    monkeypatch.delenv("AETHER_MODEL_REASONING", raising=False)
    monkeypatch.delenv("AETHER_MODEL_FAST", raising=False)
    assert get_model("REASONING") == get_model("FAST") == FALLBACK_MODEL


def test_heavy_tier_default_is_unaffected():
    """Scope pin: the decision is about the REASONING tier specifically (the
    tier tailor/coverLetter actually run on) — HEAVY is unused by any current
    backend (``_LLM_TIER_BY_BACKEND`` maps nothing to it) and carries no
    measured serving-reality evidence in the AUD-ECON-2 scout log, so it is
    left exactly as configured."""
    from app.services.llm_client import _DEFAULT_MODEL_BY_TIER

    assert _DEFAULT_MODEL_BY_TIER["HEAVY"] == "claude-opus-4-8"


def test_structured_and_fast_light_tiers_are_unaffected(monkeypatch):
    """Scope pin: only REASONING moves. STRUCTURED/FAST/LIGHT carry no
    AUD-ECON-2 finding and must resolve exactly as before."""
    from app.services.llm_client import get_model

    for var in ("AETHER_MODEL_STRUCTURED", "AETHER_MODEL_FAST", "AETHER_MODEL_LIGHT"):
        monkeypatch.delenv(var, raising=False)
    assert get_model("STRUCTURED") == "claude-sonnet-4-6"
    assert get_model("FAST") == "claude-haiku-4-5"
    assert get_model("LIGHT") == "claude-haiku-4-5"


# ---------------------------------------------------------------------------
# 2. The env-override mechanism still wins — an Owner can re-pin Opus by env,
#    with no code change (decision memo §5, "reversal cost").
# ---------------------------------------------------------------------------


def test_env_override_still_repins_the_reasoning_tier_to_opus(monkeypatch):
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-opus-4-8")
    from app.services.llm_client import get_model

    assert get_model("REASONING") == "claude-opus-4-8"


def test_env_override_can_pin_any_bare_claude_id(monkeypatch):
    """The override mechanism is generic — not special-cased to opus-4-8."""
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-sonnet-4-6")
    from app.services.llm_client import get_model

    assert get_model("REASONING") == "claude-sonnet-4-6"


def test_per_agent_user_override_still_wins_over_the_tier_default(monkeypatch):
    """The EXISTING per-agent slash-model picker precedence is untouched by
    this default-value change — a user's own choice still wins."""
    from app.services.llm_client import get_model, user_model_context

    monkeypatch.delenv("AETHER_MODEL_REASONING", raising=False)
    with user_model_context("claude-opus-4-8"):
        assert get_model("REASONING") == "claude-opus-4-8"


# ---------------------------------------------------------------------------
# 3. .env.example documents the SAME default the code now ships (repo
#    convention per the existing comment: "These mirror
#    llm_client._DEFAULT_MODEL_BY_TIER so behaviour is Anthropic-first even
#    when a var is unset").
# ---------------------------------------------------------------------------


def test_env_example_documents_the_new_reasoning_default():
    from pathlib import Path

    from app.services.llm_client import _DEFAULT_MODEL_BY_TIER

    repo_root = Path(__file__).resolve().parents[3]
    env_example = (repo_root / ".env.example").read_text()
    expected = f'AETHER_MODEL_REASONING={_DEFAULT_MODEL_BY_TIER["REASONING"]}'
    assert expected in env_example, (
        f".env.example must document the code default verbatim — expected a "
        f"line {expected!r}"
    )
