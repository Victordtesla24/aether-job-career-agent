"""GOLD-MASTER-V4, §22 STEP 2 (SECOND ROUND) — adversarial-review FAIL on
GMV4-ats-001 (W-HF): ``ATSEngine`` correctly resolves genuine
``all-MiniLM-L6-v2`` embeddings through three paths (``local``, ``hf_api``,
``degraded``) and stamps ``ATSScore.semantic_path`` with which one actually
produced the number — see ``app/services/ats_engine.py`` and the existing,
still-green ``test_ats_engine_semantic.py`` (NOT modified here).

THE DEFECT (confirmed by re-reading each site): NO API consumer checks
``semantic_path`` before handing ``semantic_similarity`` to the caller/UI, so
the neutral ``_DEGRADED_SEMANTIC_SCORE = 50.0`` placeholder — injected only
when NEITHER a local model NOR the HF Inference API is available — leaks
outward and is presented exactly like a genuine measurement:

  * ``apps/api/app/routers/resumes.py:172-183`` (``ats_score`` handler) builds
    its response dict from ``score.semantic_similarity`` alone;
    ``score.semantic_path`` is never read, never included in the payload.
    ``apps/web/src/app/dashboard/resume/page.tsx:573`` then renders it
    unconditionally as "Semantic similarity (40%)".
  * ``apps/api/app/routers/jobs.py:298,317`` (``_build_insights``) reads
    ``sem = float(score.semantic_similarity)`` and blends it into
    ``dimensions[].Culture Fit`` (``0.5*sem + 0.5*exp``), the top-level
    ``"semantic"`` field, and the narrative string — again with no
    ``semantic_path`` check anywhere in the function.

These tests exercise the two router-level functions DIRECTLY (no HTTP, no DB
— ``ResumeRepository``/``JobRepository``/``ATSEngine``/
``resolve_user_resume_text`` are duck-typed stubs installed via
``monkeypatch``, matching the pattern already established in
``test_tailor_response_contract.py``). This is deliberately the smallest
honest reproduction: the defect is in what the handler DOES with a genuine
``ATSScore`` it already has in hand, not in DB plumbing, so no
``client``/``db_session`` fixture is needed or used.
"""
from __future__ import annotations

from app.services.ats_engine import ATSScore, _DEGRADED_SEMANTIC_SCORE

_DEGRADATION_FLAG_KEYS = (
    "semanticPath",
    "semantic_path",
    "semanticDegraded",
    "scoringDegraded",
)


def _make_score(*, semantic_path: str, semantic_similarity: float = 72.0, overall: float = 78.0) -> ATSScore:
    return ATSScore(
        overall=overall,
        keyword_match=80.0,
        semantic_similarity=semantic_similarity,
        experience_gap=90.0,
        matched_keywords=["python"],
        missing_keywords=["kubernetes"],
        requires_review=False,
        semantic_path=semantic_path,
    )


class _FixedATSEngine:
    """Duck-typed ``ATSEngine`` stub returning a pre-programmed ``ATSScore`` —
    lets each test pin ``semantic_path`` independent of any real model/network."""

    def __init__(self, score: ATSScore) -> None:
        self._score = score

    def score(self, resume_text, job_description):  # noqa: ARG002 — duck-typed signature
        return self._score


class _FakeResumeRepo:
    def __init__(self, resume: dict) -> None:
        self._resume = resume

    def get_by_id(self, resume_id, user_id):  # noqa: ARG002
        return self._resume


class _FakeJobRepo:
    def __init__(self, job: dict) -> None:
        self._job = job

    def get_by_id(self, job_id, user_id):  # noqa: ARG002
        return self._job


_RESUME_RECORD = {
    "id": "resume-1",
    "sourceJobId": "job-1",
    "sections": {"raw_text": "Experienced backend engineer with Python and Docker."},
}
_JOB_RECORD = {
    "id": "job-1",
    "title": "Backend Engineer",
    "company": "Acme",
    "description": "Looking for a backend engineer skilled in Kubernetes.",
    "source": "manual",
}


