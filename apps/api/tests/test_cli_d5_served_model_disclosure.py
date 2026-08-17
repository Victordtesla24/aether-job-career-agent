"""CLI-D5 (audit wf_9a87f76f-eaa, Track E) — every run that actually reached an
LLM must DISCLOSE, in its own output, the model that really served it.

Audit finding D5: "auto"/default chains silently serve cheap/free OpenRouter
models (deepseek/qwen/nemotron) while the config and plan copy advertise
Claude. The costing path already OBSERVES the true served id per run
(``llm_client.get_last_served_model()`` — the provider's own ``model`` field,
the same truth the billing audit trail is built on), but the run OUTPUT — the
one surface ``GET /agents/runs`` and the FE actually read — recorded
``servedModel`` ONLY when the served id happened to differ from the
config-derived intent (ML-W14 substitution bookkeeping). A run served by
exactly the configured cheap model disclosed nothing, and NO run output named
the billing provider that served it.

D5 contract (Architect decision, Track E):

1. Every AgentRun whose work made a real LLM call carries additive
   ``servedModel`` + ``servedProvider`` keys in its output — gated on the
   provider-published observation itself, and resolved to a provider with the
   SAME pure function the billing audit uses (``resolve_provider``).
2. The existing requestedModel-vs-servedModel substitution honesty is kept:
   when a different model served than the one configured, ``output["model"]``
   is the served id, never the configured lie.
3. A run that made NO LLM call carries neither key — nothing is fabricated.
"""
from __future__ import annotations

import json

import pytest

from app.repositories.agent_run import AgentRunRepository
from app.repositories.billing import ensure_user_billing
from app.routers.agents import _record_run

#: The cheap OpenRouter model the default env chain actually routes to.
_CHEAP_PRIMARY = "deepseek/deepseek-v4-pro"
_CHEAP_FALLBACK = "deepseek/deepseek-v4-flash"
#: What the plan copy advertises: a premium OpenRouter-catalog model, so it
#: bills through OpenRouter and needs no Anthropic credential here.
#:
#: MODEL-SUB-QUOTA (OWNER DIRECTIVE 2026-08-17): this was
#: ``anthropic/claude-sonnet-4.5``. A Claude id in ANY spelling is now served by
#: the operator's Anthropic subscription over the native Messages API, so it
#: cannot stand in for "an advertised model the OpenRouter chain serves
#: something else instead of". The requested-vs-served disclosure this file
#: pins is unchanged; the sibling test below covers the bare-claude/anthropic
#: provider half.
_ADVERTISED_PREMIUM = "x-ai/grok-4"
_FREE_SERVED = "qwen/qwen3-235b-a22b:free"


class _Resp:
    """Minimal httpx.Response stand-in (status_code / text / json())."""

    def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _ok(content: str, served_model: str) -> _Resp:
    """A live-shaped OpenAI-compatible 200 whose top-level ``model`` field
    mirrors the real provider bodies (``_publish_served_model``'s truth)."""
    return _Resp(
        200, content, {"choices": [{"message": {"content": content}}], "model": served_model}
    )


def _install_transport(monkeypatch, responder):
    """Route every live call through ``responder(asked_model_id)``."""
    import httpx

    seen: list[str] = []

    def _post(url, **kwargs):  # noqa: ANN001 — httpx.post signature
        model = kwargs["json"]["model"]
        seen.append(model)
        return responder(model)

    monkeypatch.setattr(httpx, "post", _post)
    return seen


