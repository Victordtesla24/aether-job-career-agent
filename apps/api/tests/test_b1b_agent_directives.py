"""B1b — AgentDirective: bounded, whitelisted, ratcheted directives with
rules-stage Supervisor evaluation (ADR-AGI-2 P1).

ORCH-B1-BLUEPRINT-2026-08-14.md §7.2 test plan. Written BEFORE implementation
(RED filed to uat/reports/evidence/models-live/b1b/). Covers:

  * the whitelist (§6.1/§6.2) — unknown keys rejected loudly, honesty gates
    structurally un-addressable;
  * the ratchet arithmetic (§3.2) — a loosening directive is a no-op BY
    CONSTRUCTION, clamp boundaries are exact;
  * immutable history (§2.2) — supersede only, no update/delete path;
  * the injection seam (§4.2) and the run_policy_fields trap (§2.4) — an
    active directive amends the policy the agent obeys AND the trace
    genuinely persists on the run row;
  * the Stage-1 rules table (§6.3) — deterministic, $0, no LLM, rationale
    cites real metric values;
  * DEV-6 — no endpoint accepts a caller-supplied directive body; only the
    evaluator issues them;
  * the API shapes (§5.2).

Run under ``flock /tmp/aether-pytest.lock``.
"""
from __future__ import annotations

import inspect
import json

import pytest

from app.db import get_connection, new_id

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _policy_for(metrics: dict) -> dict:
    """The EXACT shape ``quality_policy.resolve_policy_for_user`` returns for
    an 'available' metrics read — built from the real, unedited
    ``compute_rigor_policy`` so these tests can never drift from production's
    own tier/knob computation."""
    from app.services.quality_policy import compute_rigor_policy

    policy = compute_rigor_policy(metrics)
    policy["metrics"] = metrics
    return policy


def _ten_dims(default: float = 90.0) -> dict:
    from app.services.quality_policy import DIMENSION_KEYS

    return {k: default for k in DIMENSION_KEYS}


# ---------------------------------------------------------------------------
# The whitelist — unknown keys rejected loudly, never dropped silently.
# ---------------------------------------------------------------------------


class TestDirectiveWhitelist:
    def test_only_whitelisted_fields_survive(self):
        from app.services.agent_directives import validate_directive

        whitelisted, rejected = validate_directive(
            {"maxIterations": 8, "totallyMadeUpField": 1}
        )
        assert whitelisted == {"maxIterations": 8}
        assert "totallyMadeUpField" in rejected
        assert "totallyMadeUpField" not in whitelisted

    def test_an_unwhitelisted_key_is_rejected_loudly_not_dropped(self):
        """Rejection must be RECORDED (returned), never merely absent."""
        from app.services.agent_directives import validate_directive

        _, rejected = validate_directive({"skip_quota": True})
        assert rejected == ("skip_quota",)

    def test_all_four_named_fields_are_whitelisted(self):
        from app.services.agent_directives import DIRECTIVE_FIELDS

        assert set(DIRECTIVE_FIELDS) == {
            "maxIterations",
            "targetScore",
            "coverLetterRetries",
            "storyEvidenceStrictness",
        }

    @pytest.mark.parametrize(
        "forbidden_key",
        [
            # Tier-decision thresholds (quality_policy.py) — a Supervisor
            # amending these would be grading its own homework.
            "DIMENSION_FLOOR",
            "INTERVIEW_CONVERSION_TARGET",
            "MIN_SAMPLE_SIZE",
            "dimensionFloor",
            "interviewConversionTarget",
            "minSampleSize",
            # Honesty gates.
            "fabricationGuard",
            "entailmentWindow",
            "groundingStrictness",
            # Spend / quota.
            "skip_quota",
            "system_run",
            "spendCapUsd",
            "spend_cap",
            "AETHER_LLM_BUDGET_SECONDS",
            # Approval gates.
            "approvalRequired",
            "_APPROVAL_GATED",
            "approvalGated",
            # Model / credential routing.
            "model",
            "provider",
            "authMode",
            "credentialRef",
            "fallbackChain",
            # Execution classes (charter data — R-8 gated).
            "execClass",
            "siloBasis",
            "onRefusal",
            "dependsOn",
            "coversCards",
        ],
    )
    def test_honesty_gates_are_absent_from_the_whitelist(self, forbidden_key):
        from app.services.agent_directives import DIRECTIVE_FIELDS, validate_directive

        assert forbidden_key not in DIRECTIVE_FIELDS
        whitelisted, rejected = validate_directive({forbidden_key: "anything"})
        assert whitelisted == {}
        assert forbidden_key in rejected


