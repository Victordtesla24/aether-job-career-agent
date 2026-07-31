"""GMV4-tailor-001 — HTTP-BOUNDARY regression tests (§22 STEP 2, GOLD-MASTER-V4).

Coverage gap this file closes (reviewer finding, not re-litigated here): the 4
existing contract tests (``test_tailor_response_contract.py``) exercise only
``TailoringAgent.run()`` directly via ``dataclasses.asdict()`` — they never
drive the actual HTTP router (``agents.py`` ``run_tailor``'s hand-built 200
response dict) or the async ``GET /agents/jobs/{job_id}`` poll path
(``_job_status_payload`` -> ``job.get("result")``), which is EXACTLY the layer
where the original GMV4-tailor-001 bug lived: the router whitelisted its
response keys and silently dropped ``iterations``/``gapKeywords`` even though
``TailoringAgent.run()`` had already computed them. A future regression
re-dropping a key from that dict (or a ``.get()`` key typo) would pass all 4
existing tests undetected. These tests drive both real HTTP paths with
``TestClient`` so that class of regression is caught here.

The fix is ALREADY present in the working tree (``TailorRunResult`` carries
``iterations``/``gapKeywords`` — tailor_agent.py:311-327 — and ``run_tailor``
serves both — agents.py:2390-2399), so every test below is expected to PASS
against current code; these are REGRESSION tests, not fail-first defect
reproductions. Teeth were proven by a separate, NOT-committed monkeypatch
demonstration (see the STEP-2 execution report for the verbatim RED/GREEN
transcript) rather than a ``git stash`` of the two source files: this file's
production siblings (``apps/api/app/routers/agents.py`` in particular) carry
OTHER workstreams' concurrent uncommitted work (an in-progress SSE endpoint)
in the SAME file, and a file-level stash/pop of a live shared file mid-swarm
was judged too risky to hold open for the duration of the shared
``aether_test`` pytest lock queue — the task brief's own explicit fallback for
exactly this situation.
"""
from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from app.agents.tailor_agent import TailorRunResult
from app.repositories.agent_run import AgentRunRepository
from app.repositories.background_jobs import BackgroundJobRepository

# --- shared stub fixture -----------------------------------------------------

_CONVERSION_METRICS: dict[str, Any] = {
    "baselineATSScore": 40.0,
    "tailoredATSScore": 91.0,
    "estimatedConversionLift": "+1.3%",
    "methodology": "Like-for-like ATS delta (shared context) x population baseline (2.5%)",
    "confidence": "model-estimated",
}

_ITERATIONS: list[dict[str, Any]] = [
    {
        "iteration": 1,
        "score": 40.0,
        "gapKeywords": ["kubernetes", "kafka"],
        "changes": 2,
        "rejected": [],
    },
    {
        "iteration": 2,
        "score": 91.0,
        "gapKeywords": ["kafka"],
        "changes": 2,
        "rejected": [],
    },
]
_GAP_KEYWORDS: list[str] = ["kafka"]

#: The full pre-existing response shape (everything ``run_tailor`` served
#: BEFORE GMV4-tailor-001) plus the two fields the fix added — asserted as an
#: exact SET below so a future removal (from either side) fails loudly.
_PREEXISTING_KEYS = {
    "resume_id",
    "changes",
    "rejected",
    "conversionMetrics",
    "approvalRequired",
    "approval_id",
    "approval_status",
    "warning",
}
_NEW_KEYS = {"iterations", "gapKeywords"}


def _make_result(**overrides: Any) -> TailorRunResult:
    """A real ``TailorRunResult`` (not a duck-typed dict) with known,
    non-trivial ``iterations``/``gapKeywords`` — exactly the object
    ``TailoringAgent.run()`` returns today, so ``_to_output``'s
    ``dataclasses.asdict()`` path is exercised for real."""
    fields: dict[str, Any] = dict(
        resume_id="child-resume-http-1",
        changes=2,
        rejected=[],
        conversionMetrics=dict(_CONVERSION_METRICS),
        approval_id="appr-http-1",
        approval_status="pending",
        warning=None,
        iterations=[dict(it) for it in _ITERATIONS],
        gapKeywords=list(_GAP_KEYWORDS),
    )
    fields.update(overrides)
    return TailorRunResult(**fields)


