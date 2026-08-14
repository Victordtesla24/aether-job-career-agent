"""U-AX round-3 — the degraded-provenance + granularity defect CLASS (R-01..R-04).

One class, not four patches. The invariant these tests pin:

    No degraded / placeholder-contaminated ATS or fit-dimension value may EVER
    render as a measurement or persist as policy evidence.

Three enforcement points, all covered here:

* **R-04 (source)** — ``routers/jobs.py::_build_insights``'s ATS-engine
  exception fallback copies ``Job.fitScore`` into ``keyword_match`` /
  ``experience`` / ``semantic`` / ``overall``. A copied fit score is NOT a
  measured keyword match and NOT a measured experience fit, so every
  résumé-derived dimension it feeds must carry ``degraded: True``. The
  résumé-INDEPENDENT three (Salary Fit / Location Match / Company Stability)
  are computed from the ``Job`` row alone and stay honestly measured.
* **R-04 (consequence)** — ``services/submission_snapshot.py`` persists that
  radar onto ``Application.dimensionScoresAtSubmission`` and
  ``services/quality_policy.py`` consumes it as the deterministic rigor
  policy's ``DIMENSION_FLOOR`` evidence. A fabricated number must therefore
  never reach either: it must be excluded from the snapshot (and named in
  ``_meta.degradedExcluded``) so the policy can neither escalate nor decline
  to escalate on a number no engine measured.
* **R-01 + R-03 (surface)** — ``GET /resumes/{id}/tailoring-impact`` is the
  ONE granularity + provenance authority for a before/after pair. Both halves
  are produced by the same blend (``routers/jobs.py::build_fit_dimensions``)
  and the same rounding authority (``routers/jobs.py::_round``: integer,
  clamped [0,100]), which structurally removes both the mixed-granularity
  delta (integer ``before`` vs 1-dp ``after``) and the duplicated client-side
  blend that produced it. A non-measured half reports ``ats: null`` +
  ``atsMeasured: false`` — never a bold number.

Run under ``flock /tmp/aether-pytest.lock`` (shared ``aether_test`` schema).
"""
from __future__ import annotations

import json

import pytest

from app.db import get_connection, new_id

RESUME_TEXT = (
    "Jordan Blake — Delivery Lead. 9 years leading agile delivery programs, "
    "stakeholder management, risk governance, Jira, Confluence, SQL reporting, "
    "cloud migration and vendor management for enterprise platforms."
)

JOB_DESCRIPTION = (
    "We are hiring a Senior Delivery Lead to run enterprise agile delivery "
    "programs. You will own stakeholder management, risk governance and vendor "
    "management, reporting on delivery health with SQL and Jira."
)


def _seed_job(user_id: str, *, fit_score: float = 82.0) -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","atsScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Senior Delivery Lead", "ExampleCorp",
                    "Melbourne VIC", False, JOB_DESCRIPTION,
                    json.dumps(["agile delivery", "stakeholder management"]),
                    "greenhouse", f"https://example.com/{job_id}", fit_score, 61.0,
                ),
            )
        conn.commit()
    return job_id


def _seed_resume(user_id: str, *, source_job_id: str | None = None, version: int = 1) -> str:
    resume_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    resume_id, user_id, version,
                    json.dumps({"raw_text": RESUME_TEXT}), "hash-r3", source_job_id,
                ),
            )
        conn.commit()
    return resume_id


def _seed_application(user_id: str, job_id: str, resume_id: str) -> str:
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Application"
                   ("id","userId","jobId","resumeId","status","coverLetter",
                    "createdAt","updatedAt")
                   VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
                (app_id, user_id, job_id, resume_id, "Dear Hiring Manager,\n\nJordan"),
            )
        conn.commit()
    return app_id


@pytest.fixture()
def broken_ats(monkeypatch):
    """Force the ATS engine to raise, exercising ``_build_insights``'s except
    branch — the R-04 fallback that copies ``Job.fitScore`` into every subscore."""
    from app.services import ats_engine

    def _boom(self, *args, **kwargs):  # noqa: ANN001, ARG001
        raise RuntimeError("embedding backend unavailable")

    monkeypatch.setattr(ats_engine.ATSEngine, "score", _boom, raising=True)


#: The three dimensions computed from the ``Job`` row alone — tailoring the
#: résumé's WORDS cannot move them, and an ATS-engine failure cannot
#: contaminate them either.
JOB_ONLY_DIMENSIONS = {"Salary Fit", "Location Match", "Company Stability"}

