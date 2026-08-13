"""U1X-b ROLE — failing tests for the Orchestrator role-assignment gap.

RCA (agents-uplift discovery, roles-tiers scout; full evidence in
uat/reports/evidence/agents-uplift/u1x-discovery/): the user-facing
"Orchestration Agent" catalog card (key ``orchestration``, backend
``supervisor``) is a pure bookkeeping closure inside ``_pipeline_core`` — it
records a static plan list and makes NO LLM call, so it has no tier. Live-
verified: ``GET /agents/catalog`` returns
``orchestration.model == "deterministic"``,
``orchestration.modelOverridable == false``. The EXISTING per-agent override
machinery (``AgentConfig`` table, ``GET/PUT /agents/config/{agent_key}``)
technically accepts writes for ANY catalog key including ``orchestration``
(no fix needed at the storage layer), but the RESOLVER every other role's
choice is read back through — ``_user_model_override`` (agents.py) — hard-
excludes it: ``if agent_name not in _LLM_TIER_BY_BACKEND: return None``, and
``"supervisor"`` is absent from that dict. So a persisted orchestrator choice
is a complete no-op today: it can never be read back, never bound into a live
call, and the catalog's default (no override) model stays the honest-but-
unhelpful ``"deterministic"`` sentinel rather than the flagship anthropic id
(U-PLAN's explicit spec: "default when unset = the flagship anthropic id
from the static catalog").

PINNED CONTRACT for the fixer:
  * ``AGENT_CATALOG``'s ``orchestration`` entry's ``recommended`` becomes the
    static catalog's flagship (premium-tier) anthropic id
    (``llm_client._STATIC_MODEL_CATALOG["anthropic"]``, currently
    ``"claude-opus-4-8"``) instead of the ``"deterministic"`` sentinel.
  * ``_model_overridable("supervisor")`` (agents.py) becomes ``True`` so
    ``GET /agents/catalog``'s ``orchestration.modelOverridable`` flips to
    ``true`` and the FE picker unlocks.
  * ``_user_model_override(user_id, "supervisor")`` becomes resolvable — a
    persisted ``AgentConfig`` row for ``agentKey="orchestration"`` must be
    readable through the SAME resolver every other role's choice already
    goes through, exactly like ``reuse the existing per-agent override
    tables/endpoints`` in the U-PLAN spec.
  * ADR-ML-3 (no silent model substitution for a user-selected model) must
    hold for the orchestrator's choice too: once resolvable, binding it as
    the active ``user_model_context`` value must produce a single-attempt
    ``LLMClient._model_chain`` (no silent fallback to a DIFFERENT model on
    failure) — the SAME guarantee already proven for every other
    overridable agent (test_ml_catalog_fix1.py::
    test_user_chosen_model_failure_does_not_silently_substitute_fallback).

Test-authorship only — no fix is implemented in this file.
"""

from __future__ import annotations

import pytest

from app.services import credential_vault as vault
from app.services.llm_client import LLMClient, _STATIC_MODEL_CATALOG, user_model_context

_FLAGSHIP_ANTHROPIC_ID = next(
    m["id"] for m in _STATIC_MODEL_CATALOG["anthropic"] if m["tier"] == "premium"
)


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