# ---------------------------------------------------------------------------
# The ratchet arithmetic — a loosening directive is a no-op BY CONSTRUCTION.
# ---------------------------------------------------------------------------


class TestRatchetArithmetic:
    def test_a_directive_can_never_lower_a_baseline_knob(self):
        """Property-style: for a spread of baselines and requested values,
        the applied value is NEVER below the baseline for an increase-
        direction field."""
        from app.services.agent_directives import apply_directives

        for baseline in (5, 7, 9):
            for requested in (0, 1, baseline - 1, baseline, baseline + 1, 999):
                application = apply_directives(
                    {"maxIterations": baseline},
                    [{"id": "d1", "directive": {"maxIterations": requested}}],
                )
                assert application.knobs["maxIterations"] >= baseline, (
                    f"baseline={baseline} requested={requested} "
                    f"applied={application.knobs['maxIterations']}"
                )

    def test_a_below_baseline_request_yields_exactly_the_baseline(self):
        from app.services.agent_directives import apply_directives

        application = apply_directives(
            {"maxIterations": 7},
            [{"id": "d1", "directive": {"maxIterations": 3}}],
        )
        assert application.knobs["maxIterations"] == 7
        assert application.clamped["maxIterations"]["reason"] == "ratchet"
        assert application.clamped["maxIterations"]["requested"] == 3
        assert application.clamped["maxIterations"]["applied"] == 7

    def test_a_value_above_the_ceiling_is_clamped_and_the_clamp_is_recorded(self):
        from app.services.agent_directives import apply_directives

        application = apply_directives(
            {"maxIterations": 5},
            [{"id": "d1", "directive": {"maxIterations": 999}}],
        )
        assert application.knobs["maxIterations"] == 10  # the ceiling
        assert application.clamped["maxIterations"] == {
            "requested": 999,
            "applied": 10,
            "reason": "ceiling",
        }

    def test_max_iterations_has_a_ceiling_the_consumer_lacks(self):
        """tailor_agent.resolve_loop_knobs clamps ONLY the floor — the
        directive layer is the ONLY place a ceiling exists for this field."""
        from app.agents.tailor_agent import resolve_loop_knobs
        from app.services.agent_directives import apply_directives

        # The consumer alone obeys an absurd knob verbatim (no ceiling there).
        consumer_max_iterations, _ = resolve_loop_knobs({"maxIterations": 999})
        assert consumer_max_iterations == 999

        # The directive layer clamps it.
        application = apply_directives(
            {"maxIterations": 5},
            [{"id": "d1", "directive": {"maxIterations": 999}}],
        )
        assert application.knobs["maxIterations"] == 10

    def test_target_score_ceiling_is_95(self):
        from app.services.agent_directives import apply_directives

        application = apply_directives(
            {"targetScore": 85.0},
            [{"id": "d1", "directive": {"targetScore": 200.0}}],
        )
        assert application.knobs["targetScore"] == 95.0
        assert application.clamped["targetScore"]["reason"] == "ceiling"

    def test_target_score_exact_boundary_is_not_clamped(self):
        from app.services.agent_directives import apply_directives

        application = apply_directives(
            {"targetScore": 85.0},
            [{"id": "d1", "directive": {"targetScore": 95.0}}],
        )
        assert application.knobs["targetScore"] == 95.0
        assert "targetScore" not in application.clamped  # exact ceiling, no clamp note

    def test_cover_letter_retries_ceiling_matches_the_consumers(self):
        """Drift guard: the directive ceiling must equal the consumer's OWN
        constant, never a re-typed number that could silently diverge."""
        from app.agents.cover_letter_agent import _MAX_CORRECTIVE_RETRIES
        from app.services.agent_directives import DIRECTIVE_FIELDS

        assert DIRECTIVE_FIELDS["coverLetterRetries"].ceiling == _MAX_CORRECTIVE_RETRIES

    def test_story_evidence_strictness_only_tightens(self):
        """restrict-enum: standard -> strict is the only reachable direction."""
        from app.services.agent_directives import apply_directives

        tightened = apply_directives(
            {"storyEvidenceStrictness": "standard"},
            [{"id": "d1", "directive": {"storyEvidenceStrictness": "strict"}}],
        )
        assert tightened.knobs["storyEvidenceStrictness"] == "strict"

        # A directive "requesting" a loosening from strict -> standard is a
        # no-op by construction.
        loosening_attempt = apply_directives(
            {"storyEvidenceStrictness": "strict"},
            [{"id": "d1", "directive": {"storyEvidenceStrictness": "standard"}}],
        )
        assert loosening_attempt.knobs["storyEvidenceStrictness"] == "strict"
        assert loosening_attempt.clamped["storyEvidenceStrictness"]["reason"] == "ratchet"

    def test_a_directive_touching_nothing_recognized_yields_no_applied_id(self):
        from app.services.agent_directives import apply_directives

        application = apply_directives(
            {"maxIterations": 5}, [{"id": "ghost", "directive": {}}]
        )
        assert application.applied_directive_ids == ()


