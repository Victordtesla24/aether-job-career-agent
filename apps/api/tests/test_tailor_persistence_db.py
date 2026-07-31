"""GMV4-tailor-001 §6.1(c) — persistence half of the tailoring response
contract defect (§22 STEP 2, GOLD-MASTER-V4).

ISOLATED IN ITS OWN FILE, per the task brief's explicit instruction
("test_tailor_persists_ats_score_and_iteration_to_db ... If this needs DB
fixtures, isolate it in its own file/class and flag it"). The other 4
DEFECT-2 tests (``test_tailor_response_contract.py``) are fully DB-free; this
one genuinely cannot be, because §6.1(c) is a persistence claim and the only
way to honestly verify what Postgres actually stored is to write a real row
and read it back.

DB-DEPENDENT — DELIBERATELY NOT the ``client``/``db_session`` pytest fixtures.
``conftest.py``'s ``client`` fixture calls ``_truncate_tables()``
(``TRUNCATE "User", "Job", "Resume", ... CASCADE``) before every test — the
task brief explicitly warned that this collides with the separately-running
full-suite pytest process holding ``/tmp/aether-pytest.lock`` (shared
``aether_test`` schema; concurrent TRUNCATE causes phantom failures in BOTH
processes). This file instead makes narrow, real writes directly through the
production repositories (``UserRepository``, ``JobRepository``,
``ResumeRepository`` — the same code path the app itself uses, so this is
still a genuine integration check, not a mock), with:
  - every row keyed by a fresh ``uuid4``-suffixed id/email (never collides
    with another concurrent process's rows),
  - only INSERT/SELECT/DELETE (never TRUNCATE),
  - a ``finally`` block that deletes exactly the rows this test created.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.agents.tailor_agent import TailoringAgent
from app.db import get_connection
from app.repositories.job import JobRepository
from app.repositories.resume import ResumeRepository
from app.repositories.user import UserRepository
from app.services.ats_engine import ATSScore
from app.services.resume_tailor import TailorResult


class _StubStories:
    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:  # noqa: ANN001
        return []


class _StubApprovals:
    def create(self, user_id: str, kind: str, extras: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        return {"id": "appr-1", "status": "pending"}


class _ScriptedService:
    """No LLM call — deterministic rewrite that always nets >=1 real change,
    so the run never short-circuits via ``NoChangesApplied``."""

    def __init__(self) -> None:
        self.calls = 0

    def tailor(
        self, resume_text: str, jd: str, originals: Any = None, evidence_extra: str = ""
    ) -> TailorResult:
        self.calls += 1
        base = list(originals or [])
        rewritten = [
            {
                "text": f"{b['text']} (pass {self.calls})",
                "evidenceRef": b.get("evidenceRef", f"bullet-{i}"),
            }
            for i, b in enumerate(base)
        ]
        return TailorResult(bullets=rewritten, originals=base, changes=len(rewritten), rejected=[])


class _ScriptedATSEngine:
    """Deterministic sub-target score on every call — proves the persistence
    claim under the SAME "never reaches 85" scenario the anti-dishonesty test
    uses, so a reader can see both halves (response + persistence) of §6.1(b)/
    (c) against one consistent scenario."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
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
            missing_keywords=["kubernetes"],
            requires_review=True,
        )


def _make_user() -> dict[str, Any]:
    email = f"gmv4-tailor-persist-{uuid.uuid4().hex[:12]}@example.com"
    return UserRepository().create(email, "not-a-real-hash", name="GMV4 Persist Test")


def _make_job(user_id: str) -> dict[str, Any]:
    return JobRepository().create(
        user_id,
        {
            "title": "Senior Backend Engineer",
            "company": "Acme",
            "description": "Backend role requiring Python, PostgreSQL, Kubernetes.",
            "source": "gmv4-test",
            "sourceUrl": f"https://example.com/gmv4-{uuid.uuid4().hex[:8]}",
        },
    )


def _make_base_resume(user_id: str) -> dict[str, Any]:
    bullets = [
        {"text": "Built backend services handling 2000000 requests/day.", "evidenceRef": "bullet-0"},
    ]
    return ResumeRepository().create(
        user_id,
        {"raw_text": "JANE DOE\nSenior Backend Engineer\n- " + bullets[0]["text"], "bullets": bullets},
        "gmv4-format-hash",
        label="Base",
        version=1,
    )


def _cleanup(user_id: str, job_id: str) -> None:
    """Narrow DELETE of exactly this test's own rows — never TRUNCATE. Resume
    rows cascade-delete via the User FK's ``onDelete: Cascade``, so deleting
    the User is sufficient for both Resume and Job."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "User" WHERE "id" = %s', (user_id,))
        conn.commit()


def test_tailor_persists_ats_score_and_iteration_to_db() -> None:
    """§6.1(c): the tailoring RUN's ats_score data must be persisted, not just
    returned transiently in the HTTP response.

    Split verdict, both evidenced below:
      - Per-iteration data IS already persisted:
        ``TailoringAgent.run`` writes ``loop_result.iterations`` into
        ``sections["tailoringIterations"]`` (tailor_agent.py:463) via the REAL
        ``ResumeRepository.create`` — asserted below as a documented
        pre-condition (a test that stopped here would trivially pass).
      - The ats_score SUMMARY (baseline/tailored) is NOT persisted anywhere:
        ``conversion_metrics = _compute_conversion_metrics(...)`` runs AFTER
        ``self._resumes.create(...)`` has already returned (tailor_agent.py:
        453-475 — ``create()`` is called first, ``_compute_conversion_metrics``
        second) and its result is only ever assigned to the in-memory
        ``TailorRunResult.conversionMetrics`` (tailor_agent.py:521), never
        written back to the Resume row. A page load that reads the persisted
        record (rather than the just-returned HTTP response) has no ats_score
        to show — this is the genuine, currently-failing gap.
    """
    user = _make_user()
    user_id = user["id"]
    job = _make_job(user_id)
    base = _make_base_resume(user_id)

    agent = TailoringAgent(
        resumes=ResumeRepository(),
        jobs=JobRepository(),
        service=_ScriptedService(),
        stories=_StubStories(),
        approvals=_StubApprovals(),
        ats_engine=_ScriptedATSEngine([40.0, 41.0, 42.0, 43.0, 44.0]),
    )

    try:
        result = agent.run(user_id, job["id"], resume_id=base["id"])

        persisted = ResumeRepository().get_by_id(result.resume_id, user_id)
        assert persisted is not None, "tailored resume version was not persisted at all"
        sections = persisted["sections"]

        # Pre-condition already true today (documented, not the failure).
        assert "tailoringIterations" in sections, sections
        assert len(sections["tailoringIterations"]) == 5, sections["tailoringIterations"]

        # The genuine, currently-failing requirement: the ats_score summary
        # must survive a reload — it does not exist anywhere in `sections`.
        has_persisted_score = (
            "baselineATSScore" in sections
            or "tailoredATSScore" in sections
            or "conversionMetrics" in sections
        )
        assert has_persisted_score, (
            "ats_score (baseline/tailored) was returned in the HTTP response "
            "but never persisted to the Resume row — a reload has no score to "
            f"show. Persisted sections keys were: {sorted(sections.keys())}"
        )
    finally:
        _cleanup(user_id, job["id"])
