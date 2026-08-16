"""Deterministic agent rigor policy — the U-AX self-improvement loop's brain.

U-PLAN.md "U-AX BUILD SPEC ADDITIONS" item 2 + "U2c/U5 ENRICHMENT MANDATE"
item 2/3 (both binding): the agents must tighten their own effort while the
measured outcome is below target, and a paying subscriber must be able to see
WHY. That imposes three hard design rules, and this module exists to satisfy
all three in one place:

1. **Deterministic and explainable.** :func:`compute_rigor_policy` is a PURE
   function of a metric snapshot — no LLM decides rigor invisibly, no clock, no
   randomness, no hidden state. The same snapshot always yields the same tier
   AND the same human-readable ``triggers`` list, which is exactly what the
   Agent Performance Policy panel renders.
2. **Honest about ignorance.** A user with almost no submitted applications has
   no trustworthy conversion rate. Reporting them as ``standard`` (i.e.
   "healthy") would fabricate confidence out of zero signal, so a distinct
   ``insufficient_data`` tier says so — and, per rule 3, still runs at the full
   shipped rigor rather than using "we don't know" as an excuse to under-try.
3. **Rigor only ever escalates.** Every tier's knobs are >= the product's
   shipped defaults (``tailoring_loop.DEFAULT_MAX_ITERATIONS`` /
   ``DEFAULT_TARGET_SCORE``, and the cover-letter agent's 2 corrective
   retries). No tier may silently relax below what users already get today.

COST BOUNDING (spend-cap interaction, binding). Per
``docs/subscription/billing-architecture.md:432`` the plan spend cap is checked
*pre-run* against accumulated spend: "A single run whose actual cost pushes
spendUsedUsd over spendCapUsd is allowed to finish ... but the next reserve
fails — the cap is a soft ceiling that halts the following run, not a mid-run
kill." A heightened tier therefore CANNOT lean on the cap to interrupt an
expensive run; it must bound its own worst case. It does, by construction:

* every knob is a small integer/float constant defined here — there is no
  unbounded "keep trying" mode;
* :data:`_HEIGHTENED` raises the tailor iteration ceiling by exactly 2 (5 -> 7,
  a <=40% worst-case increase in tailor LLM calls) and the cover-letter
  corrective retries by exactly 1 (2 -> 3, one extra draft on a run that is
  already permitted up to 4);
* the existing per-client wall-clock LLM budget (``llm_client`` budgets, armed
  once per run and shared across iterations) still bounds total live-call time
  regardless of tier, so a higher iteration ceiling cannot extend a run past
  its budget — it can only use the budget it already had more thoroughly.

The reserve-before-call quota mechanics in ``routers/agents.py`` are untouched:
this module never reserves, refunds, bills or chooses a model. It only decides
how hard the already-authorised run tries.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from app.services.quality_gate import QUALITY_FLOOR
from app.services.tailoring_loop import DEFAULT_MAX_ITERATIONS, DEFAULT_TARGET_SCORE

logger = logging.getLogger(__name__)

#: Interview-conversion target: 1 interview per 5 submitted applications (20%),
#: per the U2c/U5 ENRICHMENT MANDATE item 2. Expressed as a FRACTION because
#: that is how ``compute_rigor_policy`` receives it; the analytics endpoint
#: reports percentages and converts at its own boundary.
INTERVIEW_CONVERSION_TARGET = 0.20

#: The 10-dimensional fit floor: every dimension must be strictly ABOVE 80%
#: ("10-dimensional fit score > 80% across ALL dimensions", same mandate). A
#: dimension sitting exactly AT 80.0 has not cleared the bar and triggers.
#:
#: U2c: BOUND to ``services.quality_gate.QUALITY_FLOOR`` rather than re-typed,
#: so the floor this module escalates rigor on and the floor each individual
#: artifact is now GATED on are the same number by construction. The constant
#: lives in ``quality_gate`` (the leaf) because this module imports
#: ``tailoring_loop``, which in turn imports ``quality_gate`` — defining it
#: here would close that cycle.
DIMENSION_FLOOR = QUALITY_FLOOR

#: Below this many submitted applications the conversion rate is not a rate,
#: it is an anecdote. 5 is the smallest sample at which the 1-in-5 target is
#: even expressible: with 4 submissions "20%" cannot be observed at all, so any
#: verdict below 5 would be an artefact of the denominator rather than a
#: measurement. Reported as ``insufficient_data`` rather than guessed.
MIN_SAMPLE_SIZE = 5

#: The canonical 10 fit dimensions, in the SAME order the Job-Discovery fit
#: radar renders them (``routers/jobs.py::_build_insights``), keyed in camelCase
#: as they are snapshotted onto ``Application.dimensionScoresAtSubmission``.
#: Iterating this fixed tuple (never a dict's insertion order) is what makes
#: the ``triggers`` list byte-identical across repeated calls.
DIMENSION_KEYS: tuple[str, ...] = (
    "technicalSkills",
    "experienceLevel",
    "industryMatch",
    "roleAlignment",
    "cultureFit",
    "salaryFit",
    "locationMatch",
    "careerGrowth",
    "companyStability",
    "northStarAlign",
)

#: Human labels for the dimension keys — used verbatim in trigger strings so
#: the UI panel can render the reason without a second lookup table.
DIMENSION_LABELS: dict[str, str] = {
    "technicalSkills": "Technical Skills",
    "experienceLevel": "Experience Level",
    "industryMatch": "Industry Match",
    "roleAlignment": "Role Alignment",
    "cultureFit": "Culture Fit",
    "salaryFit": "Salary Fit",
    "locationMatch": "Location Match",
    "careerGrowth": "Career Growth",
    "companyStability": "Company Stability",
    "northStarAlign": "North Star Align",
}

TIER_STANDARD = "standard"
TIER_HEIGHTENED = "heightened"
TIER_INSUFFICIENT_DATA = "insufficient_data"

TIERS: tuple[str, ...] = (TIER_STANDARD, TIER_HEIGHTENED, TIER_INSUFFICIENT_DATA)

#: Baseline = the product's SHIPPED defaults, imported (never re-typed) from the
#: modules that own them so a future change to either default cannot leave this
#: tier silently more lenient than what users already get.
_STANDARD: dict[str, Any] = {
    "maxIterations": DEFAULT_MAX_ITERATIONS,
    "targetScore": DEFAULT_TARGET_SCORE,
    "coverLetterRetries": 2,
}

#: Escalated rigor. Deltas are deliberately small, fixed integers (see the
#: COST BOUNDING note in the module docstring): +2 tailor iterations, +3 ATS
#: points of target, +1 cover-letter corrective retry.
_HEIGHTENED: dict[str, Any] = {
    "maxIterations": DEFAULT_MAX_ITERATIONS + 2,
    "targetScore": DEFAULT_TARGET_SCORE + 3.0,
    "coverLetterRetries": 3,
}

#: "We don't know yet" is NOT a licence to try less — it inherits the standard
#: knobs exactly (rule 3 above).
_KNOBS_BY_TIER: dict[str, dict[str, Any]] = {
    TIER_STANDARD: _STANDARD,
    TIER_HEIGHTENED: _HEIGHTENED,
    TIER_INSUFFICIENT_DATA: dict(_STANDARD),
}

#: Plain-language description of what the agents do differently at each tier —
#: the "what the agents are doing differently at this tier" half of the Agent
#: Performance Policy panel (U-AX item 2a). Kept next to the knobs so the copy
#: cannot drift from the numbers it describes.
_TIER_BEHAVIOUR: dict[str, str] = {
    TIER_STANDARD: (
        "Standard rigor: résumé tailoring runs up to "
        f"{_STANDARD['maxIterations']} scoring iterations targeting an ATS score "
        f"of {_STANDARD['targetScore']:.0f}, and the cover-letter agent takes up "
        f"to {_STANDARD['coverLetterRetries']} corrective retries. These are the "
        "product's shipped defaults."
    ),
    TIER_HEIGHTENED: (
        "Heightened rigor: résumé tailoring runs up to "
        f"{_HEIGHTENED['maxIterations']} scoring iterations (instead of "
        f"{_STANDARD['maxIterations']}) targeting an ATS score of "
        f"{_HEIGHTENED['targetScore']:.0f} (instead of "
        f"{_STANDARD['targetScore']:.0f}), and the cover-letter agent takes up "
        f"to {_HEIGHTENED['coverLetterRetries']} corrective retries (instead of "
        f"{_STANDARD['coverLetterRetries']}). The truthfulness guards are "
        "unchanged — more effort never means looser evidence rules."
    ),
    TIER_INSUFFICIENT_DATA: (
        "Not enough submitted applications yet to measure a conversion rate, so "
        "no escalation decision can honestly be made. The agents run at the full "
        "standard rigor in the meantime — never less."
    ),
}


def knobs_for_tier(tier: str) -> dict[str, Any]:
    """Translate a rigor tier into the pipeline's REAL knobs.

    Returns a fresh dict every call so a caller mutating its copy cannot
    poison the module-level baselines.

    Raises ``ValueError`` on an unknown tier — never a silent default. A typo'd
    tier that quietly fell back to ``standard`` would disable the whole
    escalation loop while the panel kept claiming it was active.
    """
    try:
        knobs = _KNOBS_BY_TIER[tier]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"unknown rigor tier {tier!r} — valid tiers: {sorted(_KNOBS_BY_TIER)}"
        ) from exc
    return dict(knobs)


def tier_behaviour(tier: str) -> str:
    """The honest one-paragraph description of what ``tier`` changes."""
    try:
        return _TIER_BEHAVIOUR[tier]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"unknown rigor tier {tier!r} — valid tiers: {sorted(_TIER_BEHAVIOUR)}"
        ) from exc


def _as_float(value: Any) -> float | None:
    """Best-effort numeric coercion that NEVER invents a number.

    A non-numeric dimension score (``None``, a string, a nested dict from a
    future schema) yields ``None`` and is skipped by the floor check rather
    than being coerced to 0.0 — which would manufacture a trigger out of
    missing data.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def compute_rigor_policy(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the rigor tier for one metric snapshot. PURE and deterministic.

    ``metrics`` keys (all optional; absent/unusable inputs are reported, never
    guessed):

    * ``sampleSize`` — submitted applications the rate is computed over.
    * ``conversionRate`` — interviews / submissions, as a FRACTION (0.2 == 20%).
    * ``dimensionScores`` — ``{dimensionKey: 0..100}``; missing dimensions are
      simply not evaluated (and are counted in ``dimensionsEvaluated`` so the
      UI can say how much of the floor check was actually possible).

    Returns ``{"tier", "triggers", "dimensionsEvaluated", "knobs", "behaviour",
    "thresholds"}``. ``triggers`` is the ordered, human-readable list of the
    metrics that FORCED the tier — empty for ``standard``, which is what makes
    "why is it heightened?" answerable without reading code.
    """
    sample_size = int(_as_float(metrics.get("sampleSize")) or 0)
    raw_dimensions = metrics.get("dimensionScores") or {}
    dimensions: Mapping[str, Any] = (
        raw_dimensions if isinstance(raw_dimensions, Mapping) else {}
    )
    evaluated = [
        (key, score)
        for key in DIMENSION_KEYS
        if (score := _as_float(dimensions.get(key))) is not None
    ]

    thresholds = {
        "interviewConversionTarget": INTERVIEW_CONVERSION_TARGET,
        "dimensionFloor": DIMENSION_FLOOR,
        "minSampleSize": MIN_SAMPLE_SIZE,
    }

    if sample_size < MIN_SAMPLE_SIZE:
        return {
            "tier": TIER_INSUFFICIENT_DATA,
            "triggers": [
                f"insufficient data: {sample_size} submitted application(s) — at "
                f"least {MIN_SAMPLE_SIZE} are needed before an interview-conversion "
                "rate means anything"
            ],
            "dimensionsEvaluated": len(evaluated),
            "knobs": knobs_for_tier(TIER_INSUFFICIENT_DATA),
            "behaviour": tier_behaviour(TIER_INSUFFICIENT_DATA),
            "thresholds": thresholds,
        }

    triggers: list[str] = []
    conversion = _as_float(metrics.get("conversionRate"))
    if conversion is not None and conversion < INTERVIEW_CONVERSION_TARGET:
        triggers.append(
            f"interview conversion {conversion * 100:.1f}% is below the "
            f"{INTERVIEW_CONVERSION_TARGET * 100:.0f}% target "
            f"(1 interview per {int(round(1 / INTERVIEW_CONVERSION_TARGET))} "
            f"submitted applications), measured over {sample_size} submissions"
        )
    # Fixed DIMENSION_KEYS order (not the mapping's) => byte-identical output
    # for equal inputs, which the determinism test pins.
    for key, score in evaluated:
        if score <= DIMENSION_FLOOR:
            triggers.append(
                f"fit dimension {key} ({DIMENSION_LABELS.get(key, key)}) at "
                f"{score:.1f} is at or below the {DIMENSION_FLOOR:.0f}% floor"
            )

    tier = TIER_HEIGHTENED if triggers else TIER_STANDARD
    return {
        "tier": tier,
        "triggers": triggers,
        "dimensionsEvaluated": len(evaluated),
        "knobs": knobs_for_tier(tier),
        "behaviour": tier_behaviour(tier),
        "thresholds": thresholds,
    }


# ---------------------------------------------------------------------------
# Live metric sourcing — the impure half, kept strictly separate so the policy
# decision above stays a pure function that tests can pin exhaustively.
# ---------------------------------------------------------------------------

#: How many of the most recent snapshot-bearing submissions feed the dimension
#: average. Bounded so the query cost is constant regardless of account age.
_DIMENSION_SAMPLE_LIMIT = 50


def collect_policy_metrics(user_id: str) -> dict[str, Any]:
    """Read THIS user's real, already-instrumented outcome metrics.

    Sources, all live DB reads — nothing modelled, nothing defaulted:

    * ``sampleSize`` / ``conversionRate`` — DISTINCT-job VERIFIED-submission and
      interview counts. ``submitted`` counts only jobs with a real
      ``transmittedAt`` (an application the agent actually sent), NOT every
      non-draft row: the funnel's "left draft" population includes prepared /
      approved / recorded-but-unverified applications that never left the
      building, and computing a conversion rate over those phantoms (e.g. 0.3%
      over ~390 never-sent rows) fabricated the very signal this policy escalates
      on. With few real transmissions the sample is honestly below
      ``MIN_SAMPLE_SIZE`` and the policy returns ``insufficient_data`` rather
      than tightening rigor on fiction. ``interview``/``offer`` still count as an
      interview reached.
    * ``dimensionScores`` — the mean of the 10-dimension snapshots recorded on
      the most recent :data:`_DIMENSION_SAMPLE_LIMIT` submissions that HAVE one
      (``Application.dimensionScoresAtSubmission``). Applications submitted
      before this instrumentation existed carry NULL and are excluded rather
      than back-filled with an invented number.

    ``available`` is False (with ``reason``) when the reads themselves failed —
    the caller then still gets an honest ``insufficient_data`` verdict instead
    of a fabricated "healthy" one.
    """
    from app.db import ensure_application_submission_snapshot_columns, get_connection

    try:
        ensure_application_submission_snapshot_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    SELECT
                      COUNT(DISTINCT "jobId") FILTER (
                          WHERE "transmittedAt" IS NOT NULL) AS submitted,
                      COUNT(DISTINCT "jobId") FILTER (
                          WHERE "status" IN ('interview'::"ApplicationStatus",
                                             'offer'::"ApplicationStatus")
                      ) AS interviewed
                    FROM "Application" WHERE "userId" = %s
                    ''',
                    (user_id,),
                )
                row = cur.fetchone()
                submitted = int(row[0] or 0) if row else 0
                interviewed = int(row[1] or 0) if row else 0

                cur.execute(
                    '''
                    SELECT "dimensionScoresAtSubmission" FROM "Application"
                    WHERE "userId" = %s
                      AND "dimensionScoresAtSubmission" IS NOT NULL
                    ORDER BY "updatedAt" DESC LIMIT %s
                    ''',
                    (user_id, _DIMENSION_SAMPLE_LIMIT),
                )
                snapshots = [r[0] for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001 — an unreadable metric is reported
        logger.warning("quality_policy: metric collection failed: %s", exc)
        return {
            "available": False,
            "reason": f"policy inputs unavailable: {type(exc).__name__}",
            "sampleSize": 0,
            "conversionRate": 0.0,
            "dimensionScores": {},
            "dimensionSampleSize": 0,
        }

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            continue
        for key in DIMENSION_KEYS:
            value = _as_float(snapshot.get(key))
            if value is None:
                continue
            totals[key] = totals.get(key, 0.0) + value
            counts[key] = counts.get(key, 0) + 1

    dimension_scores = {
        key: round(totals[key] / counts[key], 2) for key in DIMENSION_KEYS if counts.get(key)
    }
    return {
        "available": True,
        "reason": None,
        "sampleSize": submitted,
        "conversionRate": (interviewed / submitted) if submitted else 0.0,
        "interviewCount": interviewed,
        "dimensionScores": dimension_scores,
        "dimensionSampleSize": len(snapshots),
    }


def resolve_policy_for_user(user_id: str) -> dict[str, Any]:
    """The live policy for ``user_id``: real metrics -> pure decision.

    The returned dict is exactly what gets stamped onto every AgentRun this
    user triggers (``AgentRun.policyTier`` + ``AgentRun.metricSnapshot``) and
    what ``GET /analytics/agent-policy`` renders — one computation, one truth,
    so "policy inputs consumed" on a run card is literally the snapshot the
    agent sourced.
    """
    metrics = collect_policy_metrics(user_id)
    if not metrics.get("available"):
        # Honest ignorance, explicitly labelled — never a silent "standard".
        return {
            "tier": TIER_INSUFFICIENT_DATA,
            "triggers": [str(metrics.get("reason") or "policy inputs unavailable")],
            "dimensionsEvaluated": 0,
            "knobs": knobs_for_tier(TIER_INSUFFICIENT_DATA),
            "behaviour": tier_behaviour(TIER_INSUFFICIENT_DATA),
            "thresholds": {
                "interviewConversionTarget": INTERVIEW_CONVERSION_TARGET,
                "dimensionFloor": DIMENSION_FLOOR,
                "minSampleSize": MIN_SAMPLE_SIZE,
            },
            "metrics": metrics,
        }
    policy = compute_rigor_policy(metrics)
    policy["metrics"] = metrics
    return policy