def _call_resume_ats(monkeypatch, score: ATSScore) -> dict:
    """Call ``resumes.ats_score`` directly (no HTTP/DB) with every internal
    dependency it locally-imports monkeypatched to a hermetic stub."""
    import app.repositories.job as job_repo_module
    import app.services.ats_engine as ats_engine_module
    from app.routers import resumes

    monkeypatch.setattr(resumes, "ResumeRepository", lambda: _FakeResumeRepo(_RESUME_RECORD))
    monkeypatch.setattr(job_repo_module, "JobRepository", lambda: _FakeJobRepo(_JOB_RECORD))
    monkeypatch.setattr(ats_engine_module, "ATSEngine", lambda: _FixedATSEngine(score))

    return resumes.ats_score("resume-1", {"id": "user-1"}, job_id=None)


def _call_job_insights(monkeypatch, score: ATSScore, resume_text: str = "Experienced backend engineer with Python and Docker.") -> dict:
    """Call ``jobs._build_insights`` directly (no HTTP/DB)."""
    import app.services.ats_engine as ats_engine_module
    import app.services.resume_grounding as resume_grounding_module
    from app.routers import jobs

    monkeypatch.setattr(ats_engine_module, "ATSEngine", lambda: _FixedATSEngine(score))
    monkeypatch.setattr(
        resume_grounding_module,
        "resolve_user_resume_text",
        lambda user_id, allow_operator_fallback=False: resume_text,  # noqa: ARG005
    )

    return jobs._build_insights(_JOB_RECORD, "user-1")


def _degradation_flagged(payload: dict) -> bool:
    for key in _DEGRADATION_FLAG_KEYS:
        value = payload.get(key)
        if value == "degraded" or value is True:
            return True
    return False


# ---------------------------------------------------------------------------


def test_resume_ats_response_includes_semantic_path(monkeypatch):
    score = _make_score(semantic_path="local")
    resp = _call_resume_ats(monkeypatch, score)
    assert "semantic_path" in resp, (
        "GET /resumes/{id}/ats omits semantic_path entirely — the caller has "
        f"no way to know which scoring path produced the number. payload keys: {sorted(resp)}"
    )
    assert resp["semantic_path"] == "local"


def test_resume_ats_response_flags_degraded_scoring(monkeypatch):
    score = _make_score(semantic_path="degraded", semantic_similarity=_DEGRADED_SEMANTIC_SCORE)
    resp = _call_resume_ats(monkeypatch, score)
    assert resp.get("semantic_path") == "degraded", (
        "GET /resumes/{id}/ats does not carry an unambiguous degraded-scoring "
        f"signal a client can branch on (not just the bare number); payload: {resp}"
    )


def test_job_insights_does_not_blend_degraded_semantic_into_culture_fit(monkeypatch):
    score = _make_score(semantic_path="degraded", semantic_similarity=_DEGRADED_SEMANTIC_SCORE)
    result = _call_job_insights(monkeypatch, score)

    culture_fit_dims = [d for d in result.get("dimensions", []) if d.get("label") == "Culture Fit"]
    assert not culture_fit_dims or _degradation_flagged(result), (
        "GET /jobs/{id}/insights blends the degraded semantic placeholder into "
        f"a real-looking 'Culture Fit' dimension ({culture_fit_dims}) with no "
        f"degradation signal anywhere in the payload: {result}"
    )


def test_degraded_score_is_never_returned_as_an_unqualified_number(monkeypatch):
    """Anti-regression test for the whole class: no API surface may return the
    50.0 degraded placeholder without an accompanying degradation signal."""
    score = _make_score(semantic_path="degraded", semantic_similarity=_DEGRADED_SEMANTIC_SCORE)

    resume_resp = _call_resume_ats(monkeypatch, score)
    assert resume_resp["semantic_similarity"] == round(_DEGRADED_SEMANTIC_SCORE, 1)
    assert resume_resp.get("semantic_path") == "degraded", (
        f"resumes ATS endpoint returned the {_DEGRADED_SEMANTIC_SCORE} degraded "
        f"placeholder as an unqualified number: {resume_resp}"
    )

    insights_resp = _call_job_insights(monkeypatch, score)
    assert insights_resp["semantic"] == round(_DEGRADED_SEMANTIC_SCORE)
    assert _degradation_flagged(insights_resp), (
        f"jobs insights endpoint returned the {_DEGRADED_SEMANTIC_SCORE} degraded "
        f"placeholder as an unqualified number: {insights_resp}"
    )
