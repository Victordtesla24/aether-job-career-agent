"""CRITICAL-3 — the tailor agent hot-looped against an upstream returning 402.

MEASURED CAUSE (production, 2026-08-02, reproduced from the ``AgentRun`` audit
table before a line of this fix was written):

* OpenRouter returned HTTP 402 (out of credits) → ``InsufficientCreditsError``.
* ``LLMClient._auto`` walked its model chain, every model 402'd on the same
  credential, and the chain-exhaustion raise **erased the failure class**:
  it raised a bare ``LLMUnavailableError``.
* ``app/routers/agents.py::_dispatch`` mapped that to
  ``HTTPException(503, "The AI service is temporarily unavailable. Please try
  again in a moment.")`` — a message that is FALSE for a 402 (it is not
  temporary and retrying does not help).
* ``board_sweep.sweep_user_stretch`` has an ``except LLMUnavailableError``
  circuit breaker (``LLM_OUTAGE_BREAKER = 3``) — but ``_dispatch`` never lets
  that exception escape, so the sweep hit ``except HTTPException`` instead,
  counted a plain failure, and kept going. The breaker was DEAD CODE on the
  only path that can reach it.
* The stretch therefore ran its full ``max_jobs`` (10) attempts, reported
  ``reason='job-cap'`` — which sets ``needs_continuation`` — and the 10-minute
  cron re-ran the identical 10 jobs on the next tick.

Live evidence (``AgentRun``, schema ``aether``): 10 distinct job ids, **37
failed tailor runs EACH** in the 2026-08-02 19:00→01:00 window, 60 failures
per hour, every row ``billingAuditJson.quotaPath = "metered_api"``,
``provider = "openrouter"``, ``systemRun = true``.

These tests pin the fix: classes are preserved end to end, non-retryable
classes fail fast (one attempt, honest message), retryable classes back off
exponentially with jitter and trip the breaker, a tripped circuit persists for
a cooling period and blocks live calls before any HTTP request is made, and a
stretch that only failed never asks for a continuation.
"""
from __future__ import annotations

import json
import logging
import time
import uuid

import pytest
from fastapi import HTTPException

from app.services import llm_client as lc
from app.services.llm_client import (
    InsufficientCreditsError,
    LLMClient,
    LLMUnavailableError,
)
from app.workers import board_sweep


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


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
    """A real base résumé so the tailor agent gets past its grounding gate and
    actually reaches the LLM transport (otherwise it refuses with
    ``MissingResumeError`` and the upstream is never contacted at all)."""
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
            (resume_id, user_id, json.dumps(sections), "hash-critical3"),
        )
    conn.commit()
    return resume_id


def _far_deadline() -> float:
    return time.monotonic() + 3600.0


def _dispatch_style_503(cause: LLMUnavailableError) -> HTTPException:
    """Exactly what ``_dispatch`` raises for an ``LLMUnavailableError``:
    a 503 whose ``__cause__`` is the classified LLM failure."""
    exc = HTTPException(503, lc.llm_failure_user_message(cause))
    exc.__cause__ = cause
    return exc


# --------------------------------------------------------------------------
# 1. The failure CLASS must survive chain exhaustion (it used to be erased).
# --------------------------------------------------------------------------
class TestFailureClassSurvivesChainExhaustion:
    def test_402_is_classified_non_retryable(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)

        def _boom(self, *a, **k):
            raise InsufficientCreditsError("LLM provider HTTP 402: no credit")

        monkeypatch.setattr(LLMClient, "_call_live", _boom)
        monkeypatch.setattr(lc, "_record_llm_circuit_open", lambda *a, **k: None)
        with pytest.raises(LLMUnavailableError) as ei:
            llm._auto("p", "s", "u", model="m", temperature=0.0, fixture_key="k")
        assert ei.value.failure_class == lc.LLM_FAILURE_INSUFFICIENT_CREDITS
        assert ei.value.retryable is False

    def test_401_is_classified_non_retryable(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)

        def _boom(self, *a, **k):
            raise lc.ProviderAuthError("LLM provider HTTP 401: bad key")

        monkeypatch.setattr(LLMClient, "_call_live", _boom)
        monkeypatch.setattr(lc, "_record_llm_circuit_open", lambda *a, **k: None)
        with pytest.raises(LLMUnavailableError) as ei:
            llm._auto("p", "s", "u", model="m", temperature=0.0, fixture_key="k")
        assert ei.value.failure_class == lc.LLM_FAILURE_AUTH
        assert ei.value.retryable is False

    def test_5xx_stays_retryable(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)

        def _boom(self, *a, **k):
            raise RuntimeError("LLM provider HTTP 503: upstream down")

        monkeypatch.setattr(LLMClient, "_call_live", _boom)
        monkeypatch.setattr(lc, "_sleep_for_backoff", lambda s: None)
        with pytest.raises(LLMUnavailableError) as ei:
            llm._auto("p", "s", "u", model="m", temperature=0.0, fixture_key="k")
        assert ei.value.failure_class == lc.LLM_FAILURE_RETRYABLE
        assert ei.value.retryable is True

    def test_429_stays_retryable(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient, "_call_live",
            lambda self, *a, **k: (_ for _ in ()).throw(
                RuntimeError("LLM provider HTTP 429: slow down")),
        )
        monkeypatch.setattr(lc, "_sleep_for_backoff", lambda s: None)
        with pytest.raises(LLMUnavailableError) as ei:
            llm._auto("p", "s", "u", model="m", temperature=0.0, fixture_key="k")
        assert ei.value.retryable is True