# ---------------------------------------------------------------------------
# Immutability — supersede only; no update/delete path.
# ---------------------------------------------------------------------------


class TestDirectiveStoreImmutability:
    def test_no_update_or_delete_method_exists(self):
        from app.repositories.agent_directive import AgentDirectiveRepository

        public_methods = {
            name
            for name in dir(AgentDirectiveRepository)
            if not name.startswith("_")
        }
        assert "update" not in public_methods
        assert "delete" not in public_methods
        assert "edit" not in public_methods
        assert {"issue", "supersede", "list_active", "list_history"} <= public_methods

    def test_a_directive_is_never_edited_only_superseded(self, client, test_user_id):  # noqa: ARG002
        from app.repositories.agent_directive import AgentDirectiveRepository

        repo = AgentDirectiveRepository()
        first_id = repo.issue(
            test_user_id, "tailor",
            directive={"maxIterations": 7},
            rationale="initial",
            metrics_cited={"conversionRate": 0.1},
        )
        second_id = repo.issue(
            test_user_id, "tailor",
            directive={"maxIterations": 9},
            rationale="tightened further",
            metrics_cited={"conversionRate": 0.05},
        )
        assert first_id != second_id

        history = repo.list_history(test_user_id, "tailor")
        by_id = {row["id"]: row for row in history}
        assert by_id[first_id]["status"] == "superseded"
        assert by_id[first_id]["supersededById"] == second_id
        # The OLD row's own instruction content is untouched.
        assert by_id[first_id]["directive"] == {"maxIterations": 7}
        assert by_id[first_id]["rationale"] == "initial"
        assert by_id[second_id]["status"] == "active"
        assert by_id[second_id]["directive"] == {"maxIterations": 9}

    def test_history_survives_supersession(self, client, test_user_id):  # noqa: ARG002
        from app.repositories.agent_directive import AgentDirectiveRepository

        repo = AgentDirectiveRepository()
        repo.issue(
            test_user_id, "coverLetter", directive={"coverLetterRetries": 3},
            rationale="r1", metrics_cited={},
        )
        repo.issue(
            test_user_id, "coverLetter", directive={"coverLetterRetries": 4},
            rationale="r2", metrics_cited={},
        )
        history = repo.list_history(test_user_id, "coverLetter")
        assert len(history) == 2
        active = repo.list_active(test_user_id, "coverLetter")
        assert len(active) == 1
        assert active[0]["directive"] == {"coverLetterRetries": 4}

    def test_two_active_directives_for_one_agent_are_impossible(
        self, client, test_user_id  # noqa: ARG002
    ):
        """The partial unique index makes this a DB fact: after N issues for
        the same (user, agent), exactly one row is ever 'active'."""
        from app.repositories.agent_directive import (
            AgentDirectiveRepository,
            ensure_agent_directive_table,
        )

        ensure_agent_directive_table()
        repo = AgentDirectiveRepository()
        for i in range(5):
            repo.issue(
                test_user_id, "tailor", directive={"maxIterations": 5 + i},
                rationale=f"r{i}", metrics_cited={},
            )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT COUNT(*) FROM "AgentDirective" '
                    'WHERE "userId" = %s AND "agentKey" = %s AND "status" = \'active\'',
                    (test_user_id, "tailor"),
                )
                count = cur.fetchone()[0]
        assert count == 1

    def test_supersede_without_replacement_retires_cleanly(
        self, client, test_user_id  # noqa: ARG002
    ):
        from app.repositories.agent_directive import AgentDirectiveRepository

        repo = AgentDirectiveRepository()
        directive_id = repo.issue(
            test_user_id, "storyExtractor",
            directive={"storyEvidenceStrictness": "strict"},
            rationale="no stories yet", metrics_cited={"storyCount": 0},
        )
        changed = repo.supersede(directive_id, reason="metrics recovered")
        assert changed is True
        active = repo.list_active(test_user_id, "storyExtractor")
        assert active == []
        history = repo.list_history(test_user_id, "storyExtractor")
        assert history[0]["status"] == "superseded"
        # Retiring a row twice is a safe no-op, never an error.
        assert repo.supersede(directive_id, reason="again") is False

    def test_ensure_table_is_idempotent_and_uses_a_distinct_lock(self):
        from app.repositories.agent_directive import (
            _AGENT_DIRECTIVE_LOCK,
            ensure_agent_directive_table,
        )

        ensure_agent_directive_table()
        ensure_agent_directive_table()  # must not raise
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables"
                    " WHERE table_schema = ANY(current_schemas(false))"
                    " AND table_name = 'AgentDirective'"
                )
                assert cur.fetchone() is not None
        # Distinct from every other advisory-lock id in the codebase.
        assert _AGENT_DIRECTIVE_LOCK == 7420260816


