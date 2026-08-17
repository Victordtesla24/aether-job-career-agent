"""AUD-AGENT-4 — the agent count the product shows must be honest.

THE LEDGER FINDING. ``AGENT_CATALOG`` is a list of CARDS, not of agents: one
deterministic engine (``fitScorer``) is presented as THREE cards — Match
Scoring, ATS Optimization and Skill Gap — so ``len(AGENT_CATALOG)`` has never
been a count of agents. ``GET /agents/catalog`` transmitted only
``counts.total`` (the card total), and every user-facing surface rendered it
as "22 agents": the product's headline number counted one engine three times.

The relabel half of the finding already landed (the facet cards' tips say they
are facets of Match Scoring). This file pins the COUNT half:

  1. the server computes and transmits BOTH honest numbers — ``engines``
     (distinct implemented backends) and ``cards`` (catalog entries) — so no
     surface has to guess which one it is holding;
  2. an engine behind several cards is counted ONCE, and the gap between the
     two numbers is exactly the facet padding, never an accident;
  3. those numbers reconcile with the conductor's own server-derived
     "Run everything (N agents / M cards)" plan, so the two screens cannot
     disagree about how big this product is;
  4. no web surface renders a hardcoded agent count or reads the padded card
     total as an agent count;
  5. every WORKFLOW MAP carries the same honest basis, per map, so the
     orchestration screen's own header count is the server's arithmetic and
     not a client-side sum of nodes (round 2: the Orchestration tab's map
     header still read ``{sum of stage nodes} agents``, which is the fitScorer
     triple-count all over again on the SAME screen as the two surfaces fixed
     first);
  6. the sidebar Agent Pulse's "N agents ready" — rendered on every dashboard
     screen — counts DISTINCT AGENTS, because ``GET /agents`` is one row per
     engine.

DB-backed; uses the shared ``client`` / ``auth_headers`` fixtures. No LLM call
is made — only the catalog and orchestration-map projections are exercised.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from app.routers.agents import (
    _ALL_UI_KEYS_FOR_BACKEND,
    _EXEC_CLASS_BY_BACKEND,
    _RUNNABLE_BACKENDS,
    AGENT_CATALOG,
    AGENT_NAMES,
)

#: Distinct implemented backends — the number of agents that actually exist.
_CATALOG_ENGINES = {e["backend"] for e in AGENT_CATALOG if e.get("backend")}


def _counts(client, auth_headers) -> dict[str, int]:
    r = client.get("/agents/catalog", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["counts"]


# ---------------------------------------------------------------------------
# 1. The server transmits the honest basis
# ---------------------------------------------------------------------------


def test_catalog_counts_transmit_engines_and_cards(client, auth_headers):
    """Both numbers are server-computed and named for what they count."""
    counts = _counts(client, auth_headers)

    assert "engines" in counts, (
        "GET /agents/catalog transmits no engine count — every surface reading "
        "this payload can only render the padded card total as 'N agents'."
    )
    assert "cards" in counts, (
        "GET /agents/catalog names no card total, so a client cannot state the "
        "dual disclosure ('N engines powering M cards') without guessing."
    )
    assert counts["engines"] == len(_CATALOG_ENGINES)
    assert counts["cards"] == len(AGENT_CATALOG)


def test_engine_count_is_strictly_below_the_card_count(client, auth_headers):
    """The padding is real: this catalog has fewer agents than it has cards."""
    counts = _counts(client, auth_headers)
    assert counts["engines"] < counts["cards"], (
        "engines == cards would mean the facet padding vanished from the "
        "catalog; AUD-AGENT-4 exists because it did not."
    )


# ---------------------------------------------------------------------------
# 2. One engine behind several cards is counted ONCE
# ---------------------------------------------------------------------------


def test_one_engine_behind_three_cards_is_counted_once(client, auth_headers):
    """``fitScorer`` powers three cards and contributes one to ``engines``."""
    facets = [e["key"] for e in AGENT_CATALOG if e.get("backend") == "fitScorer"]
    assert sorted(facets) == ["atsOptimization", "matchScoring", "skillGap"], facets

    counts = _counts(client, auth_headers)
    # The whole gap between the two numbers is accounted for: every card beyond
    # the first that shares an engine, plus every card with no engine at all.
    shared_facet_cards = sum(
        len(keys) - 1 for keys in _ALL_UI_KEYS_FOR_BACKEND.values()
    )
    engineless_cards = sum(1 for e in AGENT_CATALOG if not e.get("backend"))
    assert counts["cards"] - counts["engines"] == shared_facet_cards + engineless_cards
    assert shared_facet_cards >= 2, (
        "fitScorer's two extra facet cards are the padding this finding names"
    )


# ---------------------------------------------------------------------------
# 3. The catalog and the conductor plan cannot disagree
# ---------------------------------------------------------------------------


def test_counts_reconcile_with_the_run_everything_plan(client, auth_headers):
    """Catalog scale and the conductor's plan scale are the same arithmetic.

    "Run everything (N agents / M cards)" is built from
    :data:`_EXEC_CLASS_BY_BACKEND`. The ONLY difference between its scale and
    the catalog's is the engines that cannot be dispatched at all (today:
    ``supervisor``) and the cards they own — so the two screens reconcile
    exactly, with no unexplained remainder.
    """
    counts = _counts(client, auth_headers)

    plan_engines = set(_EXEC_CLASS_BY_BACKEND)
    plan_cards = {
        card
        for fields in _EXEC_CLASS_BY_BACKEND.values()
        for card in fields["coversCards"]
    }

    assert plan_engines <= _CATALOG_ENGINES
    # Every engine the plan omits is omitted because it is not dispatchable.
    assert _CATALOG_ENGINES - plan_engines == _CATALOG_ENGINES - set(
        _RUNNABLE_BACKENDS
    )
    assert counts["engines"] - len(plan_engines) == len(
        _CATALOG_ENGINES - set(_RUNNABLE_BACKENDS)
    )

    uncovered_cards = {e["key"] for e in AGENT_CATALOG} - plan_cards
    assert uncovered_cards == {
        e["key"]
        for e in AGENT_CATALOG
        if not e.get("backend") or e["backend"] not in _RUNNABLE_BACKENDS
    }
    assert counts["cards"] - len(plan_cards) == len(uncovered_cards)


# ---------------------------------------------------------------------------
# 4. No web surface may render a padded or hardcoded agent count
# ---------------------------------------------------------------------------

_WEB_SRC = Path(__file__).resolve().parents[3] / "apps" / "web" / "src"

#: The two screens that consume ``GET /agents/catalog``'s counts. Named
#: explicitly so this guard fails loudly if either is renamed away from the
#: check rather than silently scanning nothing.
_CATALOG_COUNT_SURFACES = (
    _WEB_SRC / "components" / "agents" / "AgentConfigGrid.tsx",
    _WEB_SRC / "app" / "dashboard" / "agents" / "page.tsx",
)

#: A literal count of agents baked into source (e.g. "22 agents").
_HARDCODED_AGENT_COUNT = re.compile(r"\b\d+\s+agents\b", re.IGNORECASE)
#: The padded card total read straight out of the catalog payload.
_PADDED_TOTAL = re.compile(r"\bcounts\s*\??\.\s*total\b")

#: A COMPUTED count rendered as a count of agents — `{sum} agents` in JSX or
#: `${sum} agents` in a template literal.
#:
#: ROUND 2 EXISTS BECAUSE :data:`_HARDCODED_AGENT_COUNT` CANNOT SEE THESE. It
#: matches a literal digit before the word, so it was blind to
#: ``OrchestrationMap.tsx``'s map header —
#: ``{model.stages.reduce((n, s) => n + s.nodes.length, 0)} agents`` — which
#: summed NODES and therefore counted the fitScorer engine three times, on the
#: same screen as the two surfaces the first round fixed.
#:
#: The interpolation must look like a COUNT (a `.length` / `reduce(` / `count` /
#: `total` / `size` in the expression) so agent NAMES interpolated into prose
#: (``${agentName} agent``) are not swept up, and the word must not be the
#: adjective of some other noun — "agent runs" counts RUNS and "agent cards"
#: counts CARDS, both of which are honest things to count.
_INTERPOLATED_AGENT_COUNT = re.compile(
    r"\$?\{[^{}]*(?:\.length\b|\breduce\s*\(|[Cc]ount\b|\btotal\b|\bsize\b)[^{}]*\}"
    r"[^{}]{0,24}?\bagents?\b(?!\s*(?:runs?|cards?)\b)"
)

#: The ONLY interpolations allowed to be labelled "agents", each because the
#: number it holds is a SERVER-computed count of distinct engines:
#:
#: ``plan.agentCount``  ``GET /agents/orchestration-plan`` — the conductor's
#:                      "Run everything (N agents / M cards)", one entry per
#:                      dispatchable backend (``_EXEC_CLASS_BY_BACKEND``).
#: ``pulse.total``      ``GET /agents`` — one row per :data:`AGENT_NAMES`
#:                      entry, i.e. per distinct engine. Pinned by
#:                      ``test_the_sidebar_pulse_counts_engines_not_cards``.
#:
#: Nothing may be added here without a test in THIS file proving the number is
#: an engine count; the allowlist is the audit trail, not a mute button.
_SERVER_DERIVED_AGENT_COUNTS = ("plan.agentCount", "pulse.total")


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Source lines with ``//`` and ``/* … */`` comments blanked out.

    Comments are prose ABOUT the defect (this repo's are long and cite the old
    numbers by design); only shipped code and copy is in scope. Blanking rather
    than dropping keeps line numbers usable in the failure message.
    """
    out: list[tuple[int, str]] = []
    in_block = False
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line, rest = "", raw
        while rest:
            if in_block:
                end = rest.find("*/")
                if end < 0:
                    rest = ""
                    break
                rest = rest[end + 2 :]
                in_block = False
                continue
            start = rest.find("/*")
            slash = rest.find("//")
            if slash >= 0 and (start < 0 or slash < start):
                line += rest[:slash]
                rest = ""
                break
            if start < 0:
                line += rest
                rest = ""
                break
            line += rest[:start]
            rest = rest[start + 2 :]
            in_block = True
        out.append((n, line))
    return out


