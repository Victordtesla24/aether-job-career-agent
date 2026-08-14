"""The Supervisor's run scheduler — plan as DATA, one executor, zero agent names.

ADR-AGI-3 Decision 1. The repo already held four server-side schedulers plus a
client-owned batch runner; this package is the one they fold into. It is split
in two so each half can be reasoned about (and tested) alone:

* :mod:`.planner` — a pure function from charter data to an ordered, bounded
  plan. No IO of any kind.
* :mod:`.executor` — the loop that drives a plan to a terminal state, with every
  side effect (dispatch, admission claim, state persistence) injected.

Neither module names an agent: the thin-kernel law (``DESIGN-PRINCIPLE.md``
line 9) makes per-agent branching here a review failure, and the test-suite
greps this package for every backend in the charter.
"""
from __future__ import annotations

from .executor import execute_plan
from .planner import (
    EXEC_CLASSES,
    EXEC_INDEPENDENT,
    EXEC_SEQUENTIAL,
    EXEC_SILO,
    MAX_PLAN_CONCURRENCY,
    ON_REFUSAL_HALT,
    ON_REFUSAL_ISOLATE,
    CharterEntry,
    CharterError,
    PlanCycleError,
    PlanStep,
    RunPlan,
    build_plan,
    normalize_charter,
    plan_concurrency_ceiling,
    resolve_targets,
)

__all__ = [
    "EXEC_CLASSES",
    "EXEC_INDEPENDENT",
    "EXEC_SEQUENTIAL",
    "EXEC_SILO",
    "MAX_PLAN_CONCURRENCY",
    "ON_REFUSAL_HALT",
    "ON_REFUSAL_ISOLATE",
    "CharterEntry",
    "CharterError",
    "PlanCycleError",
    "PlanStep",
    "RunPlan",
    "build_plan",
    "execute_plan",
    "normalize_charter",
    "plan_concurrency_ceiling",
    "resolve_targets",
]
