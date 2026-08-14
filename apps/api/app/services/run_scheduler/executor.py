"""Plan EXECUTION — one loop, fully injected, zero agent knowledge.

The executor walks a plan built by :mod:`.planner` and drives it to a terminal
state. Everything it cannot know is handed in as a callable, which is what keeps
this file free of agents, HTTP, the database, quota and the LLM:

``dispatch(key, params)``       run one step. The caller wires this to the
                                EXISTING ``_dispatch`` → ``_record_run`` →
                                ``_execute_reserved_run`` chain, so a plan step
                                is billed, audited, heart-beaten and refunded
                                exactly like pressing Run on the agents screen.
                                There is deliberately NO quota-exemption seam in
                                this module (R-2b: the sweeps' run-count
                                exemption stays sweep-only).
``claim(key)``                  take the exclusive in-flight slot for a silo
                                step. Returns ``(token, acquired)``; a lost race
                                is an honest refusal, never a silent second run.
``release(token, key, ok)``     hand the slot back on EVERY path.
``on_state(key, state, detail)``persist the transition. Narration may only be
                                fed from a persisted transition, so this is
                                called before and after each dispatch.
``halting_reason(exc)``         ``str`` when this failure means the whole plan
                                must stop (quota exhausted — R-4: a plan that
                                presses on collects N identical 429s while the
                                first was the answer), else ``None``.

Propagation is CHARTER DATA, not code, and it has exactly two scopes:

* **the chain** — a step whose ``onRefusal`` is ``halt-chain`` takes its
  transitive dependents down with it (recorded ``not_attempted``, naming the
  predecessor). This is ``_pipeline_core``'s shipped behaviour, preserved. A
  step whose ``onRefusal`` is ``isolate`` does NOT: the rest of the plan,
  including its own dependents, carries on — which is what "a refusal is
  isolated, the plan continues" has to mean if it is to mean anything.
* **the plan** — reserved for ``halting_reason``: a quota or entitlement answer
  cannot become different later in the same plan, so continuing would collect N
  identical 429s while the first was the answer (R-4). Nothing else stops a plan.

Keeping those two apart is the difference between "discovery was already
running, so the four steps that needed it were skipped" and "discovery was
already running, so nothing ran" — the second would be true of the code and
useless to the user.

So is PARAMETER THREADING: a step's ``paramsFrom`` names the earlier step and
output field each of its run parameters comes from, so a chain can carry a real
target through without this module knowing what a "job" is. When a declared
input was never produced (the upstream step legitimately found nothing to work
on), the step is recorded ``not_attempted`` with the missing input named — the
honest answer, rather than dispatching a run guaranteed to be refused.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "STATE_COMPLETED",
    "STATE_FAILED",
    "STATE_NOT_ATTEMPTED",
    "STATE_PENDING",
    "STATE_REFUSED",
    "STATE_RUNNING",
    "STATE_SKIPPED",
    "execute_plan",
]

STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_REFUSED = "refused"
STATE_SKIPPED = "skipped"
STATE_NOT_ATTEMPTED = "not_attempted"

#: States that mean "this step produced its output". Only these satisfy a
#: dependent's precondition.
_SATISFIED = frozenset({STATE_COMPLETED})

_HALT_ON_REFUSAL = "halt-chain"


def _honest_error(exc: BaseException) -> str:
    """A short, secret-free description of a failure.

    ``detail`` is preferred (FastAPI's HTTPException carries the message the
    product already decided is safe to show); otherwise ``str(exc)``, and the
    exception class name only when the message is empty — never a traceback and
    never a raw provider payload.
    """
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    message = str(exc).strip()
    return message or type(exc).__name__


def _resolve_params(
    step: Mapping[str, Any], outputs: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    """Build a step's run parameters from earlier steps' outputs.

    Reads the step's ``paramsFrom`` triples — ``(param, source_step, field)`` —
    and returns ``(params, missing)``. ``missing`` names every declared input
    that the source step did not actually produce, so the caller can refuse
    honestly instead of dispatching a run that can only fail.

    An empty/absent value counts as missing on purpose: an upstream step that
    completed but selected nothing (no match, no eligible row) has produced no
    target, and passing ``None`` down would turn "nothing to do" into an error.
    """
    declared = step.get("paramsFrom") or ()
    params: dict[str, Any] = {}
    missing: list[str] = []
    for triple in declared:
        try:
            param, source_key, field = triple[0], triple[1], triple[2]
        except (TypeError, IndexError):  # malformed row — treat as unavailable
            missing.append(str(triple))
            continue
        value = outputs.get(source_key, {}).get(field)
        if value in (None, "", [], {}):
            missing.append(f"{source_key}.{field}")
        else:
            params[param] = value
    return params, missing


def execute_plan(
    *,
    steps: Sequence[Mapping[str, Any]],
    dispatch: Callable[[str, Mapping[str, Any]], Any],
    claim: Callable[[str], tuple[Any, bool]],
    release: Callable[[Any, str, bool], None],
    on_state: Callable[[str, str, Mapping[str, Any]], None],
    halting_reason: Callable[[BaseException], str | None],
    spacing_seconds: float = 0.0,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Execute ``steps`` in plan order and return an honest summary.

    The summary names what ran, what refused, what failed, where the plan
    halted and — crucially — what was NOT attempted, so the user is never left
    to infer that silence meant success.
    """
    import time as _time

    _sleep = sleep if sleep is not None else _time.sleep

    results: list[dict[str, Any]] = []
    state_by_key: dict[str, str] = {}
    outputs: dict[str, Mapping[str, Any]] = {}
    #: Steps that ended the chain for their dependents (``halt-chain`` and not
    #: completed). A dependent of one of these is never attempted.
    chain_broken_by: dict[str, str] = {}
    halted_at: str | None = None
    halt_reason: str | None = None
    first = True

    for step in steps:
        key = str(step["key"])
        on_refusal = str(step.get("onRefusal") or _HALT_ON_REFUSAL)
        depends_on = [str(d) for d in (step.get("dependsOn") or [])]
        exclusive = bool(step.get("exclusive"))

        def _record(state: str, detail: Mapping[str, Any] | None = None) -> None:
            payload = dict(detail or {})
            state_by_key[key] = state
            results.append({"key": key, "state": state, "detail": payload})
            on_state(key, state, payload)

        if halted_at is not None:
            _record(
                STATE_NOT_ATTEMPTED,
                {"reason": f"the plan halted at {halted_at}: {halt_reason}"},
            )
            continue

        # A predecessor that broke ITS chain takes this step with it. A
        # predecessor that merely failed under ``isolate`` does not: the plan
        # continues, and if this step genuinely needed a value that predecessor
        # was to produce, the ``paramsFrom`` check below catches it honestly.
        blocked_by = [d for d in depends_on if d in chain_broken_by]
        if blocked_by:
            _record(
                STATE_NOT_ATTEMPTED,
                {
                    "reason": (
                        "did not run because "
                        + ", ".join(f"{d} {chain_broken_by[d]}" for d in blocked_by)
                    ),
                    "blockedBy": blocked_by,
                },
            )
            chain_broken_by[key] = "was not attempted"
            continue

        params, missing_inputs = _resolve_params(step, outputs)
        if missing_inputs:
            _record(
                STATE_NOT_ATTEMPTED,
                {
                    "reason": (
                        "did not run because "
                        + ", ".join(missing_inputs)
                        + " was not produced — there was nothing for it to work on"
                    ),
                    "missingInputs": missing_inputs,
                },
            )
            if on_refusal == _HALT_ON_REFUSAL:
                chain_broken_by[key] = "had nothing to work on"
            continue

        if not first and spacing_seconds > 0:
            _sleep(spacing_seconds)
        first = False

        token: Any = None
        acquired = True
        if exclusive:
            token, acquired = claim(key)
            if not acquired:
                _record(
                    STATE_REFUSED,
                    {
                        "reason": (
                            f"{key} is already running for this account; a second "
                            "concurrent pass is the same unit of work asked for "
                            "twice, so it was not started"
                        )
                    },
                )
                if on_refusal == _HALT_ON_REFUSAL:
                    chain_broken_by[key] = "was already running"
                continue

        _record(STATE_RUNNING, {})
        try:
            output = dispatch(key, params)
        except BaseException as exc:  # noqa: BLE001 — every failure is recorded
            if exclusive:
                release(token, key, False)
            reason = _honest_error(exc)
            _record(STATE_FAILED, {"reason": reason})
            stop = halting_reason(exc)
            if stop:
                halted_at, halt_reason = key, stop
            elif on_refusal == _HALT_ON_REFUSAL:
                chain_broken_by[key] = f"failed ({reason})"
            logger.info("run-plan step %s failed: %s", key, reason)
            continue
        if exclusive:
            release(token, key, True)
        if isinstance(output, Mapping):
            outputs[key] = output
        _record(
            STATE_COMPLETED,
            {"runId": output.get("run_id") if isinstance(output, Mapping) else None},
        )

    # Collapse to the LAST recorded state per step (a step transitions
    # running -> terminal, and only the terminal one is its outcome).
    final: dict[str, dict[str, Any]] = {}
    for entry in results:
        final[entry["key"]] = entry
    ordered = [final[str(s["key"])] for s in steps if str(s["key"]) in final]
    not_attempted = [
        e["key"] for e in ordered if e["state"] in (STATE_NOT_ATTEMPTED, STATE_SKIPPED)
    ]
    # Three statuses, because two would force a lie: a plan where the spine
    # broke but nine enrichment agents ran is neither a success nor a stop.
    if halted_at is not None:
        status = "halted"
    elif all(e["state"] == STATE_COMPLETED for e in ordered):
        status = "completed"
    else:
        status = "partial"
    return {
        "status": status,
        "haltedAtStep": halted_at,
        "haltReason": halt_reason,
        "steps": ordered,
        "notAttempted": not_attempted,
        "completedCount": sum(1 for e in ordered if e["state"] == STATE_COMPLETED),
        "failedCount": sum(1 for e in ordered if e["state"] == STATE_FAILED),
        "refusedCount": sum(1 for e in ordered if e["state"] == STATE_REFUSED),
    }
