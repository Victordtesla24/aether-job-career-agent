"""U-AGI P1-A — the execution-class CHARTER DATA cannot rot into a lie.

Every assertion here is one of the seven the R-8 classifier demanded
(``uat/reports/evidence/market-perf/u-agi/p1a/EXEC-CLASSES.md`` §6.1), pinned so
that adding an agent, re-wiring a card, or extending the silo set without its
database backstop fails the build instead of shipping a decorative field.

No database, no HTTP: this is a data-integrity suite over module constants.
"""
from __future__ import annotations

import pytest

from app.repositories.background_jobs import _SINGLETON_AGENTS
from app.routers.agents import (
    _EXEC_CLASS_BY_BACKEND,
    _LLM_TIER_BY_BACKEND,
    _ROLE_MODEL_BACKENDS,
    _RUNNABLE_BACKENDS,
    AGENT_CATALOG,
)
from app.services.llm_client import OPERATOR_SCOPED_AGENT_KEYS
from app.services.run_scheduler import build_plan, normalize_charter

#: U-AGI §5.3 tier-3 real-world actors (approval-gated, side-effecting).
T3_BACKENDS = frozenset(
    {"submission", "emailAgent", "recruiterOutreach", "reference", "notification"}
)


def test_1_every_runnable_backend_is_classified_and_nothing_else_is() -> None:
    """A newly wired agent may not ship unclassified, and a classification may
    not survive its agent's removal."""
    assert set(_EXEC_CLASS_BY_BACKEND) == set(_RUNNABLE_BACKENDS)
    assert len(_EXEC_CLASS_BY_BACKEND) == 19
    # ``supervisor`` builds the plan; it is never a STEP in one.
    assert "supervisor" not in _EXEC_CLASS_BY_BACKEND


def test_2_covers_cards_is_the_whole_catalog_minus_orchestration_no_duplicates() -> None:
    """R-2a as an assertion: the shipped dedup is frontend-only, so the SERVER
    plan must account for every card exactly once or it double-bills."""
    covered: list[str] = []
    for entry in _EXEC_CLASS_BY_BACKEND.values():
        covered.extend(entry["coversCards"])
    assert len(covered) == len(set(covered)), "a card is claimed by two backends"

    catalog_keys = {a["key"] for a in AGENT_CATALOG}
    assert set(covered) == catalog_keys - {"orchestration"}
    assert len(catalog_keys) == 22
    assert len(covered) == 21


def test_3_every_edge_points_at_a_classified_backend() -> None:
    for backend, entry in _EXEC_CLASS_BY_BACKEND.items():
        for field in ("dependsOn", "enrichedBy"):
            for target in entry.get(field, ()):
                assert target in _EXEC_CLASS_BY_BACKEND, (
                    f"{backend}.{field} points at unknown backend {target!r}"
                )


def test_4_the_depends_on_graph_is_acyclic_and_plannable() -> None:
    plan = build_plan(normalize_charter(_EXEC_CLASS_BY_BACKEND))
    assert len(plan.steps) == 19
    assert sorted(plan.covered_cards) == sorted(
        {a["key"] for a in AGENT_CATALOG} - {"orchestration"}
    )


def test_5_silo_class_is_backed_by_the_database_singleton_guard() -> None:
    """F-R8-1: the ``silo`` field is DECORATIVE unless the partial unique index
    actually covers the same set. Pin both halves together."""
    silos = {
        b for b, e in _EXEC_CLASS_BY_BACKEND.items() if e["execClass"] == "silo"
    }
    assert silos == {
        "scout", "submission", "emailAgent", "notification",
        "recruiterOutreach", "reference",
    }
    assert set(_SINGLETON_AGENTS) == silos, (
        "the DB singleton set and the charter silo set must be one decision"
    )


def test_5b_silo_basis_is_present_exactly_when_the_class_is_silo() -> None:
    for backend, entry in _EXEC_CLASS_BY_BACKEND.items():
        is_silo = entry["execClass"] == "silo"
        has_basis = bool(entry.get("siloBasis"))
        assert is_silo == has_basis, backend
        if is_silo:
            assert entry["siloBasis"] in {"race-proven", "tier-conservative"}


def test_6_every_tier3_real_world_actor_is_siloed() -> None:
    """U-AGI §5.4 tier/class consistency — an approval-gated real-world actor
    may never be fanned out."""
    for backend in T3_BACKENDS:
        assert _EXEC_CLASS_BY_BACKEND[backend]["execClass"] == "silo", backend


def test_on_refusal_is_declared_for_every_backend() -> None:
    for backend, entry in _EXEC_CLASS_BY_BACKEND.items():
        assert entry["onRefusal"] in {"halt-chain", "isolate"}, backend
    # The application spine halts; everything else is isolated.
    halting = {
        b for b, e in _EXEC_CLASS_BY_BACKEND.items() if e["onRefusal"] == "halt-chain"
    }
    assert halting == {"scout", "fitScorer", "matcher", "tailor", "coverLetter"}