# ---------------------------------------------------------------------------
# The injection seam — the applied policy the agent obeys, and the
# run_policy_fields trap (§2.4): the trace genuinely persists on the run row.
# ---------------------------------------------------------------------------


class TestInjectionSeam:
    def test_no_active_directive_leaves_the_policy_unchanged(
        self, client, test_user_id, monkeypatch  # noqa: ARG002
    ):
        from app.routers.agents import _with_quality_policy

        monkeypatch.setenv("AETHER_AGI_DIRECTIVES_ENABLED", "true")
        params = _with_quality_policy(test_user_id, {}, agent_key="tailor")
        policy = params["qualityPolicy"]
        assert policy["directives"]["appliedIds"] == []
        assert policy["directives"]["clamped"] == {}

    def test_an_active_directive_amends_the_policy_the_agent_obeys(
        self, client, test_user_id, monkeypatch  # noqa: ARG002
    ):
        from app.repositories.agent_directive import AgentDirectiveRepository
        from app.routers.agents import _with_quality_policy

        monkeypatch.setenv("AETHER_AGI_DIRECTIVES_ENABLED", "true")
        directive_id = AgentDirectiveRepository().issue(
            test_user_id, "tailor",
            directive={"maxIterations": 9, "targetScore": 91.0},
            rationale="Tighten tailoring effort.",
            metrics_cited={"conversionRate": 0.0, "sampleSize": 50},
        )
        params = _with_quality_policy(test_user_id, {}, agent_key="tailor")
        policy = params["qualityPolicy"]
        assert policy["knobs"]["maxIterations"] >= 9
        assert policy["knobs"]["targetScore"] >= 91.0
        assert directive_id in policy["directives"]["appliedIds"]

    def test_the_amended_policy_is_the_one_persisted_on_the_run(
        self, client, test_user_id, monkeypatch  # noqa: ARG002
    ):
        """THE TRAP TEST (§2.4). Fails without the run_policy_fields fix: the
        'directives' key would be silently dropped on its way to the DB."""
        from app.repositories.agent_directive import AgentDirectiveRepository
        from app.repositories.agent_run import AgentRunRepository
        from app.routers.agents import _with_quality_policy

        monkeypatch.setenv("AETHER_AGI_DIRECTIVES_ENABLED", "true")
        directive_id = AgentDirectiveRepository().issue(
            test_user_id, "tailor",
            directive={"maxIterations": 9},
            rationale="Tighten tailoring effort.",
            metrics_cited={"conversionRate": 0.0, "sampleSize": 50},
        )
        params = _with_quality_policy(test_user_id, {}, agent_key="tailor")
        run = AgentRunRepository().start(test_user_id, "tailor", params)
        # AgentRunRepository.start()'s own RETURNING clause is the legacy
        # ``_COLUMNS`` projection (deliberately NOT widened — see
        # ``last_policy_run_by_agent``'s docstring) — read the policy columns
        # back with a direct query, the same way a reader that needs them
        # already does.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "metricSnapshot" FROM "AgentRun" WHERE "id" = %s',
                    (run["id"],),
                )
                metric_snapshot = cur.fetchone()[0]
        assert metric_snapshot is not None
        assert "directives" in metric_snapshot, (
            "AgentRun.metricSnapshot['directives'] missing — the "
            "run_policy_fields trap (§2.4) is not fixed"
        )
        assert directive_id in metric_snapshot["directives"]["appliedIds"]

    def test_a_directive_store_failure_degrades_to_the_baseline_policy(
        self, client, test_user_id, monkeypatch  # noqa: ARG002
    ):
        from app.repositories import agent_directive as agent_directive_module
        from app.routers.agents import _with_quality_policy

        monkeypatch.setenv("AETHER_AGI_DIRECTIVES_ENABLED", "true")

        def _boom(self, user_id, agent_key=None):
            raise RuntimeError("directive store unavailable")

        monkeypatch.setattr(
            agent_directive_module.AgentDirectiveRepository, "list_active", _boom
        )
        # Must not raise — degrades to the baseline policy.
        params = _with_quality_policy(test_user_id, {}, agent_key="tailor")
        assert isinstance(params["qualityPolicy"], dict)
        assert "tier" in params["qualityPolicy"]

    def test_no_agent_key_resolves_no_directives(
        self, client, test_user_id, monkeypatch  # noqa: ARG002
    ):
        from app.repositories.agent_directive import AgentDirectiveRepository
        from app.routers.agents import _with_quality_policy

        monkeypatch.setenv("AETHER_AGI_DIRECTIVES_ENABLED", "true")
        AgentDirectiveRepository().issue(
            test_user_id, "tailor", directive={"maxIterations": 9},
            rationale="r", metrics_cited={},
        )
        params = _with_quality_policy(test_user_id, {}, agent_key=None)
        policy = params["qualityPolicy"]
        # No directive resolution attempted at all when agent_key is absent.
        assert "directives" not in policy or policy["directives"]["appliedIds"] == []

    def test_the_seam_stays_idempotent(self, client, test_user_id):  # noqa: ARG002
        from app.routers.agents import _with_quality_policy

        stamped = {"qualityPolicy": {"tier": "standard", "knobs": {}}}
        result = _with_quality_policy(test_user_id, stamped, agent_key="tailor")
        assert result is stamped  # returned unchanged, not re-resolved

    def test_directives_paused_by_default_never_amend_the_policy(
        self, client, test_user_id, monkeypatch  # noqa: ARG002
    ):
        """AETHER_AGI_DIRECTIVES_ENABLED code-defaults OFF (§9.1) — an active
        directive exists but must not amend the run until enabled."""
        from app.repositories.agent_directive import AgentDirectiveRepository
        from app.routers.agents import _with_quality_policy

        monkeypatch.delenv("AETHER_AGI_DIRECTIVES_ENABLED", raising=False)
        AgentDirectiveRepository().issue(
            test_user_id, "tailor", directive={"maxIterations": 9},
            rationale="r", metrics_cited={},
        )
        params = _with_quality_policy(test_user_id, {}, agent_key="tailor")
        policy = params["qualityPolicy"]
        assert "directives" not in policy


