"""PROD-VERIFY-5A F-1 + F-3 — honest HTTP translation and honest agent counts.

F-1 (MED) — ``POST /agents/{name}/run`` returned an unhandled HTTP 500 for a
guard rejection. The DEDICATED ``POST /agents/cover-letter/run`` wraps the
dispatch in ``except FabricationError / StructuralError -> 422``; the GENERIC
per-name route caught only ``LookupError``, so a guard rejection escaped as an
unhandled exception: body literally ``Internal Server Error`` plus a full
traceback in the API log. Reproduced live on production:

    POST /api/agents/coverLetter/run {"job_id": "c90eb4a8d3a8f239f3a29ca9f"}
      -> HTTP 500 + app.agents.cover_letter_agent.FabricationError:
         Fabricated entities detected: ['prm']

A guard rejection is a NORMAL product outcome (the guard working — Aether
refuses to ship ungrounded or non-compliant text), and ``_record_run`` has
ALREADY recorded the honest ``completed`` degrade and refunded the reserved run
by the time the exception reaches the route. Only the HTTP translation was
missing. The generic route matters more than the finding's own note suggests:
``apps/web/src/app/dashboard/agents/page.tsx`` runs every agent WITHOUT an
``AGENT_ROUTE`` entry through it (``runAgent(AGENT_ROUTE[backend] ?? backend)``)
— all six wave-4A/4B agents included.

F-3 (MED) — ``GET /agents`` was built from a hardcoded 8-tuple
(``agents.py:75 AGENT_NAMES``) while ``GET /agents/catalog`` reports 16 active
cards. The sidebar Agent Pulse renders ``"8 agents ready"`` on EVERY dashboard
screen from that list, so the product visibly contradicted itself, and the
Orchestration view (which reads ``AgentSummary.status`` from the same list)
could never show the six new agents. The list must be DERIVED from the catalog
so a newly wired agent cannot be omitted again — while keeping every pipeline
node the Orchestration graph looks up by name, in pipeline order.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _catalog_backends() -> list[str]:
    """Every DISTINCT implemented backend in the catalog, in catalog order.

    ``dict.fromkeys`` de-duplicates while preserving order: ``fitScorer`` powers
    three catalog facets (Match Scoring, ATS Optimization, Skill Gap) but is ONE
    agent, so it must appear once.
    """
    from app.routers.agents import AGENT_CATALOG

    return list(
        dict.fromkeys(e["backend"] for e in AGENT_CATALOG if e.get("backend"))
    )


def _list_agents(client, auth_headers) -> list[dict]:
    res = client.get("/agents", headers=auth_headers)
    assert res.status_code == 200, res.text
    return res.json()


def _raising_callable(monkeypatch, exc: Exception, canonical: str = "coverLetter"):
    """Replace the PURE agent-resolution seam so the agent's own callable raises
    ``exc``.

    Everything downstream stays REAL: ``_dispatch`` -> ``_record_run`` still
    reserves quota, runs the guard-rejection handler (honest ``completed``
    degrade + refund) and re-raises, so these tests exercise the actual route
    behaviour rather than a stubbed-out response.
    """

    def _fake_agent_callable(user_id, name, params):  # noqa: ANN001, ARG001
        def _run():
            raise exc

        return canonical, _run

    monkeypatch.setattr(
        "app.routers.agents._agent_callable", _fake_agent_callable
    )


# ---------------------------------------------------------------------------
# F-1 — the generic per-name run route must translate a guard rejection
# ---------------------------------------------------------------------------


def test_generic_run_route_returns_422_for_a_fabrication_rejection(
    client, auth_headers, monkeypatch
):
    """The exact live repro: a fabrication rejection through the GENERIC route
    must be an honest 422 naming the flagged items, never a bare 500."""
    from app.agents.cover_letter_agent import FabricationError

    _raising_callable(monkeypatch, FabricationError(["prm"]))

    res = client.post(
        "/agents/coverLetter/run", json={"job_id": "c90eb4a8d3a8f239f3a29ca9f"},
        headers=auth_headers,
    )
    assert res.status_code == 422, (
        f"guard rejection surfaced as HTTP {res.status_code} "
        f"({res.text[:200]!r}) — a normal product outcome must never be a 500"
    )
    detail = res.json()["detail"]
    # The frontend's rejection parser (apps/web/src/components/cover-letters/
    # rejection.ts) reads the flagged items out of these exact anchors.
    assert "fabrication guard:" in detail.lower(), detail
    assert "prm" in detail, detail


def test_generic_run_route_returns_422_for_a_structural_rejection(
    client, auth_headers, monkeypatch
):
    from app.agents.cover_letter_agent import StructuralError

    _raising_callable(monkeypatch, StructuralError(["the closing paragraph"]))

    res = client.post(
        "/agents/coverLetter/run", json={}, headers=auth_headers
    )
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert "format contract not met:" in detail.lower(), detail
    assert "closing paragraph" in detail, detail


def test_the_dedicated_cover_letter_route_keeps_its_422_wording(
    client, auth_headers, monkeypatch
):
    """Regression rail for unifying the two routes on one translation: the
    dedicated route's detail wording is a CONTRACT with the studio's rejection
    panel, so it must be unchanged by the shared seam."""
    import os

    from app.agents.cover_letter_agent import FabricationError

    monkeypatch.setitem(os.environ, "AETHER_ASYNC_GENERATION", "false")
    _raising_callable(monkeypatch, FabricationError(["Kubernetes"]))

    res = client.post(
        "/agents/cover-letter/run", json={"job_id": "c90eb4a8d3a8f239f3a29ca9f"},
        headers=auth_headers,
    )
    assert res.status_code == 422, res.text
    assert res.json()["detail"] == (
        "Cover letter rejected by fabrication guard: ['Kubernetes']"
    )


def test_a_guard_rejection_through_the_generic_route_is_still_refunded(
    client, auth_headers, test_user_id, monkeypatch
):
    """The 422 must not change the honest accounting the guard-rejection handler
    in ``_record_run`` already performs: no letter was produced, so the reserved
    run is refunded and the AgentRun row is a ``completed`` degrade — not a red
    ``failed`` row for a correct refusal."""
    from app.agents.cover_letter_agent import FabricationError
    from app.repositories.billing import UsageQuotaRepository, ensure_user_billing

    ensure_user_billing(test_user_id)
    before = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])

    _raising_callable(monkeypatch, FabricationError(["prm"]))
    assert client.post(
        "/agents/coverLetter/run", json={}, headers=auth_headers
    ).status_code == 422

    assert int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"]) == before
    runs = client.get("/agents/runs", headers=auth_headers).json()
    degrade = next(r for r in runs if r["agentName"] == "coverLetter")
    assert degrade["status"] == "completed", degrade
    assert degrade["output"]["coverLetterUnavailable"] is True


def test_no_run_route_leaves_a_guard_rejection_unhandled():
    """Structural pin: EVERY route that dispatches an agent by name must handle
    the two guard exceptions. Pins the fix at the seam rather than at one call
    site, so a future per-name route cannot reintroduce the bare 500."""
    import inspect

    from app.routers import agents as agents_router

    source = inspect.getsource(agents_router.run_named_agent)
    assert (
        "FabricationError" in source or "_guard_rejection_http_error" in source
    ), (
        "run_named_agent still catches only LookupError — a guard rejection "
        "escapes as an unhandled 500 + traceback"
    )


# ---------------------------------------------------------------------------
# F-3 — GET /agents must reflect every implemented agent
# ---------------------------------------------------------------------------


def test_get_agents_lists_every_implemented_catalog_backend(client, auth_headers):
    names = [a["name"] for a in _list_agents(client, auth_headers)]
    missing = [b for b in _catalog_backends() if b not in names]
    assert not missing, (
        f"GET /agents omits implemented agents {missing} that "
        f"GET /agents/catalog reports as active — the sidebar Agent Pulse and "
        f"the Orchestration view read this list"
    )


def test_get_agents_includes_the_six_wave4_agents(client, auth_headers):
    """The exact six the live probe found missing."""
    names = {a["name"] for a in _list_agents(client, auth_headers)}
    for backend in (
        "compliance", "salaryIntelligence", "marketTrends", "learningFeedback",
        "companyResearch", "interviewPrep",
    ):
        assert backend in names, f"{backend!r} missing from GET /agents: {sorted(names)}"


def test_get_agents_invents_nothing(client, auth_headers):
    """The other direction — the list must not name an agent the catalog does
    not implement, and must not repeat one."""
    names = [a["name"] for a in _list_agents(client, auth_headers)]
    assert len(names) == len(set(names)), f"duplicate agent rows: {names}"
    unknown = [n for n in names if n not in set(_catalog_backends())]
    assert not unknown, f"GET /agents names non-catalog agents: {unknown}"


def test_the_agent_registry_is_derived_not_hardcoded():
    """Anti-regression pin: ``AGENT_NAMES`` must be exactly the catalog's set of
    distinct implemented backends, so wiring a new agent into the catalog can
    never again leave this list — and therefore the sidebar count — stale."""
    from app.routers.agents import AGENT_NAMES

    assert set(AGENT_NAMES) == set(_catalog_backends())


def test_the_pipeline_graph_nodes_stay_present_and_in_pipeline_order(
    client, auth_headers
):
    """The Orchestration workflow graph (apps/web/src/components/agents/
    Orchestration.tsx ``NODES``) looks each pipeline node up BY NAME in this
    list. Broadening the set must not drop or reorder any of them."""
    pipeline = [
        "supervisor", "scout", "matcher", "fitScorer", "tailor", "coverLetter",
        "storyExtractor", "emailAgent",
    ]
    names = [a["name"] for a in _list_agents(client, auth_headers)]
    assert names[: len(pipeline)] == pipeline, (
        f"pipeline nodes are no longer the leading, in-order prefix: {names}"
    )


def test_every_row_keeps_the_agent_summary_shape(client, auth_headers):
    """``AgentSummarySchema`` (apps/web/src/lib/api/agents.ts) parses every row;
    a newly added row with a missing key would break the sidebar, the topbar
    search index and the Orchestration view at once."""
    for row in _list_agents(client, auth_headers):
        assert set(row) == {
            "name",
            "status",
            "last_run",
            "approval_gated",
            "enabled",
        }, row
        assert isinstance(row["name"], str) and row["name"]
        assert isinstance(row["status"], str) and row["status"]
        assert row["last_run"] is None or isinstance(row["last_run"], str)
        assert isinstance(row["approval_gated"], bool)
        assert isinstance(row["enabled"], bool)


def test_the_agent_count_no_longer_contradicts_the_catalog(client, auth_headers):
    """The reported contradiction, pinned from both ends.

    The two numbers count DIFFERENT things and must stay reconcilable: the
    catalog's ``active`` counts CARDS (16), this list counts distinct AGENTS
    (14). The whole difference is ``fitScorer``, which powers three catalog
    facets — Match Scoring, ATS Optimization and Skill Gap — but is one agent.
    """
    from app.routers.agents import AGENT_CATALOG

    listed = _list_agents(client, auth_headers)
    counts = client.get("/agents/catalog", headers=auth_headers).json()["counts"]

    assert len(listed) != 8, (
        "GET /agents still reports the hardcoded 8 while the catalog reports "
        f"{counts['active']} active cards"
    )
    active_cards = [
        e for e in AGENT_CATALOG if e.get("backend")
    ]  # every implemented card (none paused/failed in a fresh account)
    facet_surplus = len(active_cards) - len(_catalog_backends())
    assert len(listed) + facet_surplus == counts["active"], (
        f"{len(listed)} listed agents + {facet_surplus} shared-backend facets "
        f"!= {counts['active']} active cards — the two endpoints disagree "
        f"about the agent SET, not just about card granularity"
    )
