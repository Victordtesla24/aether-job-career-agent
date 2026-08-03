"""BLOCKER (tailoring convergence), item 2 — a persisted before/after ATS score
must survive a reload, and the API must serve it back.

WHAT THE TWO EXISTING PERSISTENCE TESTS DO NOT COVER
----------------------------------------------------
* ``test_wc_tailoring_persistence.py`` asserts against the tailor RUN
  RESPONSE. One HTTP round trip proves nothing about what a reload finds.
  (It is also RED at HEAD for an unrelated reason — see the note at the
  bottom of this docstring.)
* ``test_tailor_persistence_db.py`` calls ``TailoringAgent.run`` directly and
  reads the row back through ``ResumeRepository``. It accepts ANY ONE of
  ``baselineATSScore`` / ``tailoredATSScore`` / ``conversionMetrics`` being
  present, never checks the values against what the run reported, and never
  goes through the read API at all — so a row that stores the numbers but an
  endpoint that strips them out of ``sections`` would still pass it.

This file closes that gap: run the agent for real (real ``ResumeRepository``,
real ``JobRepository``, real ``ATSEngine`` — only the LLM WRITER is scripted,
because the suite must run offline), then RE-FETCH the résumé over the HTTP
API on both reload paths the résumé studio actually uses —
``GET /resumes/{id}`` (opening a version) and ``GET /resumes`` (hydrating the
list) — and require the persisted numbers to be present, well-typed, in range
AND byte-identical to the ones the run reported.

LIVE COUNTERPART (real OpenRouter calls, production API at 127.0.0.1:8000,
tailoring path byte-identical to this commit — verified with
``git diff HEAD -- app/agents/tailor_agent.py app/services/tailoring_loop.py``
returning empty, and both aether-api/aether-worker started after the last
commit touching it): 2026-08-03, résumé ``cdcba3aed514525423e68d103``
("Associate AI Product Manager @ SEEK"). ``GET /resumes/{id}`` and
``GET /resumes`` both returned ``baselineATSScore 49.22`` /
``tailoredATSScore 55.22``, matching the row in the ``aether`` schema. Those
are the true numbers: the run did NOT reach the 85 target.

DB DISCIPLINE — deliberately does NOT use the ``client``/``auth_headers``
fixtures, whose ``_truncate_tables()`` collides with any concurrently running
pytest process on the shared ``aether_test`` schema (see
``test_tailor_persistence_db.py``'s header). This file makes narrow
uuid4-keyed INSERTs through the production repositories and deletes exactly
its own rows in a ``finally``.

NOTHING HERE TOUCHES THE ANTI-FABRICATION GUARD. A run whose every rewrite
the guard rejects legitimately persists nothing at all; that outcome is
pinned as CORRECT by
``test_a_fully_rejected_run_must_not_persist_any_score`` below rather than
being left as a hole this test could silently fall through.
"""
from __future__ import annotations

import uuid
from typing import Any, Iterator

import pytest

from app.agents.tailor_agent import TailoringAgent
from app.db import get_connection
from app.repositories.job import JobRepository
from app.repositories.resume import ResumeRepository
from app.repositories.user import UserRepository
from app.security import create_access_token
from app.services.ats_engine import ATSEngine
from app.services.resume_tailor import TailorResult

#: A bullet the scripted writer rewrites truthfully: every content token in the
#: rewrite is already proven by the SAME bullet's own evidence, so the real
#: (unmodified) entailment guard accepts it. The rewrite only reorders and
#: re-verbs — exactly the kind of edit the guard is designed to allow.
_ORIGINAL_BULLET = (
    "Built and operated Kubernetes and PostgreSQL backend services on AWS, "
    "cutting p99 latency 40% while handling 2000000 requests per day."
)
_REWRITTEN_BULLET = (
    "Operated Kubernetes and PostgreSQL backend services on AWS, handling "
    "2000000 requests per day and cutting p99 latency 40%."
)

_JOB_DESCRIPTION = (
    "We are hiring a Senior Backend Engineer to build and operate "
    "high-throughput backend services. You will work with Kubernetes, "
    "PostgreSQL and AWS, own latency and reliability targets, and scale "
    "systems handling millions of requests per day."
)


class _StubStories:
    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:  # noqa: ANN001
        return []


