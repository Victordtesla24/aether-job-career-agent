"""ML-email-001 (LOW) — failing test BEFORE fix (MODELS-LIVE §7 step 2).

RCA verified against CURRENT code (2026-07-22):
- ``_execute_reserved_run`` (apps/api/app/routers/agents.py:777-833) prices
  EVERY metered agent run purely off ``_model_for_agent(agent_name, ...)``
  (agents.py:848-861), which returns a real model id whenever
  ``agent_name in _LLM_TIER_BY_BACKEND`` (agents.py:840-846) —
  ``"emailAgent": "REASONING"`` is unconditionally in that map. The cost/token
  computation (agents.py:806-818) derives ``tokensIn``/``tokensOut`` from the
  JSON-serialized SIZE of ``params``/``output`` and stamps ``model`` with
  ``get_model("REASONING")`` whenever ``model is not None`` — there is no
  check for whether the agent actually invoked the LLM.
- ``EmailAgent._triage`` (apps/api/app/agents/email_agent.py:191-206) returns
  early — BEFORE ever calling ``self._llm.complete_json(...)`` — whenever
  there are no local ``EmailThread`` rows to classify (``if not threads:``,
  email_agent.py:203-215): a genuinely zero-LLM-call, no-op/degraded run
  (either "Connect Gmail to triage your recruiter inbox." when not connected,
  or "No emails to triage yet." when connected with an empty inbox).

Because ``_execute_reserved_run`` has no visibility into whether the agent
callable actually reached the LLM, this zero-LLM-call triage run is still
metered as if a REASONING-tier generation happened: a real model id is
stamped and a non-zero cost/token figure — purely derived from the tiny
request/response payload size — is charged and recorded on the AgentRun.

Target behaviour (not yet implemented): a no-op/degraded EmailAgent triage
run (zero LLM calls) must record ZERO cost/tokens (and/or no model stamp),
not a generic payload-size-derived charge.
"""
from __future__ import annotations


class TestEmailAgentNoopTriageZeroCost:
    def test_noop_triage_no_gmail_no_threads_records_zero_cost(
        self, client, auth_headers
    ):
        """A fresh user with Gmail NOT connected and NO local email threads:
        ``_triage`` early-returns via its ``if not threads:`` branch WITHOUT
        ever calling the LLM. The run must be metered as the zero-LLM-call
        no-op it actually was.

        FAILS TODAY: the response carries a non-zero ``costUsd``/``tokensIn``/
        ``tokensOut`` and a stamped REASONING-tier ``model``, purely derived
        from the tiny request/response JSON payload size — not from any real
        LLM usage (there was none).
        """
        resp = client.post(
            "/agents/email/run", json={"mode": "triage"}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Sanity: this really is the zero-LLM-call no-op path (no Gmail
        # connected, nothing local to triage), not the metered classify path.
        assert data["triaged"] == 0
        assert data["connected"] is False

        assert data["model"] is None, (
            "a no-op triage (zero LLM calls) must not stamp a model id — got "
            f"{data['model']!r}"
        )
        assert float(data["costUsd"] or 0) == 0.0, (
            "a no-op triage (zero LLM calls) must record zero cost — got "
            f"{data['costUsd']!r}"
        )
        assert int(data["tokensIn"] or 0) == 0
        assert int(data["tokensOut"] or 0) == 0
