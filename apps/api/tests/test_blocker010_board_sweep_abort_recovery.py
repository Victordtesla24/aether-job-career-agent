"""BLOCKER-010 — the board sweep aborted 127 stretches on a RETRYABLE class.

MEASURED CAUSE (production ``/var/log/aether/worker.log``, read before a line
of this fix was written; 127 ``ABORTING stretch`` lines, last successful
``board-complete`` 2026-08-04T02:00:01Z):

    board-sweep <user>: ABORTING stretch after job <id> — upstream LLM failure
    class=retryable retryable=True; 6669 eligible job(s) suppressed
    (not attempted) rather than retried: LLM backend unavailable: live call
    failed: LLM call exceeded hard budget of 70.9s for 'cover_letter'

Three findings, each pinned by a test below.

1. THE OUTAGE COUNTER CONFLATES "THIS JOB FAILED" WITH "THE PROVIDER IS DOWN".
   The three sampled aborts were caused by, respectively, an Nvidia HTTP 404
   ("Provider returned error"), an Nvidia 502 ``ResourceExhausted: Worker local
   total request limit reached (32/32)``, and ``LLM call exceeded hard budget
   of 70.9s`` — the last of which is OUR OWN wall clock running out. No
   provider ever refused anything in that third case, yet it counted toward a
   provider-down breaker. ``llm_client._auto`` classes a budget exhaustion
   ``LLM_FAILURE_RETRYABLE`` ("A budget exhaustion is always retryable
   regardless of what any earlier attempt raised"), which is correct about
   RETRYABILITY and silent about WHOSE fault it was — and the sweep needs the
   second fact, not the first.

2. THE COUNTER IS NOT CLEARED BY A SUCCESSFUL PROVIDER CALL. It is reset only
   after a coverLetter run that produced a letter. Two of the four sampled
   aborts logged ``llm-unavailable (processed=0 tailored=1 covers=0
   failures=3)`` — a tailor run SUCCEEDED in that very stretch, which is direct
   proof the upstream was answering, and the sweep still declared it down.

3. THE ABORT'S ``suppressed`` FIGURE IS THE WHOLE BACKLOG, NOT THE LOSS. It is
   ``_remaining_eligible_count`` — every eligible job the user has (6,055 →
   6,669 and climbing). A stretch is bounded by ``max_jobs`` (10) and by its
   wall clock, so the jobs an abort actually cost is at most a handful; the
   other ~6,660 were never going to be attempted in that stretch under ANY
   outcome, ``board-complete`` included. Reporting them as "suppressed (not
   attempted) rather than retried" attributes ordinary backlog growth to the
   abort and makes a bounded, working circuit breaker read as a catastrophic
   mass suppression.

WHAT IS DELIBERATE AND MUST SURVIVE: aborting on a genuine provider outage is
INTENTIONAL (commit 0b6102d, CRITICAL-3 — the tailor agent hot-looped 60 paid
calls/hour against an upstream returning 402). ``TestTheBreakerIsPreserved``
below is the guard: a provider that really is refusing must still stop the
stretch after ``LLM_OUTAGE_BREAKER`` attempts, and a budget-starved worker must
still stop after a bounded number of attempts rather than walking the job cap.
"""
from __future__ import annotations

import logging
import time
import uuid

import pytest
from fastapi import HTTPException

from app.services import llm_client as lc
from app.services.llm_client import LLMClient, LLMUnavailableError
from app.workers import board_sweep

#: Read through ``getattr`` ONLY so this module still COLLECTS against the
#: pre-fix code and every test below reports its own honest RED, instead of the
#: whole file dying in one collection ImportError. The fix adds the real
#: constant; ``test_budget_exhaustion_carries_a_distinct_retryable_class``
#: asserts on ``lc.LLM_FAILURE_BUDGET_EXHAUSTED`` directly.
_BUDGET_CLASS = getattr(lc, "LLM_FAILURE_BUDGET_EXHAUSTED", "budget_exhausted")


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


def _seed_job(conn, user_id: str, *, fit: float) -> str:
    """One ``screening`` job with a fitScore — sweep mode ``full``.

    ``fit`` is explicit in every call so ``_next_target``'s
    ``ORDER BY fitScore DESC`` gives these tests a DETERMINISTIC job order and
    the per-job failure scripts below can name which job fails how.
    """
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


