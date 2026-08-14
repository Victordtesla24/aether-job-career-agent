"""U-AGI P1-A — the Supervisor run scheduler as PURE planning (ADR-AGI-3 D1).

These tests pin the three invariants the orchestrator named, as PROPERTIES over
randomly generated charters rather than as a handful of hand-picked examples:

1. a plan never violates a ``dependsOn`` edge,
2. a ``silo`` step is never co-scheduled with anything,
3. the dedup by backend covers every requested card exactly once.

Plus the thin-kernel law (DESIGN-PRINCIPLE.md:9): the scheduler package holds
ZERO agent names — every behaviour comes from charter DATA handed in by the
caller. That is asserted by grepping the package itself, so a future
``if backend == "tailor"`` fails this suite rather than a human review.

No database, no HTTP, no LLM: the planner is a pure function.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from app.services.run_scheduler import (
    CharterError,
    PlanCycleError,
    build_plan,
    normalize_charter,
    plan_concurrency_ceiling,
    resolve_targets,
)

# ---------------------------------------------------------------------------
# Fixtures: synthetic charters (deliberately NOT the product's real one — the
# scheduler must be correct for any charter shaped like this).
# ---------------------------------------------------------------------------

SIMPLE = {
    "a": {"execClass": "silo", "siloBasis": "race-proven", "onRefusal": "halt-chain",
          "dependsOn": [], "coversCards": ["ca"]},
    "b": {"execClass": "sequential", "onRefusal": "halt-chain",
          "dependsOn": ["a"], "coversCards": ["cb1", "cb2"]},
    "c": {"execClass": "sequential", "onRefusal": "halt-chain",
          "dependsOn": ["b"], "coversCards": ["cc"]},
    "d": {"execClass": "independent", "onRefusal": "isolate",
          "dependsOn": [], "coversCards": ["cd"]},
    "e": {"execClass": "independent", "onRefusal": "isolate",
          "dependsOn": [], "coversCards": ["ce"]},
    "f": {"execClass": "independent", "onRefusal": "isolate",
          "dependsOn": [], "coversCards": ["cf"]},
}


def _random_charter(rng: random.Random, size: int) -> dict[str, dict]:
    """A random ACYCLIC charter: node ``i`` may only depend on nodes ``< i``."""
    charter: dict[str, dict] = {}
    for i in range(size):
        key = f"n{i}"
        exec_class = rng.choice(["sequential", "independent", "silo"])
        pool = [f"n{j}" for j in range(i)]
        deps = rng.sample(pool, k=min(len(pool), rng.randint(0, 2)))
        entry: dict = {
            "execClass": exec_class,
            "onRefusal": rng.choice(["halt-chain", "isolate"]),
            "dependsOn": deps,
            "coversCards": [f"card{i}_{c}" for c in range(rng.randint(1, 3))],
        }
        if exec_class == "silo":
            entry["siloBasis"] = rng.choice(["race-proven", "tier-conservative"])
        charter[key] = entry
    return charter


def _group_index_of(plan, key: str) -> int:
    return next(s.group for s in plan.steps if s.key == key)


# ---------------------------------------------------------------------------
# PROPERTY 1 — a plan never violates a dependsOn edge.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(40))
def test_property_plan_never_violates_a_depends_on_edge(seed: int) -> None:
    rng = random.Random(seed)
    raw = _random_charter(rng, rng.randint(1, 14))
    charter = normalize_charter(raw)
    plan = build_plan(charter, concurrency=rng.randint(1, 3))

    planned = {s.key for s in plan.steps}
    assert planned == set(charter), "every charter key must be planned exactly once"
    assert len(plan.steps) == len(planned), "no key may appear twice in a plan"

    for step in plan.steps:
        for dep in step.depends_on:
            if dep in planned:
                assert _group_index_of(plan, dep) < step.group, (
                    f"{step.key} (group {step.group}) is scheduled at or before its "
                    f"dependency {dep} (group {_group_index_of(plan, dep)})"
                )


def test_a_cycle_is_refused_loudly_never_silently_reordered() -> None:
    cyclic = {
        "x": {"execClass": "sequential", "onRefusal": "halt-chain",
              "dependsOn": ["y"], "coversCards": ["cx"]},
        "y": {"execClass": "sequential", "onRefusal": "halt-chain",
              "dependsOn": ["x"], "coversCards": ["cy"]},
    }
    with pytest.raises(PlanCycleError):
        build_plan(normalize_charter(cyclic))


# ---------------------------------------------------------------------------
# PROPERTY 2 — a silo step is never co-scheduled.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(40))
def test_property_a_silo_step_never_shares_a_group(seed: int) -> None:
    rng = random.Random(1000 + seed)
    charter = normalize_charter(_random_charter(rng, rng.randint(1, 14)))
    plan = build_plan(charter, concurrency=rng.randint(1, 3))

    by_group: dict[int, list] = {}
    for step in plan.steps:
        by_group.setdefault(step.group, []).append(step)

    for group, members in by_group.items():
        silos = [m for m in members if m.exec_class == "silo"]
        if silos:
            assert len(members) == 1, (
                f"group {group} co-schedules silo {silos[0].key} with "
                f"{[m.key for m in members if m.key != silos[0].key]}"
            )
            assert members[0].exclusive is True


@pytest.mark.parametrize("seed", range(30))
def test_property_no_group_ever_exceeds_the_concurrency_ceiling(seed: int) -> None:
    rng = random.Random(2000 + seed)
    charter = normalize_charter(_random_charter(rng, rng.randint(1, 14)))
    ceiling = rng.randint(1, 3)
    plan = build_plan(charter, concurrency=ceiling)
    for group in plan.groups:
        assert 1 <= len(group) <= ceiling


# ---------------------------------------------------------------------------
# PROPERTY 3 — server-side dedup by backend covers every card exactly once.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(40))
def test_property_dedup_covers_every_card_exactly_once(seed: int) -> None:
    rng = random.Random(3000 + seed)
    raw = _random_charter(rng, rng.randint(1, 14))
    charter = normalize_charter(raw)
    plan = build_plan(charter)

    all_cards = [c for e in charter.values() for c in e.covers_cards]
    covered = [c for s in plan.steps for c in s.covers_cards]
    assert sorted(covered) == sorted(all_cards)
    assert len(set(covered)) == len(covered), "a card may never be covered twice"
    assert sorted(plan.covered_cards) == sorted(all_cards)


def test_requesting_three_cards_of_one_backend_yields_ONE_dispatch() -> None:
    """R-2a as an assertion: the shipped dedup is frontend-only; this is it
    server-side. Three cards of one backend must bill ONE metered run."""
    charter = normalize_charter(SIMPLE)
    keys, collapsed, duplicates = resolve_targets(charter, ["cb1", "cb2"])
    assert keys == ("b",)
    assert collapsed["b"] == ("cb1", "cb2")
    assert duplicates == 1  # two cards, one dispatch => one collapsed duplicate

    plan = build_plan(charter, targets=keys)
    assert [s.key for s in plan.steps] == ["b"]
    assert plan.duplicate_targets_collapsed == 1
    assert sorted(plan.covered_cards) == ["cb1", "cb2"]


def test_an_unknown_card_is_refused_never_silently_dropped() -> None:
    charter = normalize_charter(SIMPLE)
    with pytest.raises(CharterError):
        resolve_targets(charter, ["no-such-card"])


# ---------------------------------------------------------------------------
# Charter validation — the data cannot rot into a lie.
# ---------------------------------------------------------------------------


def test_a_dangling_depends_on_edge_is_refused() -> None:
    bad = {"a": {"execClass": "independent", "onRefusal": "isolate",
                 "dependsOn": ["ghost"], "coversCards": ["ca"]}}
    with pytest.raises(CharterError):
        normalize_charter(bad)


def test_silo_without_a_basis_is_refused_and_basis_without_silo_too() -> None:
    with pytest.raises(CharterError):
        normalize_charter({"a": {"execClass": "silo", "onRefusal": "isolate",
                                 "dependsOn": [], "coversCards": ["ca"]}})
    with pytest.raises(CharterError):
        normalize_charter({"a": {"execClass": "independent", "onRefusal": "isolate",
                                 "siloBasis": "race-proven",
                                 "dependsOn": [], "coversCards": ["ca"]}})


def test_an_unknown_exec_class_or_refusal_mode_is_refused() -> None:
    with pytest.raises(CharterError):
        normalize_charter({"a": {"execClass": "parallel-ish", "onRefusal": "isolate",
                                 "dependsOn": [], "coversCards": ["ca"]}})
    with pytest.raises(CharterError):
        normalize_charter({"a": {"execClass": "independent", "onRefusal": "explode",
                                 "dependsOn": [], "coversCards": ["ca"]}})


def test_a_card_claimed_by_two_backends_is_refused() -> None:
    bad = {
        "a": {"execClass": "independent", "onRefusal": "isolate",
              "dependsOn": [], "coversCards": ["shared"]},
        "b": {"execClass": "independent", "onRefusal": "isolate",
              "dependsOn": [], "coversCards": ["shared"]},
    }
    with pytest.raises(CharterError):
        normalize_charter(bad)


# ---------------------------------------------------------------------------
# Concurrency ceiling + honest narration (R-3 / R-6).
# ---------------------------------------------------------------------------


def test_ceiling_is_the_minimum_of_worker_capacity_and_the_admin_dial() -> None:
    assert plan_concurrency_ceiling(worker_max_jobs=3, admin_dial=1) == 1
    assert plan_concurrency_ceiling(worker_max_jobs=3, admin_dial=9) == 3
    assert plan_concurrency_ceiling(worker_max_jobs=2, admin_dial=3) == 2
    # Never zero or negative, whatever an operator types.
    assert plan_concurrency_ceiling(worker_max_jobs=3, admin_dial=0) == 1
    assert plan_concurrency_ceiling(worker_max_jobs=0, admin_dial=-4) == 1


def test_narration_states_what_the_scheduler_DID_not_what_the_class_permits() -> None:
    """R-6: with the ceiling at 1 an ``independent`` step must not be narrated as
    running in parallel — the plan says what actually happens."""
    charter = normalize_charter(SIMPLE)
    plan = build_plan(charter, concurrency=1)
    independent = next(s for s in plan.steps if s.exec_class == "independent")
    assert "parallel" not in independent.rationale.lower() or "ceiling" in (
        independent.rationale.lower()
    )
    assert "1" in independent.rationale
    assert plan.concurrency == 1
    # Every step carries a non-empty, human-readable reason.
    for step in plan.steps:
        assert step.rationale.strip()
    assert any("per step" in n.lower() for n in plan.notes), (
        "the plan must state that budget is reserved per step, never pre-reserved"
    )


def test_a_silo_rationale_names_its_basis_and_the_db_as_the_enforcer() -> None:
    plan = build_plan(normalize_charter(SIMPLE))
    silo = next(s for s in plan.steps if s.exec_class == "silo")
    assert "race-proven" in silo.rationale
    assert "database" in silo.rationale.lower()


def test_unmet_dependencies_of_a_partial_selection_are_stated_never_hidden() -> None:
    charter = normalize_charter(SIMPLE)
    plan = build_plan(charter, targets=("c",))  # depends on b, which is not selected
    step = plan.steps[0]
    assert step.unmet_dependencies == ("b",)
    assert "b" in step.rationale


def test_a_param_edge_without_an_ordering_edge_is_refused() -> None:
    """A data edge with no ``dependsOn`` behind it would let the reader be
    scheduled before the writer — refuse it at the charter, not at 3am."""
    bad = {
        "src": {"execClass": "independent", "onRefusal": "isolate",
                "dependsOn": [], "coversCards": ["c1"]},
        "dst": {"execClass": "independent", "onRefusal": "isolate",
                "dependsOn": [], "paramsFrom": {"x": ("src", "y")},
                "coversCards": ["c2"]},
    }
    with pytest.raises(CharterError):
        normalize_charter(bad)


def test_a_param_edge_from_an_unknown_step_is_refused() -> None:
    bad = {
        "dst": {"execClass": "independent", "onRefusal": "isolate",
                "dependsOn": ["ghost"], "paramsFrom": {"x": ("ghost", "y")},
                "coversCards": ["c2"]},
    }
    with pytest.raises(CharterError):
        normalize_charter(bad)


def test_params_from_survives_onto_the_step_payload() -> None:
    charter = normalize_charter(
        {
            "src": {"execClass": "independent", "onRefusal": "isolate",
                    "dependsOn": [], "coversCards": ["c1"]},
            "dst": {"execClass": "sequential", "onRefusal": "halt-chain",
                    "dependsOn": ["src"], "paramsFrom": {"job_id": ("src", "top")},
                    "coversCards": ["c2"]},
        }
    )
    plan = build_plan(charter)
    dst = next(s for s in plan.steps if s.key == "dst")
    assert dst.params_from == (("job_id", "src", "top"),)
    assert dst.as_dict()["paramsFrom"] == [["job_id", "src", "top"]]


def test_metered_steps_are_flagged_from_data_not_guessed() -> None:
    plan = build_plan(normalize_charter(SIMPLE), metered={"b", "c"})
    metered = {s.key for s in plan.steps if s.metered}
    assert metered == {"b", "c"}
    assert plan.metered_step_count == 2


# ---------------------------------------------------------------------------
# THIN-KERNEL LAW — DESIGN-PRINCIPLE.md:9 / EXEC-CLASSES.md §6.1 test 7.
# ---------------------------------------------------------------------------


def test_the_scheduler_package_contains_zero_agent_names() -> None:
    """A single ``if backend == "tailor"`` inside the scheduler fails review
    (DESIGN-PRINCIPLE.md:9). Asserted mechanically so it cannot be argued."""
    from app.routers.agents import _EXEC_CLASS_BY_BACKEND

    package = Path(__file__).resolve().parents[1] / "app" / "services" / "run_scheduler"
    sources = sorted(package.glob("*.py"))
    assert sources, "run_scheduler package not found"

    offenders: list[str] = []
    for path in sources:
        text = path.read_text()
        for backend in _EXEC_CLASS_BY_BACKEND:
            if backend in text:
                offenders.append(f"{path.name}: {backend}")
    assert offenders == [], (
        "the scheduler must read charter DATA, never name an agent: " f"{offenders}"
    )
