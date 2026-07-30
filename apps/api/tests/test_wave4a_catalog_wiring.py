"""Wave-4A — catalog wiring + card-copy honesty for the five new agents.

Contract (uat/reports/evidence/models-live/real-agent-contract-file-line-index-
2026-07-29.md): a catalog entry that gains a ``backend`` becomes ``active``
SERVER-SIDE with no frontend change, is dispatchable through
``POST /agents/{backend}/run``, and reports ``runnable: true``.

ADR-AG-1 also requires each card's TIP to be corrected in the same change where
it overpromised — no card may still advertise a capability the shipped agent
does not have (browser automation, external web research, market-data feeds,
adaptive learning).
"""
from __future__ import annotations

import pytest

WAVE_4A = {
    "compliance": "compliance",
    "salaryIntelligence": "salaryIntelligence",
    "marketTrends": "marketTrends",
    "companyResearch": "companyResearch",
    "learningFeedback": "learningFeedback",
}

#: Phrases the OLD tips used that promise capabilities this product does not
#: have. None may survive anywhere in the catalog copy for these five cards.
FORBIDDEN_CLAIMS = (
    "from web sources",
    "market & hiring trend signals",
    "learns from application outcomes",
    "at scale",
    "browser automation",
    # compliance's old tip implied a second-opinion LLM verifier that does not
    # exist — the only truthfulness authority is the generation-time guard.
    "careful reasoning about truthfulness",
)


@pytest.fixture()
def cards(client, auth_headers) -> dict:
    body = client.get("/agents/catalog", headers=auth_headers).json()
    return {a["key"]: a for a in body["agents"]}


@pytest.mark.parametrize("key,backend", sorted(WAVE_4A.items()))
def test_card_is_wired_active_and_runnable(cards, key, backend):
    card = cards[key]
    assert card["backend"] == backend
    assert card["status"] == "active"
    assert card["runnable"] is True
    assert card["enabled"] is True


@pytest.mark.parametrize("key", sorted(WAVE_4A))
def test_card_copy_no_longer_overpromises(cards, key):
    tip = cards[key]["tip"].lower()
    offenders = [c for c in FORBIDDEN_CLAIMS if c in tip]
    assert not offenders, (
        f"{key} card tip still promises {offenders} — ADR-AG-1 requires the copy "
        f"to be corrected in the same change as the implementation: {tip!r}"
    )


@pytest.mark.parametrize(
    "key,marker",
    [
        ("compliance", "guard"),
        ("salaryIntelligence", "disclosed"),
        ("marketTrends", "your own"),
        ("companyResearch", "your own"),
        ("learningFeedback", "read-only"),
    ],
)
def test_card_copy_states_the_honest_scope(cards, key, marker):
    assert marker in cards[key]["tip"].lower(), (
        f"{key} tip must state its honest scope (expected {marker!r}): "
        f"{cards[key]['tip']!r}"
    )


@pytest.mark.parametrize(
    "key",
    ["compliance", "salaryIntelligence", "marketTrends", "learningFeedback"],
)
def test_deterministic_cards_advertise_no_model(cards, key):
    """A deterministic agent must not recommend an LLM (that would imply a model
    choice matters) and must not render a functional model picker."""
    assert cards[key]["recommended"] == "deterministic"
    assert cards[key]["model"] == "deterministic"
    assert cards[key]["modelOverridable"] is False


def test_company_research_is_the_only_metered_new_card(cards):
    from app.services.llm_client import get_model

    card = cards["companyResearch"]
    assert card["recommended"] != "deterministic"
    assert card["model"] == get_model("REASONING")
    assert card["modelOverridable"] is True


def test_catalog_counts_moved_five_cards_out_of_planned(cards, client, auth_headers):
    body = client.get("/agents/catalog", headers=auth_headers).json()
    planned = {a["key"] for a in body["agents"] if a["status"] == "planned"}
    assert not (set(WAVE_4A) & planned)
    # The honesty contract itself is unchanged: still exactly the no-backend set.
    assert body["counts"]["planned"] == sum(
        1 for a in body["agents"] if a["backend"] is None
    )
    assert planned == {a["key"] for a in body["agents"] if a["backend"] is None}


@pytest.mark.parametrize("backend", sorted(WAVE_4A.values()))
def test_generic_run_route_dispatches_each_new_backend(client, auth_headers, backend):
    """The FE runs a card via ``AGENT_ROUTE[backend] ?? backend`` — i.e. the raw
    camelCase backend name on the generic route. That must resolve (never 404)
    with no params, so no frontend mapping is required."""
    resp = client.post(f"/agents/{backend}/run", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["run_id"]


@pytest.mark.parametrize(
    "slug,backend",
    [
        ("compliance", "compliance"),
        ("salary-intelligence", "salaryIntelligence"),
        ("market-trends", "marketTrends"),
        ("company-research", "companyResearch"),
        ("learning-feedback", "learningFeedback"),
    ],
)
def test_kebab_case_aliases_resolve_to_the_same_backend(
    client, auth_headers, slug, backend
):
    resp = client.post(f"/agents/{slug}/run", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    runs = client.get("/agents/runs", headers=auth_headers).json()
    assert any(r["agentName"] == backend for r in runs), (
        f"alias /agents/{slug}/run must audit under the canonical name {backend!r}"
    )


def test_new_agents_are_not_approval_gated(client, auth_headers):
    from app.routers.agents import _APPROVAL_GATED

    assert not (set(WAVE_4A.values()) & _APPROVAL_GATED)


def test_test_run_preview_works_for_every_new_card(client, auth_headers):
    for key in sorted(WAVE_4A):
        res = client.post(
            "/agents/test-run", json={"agent_key": key}, headers=auth_headers
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["model"]
        assert body["creditsCharged"] == 0.0
        if key == "companyResearch":
            assert body["estCost"] is not None
        else:
            # Deterministic: no fabricated spend estimate.
            assert body["estCost"] is None
            assert body["estTokens"] is None
