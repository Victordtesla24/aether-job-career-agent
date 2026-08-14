"""GAP-P4-002 — a guard rejection is an honest COMPLETED degrade, not a failure.

When the cover agent's fabrication guard (``FabricationError``) or §10.2
structural guard (``StructuralError``) rejects a draft after every corrective
retry, the guard is WORKING — Aether refuses to ship an ungrounded or
non-compliant letter. The async worker
(``app/workers/tasks.py``) and the synchronous pipeline
(``app/routers/agents.py::_pipeline_core``) already degrade honestly, but the
shared ``_execute_reserved_run`` fell through to its generic
``except Exception`` and recorded the AgentRun audit row as ``status='failed'``
— surfacing the guard doing its job as a red failure in the owner-visible
"Recent runs" table and in the Agents-screen health classification.

These tests pin the intended behaviour AND the two invariants the reverted WIP
broke (WIP-BRANCH-AUDIT-2026-07-29 blocker #1): its ``except`` clauses named
``FabricationError``/``StructuralError`` without ever binding them in that
scope, so a ``NameError`` fired instead — orphaning the AgentRun row in
``'running'`` forever, making every handler declared BELOW them unreachable
(``QuotaExhaustedError`` -> 429, ``LLMUnavailableError`` -> 503), and — the
billing-critical part — skipping ``_refund_once()`` so a paying user's reserved
run was consumed and never refunded.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.repositories.agent_run import AgentRunRepository
from app.repositories.billing import UsageQuotaRepository, ensure_user_billing
from app.routers.agents import _record_run


@pytest.fixture(autouse=True)
def _model_env(monkeypatch):
    # Metered agents resolve a model for cost computation; pin it so the
    # quota/spend path is deterministic (mirrors test_gap_p6_billing).
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")


def _guard_errors():
    from app.agents.cover_letter_agent import FabricationError, StructuralError

    return FabricationError, StructuralError


def _latest_cover_run(user_id: str) -> dict:
    runs = [
        r
        for r in AgentRunRepository().list_recent(user_id)
        if r["agentName"] == "coverLetter"
    ]
    assert runs, "no coverLetter AgentRun was recorded"
    return runs[0]


def _run_with_guard_rejection(user_id: str, exc: Exception):
    def _raise():
        raise exc

    return _record_run(user_id, "coverLetter", {"job_id": "j"}, _raise)


class TestGuardRejectionIsAnHonestCompletedDegrade:
    def test_fabrication_rejection_records_completed_not_failed(
        self, client, auth_headers, test_user_id,
    ):
        FabricationError, _ = _guard_errors()
        ensure_user_billing(test_user_id)

        with pytest.raises(FabricationError):
            _run_with_guard_rejection(
                test_user_id, FabricationError(["Acme Corp", "40%"])
            )

        run = _latest_cover_run(test_user_id)
        assert run["status"] == "completed", (
            "the fabrication guard REJECTING a draft is the guard working — it "
            "must not be audited as a failed agent run"
        )
        output = run["output"] or {}
        assert output.get("coverLetterUnavailable") is True
        assert output.get("cover_letter_id") is None
        # The reason must name the flagged entities (already rendered into
        # English by FabricationError.__init__) — never verbatim LLM output.
        assert "Acme Corp" in str(output.get("reason"))
        assert float(run["costUsd"] or 0) == 0.0, "no letter produced — never billed"

    def test_structural_rejection_records_completed_not_failed(
        self, client, auth_headers, test_user_id,
    ):
        _, StructuralError = _guard_errors()
        ensure_user_billing(test_user_id)

        with pytest.raises(StructuralError):
            _run_with_guard_rejection(
                test_user_id, StructuralError(["missing closing", "too many words"])
            )

        run = _latest_cover_run(test_user_id)
        assert run["status"] == "completed"
        output = run["output"] or {}
        assert output.get("coverLetterUnavailable") is True
        assert "missing closing" in str(output.get("reason"))
        assert float(run["costUsd"] or 0) == 0.0

    @pytest.mark.parametrize("which", ["fabrication", "structural"])
    def test_guard_rejection_refunds_the_reserved_run(
        self, which, client, auth_headers, test_user_id,
    ):
        """The billing-critical invariant the broken WIP destroyed.

        ``coverLetter`` is metered, so ``_record_run`` atomically RESERVES one
        run before the agent is invoked. A guard rejection produces no letter,
        so that reservation MUST be refunded — ``runsUsed`` back to 0.
        """
        FabricationError, StructuralError = _guard_errors()
        ensure_user_billing(test_user_id)
        exc = (
            FabricationError(["Nonexistent Ltd"])
            if which == "fabrication"
            else StructuralError(["§10.2 violation"])
        )

        before = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
        with pytest.raises((FabricationError, StructuralError)):
            _run_with_guard_rejection(test_user_id, exc)
        after = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
        assert after == before == 0, (
            "the reserved run must be refunded — a guard rejection produced no "
            "letter, so the user must never be billed for it"
        )

    def test_rejection_still_propagates_so_callers_keep_their_shape(
        self, client, auth_headers, test_user_id, patch_agent_run,
    ):
        """The handler records + refunds, then RE-RAISES.

        ``run_cover_letter`` maps the re-raise to a 422 and ``_pipeline_core``
        degrades the pipeline gracefully; neither response shape may change.
        """
        FabricationError, _ = _guard_errors()
        ensure_user_billing(test_user_id)
        from app.agents import cover_letter_agent as cl_module

        def _boom():
            raise FabricationError(["Fabricated Pty Ltd"])

        # Signature-derived double (conftest ``patch_agent_run``): it accepts
        # whatever the REAL ``CoverLetterAgent.run`` accepts, so the router's
        # own dispatch kwargs can never masquerade as a guard-mapping failure.
        cover_calls = patch_agent_run(cl_module.CoverLetterAgent, _boom)
        run = client.post(
            "/agents/scout/run",
            json={"query": "python engineer", "location": "Sydney"},
            headers=auth_headers,
        )
        assert run.status_code == 202, run.text
        job = client.get("/jobs", headers=auth_headers).json()[0]

        resp = client.post(
            "/agents/cover-letter/run",
            json={"job_id": job["id"]},
            headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "Fabricated Pty Ltd" in resp.json()["detail"]
        # The 422 came from the guard rejection this test injected — not from
        # an unrelated earlier refusal that never reached the agent at all.
        assert cover_calls, "the router never reached CoverLetterAgent.run"
        # ...and the audit row is the honest COMPLETED degrade, not "failed".
        assert _latest_cover_run(test_user_id)["status"] == "completed"


class TestHandlersBelowTheGuardClausesStayReachable:
    """Regression pins for WIP-BRANCH-AUDIT blocker #1's blast radius.

    Python evaluates ``except`` clauses in order, so an unbound name in an
    earlier clause raises ``NameError`` and makes every LATER handler
    unreachable. These two pass before AND after this fix by design — they are
    the guard-rail that catches a re-introduction of that defect.
    """

    def test_quota_exhausted_still_maps_to_429(
        self, client, auth_headers, test_user_id,
    ):
        from app.services.llm_client import QuotaExhaustedError

        ensure_user_billing(test_user_id)

        def _quota():
            raise QuotaExhaustedError("anthropic", reason="subscription_quota_exceeded")

        with pytest.raises(HTTPException) as ei:
            _record_run(test_user_id, "coverLetter", {"job_id": "j"}, _quota)
        assert ei.value.status_code == 429
        assert int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"]) == 0

    def test_llm_unavailable_still_maps_to_503(
        self, client, auth_headers, test_user_id,
    ):
        from app.services.llm_client import LLMUnavailableError

        ensure_user_billing(test_user_id)

        def _down():
            raise LLMUnavailableError("LLM backend unavailable: live call failed")

        with pytest.raises(HTTPException) as ei:
            _record_run(test_user_id, "coverLetter", {"job_id": "j"}, _down)
        assert ei.value.status_code == 503
        assert int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"]) == 0

    def test_guard_error_names_are_bound_at_module_scope(self):
        """The literal defect: the names must resolve without a local import."""
        import app.routers.agents as agents_module

        assert hasattr(agents_module, "FabricationError")
        assert hasattr(agents_module, "StructuralError")
