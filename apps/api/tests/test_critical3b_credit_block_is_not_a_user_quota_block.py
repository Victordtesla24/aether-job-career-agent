"""CRITICAL-3b — an upstream CREDIT failure must never be blamed on the user.

BLOCKER found by the adversarial review of 0b6102d (the LLM circuit breaker):

    "The circuit breaker's own cooldown is re-read by ``_dispatch``'s
     pre-existing ``AgentQuotaBlock`` gate, which does NOT inspect ``reason`` —
     so from the SECOND attempt onward a 402 out-of-credits surfaces to the
     user as a QUOTA BLOCK."

0b6102d parked the breaker cooldown in the SAME ``AgentQuotaBlock`` row that
already carried subscription-quota cooldowns, distinguished only by a
``reason`` prefix (``llm_circuit_open:``). ``LLMClient._call_live`` learned to
read that prefix; the two OTHER readers of the same row did not:

* ``routers/agents.py::_record_run``   (the sync gate every ``_dispatch`` run
  passes through), and
* ``routers/agents.py::_enqueue_single_agent`` (the async/ARQ gate),

both raised ``_quota_429("subscription_quota_exceeded")`` for ANY active row.

The consequences, all of them dishonest in the same direction:

1. The user is told "Your <provider> subscription quota is exhausted" when the
   truth is "our upstream AI provider is out of credit" — an operator failure
   billed to the user's reputation, with a "switch to API-key billing"
   suggestion that fixes nothing.
2. ``board_sweep.sweep_user_stretch`` special-cases ``HTTPException(429)`` as
   ``reason="quota-exhausted"`` and logs "plan quota 429 — stopping". So from
   tick 2 onward the operator's own telemetry ALSO blamed the user's quota,
   hiding the dead upstream the breaker exists to make visible.
3. The 429 carried no ``__cause__``, so ``board_sweep._llm_failure`` could not
   recover the failure class — the honest ``llm-insufficient_credits`` reason
   and the ``suppressed`` count silently stopped being reported.

The first attempt was already correct (the breaker is still CLOSED then, so the
failure travels the ``LLMUnavailableError`` path). Every test below therefore
exercises the state AFTER the circuit is open — the only state where the bug
exists.
"""
from __future__ import annotations

import json
import time
import uuid

import pytest
from fastapi import HTTPException

from app.services import llm_client as lc
from app.workers import board_sweep


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


def _provider_for(user_id: str, agent: str = "tailor") -> str:
    """The provider ``_record_run``'s gate will look the block up under —
    resolved by the SAME function the gate uses, never guessed."""
    from app.routers.agents import _billing_audit

    _, provider = _billing_audit(user_id, agent)
    assert provider is not None, "the tailor agent must resolve a provider"
    return provider


def _open_circuit(user_id: str, provider: str, failure_class: str) -> None:
    """Put the user+provider circuit in the OPEN state the breaker leaves
    behind after a non-retryable upstream refusal (the 'second attempt' state)."""
    from app.repositories.user_provider_credential import AgentQuotaBlockRepository

    AgentQuotaBlockRepository().set_block(
        user_id, provider,
        expires_at=lc.datetime.now(lc.timezone.utc) + lc.timedelta(seconds=900),
        reason=f"{lc.CIRCUIT_REASON_PREFIX}{failure_class}",
    )


def _never_called(**kwargs):
    raise AssertionError("the agent must not execute while the circuit is open")


def _seed_job(conn, user_id: str, *, fit: float = 80.0) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, "Engineer", "Acme", "Build.", "greenhouse",
             f"https://example.com/job/{job_id}", "screening", fit),
        )
    conn.commit()
    return job_id


def _seed_base_resume(conn, user_id: str) -> str:
    resume_id = _uid()
    sections = {
        "raw_text": (
            "Vikram Sarkar\nSenior Engineer\n"
            "- Built and shipped a payments integration handling 4k requests/day.\n"
            "- Led a team of 4 engineers through a platform migration.\n"
        ),
        "bullets": [
            {"id": "b1", "text": "Built and shipped a payments integration."},
        ],
    }
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"createdAt","updatedAt") VALUES (%s,%s,1,%s,%s,NOW(),NOW())',
            (resume_id, user_id, json.dumps(sections), "hash-critical3b"),
        )
    conn.commit()
    return resume_id


def _runs_used(user_id: str) -> int:
    from app.repositories.billing import UsageQuotaRepository, ensure_user_billing

    ensure_user_billing(user_id)
    quota = UsageQuotaRepository().get_by_user(user_id)
    assert quota is not None
    return int(quota["runsUsed"])


def _agent_run_count(user_id: str) -> int:
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM "AgentRun" WHERE "userId" = %s', (user_id,)
            )
            return int(cur.fetchone()[0])


