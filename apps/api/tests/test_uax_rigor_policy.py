"""U-AX build spec items 2+3 — the deterministic rigor-policy module and its
knob-mapping enforcement seam. Failing tests written BEFORE implementation.

Per the U-AX BUILD SPEC ADDITIONS (U-PLAN.md item 2) and the feedback-loop
scout's design map (uat/reports/evidence/agents-uplift/u-ax-discovery/ —
the "loop" result in
/tmp/claude-2000/.../tasks/w4kr2vlps.output):

  * ``compute_rigor_policy(metrics) -> {"tier": ..., "triggers": [...]}`` —
    a PURE, deterministic function (no LLM self-deciding rigor invisibly).
    Pinned boundaries: conversion rate vs the 20% target
    (U2c/U5 ENRICHMENT MANDATE item 2: "1 interview per 5 submitted
    applications"), each of the 10 fit-radar dimension scores vs an 80% floor
    (>80% target per the same mandate), and an honest "insufficient_data"
    tier when the sample is too small to trust a rate at all (never silently
    reported as "standard" on zero signal — the live DB shows conversion is
    genuinely 0/235 today, which is a DATA fact, not something the policy may
    paper over as "healthy").
  * A knob-mapping function translating a tier into the tailor/cover
    pipeline's real knobs, per the scout's KNOB INVENTORY:
      - ``tailoring_loop.DEFAULT_MAX_ITERATIONS`` (5) / ``DEFAULT_TARGET_SCORE``
        (85.0) — already ``TailoringLoop`` constructor params, never overridden
        by the sole call site (``tailor_agent.py:460``).
      - cover-letter corrective retries — currently HARDCODED
        ``for attempt in ("retry", "retry2")`` (2 retries,
        ``cover_letter_agent.py:1599``), not a parameter today.
    A heightened tier must raise BOTH above their standard-tier baseline;
    it must never lower them (rigor only escalates, never silently relaxes
    below the product's shipped defaults).
  * Persistence per AgentRun: ``AgentRun.policyTier`` (text) +
    ``AgentRun.metricSnapshot`` (jsonb) — additive, nullable — recorded on
    every AgentRun row created via the resolved policy (the scout's
    recommended enforcement seam: merged into ``params["qualityPolicy"]``
    upstream of ``_agent_callable``/``runs.start`` in both the sync
    ``_dispatch`` and async ``_enqueue_single_agent`` paths).

GROUND TRUTH: a negative grep for
``quality.?tier|effort.?level|policy.?tier|rigor`` across ``apps/api/app``
returned ZERO matches (feedback-loop scout, 2026-08-13) — this is genuinely
greenfield.

Run under ``flock /tmp/aether-pytest.lock``.
"""
from __future__ import annotations

import json

import pytest

from app.db import get_connection, new_id


# ---------------------------------------------------------------------------
# Item 2 — compute_rigor_policy: pure, deterministic, pinned boundaries.
# ---------------------------------------------------------------------------


class TestComputeRigorPolicy:
    def test_standard_tier_when_thresholds_are_met(self):
        from app.services.quality_policy import compute_rigor_policy

        metrics = {
            "sampleSize": 50,
            "conversionRate": 0.25,  # >= 20% target
            "dimensionScores": {  # all 10 dimensions strictly above 80
                "technicalSkills": 91.0, "experienceLevel": 85.0,
                "industryMatch": 82.0, "roleAlignment": 88.0,
                "cultureFit": 84.0, "salaryFit": 90.0,
                "locationMatch": 95.0, "careerGrowth": 81.0,
                "companyStability": 83.0, "northStarAlign": 86.0,
            },
        }
        policy = compute_rigor_policy(metrics)
        assert policy["tier"] == "standard"
        assert policy["triggers"] == []

    def test_heightened_tier_triggered_by_conversion_below_20_percent_target(self):
        from app.services.quality_policy import compute_rigor_policy

        metrics = {
            "sampleSize": 50,
            "conversionRate": 0.10,  # below the 20% target
            "dimensionScores": {k: 90.0 for k in _ten_dims()},
        }
        policy = compute_rigor_policy(metrics)
        assert policy["tier"] == "heightened"
        assert any("conversion" in t.lower() for t in policy["triggers"])

    def test_heightened_tier_triggered_by_a_dimension_at_or_below_80_floor(self):
        from app.services.quality_policy import compute_rigor_policy

        dims = {k: 90.0 for k in _ten_dims()}
        dims["cultureFit"] = 80.0  # AT the floor, not above it -> must trigger
        metrics = {"sampleSize": 50, "conversionRate": 0.30, "dimensionScores": dims}
        policy = compute_rigor_policy(metrics)
        assert policy["tier"] == "heightened"
        assert any("culturefit" in t.lower() for t in policy["triggers"])

    def test_insufficient_data_tier_is_honest_about_a_tiny_sample(self):
        """Mirrors the live DB fact (0/235 interviews, but a NEW user with 1-2
        submissions must not have their single data point dressed up as a
        trustworthy 'standard' or 'heightened' verdict)."""
        from app.services.quality_policy import compute_rigor_policy

        metrics = {
            "sampleSize": 1,
            "conversionRate": 0.0,
            "dimensionScores": {k: 90.0 for k in _ten_dims()},
        }
        policy = compute_rigor_policy(metrics)
        assert policy["tier"] == "insufficient_data"
        assert policy["triggers"] == [] or all(
            "insufficient" in t.lower() or "sample" in t.lower()
            for t in policy["triggers"]
        )

    def test_pure_function_is_deterministic_across_repeated_calls(self):
        from app.services.quality_policy import compute_rigor_policy

        metrics = {
            "sampleSize": 20,
            "conversionRate": 0.05,
            "dimensionScores": {k: 70.0 for k in _ten_dims()},
        }
        first = compute_rigor_policy(metrics)
        second = compute_rigor_policy(dict(metrics))  # fresh dict, same values
        assert first == second