# --------------------------------------------------------------------------
# 2. Exponential backoff WITH JITTER between retryable attempts; none for a
#    non-retryable class (waiting to re-ask a question already answered "no").
# --------------------------------------------------------------------------
class TestBackoff:
    def test_retryable_attempts_sleep_with_bounded_full_jitter(
        self, tmp_path, monkeypatch
    ):
        slept: list[float] = []
        monkeypatch.setattr(lc, "_sleep_for_backoff", slept.append)
        monkeypatch.setenv("AETHER_LLM_RETRY_BACKOFF_BASE_SECONDS", "2")
        monkeypatch.setenv("AETHER_LLM_RETRY_BACKOFF_MAX_SECONDS", "8")
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient, "_call_live",
            lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 502")),
        )
        with pytest.raises(LLMUnavailableError):
            llm._auto("p", "s", "u", model="m", temperature=0.0, fixture_key="k")
        assert slept, "a retryable failure must back off before the next attempt"
        assert all(0.0 <= d <= 8.0 for d in slept), slept

    def test_full_jitter_is_actually_random(self, monkeypatch):
        monkeypatch.setenv("AETHER_LLM_RETRY_BACKOFF_BASE_SECONDS", "4")
        monkeypatch.setenv("AETHER_LLM_RETRY_BACKOFF_MAX_SECONDS", "60")
        draws = {round(lc._backoff_delay(2), 6) for _ in range(40)}
        assert len(draws) > 1, "backoff must be jittered, not a fixed delay"
        assert all(0.0 <= d <= 16.0 for d in draws), draws

    def test_non_retryable_failure_does_not_sleep(self, tmp_path, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(lc, "_sleep_for_backoff", slept.append)
        monkeypatch.setattr(lc, "_record_llm_circuit_open", lambda *a, **k: None)
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient, "_call_live",
            lambda self, *a, **k: (_ for _ in ()).throw(
                InsufficientCreditsError("HTTP 402")),
        )
        with pytest.raises(LLMUnavailableError):
            llm._auto("p", "s", "u", model="m", temperature=0.0, fixture_key="k")
        assert slept == []


# --------------------------------------------------------------------------
# 3. The user-facing message must stop lying about a 402.
# --------------------------------------------------------------------------
class TestHonestMessages:
    def test_insufficient_credits_message_is_actionable(self):
        exc = LLMUnavailableError(
            "boom", failure_class=lc.LLM_FAILURE_INSUFFICIENT_CREDITS
        )
        msg = lc.llm_failure_user_message(exc)
        assert msg != lc.LLM_UNAVAILABLE_USER_MESSAGE
        assert "temporarily unavailable" not in msg.lower()
        assert "credit" in msg.lower()

    def test_auth_message_is_actionable(self):
        exc = LLMUnavailableError("boom", failure_class=lc.LLM_FAILURE_AUTH)
        msg = lc.llm_failure_user_message(exc)
        assert "temporarily unavailable" not in msg.lower()

    def test_retryable_message_is_unchanged(self):
        exc = LLMUnavailableError("boom")
        assert lc.llm_failure_user_message(exc) == lc.LLM_UNAVAILABLE_USER_MESSAGE