@pytest.fixture()
def openrouter_env(monkeypatch):
    """Env exactly like production: cheap primary + fallback, OpenRouter key."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.delenv("AETHER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ABACUS_API_KEY", raising=False)
    monkeypatch.setenv("AETHER_MODEL_REASONING", _CHEAP_PRIMARY)
    monkeypatch.setenv("AETHER_MODEL_FALLBACK", _CHEAP_FALLBACK)
    return None


def _run_cover_letter(tmp_path, user_id: str) -> dict:
    """A metered coverLetter run whose body makes a REAL client call through
    the mocked transport — the exact production shape (``_record_run`` →
    ``_execute_reserved_run`` → agent → ``LLMClient``), mirroring
    test_ml_w14_served_model_billing.py."""
    from app.services.llm_client import LLMClient

    def _fn() -> dict:
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        return {"content": llm.complete("cover_letter", "sys", "usr")}

    return _record_run(user_id, "coverLetter", {}, _fn)


def _stored_cover_output(user_id: str) -> dict:
    stored = AgentRunRepository().last_run_by_agent(user_id)["coverLetter"]
    output = stored["output"]
    if isinstance(output, str):  # driver-dependent JSON handling
        output = json.loads(output)
    return output


# ---------------------------------------------------------------------------
# 1. THE DEFECT — a run served by exactly the configured model disclosed
#    nothing at all.
# ---------------------------------------------------------------------------


def test_run_served_by_the_configured_model_still_discloses_it(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """FAILS NOW: when the served id equals the config-derived intent, the
    output carries no ``servedModel`` and no ``servedProvider`` — the exact
    silence D5 flags: config/plans can advertise anything while the run's own
    record never names the cheap model that actually did the work."""
    ensure_user_billing(test_user_id)
    _install_transport(monkeypatch, lambda m: _ok("Dear Hiring Manager, ...", m))

    out = _run_cover_letter(tmp_path, test_user_id)

    assert out["servedModel"] == _CHEAP_PRIMARY, (
        "the run output must always name the model that ACTUALLY served it"
    )
    assert out["servedProvider"] == "openrouter", (
        "the disclosure must name the billing provider too, resolved with the "
        "same pure function the billing audit uses"
    )
    # No substitution happened, so the intent needs no separate key.
    assert "requestedModel" not in out
    assert out["model"] == _CHEAP_PRIMARY


def test_the_disclosure_is_persisted_on_the_run_row_the_ui_reads(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """The owner-facing 'Recent runs' table and ``GET /agents/runs`` read the
    persisted ``AgentRun.output`` — the disclosure must be on the row, not
    only the HTTP response."""
    ensure_user_billing(test_user_id)
    _install_transport(monkeypatch, lambda m: _ok("Dear Hiring Manager, ...", m))

    out = _run_cover_letter(tmp_path, test_user_id)
    stored_output = _stored_cover_output(test_user_id)

    assert stored_output["servedModel"] == _CHEAP_PRIMARY
    assert stored_output["servedProvider"] == "openrouter"
    assert out["run_id"] == AgentRunRepository().last_run_by_agent(test_user_id)[
        "coverLetter"
    ]["id"]


# ---------------------------------------------------------------------------
# 2. The audit's headline lie shape: config advertises Claude, a free/cheap
#    model serves — requested vs served must be distinguished honestly.
# ---------------------------------------------------------------------------


def test_advertised_premium_served_free_model_distinguishes_requested_vs_served(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """The configured (advertised) model is a Claude id; the provider actually
    serves a free qwen model. The output must carry the intent as
    ``requestedModel``, the truth as ``servedModel`` (+ provider), and
    ``model`` must be the served id — never the configured lie."""
    ensure_user_billing(test_user_id)
    monkeypatch.setenv("AETHER_MODEL_REASONING", _ADVERTISED_PREMIUM)
    _install_transport(monkeypatch, lambda m: _ok("Dear Hiring Manager, ...", _FREE_SERVED))

    out = _run_cover_letter(tmp_path, test_user_id)

    assert out["requestedModel"] == _ADVERTISED_PREMIUM
    assert out["servedModel"] == _FREE_SERVED
    assert out["servedProvider"] == "openrouter"
    assert out["model"] == _FREE_SERVED, (
        "output['model'] must never report the configured model when a "
        "different model actually served"
    )


def test_a_bare_claude_serving_reports_the_anthropic_provider(
    client, auth_headers, test_user_id, monkeypatch
):
    """Provider resolution half: a direct-Anthropic serving (bare claude-* id)
    must disclose ``servedProvider == 'anthropic'`` — same observation seam as
    test_uagi_p1a_r5_fallback_fields.py's controlled-observation harness."""
    from app.routers import agents as agents_mod

    served = "claude-haiku-4-5"
    monkeypatch.setattr(agents_mod, "get_last_served_model", lambda: served)
    monkeypatch.setattr(agents_mod, "get_last_fallback_reason", lambda: None)
    monkeypatch.setattr(
        agents_mod, "_model_for_agent", lambda name, override=None: served
    )
    out = agents_mod._record_run(
        test_user_id, "storyExtractor", {}, lambda: {"stories": []}
    )
    assert out["servedModel"] == served
    assert out["servedProvider"] == "anthropic"
    assert "requestedModel" not in out


