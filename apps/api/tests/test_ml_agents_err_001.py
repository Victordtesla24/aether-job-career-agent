"""MODELS-LIVE — failing tests for ML-agents-err-001 (transient/refunded-
tolerant agent status on ``GET /agents/catalog``).

RCA: uat/reports/evidence/models-live/adversarial/AGENTS-ERRORING-RCA.md
Fix spec finalized in ``docs/delivery/MODELS-LIVE-GAPS.json`` (commit
``c239131``, "finalize err-001 fix spec (transient/refunded-tolerant
windowed agent status)").

THE DEFECT (verified): ``agent_catalog()`` (apps/api/app/routers/agents.py,
~line 1794) computes the per-agent dashboard ``status`` from the SINGLE
most-recent ``AgentRun`` with NO transient/refund classification and NO
window:

    elif run and run["status"] == "failed":
        state = "error"

So a TRANSIENT upstream failure (e.g. "The AI service is temporarily
unavailable", a 429/503/timeout) or a REFUNDED failure (``costUsd IS NULL`` —
reserved-then-refunded, never billed) paints the agent card permanently
"error" even though the agent is healthy and the user was never charged.
This is exactly the operator-visible "some agents erroring out" report
root-caused live against production in AGENTS-ERRORING-RCA.md §1-2 (a
``tailor`` run failing with "The AI service is temporarily unavailable...",
``costUsd=NULL``, painting the Resume Tailoring Agent card red until the
next real run).

DESIRED CONTRACT (CORRECTED 2026-07-23 — the ONLY valid transient signal is
the ERROR MESSAGE; see the ADVERSARIAL CORRECTION note below for why the
original ``costUsd IS NULL ⇒ refunded ⇒ active`` premise is invalid):
  1. Most-recent run failed with a TRANSIENT/upstream-unavailable error
     (temporarily unavailable / 429 / 503 / 502 / 504 / timeout / timed out
     / overloaded / rate limit / service unavailable / try again) →
     ``status == "active"`` (not "error").
  2. Most-recent run failed with ANY OTHER (generic/genuine) message —
     regardless of ``costUsd``, which is unconditionally NULL on every
     failed run in production — → ``status == "error"`` (unchanged).
     ``costUsd IS NULL`` is NOT an independent "refunded, therefore
     healthy" signal; it carries no information on its own.
  3. Most-recent run failed with a GENUINE non-transient agent-logic error
     (KeyError, validation failure — never transient wording) →
     ``status == "error"`` (unchanged).
  4. Persistence guard: the last 3 runs are ALL ``failed`` (even if each
     individually looks transient) → ``status == "error"`` — chronic
     breakage must still surface; transient-tolerance must not hide a
     persistently broken agent.
  5. Regression guard: most-recent run ``completed`` with a graceful-degrade
     output flag (``coverLetterUnavailable=true``) → ``status == "active"``
     (already correct today; must stay correct after the fix).

Test 1 (transient wording → active) is the PRIMARY reproduction — it FAILS
against pre-fix code and now PASSES against af98b04 (the fix commit).
Captured fail output:
uat/reports/evidence/models-live/adversarial/ERR-001-TESTS-FAIL.md.
Test 2 (renamed 2026-07-23 to ``test_generic_nontransient_failure_shows_error``;
see ADVERSARIAL CORRECTION below) now FAILS against af98b04 — that failure
is the correctly-reproduced BLOCKER, not a regression.

ADVERSARIAL CORRECTION (2026-07-23): af98b04 FAILED review with a BLOCKER.
``_is_transient_or_refunded_failure`` (agents.py:1794) returns True
whenever ``run.get("costUsd") is None`` — checked BEFORE the keyword
check. But NO ``AgentRunRepository.finish(..., "failed", ...)`` call site
in the whole codebase ever passes ``cost_usd`` — confirmed by grep:
    agents.py:735   runs.finish(run_id, "failed", error="http error")
    agents.py:771   runs.finish(run_id, "failed", error=str(exc))
    agents.py:788   runs.finish(run_id, "failed", error=LLM_UNAVAILABLE_USER_MESSAGE)
    agents.py:794   runs.finish(run_id, "failed", error=str(exc))
    agents.py:1185  runs.finish(run["id"], "failed", error="generation queue unavailable")
    workers/tasks.py:109  AgentRunRepository().finish(run_id, "failed", error=...)
``cost_usd`` is only ever passed on the SUCCESS path (agents.py:841,
``runs.finish(run_id, "completed", output=output, cost_usd=cost)``). So in
production ``costUsd`` is ALWAYS NULL on a failed run — the "genuine
billed failure" case the fix's docstring/tests claimed to guard against
(``costUsd`` a real positive value on a failed run) never occurs. The
original test 3 (``test_genuine_billed_failure_still_shows_error``) seeded
an UNREALISTIC ``cost_usd=0.0164`` on a FAILED run, which skipped the
``costUsd IS NULL`` early-return and exercised only the keyword branch —
masking the BLOCKER. That test and a new alternating-failures test below
are corrected to the production-realistic ``costUsd=None`` seeding; they
now FAIL against af98b04, proving genuine billed logic errors (KeyError,
validation) are misclassified as transient and hidden as "active".

No production code is modified by this file — see the DO-NOT-IMPLEMENT
instruction on the test-author brief; a fixer session addresses the defect.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.db import new_id

# The Resume Tailoring Agent — the exact agent/catalog-key the live RCA
# (AGENTS-ERRORING-RCA.md §1-2) observed painted red by a transient, refunded
# failure ("tailor" backend, "resumeTailoring" catalog key).
_BACKEND = "tailor"
_CATALOG_KEY = "resumeTailoring"

# The Cover Letter Agent — used for the graceful-degrade regression guard
# (test 5), matching the real coverLetterUnavailable flag shape from
# AGENTS-ERRORING-RCA.md §4 run #4.
_COVER_BACKEND = "coverLetter"
_COVER_CATALOG_KEY = "coverLetter"

_GENUINE_ERROR = (
    "KeyError: 'summary' — resume section missing required field during "
    "tailoring"
)


def _seed_run(
    cur,
    user_id: str,
    *,
    status: str,
    error: str | None = None,
    cost_usd: float | None = None,
    output: dict | None = None,
    created_at: datetime,
    agent_name: str = _BACKEND,
) -> None:
    """Insert one AgentRun row with an explicit createdAt for deterministic
    'most recent' / 'last N' ordering — mirrors the seeding style used by
    test_gap_p6_admin.py::_seed_runs and
    test_mv_email_center.py::_seed_draft_reply_run.
    """
    cur.execute(
        '''
        INSERT INTO "AgentRun"
            ("id", "userId", "agentName", "status", "error", "costUsd",
             "output", "startedAt", "completedAt", "createdAt")
        VALUES (%s, %s, %s, %s::"AgentRunStatus", %s, %s, %s::jsonb,
                %s, %s, %s)
        ''',
        (
            new_id(), user_id, agent_name, status, error, cost_usd,
            json.dumps(output or {}), created_at, created_at, created_at,
        ),
    )


def _catalog_entry(client, auth_headers, key: str) -> dict:
    res = client.get("/agents/catalog", headers=auth_headers)
    assert res.status_code == 200, res.text
    by_key = {a["key"]: a for a in res.json()["agents"]}
    assert key in by_key, f"{key!r} missing from catalog: {sorted(by_key)}"
    return by_key[key]


# ---------------------------------------------------------------------------
# 1. PRIMARY — transient/upstream-unavailable failure must NOT paint "error"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "transient_message",
    [
        "The AI service is temporarily unavailable. Please try again in a moment.",
        "LLM provider HTTP 429: rate-limited upstream, please retry shortly",
        "LLM backend unavailable: live call failed: HTTP 503 Service Unavailable",
        "LLMUnavailableError: upstream request timed out after 30s",
    ],
)
def test_transient_failure_shows_active_not_error(
    client, auth_headers, test_user_id, db_session, transient_message,
):
    """FAILS NOW: ``agent_catalog()`` paints ANY ``status='failed'`` last run
    as ``'error'`` regardless of whether the failure was a transient upstream
    blip. This is the live RCA's exact reproduction — a 429 / "temporarily
    unavailable" failure, refunded (``costUsd`` NULL), must show the agent as
    healthy ("active"), not persistently broken.
    """
    with db_session.cursor() as cur:
        _seed_run(
            cur, test_user_id,
            status="failed", error=transient_message, cost_usd=None,
            created_at=datetime.now(timezone.utc),
        )
    db_session.commit()

    entry = _catalog_entry(client, auth_headers, _CATALOG_KEY)
    assert entry["status"] == "active", (
        f"{_CATALOG_KEY} shows status={entry['status']!r} after a single "
        f"transient/refunded failure ({transient_message!r}) — the catalog "
        "must not paint a healthy agent red for a transient upstream blip "
        "(ML-agents-err-001)"
    )


# ---------------------------------------------------------------------------
# 2. GUARD — generic non-transient failure (costUsd IS NULL) still "error"
# ---------------------------------------------------------------------------


def test_generic_nontransient_failure_shows_error(
    client, auth_headers, test_user_id, db_session,
):
    """CORRECTED (2026-07-23 adversarial fixture correction): this test
    used to be named ``test_refunded_failure_shows_active_not_error`` and
    asserted "active" on the theory that ``costUsd IS NULL`` alone (a
    "refunded / never billed" run) was an independent honest transient
    signal. That premise is INVALID: grep confirms NO
    ``AgentRunRepository.finish(..., "failed", ...)`` call site anywhere in
    the codebase (agents.py:735,771,788,794,1185; workers/tasks.py:109)
    ever passes ``cost_usd`` — it is set only on the success path
    (agents.py:841). So ``costUsd`` is unconditionally NULL on EVERY failed
    run in production; "costUsd IS NULL" carries no information about
    whether a failure was transient or genuine and cannot be used as a
    classification signal on its own.

    The correct contract (MODELS-LIVE-GAPS.json, corrected 2026-07-23) is
    that ONLY the error message's wording determines transience. This
    fixture seeds a failed run with ``costUsd=None`` (production-realistic
    for ALL failures) and a GENERIC, non-transient message — no
    "temporarily unavailable" / 429 / 503 / 502 / 504 / timeout / "timed
    out" / overloaded / "rate limit" / "service unavailable" / "try again"
    wording anywhere in it. A generic message like this is GENUINE agent
    breakage and must surface as "error", not be swallowed as "active"
    merely because costUsd happens to be NULL (as it always is on failure).
    Transient-wording → "active" is already covered independently by
    ``test_transient_failure_shows_active_not_error`` above.

    EXPECTED TO FAIL against af98b04 — the BLOCKER checks ``costUsd is
    None`` before the keyword check, so this generic non-transient failure
    is wrongly classified as transient/refunded and shown "active".
    """
    with db_session.cursor() as cur:
        _seed_run(
            cur, test_user_id,
            status="failed",
            error="Unexpected error occurred while processing the request.",
            cost_usd=None,
            created_at=datetime.now(timezone.utc),
        )
    db_session.commit()

    entry = _catalog_entry(client, auth_headers, _CATALOG_KEY)
    assert entry["status"] == "error", (
        f"{_CATALOG_KEY} shows status={entry['status']!r} after a single "
        "generic, non-transient failure (costUsd IS NULL, as ALL failed "
        "runs are in production) — costUsd being NULL is not itself a "
        "transient signal; only transient WORDING should map to 'active' "
        "(ML-agents-err-001 guard)"
    )


# ---------------------------------------------------------------------------
# 3. GUARD — genuine (non-transient) agent-logic failure still shows "error"
# ---------------------------------------------------------------------------


def test_genuine_billed_failure_still_shows_error(
    client, auth_headers, test_user_id, db_session,
):
    """ADVERSARIAL CORRECTION (2026-07-23): seeds ``cost_usd=None`` — the
    PRODUCTION-REALISTIC value for every failed AgentRun. No
    ``AgentRunRepository.finish(..., "failed", ...)`` call site (agents.py
    :735,771,788,794,1185; workers/tasks.py:109) ever passes ``cost_usd`` —
    it is only ever set on the success path (agents.py:841). A "genuinely
    billed" failure with a real positive ``costUsd`` does not exist in
    production, so seeding one (as the original version of this test did,
    ``cost_usd=0.0164``) is a fake-pass fixture that never exercises the
    ``costUsd IS NULL`` early-return branch of
    ``_is_transient_or_refunded_failure`` and therefore cannot catch the
    BLOCKER: that function returns True for EVERY failed run (since
    ``costUsd`` is unconditionally NULL) BEFORE it ever reaches the keyword
    check, so a genuine, non-transient agent-logic error (KeyError,
    validation failure — never "temporarily unavailable"/429/503/timeout)
    is misclassified as transient/refunded and the card is painted "active"
    instead of "error", hiding real breakage from the operator.

    EXPECTED TO FAIL against af98b04 — that failure IS the reproduction of
    the BLOCKER.
    """
    with db_session.cursor() as cur:
        _seed_run(
            cur, test_user_id,
            status="failed", error=_GENUINE_ERROR, cost_usd=None,
            created_at=datetime.now(timezone.utc),
        )
    db_session.commit()

    entry = _catalog_entry(client, auth_headers, _CATALOG_KEY)
    assert entry["status"] == "error", (
        f"{_CATALOG_KEY} shows status={entry['status']!r} for a genuine, "
        "non-transient agent-logic failure (costUsd=None, as ALL failed "
        "runs are in production) — real breakage must still surface as "
        "'error' (ML-agents-err-001 guard; BLOCKER: costUsd IS NULL is "
        "checked before the keyword check, so this is misclassified as "
        "transient/refunded and shown 'active')"
    )


# ---------------------------------------------------------------------------
# 3b. PRIMARY (corrected) — alternating genuine failures must show "error"
# ---------------------------------------------------------------------------


def test_alternating_genuine_failures_show_error(
    client, auth_headers, test_user_id, db_session,
):
    """ADDED (2026-07-23 adversarial correction): the 3-consecutive-failures
    "chronic" guard (test 4 below) is NOT sufficient to catch genuine
    breakage — an agent that fails on every other run (>=50% failure rate)
    but never fails 3-in-a-row will never trip the chronic guard, and
    because ``costUsd`` is unconditionally NULL on every failed run in
    production (see module docstring), ``_is_transient_or_refunded_failure``
    misclassifies each of those genuine failures as transient/refunded.
    Seeds ~10 runs (oldest to newest) alternating genuine-failure
    (``cost_usd=None``, KeyError-style non-transient error) / success, with
    the LATEST run a genuine failure and >=50% of the runs failed, but never
    3 consecutive failures — so only the (non-chronic) transient/refunded
    classification of the single most-recent failed run determines the
    catalog status.

    EXPECTED TO FAIL against af98b04 — the latest run is a genuine failure
    with ``costUsd=None``, so the BLOCKER classifies it as
    transient/refunded and the catalog wrongly shows "active" instead of
    "error".
    """
    base = datetime.now(timezone.utc)
    # 10 runs, oldest first: completed, failed, completed, failed, ... ,
    # ending on a failed run (index 9, the most recent — highest createdAt).
    # 5/10 = 50% failed; no 3 consecutive failures anywhere in the sequence.
    #
    # LOOP-PARITY FIX (2026-07-23 adversarial fixture correction): the prior
    # version used ``if i % 2 == 0: failed`` which made index 9 (odd) the
    # COMPLETED run — i.e. the MOST RECENT run was healthy, contradicting
    # this test's own docstring/purpose and making the "error" assertion
    # unsatisfiable by any correct implementation (a completed latest run
    # correctly yields "active"). Flipped to ``i % 2 == 1: failed`` so the
    # newest run (i=9, highest createdAt) is the genuine failure.
    with db_session.cursor() as cur:
        for i in range(10):
            created_at = base - timedelta(minutes=(9 - i) * 5)
            if i % 2 == 1:
                _seed_run(
                    cur, test_user_id,
                    status="failed", error=_GENUINE_ERROR, cost_usd=None,
                    created_at=created_at,
                )
            else:
                _seed_run(
                    cur, test_user_id,
                    status="completed", error=None, cost_usd=0.02,
                    output={"summary": "tailoring completed"},
                    created_at=created_at,
                )
    db_session.commit()

    entry = _catalog_entry(client, auth_headers, _CATALOG_KEY)
    assert entry["status"] == "error", (
        f"{_CATALOG_KEY} shows status={entry['status']!r} after an "
        "alternating genuine-failure/success run history (latest run a "
        "genuine, non-transient failure, 50% failure rate, never 3 "
        "consecutive failures) — the chronic (3-in-a-row) guard alone must "
        "not be relied on to catch genuine breakage; the single most-recent "
        "genuine failure must independently surface as 'error' "
        "(ML-agents-err-001 guard; exposes the same costUsd-IS-NULL "
        "BLOCKER as the corrected test 3)"
    )


# ---------------------------------------------------------------------------
# 4. GUARD (persistence) — last 3 runs ALL failed still shows "error"
# ---------------------------------------------------------------------------


def test_chronic_failures_still_show_error_despite_transient_wording(
    client, auth_headers, test_user_id, db_session,
):
    """GUARD, already PASSES against current code (documented): even if
    every one of the last 3 runs individually LOOKS transient (refunded,
    "temporarily unavailable"-style wording), 3-for-3 failures in a row is
    chronic breakage, not a one-off blip, and must still surface as "error"
    — a transient-tolerant fix must not blanket-hide a persistently broken
    agent. Passes today (trivially, since current code only ever inspects
    the single last run, which is itself 'failed' here); must keep passing
    once the fix adds a persistence/window check on top of the transient
    exception from tests 1-2. Seeds were already ``cost_usd=None``
    (production-realistic) prior to the 2026-07-23 adversarial correction —
    no change needed here.
    """
    base = datetime.now(timezone.utc)
    with db_session.cursor() as cur:
        for i in range(3):
            _seed_run(
                cur, test_user_id,
                status="failed",
                error="The AI service is temporarily unavailable. Please try again in a moment.",
                cost_usd=None,
                created_at=base - timedelta(minutes=(2 - i) * 5),
            )
    db_session.commit()

    entry = _catalog_entry(client, auth_headers, _CATALOG_KEY)
    assert entry["status"] == "error", (
        f"{_CATALOG_KEY} shows status={entry['status']!r} after 3 "
        "consecutive failed runs — chronic breakage must surface as "
        "'error' even when each individual failure looks transient "
        "(ML-agents-err-001 persistence guard)"
    )


# ---------------------------------------------------------------------------
# 5. REGRESSION GUARD — graceful degrade (completed) still shows "active"
# ---------------------------------------------------------------------------


def test_graceful_degrade_completed_run_still_shows_active(
    client, auth_headers, test_user_id, db_session,
):
    """REGRESSION GUARD, already PASSES against current code (documented):
    a run that COMPLETED with a graceful-degrade output flag (e.g.
    ``coverLetterUnavailable: true``, ``costUsd: 0.0`` — the real shape from
    AGENTS-ERRORING-RCA.md §4 run #4) is status='completed', never
    'failed', so it must keep showing "active". This is the honest-degrade
    contract the RCA confirmed already works correctly; a windowed/
    transient-tolerant fix to the 'failed' path must not regress it.
    """
    with db_session.cursor() as cur:
        _seed_run(
            cur, test_user_id,
            status="completed", error=None, cost_usd=0.0,
            output={
                "coverLetterUnavailable": True,
                "message": (
                    "Your cover letter writing model was temporarily "
                    "unavailable. Please try again."
                ),
            },
            created_at=datetime.now(timezone.utc),
            agent_name=_COVER_BACKEND,
        )
    db_session.commit()

    entry = _catalog_entry(client, auth_headers, _COVER_CATALOG_KEY)
    assert entry["status"] == "active", (
        f"{_COVER_CATALOG_KEY} shows status={entry['status']!r} after a "
        "completed run with a graceful coverLetterUnavailable degrade — "
        "this honest-degrade contract must not regress (ML-agents-err-001)"
    )
