"""GMV4-tailor-001 (HIGH) — the tailoring RESPONSE contract omits iteration
data (§22 STEP 2, GOLD-MASTER-V4).

``POST /agents/tailor/run`` (``apps/api/app/routers/agents.py:2292``) builds
its JSON body from ``output = _dispatch(...)``, which is
``_to_output(TailoringAgent.run(...))`` (``routers/agents.py:579-582``):

    def _to_output(result: Any) -> dict[str, Any]:
        if is_dataclass(result) and not isinstance(result, type):
            return asdict(result)
        ...

i.e. for the tailor backend the HTTP response body is *exactly*
``dataclasses.asdict(TailorRunResult)`` plus one router-added key
(``approvalRequired = agent_name in _APPROVAL_GATED``, a static membership
check unrelated to the run's content — ``"tailor" in _APPROVAL_GATED`` is
always True, see ``routers/agents.py:95-98,1146``).

That equivalence is why these tests exercise ``TailoringAgent.run()``
directly (via ``dataclasses.asdict``) with lightweight duck-typed stubs for
its repository dependencies — exactly the pattern the codebase's OWN authors
already established for this agent in ``test_gap_p6_tailoring_ats.py``. This
is the SAME response contract the router serves, reached without any DB,
HTTP, or LLM call — the smallest honest test for a defect that lives in
``TailorRunResult``'s shape, not in routing/auth/persistence plumbing.

PLUMBING VS COMPUTATION — explicit finding (required by the task brief):
``TailoringLoop.run()`` (app/services/tailoring_loop.py:152-222) ALREADY
computes everything this defect asks to expose:
  - ``TailoringLoopResult.iterations``: one dict per attempt, each carrying
    ``"iteration"`` (1-based index), ``"score"`` (ATS overall for that
    attempt), ``"gapKeywords"`` (cleaned missing-keyword list), ``"changes"``,
    ``"rejected"`` (tailoring_loop.py:179-186).
  - ``TailoringLoopResult.warning``: an honest, NEVER-clamped sub-target
    message naming the achieved best score (tailoring_loop.py:204-212).
This is a PLUMBING job, not a computation job, for the ``iterations`` /
``gapKeywords`` gap: ``TailoringAgent.run()`` (app/agents/tailor_agent.py:
420-525) receives ``loop_result.iterations`` and WRITES it to the DB
(``sections["tailoringIterations"]``, tailor_agent.py:463) but never copies
it onto the returned ``TailorRunResult`` dataclass (tailor_agent.py:281-295
lists that dataclass's fields: no ``iterations``, no ``gapKeywords``). The
data exists in memory at the exact point the dataclass is constructed; it is
simply not assigned to a field.

Two claims in the human-authored finding do NOT hold at the backend/API
layer once actually read (both confirmed against apps/web/src too — noted so
the implementer does not duplicate work):
  - ``conversionMetrics.baselineATSScore`` / ``.tailoredATSScore`` ALREADY
    exist in the response today (``_compute_conversion_metrics``,
    tailor_agent.py:71-119, wired into ``TailorRunResult.conversionMetrics``
    at tailor_agent.py:472-479) and ARE already read by
    ``apps/web/src/app/dashboard/resume/page.tsx:365-366`` (the "Before: X% →
    After: Y%" banner). The screen-tester's "rendered nowhere" observation is
    real but is a FRONTEND wiring gap on a DIFFERENT page
    (``apps/web/src/app/dashboard/jobs/page.tsx`` — see that file's own test
    docstring at ``__tests__/tailor-score-refresh.test.tsx:6-8``: "conversionMetrics
    is never read anywhere in jobs/page.tsx"), not a missing backend field.
    ``test_tailor_response_includes_ats_score_before_and_after`` below is
    therefore written to fail on the genuine remaining gap — that the
    after-score cannot be traced back to a real optimizer iteration, because
    ``iterations`` is entirely absent — rather than on presence of
    ``conversionMetrics`` itself (which would trivially pass and be a
    defective test).

    IMPORTANT wrinkle discovered while writing these tests (verbatim run
    evidence below): ``_compute_conversion_metrics`` builds its OWN fresh
    ``ATSEngine()`` internally (tailor_agent.py:94) instead of reusing the
    ``ats_engine`` the loop was given — so ``conversionMetrics.tailoredATSScore``
    is a SEPARATE, independently-computed real-engine score, not simply a
    copy of the loop's own winning-iteration score. It also re-scores against
    a DIFFERENT job-description string than the loop used internally
    (``job.get("description") or ""`` at tailor_agent.py:474 vs. the loop's
    ``f"{title} at {company}. {description}"`` built at tailor_agent.py:399).
    This means a test cannot assert exact numeric equality between a stubbed
    loop score and ``conversionMetrics`` without asserting something false —
    the tests below deliberately do NOT do that; they assert presence/
    traceability-by-shape only. This double-scoring-with-different-JD-text
    discrepancy is itself worth the implementer's attention but is a SEPARATE
    concern from GMV4-tailor-001 and is called out here only so it is not
    mistaken for a test bug.
  - ``warning``/honest sub-target reporting (§5.3.1 point 5) is ALREADY wired
    end-to-end and does not clamp (tailor_agent.py:524,
    tailoring_loop.py:202-212). ``test_tailor_sub_target_score_is_reported_honestly``
    is included per the task brief as the anti-dishonesty regression lock;
    see its own docstring for the verbatim run result confirming it already
    passes, and why it is kept rather than dropped.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.agents.tailor_agent import TailoringAgent
from app.services.ats_engine import ATSScore
from app.services.resume_tailor import TailorResult

# --- shared synthetic fixture (no bundled-PDF / DB / LLM dependence) --------

_RESUME = (
    "JANE DOE\n"
    "Senior Backend Engineer\n"
    "\n"
    "SKILLS\n"
    "Python, PostgreSQL, REST\n"
    "\n"
    "EXPERIENCE\n"
    "Acme Corp\n"
    "2019 - 2024 | Sydney\n"
    "- Built backend services handling 2000000 requests per day, cutting latency by 40%.\n"
    "- Led a team of 5 engineers delivering payment features.\n"
)
_ORIGINAL_BULLETS = [
    {
        "text": "Built backend services handling 2000000 requests per day, cutting latency by 40%.",
        "evidenceRef": "bullet-0",
    },
    {"text": "Led a team of 5 engineers delivering payment features.", "evidenceRef": "bullet-1"},
]
_JD = (
    "Senior Backend Engineer. Requirements: Python, PostgreSQL, REST, "
    "Kubernetes, Kafka, backend services."
)


class _StubStories:
    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:  # noqa: ANN001
        return []


class _StubJobs:
    def get_by_id(self, job_id: str, user_id: str) -> dict[str, Any]:  # noqa: ANN001
        return {"title": "Backend Engineer", "company": "Acme", "description": _JD}

    def advance_status(self, *a: Any, **k: Any) -> None:  # noqa: ANN401
        pass


class _StubResumes:
    """Records the persisted ``sections`` payload so a caller can inspect
    exactly what would be written to the DB (mirrors what
    ``ResumeRepository.create`` actually persists into the ``Resume.sections``
    JSON column, without touching Postgres)."""

    def __init__(self) -> None:
        self.created_sections: dict[str, Any] | None = None

    def get_by_id(self, resume_id: str, user_id: str) -> dict[str, Any]:  # noqa: ANN001
        return {
            "id": "base-1",
            "formatHash": "hash-1",
            "sections": {"raw_text": _RESUME, "bullets": _ORIGINAL_BULLETS},
        }

    def create(self, user_id: str, sections: dict[str, Any], *a: Any, **k: Any) -> dict[str, Any]:  # noqa: ANN401
        self.created_sections = sections
        return {"id": "child-1"}

    def next_version(self, user_id: str) -> int:  # noqa: ANN001
        return 2


class _StubApprovals:
    def create(self, user_id: str, kind: str, extras: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        return {"id": "appr-1", "status": "pending"}


class _ScriptedService:
    """Each call returns a bullet rewrite that DIFFERS from the current
    originals (so ``changes >= 1`` on every iteration — never triggers
    ``NoChangesApplied``), with no rejections."""

    def __init__(self) -> None:
        self.calls = 0

    def tailor(
        self, resume_text: str, jd: str, originals: Any = None, evidence_extra: str = ""
    ) -> TailorResult:
        self.calls += 1
        base = list(originals or _ORIGINAL_BULLETS)
        rewritten = [
            {
                "text": f"{b['text']} (pass {self.calls})",
                "evidenceRef": b.get("evidenceRef", f"bullet-{i}"),
            }
            for i, b in enumerate(base)
        ]
        return TailorResult(
            bullets=rewritten,
            originals=base,
            changes=len(rewritten),
            rejected=[],
        )


class _ScriptedATSEngine:
    """Deterministic, fully controllable scorer: returns scripted
    ``overall``/``missing_keywords`` per call, independent of the real
    ``ATSEngine`` heuristics — makes the loop's iteration count and final
    score fully predictable for the assertions below."""

    def __init__(self, scores: list[float], missing: list[list[str]]) -> None:
        self._scores = scores
        self._missing = missing
        self.calls = 0

    def score(self, resume_text: str, job_description: str) -> ATSScore:
        i = min(self.calls, len(self._scores) - 1)
        self.calls += 1
        return ATSScore(
            overall=self._scores[i],
            keyword_match=self._scores[i],
            semantic_similarity=self._scores[i],
            experience_gap=100.0,
            matched_keywords=[],
            missing_keywords=self._missing[min(i, len(self._missing) - 1)],
            requires_review=self._scores[i] < 85.0,
        )


def _run_agent(*, scores: list[float], missing: list[list[str]]) -> dict[str, Any]:
    """Runs ``TailoringAgent.run()`` fully DB/LLM-free and returns the EXACT
    dict shape the HTTP layer serves (``_to_output`` == ``dataclasses.asdict``
    for a dataclass result — see module docstring)."""
    agent = TailoringAgent(
        resumes=_StubResumes(),
        jobs=_StubJobs(),
        service=_ScriptedService(),
        stories=_StubStories(),
        approvals=_StubApprovals(),
        ats_engine=_ScriptedATSEngine(scores, missing),
    )
    result = agent.run("user-1", "job-1", resume_id="base-1")
    return asdict(result)


# --- 1. iteration-level progress (§6.1(b)) -----------------------------------


def test_tailor_response_includes_iterations() -> None:
    """The response must expose per-iteration data (index + score achieved),
    so the UI can render tailoring PROGRESS, not just a final number.

    ``TailoringLoop`` already computes this (``TailoringLoopResult.iterations``,
    tailoring_loop.py:179-186) and ``TailoringAgent.run`` already reads it —
    but only to persist it to the DB (tailor_agent.py:463); it is never copied
    onto the returned ``TailorRunResult`` (tailor_agent.py:281-295 has no
    ``iterations`` field at all), so it never reaches the HTTP response.
    """
    # Reaches target on iteration 3 -> proves multi-iteration progress, not
    # just a single-shot summary.
    body = _run_agent(scores=[40.0, 62.0, 90.0], missing=[["kubernetes"], ["kafka"], []])

    assert "iterations" in body, (
        f"TailorRunResult has no 'iterations' field — response keys were: "
        f"{sorted(body.keys())}"
    )
    iterations = body["iterations"]
    assert isinstance(iterations, list) and len(iterations) == 3, iterations
    assert [it["iteration"] for it in iterations] == [1, 2, 3], iterations
    assert [it["score"] for it in iterations] == [40.0, 62.0, 90.0], iterations


# --- 2. before/after ATS delta traceability (§6.2, G-C/G-J/G-SUB badge) ------


def test_tailor_response_includes_ats_score_before_and_after() -> None:
    """Both the pre-tailoring baseline and the post-tailoring score must be
    present AND the post-tailoring score must be traceable to a real
    optimizer iteration (not merely a separately-shadow-computed number),
    so the delta badge (G-C/G-J/G-SUB) reflects what the loop actually did.

    ``conversionMetrics.baselineATSScore``/``.tailoredATSScore`` ALREADY exist
    in the response today (see module docstring) — asserted here as a
    documented pre-condition, not the failure. The genuine gap is that
    ``tailoredATSScore`` cannot be cross-checked against any iteration record,
    because ``iterations`` is entirely absent from the response.
    """
    body = _run_agent(scores=[40.0, 62.0, 90.0], missing=[["kubernetes"], ["kafka"], []])

    conv = body.get("conversionMetrics")
    assert conv is not None, body
    # Pre-condition already true today (documented, not the failure): both
    # numbers exist. Deliberately NOT asserting an exact value here —
    # ``conversionMetrics`` uses its own independently-computed real
    # ATSEngine score (see module docstring "IMPORTANT wrinkle"), not the
    # stubbed loop score, so any exact-value assertion here would be false.
    assert "baselineATSScore" in conv and "tailoredATSScore" in conv, conv
    assert isinstance(conv["tailoredATSScore"], (int, float)), conv

    # The genuine, currently-failing requirement: the after-score must be
    # traceable to a real optimizer iteration record so the UI can show which
    # pass produced it (and so a future regression in the loop<->dataclass
    # wiring is caught here, not just in test_tailor_response_includes_iterations).
    assert "iterations" in body, (
        "conversionMetrics.tailoredATSScore is present but untraceable to any "
        f"optimizer iteration — 'iterations' is missing from the response "
        f"entirely. Response keys were: {sorted(body.keys())}"
    )
    iterations = body["iterations"]
    assert isinstance(iterations, list) and len(iterations) == 3, iterations
    best = max(iterations, key=lambda it: it["score"])
    assert best["iteration"] == 3 and best["score"] == 90.0, best


# --- 3. missing-keyword chip list (§6.2 UI chips) ----------------------------


def test_tailor_response_includes_gap_keywords() -> None:
    """The response must expose the still-missing JD keywords (for the UI
    chip list) as a directly-readable field — currently absent: neither
    ``TailorRunResult`` nor its ``asdict()`` shape has a ``gapKeywords`` key
    (tailor_agent.py:281-295), even though every iteration already computed
    one (``clean_gap_keywords`` output, tailoring_loop.py:177,184).
    """
    # Never reaches target -> exhausts all 5 iterations -> exercises the
    # richest possible gapKeywords trail.
    body = _run_agent(
        scores=[40.0, 45.0, 48.0, 50.0, 52.0],
        missing=[["kubernetes", "kafka"], ["kafka"], ["kafka"], ["kafka"], ["kafka"]],
    )

    assert "gapKeywords" in body, (
        f"No top-level 'gapKeywords' field for the UI chip list — response "
        f"keys were: {sorted(body.keys())}"
    )
    assert body["gapKeywords"] == ["kafka"], body["gapKeywords"]


# --- 4. anti-dishonesty: sub-target result is reported truthfully -----------


def test_tailor_sub_target_score_is_reported_honestly() -> None:
    """When the loop cannot reach the 85.0 target within its iteration cap,
    the response must say so TRUTHFULLY with the ACHIEVED score — never
    clamp, round up to the target, or silently hide the shortfall — AND that
    claim must be VERIFIABLE, not just a trust-me string: a client must be
    able to check "best score achieved: 44.0" against a real, structured
    attempt-by-attempt trail, not merely trust free text.

    Split verdict (both halves evidenced, not assumed):
      - The WARNING TEXT itself is already honest today: ``TailoringLoop.run``
        (tailoring_loop.py:202-212) computes ``success = best_score >=
        target_score`` with no clamping anywhere in the file, and
        ``TailoringAgent.run`` forwards ``warning=loop_result.warning``
        verbatim (tailor_agent.py:524). Asserted below as a documented
        pre-condition, not the failure (a naive version of this test that
        stopped here would PASS today and be a defective, tautological test
        per the task brief's own rule).
      - The VERIFIABLE half genuinely fails: nothing in the response lets a
        caller cross-check the warning's "44.0" claim against real
        iteration-by-iteration evidence, because ``iterations`` — the exact
        same field ``test_tailor_response_includes_iterations`` targets — is
        entirely absent from ``TailorRunResult`` (tailor_agent.py:281-295).
        An honest-sounding string with no audit trail is a weaker honesty
        contract than §6.1(b) requires; this is the "make it strong" version
        the task brief asked for.
    """
    body = _run_agent(
        scores=[40.0, 41.0, 42.0, 43.0, 44.0],  # never reaches 85.0
        missing=[["kubernetes"]] * 5,
    )

    conv = body.get("conversionMetrics")
    assert conv is not None, body
    # requires_review is copied straight from the loop's own honest verdict
    # (tailor_agent.py:479: conversion_metrics["requires_review"] =
    # loop_result.requires_review) — unlike tailoredATSScore this is NOT
    # re-derived from a separate real-engine call, so asserting it here is
    # sound regardless of the "IMPORTANT wrinkle" noted in the module docstring.
    assert conv["requires_review"] is True, conv

    warning = body.get("warning")
    assert warning is not None, "sub-target run must carry an honest warning, got None"
    assert "44.0" in warning, warning  # the ACHIEVED score, verbatim
    assert "85" in warning, warning  # names the target it fell short of
    # Must never claim success it did not earn.
    assert "success" not in warning.lower()
    assert "target reached" not in warning.lower()

    # The genuine, currently-failing requirement: the "44.0" claim must be
    # independently VERIFIABLE against the real attempt trail, not just
    # asserted in prose.
    assert "iterations" in body, (
        "warning honestly says 'Best score achieved: 44.0/100' but nothing "
        "in the response lets a caller VERIFY that claim against the real "
        "iteration-by-iteration trail — 'iterations' is missing entirely. "
        f"Response keys were: {sorted(body.keys())}"
    )
    iterations = body["iterations"]
    assert len(iterations) == 5, iterations  # every attempt exhausted, none hidden
    assert max(it["score"] for it in iterations) == 44.0, iterations  # matches the warning's claim
