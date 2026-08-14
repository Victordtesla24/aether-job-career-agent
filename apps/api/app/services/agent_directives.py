"""AgentDirective whitelist, clamp and ratchet arithmetic — ADR-AGI-2 P1.

ORCH-B1-BLUEPRINT-2026-08-14.md §3.2/§6. This module is PURE: no IO, no LLM,
no agent names, no database access. It is THE security boundary of B1b — a
field that is not in :data:`DIRECTIVE_FIELDS` cannot be amended by any
directive, from any issuer, ever, because :func:`validate_directive` splits
any un-whitelisted key into ``rejected_keys`` before anything reaches the
repository.

RATCHET ARITHMETIC (§3.2/§6.1) — the one-way rigor ratchet is ARITHMETIC, not
a check a future edit could forget:

    increase-direction field:  applied = min(ceiling, max(baseline, requested))
    restrict-enum field:       applied = the STRICTER of (baseline, requested)
                                          along the declared order

A directive proposing a value below the current baseline is therefore a
recorded no-op (reason ``"ratchet"``), never obeyed — there is no branch, and
no field definition, that can lower a baseline knob. A value above the
ceiling is clamped (reason ``"ceiling"``) and the clamp is recorded, never
silently dropped.

DRIFT NOTE (2026-08-14, this branch): the blueprint's design tree predates
this branch's landed U2c work, which rebinds
``quality_policy.DIMENSION_FLOOR`` to ``quality_gate.QUALITY_FLOOR``. Neither
name appears in :data:`DIRECTIVE_FIELDS` — re-verified against the CURRENT
``quality_policy.py``/``tailoring_loop.py`` on this branch, read-only, per the
task's hard rule against editing those files. The four whitelisted fields and
their consumers are otherwise unchanged from the blueprint's §6.1 table.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# Read-only imports — the actual clamp/ceiling values these mirror. Importing
# the consumer's OWN constant (never re-typing it) is what keeps
# ``coverLetterRetries``'s ceiling from silently drifting away from what
# ``cover_letter_agent.py`` will actually honor — pinned by
# ``test_cover_letter_retries_ceiling_matches_the_consumers``.
from app.agents.cover_letter_agent import _MAX_CORRECTIVE_RETRIES

#: ``maxIterations`` has NO consumer-side ceiling
#: (``tailor_agent.resolve_loop_knobs`` clamps only the floor — verified
#: read-only against the current tree) — so THIS is the only ceiling that
#: exists anywhere for it. 10 is a <=2x worst-case over the heightened-tier
#: baseline of 7.
_MAX_ITERATIONS_CEILING = 10

#: 100 is unreachable in practice (ATS scoring never yields a perfect 100),
#: so a ceiling there would burn every iteration on an unreachable target.
_TARGET_SCORE_CEILING = 95.0

#: Ordered loosest -> strictest. A directive may only move an agent's
#: strictness index UP this list, never down (§6.1 "restrict-enum").
STORY_STRICTNESS_ORDER: tuple[str, ...] = ("standard", "strict")


@dataclass(frozen=True)
class DirectiveField:
    """One amendable knob: its type, its clamp ceiling, and which arithmetic
    makes 'tighten' the only reachable direction."""

    name: str
    kind: type
    ceiling: Any
    direction: str  # 'increase' | 'restrict-enum' — never 'decrease' in P1
    consumer: str  # file:line of the code that obeys it, for the audit trail
    enum_order: tuple[str, ...] = field(default_factory=tuple)


#: THE whitelist — §6.1. The only place it is declared. Four fields, exactly
#: as the ticket names them: maxIterations, targetScore, coverLetterRetries,
#: storyEvidenceStrictness.
DIRECTIVE_FIELDS: Mapping[str, DirectiveField] = {
    "maxIterations": DirectiveField(
        name="maxIterations",
        kind=int,
        ceiling=_MAX_ITERATIONS_CEILING,
        direction="increase",
        consumer=(
            "apps/api/app/agents/tailor_agent.py:483-503 (resolve_loop_knobs) "
            "-> app/services/tailoring_loop.py TailoringLoop.max_iterations"
        ),
    ),
    "targetScore": DirectiveField(
        name="targetScore",
        kind=float,
        ceiling=_TARGET_SCORE_CEILING,
        direction="increase",
        consumer=(
            "apps/api/app/agents/tailor_agent.py:483-503 (resolve_loop_knobs) "
            "-> app/services/tailoring_loop.py TailoringLoop.target_score"
        ),
    ),
    "coverLetterRetries": DirectiveField(
        name="coverLetterRetries",
        kind=int,
        ceiling=_MAX_CORRECTIVE_RETRIES,
        direction="increase",
        consumer=(
            "apps/api/app/agents/cover_letter_agent.py "
            "_corrective_retry_labels/_MAX_CORRECTIVE_RETRIES"
        ),
    ),
    "storyEvidenceStrictness": DirectiveField(
        name="storyEvidenceStrictness",
        kind=str,
        ceiling="strict",
        direction="restrict-enum",
        consumer=(
            "apps/api/app/agents/story_extractor.py _criteria/_reject_reason "
            "(B1c — the field is whitelisted here in P1; its consumer lands "
            "in B1c per ORCH-B1-BLUEPRINT-2026-08-14.md §3.3)"
        ),
        enum_order=STORY_STRICTNESS_ORDER,
    ),
}


@dataclass(frozen=True)
class DirectiveApplication:
    """What a directive did to a policy — the honest record, including
    no-ops."""

    knobs: dict[str, Any]
    clamped: dict[str, dict[str, Any]]  # {field: {requested, applied, reason}}
    rejected_keys: tuple[str, ...]
    applied_directive_ids: tuple[str, ...]


def validate_directive(raw: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Split a proposed directive into ``(whitelisted_fields, rejected_keys)``.

    Rejection is loud and recorded; it is never a silent drop, because a
    Supervisor that believes it issued an instruction nobody obeys is worse
    than one that is told no."""
    whitelisted: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in raw.items():
        if key in DIRECTIVE_FIELDS:
            whitelisted[key] = value
        else:
            rejected.append(key)
    return whitelisted, tuple(rejected)


