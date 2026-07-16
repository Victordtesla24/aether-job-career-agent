"""GAP-P6-TAIL-005 — deliver genuine tailoring lift within the synchronous budget.

Live production QA (uat/reports/evidence/phase6/qa-prod-craft4.json) confirmed the
tailoring is content-only + ZERO-fabrication (5x verified) and the entailment
verifier does real per-bullet judgment WHEN it has time (run 12: 11 kept / 3
rejected). But lift is never DELIVERED because the run rewrites ALL ~18 bullets in
one call:

* the tailor LLM call is too slow to complete a full-resume rewrite inside its
  budget (84% honest-failure rate this session), and
* even when it completes, an 18-candidate entailment batch cannot be verified
  inside a FIXED 15s window, so the fail-safe reverts EVERYTHING — including
  genuinely story-grounded JD-keyword rewrites ('payments'/'SQL'/'Confluence',
  run 2). This is a batch-size / latency wall, not a correctness bug.

Two fixes, both locked here:

**FIX 1 — cap the tailoring batch to the top-K most-impactful bullets.** Instead
of asking the model to rewrite ALL bullets, deterministically select the K bullets
whose own-context evidence can add the most JD keywords the resume currently lacks
(strict-lift levers), tie-broken by existing JD overlap and document order. Only
those K are sent to the model and are eligible to change; the rest pass through
unchanged (content-only). A smaller tailor call completes faster AND a smaller
entailment batch verifies within budget, so genuine lift SURVIVES.

**FIX 2 — scale the entailment budget with candidate count.** Replace the fixed
``AETHER_LLM_ENTAILMENT_BUDGET_SECONDS=15`` with ``base + per_candidate * N``
(capped, floored) so a small batch verifies comfortably while a large one still
cannot blow the ~100s HTTP edge.

Preserved: zero fabrication (entailment STILL reverts genuine fabrications),
content-only (only the top-K bullets' TEXT changes; order/indices intact), the
no-fixture-on-failure contract (AUTH-002), the anchor fix (TAIL-004), and the
dedicated-window default (the no-arg budget getter is unchanged).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents.tailor_agent import _compute_conversion_metrics
from app.services import llm_client, resume_tailor
from app.services.llm_client import LLMClient
from app.services.resume_tailor import ResumeTailorService


class _ScriptedLLM:
    """Answers the ``tailor`` and ``tailor_entailment`` prompts distinctly and
    records the tailor ``user`` prompt (to assert the batch cap)."""

    def __init__(
        self,
        tailor_raw: dict[str, Any],
        entailment_raw: dict[str, Any] | None = None,
    ) -> None:
        self.tailor_raw = tailor_raw
        self.entailment_raw = entailment_raw if entailment_raw is not None else {"results": []}
        self.captured_tailor_user = ""

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        if prompt_name == "tailor_entailment":
            return self.entailment_raw
        self.captured_tailor_user = user
        return self.tailor_raw


# ---------------------------------------------------------------------------
# Shared fixtures: a resume LARGER than the cap, with exactly one strict-lift
# lever (the "backend" bullet, whose Story-Bank evidence proves Kubernetes/Kafka
# — JD keywords absent from the resume text). The lever is placed MID-document
# (index 4) so selecting it proves the selector ranks by impact, not position.
# ---------------------------------------------------------------------------

_LIFT_BULLET = {
    "text": "Built backend services handling 2000000 requests per day, cutting latency by 40%.",
    "evidenceRef": "bullet-4",
}
_FILLERS = [
    {
        "text": f"Handled routine coordination number {i} for the wider group.",
        "evidenceRef": f"bullet-{i}",
    }
    for i in (0, 1, 2, 3, 5, 6, 7, 8)
]
# document order: fillers 0-3, lever at 4, fillers 5-8
_MANY_BULLETS = _FILLERS[:4] + [_LIFT_BULLET] + _FILLERS[4:]

_MANY_RESUME = (
    "JANE DOE\n"
    "Senior Backend Engineer\n"
    "\n"
    "SKILLS\n"
    "Python, PostgreSQL, REST\n"
    "\n"
    "EXPERIENCE\n"
    "Acme Corp\n"
    "2019 - 2024 | Sydney\n"
    + "".join(f"• {b['text']}\n" for b in _MANY_BULLETS)
)
_MANY_JD = (
    "Senior Backend Engineer. Requirements: Python, PostgreSQL, REST, "
    "Kubernetes, Kafka, backend services."
)
_STORY = (
    "Story: Platform reliability. Deployed Kubernetes clusters and Kafka "
    "streaming pipelines in production, backing the payment services."
)
_LIFT_REWRITE = {
    "bullets": [
        {
            "text": "Built backend services on Kubernetes with Kafka streaming, "
            "handling 2000000 requests per day, cutting latency by 40%.",
            "evidenceRef": "bullet-4",
        }
    ],
    "evidenceRefs": ["bullet-4"],
}


# ===========================================================================
# (f) AETHER_TAILOR_MAX_BULLETS knob
# ===========================================================================


def test_tailor_max_bullets_env_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("AETHER_TAILOR_MAX_BULLETS", raising=False)
    assert resume_tailor.get_tailor_max_bullets() == 8
    monkeypatch.setenv("AETHER_TAILOR_MAX_BULLETS", "not-a-number")
    assert resume_tailor.get_tailor_max_bullets() == 8
    monkeypatch.setenv("AETHER_TAILOR_MAX_BULLETS", "6")
    assert resume_tailor.get_tailor_max_bullets() == 6
    monkeypatch.setenv("AETHER_TAILOR_MAX_BULLETS", "0")  # <=0 disables the cap
    assert resume_tailor.get_tailor_max_bullets() == 0


# ===========================================================================
# (a) tailoring batch capped to top-K — selection + integration
# ===========================================================================


def test_select_bullets_to_tailor_caps_and_picks_lever() -> None:
    """The selector returns exactly K bullets and MUST include the strict-lift
    lever (the backend bullet whose story evidence adds Kubernetes/Kafka), even
    though it sits mid-document — impact beats position. Deterministic."""
    structured = [dict(b) for b in _MANY_BULLETS]
    chosen = resume_tailor.select_bullets_to_tailor(
        structured, _MANY_JD, _MANY_RESUME, _STORY, max_bullets=4
    )
    assert len(chosen) == 4
    refs = {b["evidenceRef"] for b in chosen}
    assert "bullet-4" in refs, ("lever not selected", refs)
    # returned in document order (indices ascending)
    order = [b["evidenceRef"] for b in chosen]
    assert order == sorted(order, key=lambda r: int(r.split("-")[1]))
    # deterministic
    again = resume_tailor.select_bullets_to_tailor(
        structured, _MANY_JD, _MANY_RESUME, _STORY, max_bullets=4
    )
    assert [b["evidenceRef"] for b in again] == order


def test_select_returns_all_when_under_cap() -> None:
    structured = [dict(b) for b in _MANY_BULLETS[:3]]
    chosen = resume_tailor.select_bullets_to_tailor(
        structured, _MANY_JD, _MANY_RESUME, _STORY, max_bullets=8
    )
    assert [b["evidenceRef"] for b in chosen] == [b["evidenceRef"] for b in structured]


def test_batch_cap_limits_prompt_and_changes(monkeypatch) -> None:
    """With K=3 and 8 bullets, the tailor PROMPT lists exactly 3 bullets and at
    most 3 bullets change — even when the model returns a rewrite for every
    bullet. Without the cap all 8 would be rewritten (too slow + un-verifiable)."""
    monkeypatch.setenv("AETHER_TAILOR_MAX_BULLETS", "3")
    originals = [
        {"text": f"Handled routine coordination number {i} for the wider group.",
         "evidenceRef": f"bullet-{i}"}
        for i in range(8)
    ]
    jd = "Team Lead. Requirements: leadership, delivery cadence."
    # model returns a benign, evidence-neutral rewrite for EVERY bullet
    rewrite = {
        "bullets": [
            {"text": o["text"] + " overall", "evidenceRef": o["evidenceRef"]}
            for o in originals
        ],
        "evidenceRefs": [o["evidenceRef"] for o in originals],
    }
    entail = {"results": [{"ref": o["evidenceRef"], "entailed": True} for o in originals]}
    llm = _ScriptedLLM(rewrite, entail)
    resume = "EXPERIENCE\n" + "".join(f"• {o['text']}\n" for o in originals)
    result = ResumeTailorService(llm=llm).tailor(resume, jd, originals=originals)
    # exactly K bullets appear in the prompt sent to the model
    listed = sum(1 for o in originals if f"{o['evidenceRef']}:" in llm.captured_tailor_user)
    assert listed == 3, (listed, llm.captured_tailor_user)
    assert result.changes <= 3, result.changes


# ===========================================================================
# (b) entailment budget scales with candidate count
# ===========================================================================


def test_entailment_budget_scales_with_candidate_count(monkeypatch) -> None:
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", "8")  # base
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_PER_CANDIDATE_SECONDS", "3")
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_MAX_SECONDS", "40")
    assert llm_client.get_entailment_budget_seconds(1) == pytest.approx(11.0)  # 8 + 3
    assert llm_client.get_entailment_budget_seconds(4) == pytest.approx(20.0)  # 8 + 12
    assert llm_client.get_entailment_budget_seconds(1) < llm_client.get_entailment_budget_seconds(8)
    assert llm_client.get_entailment_budget_seconds(100) == pytest.approx(40.0)  # capped
    # floor holds when base/per collapse to ~0
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", "0")
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_PER_CANDIDATE_SECONDS", "0")
    assert llm_client.get_entailment_budget_seconds(1) == llm_client._MIN_ATTEMPT_SECONDS


def test_entailment_budget_no_arg_default_preserved(monkeypatch) -> None:
    """TAIL-004 contract: the no-argument getter is unchanged (dedicated fixed
    window) so its existing tests and callers keep working."""
    monkeypatch.delenv("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", raising=False)
    assert llm_client.get_entailment_budget_seconds() == 20.0
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", "2")  # below floor
    assert llm_client.get_entailment_budget_seconds() == llm_client._MIN_ATTEMPT_SECONDS


def test_entailment_window_scales_with_batch_at_call_site(monkeypatch) -> None:
    """The verifier window opened around the real call scales with the number of
    CHANGED bullets: a 4-candidate batch gets a strictly larger window than a
    1-candidate batch."""
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", "8")
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_PER_CANDIDATE_SECONDS", "3")
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_MAX_SECONDS", "60")
    monkeypatch.setenv("AETHER_TAILOR_MAX_BULLETS", "0")  # no cap for this measurement
    clock = {"t": 5000.0}
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: clock["t"])

    class _MeasuringLLM(LLMClient):
        def __init__(self) -> None:
            super().__init__(mode="auto")
            self.window = 0.0

        def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
            if prompt_name == "tailor_entailment":
                self.window = self._remaining_budget()
                return {"results": []}
            return self._tailor_raw

    def _run(n: int) -> float:
        originals = [
            {"text": f"Coordinated stream {i} across the group.", "evidenceRef": f"bullet-{i}"}
            for i in range(n)
        ]
        llm = _MeasuringLLM()
        llm._tailor_raw = {
            "bullets": [
                {"text": o["text"] + " overall", "evidenceRef": o["evidenceRef"]}
                for o in originals
            ],
            "evidenceRefs": [o["evidenceRef"] for o in originals],
        }
        resume = "EXPERIENCE\n" + "".join(f"• {o['text']}\n" for o in originals)
        ResumeTailorService(llm=llm).tailor(resume, "Coordinator role.", originals=originals)
        return llm.window

    window_1 = _run(1)
    window_4 = _run(4)
    assert window_4 > window_1
    assert window_1 == pytest.approx(11.0)  # 8 + 3*1
    assert window_4 == pytest.approx(20.0)  # 8 + 3*4


# ===========================================================================
# (c) an evidence-backed keyword rewrite in a SMALL batch survives + lifts ATS
# ===========================================================================


def test_evidence_backed_keyword_in_small_batch_survives_and_lifts(monkeypatch) -> None:
    """The GOAL: with a large resume capped to a small batch, the story-grounded
    Kubernetes/Kafka rewrite on the selected lever bullet SURVIVES entailment and
    yields a STRICT tailoredATS > baselineATS — zero fabrication, metrics kept."""
    monkeypatch.setenv("AETHER_TAILOR_MAX_BULLETS", "4")
    entail = {"results": [{"ref": "bullet-4", "entailed": True, "reason": "story proves it"}]}
    llm = _ScriptedLLM(_LIFT_REWRITE, entail)
    structured = [dict(b) for b in _MANY_BULLETS]
    result = ResumeTailorService(llm=llm).tailor(
        _MANY_RESUME, _MANY_JD, originals=structured, evidence_extra=_STORY
    )
    # only the lever changed; batch cap respected
    assert 1 <= result.changes <= 4
    kept = next(b for b in result.bullets if b["evidenceRef"] == "bullet-4")
    assert "Kubernetes" in kept["text"] and "Kafka" in kept["text"], result.rejected
    assert "2000000" in kept["text"] and "40%" in kept["text"]  # metrics preserved
    # content-only: same bullet count / order / indices
    assert [b["evidenceRef"] for b in result.bullets] == [b["evidenceRef"] for b in structured]
    metrics = _compute_conversion_metrics(
        _MANY_RESUME, result.originals, result.bullets, _MANY_JD
    )
    assert metrics["tailoredATSScore"] > metrics["baselineATSScore"], metrics  # STRICT lift
    assert metrics["estimatedConversionLift"].startswith("+")
    assert metrics["estimatedConversionLift"] != "+0.0%", metrics


# ===========================================================================
# (d) fabrication STILL reverted inside a capped batch (no §9 regression)
# ===========================================================================

_FAB_RESUME = (
    "EXPERIENCE\n"
    "NAB\n"
    "2015 - 2018 | Melbourne\n"
    "• Led regulatory reporting for financial institutions across banking systems.\n"
    "InfoCentric\n"
    "2011 - 2014 | Sydney\n"
    "• Delivered analytics and Business Intelligence projects, boosting engagement by 20%.\n"
    + "".join(
        f"• Handled routine coordination number {i} for the wider group.\n"
        for i in range(6)
    )
)
_FAB_ORIGINALS = (
    [
        {"text": "Led regulatory reporting for financial institutions across banking systems.",
         "evidenceRef": "bullet-0"},
        {"text": "Delivered analytics and Business Intelligence projects, boosting engagement by 20%.",
         "evidenceRef": "bullet-1"},
    ]
    + [
        {"text": f"Handled routine coordination number {i} for the wider group.",
         "evidenceRef": f"bullet-{i + 2}"}
        for i in range(6)
    ]
)


def test_fabrication_still_reverted_in_capped_batch(monkeypatch) -> None:
    """Even under the batch cap, a rewrite whose words all appear in the corpus
    (on a DIFFERENT employer) but is NOT entailed for THIS bullet must revert.
    The InfoCentric bullet carries enough JD overlap to be selected, so it goes
    through entailment and is reverted (§9 zero-tolerance preserved)."""
    monkeypatch.setenv("AETHER_TAILOR_MAX_BULLETS", "3")
    jd = "Business Analyst. Requirements: analytics, business intelligence, financial institutions."
    rewrite = {
        "bullets": [
            {"text": "Delivered analytics and Business Intelligence projects for financial "
             "institutions, boosting engagement by 20%.",
             "evidenceRef": "bullet-1"}
        ],
        "evidenceRefs": ["bullet-1"],
    }
    entail = {"results": [{"ref": "bullet-1", "entailed": False,
                           "reason": "InfoCentric never tied to finance."}]}
    result = ResumeTailorService(llm=_ScriptedLLM(rewrite, entail)).tailor(
        _FAB_RESUME, jd, originals=_FAB_ORIGINALS
    )
    reverted = next(b for b in result.bullets if b["evidenceRef"] == "bullet-1")
    assert "for financial institutions" not in reverted["text"]
    assert reverted["text"] == _FAB_ORIGINALS[1]["text"]
    assert result.changes == 0
    assert any("financial institutions" in r for r in result.rejected)