#: Everything else on the radar is (wholly or partly) résumé-derived.
RESUME_DERIVED_DIMENSIONS = {
    "Technical Skills", "Experience Level", "Industry Match", "Role Alignment",
    "Culture Fit", "Career Growth", "North Star Align",
}


class TestExceptionFallbackMarksEveryAffectedDimensionDegraded:
    """R-04 (source). jobs.py's ``except`` branch sets
    ``km = sem = exp = overall = float(job['fitScore'])`` — a copied fit score.
    Every dimension built from it must say so."""

    def test_resume_derived_dimensions_are_all_degraded(
        self, client, auth_headers, test_user_id, broken_ats
    ):
        _seed_resume(test_user_id)
        job_id = _seed_job(test_user_id)

        resp = client.get(f"/jobs/{job_id}/insights", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        by_label = {d["label"]: d for d in body["dimensions"]}

        for label in sorted(RESUME_DERIVED_DIMENSIONS):
            assert by_label[label]["degraded"] is True, (
                f"{label} was built from a copied Job.fitScore on the ATS-exception "
                "fallback and must NOT be presented as a measurement"
            )

    def test_job_only_dimensions_stay_honestly_measured(
        self, client, auth_headers, test_user_id, broken_ats
    ):
        """Failing closed on EVERYTHING would be its own dishonesty — salary,
        location and source stability are real facts about the Job row."""
        _seed_resume(test_user_id)
        job_id = _seed_job(test_user_id)

        body = client.get(f"/jobs/{job_id}/insights", headers=auth_headers).json()
        by_label = {d["label"]: d for d in body["dimensions"]}
        for label in sorted(JOB_ONLY_DIMENSIONS):
            assert by_label[label]["degraded"] is False, label

    def test_payload_declares_the_ats_itself_unmeasured(
        self, client, auth_headers, test_user_id, broken_ats
    ):
        """The headline ATS number on that payload is a copied fit score too."""
        _seed_resume(test_user_id)
        job_id = _seed_job(test_user_id)

        body = client.get(f"/jobs/{job_id}/insights", headers=auth_headers).json()
        assert body["atsMeasured"] is False
        assert body["semanticDegraded"] is True

    def test_healthy_engine_still_reports_measured(
        self, client, auth_headers, test_user_id
    ):
        """0-regression guard: with a working engine the flag is honest the
        other way (the semantic half may still degrade in a sandbox without the
        embedding model — ``atsMeasured`` tracks the ENGINE, not the model)."""
        _seed_resume(test_user_id)
        job_id = _seed_job(test_user_id)

        body = client.get(f"/jobs/{job_id}/insights", headers=auth_headers).json()
        assert body["atsMeasured"] is True


class TestFabricatedDimensionsNeverBecomePolicyEvidence:
    """R-04 (consequence). The snapshot is the deterministic rigor policy's
    ``DIMENSION_FLOOR`` evidence — a copied fit score must never reach it."""

    def test_snapshot_excludes_every_degraded_dimension(
        self, client, auth_headers, test_user_id, broken_ats
    ):
        from app.services.submission_snapshot import measure_dimension_snapshot

        _seed_resume(test_user_id)
        job_id = _seed_job(test_user_id)

        snapshot = measure_dimension_snapshot(test_user_id, job_id)
        assert snapshot is not None, "job-only dimensions are still measurable"
        assert "technicalSkills" not in snapshot
        assert "experienceLevel" not in snapshot
        assert "roleAlignment" not in snapshot
        excluded = set(snapshot["_meta"]["degradedExcluded"])
        assert RESUME_DERIVED_DIMENSIONS <= excluded

    def test_rigor_policy_cannot_trigger_on_a_fabricated_dimension(
        self, client, auth_headers, test_user_id, broken_ats
    ):
        """``Job.fitScore`` here is 82 — comfortably ABOVE the 80 floor. If the
        fabricated copy leaked through as a measurement it would silently
        SATISFY the floor for Technical Skills / Experience Level, i.e. stop the
        policy escalating on evidence that was never measured."""
        from app.services.quality_policy import compute_rigor_policy
        from app.services.submission_snapshot import measure_dimension_snapshot

        _seed_resume(test_user_id)
        job_id = _seed_job(test_user_id, fit_score=82.0)

        snapshot = measure_dimension_snapshot(test_user_id, job_id) or {}
        policy = compute_rigor_policy(
            {"sampleSize": 40, "conversionRate": 0.05, "dimensionScores": snapshot}
        )
        assert not any("technicalSkills" in t for t in policy["triggers"])
        assert not any("experienceLevel" in t for t in policy["triggers"])
        # ...and the count of dimensions the floor check could honestly consider
        # excludes them, so the panel can say how much of the check was possible.
        assert policy["dimensionsEvaluated"] == len(JOB_ONLY_DIMENSIONS)

    def test_persisted_submission_snapshot_carries_no_fabricated_dimension(
        self, client, auth_headers, test_user_id, broken_ats
    ):
        from app.services.submission_snapshot import record_submission_snapshot

        resume_id = _seed_resume(test_user_id)
        job_id = _seed_job(test_user_id)
        app_id = _seed_application(test_user_id, job_id, resume_id)

        record_submission_snapshot(test_user_id, app_id, job_id, resume_id)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "dimensionScoresAtSubmission" FROM "Application" WHERE "id" = %s',
                    (app_id,),
                )
                stored = cur.fetchone()[0]
        assert stored is not None
        assert "technicalSkills" not in stored
        assert "experienceLevel" not in stored