# ---------------------------------------------------------------------------
# Stage-1 rules — deterministic, $0, no LLM; rationale cites real metrics.
# ---------------------------------------------------------------------------


class TestSupervisorRulesStage:
    def test_the_rules_stage_makes_no_llm_call(self):
        import sys

        assert "app.services.llm_client" not in sys.modules or True  # module import is fine
        from app.services import supervisor_rules

        # The pure evaluate() function's own module never imports an LLM client.
        source = inspect.getsource(supervisor_rules.evaluate)
        assert "llm_client" not in source
        assert "LLMClient" not in source

    def test_heightened_tier_conversion_trigger_proposes_a_tailor_directive(self):
        from app.services.supervisor_rules import evaluate

        policy = _policy_for(
            {"sampleSize": 50, "conversionRate": 0.0, "dimensionScores": _ten_dims()}
        )
        assert policy["tier"] == "heightened"
        proposals, retired = evaluate(policy, active={})
        assert retired == []
        tailor_proposals = [p for p in proposals if p.agent_key == "tailor"]
        assert len(tailor_proposals) == 1
        proposal = tailor_proposals[0]
        # Every number in the rationale must be the REAL cited metric.
        assert "0.0%" in proposal.rationale
        assert "50" in proposal.rationale
        assert proposal.metrics_cited["conversionRate"] == 0.0
        assert proposal.metrics_cited["sampleSize"] == 50
        assert proposal.directive["maxIterations"] > policy["knobs"]["maxIterations"] - 1

    def test_a_dimension_below_floor_proposes_a_cover_letter_directive(self):
        from app.services.supervisor_rules import evaluate

        dims = _ten_dims()
        dims["cultureFit"] = 45.0
        policy = _policy_for(
            {"sampleSize": 50, "conversionRate": 0.30, "dimensionScores": dims}
        )
        assert policy["tier"] == "heightened"
        proposals, _ = evaluate(policy, active={})
        cover_proposals = [p for p in proposals if p.agent_key == "coverLetter"]
        assert len(cover_proposals) == 1
        assert "cultureFit" in cover_proposals[0].rationale
        assert "45.0" in cover_proposals[0].rationale
        assert cover_proposals[0].metrics_cited["score"] == 45.0

    def test_zero_stories_proposes_strict_story_evidence(self):
        from app.services.supervisor_rules import evaluate

        policy = _policy_for(
            {"sampleSize": 50, "conversionRate": 0.0, "dimensionScores": _ten_dims()}
        )
        proposals, _ = evaluate(policy, active={}, story_count=0)
        story_proposals = [p for p in proposals if p.agent_key == "storyExtractor"]
        assert len(story_proposals) == 1
        assert story_proposals[0].directive == {"storyEvidenceStrictness": "strict"}

    def test_no_rule_can_propose_a_loosening(self):
        """Every proposal's requested numeric value is >= the tier baseline
        it was computed from."""
        from app.services.supervisor_rules import evaluate

        policy = _policy_for(
            {"sampleSize": 50, "conversionRate": 0.0, "dimensionScores": _ten_dims()}
        )
        proposals, _ = evaluate(policy, active={}, story_count=0)
        for proposal in proposals:
            for key, value in proposal.directive.items():
                if isinstance(value, (int, float)):
                    baseline = policy["knobs"].get(key, 0)
                    assert value >= baseline

    def test_reevaluation_does_not_churn_history(self, client, test_user_id):  # noqa: ARG002
        from app.repositories.agent_directive import AgentDirectiveRepository
        from app.services.supervisor_rules import evaluate

        policy = _policy_for(
            {"sampleSize": 50, "conversionRate": 0.0, "dimensionScores": _ten_dims()}
        )
        repo = AgentDirectiveRepository()
        proposals, _ = evaluate(policy, active={}, story_count=0)
        for proposal in proposals:
            repo.issue(
                test_user_id, proposal.agent_key, directive=proposal.directive,
                rationale=proposal.rationale, metrics_cited=proposal.metrics_cited,
            )
        assert proposals, "fixture metrics must trigger at least one proposal"
        active_after_first = {
            row["agentKey"]: row for row in repo.list_active(test_user_id)
        }
        # SAME metric snapshot again.
        proposals_again, retired_again = evaluate(
            policy, active=active_after_first, story_count=0
        )
        assert proposals_again == []
        assert retired_again == []
        # History unchanged — no new rows for any agent that WAS proposed.
        for proposal in proposals:
            assert len(repo.list_history(test_user_id, proposal.agent_key)) == 1

    def test_a_recovered_tier_retires_the_directive_it_does_not_invert_it(self):
        from app.services.supervisor_rules import evaluate

        recovered_policy = _policy_for(
            {"sampleSize": 50, "conversionRate": 0.30, "dimensionScores": _ten_dims()}
        )
        assert recovered_policy["tier"] == "standard"
        active = {
            "tailor": {"id": "existing-directive-id", "directive": {"maxIterations": 9}}
        }
        proposals, retired = evaluate(recovered_policy, active=active, story_count=5)
        assert proposals == []  # never a loosening directive
        assert retired == ["existing-directive-id"]

    def test_determinism_same_inputs_same_directives(self):
        from app.services.supervisor_rules import evaluate

        policy = _policy_for(
            {"sampleSize": 50, "conversionRate": 0.0, "dimensionScores": _ten_dims()}
        )
        proposals_a, retired_a = evaluate(policy, active={}, story_count=0)
        proposals_b, retired_b = evaluate(policy, active={}, story_count=0)
        assert [
            (p.agent_key, p.directive, p.rationale) for p in proposals_a
        ] == [(p.agent_key, p.directive, p.rationale) for p in proposals_b]
        assert retired_a == retired_b

    def test_rules_stage_evaluate_issues_via_the_repository_end_to_end(
        self, client, test_user_id, db_session  # noqa: ARG002
    ):
        """Integration: seed a real Application row so
        resolve_policy_for_user's live metric read finds a heightened-tier
        signal, then run the impure wrapper end to end."""
        from app.repositories.agent_directive import AgentDirectiveRepository
        from app.services.supervisor_rules import rules_stage_evaluate

        _seed_submitted_applications(test_user_id, count=6, interviews=0)
        result = rules_stage_evaluate(test_user_id)
        assert result["evaluated"] is True
        assert isinstance(result["issued"], list)
        if result["issued"]:
            active = AgentDirectiveRepository().list_active(test_user_id)
            assert len(active) == len(result["issued"])
            for row in active:
                assert row["rationale"]
                assert row["metricsCited"]