# --------------------------------------------------------------------------
# 1. The SECOND attempt must not be presented as the user's plan quota.
# --------------------------------------------------------------------------
class TestSecondAttemptIsNotAQuotaBlock:
    def test_out_of_credits_is_an_operator_problem_not_a_user_quota_block(
        self, db_session, test_user_id
    ):
        from app.routers.agents import _record_run

        provider = _provider_for(test_user_id)
        _open_circuit(test_user_id, provider, lc.LLM_FAILURE_INSUFFICIENT_CREDITS)

        with pytest.raises(HTTPException) as ei:
            _record_run(test_user_id, "tailor", {"job_id": "j"}, _never_called)

        assert ei.value.status_code == 503, (
            "an upstream out-of-credit cooldown is a SERVICE problem (503); "
            f"got {ei.value.status_code} — the user was blamed for it"
        )
        assert ei.value.detail == lc.LLM_INSUFFICIENT_CREDITS_USER_MESSAGE
        text = str(ei.value.detail).lower()
        assert "your" not in text or "subscription quota" not in text
        assert "quota" not in text, f"must not mention the user's quota: {text}"
        assert "upgrade" not in text and "/pricing" not in text, (
            "an operator credit failure must carry no upgrade CTA"
        )
        assert "api-key billing" not in text

    def test_a_bad_api_key_is_an_operator_problem_not_a_user_quota_block(
        self, db_session, test_user_id
    ):
        from app.routers.agents import _record_run

        provider = _provider_for(test_user_id)
        _open_circuit(test_user_id, provider, lc.LLM_FAILURE_AUTH)

        with pytest.raises(HTTPException) as ei:
            _record_run(test_user_id, "tailor", {"job_id": "j"}, _never_called)

        assert ei.value.status_code == 503
        assert ei.value.detail == lc.LLM_AUTH_FAILED_USER_MESSAGE
        text = str(ei.value.detail).lower()
        assert "quota" not in text
        assert "upgrade" not in text and "/pricing" not in text

    def test_a_genuine_subscription_quota_block_still_raises_the_429(
        self, db_session, test_user_id
    ):
        """Regression guard: the fix must narrow ONLY the circuit rows. A real
        subscription cooldown keeps its 429, its reset time and its CTA."""
        from app.repositories.user_provider_credential import AgentQuotaBlockRepository
        from app.routers.agents import _record_run

        provider = _provider_for(test_user_id)
        AgentQuotaBlockRepository().set_block(
            test_user_id, provider,
            expires_at=lc.datetime.now(lc.timezone.utc) + lc.timedelta(seconds=900),
            reason="subscription_quota_exceeded",
        )

        with pytest.raises(HTTPException) as ei:
            _record_run(test_user_id, "tailor", {"job_id": "j"}, _never_called)

        assert ei.value.status_code == 429
        detail = ei.value.detail
        assert detail["error"] == "subscription_quota_exceeded"
        assert detail["retryAfter"] > 0
        assert "Agent Settings" in detail["suggestion"]

    def test_an_unrecognised_circuit_reason_degrades_to_the_transient_message(
        self, db_session, test_user_id
    ):
        """Defence in depth: a circuit row whose class we cannot read must fall
        back to the TRANSIENT message (retry with backoff) — never to a quota
        accusation, and never to a permanent-sounding claim we cannot support."""
        from app.repositories.user_provider_credential import AgentQuotaBlockRepository
        from app.routers.agents import _record_run

        provider = _provider_for(test_user_id)
        AgentQuotaBlockRepository().set_block(
            test_user_id, provider,
            expires_at=lc.datetime.now(lc.timezone.utc) + lc.timedelta(seconds=900),
            reason=f"{lc.CIRCUIT_REASON_PREFIX}something_new",
        )

        with pytest.raises(HTTPException) as ei:
            _record_run(test_user_id, "tailor", {"job_id": "j"}, _never_called)

        assert ei.value.status_code == 503
        assert ei.value.detail == lc.LLM_UNAVAILABLE_USER_MESSAGE

    def test_the_gate_carries_the_failure_class_for_the_autopilot(
        self, db_session, test_user_id
    ):
        """``board_sweep._llm_failure`` recovers the class from ``__cause__``.
        A 429 with no cause made the class unrecoverable, so the sweep counted
        an ordinary failure (and mislabelled the tick as a quota stop)."""
        from app.routers.agents import _record_run

        provider = _provider_for(test_user_id)
        _open_circuit(test_user_id, provider, lc.LLM_FAILURE_INSUFFICIENT_CREDITS)

        with pytest.raises(HTTPException) as ei:
            _record_run(test_user_id, "tailor", {"job_id": "j"}, _never_called)

        recovered = board_sweep._llm_failure(ei.value)
        assert recovered is not None, "the class must survive the HTTP translation"
        assert recovered.failure_class == lc.LLM_FAILURE_INSUFFICIENT_CREDITS
        assert recovered.retryable is False