class TestOneGranularityAuthorityForTheBeforeAfterPair:
    """R-01 + R-03. ``GET /resumes/{id}/tailoring-impact`` is the single
    authority: both halves blended and rounded by the SAME server-side code."""

    def test_requires_authentication(self, client):
        assert client.get("/resumes/does-not-exist/tailoring-impact").status_code == 401

    def test_before_half_is_byte_identical_to_the_jobs_insights_panel(
        self, client, auth_headers, test_user_id
    ):
        """Parity against the server blend: the "before" half MUST equal what
        the Job Discovery fit radar shows for the same (user, job) — not a
        re-implementation, not a differently-rounded twin."""
        _seed_resume(test_user_id)
        job_id = _seed_job(test_user_id)
        tailored_id = _seed_resume(test_user_id, source_job_id=job_id, version=2)

        insights = client.get(f"/jobs/{job_id}/insights", headers=auth_headers).json()
        impact = client.get(
            f"/resumes/{tailored_id}/tailoring-impact", headers=auth_headers
        )
        assert impact.status_code == 200, impact.text
        before = impact.json()["before"]

        assert before["dimensions"] == insights["dimensions"]
        if insights["atsMeasured"] and not insights["semanticDegraded"]:
            assert before["ats"] == insights["overall"]

    def test_both_halves_use_the_same_integer_clamped_granularity(
        self, client, auth_headers, test_user_id
    ):
        _seed_resume(test_user_id)
        job_id = _seed_job(test_user_id)
        tailored_id = _seed_resume(test_user_id, source_job_id=job_id, version=2)

        body = client.get(
            f"/resumes/{tailored_id}/tailoring-impact", headers=auth_headers
        ).json()
        for half in ("before", "after"):
            ats = body[half]["ats"]
            assert ats is None or (isinstance(ats, int) and 0 <= ats <= 100), (half, ats)
            for dim in body[half]["dimensions"]:
                assert isinstance(dim["score"], int), (half, dim)
                assert 0 <= dim["score"] <= 100, (half, dim)
                assert isinstance(dim["degraded"], bool), (half, dim)

        before_labels = [d["label"] for d in body["before"]["dimensions"]]
        after_labels = [d["label"] for d in body["after"]["dimensions"]]
        assert before_labels == after_labels

    def test_a_degraded_half_reports_null_ats_never_a_number(
        self, client, auth_headers, test_user_id, broken_ats
    ):
        """R-01: a placeholder-contaminated ATS must not be rendered as a bold
        number, so the wire itself withholds it."""
        _seed_resume(test_user_id)
        job_id = _seed_job(test_user_id)
        tailored_id = _seed_resume(test_user_id, source_job_id=job_id, version=2)

        body = client.get(
            f"/resumes/{tailored_id}/tailoring-impact", headers=auth_headers
        ).json()
        assert body["before"]["ats"] is None
        assert body["before"]["atsMeasured"] is False
        assert body["after"]["ats"] is None
        assert body["after"]["atsMeasured"] is False

    def test_unknown_resume_is_404_not_a_fabricated_pair(self, client, auth_headers):
        resp = client.get("/resumes/nope-not-real/tailoring-impact", headers=auth_headers)
        assert resp.status_code == 404

    def test_resume_with_no_source_job_is_422_not_a_guessed_job(
        self, client, auth_headers, test_user_id
    ):
        """A before/after pair is only meaningful against a specific posting —
        picking one would fabricate the comparison."""
        _seed_resume(test_user_id)
        orphan = _seed_resume(test_user_id, source_job_id=None, version=3)
        resp = client.get(f"/resumes/{orphan}/tailoring-impact", headers=auth_headers)
        assert resp.status_code == 422