def _ten_dims() -> list[str]:
    return [
        "technicalSkills", "experienceLevel", "industryMatch", "roleAlignment",
        "cultureFit", "salaryFit", "locationMatch", "careerGrowth",
        "companyStability", "northStarAlign",
    ]


# ---------------------------------------------------------------------------
# Item 3 — the knob-mapping function (enforcement seam).
# ---------------------------------------------------------------------------


class TestKnobsForTier:
    def test_standard_tier_knobs_match_shipped_defaults(self):
        """The 'standard' tier must not be MORE lenient than the product's
        existing shipped defaults — it is the baseline, not a relaxation."""
        from app.services.quality_policy import knobs_for_tier
        from app.services.tailoring_loop import (
            DEFAULT_MAX_ITERATIONS,
            DEFAULT_TARGET_SCORE,
        )

        knobs = knobs_for_tier("standard")
        assert knobs["maxIterations"] == DEFAULT_MAX_ITERATIONS
        assert knobs["targetScore"] == DEFAULT_TARGET_SCORE
        assert knobs["coverLetterRetries"] >= 2  # never below the shipped 2 retries

    def test_heightened_tier_strictly_increases_rigor_over_standard(self):
        from app.services.quality_policy import knobs_for_tier

        standard = knobs_for_tier("standard")
        heightened = knobs_for_tier("heightened")
        assert heightened["maxIterations"] > standard["maxIterations"]
        assert heightened["targetScore"] >= standard["targetScore"]
        assert heightened["coverLetterRetries"] > standard["coverLetterRetries"]

    def test_insufficient_data_tier_never_relaxes_below_standard(self):
        """An honest 'we don't know yet' tier must not be used as an excuse to
        under-try — it falls back to (never below) the standard knobs."""
        from app.services.quality_policy import knobs_for_tier

        standard = knobs_for_tier("standard")
        insufficient = knobs_for_tier("insufficient_data")
        assert insufficient["maxIterations"] >= standard["maxIterations"]
        assert insufficient["targetScore"] >= standard["targetScore"]

    def test_unknown_tier_raises_rather_than_silently_defaulting(self):
        from app.services.quality_policy import knobs_for_tier

        with pytest.raises((KeyError, ValueError)):
            knobs_for_tier("not-a-real-tier")


# ---------------------------------------------------------------------------
# Persistence — AgentRun.policyTier / metricSnapshot (additive columns).
# ---------------------------------------------------------------------------


class TestAgentRunPolicyPersistence:
    def test_ensure_columns_creates_them_idempotently(self, client, db_session):  # noqa: ARG002
        from app.repositories.agent_run import ensure_agent_run_policy_columns

        ensure_agent_run_policy_columns()
        ensure_agent_run_policy_columns()
        with db_session.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'AgentRun'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('policyTier', 'metricSnapshot')"
            )
            cols = {row[0] for row in cur.fetchall()}
        assert cols == {"policyTier", "metricSnapshot"}

    def test_tailor_run_persists_the_resolved_policy_tier_and_snapshot(
        self, client, auth_headers, test_user_id, db_session
    ):
        """The tier resolved for THIS run must be readable back off the
        AgentRun row it produced — 'per-run visibility' (U-AX item 2b)."""
        from app.repositories.agent_run import ensure_agent_run_policy_columns

        ensure_agent_run_policy_columns()

        job_id = new_id()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''INSERT INTO "Job"
                       ("id","userId","title","company","location","remote",
                        "description","requirements","source","sourceUrl",
                        "fitScore","updatedAt")
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                    (
                        job_id, test_user_id, "Backend Engineer", "Acme",
                        "Melbourne VIC", False, "Own the platform.",
                        json.dumps([]), "adzuna", f"https://example.com/{job_id}",
                        70.0,
                    ),
                )
            conn.commit()

        resp = client.post(
            "/agents/tailor/run", json={"job_id": job_id}, headers=auth_headers
        )
        assert resp.status_code in (200, 422), resp.text

        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "policyTier", "metricSnapshot" FROM "AgentRun"'
                ' WHERE "userId" = %s AND "agentName" = \'tailor\''
                ' ORDER BY "createdAt" DESC LIMIT 1',
                (test_user_id,),
            )
            row = cur.fetchone()
        assert row is not None
        policy_tier, metric_snapshot = row
        assert policy_tier in ("standard", "heightened", "insufficient_data"), (
            f"AgentRun.policyTier not populated with a valid tier (got {policy_tier!r})"
        )
        assert metric_snapshot is not None, (
            "AgentRun.metricSnapshot was not populated — per-run 'policy "
            "inputs consumed' cannot be reconstructed without it"
        )
