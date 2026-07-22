"""MODELS-LIVE §7 step 2 — failing tests for 3 Agents-screen findings from the
deep UI test (uat/reports/evidence/models-live/screens/agents/
TESTING-OUTCOME-REPORT.md) that the mocked FIX-1 unit tests missed:

  * ML-agents-001 (BLOCKER) — storyExtraction runs on the STRUCTURED model
    tier, which `_USER_OVERRIDABLE_TIERS` (app/services/llm_client.py)
    deliberately excludes from user override — a pick in its per-agent
    picker silently no-ops at run time. The FE's existing deterministic-lock
    (ML-catalog-008/N2) only checks `agent.recommended === "deterministic"`,
    so a STRUCTURED-tier agent whose `recommended` is a real model id (e.g.
    storyExtraction's `"claude-haiku-4-5-20251001"`) slips through as a
    FUNCTIONAL picker. Intended fix (per the test-authoring brief): the
    backend catalog/config response gains an authoritative per-agent
    `modelOverridable` boolean (never hardcoded agent names in the FE) —
    derived from the agent's backend tier (`_LLM_TIER_BY_BACKEND`) being in
    `_USER_OVERRIDABLE_TIERS`, AND the backend not being deterministic
    (`_DETERMINISTIC_BACKENDS`) / absent (planned).
    This file pins the BACKEND half of that contract (`GET /agents/catalog`
    exposes `modelOverridable`, correct per agent); the FE half (the picker
    actually reading it to lock storyExtraction) is pinned separately in
    apps/web/src/__tests__/agents/ml-agents-refix.test.tsx.

  * ML-agents-002 (HIGH) — after a user saves a per-agent model override via
    `PUT /agents/config/{agentKey}`, `GET /agents/catalog`'s `model` field
    for that agent keeps showing the env-default model, not the saved one.
    Root cause: `agent_catalog()` calls `_model_for_agent(backend)` with NO
    `override` argument (agents.py ~1725) — every other caller
    (`_billing_audit`, `_execute_reserved_run`) correctly threads
    `override=_user_model_override(user_id, backend)`. This is the DISPLAY
    bug the deep UI test found ("save+reload shows default, not the saved
    model") — a mocked FE unit test can't reproduce it because the mock
    controls what `fetchCatalog()` returns; only hitting the real endpoint
    after a real PUT exposes it. The live-repro Playwright spec
    (apps/web/e2e/ml-agents-refix.spec.ts) proves the user-facing symptom;
    this file pins the exact backend contract the fix must satisfy.

  * ML-agents-004 (BLOCKER placeholder) — the Test Run modal's cost/token
    estimate (`POST /agents/test-run`) is a STATIC placeholder: fixed
    2800/1400 estimated input/output tokens times whatever
    `_model_for_agent(backend)` resolves to — which (same root cause as
    ML-agents-002) ignores the user's per-agent override, so two agents with
    DIFFERENT saved models still show an IDENTICAL cost estimate (both
    resolve to the same tier env-default). Intended fix: cost the estimate
    against the model the agent will ACTUALLY run on
    (`_model_for_agent(backend, override=_user_model_override(...))`), or
    honestly report the estimate as unavailable — never a fixed fake number.

ML-agents-003 (OAuth URL) and ML-agents-005 (mobile 390px overflow) are
covered elsewhere (adjudicated separately / apps/web/e2e/ml-agents-refix.spec.ts).

Every test below fails against CURRENT code for the reason documented in its
docstring.
"""
from __future__ import annotations

import pytest

from app.db import get_connection


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    from app.services import credential_vault as vault

    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture(autouse=True)
def _clean_agent_tables():
    """Screen-scoped tables (AgentConfig/AgentProvider) are lazily created and
    not in conftest's TRUNCATE list — drop them after each test and reset the
    router's process-level ready-cache, mirroring test_agents_screen.py."""
    from app.routers import agents as agents_module

    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS "AgentConfig"')
            cur.execute('DROP TABLE IF EXISTS "AgentProvider"')
        conn.commit()
    agents_module._tables_ready = False


def _catalog_by_key(client, auth_headers) -> dict[str, dict]:
    res = client.get("/agents/catalog", headers=auth_headers)
    assert res.status_code == 200, res.text
    return {a["key"]: a for a in res.json()["agents"]}


# ---------------------------------------------------------------------------
# ML-agents-001 — authoritative per-agent `modelOverridable` signal
# ---------------------------------------------------------------------------