# ---------------------------------------------------------------------------
# 3. Honesty pins — no LLM call means NO disclosure keys (never fabricated).
#    These must pass BEFORE and AFTER the fix.
# ---------------------------------------------------------------------------


def test_a_metered_run_that_made_no_llm_call_carries_no_disclosure(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """A coverLetter run whose callable never touches the model observes
    nothing — nothing may be disclosed, because nothing served."""
    ensure_user_billing(test_user_id)
    out = _record_run(test_user_id, "coverLetter", {}, lambda: {"content": "x"})
    assert "servedModel" not in out
    assert "servedProvider" not in out


def test_a_deterministic_agent_run_carries_no_disclosure(
    monkeypatch, openrouter_env, client, auth_headers, test_user_id
):
    """Deterministic agents (scout) make no LLM calls at all."""
    out = _record_run(test_user_id, "scout", {}, lambda: {"jobs": 0})
    assert out["model"] is None
    assert "servedModel" not in out
    assert "servedProvider" not in out


# ---------------------------------------------------------------------------
# 4. The guard-rejection degrade path is a completed run that made real LLM
#    calls — it must disclose too, even without a substitution.
# ---------------------------------------------------------------------------


def test_guard_degraded_run_discloses_the_served_model_without_substitution(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """FAILS NOW: the ``except (FabricationError, StructuralError)`` branch
    records ``servedModel`` only when the served id differs from the intent.
    A degraded run served by exactly the configured model is still a run whose
    work used an LLM — it must disclose what served, with its provider."""
    from app.agents.cover_letter_agent import FabricationError
    from app.services.llm_client import LLMClient

    ensure_user_billing(test_user_id)
    # Intent == served: no substitution, disclosure must still happen.
    monkeypatch.setenv("AETHER_MODEL_REASONING", _CHEAP_PRIMARY)
    _install_transport(
        monkeypatch, lambda m: _ok("Dear Hiring Manager, " + "y" * 400, m)
    )

    def _fn():
        llm = LLMClient(mode="live", fixture_dir=tmp_path)
        llm._call_live(
            "You are a truthful cover-letter writer." * 5,
            "Target role: Staff Engineer at Acme.\n" + "x" * 800,
            model=_CHEAP_PRIMARY,
            temperature=0.0,
        )
        raise FabricationError(["Acme Corp"])

    with pytest.raises(FabricationError):
        _record_run(test_user_id, "coverLetter", {"job_id": "j"}, _fn)

    output = _stored_cover_output(test_user_id)
    assert output.get("coverLetterUnavailable") is True
    assert output["servedModel"] == _CHEAP_PRIMARY
    assert output["servedProvider"] == "openrouter"
    assert "requestedModel" not in output  # no substitution → no intent key
    assert output["model"] == _CHEAP_PRIMARY


def test_guard_degraded_run_with_no_served_call_discloses_nothing(
    monkeypatch, openrouter_env, client, auth_headers, test_user_id
):
    """PIN (passes BEFORE and AFTER): a degrade whose every attempt failed
    before any successful call observed nothing — no disclosure keys."""
    from app.agents.cover_letter_agent import FabricationError

    ensure_user_billing(test_user_id)

    def _raise():
        raise FabricationError(["term"])

    with pytest.raises(FabricationError):
        _record_run(test_user_id, "coverLetter", {"job_id": "j"}, _raise)

    output = _stored_cover_output(test_user_id)
    assert output.get("model") is None
    assert "servedModel" not in output
    assert "servedProvider" not in output