# --------------------------------------------------------------------------
# 4. The circuit breaker PERSISTS across ticks and blocks the HTTP call itself.
# --------------------------------------------------------------------------
class TestPersistentCircuit:
    def test_402_exhaustion_opens_the_circuit_for_a_cooling_period(
        self, db_session, user_id, tmp_path, monkeypatch
    ):
        from app.repositories.user_provider_credential import AgentQuotaBlockRepository

        monkeypatch.setenv("AETHER_LLM_BREAKER_COOLDOWN_SECONDS", "900")
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient, "_call_live",
            lambda self, *a, **k: (_ for _ in ()).throw(
                InsufficientCreditsError("HTTP 402", provider="openrouter")),
        )
        with lc.user_credential_context(user_id, "tailor"):
            with pytest.raises(LLMUnavailableError):
                llm._auto("p", "s", "u", model="m", temperature=0.0, fixture_key="k")
        block = AgentQuotaBlockRepository().get_active(user_id, "openrouter")
        assert block is not None, "a non-retryable upstream failure must open the circuit"
        assert block["reason"].startswith(lc.CIRCUIT_REASON_PREFIX)
        assert lc.LLM_FAILURE_INSUFFICIENT_CREDITS in block["reason"]

    def test_open_circuit_blocks_the_live_call_before_any_http(
        self, db_session, user_id, monkeypatch
    ):
        from app.repositories.user_provider_credential import AgentQuotaBlockRepository

        AgentQuotaBlockRepository().set_block(
            user_id, "openrouter",
            expires_at=lc.datetime.now(lc.timezone.utc) + lc.timedelta(seconds=900),
            reason=f"{lc.CIRCUIT_REASON_PREFIX}{lc.LLM_FAILURE_INSUFFICIENT_CREDITS}",
        )
        llm = LLMClient(mode="live")
        # No credential is resolved and no httpx call is built: the breaker
        # short-circuits at the top of ``_call_live``.
        with lc.user_credential_context(user_id, "tailor"):
            with pytest.raises(lc.LLMCircuitOpenError) as ei:
                llm._call_live("s", "u", model="openrouter/whatever", temperature=0.0)
        assert ei.value.retryable is False
        assert ei.value.failure_class == lc.LLM_FAILURE_INSUFFICIENT_CREDITS

    def test_subscription_quota_block_still_raises_quota_exhausted(
        self, db_session, user_id
    ):
        """Regression guard: the circuit reuses the block table but must NOT
        change the meaning of an existing subscription-quota cooldown."""
        from app.repositories.user_provider_credential import AgentQuotaBlockRepository

        AgentQuotaBlockRepository().set_block(
            user_id, "openrouter",
            expires_at=lc.datetime.now(lc.timezone.utc) + lc.timedelta(seconds=900),
            reason="subscription_quota_exceeded",
        )
        llm = LLMClient(mode="live")
        with lc.user_credential_context(user_id, "tailor"):
            with pytest.raises(lc.QuotaExhaustedError):
                llm._call_live("s", "u", model="openrouter/whatever", temperature=0.0)