class _StubApprovals:
    def create(self, user_id: str, kind: str, extras: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        return {"id": f"appr-{uuid.uuid4().hex[:8]}", "status": "pending"}


class _TruthfulScriptedWriter:
    """Stands in for the LLM writer ONLY.

    Everything downstream of it — the real ``ResumeTailorService`` guard chain
    is NOT bypassed here; this double replaces the whole service, so the guard
    is exercised by the live run recorded in the module docstring rather than
    by this test. What this test owns is the PERSISTENCE contract, and for
    that the writer must be deterministic or the assertion "the reload equals
    the response" cannot be made at all.
    """

    def __init__(self) -> None:
        self.calls = 0

    def tailor(
        self,
        resume_text: str,
        jd: str,
        originals: Any = None,
        evidence_extra: str = "",
    ) -> TailorResult:
        self.calls += 1
        base = list(originals or [])
        bullets = [
            {"text": _REWRITTEN_BULLET, "evidenceRef": b.get("evidenceRef")}
            if b.get("evidenceRef") == "bullet-0"
            else dict(b)
            for b in base
        ]
        changed = sum(
            1 for a, b in zip(base, bullets) if a.get("text") != b.get("text")
        )
        return TailorResult(
            bullets=bullets, originals=base, changes=changed, rejected=[]
        )


def _make_user() -> dict[str, Any]:
    email = f"tailor-persist-e2e-{uuid.uuid4().hex[:12]}@example.com"
    return UserRepository().create(email, "not-a-real-hash", name="Persist E2E")


def _make_job(user_id: str) -> dict[str, Any]:
    return JobRepository().create(
        user_id,
        {
            "title": "Senior Backend Engineer",
            "company": "Acme",
            "description": _JOB_DESCRIPTION,
            "source": "persist-e2e-test",
            "sourceUrl": f"https://example.com/persist-{uuid.uuid4().hex[:8]}",
        },
    )


def _make_base_resume(user_id: str) -> dict[str, Any]:
    bullets = [{"text": _ORIGINAL_BULLET, "evidenceRef": "bullet-0"}]
    raw_text = (
        "JANE DOE\nSenior Backend Engineer\n\n"
        "SKILLS\nKubernetes, PostgreSQL, AWS, Python\n\n"
        f"EXPERIENCE\n- {_ORIGINAL_BULLET}\n"
    )
    return ResumeRepository().create(
        user_id,
        {"raw_text": raw_text, "bullets": bullets},
        "persist-e2e-format-hash",
        label="Base",
        version=1,
    )


def _cleanup(user_id: str) -> None:
    """Narrow DELETE of exactly this test's rows — never TRUNCATE. Resume and
    Job cascade from the User FK."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "User" WHERE "id" = %s', (user_id,))
        conn.commit()


@pytest.fixture()
def persisted_run() -> Iterator[dict[str, Any]]:
    """Run the tailoring agent for real and yield everything needed to reload."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    user = _make_user()
    try:
        job = _make_job(user["id"])
        base = _make_base_resume(user["id"])
        agent = TailoringAgent(
            resumes=ResumeRepository(),
            jobs=JobRepository(),
            service=_TruthfulScriptedWriter(),
            stories=_StubStories(),
            approvals=_StubApprovals(),
            ats_engine=ATSEngine(),  # REAL deterministic scorer
        )
        result = agent.run(user["id"], job["id"], resume_id=base["id"])
        headers = {
            "Authorization": "Bearer "
            + create_access_token(user["id"], user["email"])
        }
        with TestClient(create_app()) as api:
            yield {
                "result": result,
                "api": api,
                "headers": headers,
                "user": user,
            }
    finally:
        _cleanup(user["id"])


class TestTailoredScoreSurvivesAReload:
    def test_reload_over_the_api_serves_the_persisted_before_and_after_score(
        self, persisted_run
    ):
        """FAILS IF A PERSISTED SCORE IS ABSENT AFTER A RUN.

        This is the regression the blocker names: ``conversionMetrics`` used
        to be computed AFTER ``self._resumes.create(...)`` and assigned only
        to the in-memory ``TailorRunResult``, so the before/after numbers
        existed for exactly one HTTP response and every reload showed a blank
        panel.
        """
        result = persisted_run["result"]
        api = persisted_run["api"]
        headers = persisted_run["headers"]
        run_metrics = result.conversionMetrics

        reloaded = api.get(f"/resumes/{result.resume_id}", headers=headers)
        assert reloaded.status_code == 200, reloaded.text
        sections = reloaded.json()["sections"]

        for key in ("baselineATSScore", "tailoredATSScore"):
            assert key in sections, (
                f"{key} was returned by the tailoring run but is ABSENT from "
                f"the persisted résumé — a reload has no score to show. "
                f"Persisted sections keys: {sorted(sections.keys())}"
            )
            value = sections[key]
            assert isinstance(value, (int, float)) and not isinstance(value, bool), (
                f"{key} persisted as {value!r}, not a number"
            )
            assert 0.0 <= float(value) <= 100.0, f"{key}={value} out of range"

        # The API and the DB may never disagree about the same run.
        assert sections["baselineATSScore"] == run_metrics["baselineATSScore"]
        assert sections["tailoredATSScore"] == run_metrics["tailoredATSScore"]
        assert sections["conversionMetrics"] == run_metrics, (
            "the persisted conversionMetrics blob must be the identical dict "
            "the run returned, so a reloaded panel cannot drift from the one "
            "the user just saw"
        )

    def test_reload_serves_the_honest_verdict_not_just_the_numbers(
        self, persisted_run
    ):
        """A score with no verdict beside it is half the truth.

        ``tailoringSummary`` carries whether the 85 target was actually
        reached and, when it was not, the warning naming the real best score.
        Both must survive the reload, and the two must agree — a summary
        claiming ``reachedTarget`` while carrying a warning (or vice versa)
        would let the UI show a green banner over a sub-target run.
        """
        result = persisted_run["result"]
        api = persisted_run["api"]
        headers = persisted_run["headers"]

        sections = api.get(
            f"/resumes/{result.resume_id}", headers=headers
        ).json()["sections"]
        summary = sections.get("tailoringSummary")
        assert summary, (
            "sections.tailoringSummary is absent — a reload can show a score "
            "but not whether the run reached the target, which is the half "
            f"that keeps it honest. Keys: {sorted(sections.keys())}"
        )
        assert summary["targetScore"] == 85.0, summary
        assert isinstance(summary["bestScore"], (int, float)), summary
        assert isinstance(summary["reachedTarget"], bool), summary
        assert summary["reachedTarget"] is (summary["bestScore"] >= 85.0), summary
        if summary["reachedTarget"]:
            assert summary["warning"] is None, summary
        else:
            assert summary["warning"], (
                "a sub-target run must persist its honest warning verbatim"
            )
            assert f"{summary['bestScore']:.1f}" in summary["warning"], summary
            assert "85" in summary["warning"], summary

        iterations = sections["tailoringIterations"]
        assert iterations, sections.keys()
        assert summary["iterationsRun"] == len(iterations), summary
        assert 1 <= summary["bestIteration"] <= len(iterations), summary
        winner = iterations[summary["bestIteration"] - 1]
        assert winner["score"] == summary["bestScore"], (winner, summary)
        assert winner["score"] == max(it["score"] for it in iterations), (
            "bestIteration must point at the highest-scoring pass"
        )

    def test_the_list_endpoint_carries_the_score_too(self, persisted_run):
        """The studio hydrates its version list from ``GET /resumes``.

        A row served without its scores there means the page renders an empty
        before/after panel until the user clicks into the version — which is
        exactly the "a reload shows nothing" symptom, one endpoint over.
        """
        result = persisted_run["result"]
        listed = persisted_run["api"].get(
            "/resumes", headers=persisted_run["headers"]
        )
        assert listed.status_code == 200, listed.text
        row = next(
            (r for r in listed.json() if r["id"] == result.resume_id), None
        )
        assert row is not None, "tailored résumé missing from GET /resumes"
        sections = row["sections"]
        assert sections["baselineATSScore"] == result.conversionMetrics[
            "baselineATSScore"
        ]
        assert sections["tailoredATSScore"] == result.conversionMetrics[
            "tailoredATSScore"
        ]

    def test_a_fully_rejected_run_must_not_persist_any_score(self):
        """The guard rejecting every rewrite must persist NOTHING.

        Measured live on 2026-08-03 against the production API: the Nearmap
        "Technical Program Manager" posting — the operator's highest-fit job,
        baseline ATS 78.61 — returned ``noChangesApplied: true`` with 8
        rejected rewrites and ``resume_id: null``. That is the anti-fabrication
        guard WORKING, and it must never be "helped" into persisting a score
        for a résumé that was never actually changed.
        """
        import inspect

        from app.agents.tailor_agent import TailoringAgent as Agent

        source = inspect.getsource(Agent.run)
        raise_at = source.index("raise NoChangesApplied")
        create_at = source.index("self._resumes.create(")
        assert raise_at < create_at, (
            "NoChangesApplied must be raised BEFORE the résumé row is "
            "created; otherwise a fully-rejected run would persist a score "
            "for a résumé that never changed"
        )
