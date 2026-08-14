"""U-STORY-1 step 1 — Story Bank evidence is JD-scoped and character-budgeted.

Discovery (``uat/reports/evidence/market-perf/u-story/U-STORY-DISCOVERY.md``
§2.3 gap 1, AGENT-GRAPH.json edge ``svc.build_story_evidence ->
agent.resumeTailoring``): ``build_story_evidence`` has carried a
``job_description`` parameter and ``story_relevance.filter_stories_by_relevance``
has existed since §7.3.5, yet **all three production call sites omit the
argument** — ``tailor_agent.py:546``, ``cover_letter_agent.py:1557`` and
``routers/cover_letters.py:752``. Every story the user owns is therefore folded
into every job's prompt, unranked and (unlike the corpus path next to it,
``services/evidence_corpus.py:98-133``) with no character budget at all. On a
40-story bank that is the largest unpriced token load in the tailoring prompt.

This module pins the two halves of the fix:

* **Selection** — a story that proves NOTHING the posting asks for is ranked
  out; the on-point story survives, strongest first.
* **Budget** — the rendered evidence never exceeds the configured character
  budget, and what survives the cut is the strongest evidence, not an
  arbitrary prefix.

plus the three call sites actually passing the job description.

Nothing here relaxes a guard: relevance selection can only ever NARROW the set
of the candidate's OWN true stories, and the fabrication/entailment guards
downstream are untouched.

Run under the shared test-DB lock::

    nice flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_ustory1_s1_story_evidence_jd_scoped.py -p no:randomly -q
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents.tailor_agent import build_story_evidence

# ---------------------------------------------------------------------------
# Shared fixtures — a full-length posting and two stories at opposite ends of
# the relevance range (measured scores recorded in
# uat/reports/evidence/market-perf/u-story/s1/relevance-range.json).
# ---------------------------------------------------------------------------

_JD = (
    "Senior Platform Engineer at Northwind Logistics. We are seeking an "
    "experienced platform engineer to own our Kubernetes estate and CI/CD "
    "tooling. You will design, build and operate resilient distributed "
    "services in Python, drive observability with Prometheus and Grafana, and "
    "partner with product teams to reduce deployment lead time. "
    "Responsibilities: operate multi-region Kubernetes clusters; build "
    "Terraform modules for repeatable infrastructure; own incident response "
    "and the on-call rotation; improve pipeline reliability and reduce build "
    "times. Requirements: deep Kubernetes and container expertise; strong "
    "Python; infrastructure as code with Terraform; experience with AWS."
)

_RELEVANT_STORY: dict[str, Any] = {
    "title": "Kubernetes migration cut deploy time",
    "situation": "Legacy VMs were fragile and deploys took hours.",
    "task": "Move the platform to containers and automate the pipeline.",
    "action": (
        "Designed and operated multi-region Kubernetes clusters, wrote "
        "Terraform modules and rebuilt the CI/CD pipeline in Python with "
        "Prometheus observability."
    ),
    "result": "Deployment lead time fell 82 percent and uptime reached 99.9%.",
    "tags": ["kubernetes", "terraform"],
    "metrics": {"uptime": "99.9%"},
}

_IRRELEVANT_STORY: dict[str, Any] = {
    "title": "Ran the office charity bake sale",
    "situation": "The social committee needed a fundraiser.",
    "task": "Organise a bake sale.",
    "action": "Recruited volunteers, booked the atrium and printed posters.",
    "result": "Raised 4,200 dollars for the local shelter.",
    "tags": ["community"],
    "metrics": {"raised": "4200"},
}


class _StubStories:
    def __init__(self, stories: list[dict[str, Any]]) -> None:
        self._stories = stories

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        return list(self._stories)


# ---------------------------------------------------------------------------
# (a) Selection — the irrelevant story is ranked out, the on-point one survives
# ---------------------------------------------------------------------------


def test_irrelevant_stories_are_ranked_out_when_the_job_is_known() -> None:
    """A story that proves none of the posting's vocabulary must not reach the
    prompt; the on-point story must."""
    evidence = build_story_evidence(
        "user-1",
        repo=_StubStories([_IRRELEVANT_STORY, _RELEVANT_STORY]),
        job_description=_JD,
    )
    assert "Kubernetes" in evidence, evidence
    assert "bake sale" not in evidence.lower(), evidence
    assert "shelter" not in evidence.lower(), evidence


def test_without_a_job_description_every_story_is_still_included() -> None:
    """Backward compatibility: a caller with no job in hand gets the prior
    unconditional corpus (narrowing must never happen by accident)."""
    evidence = build_story_evidence(
        "user-1", repo=_StubStories([_IRRELEVANT_STORY, _RELEVANT_STORY])
    )
    assert "Kubernetes" in evidence
    assert "bake sale" in evidence.lower()


def test_strongest_evidence_is_ranked_first() -> None:
    """Ranking is by relevance to THIS posting, strongest first — the same
    discipline ``rank_corpus_items`` applies to corpus evidence."""
    weaker = dict(_RELEVANT_STORY)
    weaker.update(
        {
            "title": "Wrote a Python reporting script",
            "situation": "Reports were manual.",
            "task": "Automate them.",
            "action": "Wrote a Python script that emailed a weekly summary.",
            "result": "Saved two hours a week.",
            "tags": ["python"],
            "metrics": {},
        }
    )
    evidence = build_story_evidence(
        "user-1",
        repo=_StubStories([weaker, _RELEVANT_STORY]),
        job_description=_JD,
    )
    assert evidence.index("Kubernetes migration") < evidence.index(
        "Wrote a Python reporting script"
    ), evidence


# ---------------------------------------------------------------------------
# (b) Budget — the same character-budget discipline the corpus path has
# ---------------------------------------------------------------------------


def test_story_evidence_holds_the_character_budget(monkeypatch: Any) -> None:
    """The rendered evidence is bounded, and the bound keeps the STRONGEST
    story rather than an arbitrary prefix of the bank."""
    monkeypatch.setenv("AETHER_STORY_EVIDENCE_MAX_CHARS", "700")
    filler = [
        {
            "title": f"Kubernetes cluster upgrade {n}",
            "situation": "s" * 120,
            "task": "Kubernetes Terraform Python pipeline work " + "t" * 80,
            "action": "Operated Kubernetes clusters with Terraform. " + "a" * 80,
            "result": "Reliability improved. " + "r" * 80,
            "tags": ["kubernetes"],
            "metrics": {},
        }
        for n in range(12)
    ]
    evidence = build_story_evidence(
        "user-1",
        repo=_StubStories([*filler, _RELEVANT_STORY]),
        job_description=_JD,
    )
    assert 0 < len(evidence) <= 700, len(evidence)
    # The strongest-ranked story is the one that survives the cut.
    assert "Kubernetes migration cut deploy time" in evidence, evidence


def test_budget_applies_even_without_a_job_description(monkeypatch: Any) -> None:
    """The unpriced-token-load fix is unconditional — a JD-free caller is
    bounded too."""
    monkeypatch.setenv("AETHER_STORY_EVIDENCE_MAX_CHARS", "500")
    filler = [
        {
            "title": f"Story {n}",
            "situation": "s" * 40,
            "task": "t" * 40,
            "action": "a" * 40,
            "result": "r" * 40,
            "tags": [],
            "metrics": {},
        }
        for n in range(10)
    ]
    evidence = build_story_evidence("user-1", repo=_StubStories(filler))
    assert 0 < len(evidence) <= 500, len(evidence)
    # An unbudgeted producer would have emitted all ten (~1,700 chars).
    assert evidence.count("\n\n") < 9, evidence.count("\n\n")


# ---------------------------------------------------------------------------
# (c) The three production call sites actually pass the job description
# ---------------------------------------------------------------------------


def test_tailoring_agent_passes_the_job_description(monkeypatch: Any) -> None:
    """``tailor_agent.py:546`` — the tailoring agent's story evidence must be
    scoped to the job it is tailoring for."""
    from app.agents import tailor_agent as tailor_agent_module
    from app.agents.tailor_agent import NoChangesApplied, TailoringAgent
    from app.services.resume_tailor import TailorResult

    captured: dict[str, Any] = {}

    def _spy(user_id: str, repo: Any = None, job_description: str | None = None) -> str:
        captured["job_description"] = job_description
        return ""

    monkeypatch.setattr(tailor_agent_module, "build_story_evidence", _spy)

    resume_text = "Built payment services in Python at Northwind. Led 6 engineers."
    originals = [{"evidenceRef": "b1", "text": "Built payment services in Python."}]

    class _StubService:
        def tailor(self, resume_text, jd, originals=None, evidence_extra=""):  # noqa: ANN001
            return TailorResult(bullets=list(originals or []), originals=list(originals or []))

    class _StubResumes:
        def get_by_id(self, resume_id, user_id):  # noqa: ANN001
            return {
                "id": "base-1",
                "formatHash": "hash",
                "sections": {"raw_text": resume_text, "bullets": originals},
            }

        def create(self, *a, **k):  # noqa: ANN001, ANN002
            return {"id": "child-1"}

        def next_version(self, user_id):  # noqa: ANN001
            return 2

    class _StubJobs:
        def get_by_id(self, job_id, user_id):  # noqa: ANN001
            return {
                "title": "Senior Platform Engineer",
                "company": "Northwind Logistics",
                "description": _JD,
            }

    agent = TailoringAgent(
        resumes=_StubResumes(),
        jobs=_StubJobs(),
        service=_StubService(),
        stories=_StubStories([]),
    )
    with pytest.raises(NoChangesApplied):
        agent.run("user-1", "job-1", resume_id="base-1")

    assert captured.get("job_description"), captured
    assert "Kubernetes" in captured["job_description"], captured


def test_cover_letter_agent_passes_the_job_description(monkeypatch: Any) -> None:
    """``cover_letter_agent.py:1557`` — the letter's story evidence must be
    scoped to the posting it is written for."""
    from app.agents.cover_letter_agent import CoverLetterAgent
    from app.services.llm_client import LLMClient

    captured: dict[str, Any] = {}

    class _Stop(RuntimeError):
        pass

    def _spy(user_id: str, repo: Any = None, job_description: str | None = None) -> str:
        captured["job_description"] = job_description
        return ""

    monkeypatch.setattr("app.agents.cover_letter_agent.build_story_evidence", _spy)
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.build_career_corpus", lambda uid: ""
    )
    monkeypatch.setattr(
        "app.agents.cover_letter_agent.require_user_resume_text",
        lambda user_id, message: "Senior engineer with Python and Kubernetes experience.",
    )

    class _ProbeLLM(LLMClient):
        def __init__(self) -> None:
            super().__init__(mode="auto")

        def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
            raise _Stop()

    class _FakeJobs:
        def get_by_id(self, job_id, user_id):  # noqa: ANN001
            return {
                "id": job_id,
                "title": "Senior Platform Engineer",
                "company": "Northwind Logistics",
                "description": _JD,
            }

    class _FakeUsers:
        def get_by_id(self, user_id):  # noqa: ANN001
            return {"name": "Jordan Rivera"}

        def get_target_role(self, user_id):  # noqa: ANN001
            return None

    agent = CoverLetterAgent(
        llm=_ProbeLLM(), jobs=_FakeJobs(), users=_FakeUsers(), stories=_StubStories([])
    )
    with pytest.raises(_Stop):
        agent.run("user-1", "job-1")

    assert captured.get("job_description"), captured
    assert "Kubernetes" in captured["job_description"], captured


def test_cover_letter_refine_passes_the_job_description(monkeypatch: Any) -> None:
    """``routers/cover_letters.py:752`` — the REVISE path re-derives the same
    claim evidence and must scope it to the same posting."""
    from app.routers import cover_letters as cover_letters_module

    captured: dict[str, Any] = {}

    class _Stop(RuntimeError):
        pass

    def _spy(user_id: str, repo: Any = None, job_description: str | None = None) -> str:
        captured["job_description"] = job_description
        return ""

    monkeypatch.setattr(cover_letters_module, "build_story_evidence", _spy)
    monkeypatch.setattr(cover_letters_module, "build_career_corpus", lambda uid: "")
    monkeypatch.setattr(
        cover_letters_module,
        "_load_letter",
        lambda letter_id, user_id: {
            "id": letter_id,
            "jobId": "job-1",
            "coverLetter": "Dear Hiring Manager,\n\nI led 6 engineers.\n\nJordan Rivera",
        },
    )
    monkeypatch.setattr(
        cover_letters_module,
        "resolve_user_resume_text",
        lambda user_id, allow_operator_fallback=False: (
            "Senior engineer with Python and Kubernetes experience."
        ),
    )

    class _FakeJobRepo:
        def get_by_id(self, job_id, user_id):  # noqa: ANN001
            return {
                "id": job_id,
                "title": "Senior Platform Engineer",
                "company": "Northwind Logistics",
                "description": _JD,
            }

    class _FakeUserRepo:
        def get_target_role(self, user_id):  # noqa: ANN001
            return None

    class _StopLLM:
        def complete_json(self, *a, **k):  # noqa: ANN001, ANN002
            raise _Stop()

    monkeypatch.setattr(cover_letters_module, "JobRepository", _FakeJobRepo)
    monkeypatch.setattr(cover_letters_module, "UserRepository", _FakeUserRepo)
    monkeypatch.setattr(cover_letters_module, "LLMClient", _StopLLM)

    body = cover_letters_module.RefineRequest(instructions="Tighten the opening.")
    with pytest.raises(_Stop):
        cover_letters_module._refine_cover_letter_body(
            "letter-1", body, {"id": "user-1", "name": "Jordan Rivera"}
        )

    assert captured.get("job_description"), captured
    assert "Kubernetes" in captured["job_description"], captured