def test_catalog_exposes_model_overridable_field(client, auth_headers):
    """GET /agents/catalog must expose a `modelOverridable` boolean on every
    agent so the FE can lock a picker WITHOUT hardcoding agent names.

    FAILS NOW: the catalog response carries no such field at all — the FE's
    only signal today is `recommended === "deterministic"`, which is silent
    about the STRUCTURED tier (see the next test).
    """
    agents = _catalog_by_key(client, auth_headers)
    missing = [k for k, a in agents.items() if "modelOverridable" not in a]
    assert not missing, (
        f"'modelOverridable' is missing from {len(missing)}/{len(agents)} "
        f"catalog agents (e.g. {missing[:5]}) — the backend exposes no "
        "authoritative per-agent override signal for the FE picker to lock on"
    )


def test_story_extraction_structured_tier_is_not_overridable(client, auth_headers):
    """storyExtraction runs on the STRUCTURED tier
    (`_LLM_TIER_BY_BACKEND["storyExtractor"] == "STRUCTURED"`), which
    `_USER_OVERRIDABLE_TIERS` deliberately excludes — a picked model is NEVER
    honoured at run time (`get_model("STRUCTURED")` always falls through to
    the env default; see llm_client.py `_USER_OVERRIDABLE_TIERS` / `get_model`).
    `modelOverridable` must be False for it — the same honest treatment the
    4 fully-deterministic backends already need.

    FAILS NOW: the field does not exist (previous test), so this assertion
    cannot even be evaluated as True — `.get(..., None) is False` is False.
    """
    agents = _catalog_by_key(client, auth_headers)
    story = agents["storyExtraction"]
    assert story["backend"] == "storyExtractor"
    # Sanity: this agent's `recommended` is a REAL model id, not the literal
    # "deterministic" sentinel — proving the OLD `recommended === "deterministic"`
    # signal the FE lock used cannot distinguish it from an overridable agent.
    assert story["recommended"] != "deterministic"
    assert story.get("modelOverridable") is False, (
        f"storyExtraction (STRUCTURED tier, model never read at run time) "
        f"must report modelOverridable=False, got {story.get('modelOverridable')!r}"
    )


@pytest.mark.parametrize(
    "key",
    ["jobDiscovery", "atsOptimization", "matchScoring", "jobMatching",
     "skillGap", "orchestration"],
)
def test_deterministic_backed_agents_are_not_overridable(client, auth_headers, key):
    """Every catalog entry backed by a deterministic backend (scout/fitScorer/
    matcher/supervisor — no LLM call, `_model_for_agent` returns None) must
    also report `modelOverridable=False`. FAILS NOW: field absent."""
    agents = _catalog_by_key(client, auth_headers)
    assert agents[key].get("modelOverridable") is False, (
        f"{key} (deterministic backend {agents[key]['backend']!r}) must "
        f"report modelOverridable=False, got {agents[key].get('modelOverridable')!r}"
    )


@pytest.mark.parametrize("key", ["resumeTailoring", "coverLetter", "emailAgent"])
def test_reasoning_tier_agents_are_overridable(client, auth_headers, key):
    """tailor/coverLetter/emailAgent run on the REASONING tier — IN
    `_USER_OVERRIDABLE_TIERS` — so a per-agent picker IS meaningful for them
    and `modelOverridable` must be True. FAILS NOW: field absent."""
    agents = _catalog_by_key(client, auth_headers)
    assert agents[key].get("modelOverridable") is True, (
        f"{key} (REASONING tier, user-overridable at run time) must report "
        f"modelOverridable=True, got {agents[key].get('modelOverridable')!r}"
    )


# ---------------------------------------------------------------------------
# ML-agents-002 — catalog `model` field must reflect the saved per-agent
# override, not silently fall back to the tier's env default
# ---------------------------------------------------------------------------