def _far_deadline() -> float:
    return time.monotonic() + 3600.0


def _dispatch_style_503(cause: LLMUnavailableError) -> HTTPException:
    """Exactly what ``routers/agents._dispatch`` raises for an
    ``LLMUnavailableError``: a 503 whose ``__cause__`` carries the class.
    This is the ONLY path production takes into the sweep's breaker."""
    exc = HTTPException(503, lc.llm_failure_user_message(cause))
    exc.__cause__ = cause
    return exc


def _provider_refusal() -> HTTPException:
    """An upstream that ANSWERED with an error — the production Nvidia
    ``HTTP 404: Provider returned error`` / ``502 ResourceExhausted`` shape."""
    return _dispatch_style_503(
        LLMUnavailableError(
            "LLM backend unavailable: live call failed: LLM provider HTTP 404: "
            '{"error":{"message":"Provider returned error","code":404}}',
            failure_class=lc.LLM_FAILURE_RETRYABLE,
        )
    )


def _budget_exhaustion() -> HTTPException:
    """OUR OWN wall clock ran out — the production
    ``LLM call exceeded hard budget of 70.9s for 'cover_letter'`` shape.
    No provider refused anything here."""
    return _dispatch_style_503(
        LLMUnavailableError(
            "LLM backend unavailable: live call failed: LLM call exceeded hard "
            "budget of 70.9s for 'cover_letter'",
            failure_class=_BUDGET_CLASS,
        )
    )


def _letter(job_id: str) -> dict:
    """A coverLetter result that GENUINELY produced a letter (non-null id) —
    the shape ``_cover_result_degraded`` must NOT treat as a degrade."""
    return {"cover_letter_id": f"letter-{job_id}"}


# --------------------------------------------------------------------------
# 1. "This job failed" is not "the provider is down".
# --------------------------------------------------------------------------
class TestLocalFailuresDoNotProveTheProviderIsDown:
    def test_budget_exhaustion_interleaved_with_one_refusal_does_not_abort(
        self, db_session, user_id, monkeypatch
    ):
        """The production abort shape: a mixture of local budget exhaustion and
        provider errors summing to three, none of which is three consecutive
        provider refusals.

        Pre-fix all three increment the SAME counter and the stretch aborts on
        the third job, so the fourth is never attempted.
        """
        jobs = [_seed_job(db_session, user_id, fit=99.0 - i) for i in range(4)]
        script = {
            jobs[0]: _budget_exhaustion,
            jobs[1]: _provider_refusal,
            jobs[2]: _budget_exhaustion,
            jobs[3]: _provider_refusal,
        }
        calls: list[tuple[str, str]] = []

        def _agent(uid, agent, params):
            calls.append((agent, params["job_id"]))
            raise script[params["job_id"]]()

        monkeypatch.setattr(board_sweep, "_run_agent", _agent)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        attempted = {jid for _, jid in calls}
        assert jobs[3] in attempted, (
            "two local budget exhaustions plus one provider refusal is not a "
            f"provider outage; the stretch abandoned the board at job 3. "
            f"calls={calls} summary={summary}"
        )
        assert summary["reason"] != "llm-unavailable", summary

    def test_a_successful_tailor_clears_the_provider_outage_counter(
        self, db_session, user_id, monkeypatch
    ):
        """A tailor run that SUCCEEDS is direct proof the upstream answered.

        Production logged this exact stretch twice:
        ``llm-unavailable (processed=0 tailored=1 covers=0 failures=3)`` — the
        provider demonstrably worked mid-stretch and the sweep still declared
        it down. Only a cover that produced a letter cleared the counter.
        """
        jobs = [_seed_job(db_session, user_id, fit=99.0 - i) for i in range(4)]
        calls: list[tuple[str, str]] = []

        def _agent(uid, agent, params):
            jid = params["job_id"]
            calls.append((agent, jid))
            if jid == jobs[2] and agent == "tailor":
                return {"resume_id": "r-ok"}  # the provider ANSWERED
            raise _provider_refusal()

        monkeypatch.setattr(board_sweep, "_run_agent", _agent)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert ("tailor", jobs[2]) in calls, calls
        assert summary["tailored"] == 1, summary
        attempted = {jid for _, jid in calls}
        assert jobs[3] in attempted, (
            "a tailor run SUCCEEDED in this stretch — the provider is not "
            f"down. calls={calls} summary={summary}"
        )
        assert summary["reason"] != "llm-unavailable", summary