@pytest.mark.parametrize("path", _CATALOG_COUNT_SURFACES, ids=lambda p: p.name)
def test_catalog_surfaces_never_read_the_padded_card_total(path: Path):
    """Neither catalog screen may read ``counts.total`` — it is not agents."""
    assert path.is_file(), f"{path} moved; this guard would silently pass"
    offenders = [(n, ln.strip()) for n, ln in _code_lines(path) if _PADDED_TOTAL.search(ln)]
    assert offenders == [], (
        f"{path.name} reads the padded card total as a displayed count: {offenders}"
    )


def _shipped_web_sources() -> list[Path]:
    """Every shipped `.ts`/`.tsx` under `apps/web/src` — tests excluded."""
    out = []
    for path in sorted(_WEB_SRC.rglob("*.ts*")):
        parts = set(path.parts)
        if "__tests__" in parts or ".test." in path.name or ".spec." in path.name:
            continue
        out.append(path)
    return out


def test_no_web_source_hardcodes_an_agent_count():
    """No shipped web copy states a count of agents as a literal."""
    offenders: list[str] = []
    for path in _shipped_web_sources():
        for n, line in _code_lines(path):
            if _HARDCODED_AGENT_COUNT.search(line):
                offenders.append(f"{path.relative_to(_WEB_SRC)}:{n}: {line.strip()}")
    assert offenders == [], "hardcoded agent counts in web copy:\n" + "\n".join(offenders)


