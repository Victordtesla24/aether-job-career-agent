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


# ---------------------------------------------------------------------------
# F-UAX-06 — the resolved knobs must reach the pipeline, not merely persist a
# tier string. TestAgentRunPolicyPersistence above proves persistence only;
# these prove the tailor loop, cover-letter retries and _agent_trend.
# ---------------------------------------------------------------------------


class TestTailorPolicyKnobsReachTheLoop:
    """`TailoringAgent.run` must construct its `TailoringLoop` from the
    resolved policy's knobs, not merely accept them as a dead parameter."""

    def test_resolve_loop_knobs_defaults_when_no_policy_given(self):
        from app.agents.tailor_agent import resolve_loop_knobs
        from app.services.tailoring_loop import (
            DEFAULT_MAX_ITERATIONS,
            DEFAULT_TARGET_SCORE,
        )

        max_iterations, target_score = resolve_loop_knobs(None)
        assert max_iterations == DEFAULT_MAX_ITERATIONS
        assert target_score == DEFAULT_TARGET_SCORE

    def test_resolve_loop_knobs_threads_heightened_tier_verbatim(self):
        """The exact numbers the scout cited (max_iterations=7,
        target_score=88) come from `knobs_for_tier`, not hand-picked here."""
        from app.agents.tailor_agent import resolve_loop_knobs
        from app.services.quality_policy import knobs_for_tier

        heightened = knobs_for_tier("heightened")
        max_iterations, target_score = resolve_loop_knobs(heightened)
        assert max_iterations == heightened["maxIterations"]
        assert target_score == heightened["targetScore"]
        assert max_iterations > 5  # strictly above the shipped default of 5

    def test_resolve_loop_knobs_never_relaxes_below_shipped_defaults(self):
        from app.agents.tailor_agent import resolve_loop_knobs
        from app.services.tailoring_loop import (
            DEFAULT_MAX_ITERATIONS,
            DEFAULT_TARGET_SCORE,
        )

        max_iterations, target_score = resolve_loop_knobs(
            {"maxIterations": 1, "targetScore": 10.0}
        )
        assert max_iterations == DEFAULT_MAX_ITERATIONS
        assert target_score == DEFAULT_TARGET_SCORE

    def test_run_constructs_tailoring_loop_with_the_resolved_knobs(self, monkeypatch):
        """End-to-end proof at the ACTUAL call site (`TailoringAgent.run`):
        a `TailoringLoop` substitute captures its constructor kwargs, so no
        LLM call or DB fixture is needed to observe that the numbers a
        resolved policy carries really reach the object the loop runs on."""
        from app.agents import tailor_agent as tailor_agent_module

        captured = {}

        class _CaptureLoop:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run(self, *a, **k):
                raise RuntimeError("stop-before-llm")

        monkeypatch.setattr(tailor_agent_module, "TailoringLoop", _CaptureLoop)
        monkeypatch.setattr(tailor_agent_module, "build_career_corpus", lambda *a, **k: "")
        monkeypatch.setattr(tailor_agent_module, "build_story_evidence", lambda *a, **k: "")

        agent = tailor_agent_module.TailoringAgent.__new__(tailor_agent_module.TailoringAgent)
        agent._service = object()
        agent._ats_engine = object()
        agent._stories = None
        agent._jobs = type(
            "J",
            (),
            {
                "get_by_id": staticmethod(
                    lambda *a, **k: {
                        "id": "j1",
                        "title": "Backend Engineer",
                        "company": "Acme",
                        "description": "Own the platform.",
                    }
                )
            },
        )()
        agent.ensure_base_resume = lambda user_id: {  # noqa: ARG005
            # RT-002 raises ResumeBulletsUnavailableError before the loop is
            # ever constructed when there is nothing to rewrite — irrelevant
            # to this test (which pins the resolved policy knobs reaching the
            # loop, not résumé content), so a real, non-empty bullet list is
            # required just to reach ``TailoringLoop(...)``.
            "sections": {
                "raw_text": "Experienced engineer.",
                "bullets": ["Led backend platform migrations serving 2M users."],
            }
        }

        with pytest.raises(RuntimeError, match="stop-before-llm"):
            agent.run("u1", "j1", policy_knobs={"maxIterations": 9, "targetScore": 91.0})

        assert captured.get("max_iterations") == 9
        assert captured.get("target_score") == 91.0