# --------------------------------------------------------------------------
# 2. A run blocked by an upstream credit failure is never billed.
# --------------------------------------------------------------------------
class TestNoBillingForAnUpstreamCreditFailure:
    def test_the_open_circuit_gate_consumes_no_plan_quota_and_writes_no_run(
        self, db_session, test_user_id
    ):
        from app.routers.agents import _record_run

        provider = _provider_for(test_user_id)
        before_runs = _runs_used(test_user_id)
        before_rows = _agent_run_count(test_user_id)
        _open_circuit(test_user_id, provider, lc.LLM_FAILURE_INSUFFICIENT_CREDITS)

        with pytest.raises(HTTPException):
            _record_run(test_user_id, "tailor", {"job_id": "j"}, _never_called)

        assert _runs_used(test_user_id) == before_runs, (
            "a run refused because OUR provider is out of credit must not "
            "consume the user's paid plan quota"
        )
        assert _agent_run_count(test_user_id) == before_rows

    def test_a_credit_failure_during_the_first_attempt_refunds_the_reservation(
        self, db_session, test_user_id
    ):
        """The first attempt DOES reserve (the circuit is closed when it
        starts). The reservation must be refunded when the upstream refuses."""
        from app.routers.agents import _record_run

        before_runs = _runs_used(test_user_id)

        def _out_of_credits(**kwargs):
            raise lc.LLMUnavailableError(
                "internal: live call failed for 'tailor_bullets': HTTP 402",
                failure_class=lc.LLM_FAILURE_INSUFFICIENT_CREDITS,
            )

        with pytest.raises(HTTPException) as ei:
            _record_run(test_user_id, "tailor", {"job_id": "j"}, _out_of_credits)

        assert ei.value.status_code == 503
        assert _runs_used(test_user_id) == before_runs, (
            "the reserved run must be refunded when the upstream is out of credit"
        )


# --------------------------------------------------------------------------
# 3. The ASYNC (ARQ) enqueue gate reads the same row and had the same bug.
# --------------------------------------------------------------------------
class TestAsyncEnqueueGate:
    def test_enqueue_reports_the_upstream_credit_failure_not_a_quota_block(
        self, db_session, test_user_id
    ):
        from app.routers.agents import _enqueue_single_agent

        provider = _provider_for(test_user_id)
        before_runs = _runs_used(test_user_id)
        _open_circuit(test_user_id, provider, lc.LLM_FAILURE_INSUFFICIENT_CREDITS)

        with pytest.raises(HTTPException) as ei:
            _enqueue_single_agent(test_user_id, "tailor", {"job_id": "j"})

        assert ei.value.status_code == 503, (
            f"async path blamed the user's quota too: {ei.value.status_code}"
        )
        assert ei.value.detail == lc.LLM_INSUFFICIENT_CREDITS_USER_MESSAGE
        assert _runs_used(test_user_id) == before_runs


# --------------------------------------------------------------------------
# 4. END-TO-END, the exact production shape: TWO sweep ticks against one real
#    HTTP server answering 402. Tick 1 opens the circuit (already correct at
#    0b6102d); tick 2 is the attempt this BLOCKER is about.
# --------------------------------------------------------------------------
class TestBoardSweepSecondTick:
    def test_the_second_tick_reports_the_upstream_refusal_not_a_quota_stop(
        self, db_session, test_user_id, monkeypatch
    ):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        requests_received: list[str] = []

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler API
                requests_received.append(self.path)
                body = b'{"error":{"code":402,"message":"Insufficient credits"}}'
                self.send_response(402)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                return

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        try:
            monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-402-probe")
            monkeypatch.setenv("OPENROUTER_BASE_URL", f"http://127.0.0.1:{port}/v1")
            monkeypatch.setenv("AETHER_MODEL_FALLBACK", "vendor/probe-model")
            monkeypatch.setenv("AETHER_MODEL_REASONING", "vendor/probe-model")
            monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "vendor/probe-model")
            monkeypatch.setenv("AETHER_MODEL_GENERATION", "vendor/probe-model")
            monkeypatch.setenv("AETHER_LLM_MODE", "auto")
            monkeypatch.setenv("AETHER_LLM_BREAKER_COOLDOWN_SECONDS", "900")
            _seed_base_resume(db_session, test_user_id)
            for _ in range(10):
                _seed_job(db_session, test_user_id)

            deadline = time.monotonic() + 3600.0
            first = board_sweep.sweep_user_stretch(test_user_id, deadline=deadline)
            after_first = len(requests_received)
            assert after_first >= 1, "tick 1 must really reach the provider"
            assert first["reason"] == f"llm-{lc.LLM_FAILURE_INSUFFICIENT_CREDITS}"

            # Tick 2 — the circuit is now open. THIS is the broken attempt.
            second = board_sweep.sweep_user_stretch(test_user_id, deadline=deadline)
        finally:
            server.shutdown()
            server.server_close()

        assert len(requests_received) == after_first, (
            "an open circuit must not contact the provider again"
        )
        assert second["reason"] == f"llm-{lc.LLM_FAILURE_INSUFFICIENT_CREDITS}", (
            "the second tick must report the UPSTREAM refusal; "
            f"got {second['reason']!r} — the operator's own telemetry blamed "
            "the user's quota"
        )
        assert second["suppressed"] > 0, (
            "the jobs left unattempted must still be reported honestly"
        )
        assert second["needs_continuation"] is False
