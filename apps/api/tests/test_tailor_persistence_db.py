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

import pytest

from app.agents.tailor_agent import NoChangesApplied, TailoringAgent
from app.db import get_connection
from app.repositories.job import JobRepository
from app.repositories.resume import ResumeRepository
from app.repositories.user import UserRepository
from app.routers.jobs import _resume_for_apply
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


class _NoOpTailorService:
    """LIVE-APPLY-LOCK: every proposed rewrite is unsupported by the
    candidate's evidence and rejected by the fabrication/entailment guards —
    the tailored bullets come back byte-identical to ``originals`` on every
    pass, so ``TailoringAgent.run`` computes ``net_changes == 0`` and raises
    ``NoChangesApplied`` (the real-world trigger: a résumé that is already a
    perfect match for the job)."""

    def tailor(
        self, resume_text: str, jd: str, originals: Any = None, evidence_extra: str = ""
    ) -> TailorResult:
        base = list(originals or [])
        return TailorResult(
            bullets=base, originals=base, changes=0, rejected=["unsupported rewrite"]
        )


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


def _make_base_resume(
    user_id: str, *, original_file: bytes | None = None
) -> dict[str, Any]:
    """The user's base résumé. ``original_file`` (LIVE-APPLY-LOCK) optionally
    seeds stored-upload bytes so a test can assert a no-op clone actually
    copies them, rather than leaving them empty — default ``None`` keeps the
    pre-existing persistence test's fixture byte-for-byte unchanged."""
    bullets = [
        {"text": "Built backend services handling 2000000 requests/day.", "evidenceRef": "bullet-0"},
    ]
    return ResumeRepository().create(
        user_id,
        {"raw_text": "JANE DOE\nSenior Backend Engineer\n- " + bullets[0]["text"], "bullets": bullets},
        "gmv4-format-hash",
        label="Base",
        version=1,
        original_file=original_file,
        original_filename="base.pdf" if original_file is not None else None,
        original_content_type="application/pdf" if original_file is not None else None,
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


def test_no_changes_applied_still_persists_a_resume_row_for_apply() -> None:
    """SESSION LIVE-APPLY-LOCK: an honest tailoring no-op must not leave the
    apply gate permanently shut.

    ``TailoringAgent.run`` raises ``NoChangesApplied`` when every proposed
    edit is rejected by the fabrication/entailment guards (``net_changes ==
    0``) — correctly, since no version was actually rewritten and the run is
    refunded. But that raise happens BEFORE ``self._resumes.create(...)`` is
    ever reached, so NO ``Resume`` row is created with ``sourceJobId ==
    job_id`` for this job. ``jobs._resume_for_apply`` (and the promotion-time
    repair in ``applications.submit_application``) select on exactly that
    column:

        SELECT "id" FROM "Resume" WHERE "userId" = %s AND "sourceJobId" = %s

    With no such row, a job whose résumé is *already a perfect match* — the
    honest, good-news case — can never satisfy ``apply_to_job``'s "a tailored
    resume is required before applying" gate. Required fix (NOT implemented
    here): the no-op run must still persist a Resume row cloned from the base
    (sections/originalFile/formatHash copied, label/version honest — never
    claiming a rewrite happened) with ``sourceJobId = job_id``, so
    ``_resume_for_apply`` resolves it — while ``NoChangesApplied`` keeps
    raising exactly as it does today (no fake "tailored" success).
    """
    user = _make_user()
    user_id = user["id"]
    job = _make_job(user_id)
    base = _make_base_resume(user_id, original_file=b"%PDF-1.4 fake base upload bytes")

    agent = TailoringAgent(
        resumes=ResumeRepository(),
        jobs=JobRepository(),
        service=_NoOpTailorService(),
        stories=_StubStories(),
        approvals=_StubApprovals(),
        # A single iteration clears the ATS target immediately (90 >= 85) and
        # every quality-gate dimension (90/90/100, all above the 80% floor),
        # so the loop stops after pass 1 — the no-op scenario needs no more.
        ats_engine=_ScriptedATSEngine([90.0]),
    )

    try:
        # The honest no-op signal must still fire — this is NOT relaxed by
        # the fix. A Resume row may now exist alongside it, but the caller
        # must still be told "no verifiable changes were applied".
        with pytest.raises(NoChangesApplied):
            agent.run(user_id, job["id"], resume_id=base["id"])

        no_op_resume = ResumeRepository().get_tailored_for_job(user_id, job["id"])
        assert no_op_resume is not None, (
            "NoChangesApplied left NO Resume row with sourceJobId=job_id — "
            "jobs._resume_for_apply has nothing to find, so a job whose "
            "résumé is already a perfect match can never be applied to."
        )
        assert no_op_resume["sourceJobId"] == job["id"], no_op_resume

        # sections/formatHash/originalFile must be COPIED from the base —
        # never fabricated or left empty.
        assert no_op_resume["sections"].get("raw_text") == base["sections"]["raw_text"], (
            no_op_resume["sections"]
        )
        assert no_op_resume["sections"].get("bullets") == base["sections"]["bullets"], (
            no_op_resume["sections"]
        )
        assert no_op_resume["formatHash"] == base["formatHash"], no_op_resume

        base_original = ResumeRepository().get_original_file(base["id"], user_id)
        no_op_original = ResumeRepository().get_original_file(no_op_resume["id"], user_id)
        assert no_op_original is not None and no_op_original["originalFile"] == (
            base_original["originalFile"]
        ), "the no-op clone's originalFile must be copied from the base, not left empty"

        # The label/version must stay honest — never claim a rewrite that did
        # not happen (MV-resume-studio-003's whole point).
        label = str(no_op_resume.get("label") or "")
        assert "tailored" not in label.lower(), (
            f"a no-op clone must never claim to be a rewrite; got label={label!r}"
        )

        resolved = _resume_for_apply(user_id, job["id"])
        assert resolved == no_op_resume["id"], (
            f"_resume_for_apply resolved {resolved!r}, not the no-op clone "
            f"{no_op_resume['id']!r} — a perfect-match job is still gated "
            "shut for applying."
        )
    finally:
        _cleanup(user_id, job["id"])


def test_repeated_no_change_runs_duplicate_resume_rows_without_bound() -> None:
    """REVIEWER attack #5 (SESSION LIVE-APPLY-LOCK): a persistent no-op clone
    with no idempotency guard, on a job whose status the no-op path never
    advances, duplicates without bound every time the job is re-attempted.

    ``board_sweep_cron`` runs every 10 minutes
    (``apps/api/app/workers/settings.py``: ``cron(board_sweep_cron,
    minute=set(range(0, 60, 10)))``) and its eligibility predicate
    (``_ELIGIBLE_JOB_PREDICATE``) selects ANY ``screening``/``matched`` job
    with a ``fitScore`` that has no ``Application`` row yet — with NO check
    for whether a ``Resume`` already exists for that job. The ONLY thing that
    ever removes such a job from "full" (tailor+cover) sweep eligibility is
    ``Job.status`` leaving ``screening``/``matched``, which happens exactly
    once in this codebase: the SUCCESS branch of ``TailoringAgent.run``
    (``tailor_agent.py``, ``self._jobs.advance_status(job_id, "tailoring",
    allowed_from={"discovered", "screening", "matched"})``) — called ONLY
    after a real rewrite, never on the ``net_changes == 0`` no-op branch.

    So a perfect-match job (résumé already optimal for it — precisely the
    scenario this fix targets) sits in ``screening``/``matched`` FOREVER: the
    sweep re-attempts it every tick, ``TailoringAgent.run`` deterministically
    re-computes ``net_changes == 0`` (same base, same job, same guard
    rejections) and re-raises ``NoChangesApplied`` — but ``
    _persist_no_change_resume`` has no "does a no-op clone already exist for
    this job" guard, so it INSERTs a fresh ``Resume`` row on every single
    retry. This test proves that with two direct calls (standing in for two
    sweep ticks) rather than waiting 20 real minutes.
    """
    user = _make_user()
    user_id = user["id"]
    job = _make_job(user_id)
    _make_base_resume(user_id, original_file=b"%PDF-1.4 fake base upload bytes")

    def _fresh_agent() -> TailoringAgent:
        # A fresh instance per call, exactly as ``routers.agents._dispatch``
        # constructs ``TailoringAgent()`` anew for every dispatched run
        # (sync HTTP call or board-sweep tick) — no in-memory state survives
        # between "ticks" in production either.
        return TailoringAgent(
            resumes=ResumeRepository(),
            jobs=JobRepository(),
            service=_NoOpTailorService(),
            stories=_StubStories(),
            approvals=_StubApprovals(),
            ats_engine=_ScriptedATSEngine([90.0]),
        )

    try:
        job_before = JobRepository().get_by_id(job["id"], user_id)
        assert job_before is not None

        # Tick 1 (e.g. the sweep's first pass, or the user's first manual
        # "Tailor" click): board_sweep's real dispatch never passes
        # ``resume_id`` (``_run_agent(user_id, "tailor", {"job_id": job_id})``
        # — no ``resume_id`` key), so this omits it too and lets
        # ``ensure_base_resume`` resolve the root every time, exactly as
        # production does.
        with pytest.raises(NoChangesApplied):
            _fresh_agent().run(user_id, job["id"])

        # Tick 2 (e.g. the NEXT board_sweep_cron tick, 10 minutes later): the
        # job's status was never advanced by the no-op branch, so it is
        # STILL eligible for a "full" (tailor+cover) sweep pass — nothing
        # in ``TailoringAgent`` or ``ResumeRepository`` distinguishes "this
        # job already has an honest no-op clone" from "this job has never
        # been attempted".
        with pytest.raises(NoChangesApplied):
            _fresh_agent().run(user_id, job["id"])

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "id" FROM "Resume" '
                    'WHERE "userId" = %s AND "sourceJobId" = %s',
                    (user_id, job["id"]),
                )
                clone_ids = [row[0] for row in cur.fetchall()]

        assert len(clone_ids) == 1, (
            f"two identical no-op tailoring attempts for the SAME job left "
            f"{len(clone_ids)} Resume row(s) with sourceJobId={job['id']!r} "
            f"({clone_ids!r}) — expected exactly 1 (idempotent). "
            "_persist_no_change_resume has no guard against re-creating a "
            "no-op clone that already exists for this job, and the no-op "
            "branch never advances Job.status the way the real-rewrite "
            "branch does (tailor_agent.py's "
            "'self._jobs.advance_status(job_id, \"tailoring\", ...)' runs "
            "only after net_changes > 0) — so board_sweep_cron (every 10 "
            "minutes, per apps/api/app/workers/settings.py) will keep "
            "re-selecting this perfect-match job as eligible and mint a NEW "
            "duplicate Resume row on every tick, unboundedly, until the user "
            "manually applies."
        )

        job_after = JobRepository().get_by_id(job["id"], user_id)
        assert job_after is not None
        assert job_after["status"] == job_before["status"], (
            f"expected the no-op branch to leave Job.status untouched "
            f"(proving it never removes the job from sweep eligibility the "
            f"way the real-rewrite branch's advance_status(...) call does); "
            f"got {job_before['status']!r} -> {job_after['status']!r}"
        )
    finally:
        _cleanup(user_id, job["id"])