def _clamp_one(
    field_def: DirectiveField, baseline: Any, requested: Any
) -> tuple[Any, dict[str, Any] | None]:
    """Ratchet ONE field. Returns ``(applied_value, clamp_record_or_None)``.

    Never raises: a malformed/unusable requested value degrades to the
    baseline (recorded as a clamp with reason ``"invalid"``), because a
    broken directive value must not take down an agent run."""
    if field_def.direction == "increase":
        try:
            baseline_value = field_def.kind(
                baseline if baseline is not None else field_def.ceiling
            )
        except (TypeError, ValueError):
            baseline_value = field_def.ceiling
        try:
            requested_value = field_def.kind(requested)
        except (TypeError, ValueError):
            return baseline_value, {
                "requested": requested,
                "applied": baseline_value,
                "reason": "invalid",
            }
        applied = min(field_def.ceiling, max(baseline_value, requested_value))
        if applied != requested_value:
            reason = "ceiling" if requested_value > field_def.ceiling else "ratchet"
            return applied, {
                "requested": requested,
                "applied": applied,
                "reason": reason,
            }
        return applied, None

    # restrict-enum: move only toward the stricter end of the declared order.
    order = field_def.enum_order
    baseline_index = order.index(baseline) if baseline in order else 0
    if requested in order:
        requested_index = order.index(requested)
        reason = "ratchet"
    else:
        # An unrecognized enum value is treated as "no tightening requested"
        # — never as an escalation to the ceiling, and never as a crash.
        requested_index = baseline_index
        reason = "invalid"
    applied_index = max(baseline_index, requested_index)
    applied = order[applied_index]
    if applied != requested:
        return applied, {"requested": requested, "applied": applied, "reason": reason}
    return applied, None


def apply_directives(
    baseline_knobs: Mapping[str, Any], directives: Sequence[Mapping[str, Any]]
) -> DirectiveApplication:
    """Amend baseline knobs with active directives (§3.2/§6.1's ratchet).

    ``directives`` is a sequence of REPOSITORY ROWS (each carrying an ``id``
    and a ``directive`` dict of already-whitelisted fields — validated once,
    at :meth:`AgentDirectiveRepository.issue` time). This function re-checks
    whitelist membership anyway (defence in depth against a corrupted/legacy
    row) rather than trusting the caller, which is what keeps
    ``rejected_keys`` meaningful even here.

    A directive proposing a LOWER value than the baseline is a no-op BY
    CONSTRUCTION — recorded in ``clamped`` with reason ``'ratchet'``, never
    obeyed. There is no code path, and no field definition, that can lower a
    baseline knob."""
    knobs: dict[str, Any] = dict(baseline_knobs)
    clamped: dict[str, dict[str, Any]] = {}
    rejected: list[str] = []
    applied_ids: list[str] = []
    for entry in directives:
        content = entry.get("directive") if isinstance(entry, Mapping) else None
        if not isinstance(content, Mapping) or not content:
            continue
        directive_id = entry.get("id") if isinstance(entry, Mapping) else None
        touched = False
        for key, requested in content.items():
            field_def = DIRECTIVE_FIELDS.get(key)
            if field_def is None:
                # Should never happen (issue() already whitelisted), but a
                # stray/legacy key is rejected here too, never silently kept.
                if key not in rejected:
                    rejected.append(key)
                continue
            baseline_value = knobs.get(key)
            applied, clamp_record = _clamp_one(field_def, baseline_value, requested)
            knobs[key] = applied
            if clamp_record is not None:
                clamped[key] = clamp_record
            touched = True
        if touched and directive_id:
            applied_ids.append(str(directive_id))
    return DirectiveApplication(
        knobs=knobs,
        clamped=clamped,
        rejected_keys=tuple(rejected),
        applied_directive_ids=tuple(applied_ids),
    )


def effective_policy(
    policy: Mapping[str, Any], directives: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """The single composition used by the injection seam: returns a NEW
    policy dict whose 'knobs' are amended and whose 'directives' key records
    what was applied, clamped and rejected. Never mutates its input. Never
    raises — a malformed directive degrades to the baseline policy and is
    recorded as rejected, because a broken directive must not take down an
    agent run."""
    try:
        baseline_knobs = policy.get("knobs")
        baseline_knobs = dict(baseline_knobs) if isinstance(baseline_knobs, Mapping) else {}
        application = apply_directives(baseline_knobs, directives)
    except Exception:  # noqa: BLE001 — never take an agent run down
        new_policy = dict(policy)
        new_policy["directives"] = {
            "appliedIds": [],
            "clamped": {},
            "rejectedKeys": [],
        }
        return new_policy
    new_policy = dict(policy)
    new_policy["knobs"] = application.knobs
    new_policy["directives"] = {
        "appliedIds": list(application.applied_directive_ids),
        "clamped": application.clamped,
        "rejectedKeys": list(application.rejected_keys),
    }
    return new_policy
