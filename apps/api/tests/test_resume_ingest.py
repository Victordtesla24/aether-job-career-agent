"""Phase-2 audit Section C — resume ingestion + explicit-resume tailoring.

Covers the ``POST /resumes`` ingestion route (registers an additional root
resume, e.g. the BA-positioned variant) and the ``resume_id`` selector on
``POST /agents/tailor/run``.
"""
from __future__ import annotations

BA_RAW_TEXT = (
    "VIKRAM DESHPANDE — Senior Business Analyst / Product Owner. "
    "Lead Business Analyst at Microsoft Inc. (Oct 2015 - Oct 2016, Sydney NSW): "
    "Executed a comprehensive gap analysis for Azure ML telemetry, delivering 10 key "
    "insights that enhanced system reliability by 15% and decreased incident MTTR by 10%. "
    "Senior Business Analyst at InfoCentric (Aug 2011 - Nov 2014, Melbourne VIC): "
    "Delivered analytics and Business Intelligence (BI) projects, boosting client customer "
    "engagement by 20% and automating regulatory reporting workflows to achieve 100% accuracy."
)


def _seed_job(client, auth_headers) -> dict:
    run = client.post(
        "/agents/scout/run",
        json={"query": "business analyst", "location": "Melbourne"},
        headers=auth_headers,
    )
    assert run.status_code == 202
    return client.get("/jobs", headers=auth_headers).json()[0]


def _ingest_ba_resume(client, auth_headers) -> dict:
    resp = client.post(
        "/resumes",
        json={
            "label": "BA resume — Senior Business Analyst / Product Owner",
            "raw_text": BA_RAW_TEXT,
            "contact": {"email": "sarkar.vikram@gmail.com"},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestResumeIngestion:
    def test_post_resumes_creates_root_resume(self, client, auth_headers):
        before = len(client.get("/resumes", headers=auth_headers).json())
        created = _ingest_ba_resume(client, auth_headers)
        assert created["parentId"] is None  # a new ROOT resume, not a child
        assert created["label"].startswith("BA resume")
        assert created["sections"]["raw_text"] == BA_RAW_TEXT
        assert created["formatHash"]  # derived when not supplied
        after = client.get("/resumes", headers=auth_headers).json()
        assert len(after) == before + 1
        assert any(r["id"] == created["id"] for r in after)

    def test_post_resumes_rejects_empty_payload(self, client, auth_headers):
        resp = client.post(
            "/resumes",
            json={"label": "", "raw_text": "too short"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_ingested_bundled_ba_resume_stores_complete_bullets(
        self, client, auth_headers
    ):
        """GAP-P4-044 at the endpoint boundary: ingesting the bundled BA resume
        via ``POST /resumes`` — exactly as ``scripts/ingest_ba_resume.py`` does,
        from the PDF's flat text — must store COMPLETE work bullets, not the
        truncated first-line fragments the legacy extractor produced."""
        import fitz

        from app.agents.fit_scorer import get_base_resume_path

        ba_pdf = get_base_resume_path().parent / "Vik_Resume_BA_Final.pdf"
        doc = fitz.open(ba_pdf)
        try:
            raw_text = "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()

        resp = client.post(
            "/resumes",
            json={"label": "BA resume — bundled", "raw_text": raw_text},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        bullets = [b["text"] for b in resp.json()["sections"]["bullets"]]

        # The multi-line "Agile Delivery Leadership" bullet is stored whole,
        # not truncated to its first line.
        agile = [b for b in bullets if b.startswith("Agile Delivery Leadership")]
        assert len(agile) == 1
        assert agile[0].rstrip().endswith("executive status reporting.")
        assert not any(b.rstrip().endswith("Agile Kookaburras squad") for b in bullets)
        # No work bullet was left as a dangling first-line fragment.
        fragments = [
            b
            for b in bullets
            if ":" in b[:60] and not b.rstrip().rstrip(")\"']").endswith((".", "!", "?"))
        ]
        assert not fragments, f"stored fragmented bullets: {fragments}"

    def test_tailor_run_accepts_explicit_resume_id(self, client, auth_headers):
        """The tailoring agent must tailor the SELECTED resume, not the base."""
        created = _ingest_ba_resume(client, auth_headers)
        job = _seed_job(client, auth_headers)
        resp = client.post(
            "/agents/tailor/run",
            json={"job_id": job["id"], "resume_id": created["id"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        child = client.get(f"/resumes/{body['resume_id']}", headers=auth_headers).json()
        assert child["parentId"] == created["id"]  # child of the BA resume
        assert child["formatHash"] == created["formatHash"]

    def test_tailor_run_unknown_resume_id_is_404(self, client, auth_headers):
        job = _seed_job(client, auth_headers)
        resp = client.post(
            "/agents/tailor/run",
            json={"job_id": job["id"], "resume_id": "cnotarealresumeid123456789"},
            headers=auth_headers,
        )
        assert resp.status_code == 404
