"""GAP-P6-TAIL-001 / GAP-P6-CONV-001 — tailoring must produce a STRICT ATS
improvement from evidence-grounded keyword integration (no fabrication).

Writer-audit (uat/reports/evidence/phase6/writer-audit-G.json) finding: across
3/3 real job-resume pairs ``tailoredATSScore == baselineATSScore`` bit-for-bit
and ``estimatedConversionLift`` was invariantly ``+0.0%``. Root cause: the only
source of a *new* matched JD keyword is evidence that lives OUTSIDE the resume
text (the Story Bank / consolidated career data) — but (a) that evidence was
never wired into the tailoring agent's corpus, and (b) even the career evidence
that WAS gathered was passed only to the fabrication guard, never to the LLM
prompt, so the model could not surface it.

These tests lock the fix: story/career evidence reaches the LLM prompt, the
Story Bank is assembled into the tailoring evidence, and surfacing >=2 truthful
JD keywords the candidate's evidence proves (but the resume text lacks) raises
the ATS score STRICTLY, with zero fabrication and every metric preserved.
"""
from __future__ import annotations

from typing import Any

from app.agents.tailor_agent import (
    TailoringAgent,
    _compute_conversion_metrics,
    build_story_evidence,
)
from app.services.resume_tailor import ResumeTailorService, TailorResult

# --- shared synthetic fixture (no bundled-PDF / DB dependence) ----------------

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
    "• Built backend services handling 2000000 requests per day, cutting latency by 40%.\n"
    "• Led a team of 5 engineers delivering payment features.\n"
)
_ORIGINAL_BULLETS = [
    {
        "text": "Built backend services handling 2000000 requests per day, cutting latency by 40%.",
        "evidenceRef": "bullet-0",
    },
    {"text": "Led a team of 5 engineers delivering payment features.", "evidenceRef": "bullet-1"},
]
# Kubernetes + Kafka are genuine JD keywords the candidate PROVES via their
# Story Bank / career evidence, but which never appear in the resume TEXT.
_JD = (
    "Senior Backend Engineer. Requirements: Python, PostgreSQL, REST, "
    "Kubernetes, Kafka, backend services."
)
_STORY_EVIDENCE = (
    "Story: Platform reliability. Deployed Kubernetes clusters and Kafka "
    "streaming pipelines in production, backing the payment services."
)


