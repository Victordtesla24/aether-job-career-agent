"""Pure PLANNING for the Supervisor's run scheduler (ADR-AGI-3 Decision 1).

This module turns CHARTER DATA into a RunPlan. It knows nothing about agents,
HTTP, the database, quotas or the LLM — every behaviour is derived from the
fields the caller hands in:

``execClass``   ``sequential`` | ``independent`` | ``silo`` — governs ADMISSION
                (fan-out inside the concurrency ceiling vs an exclusive slot).
``dependsOn``   hard topological predecessors. Orthogonal to the class: it is
                the ordering input for EVERY class.
``onRefusal``   ``halt-chain`` | ``isolate`` — governs PROPAGATION, read by the
                executor, never by this module.
``coversCards`` the catalog cards one dispatch accounts for. Moving this fact
                server-side is what stops a plan that iterates catalog keys from
                billing three metered runs for one unit of work (R-2a).
``siloBasis``   ``race-proven`` | ``tier-conservative`` — present iff the class
                is ``silo``, so the plan can state WHY a step is exclusive
                instead of claiming a race that was never demonstrated.
``paramsFrom``  ``{param: (source_step, output_field)}`` — how a step gets its
                run parameters from an EARLIER step's output. Declaring it as
                data is what lets the executor thread a chain's real target
                through without a single ``if key == ...``; the source must be a
                declared ``dependsOn`` predecessor, so the ordering that makes
                the value available is the same ordering the plan already
                guarantees.

The thin-kernel law (``DESIGN-PRINCIPLE.md`` line 9) is what makes this file
worth its length: a single ``if key == "<some agent>"`` here would be per-agent
branching wearing a scheduler's clothes. The test-suite greps this package for
every backend name in the charter and fails on a hit.

Honesty rule for narration (R-6): a step's ``rationale`` describes what the
scheduler DID — the ceiling and spacing actually in force — never what its class
would permit on a bigger machine.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

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
    "normalize_charter",
    "plan_concurrency_ceiling",
    "resolve_targets",
]

EXEC_SEQUENTIAL = "sequential"
EXEC_INDEPENDENT = "independent"
EXEC_SILO = "silo"
EXEC_CLASSES = frozenset({EXEC_SEQUENTIAL, EXEC_INDEPENDENT, EXEC_SILO})

ON_REFUSAL_HALT = "halt-chain"
ON_REFUSAL_ISOLATE = "isolate"
ON_REFUSAL_MODES = frozenset({ON_REFUSAL_HALT, ON_REFUSAL_ISOLATE})

SILO_BASES = frozenset({"race-proven", "tier-conservative"})

#: Hard ceiling on plan concurrency: the ARQ worker's ``max_jobs``. A plan may
#: never claim more parallelism than the machine can actually run — on a 2-CPU
#: host that would make ``independent`` a decorative label (R-3/R-6).
MAX_PLAN_CONCURRENCY = 3


class CharterError(ValueError):
    """The charter data is inconsistent — refused loudly, never worked around."""


class PlanCycleError(CharterError):
    """``dependsOn`` contains a cycle, so no honest order exists."""


@dataclass(frozen=True)
class CharterEntry:
    """One validated charter row. Data only — never a callable."""

    key: str
    exec_class: str
    depends_on: tuple[str, ...]
    covers_cards: tuple[str, ...]
    on_refusal: str
    silo_basis: str | None = None
    enriched_by: tuple[str, ...] = ()
    params_from: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class PlanStep:
    """One step of a plan, with the reason it sits exactly here."""

    key: str
    exec_class: str
    depends_on: tuple[str, ...]
    covers_cards: tuple[str, ...]
    on_refusal: str
    group: int
    exclusive: bool
    silo_basis: str | None
    unmet_dependencies: tuple[str, ...]
    metered: bool
    rationale: str
    params_from: tuple[tuple[str, str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "paramsFrom": [list(p) for p in self.params_from],
            "execClass": self.exec_class,
            "dependsOn": list(self.depends_on),
            "coversCards": list(self.covers_cards),
            "onRefusal": self.on_refusal,
            "group": self.group,
            "exclusive": self.exclusive,
            "siloBasis": self.silo_basis,
            "unmetDependencies": list(self.unmet_dependencies),
            "metered": self.metered,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class RunPlan:
    """An ordered, bounded, self-describing plan. Nothing has run yet."""

    steps: tuple[PlanStep, ...]
    groups: tuple[tuple[str, ...], ...]
    concurrency: int
    spacing_seconds: float
    covered_cards: tuple[str, ...]
    collapsed_cards: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    duplicate_targets_collapsed: int = 0
    metered_step_count: int = 0
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.as_dict() for s in self.steps],
            "groups": [list(g) for g in self.groups],
            "concurrency": self.concurrency,
            "spacingSeconds": self.spacing_seconds,
            "coveredCards": list(self.covered_cards),
            "collapsedCards": {k: list(v) for k, v in self.collapsed_cards.items()},
            "duplicateTargetsCollapsed": self.duplicate_targets_collapsed,
            "meteredStepCount": self.metered_step_count,
            "notes": list(self.notes),
        }


def _as_tuple(value: Any, *, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise CharterError(f"{where} must be a sequence of strings, got {value!r}")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CharterError(f"{where} contains a non-string member: {item!r}")
        out.append(item)
    return tuple(out)


def _params_from(key: str, value: Any) -> tuple[tuple[str, str, str], ...]:
    """Validate ``{param: (source_step, output_field)}`` into ordered triples."""
    if not value:
        return ()
    if not isinstance(value, Mapping):
        raise CharterError(
            f"{key!r}.paramsFrom must be a mapping of param -> (step, field)"
        )
    out: list[tuple[str, str, str]] = []
    for param, source in value.items():
        if (
            not isinstance(param, str)
            or isinstance(source, str)
            or not isinstance(source, Iterable)
        ):
            raise CharterError(f"{key!r}.paramsFrom[{param!r}] is malformed")
        pair = tuple(source)
        if len(pair) != 2 or not all(isinstance(p, str) and p for p in pair):
            raise CharterError(
                f"{key!r}.paramsFrom[{param!r}] must be (source_step, output_field)"
            )
        out.append((param, pair[0], pair[1]))
    return tuple(out)


def normalize_charter(raw: Mapping[str, Mapping[str, Any]]) -> dict[str, CharterEntry]:
    """Validate charter DATA into :class:`CharterEntry` rows.

    Every rule enforced here exists because breaking it would make the plan lie:
    an unknown ``execClass`` would silently fan out a side-effecting agent; a
    dangling ``dependsOn`` would under-constrain the order; a card claimed twice
    would double-bill (R-2a); a ``silo`` without a ``siloBasis`` would assert a
    race nobody demonstrated.

    Insertion order is preserved and is the plan's deterministic tie-break, so
    the same charter always yields the same plan.
    """
    if not isinstance(raw, Mapping):
        raise CharterError("charter must be a mapping of key -> fields")

    entries: dict[str, CharterEntry] = {}
    seen_cards: dict[str, str] = {}
    for key, fields in raw.items():
        if not isinstance(fields, Mapping):
            raise CharterError(f"charter row {key!r} must be a mapping")
        exec_class = fields.get("execClass")
        if exec_class not in EXEC_CLASSES:
            raise CharterError(
                f"{key!r}: execClass must be one of {sorted(EXEC_CLASSES)}, "
                f"got {exec_class!r}"
            )
        on_refusal = fields.get("onRefusal")
        if on_refusal not in ON_REFUSAL_MODES:
            raise CharterError(
                f"{key!r}: onRefusal must be one of {sorted(ON_REFUSAL_MODES)}, "
                f"got {on_refusal!r}"
            )
        silo_basis = fields.get("siloBasis") or None
        if (exec_class == EXEC_SILO) != bool(silo_basis):
            raise CharterError(
                f"{key!r}: siloBasis must be present exactly when execClass is "
                f"{EXEC_SILO!r} (execClass={exec_class!r}, siloBasis={silo_basis!r})"
            )
        if silo_basis is not None and silo_basis not in SILO_BASES:
            raise CharterError(
                f"{key!r}: siloBasis must be one of {sorted(SILO_BASES)}, "
                f"got {silo_basis!r}"
            )
        cards = _as_tuple(fields.get("coversCards"), where=f"{key!r}.coversCards")
        if not cards:
            raise CharterError(f"{key!r}: coversCards must name at least one card")
        for card in cards:
            if card in seen_cards:
                raise CharterError(
                    f"card {card!r} is claimed by both {seen_cards[card]!r} and "
                    f"{key!r} — one card, one dispatch (R-2a)"
                )
            seen_cards[card] = key
        entries[key] = CharterEntry(
            key=key,
            exec_class=exec_class,
            depends_on=_as_tuple(fields.get("dependsOn"), where=f"{key!r}.dependsOn"),
            covers_cards=cards,
            on_refusal=on_refusal,
            silo_basis=silo_basis,
            enriched_by=_as_tuple(fields.get("enrichedBy"), where=f"{key!r}.enrichedBy"),
            params_from=_params_from(key, fields.get("paramsFrom")),
        )

    for entry in entries.values():
        for label, edges in (
            ("dependsOn", entry.depends_on),
            ("enrichedBy", entry.enriched_by),
        ):
            for target in edges:
                if target not in entries:
                    raise CharterError(
                        f"{entry.key!r}.{label} points at unknown key {target!r}"
                    )
        if entry.key in entry.depends_on:
            raise CharterError(f"{entry.key!r} depends on itself")
        for param, source_key, _field in entry.params_from:
            if source_key not in entries:
                raise CharterError(
                    f"{entry.key!r}.paramsFrom[{param!r}] reads from unknown step "
                    f"{source_key!r}"
                )
            if source_key not in entry.depends_on:
                # Otherwise the plan could schedule the reader before the
                # writer and the value would simply never be there — a data
                # edge with no ordering edge is a race waiting to be found.
                raise CharterError(
                    f"{entry.key!r}.paramsFrom[{param!r}] reads from "
                    f"{source_key!r}, which is not in its dependsOn"
                )
    return entries


def resolve_targets(
    charter: Mapping[str, CharterEntry], cards: Sequence[str]
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]], int]:
    """Map requested CARDS onto the deduplicated set of steps that cover them.

    This is the server-side half of R-2a. Returns
    ``(keys, {key: cards it covers from this request}, duplicates_collapsed)``.
    ``duplicates_collapsed`` counts the requests that did NOT become their own
    dispatch, so the caller can state coverage instead of quietly hiding it.

    An unknown card is an error: silently dropping it would let a caller believe
    work was planned that never was.
    """
    index: dict[str, str] = {}
    for key, entry in charter.items():
        for card in entry.covers_cards:
            index[card] = key

    ordered: list[str] = []
    collapsed: dict[str, list[str]] = {}
    requested = 0
    for card in cards:
        owner = index.get(card)
        if owner is None:
            raise CharterError(f"no step covers card {card!r}")
        requested += 1
        if owner not in collapsed:
            collapsed[owner] = []
            ordered.append(owner)
        if card not in collapsed[owner]:
            collapsed[owner].append(card)
    return (
        tuple(ordered),
        {k: tuple(v) for k, v in collapsed.items()},
        requested - len(ordered),
    )


def plan_concurrency_ceiling(*, worker_max_jobs: int, admin_dial: int) -> int:
    """``min(worker capacity, operator dial, module ceiling)``, floored at 1.

    Parallelism ships as an operator dial that starts at 1 (identical to today's
    behaviour). Whatever an operator types, a plan can never claim more slots
    than the worker owns, and can never claim zero.
    """
    values = [MAX_PLAN_CONCURRENCY]
    for candidate in (worker_max_jobs, admin_dial):
        try:
            values.append(int(candidate))
        except (TypeError, ValueError):
            continue
    return max(1, min(values))


def _topological_order(
    charter: Mapping[str, CharterEntry], selected: Sequence[str]
) -> list[str]:
    """A topological order over the INDUCED subgraph, or raise on a cycle.

    PRIORITY-respecting Kahn: among the steps whose predecessors are all placed,
    the one earliest in charter order wins. That choice is what makes the plan
    readable as well as correct. The obvious alternative — grouping by
    longest-path depth — is equally valid topologically and produces a plan in
    which every dependency-free agent runs before the second step of the
    application chain, i.e. the user's actual pipeline finishes last. Same
    guarantees, worse story; the charter's own order is the tie-break instead.
    """
    chosen = set(selected)
    priority = {key: i for i, key in enumerate(charter)}
    indegree = {
        key: sum(1 for d in charter[key].depends_on if d in chosen) for key in selected
    }
    dependents: dict[str, list[str]] = {key: [] for key in selected}
    for key in selected:
        for dep in charter[key].depends_on:
            if dep in chosen:
                dependents[dep].append(key)

    ready = [key for key in selected if indegree[key] == 0]
    order: list[str] = []
    while ready:
        ready.sort(key=lambda k: priority[k])
        key = ready.pop(0)
        order.append(key)
        for child in dependents[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(order) != len(selected):
        stuck = sorted(k for k in selected if indegree[k] > 0)
        raise PlanCycleError(
            "dependsOn contains a cycle; no honest execution order exists for "
            f"{stuck}"
        )
    return order


def _rationale(
    entry: CharterEntry,
    *,
    group: int,
    group_count: int,
    concurrency: int,
    in_plan_deps: tuple[str, ...],
    unmet: tuple[str, ...],
    spacing_seconds: float,
    metered: bool,
) -> str:
    parts: list[str] = []
    if entry.exec_class == EXEC_SILO:
        parts.append(
            f"Exclusive slot: at most one {entry.key} run per user may be in "
            f"flight ({entry.silo_basis}), and the database enforces it — this "
            "step shares its slot with nothing."
        )
    elif entry.exec_class == EXEC_SEQUENTIAL:
        parts.append(
            "Runs in order on the application spine; a refusal here ends the "
            "chain."
            if entry.on_refusal == ON_REFUSAL_HALT
            else "Runs in order on the application spine."
        )
    else:
        parts.append(
            "Eligible for concurrent execution; this plan runs at a concurrency "
            f"ceiling of {concurrency}, so it is scheduled in group "
            f"{group + 1} of {group_count}."
        )
    if in_plan_deps:
        parts.append(
            "Scheduled after " + ", ".join(in_plan_deps) + " — its input is "
            "produced by them."
        )
    if unmet:
        parts.append(
            "Depends on " + ", ".join(unmet) + ", which this run does not "
            "include: the step still runs, on whatever those agents left behind."
        )
    if len(entry.covers_cards) > 1:
        parts.append(
            f"One dispatch accounts for {len(entry.covers_cards)} catalog cards "
            f"({', '.join(entry.covers_cards)}) — they share a backend, so "
            "running them separately would bill the same work more than once."
        )
    parts.append(
        "Consumes the plan's normal run allowance, reserved at this step."
        if metered
        else "Makes no model call, so it reserves no paid run."
    )
    if spacing_seconds > 0 and group > 0:
        parts.append(f"Starts {spacing_seconds:g}s after the previous step.")
    return " ".join(parts)


def build_plan(
    charter: Mapping[str, CharterEntry],
    *,
    targets: Sequence[str] | None = None,
    concurrency: int = 1,
    spacing_seconds: float = 0.0,
    metered: Iterable[str] = (),
    collapsed_cards: Mapping[str, tuple[str, ...]] | None = None,
) -> RunPlan:
    """Build the plan for ``targets`` (default: the whole charter).

    Guarantees, each pinned by a property test:

    * every step is scheduled strictly AFTER every ``dependsOn`` predecessor
      that is also in the plan;
    * a ``silo`` step is alone in its group;
    * no group exceeds ``concurrency``;
    * the union of ``coversCards`` covers every requested card exactly once.

    Nothing is dispatched, reserved or billed here — a plan is a description.
    """
    selected = list(charter) if targets is None else list(dict.fromkeys(targets))
    for key in selected:
        if key not in charter:
            raise CharterError(f"unknown plan target {key!r}")
    concurrency = max(1, int(concurrency))
    metered_keys = set(metered)

    order = _topological_order(charter, selected)

    # Greedy grouping over that order. A step opens a new group when it is a
    # silo (exclusive slot), when one of its dependencies is in the group being
    # filled (a dependency must always be in an EARLIER group), or when the
    # group is already at the concurrency ceiling.
    groups: list[tuple[str, ...]] = []
    current: list[str] = []
    for key in order:
        entry = charter[key]
        is_silo = entry.exec_class == EXEC_SILO
        depends_on_current = any(d in current for d in entry.depends_on)
        if current and (is_silo or depends_on_current or len(current) >= concurrency):
            groups.append(tuple(current))
            current = []
        if is_silo:
            groups.append((key,))
            continue
        current.append(key)
    if current:
        groups.append(tuple(current))

    chosen = set(selected)
    steps: list[PlanStep] = []
    for group_index, group in enumerate(groups):
        for key in group:
            entry = charter[key]
            in_plan_deps = tuple(d for d in entry.depends_on if d in chosen)
            unmet = tuple(d for d in entry.depends_on if d not in chosen)
            is_metered = key in metered_keys
            steps.append(
                PlanStep(
                    key=key,
                    exec_class=entry.exec_class,
                    depends_on=entry.depends_on,
                    covers_cards=entry.covers_cards,
                    on_refusal=entry.on_refusal,
                    group=group_index,
                    exclusive=entry.exec_class == EXEC_SILO,
                    silo_basis=entry.silo_basis,
                    unmet_dependencies=unmet,
                    metered=is_metered,
                    params_from=entry.params_from,
                    rationale=_rationale(
                        entry,
                        group=group_index,
                        group_count=len(groups),
                        concurrency=concurrency,
                        in_plan_deps=in_plan_deps,
                        unmet=unmet,
                        spacing_seconds=spacing_seconds,
                        metered=is_metered,
                    ),
                )
            )

    covered = tuple(card for step in steps for card in step.covers_cards)
    metered_count = sum(1 for s in steps if s.metered)
    notes = (
        f"Concurrency ceiling {concurrency}: no more than {concurrency} step(s) "
        "are ever in flight, whatever a step's class permits.",
        f"Steps are spaced {spacing_seconds:g}s apart so a plan cannot saturate "
        "the worker.",
        "Budget is reserved per step at dispatch and refunded on an honest "
        "failure — the plan never pre-reserves work it may not perform.",
        f"{len(steps)} dispatch(es) account for {len(covered)} catalog card(s); "
        "cards that share a backend are covered by one run, not billed twice.",
        "A silo step holds an exclusive slot enforced by the database, not by a "
        "disabled button.",
    )
    return RunPlan(
        steps=tuple(steps),
        groups=tuple(groups),
        concurrency=concurrency,
        spacing_seconds=spacing_seconds,
        covered_cards=covered,
        collapsed_cards=dict(collapsed_cards or {}),
        # Derived, never passed in: the number of catalog cards that did NOT
        # become their own dispatch. This IS the R-2a saving, stated rather than
        # hidden — 21 cards over 19 steps means two cards were covered by a run
        # they share a backend with instead of being billed a second time.
        duplicate_targets_collapsed=len(covered) - len(steps),
        metered_step_count=metered_count,
        notes=notes,
    )