class TestCoverLetterRetriesRespectPolicyKnobs:
    """`_corrective_retry_labels` (the actual generator the retry loop
    iterates over) must respect a resolved policy's `coverLetterRetries`."""

    def test_default_labels_are_the_shipped_two_retries(self):
        from app.agents.cover_letter_agent import _corrective_retry_labels

        assert _corrective_retry_labels(None) == ("retry", "retry2")

    def test_heightened_tier_extends_the_retry_sequence(self):
        from app.agents.cover_letter_agent import _corrective_retry_labels
        from app.services.quality_policy import knobs_for_tier

        heightened = knobs_for_tier("heightened")
        labels = _corrective_retry_labels(heightened)
        assert len(labels) == heightened["coverLetterRetries"]
        assert len(labels) > len(_corrective_retry_labels(None))
        # The first two fixture-key labels are byte-for-byte preserved —
        # renaming them would silently invalidate the recorded LLM corpus.
        assert labels[:2] == ("retry", "retry2")

    def test_retry_count_is_capped_and_floored_regardless_of_input(self):
        from app.agents.cover_letter_agent import (
            _MAX_CORRECTIVE_RETRIES,
            _MIN_CORRECTIVE_RETRIES,
            _corrective_retry_labels,
        )

        assert len(_corrective_retry_labels({"coverLetterRetries": 0})) == _MIN_CORRECTIVE_RETRIES
        assert (
            len(_corrective_retry_labels({"coverLetterRetries": 999}))
            == _MAX_CORRECTIVE_RETRIES
        )


class TestAgentTrend:
    """`_agent_trend` (agents.py:3466-3520) — untested before this file per
    F-UAX-06's audit."""

    def test_no_runs_yields_null_direction_with_honest_basis(self):
        from app.routers.agents import _agent_trend

        result = _agent_trend("tailor", [])
        assert result["direction"] is None
        assert result["runs"] == 0
        assert result["basis"] == "no scored run recorded yet"

    def test_unknown_backend_reports_no_comparable_metric(self):
        from app.routers.agents import _agent_trend

        result = _agent_trend("scout", [{"output": {}}])
        assert result["metric"] is None
        assert result["direction"] is None

    def test_improving_direction_from_two_scored_tailor_runs(self):
        from app.routers.agents import _agent_trend

        # newest-first, matching `recent_runs_by_agent`'s ordering.
        runs = [
            {"output": {"tailoringSummary": {"bestScore": 80.0}}},
            {"output": {"tailoringSummary": {"bestScore": 60.0}}},
        ]
        result = _agent_trend("tailor", runs)
        assert result["direction"] == "improving"
        assert result["latest"] == 80.0
        assert result["previous"] == 60.0
        assert result["delta"] == 20.0

    def test_declining_direction_from_two_scored_cover_letter_runs(self):
        from app.routers.agents import _agent_trend

        runs = [
            {"output": {"quality": {"overall": 55.0}}},
            {"output": {"quality": {"overall": 75.0}}},
        ]
        result = _agent_trend("coverLetter", runs)
        assert result["direction"] == "declining"
        assert result["delta"] == -20.0

    def test_single_scored_run_has_no_comparison_yet(self):
        from app.routers.agents import _agent_trend

        runs = [{"output": {"tailoringSummary": {"bestScore": 80.0}}}]
        result = _agent_trend("tailor", runs)
        assert result["latest"] == 80.0
        assert result["previous"] is None
        assert result["direction"] is None