class _CaptureLLM:
    """Stub LLM that records the ``user`` prompt and returns a fixed rewrite."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.captured_user = ""

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        self.captured_user = user
        return self.raw


# --- 1. DEFECT-2 root cause (b): evidence_extra must reach the LLM prompt ------


def test_evidence_extra_is_passed_to_the_llm_prompt() -> None:
    """The consolidated evidence corpus (career + Story Bank) must be visible to
    the tailoring model — otherwise it can never surface a truthful JD keyword
    the resume text lacks. Regression: ``tailor()`` passed ``evidence_extra`` to
    the guard only, never into ``user_prompt``."""
    llm = _CaptureLLM({"bullets": [], "evidenceRefs": []})
    ResumeTailorService(llm=llm).tailor(
        _RESUME, _JD, originals=_ORIGINAL_BULLETS, evidence_extra=_STORY_EVIDENCE
    )
    assert "Kubernetes" in llm.captured_user, llm.captured_user
    assert "Kafka" in llm.captured_user, llm.captured_user


# --- 2. DEFECT-2 core: strict ATS improvement from evidence-grounded keywords --


def test_story_backed_keywords_lift_ats_strictly_without_fabrication() -> None:
    """Surfacing >=2 JD keywords the candidate's Story Bank proves (absent from
    the resume text) into an existing bullet must raise the ATS score STRICTLY,
    reject nothing, and preserve every quantified metric."""
    rewrite = {
        "bullets": [
            {
                "text": "Built backend services on Kubernetes with Kafka streaming, "
                "handling 2000000 requests per day, cutting latency by 40%.",
                "evidenceRef": "bullet-0",
            }
        ],
        "evidenceRefs": ["bullet-0"],
    }
    llm = _CaptureLLM(rewrite)
    result = ResumeTailorService(llm=llm).tailor(
        _RESUME, _JD, originals=_ORIGINAL_BULLETS, evidence_extra=_STORY_EVIDENCE
    )
    assert not result.rejected, result.rejected
    assert result.changes == 1
    new_text = result.bullets[0]["text"].lower()
    assert "kubernetes" in new_text and "kafka" in new_text  # truthful JD keywords surfaced
    assert "kubernetes" not in _RESUME.lower() and "kafka" not in _RESUME.lower()  # absent from baseline text
    assert "2000000" in result.bullets[0]["text"] and "40%" in result.bullets[0]["text"]  # metrics preserved

    metrics = _compute_conversion_metrics(_RESUME, result.originals, result.bullets, _JD)
    assert metrics["tailoredATSScore"] > metrics["baselineATSScore"], metrics  # STRICT
    assert metrics["estimatedConversionLift"].startswith("+")
    assert metrics["estimatedConversionLift"] != "+0.0%", metrics  # decision-useful lift


def test_unsupported_keyword_stays_rejected_even_with_story_bank() -> None:
    """The widened corpus must not become a fabrication loophole: a JD keyword
    NOT proven by resume, story bank or career data is still rejected."""
    rewrite = {
        "bullets": [
            {
                "text": "Built backend services on Terraform, handling 2000000 requests "
                "per day, cutting latency by 40%.",
                "evidenceRef": "bullet-0",
            }
        ],
        "evidenceRefs": ["bullet-0"],
    }
    llm = _CaptureLLM(rewrite)
    # Story evidence proves Kubernetes/Kafka, NOT Terraform.
    jd = _JD + " Terraform."
    result = ResumeTailorService(llm=llm).tailor(
        _RESUME, jd, originals=_ORIGINAL_BULLETS, evidence_extra=_STORY_EVIDENCE
    )
    assert result.bullets[0]["text"] == _ORIGINAL_BULLETS[0]["text"]  # fabrication kept out
    assert result.changes == 0
    assert result.rejected


# --- 3. DEFECT-2 root cause (a): the Story Bank is assembled into the corpus ---


class _StubStories:
    def __init__(self, stories: list[dict[str, Any]]) -> None:
        self._stories = stories

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        return list(self._stories)


def test_build_story_evidence_flattens_story_bank() -> None:
    """``build_story_evidence`` turns the user's Story Bank into evidence text so
    story-proven skills can be surfaced and pass the guard."""
    stories = [
        {
            "title": "Kubernetes migration",
            "situation": "Legacy VMs were fragile.",
            "task": "Move to containers.",
            "action": "Deployed Kubernetes clusters and Kafka pipelines.",
            "result": "99.9% uptime.",
            "tags": ["platform", "reliability"],
            "metrics": {"uptime": "99.9%"},
        }
    ]
    evidence = build_story_evidence("user-1", repo=_StubStories(stories))
    assert "Kubernetes" in evidence and "Kafka" in evidence
    assert "99.9%" in evidence  # quantified result preserved as evidence
    # Empty story bank contributes nothing (backward compatible).
    assert build_story_evidence("user-1", repo=_StubStories([])) == ""


def test_tailoring_agent_wires_story_bank_into_evidence() -> None:
    """``TailoringAgent.run`` must fold the Story Bank into the evidence corpus
    handed to the tailoring service."""
    captured: dict[str, str] = {}

    class _StubService:
        def tailor(self, resume_text, jd, originals=None, evidence_extra=""):  # noqa: ANN001
            captured["evidence_extra"] = evidence_extra
            return TailorResult(bullets=list(originals or []), originals=list(originals or []))

    class _StubResumes:
        def get_by_id(self, resume_id, user_id):  # noqa: ANN001
            return {
                "id": "base-1",
                "formatHash": "hash",
                "sections": {"raw_text": _RESUME, "bullets": _ORIGINAL_BULLETS},
            }

        def create(self, *a, **k):  # noqa: ANN001, ANN002
            return {"id": "child-1"}

        def next_version(self, user_id):  # noqa: ANN001
            return 2

    class _StubJobs:
        def get_by_id(self, job_id, user_id):  # noqa: ANN001
            return {"title": "Backend Engineer", "company": "Acme", "description": _JD}

    story = {
        "title": "Kubernetes migration",
        "situation": "s",
        "task": "t",
        "action": "Deployed Kubernetes clusters and Kafka pipelines.",
        "result": "r",
        "tags": ["platform"],
        "metrics": {},
    }
    agent = TailoringAgent(
        resumes=_StubResumes(),
        jobs=_StubJobs(),
        service=_StubService(),
        stories=_StubStories([story]),
    )
    # The stub service reports 0 net changes, so the agent honestly no-ops
    # (MV-resume-studio-003) — but the Story Bank evidence is still folded into
    # the corpus handed to ``tailor`` (captured above) before that check, which is
    # exactly what this test pins.
    import pytest as _pytest

    from app.agents.tailor_agent import NoChangesApplied

    with _pytest.raises(NoChangesApplied):
        agent.run("user-1", "job-1", resume_id="base-1")
    assert "Kubernetes" in captured["evidence_extra"], captured
    assert "Kafka" in captured["evidence_extra"], captured