def _stub_run(monkeypatch: Any, result: TailorRunResult) -> None:
    """Replace ``TailoringAgent.run`` so the router/worker execute against a
    REAL, fully-controlled ``TailorRunResult`` with no DB/LLM dependence —
    the same monkeypatch seam ``test_gap_p7_async_001.py``'s ``_stub_tailor``
    already establishes for this class."""

    def _run(self: Any, *args: Any, **kwargs: Any) -> TailorRunResult:
        return result

    monkeypatch.setattr(
        "app.agents.tailor_agent.TailoringAgent.run", _run, raising=True
    )


# =============================================================================
# 1. Sync HTTP route (POST /agents/tailor/run) carries the new fields.
# =============================================================================


def test_sync_tailor_run_http_response_includes_iterations_and_gap_keywords(
    client: Any, auth_headers: dict[str, str], monkeypatch: Any
) -> None:
    """Drives the REAL router (``agents.py`` ``run_tailor``'s hand-built 200
    dict), not ``TailoringAgent.run()`` in isolation. Before GMV4-tailor-001
    this dict omitted both keys entirely, regardless of what the agent
    computed — the exact bug class the 4 existing dataclass-level tests
    cannot see."""
    result = _make_result()
    _stub_run(monkeypatch, result)

    r = client.post(
        "/agents/tailor/run", json={"job_id": "job-http-1"}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert "iterations" in body, f"response keys were: {sorted(body.keys())}"
    assert "gapKeywords" in body, f"response keys were: {sorted(body.keys())}"
    assert body["iterations"] == _ITERATIONS, body["iterations"]
    assert body["gapKeywords"] == _GAP_KEYWORDS, body["gapKeywords"]


# =============================================================================
# 2. Additive-only guard: every pre-existing key survives, exact key SET.
# =============================================================================


def test_sync_tailor_run_http_response_preserves_all_preexisting_keys(
    client: Any, auth_headers: dict[str, str], monkeypatch: Any
) -> None:
    """GMV4-tailor-001 must be a PURELY additive change to the sync response
    shape. Asserting the exact SET (not just ``in``) means a future removal
    of ANY of the 8 pre-existing keys — or an unexpected new key — fails this
    test, not just a missing-iterations test."""
    result = _make_result()
    _stub_run(monkeypatch, result)

    r = client.post(
        "/agents/tailor/run", json={"job_id": "job-http-2"}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()

    expected = _PREEXISTING_KEYS | _NEW_KEYS
    assert set(body.keys()) == expected, (
        f"missing={sorted(expected - set(body.keys()))} "
        f"unexpected={sorted(set(body.keys()) - expected)}"
    )
    # Sanity: the pre-existing values themselves are untouched by the fix.
    assert body["resume_id"] == "child-resume-http-1"
    assert body["changes"] == 2
    assert body["rejected"] == []
    assert body["conversionMetrics"] == _CONVERSION_METRICS
    assert body["approval_id"] == "appr-http-1"
    assert body["approval_status"] == "pending"
    assert body["warning"] is None


# =============================================================================
# 3. Async poll path (the UI's ACTUAL path): run_agent_job -> mark_completed
#    -> GET /agents/jobs/{job_id}.
# =============================================================================


def test_async_job_poll_response_includes_iterations_and_gap_keywords(
    client: Any, auth_headers: dict[str, str], test_user_id: str, monkeypatch: Any
) -> None:
    """The UI polls ``GET /agents/jobs/{job_id}`` for an async-generated
    tailor run (blueprint §3.3) — a COMPLETELY different code path from the
    sync 200 dict tested above (``run_agent_job`` ->
    ``_run_single_agent_body`` -> ``_execute_reserved_run`` ->
    ``repo.mark_completed`` -> ``_job_status_payload``). It happens to already
    forward ``output`` UNFILTERED (no whitelist), so this is primarily a
    PERMANENT regression lock against that ever changing to a whitelist
    projection — exercised end-to-end for real rather than assumed."""
    from app.workers.tasks import run_agent_job

    async_iterations = [
        {
            "iteration": 1,
            "score": 55.0,
            "gapKeywords": ["docker", "kafka"],
            "changes": 3,
            "rejected": [],
        },
        {
            "iteration": 2,
            "score": 88.0,
            "gapKeywords": ["docker"],
            "changes": 1,
            "rejected": ["bad bullet"],
        },
    ]
    async_gap_keywords = ["docker"]
    result = _make_result(
        resume_id="child-resume-async-1",
        iterations=async_iterations,
        gapKeywords=async_gap_keywords,
    )
    _stub_run(monkeypatch, result)

    run = AgentRunRepository().start(
        test_user_id, "tailor", {"job_id": "job-http-async-1"}
    )
    job_id = BackgroundJobRepository().create(
        test_user_id,
        "tailor",
        run_id=run["id"],
        params={"job_id": "job-http-async-1"},
        quota_reserved=False,
    )

    asyncio.run(run_agent_job({}, job_id))

    r = client.get(f"/agents/jobs/{job_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed", body
    polled = body.get("result")
    assert polled is not None, body
    assert "iterations" in polled, f"result keys were: {sorted(polled.keys())}"
    assert "gapKeywords" in polled, f"result keys were: {sorted(polled.keys())}"
    assert polled["iterations"] == async_iterations, polled["iterations"]
    assert polled["gapKeywords"] == async_gap_keywords, polled["gapKeywords"]


# =============================================================================
# 4. Generic guard against the ORIGINAL bug class (not just this instance).
# =============================================================================


def test_router_whitelist_does_not_silently_drop_new_result_fields(
    client: Any, auth_headers: dict[str, str], monkeypatch: Any
) -> None:
    """Rather than hardcoding "iterations"/"gapKeywords" again, this walks
    ``TailorRunResult``'s OWN field list via ``dataclasses.fields()`` at
    test-run time and checks every one reaches the HTTP body. A THIRD field
    added to the dataclass later, that the router's hand-built response dict
    forgets to add, fails THIS test too — without anyone touching it.

    ``_INTERNAL_ONLY_FIELDS`` is the one documented escape hatch for a field
    genuinely never meant to reach the client. It is empty today: every
    current ``TailorRunResult`` field (``resume_id``, ``changes``,
    ``rejected``, ``conversionMetrics``, ``approval_id``, ``approval_status``,
    ``warning``, ``iterations``, ``gapKeywords``) is already served verbatim
    by ``run_tailor`` (agents.py:2376-2400), so a fully generic assertion
    (dataclass field set minus the allowlist, compared against the response
    key set) is practical here and does not need a specific-key fallback.
    """
    _INTERNAL_ONLY_FIELDS: set[str] = set()

    result = _make_result()
    _stub_run(monkeypatch, result)

    r = client.post(
        "/agents/tailor/run", json={"job_id": "job-http-4"}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()

    dataclass_field_names = {f.name for f in dataclasses.fields(TailorRunResult)}
    expected = dataclass_field_names - _INTERNAL_ONLY_FIELDS
    missing = expected - set(body.keys())
    assert not missing, (
        f"TailorRunResult field(s) {sorted(missing)} are computed by the "
        f"agent but do not reach the HTTP response body — response keys "
        f"were: {sorted(body.keys())}"
    )


# --- teeth, proven WITHOUT a source-file revert -----------------------------
#
# Verbatim RED/GREEN transcripts for a genuine mutation of the object each
# test observes (a TailorRunResult that's missing the fields the fix added,
# and — for test 4 — a dataclass SUBCLASS carrying one extra field the router
# was never told about) live in the STEP-2 execution report, not in this
# committed file: the demonstration module was run standalone and then
# deleted, so this file always tests real, unmodified production code.