def test_no_web_source_computes_its_own_agent_count():
    """No surface may label a self-computed number "agents".

    This is the round-2 guard. A count that is summed in the browser — over
    catalog cards, over map nodes, over anything — is by construction NOT the
    server's honest engine count, so it re-pads exactly the way the map header
    did. The only interpolations exempt are the two that carry a server-derived
    engine count, and each is pinned by its own test in this file.
    """
    offenders: list[str] = []
    for path in _shipped_web_sources():
        for n, line in _code_lines(path):
            if not _INTERPOLATED_AGENT_COUNT.search(line):
                continue
            if any(ok in line for ok in _SERVER_DERIVED_AGENT_COUNTS):
                continue
            offenders.append(f"{path.relative_to(_WEB_SRC)}:{n}: {line.strip()}")
    assert offenders == [], (
        "client-computed agent counts in web copy — every count labelled "
        "'agents' must be the server's engine count, or must name what it "
        "really counts (cards, runs):\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# 5. Every workflow map carries its OWN honest basis
# ---------------------------------------------------------------------------


def _maps(client, auth_headers) -> list[dict[str, Any]]:
    r = client.get("/agents/orchestration-map", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["maps"]


def _nodes(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for stage in entry["stages"] for a in stage["agents"]]


def test_every_workflow_map_transmits_engines_and_cards(client, auth_headers):
    """Each map states how many ENGINES its cards stand for.

    Without this the orchestration screen has no honest number to render and
    can only sum its own nodes — which counts one engine once per facet card.
    """
    maps = _maps(client, auth_headers)
    assert maps, "no workflow maps returned; this guard would scan nothing"

    for entry in maps:
        counts = entry.get("counts")
        assert counts is not None, (
            f"map {entry['key']!r} carries no honest count basis, so its header "
            "can only sum nodes — the padded number AUD-AGENT-4 names"
        )
        nodes = _nodes(entry)
        assert counts["cards"] == len(nodes)
        assert counts["engines"] == len({a["backend"] for a in nodes if a["backend"]})


def test_the_pipeline_map_counts_the_fit_scoring_engine_once(client, auth_headers):
    """The exact recorded deviation, at the exact surface it survived on.

    "Fit Scoring" lists four cards; three of them are the SAME ``fitScorer``
    backend. A header summing nodes says 12 agents for the Application
    Pipeline; the honest engine count is 10.
    """
    pipeline = next(m for m in _maps(client, auth_headers) if m["key"] == "application-pipeline")
    nodes = _nodes(pipeline)

    facets = sorted(a["agentKey"] for a in nodes if a["backend"] == "fitScorer")
    assert facets == ["atsOptimization", "matchScoring", "skillGap"], facets

    node_total = len(nodes)
    facet_padding = node_total - len({a["backend"] for a in nodes if a["backend"]})
    engineless = sum(1 for a in nodes if not a["backend"])

    assert pipeline["counts"]["engines"] < node_total, (
        "the map's engine count equals its node count — the fitScorer facets "
        "are being counted as separate agents again"
    )
    # The whole gap is explained: shared-backend facet cards plus roadmap cards.
    assert node_total - pipeline["counts"]["engines"] == facet_padding + engineless
    assert facet_padding >= 2, (
        "fitScorer's two extra facet cards are the padding this finding names"
    )


def test_map_counts_never_exceed_the_catalog_basis(client, auth_headers):
    """Per-map numbers and the catalog's numbers are one arithmetic.

    A map cannot contain more engines or more cards than the catalog holds, and
    the maps together must place every card exactly once — otherwise the
    screen's per-map counts and the screen's headline count describe different
    products.
    """
    catalog = _counts(client, auth_headers)
    maps = _maps(client, auth_headers)

    placed = [a["agentKey"] for entry in maps for a in _nodes(entry)]
    assert sorted(placed) == sorted(e["key"] for e in AGENT_CATALOG), (
        "the maps do not place every catalog card exactly once"
    )
    assert sum(m["counts"]["cards"] for m in maps) == catalog["cards"]

    engines_placed = {a["backend"] for entry in maps for a in _nodes(entry) if a["backend"]}
    assert len(engines_placed) == catalog["engines"]
    for entry in maps:
        assert entry["counts"]["engines"] <= catalog["engines"]
        assert entry["counts"]["cards"] <= catalog["cards"]


# ---------------------------------------------------------------------------
# 6. The sidebar pulse — the count on EVERY dashboard screen
# ---------------------------------------------------------------------------


def test_the_sidebar_pulse_counts_engines_not_cards(client, auth_headers):
    """"N agents ready" reads ``GET /agents``, which is one row per engine.

    This is the justification for ``pulse.total`` sitting in
    :data:`_SERVER_DERIVED_AGENT_COUNTS`: the row count IS the engine count,
    server-derived from :data:`AGENT_NAMES`, so the rail may say "agents".
    """
    r = client.get("/agents", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()

    assert len(rows) == len(AGENT_NAMES)
    assert len(rows) == len(_CATALOG_ENGINES), (
        "the sidebar's agent count and the catalog's engine count disagree"
    )
    assert len({row["name"] for row in rows}) == len(rows), "duplicate agent rows"
    assert len(rows) < len(AGENT_CATALOG), (
        "the rail is counting cards, not agents"
    )