# --------------------------------------------------------------------------
# 2. An abort must report the work it cost, not the whole backlog.
# --------------------------------------------------------------------------
class TestSuppressionAccountingIsHonest:
    def test_abort_reports_bounded_loss_and_the_backlog_separately(
        self, db_session, user_id, monkeypatch, caplog
    ):
        """``suppressed`` must be what the abort COST (bounded by the job cap
        and the remaining wall clock), with the full eligible backlog reported
        as its own, differently-named number."""
        for i in range(20):
            _seed_job(db_session, user_id, fit=99.0 - i)

        def _agent(uid, agent, params):
            raise _provider_refusal()

        monkeypatch.setattr(board_sweep, "_run_agent", _agent)
        with caplog.at_level(logging.WARNING, logger="app.workers.board_sweep"):
            summary = board_sweep.sweep_user_stretch(
                user_id, deadline=_far_deadline(), max_jobs=6
            )

        assert summary["reason"] == "llm-unavailable", summary
        # 3 attempts consumed of a 6-job cap -> at most 3 more were possible.
        assert summary["suppressed"] == 3, summary
        # The other 14 eligible jobs were never this stretch's to attempt.
        assert summary["eligible_backlog"] == 17, summary

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "17" in joined and "3" in joined, joined
        assert "backlog" in joined.lower(), (
            "the log must name the backlog as a backlog, not as work this "
            f"abort suppressed: {joined}"
        )

    def test_budget_starvation_reports_its_own_reason(
        self, db_session, user_id, monkeypatch
    ):
        """An operator must be able to tell a starved worker from a dead
        provider in the logs — the two need different remedies."""
        for i in range(8):
            _seed_job(db_session, user_id, fit=99.0 - i)

        def _agent(uid, agent, params):
            raise _budget_exhaustion()

        monkeypatch.setattr(board_sweep, "_run_agent", _agent)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["reason"] == f"llm-{_BUDGET_CLASS}", summary


# --------------------------------------------------------------------------
# 3. The circuit breaker CRITICAL-3 built must survive this fix intact.
# --------------------------------------------------------------------------
class TestTheBreakerIsPreserved:
    def test_a_real_provider_outage_still_stops_the_stretch(
        self, db_session, user_id, monkeypatch
    ):
        """Consecutive PROVIDER refusals with nothing succeeding in between is
        the case the breaker exists for. Unchanged: stop at
        ``LLM_OUTAGE_BREAKER``, never walk the job cap."""
        for i in range(8):
            _seed_job(db_session, user_id, fit=99.0 - i)
        calls: list[str] = []

        def _agent(uid, agent, params):
            calls.append(params["job_id"])
            raise _provider_refusal()

        monkeypatch.setattr(board_sweep, "_run_agent", _agent)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert len(calls) == board_sweep.LLM_OUTAGE_BREAKER, calls
        assert summary["reason"] == "llm-unavailable", summary
        assert summary["needs_continuation"] is False, summary

    def test_budget_starvation_is_bounded_and_never_walks_the_job_cap(
        self, db_session, user_id, monkeypatch
    ):
        """Every budget-exhausted attempt still made a real, paid call that
        timed out. Not counting them as a provider outage must NOT turn them
        into an unbounded walk of ``max_jobs`` — that is the CRITICAL-3
        hot-loop shape."""
        for i in range(8):
            _seed_job(db_session, user_id, fit=99.0 - i)
        calls: list[str] = []

        def _agent(uid, agent, params):
            calls.append(params["job_id"])
            raise _budget_exhaustion()

        monkeypatch.setattr(board_sweep, "_run_agent", _agent)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert len(calls) == board_sweep.LLM_BUDGET_STARVATION_BREAKER, calls
        assert len(calls) < board_sweep.sweep_max_jobs(), calls
        assert summary["needs_continuation"] is False, summary

    def test_a_non_retryable_refusal_still_stops_after_one_attempt(
        self, db_session, user_id, monkeypatch
    ):
        """402/401 fail-fast is untouched — one attempt, honest reason."""
        for i in range(6):
            _seed_job(db_session, user_id, fit=99.0 - i)
        calls: list[str] = []

        def _agent(uid, agent, params):
            calls.append(params["job_id"])
            raise _dispatch_style_503(
                LLMUnavailableError(
                    "HTTP 402", failure_class=lc.LLM_FAILURE_INSUFFICIENT_CREDITS
                )
            )

        monkeypatch.setattr(board_sweep, "_run_agent", _agent)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert len(calls) == 1, calls
        assert summary["reason"] == f"llm-{lc.LLM_FAILURE_INSUFFICIENT_CREDITS}"


