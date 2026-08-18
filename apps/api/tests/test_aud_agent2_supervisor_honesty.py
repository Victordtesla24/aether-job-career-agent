"""AUD-AGENT-2 — the Orchestration Agent / supervisor card must not imply
execution it never performs.

THE LEDGER FINDING (RUN-20260818T0223Z/AUD-AGENT-2/01-scout-reproduction.log):
the supervisor backend's sequencing (``_PIPELINE_PLAN`` in
``app.routers.agents``) is a hardcoded 5-element constant — no LLM call is
ever made for it, on any run, and ``output["model"]`` is hard-forced to
``None`` for every "supervisor" ``AgentRun`` row
(``_execute_reserved_run``). The catalog card ("Orchestration Agent",
``backend="supervisor"``) IS user-switchable to a real model id through the
SAME per-agent override machinery every other role uses (ML-U1X-b), and that
choice IS a genuine, readable, persisted assignment — the honesty gap is
purely in how surfaces DESCRIBE what that assignment does today: it must
never be described as the model a run "actually runs on" or "actually
served" while the backend structurally guarantees it never will, until a
genuine planning call exists.

THIS FILE PINS (backend surface):
  1. ``GET /agents/catalog``'s ``orchestration`` entry's ``tip`` discloses the
     deterministic sequencing and does not claim the assigned model executes.
  2. The entry stays genuinely overridable (``modelOverridable: True``) — the
     fix is honest RELABELLING, not disabling the real, tested override
     machinery ML-U1X-b shipped (see ``test_u1x_b_orchestrator_role.py``).
  3. ``GET /agents/orchestration-map``'s ``orchestration`` node makes no
     competing claim about model execution either (it carries no ``model``
     field at all today — silence is not a lie, and this pins that it stays
     that way rather than growing one that contradicts the catalog tip).
"""
from __future__ import annotations


def test_orchestration_catalog_tip_discloses_deterministic_sequencing(
    client, auth_headers
):
    r = client.get("/agents/catalog", headers=auth_headers)
    assert r.status_code == 200, r.text
    entry = next(e for e in r.json()["agents"] if e["key"] == "orchestration")

    tip = entry["tip"].lower()
    assert "deterministic" in tip, entry
    # The assignment IS real (ML-U1X-b) — the honesty requirement is that the
    # tip does not claim it EXECUTES today, only that it is assigned/costs
    # nothing until a genuine planning call runs on it.
    assert "actually runs" not in tip, entry
    assert "actually served" not in tip, entry


def test_orchestration_catalog_stays_genuinely_overridable(client, auth_headers):
    """Relabel, not removal: the override machinery ML-U1X-b wired stays
    live — an honest disclosure is not a reason to disable a real choice."""
    r = client.get("/agents/catalog", headers=auth_headers)
    assert r.status_code == 200, r.text
    entry = next(e for e in r.json()["agents"] if e["key"] == "orchestration")
    assert entry["modelOverridable"] is True, entry


def test_orchestration_map_node_carries_no_competing_model_claim(
    client, auth_headers
):
    """The workflow-map payload's supervisor node makes no execution claim of
    its own to contradict the catalog tip — it names status/runnable/trend
    only, never a model."""
    r = client.get("/agents/orchestration-map", headers=auth_headers)
    assert r.status_code == 200, r.text
    node = next(
        a
        for m in r.json()["maps"]
        for stage in m["stages"]
        for a in stage["agents"]
        if a["agentKey"] == "orchestration"
    )
    assert "model" not in node, node
    assert node["backend"] == "supervisor"