# --------------------------------------------------------------------------
# 5. The board sweep must STOP, not grind 10 jobs, on an upstream refusal.
# --------------------------------------------------------------------------
class TestBoardSweepStopsInsteadOfLooping:
    def test_non_retryable_503_stops_after_a_single_attempt(
        self, db_session, user_id, monkeypatch
    ):
        for _ in range(6):
            _seed_job(db_session, user_id)
        calls: list[str] = []

        def _boom(uid, agent, params):
            calls.append(agent)
            raise _dispatch_style_503(
                LLMUnavailableError(
                    "LLM backend unavailable: live call failed: HTTP 402",
                    failure_class=lc.LLM_FAILURE_INSUFFICIENT_CREDITS,
                )
            )

        monkeypatch.setattr(board_sweep, "_run_agent", _boom)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert len(calls) == 1, f"expected fail-fast, got {len(calls)} attempts"
        assert summary["reason"] == f"llm-{lc.LLM_FAILURE_INSUFFICIENT_CREDITS}"
        assert summary["failures"] == 1

    def test_retryable_503_trips_the_outage_breaker(
        self, db_session, user_id, monkeypatch
    ):
        for _ in range(8):
            _seed_job(db_session, user_id)
        calls: list[str] = []

        def _boom(uid, agent, params):
            calls.append(agent)
            raise _dispatch_style_503(
                LLMUnavailableError("LLM backend unavailable: HTTP 503")
            )

        monkeypatch.setattr(board_sweep, "_run_agent", _boom)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert len(calls) == board_sweep.LLM_OUTAGE_BREAKER, calls
        assert summary["reason"] == "llm-unavailable"

    def test_suppressed_jobs_are_reported_not_silently_dropped(
        self, db_session, user_id, monkeypatch, caplog
    ):
        for _ in range(5):
            _seed_job(db_session, user_id)

        def _boom(uid, agent, params):
            raise _dispatch_style_503(
                LLMUnavailableError(
                    "HTTP 402", failure_class=lc.LLM_FAILURE_INSUFFICIENT_CREDITS
                )
            )

        monkeypatch.setattr(board_sweep, "_run_agent", _boom)
        with caplog.at_level(logging.WARNING, logger="app.workers.board_sweep"):
            summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["suppressed"] == 4, summary
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "suppressed" in joined.lower()
        assert lc.LLM_FAILURE_INSUFFICIENT_CREDITS in joined

    def test_a_stretch_that_only_failed_never_asks_for_continuation(
        self, db_session, user_id, monkeypatch
    ):
        for _ in range(12):
            _seed_job(db_session, user_id)

        def _boom(uid, agent, params):
            raise HTTPException(500, "kaboom")

        monkeypatch.setattr(board_sweep, "_run_agent", _boom)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["reason"] == "job-cap"
        assert summary["processed"] == 0
        assert summary["needs_continuation"] is False


# --------------------------------------------------------------------------
# 6. End-to-end: the router's 503 must carry the honest class + message.
# --------------------------------------------------------------------------
class TestRouterSurfacesTheClass:
    def test_record_run_maps_402_to_an_actionable_503(self, test_user_id):
        from app.db import get_connection
        from app.routers.agents import _record_run

        def _boom(**kwargs):
            raise LLMUnavailableError(
                "internal: live call failed for 'tailor_bullets'",
                failure_class=lc.LLM_FAILURE_INSUFFICIENT_CREDITS,
            )

        with pytest.raises(HTTPException) as ei:
            _record_run(test_user_id, "tailor", {"job_id": "j"}, _boom)
        assert ei.value.status_code == 503
        detail = str(ei.value.detail).lower()
        assert "credit" in detail
        assert "temporarily unavailable" not in detail
        # …and the audit row must carry the same honest text, never the lie.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "error" FROM "AgentRun" WHERE "userId" = %s '
                    'AND "agentName" = %s ORDER BY "createdAt" DESC LIMIT 1',
                    (test_user_id, "tailor"),
                )
                row = cur.fetchone()
        assert row is not None
        assert "credit" in row[0].lower()

    def test_record_run_keeps_the_generic_message_for_a_retryable_failure(
        self, test_user_id
    ):
        from app.routers.agents import _record_run

        def _boom(**kwargs):
            raise LLMUnavailableError("internal: HTTP 503 upstream")

        with pytest.raises(HTTPException) as ei:
            _record_run(test_user_id, "tailor", {"job_id": "j"}, _boom)
        assert ei.value.detail == lc.LLM_UNAVAILABLE_USER_MESSAGE