# --------------------------------------------------------------------------
# 4. REGRESSION GUARD — already true pre-fix (skip-and-continue exists); these
#    pin it so the fix cannot quietly lose it.
# --------------------------------------------------------------------------
class TestOneTransientFailureNeverSuppressesTheRest:
    def test_stretch_reaches_completion_past_a_single_transient_failure(
        self, db_session, user_id, monkeypatch
    ):
        jobs = [_seed_job(db_session, user_id, fit=99.0 - i) for i in range(4)]
        calls: list[tuple[str, str]] = []

        def _agent(uid, agent, params):
            jid = params["job_id"]
            calls.append((agent, jid))
            if jid == jobs[0]:
                raise _provider_refusal()
            return _letter(jid) if agent == "coverLetter" else {"resume_id": "r"}

        monkeypatch.setattr(board_sweep, "_run_agent", _agent)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert summary["reason"] == "board-complete", summary
        assert summary["processed"] == 3, summary
        assert summary["covers"] == 3, summary
        assert summary["suppressed"] == 0, summary


# --------------------------------------------------------------------------
# 5. llm_client must be able to SAY whose fault a failure was.
# --------------------------------------------------------------------------
class TestBudgetExhaustionCarriesItsOwnClass:
    def test_budget_exhaustion_carries_a_distinct_retryable_class(
        self, tmp_path, monkeypatch
    ):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        llm._deadline = time.monotonic() - 1  # budget already spent

        def _never(self, *a, **k):
            raise AssertionError("no live call may be made on a spent budget")

        monkeypatch.setattr(LLMClient, "_call_live", _never)
        with pytest.raises(LLMUnavailableError) as ei:
            llm._auto("p", "s", "u", model="m", temperature=0.0, fixture_key="k")
        assert ei.value.failure_class == lc.LLM_FAILURE_BUDGET_EXHAUSTED
        # Still retryable: the provider never got the last word.
        assert ei.value.retryable is True

    def test_hard_budget_timeout_is_typed_and_classified_as_budget(
        self, tmp_path, monkeypatch
    ):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)

        def _boom(self, *a, **k):
            raise lc.LLMBudgetExceededError(
                "LLM call exceeded hard budget of 70.9s"
            )

        monkeypatch.setattr(LLMClient, "_call_live", _boom)
        monkeypatch.setattr(lc, "_sleep_for_backoff", lambda s: None)
        with pytest.raises(LLMUnavailableError) as ei:
            llm._auto("p", "s", "u", model="m", temperature=0.0, fixture_key="k")
        assert ei.value.failure_class == lc.LLM_FAILURE_BUDGET_EXHAUSTED

    def test_classify_llm_failure_is_unchanged_for_the_budget_error(self):
        """``_auto`` gates its next-model walk and backoff on
        ``classify_llm_failure(exc) == LLM_FAILURE_RETRYABLE``. The typed
        budget error must keep answering RETRYABLE there so the fallback model
        — which is faster and may well fit the remaining budget — is still
        tried. Only the CHAIN-EXHAUSTION class changes."""
        exc = lc.LLMBudgetExceededError("LLM call exceeded hard budget of 1.0s")
        assert isinstance(exc, RuntimeError)
        assert lc.classify_llm_failure(exc) == lc.LLM_FAILURE_RETRYABLE

    def test_budget_class_is_not_in_the_non_retryable_set(self):
        """It must never trip the PERSISTENT per-user+provider circuit breaker
        (``_record_llm_circuit_open``), which fires only for classes the
        provider itself answered."""
        assert (
            lc.LLM_FAILURE_BUDGET_EXHAUSTED
            not in lc.LLM_NON_RETRYABLE_FAILURE_CLASSES
        )