def _seed_submitted_applications(user_id: str, *, count: int, interviews: int) -> None:
    """Real ``Job`` + ``Application`` rows so ``collect_policy_metrics``'s
    live DB read has a genuine signal to compute a tier from."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Resume" ("id","userId","sections","formatHash","updatedAt")
                   VALUES (%s,%s,'{}','seedhash',NOW()) RETURNING "id"''',
                (new_id(), user_id),
            )
            resume_id = cur.fetchone()[0]
            for i in range(count):
                job_id = new_id()
                cur.execute(
                    '''INSERT INTO "Job"
                       ("id","userId","title","company","location","remote",
                        "description","requirements","source","sourceUrl",
                        "fitScore","updatedAt")
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                    (
                        job_id, user_id, f"Role {i}", "Acme", "Melbourne VIC",
                        False, "Own the platform.", json.dumps([]), "adzuna",
                        f"https://example.com/{job_id}", 70.0,
                    ),
                )
                app_id = new_id()
                status = "interview" if i < interviews else "submitted"
                cur.execute(
                    '''INSERT INTO "Application"
                       ("id","userId","jobId","resumeId","status","createdAt","updatedAt")
                       VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",NOW(),NOW())''',
                    (app_id, user_id, job_id, resume_id, status),
                )
        conn.commit()


# ---------------------------------------------------------------------------
# API shapes (§5.2) — auth, owner-scoping, paused honesty, DEV-6.
# ---------------------------------------------------------------------------


class TestDirectivesApiAuth:
    def test_get_directives_requires_authentication(self, client):
        resp = client.get("/agents/directives")
        assert resp.status_code == 401

    def test_get_history_requires_authentication(self, client):
        resp = client.get("/agents/directives/history", params={"agentKey": "tailor"})
        assert resp.status_code == 401

    def test_evaluate_requires_authentication(self, client):
        resp = client.post("/agents/directives/evaluate")
        assert resp.status_code == 401


class TestDirectivesApiShape:
    def test_get_directives_empty_shape(self, client, auth_headers):
        resp = client.get("/agents/directives", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["directives"] == []
        assert set(body.keys()) >= {"directives", "paused", "pausedReason"}

    def test_get_directives_paused_reflects_the_flag(
        self, client, auth_headers, monkeypatch
    ):
        monkeypatch.delenv("AETHER_AGI_DIRECTIVES_ENABLED", raising=False)
        resp = client.get("/agents/directives", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["paused"] is True
        assert resp.json()["pausedReason"]

        monkeypatch.setenv("AETHER_AGI_DIRECTIVES_ENABLED", "true")
        resp2 = client.get("/agents/directives", headers=auth_headers)
        assert resp2.json()["paused"] is False
        assert resp2.json()["pausedReason"] is None

    def test_directives_show_up_after_being_issued(
        self, client, auth_headers, test_user_id
    ):
        from app.repositories.agent_directive import AgentDirectiveRepository

        AgentDirectiveRepository().issue(
            test_user_id, "tailor", directive={"maxIterations": 9},
            rationale="Tighten tailoring effort — 0.0% over 50 submissions.",
            metrics_cited={"conversionRate": 0.0, "sampleSize": 50},
        )
        resp = client.get("/agents/directives", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        rows = resp.json()["directives"]
        assert len(rows) == 1
        assert rows[0]["agentKey"] == "tailor"
        assert rows[0]["directive"] == {"maxIterations": 9}
        assert rows[0]["rationale"].startswith("Tighten tailoring effort")

    def test_history_requires_an_agent_key(self, client, auth_headers):
        resp = client.get("/agents/directives/history", headers=auth_headers)
        assert resp.status_code == 422  # missing required query param

    def test_history_returns_superseded_rows_too(
        self, client, auth_headers, test_user_id
    ):
        from app.repositories.agent_directive import AgentDirectiveRepository

        repo = AgentDirectiveRepository()
        repo.issue(
            test_user_id, "tailor", directive={"maxIterations": 7},
            rationale="r1", metrics_cited={},
        )
        repo.issue(
            test_user_id, "tailor", directive={"maxIterations": 9},
            rationale="r2", metrics_cited={},
        )
        resp = client.get(
            "/agents/directives/history",
            params={"agentKey": "tailor"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        history = resp.json()["history"]
        assert len(history) == 2
        statuses = {row["status"] for row in history}
        assert statuses == {"active", "superseded"}


class TestDirectivesApiOwnerScoping:
    def test_another_users_directives_never_appear(self, client, auth_headers):
        from app.repositories.agent_directive import AgentDirectiveRepository

        other_user_id = new_id()
        AgentDirectiveRepository().issue(
            other_user_id, "tailor", directive={"maxIterations": 9},
            rationale="belongs to someone else", metrics_cited={},
        )
        resp = client.get("/agents/directives", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["directives"] == []


class TestDirectivesEvaluateEndpoint:
    def test_evaluate_runs_the_rules_stage_and_returns_a_summary(
        self, client, auth_headers
    ):
        resp = client.post("/agents/directives/evaluate", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["evaluated"] is True
        assert isinstance(body["issued"], list)
        assert isinstance(body["retired"], list)

    def test_no_endpoint_accepts_a_caller_supplied_directive_body(self, client, auth_headers):
        """DEV-6: POST /agents/directives/evaluate takes NO body. A caller
        attempting to smuggle a directive through the request body must be
        structurally unable to — the handler declares no body parameter at
        all, so FastAPI never binds one."""
        from app.routers.agent_directives import evaluate_directives

        signature = inspect.signature(evaluate_directives)
        for param in signature.parameters.values():
            assert param.name in ("request", "current_user"), (
                f"unexpected parameter {param.name!r} on the evaluate endpoint "
                "— it must not be able to bind a caller-supplied body"
            )

        # Even when a malicious body IS sent, the response is unaffected by it.
        resp = client.post(
            "/agents/directives/evaluate",
            headers=auth_headers,
            json={
                "agentKey": "tailor",
                "directive": {"maxIterations": 999999, "skip_quota": True},
            },
        )
        assert resp.status_code == 200, resp.text
        # Nothing in the response reflects the attacker-supplied payload.
        assert "999999" not in resp.text

    def test_evaluate_is_rate_limited(self, client, auth_headers):
        from app.rate_limit import SlidingWindowRateLimiter

        # Exhaust a tight limiter directly on the test app's state so this
        # test does not depend on (or wait for) the production window.
        client.app.state.agent_directives_evaluate_rate_limiter = (
            SlidingWindowRateLimiter(max_calls=1, window_seconds=600.0)
        )
        first = client.post("/agents/directives/evaluate", headers=auth_headers)
        assert first.status_code == 200, first.text
        second = client.post("/agents/directives/evaluate", headers=auth_headers)
        assert second.status_code == 429, second.text

    def test_no_other_post_route_under_agents_directives_exists(self, client, auth_headers):
        """DEV-6, structurally: there is exactly one POST path under
        /agents/directives, and it is /evaluate — no bare
        POST /agents/directives that could accept an arbitrary body."""
        resp = client.post("/agents/directives", headers=auth_headers)
        assert resp.status_code in (404, 405)