def test_catalog_model_field_reflects_saved_override(client, auth_headers):
    """PINS THE ROOT-CAUSE CONTRACT for the fixer: after `PUT
    /agents/config/{agentKey}` saves a model DIFFERENT from the catalog's
    `recommended` default, `GET /agents/catalog`'s `model` field for that
    same agent must show the SAVED model — not the tier's env default.

    FAILS NOW: `agent_catalog()` (agents.py ~1725) computes
    `model = _model_for_agent(backend) or "deterministic"` with NO
    `override` argument, so it always resolves to `get_model(tier)` (the env
    default) regardless of any persisted `AgentConfig.model` — even though
    `GET /agents/config/{agentKey}` (a separate endpoint) already returns the
    saved value correctly. This is exactly the "save + reload still shows
    the default" symptom from the deep UI test (ML-agents-002).
    """
    put = client.put(
        "/agents/config/resumeTailoring",
        json={"model": "deepseek/deepseek-chat"},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text

    # Sanity: the OTHER config endpoint already reflects the save correctly —
    # proves the write path and this specific read are the only broken link.
    cfg = client.get("/agents/config/resumeTailoring", headers=auth_headers)
    assert cfg.json()["model"] == "deepseek/deepseek-chat", cfg.text

    agents = _catalog_by_key(client, auth_headers)
    assert agents["resumeTailoring"]["model"] == "deepseek/deepseek-chat", (
        f"GET /agents/catalog still shows "
        f"{agents['resumeTailoring']['model']!r} for resumeTailoring after "
        "saving 'deepseek/deepseek-chat' — the catalog's display model "
        "ignores the persisted per-agent override"
    )


def test_catalog_model_field_is_per_agent_not_shared(client, auth_headers):
    """Two different agents with two DIFFERENT saved overrides must show two
    DIFFERENT `model` values in the catalog — proves a fix doesn't just
    thread a single global override into the catalog handler (which would
    pass the previous single-agent test by coincidence sharing one value).

    FAILS NOW for the same root cause as above: BOTH show the identical
    REASONING-tier env default, ignoring either saved override.
    """
    put1 = client.put(
        "/agents/config/resumeTailoring",
        json={"model": "deepseek/deepseek-chat"},
        headers=auth_headers,
    )
    assert put1.status_code == 200, put1.text
    put2 = client.put(
        "/agents/config/coverLetter",
        json={"model": "anthropic/claude-opus"},
        headers=auth_headers,
    )
    assert put2.status_code == 200, put2.text

    agents = _catalog_by_key(client, auth_headers)
    tailor_model = agents["resumeTailoring"]["model"]
    cover_model = agents["coverLetter"]["model"]
    assert tailor_model == "deepseek/deepseek-chat", (
        f"resumeTailoring catalog model is {tailor_model!r}, expected the "
        "saved 'deepseek/deepseek-chat'"
    )
    assert cover_model == "anthropic/claude-opus", (
        f"coverLetter catalog model is {cover_model!r}, expected the saved "
        "'anthropic/claude-opus'"
    )
    assert tailor_model != cover_model, (
        "both agents' catalog model resolved to the SAME value — the "
        "display is provider/tier-global, not per-agent"
    )


# ---------------------------------------------------------------------------
# ML-agents-004 — Test Run cost/token estimate must reflect the model the
# agent will ACTUALLY run on, never a constant across different selections
# ---------------------------------------------------------------------------


def test_test_run_estimate_differs_for_differently_priced_saved_models(
    client, auth_headers,
):
    """Two REASONING-tier agents with two saved models of DIFFERENT published
    price (`MODEL_PRICING`: claude-haiku-4-5-20251001 $0.001/$0.005 per 1K vs
    claude-fable-5 $0.010/$0.050 per 1K — a 10x spread) must get DIFFERENT
    `estCost` (and ideally different `model`) from `POST /agents/test-run`.

    FAILS NOW: `test_run()` computes
    `llm_model = _model_for_agent(backend) if backend else None` with NO
    `override` argument (agents.py ~2764) — both agents resolve to the SAME
    `get_model("REASONING")` env default, so `estCost` is IDENTICAL despite
    the two saved models having a 10x price difference. This is exactly the
    "static placeholder identical across agents" symptom from the deep UI
    test (ML-agents-004) — the FE TestRunModal renders `estCost`/`model`
    verbatim from this response with no client-side computation of its own.
    """
    cheap = client.put(
        "/agents/config/resumeTailoring",
        json={"model": "claude-haiku-4-5-20251001"},
        headers=auth_headers,
    )
    assert cheap.status_code == 200, cheap.text
    expensive = client.put(
        "/agents/config/coverLetter",
        json={"model": "claude-fable-5"},
        headers=auth_headers,
    )
    assert expensive.status_code == 200, expensive.text

    run_cheap = client.post(
        "/agents/test-run", json={"agent_key": "resumeTailoring"}, headers=auth_headers,
    )
    run_expensive = client.post(
        "/agents/test-run", json={"agent_key": "coverLetter"}, headers=auth_headers,
    )
    assert run_cheap.status_code == 200, run_cheap.text
    assert run_expensive.status_code == 200, run_expensive.text
    body_cheap, body_expensive = run_cheap.json(), run_expensive.json()

    assert body_cheap["estCost"] is not None
    assert body_expensive["estCost"] is not None
    assert body_cheap["estCost"] != body_expensive["estCost"], (
        "the Test Run cost estimate is a CONSTANT: resumeTailoring "
        f"(saved claude-haiku-4-5-20251001) and coverLetter (saved "
        f"claude-fable-5, 10x the published price) both estimated "
        f"${body_cheap['estCost']} — the estimate ignores each agent's own "
        "saved model"
    )
    assert body_cheap["model"] != body_expensive["model"], (
        "both agents report the SAME 'model' from /agents/test-run "
        f"({body_cheap['model']!r}) despite different saved overrides — "
        "the estimate's model field also ignores the per-agent override"
    )