# --------------------------------------------------------------------------
# 7. END-TO-END PROOF (requirement 5): a REAL socket server that answers HTTP
#    402, driven through the REAL transport. No stubbing below the HTTP layer.
#
#    Before this fix the same setup produced one paid request per attempt, per
#    job, per cron tick, forever. Now: the first attempt reaches the provider,
#    the circuit opens, and every subsequent attempt is refused locally — the
#    server's own request counter is the evidence.
# --------------------------------------------------------------------------
class TestEndToEndAgainstAReal402Server:
    def test_attempts_stop_instead_of_looping(self, db_session, user_id, monkeypatch):
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

            def log_message(self, *a):  # silence the default stderr logging
                return

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        try:
            monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-402-probe")
            monkeypatch.setenv("OPENROUTER_BASE_URL", f"http://127.0.0.1:{port}/v1")
            monkeypatch.setenv("AETHER_LLM_BREAKER_COOLDOWN_SECONDS", "900")
            # Single-model chain: isolate the breaker from the fallback model.
            monkeypatch.setenv("AETHER_MODEL_FALLBACK", "vendor/probe-model")
            llm = LLMClient(mode="live")

            with lc.user_credential_context(user_id, "tailor"):
                # Attempt 1 — a real HTTP request, a real 402 answer.
                with pytest.raises(LLMUnavailableError) as first:
                    llm._auto(
                        "p", "s", "u", model="vendor/probe-model",
                        temperature=0.0, fixture_key="k",
                    )
                assert first.value.failure_class == lc.LLM_FAILURE_INSUFFICIENT_CREDITS
                after_first = len(requests_received)
                assert after_first >= 1, "the first attempt must really reach the provider"

                # Attempts 2..6 — the circuit is open; the provider is never
                # contacted again. This is the loop that used to cost money.
                for _ in range(5):
                    with pytest.raises(lc.LLMCircuitOpenError):
                        llm._auto(
                            "p", "s", "u", model="vendor/probe-model",
                            temperature=0.0, fixture_key="k",
                        )
            assert len(requests_received) == after_first, (
                "an open circuit must not contact the provider at all; got "
                f"{len(requests_received)} requests, expected {after_first}"
            )
        finally:
            server.shutdown()
            server.server_close()

    @pytest.mark.parametrize("llm_mode", ["auto", "live"])
    def test_the_board_sweep_stops_dead_against_the_same_upstream(
        self, db_session, user_id, monkeypatch, llm_mode
    ):
        """The whole chain, as production runs it: sweep -> _dispatch -> agent
        -> transport -> 402. Ten eligible jobs; the sweep must attempt ONE.

        Both modes are exercised because they take DIFFERENT paths out of the
        transport: ``auto`` (production) raises the chain's classified
        ``LLMUnavailableError``, while ``live`` propagates the raw
        ``InsufficientCreditsError``. This parametrisation is what caught the
        sweep still walking all 10 jobs on the raw path."""
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        requests_received: list[str] = []

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
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
            monkeypatch.setenv("AETHER_LLM_MODE", llm_mode)
            _seed_base_resume(db_session, user_id)
            for _ in range(10):
                _seed_job(db_session, user_id)

            attempts: list[str] = []
            real_run_agent = board_sweep._run_agent

            def _counting(uid, agent, params):
                attempts.append(agent)
                return real_run_agent(uid, agent, params)

            monkeypatch.setattr(board_sweep, "_run_agent", _counting)
            summary = board_sweep.sweep_user_stretch(
                user_id, deadline=_far_deadline()
            )
        finally:
            server.shutdown()
            server.server_close()

        assert len(attempts) == 1, (
            f"the sweep must fail fast, not walk the board: {attempts}"
        )
        assert summary["reason"] == f"llm-{lc.LLM_FAILURE_INSUFFICIENT_CREDITS}"
        assert summary["suppressed"] == 9, summary
        assert summary["needs_continuation"] is False


# --------------------------------------------------------------------------
# 8. The Agents screen must stop painting a dead upstream as a healthy blip.
#
#    ``_is_transient_failure`` (ML-agents-err-001) classifies any failed run
#    whose message contains "temporarily unavailable" / "try again" as a
#    TRANSIENT upstream blip, which keeps the agent card looking alive. Since
#    every 402 carried exactly that text, a week of total inactivity rendered
#    as routine flakiness. The class-specific messages deliberately contain
#    neither phrase, so a non-retryable refusal now paints an honest error.
# --------------------------------------------------------------------------
class TestAgentsScreenHonesty:
    def test_a_402_failure_is_not_classified_as_a_transient_blip(self):
        from app.routers.agents import _is_transient_failure

        run = {"status": "failed", "error": lc.LLM_INSUFFICIENT_CREDITS_USER_MESSAGE}
        assert _is_transient_failure(run) is False

    def test_an_auth_failure_is_not_classified_as_a_transient_blip(self):
        from app.routers.agents import _is_transient_failure

        run = {"status": "failed", "error": lc.LLM_AUTH_FAILED_USER_MESSAGE}
        assert _is_transient_failure(run) is False

    def test_a_genuinely_transient_failure_is_still_classified_transient(self):
        from app.routers.agents import _is_transient_failure

        run = {"status": "failed", "error": lc.LLM_UNAVAILABLE_USER_MESSAGE}
        assert _is_transient_failure(run) is True