def test_the_charter_is_data_and_carries_no_behaviour() -> None:
    """DESIGN-PRINCIPLE.md:7 — a charter is DATA. Anything callable in it is
    per-agent code wearing a data costume."""
    for backend, entry in _EXEC_CLASS_BY_BACKEND.items():
        assert isinstance(entry, dict), backend
        for key, value in entry.items():
            assert isinstance(value, (str, tuple, list, dict)), f"{backend}.{key}"
            assert not callable(value), f"{backend}.{key} is callable"
            if isinstance(value, dict):
                for inner in value.values():
                    assert not callable(inner), f"{backend}.{key} holds a callable"


def test_a_param_edge_always_has_an_ordering_edge_behind_it() -> None:
    """A data edge with no ``dependsOn`` edge is a race waiting to be found:
    the reader could be scheduled before the writer."""
    for backend, entry in _EXEC_CLASS_BY_BACKEND.items():
        for param, (source, _field) in (entry.get("paramsFrom") or {}).items():
            assert source in entry["dependsOn"], f"{backend}.paramsFrom[{param}]"


def test_the_drafting_steps_take_their_target_from_the_matcher() -> None:
    """The value ``_pipeline_core`` threads by hand is charter data here, so a
    plan carries a real target without the scheduler knowing what a job is."""
    for backend in ("tailor", "coverLetter"):
        assert _EXEC_CLASS_BY_BACKEND[backend]["paramsFrom"] == {
            "job_id": ("matcher", "top_job_id")
        }


def test_operator_scoped_role_set_matches_the_role_model_backends() -> None:
    """F7: the credential resolver and the model-assignment table must name the
    SAME operator role, or one of them is enforcing a different rule."""
    assert set(_ROLE_MODEL_BACKENDS) == set(OPERATOR_SCOPED_AGENT_KEYS)
    assert OPERATOR_SCOPED_AGENT_KEYS == frozenset({"supervisor"})
    # An operator role is never metered as a per-call tier.
    for role in OPERATOR_SCOPED_AGENT_KEYS:
        assert role not in _LLM_TIER_BY_BACKEND


def test_the_plan_job_key_the_router_writes_is_the_one_the_worker_routes() -> None:
    """Two literals, one decision: a mismatch would enqueue a job nothing
    executes, and the plan would sit in ``planned`` looking like it was queued."""
    from app.routers.agents import _ORCH_PLAN_AGENT_KEY as router_key
    from app.workers.tasks import _ORCH_PLAN_AGENT_KEY as worker_key

    assert router_key == worker_key == "orchestrationPlan"
    # It must NOT be a backend name, or ``_call_is_metered`` would meter the
    # composite itself on top of its own steps.
    assert router_key not in _EXEC_CLASS_BY_BACKEND
    assert router_key not in _LLM_TIER_BY_BACKEND


def test_the_plan_ceiling_never_exceeds_the_worker_the_plan_runs_on() -> None:
    """R-3: a plan that claims more slots than the worker owns would narrate
    parallelism the machine cannot deliver."""
    from app.services.run_scheduler import MAX_PLAN_CONCURRENCY
    from app.workers.settings import WorkerSettings

    assert MAX_PLAN_CONCURRENCY == WorkerSettings.max_jobs


@pytest.mark.parametrize("ceiling", [1, 2, 3])
def test_the_real_charter_plans_the_pipeline_spine_in_topological_order(
    ceiling: int,
) -> None:
    plan = build_plan(normalize_charter(_EXEC_CLASS_BY_BACKEND), concurrency=ceiling)
    order = {step.key: step.group for step in plan.steps}
    assert order["scout"] < order["fitScorer"] < order["matcher"]
    assert order["matcher"] < order["tailor"] < order["coverLetter"]
    assert order["tailor"] < order["submission"]
    assert order["coverLetter"] < order["submission"]
    # fitScorer's ONE dispatch covers three cards (the R-2a double-bill surface).
    fit = next(s for s in plan.steps if s.key == "fitScorer")
    assert sorted(fit.covers_cards) == ["atsOptimization", "matchScoring", "skillGap"]


def test_the_plan_runs_the_application_pipeline_BEFORE_the_enrichment_fanout() -> None:
    """A depth-first grouping is equally valid topologically and produces a plan
    where every dependency-free agent runs before the second step of the user's
    actual pipeline — correct, and a bad plan. Pin the readable order."""
    plan = build_plan(normalize_charter(_EXEC_CLASS_BY_BACKEND), concurrency=1)
    ordered = [s.key for s in plan.steps]
    assert ordered[:6] == [
        "scout", "fitScorer", "matcher", "tailor", "coverLetter", "submission",
    ]
    # Every enrichment agent comes after the whole spine.
    for enrichment in ("marketTrends", "companyResearch", "interviewPrep"):
        assert ordered.index(enrichment) > ordered.index("submission")


def test_the_dedup_saving_is_stated_not_hidden() -> None:
    plan = build_plan(normalize_charter(_EXEC_CLASS_BY_BACKEND))
    assert len(plan.steps) == 19
    assert len(plan.covered_cards) == 21
    assert plan.duplicate_targets_collapsed == 2
