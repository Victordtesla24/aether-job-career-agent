"""Supervisor Stage-1 rules — ADR-AGI-2 P1 (ORCH-B1-BLUEPRINT-2026-08-14.md
§3.2/§6.3).

Deterministic, $0, no LLM call. ``evaluate()`` is a PURE function over the
metric snapshot ``quality_policy`` already computes (the exact dict
``resolve_policy_for_user`` returns) plus the caller's currently-active
directives — no IO, no agent names beyond the four this rule table already
names as data. ADR-AGI-1 Stage-2 (LLM escalation) is out of scope for B1b and
stays behind ``AETHER_AGI_SUPERVISOR_STAGE2`` (unset => off); this module
never imports an LLM client.

``rules_stage_evaluate(user_id)`` is the impure IO wrapper — the SOLE P1
issuance path (blueprint DEV-6: there is no free-form POST that creates an
arbitrary directive; only this function calls
``AgentDirectiveRepository.issue``). Every number a rule cites in its
rationale is read off ``policy["metrics"]``/``policy["thresholds"]`` — both
populated by real DB reads in ``quality_policy.collect_policy_metrics`` — or
off a real ``StoryRepository`` count. Nothing here is invented.

Idempotent by construction: a rule whose proposal equals the currently active
directive's content returns nothing, so re-evaluating on unchanged metrics
never churns history (S1-S3 recompute their proposal purely from the current
tier's baseline knobs, never from the existing directive's already-amended
value, so two evaluations against the same metric snapshot always produce the
identical proposal — which is what makes the equality check a real
idempotence guarantee rather than a coincidence).
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.quality_policy import (
    DIMENSION_FLOOR,
    INTERVIEW_CONVERSION_TARGET,
    MIN_SAMPLE_SIZE,
    TIER_HEIGHTENED,
    TIER_STANDARD,
)

logger = logging.getLogger(__name__)

#: Agents the Stage-1 rule table may issue a directive for or retire a
#: directive from — a closed set, so a future rule cannot silently reach a
#: fifth agent without this list (and its own test) changing too.
_RULE_TABLE_AGENTS: tuple[str, ...] = ("tailor", "coverLetter", "storyExtractor")


@dataclass(frozen=True)
class DirectiveProposal:
    """One proposed directive from the rule table — not yet issued."""

    agent_key: str
    directive: dict[str, Any]
    rationale: str
    metrics_cited: dict[str, Any]


def evaluate(
    policy: Mapping[str, Any],
    *,
    active: Mapping[str, Mapping[str, Any]],
    story_count: int | None = None,
) -> tuple[list[DirectiveProposal], list[str]]:
    """Stage-1 rule table (ordered, first/only match per agent) over the
    metric snapshot ``quality_policy`` already computes.

    ``active`` is ``{agentKey: active_directive_row}`` — the caller's current
    ``AgentDirectiveRepository.list_active`` result, grouped by agent. Returns
    ``(proposals, retire_ids)``. NO LLM CALL — this function makes none, and
    imports none.

    Conservative per ADR-AGI-2 step 1: only the ``heightened`` tier issues new
    tightening, one notch (a fixed, small delta over the tier's OWN baseline
    knob — never a compounding escalation across repeated evaluations), and
    only when the sample backing the trigger is large enough to trust
    (``MIN_SAMPLE_SIZE`` — the same floor ``quality_policy`` itself uses
    before calling a conversion rate meaningful at all).
    """
    proposals: list[DirectiveProposal] = []
    retire_ids: list[str] = []

    tier = policy.get("tier")
    knobs = policy.get("knobs") or {}
    metrics = policy.get("metrics") or {}
    thresholds = policy.get("thresholds") or {}

    target = thresholds.get("interviewConversionTarget", INTERVIEW_CONVERSION_TARGET)
    min_sample = thresholds.get("minSampleSize", MIN_SAMPLE_SIZE)
    floor = thresholds.get("dimensionFloor", DIMENSION_FLOOR)

    if tier == TIER_HEIGHTENED:
        # S1 — conversion below target with a trustworthy sample => tighten
        # tailor's iteration ceiling and ATS target, one notch.
        sample_size = metrics.get("sampleSize")
        conversion = metrics.get("conversionRate")
        if (
            isinstance(sample_size, (int, float))
            and sample_size >= min_sample
            and isinstance(conversion, (int, float))
            and conversion < target
        ):
            requested: dict[str, Any] = {
                "maxIterations": int(knobs.get("maxIterations") or 0) + 2,
                "targetScore": round(float(knobs.get("targetScore") or 0.0) + 3.0, 1),
            }
            existing = active.get("tailor")
            if existing is None or existing.get("directive") != requested:
                proposals.append(
                    DirectiveProposal(
                        agent_key="tailor",
                        directive=requested,
                        rationale=(
                            "Tighten tailoring effort — interview conversion "
                            f"{conversion * 100:.1f}% over {int(sample_size)} "
                            f"submissions against a {target * 100:.0f}% target."
                        ),
                        metrics_cited={
                            "conversionRate": conversion,
                            "sampleSize": int(sample_size),
                            "target": target,
                        },
                    )
                )

        # S2 — any single fit dimension at/below the floor => one extra
        # cover-letter corrective retry. Cites the WORST dimension so the
        # rationale points at a real, specific number.
        dimension_scores = metrics.get("dimensionScores") or {}
        below_floor = [
            (key, score)
            for key, score in dimension_scores.items()
            if isinstance(score, (int, float)) and score <= floor
        ]
        if below_floor:
            worst_key, worst_score = min(below_floor, key=lambda kv: kv[1])
            requested = {"coverLetterRetries": int(knobs.get("coverLetterRetries") or 0) + 1}
            existing = active.get("coverLetter")
            if existing is None or existing.get("directive") != requested:
                proposals.append(
                    DirectiveProposal(
                        agent_key="coverLetter",
                        directive=requested,
                        rationale=(
                            f"Tighten cover-letter correction — {worst_key} scored "
                            f"{worst_score:.1f} against the {floor:.0f} floor."
                        ),
                        metrics_cited={
                            "dimension": worst_key,
                            "score": worst_score,
                            "floor": floor,
                        },
                    )
                )

        # S3 — no evidence bank yet => hold story extraction to the strict bar.
        if story_count == 0:
            requested = {"storyEvidenceStrictness": "strict"}
            existing = active.get("storyExtractor")
            if existing is None or existing.get("directive") != requested:
                proposals.append(
                    DirectiveProposal(
                        agent_key="storyExtractor",
                        directive=requested,
                        rationale=(
                            "No evidence bank yet — hold story extraction to the "
                            "strict evidence bar so the first stories are the "
                            "good ones."
                        ),
                        metrics_cited={"storyCount": story_count},
                    )
                )

    elif tier == TIER_STANDARD:
        # S4 — metrics recovered: retire (never invert) any active directive
        # for the rule-table agents so the baseline reasserts itself. This is
        # a supersede-to-nothing, never a loosening directive — the ratchet
        # arithmetic makes issuing a lower value impossible anyway, so
        # "recovery" can only ever be expressed as retirement.
        for agent_key in _RULE_TABLE_AGENTS:
            existing = active.get(agent_key)
            if existing is not None and existing.get("id"):
                retire_ids.append(str(existing["id"]))

    # S5 (insufficient_data, or heightened with nothing tripped): no
    # proposal, no retirement — leave whatever is already active exactly as
    # it is. "We don't know yet" is not a licence to loosen OR to tighten.

    return proposals, retire_ids


def rules_stage_evaluate(user_id: str) -> dict[str, Any]:
    """The P1 issuance path (blueprint DEV-6): the ONLY function that calls
    ``AgentDirectiveRepository.issue``. Reads live metrics + active
    directives (real DB reads), applies :func:`evaluate`, and issues/retires
    directives accordingly.

    Never raises past a partial failure — a metrics-read failure degrades to
    "nothing evaluated" (``evaluated: False``), the same honesty rule
    ``quality_policy.resolve_policy_for_user`` already follows for its own
    callers, rather than a 500 reaching the caller of the evaluate endpoint.
    """
    from app.repositories.agent_directive import AgentDirectiveRepository
    from app.repositories.story import StoryRepository
    from app.services.agent_directives import validate_directive
    from app.services.quality_policy import resolve_policy_for_user

    repo = AgentDirectiveRepository()
    try:
        policy = resolve_policy_for_user(user_id)
    except Exception:  # noqa: BLE001
        logger.warning(
            "rules_stage_evaluate: policy resolution failed for %s",
            user_id, exc_info=True,
        )
        return {"issued": [], "retired": [], "evaluated": False}

    try:
        active_rows = repo.list_active(user_id)
    except Exception:  # noqa: BLE001
        logger.warning(
            "rules_stage_evaluate: directive store unreadable for %s",
            user_id, exc_info=True,
        )
        return {"issued": [], "retired": [], "evaluated": False}
    active_by_agent = {row["agentKey"]: row for row in active_rows}

    try:
        story_count: int | None = len(StoryRepository().list_by_user(user_id))
    except Exception:  # noqa: BLE001
        story_count = None

    proposals, retire_ids = evaluate(policy, active=active_by_agent, story_count=story_count)

    issued: list[dict[str, Any]] = []
    for proposal in proposals:
        whitelisted, rejected = validate_directive(proposal.directive)
        if rejected:
            # Defence in depth: the rule table above only ever emits
            # whitelisted field names, so this should be unreachable. If it
            # ever fires, the un-whitelisted keys are dropped LOUDLY (logged),
            # never silently stored.
            logger.error(
                "supervisor_rules proposed un-whitelisted keys %s for agent "
                "%s — dropped, never issued",
                rejected, proposal.agent_key,
            )
        if not whitelisted:
            continue
        directive_id = repo.issue(
            user_id,
            proposal.agent_key,
            directive=whitelisted,
            rationale=proposal.rationale,
            metrics_cited=proposal.metrics_cited,
            rejected_keys=rejected,
            issued_by="supervisor-rules",
        )
        issued.append({"id": directive_id, "agentKey": proposal.agent_key})

    retired: list[str] = []
    for directive_id in retire_ids:
        if repo.supersede(
            directive_id, reason="Metrics recovered — returning to baseline rigor."
        ):
            retired.append(directive_id)

    return {"issued": issued, "retired": retired, "evaluated": True}