def test_orchestrator_role_override_is_read_by_the_resolver(
    client, auth_headers, test_user_id
):
    """FAILS NOW: the write succeeds (the storage layer is generic), but
    ``_user_model_override(user_id, "supervisor")`` returns ``None``
    unconditionally — ``"supervisor"`` is absent from
    ``_LLM_TIER_BY_BACKEND`` so the resolver refuses to consider it at all,
    making a persisted orchestrator choice a complete no-op."""
    put = client.put(
        "/agents/config/orchestration",
        json={"model": "claude-sonnet-4-6"},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    assert put.json()["model"] == "claude-sonnet-4-6"

    from app.routers.agents import _user_model_override

    resolved = _user_model_override(test_user_id, "supervisor")
    assert resolved == "claude-sonnet-4-6", (
        f"orchestrator role override was persisted via the EXISTING per-agent "
        f"AgentConfig table/endpoint but the resolver every other role's "
        f"choice is read through (`_user_model_override`) returned "
        f"{resolved!r} instead of the saved choice — the role picker would "
        "silently no-op."
    )


def test_orchestrator_catalog_defaults_to_flagship_anthropic_model(
    client, auth_headers
):
    """FAILS NOW: ``orchestration.recommended``/``.model`` is the
    ``"deterministic"`` sentinel and ``modelOverridable`` is ``False`` — a
    role picker has nothing to default to or bind against."""
    r = client.get("/agents/catalog", headers=auth_headers)
    assert r.status_code == 200, r.text
    entry = next(e for e in r.json()["agents"] if e["key"] == "orchestration")

    assert entry["modelOverridable"] is True, (
        f"orchestration.modelOverridable is {entry['modelOverridable']!r} — "
        "the role picker has nothing to bind to while this stays false."
    )
    assert entry["model"] == _FLAGSHIP_ANTHROPIC_ID, (
        f"orchestration's default (no override set) model is "
        f"{entry['model']!r}, expected the static catalog's flagship "
        f"anthropic id {_FLAGSHIP_ANTHROPIC_ID!r}"
    )
    assert entry["recommended"] == _FLAGSHIP_ANTHROPIC_ID, entry


def test_orchestrator_override_binds_into_a_no_silent_substitution_chain(
    client, auth_headers, test_user_id
):
    """ADR-ML-3, the resolver's failure path: once the orchestrator's choice
    is genuinely resolvable and bound as the active ``user_model_context``,
    ``LLMClient._model_chain`` must treat it as a deliberate USER choice — a
    single-attempt chain with NO silent fallback substitution on failure —
    exactly the guarantee every other overridable role already gets.

    FAILS NOW at the first assertion: ``_user_model_override`` cannot resolve
    'supervisor' at all yet (same root cause as the resolver test above), so
    nothing can ever bind this choice into a live call in the first place —
    the orchestrator's "choice" is silently ignored entirely, not merely
    substituted on failure.
    """
    put = client.put(
        "/agents/config/orchestration",
        json={"model": _FLAGSHIP_ANTHROPIC_ID},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text

    from app.routers.agents import _user_model_override

    chosen = _user_model_override(test_user_id, "supervisor")
    assert chosen == _FLAGSHIP_ANTHROPIC_ID, (
        "cannot exercise the ADR-ML-3 no-substitution failure path: the "
        "orchestrator's persisted choice is not resolvable at all yet "
        f"(_user_model_override returned {chosen!r})"
    )

    with user_model_context(chosen):
        chain = LLMClient._model_chain(chosen)
    assert chain == [chosen], (
        f"ADR-ML-3: a user-selected orchestrator model must run ALONE (no "
        f"silent fallback substitution) once bound as the active choice — "
        f"got chain {chain!r}"
    )


# --------------------------------------------------------------------------- #
# F-1 (review re-fix, BLOCKER): the orchestrator's role assignment must not
# fabricate spend for a step that makes NO LLM call. Giving ``supervisor`` a
# real model id via ``_ROLE_MODEL_BACKENDS`` broke ``_execute_reserved_run``'s
# zero-cost gate (``if model is None or ...``), which used to be true for
# every deterministic backend precisely BECAUSE ``_model_for_agent`` returned
# None for them. Once the role backend returns a real id, the gate must be
# widened (not the id removed) so a supervisor step still records $0 / 0
# tokens / model=None — exactly like every other deterministic agent.
# --------------------------------------------------------------------------- #


def test_supervisor_role_run_still_records_zero_cost_and_no_model(
    client, auth_headers, test_user_id
):
    """FAILS on the regression: ``_model_for_agent('supervisor')`` now
    returns the flagship anthropic id (this slice's own fix), so the costing
    tail's ``model is None`` gate no longer fires and a run that made NO LLM
    call gets priced off its params/output JSON at Opus rates."""
    from app.routers.agents import _record_run

    out = _record_run(
        test_user_id,
        "supervisor",
        {},
        lambda: {"plan": ["scout", "fitScorer", "matcher", "tailor", "coverLetter"]},
    )
    assert out["model"] is None, (
        f"supervisor makes no LLM call — output['model'] must stay None, got "
        f"{out['model']!r} (a real model id here means a run stamp that "
        "never actually served this run)"
    )
    assert out["tokensIn"] == 0 and out["tokensOut"] == 0, out
    assert out["costUsd"] == 0.0, (
        f"supervisor run recorded costUsd={out['costUsd']!r} — GET "
        "/agents/stats sums this into spendUsd/avgCostPerRun/tokensTotal for "
        "a step that made NO LLM call and charges no quota "
        "(_call_is_metered is False for it)."
    )
    assert out["billingAudit"] == {"quotaPath": "none"}, out["billingAudit"]


def test_test_run_estimator_supervisor_role_stays_zero_cost(
    client, auth_headers
):
    """R-1 (BE re-fix round 2): the SAME regression as
    ``test_supervisor_role_run_still_records_zero_cost_and_no_model`` above,
    but at the dry-run estimator (``POST /agents/test-run``) instead of the
    real run-costing tail. ``_model_for_agent('supervisor', ...)`` now
    returns the flagship anthropic id (U1X-b), so the estimator's
    ``if llm_model is not None`` guard no longer excludes the Orchestration
    Agent — it fabricates ``estCost``/``estTokens`` off two hardcoded
    literals (2800/1400 input/output tokens) for a backend that makes ZERO
    LLM calls today. The role's display id must still surface in ``model``
    (U1X-b's own contract — the picker needs it to show what the role is
    assigned), but the derived spend/token figures must stay genuinely null,
    exactly like every other backend absent from ``_LLM_TIER_BY_BACKEND``."""
    res = client.post(
        "/agents/test-run", json={"agent_key": "orchestration"}, headers=auth_headers
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["model"] not in (None, "deterministic"), (
        "the role's assigned display id must still surface in `model` — "
        f"got {body['model']!r}"
    )
    assert body["estCost"] is None, (
        f"estCost={body['estCost']!r} for agent_key='orchestration' — the "
        "supervisor backend makes NO LLM call (absent from "
        "_LLM_TIER_BY_BACKEND), so this is a fabricated spend figure "
        "rendered to the user as a real dollar estimate."
    )
    assert body["estTokens"] is None, (
        f"estTokens={body['estTokens']!r} for agent_key='orchestration' — "
        "same fabrication as estCost, fed by the endpoint's own hardcoded "
        "2800/1400 literals for a backend with no real LLM call."
    )
    assert body["creditsCharged"] == 0.0, body
