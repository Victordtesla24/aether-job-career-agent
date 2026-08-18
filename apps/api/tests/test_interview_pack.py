"""Orchestrator interview pack: Aether-branded prep PDFs + employer-facing artefacts.

The Supervisor records a plan and delegates to the existing agents. Prep and
slides use the gilt/obsidian design system. Résumé and cover letter stay the
employer's document — never re-skinned in Aether chrome. Missing tailor/cover
artefacts are gaps, never invented.
"""
from __future__ import annotations

import json
import uuid
import zipfile
from io import BytesIO

from app.services.interview_pack_pdf import GOLD, INK_0, render_prep_pdf, render_slides_pdf


def _briefing() -> dict:
    return {
        "logistics": [
            "Face-to-face interview · 10:00am, Wednesday 19 August 2026 (Melbourne)",
            "Location: Docklands office",
        ],
        "traps": [
            {
                "title": "Unanswered question in the email trail",
                "detail": "When did you finish with the ATO?",
            }
        ],
        "companyNotes": ["Notes come from your own postings for Next Business Energy."],
        "interviewerNotes": ["Adan Micallef · adan@nextbusinessenergy.com.au"],
        "questionsToAsk": [
            "Where has the tender actually got to — still going to market, or a shortlist?"
        ],
        "guidelines": [
            "This is face to face at Docklands office. Plan the route and arrive ten minutes early."
        ],
        "closing": ["Ask where the process goes next."],
        "documentMarkdown": (
            "# Interview prep — Project Manager at Next Business Energy\n\n"
            "Docklands office. When did you finish with the ATO?\n"
        ),
    }


def test_prep_pdf_is_gilt_branded_and_carries_trail_facts():
    import fitz

    pdf = render_prep_pdf(
        title="Project Manager",
        company="Next Business Energy",
        briefing=_briefing(),
        questions=[],
    )
    assert pdf.startswith(b"%PDF")
    text = fitz.open(stream=pdf, filetype="pdf")[0].get_text()
    assert "AETHER" in text
    assert "DOCKLANDS" in text.upper() or "Docklands" in text
    assert "ATO" in text
    assert "FF6B35" not in pdf.hex().upper()
    assert GOLD.lower() == "#c9a84c"
    assert INK_0.lower() == "#08080a"


def test_slides_pdf_is_four_landscape_pages():
    import fitz

    pdf = render_slides_pdf(
        title="Project Manager",
        company="Next Business Energy",
        briefing=_briefing(),
        questions=[],
    )
    doc = fitz.open(stream=pdf, filetype="pdf")
    assert doc.page_count == 4
    text = "\n".join(page.get_text() for page in doc)
    assert "AETHER" in text
    assert "LOGISTICS" in text.upper()
    rect = doc[0].rect
    assert rect.width > rect.height


def test_assemble_pack_zips_branded_docs_and_records_honest_gaps(
    db_session, test_user_id
):
    from app.services.interview_pack import assemble_interview_pack, load_pack_zip

    job_id, resume_id, app_id = (
        uuid.uuid4().hex,
        uuid.uuid4().hex,
        uuid.uuid4().hex,
    )
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (
                job_id,
                test_user_id,
                "Project Manager — Retail Systems Transformation",
                "Next Business Energy",
                "Billing platform tender.",
                "email",
                f"https://example.com/job/{job_id}",
                80.0,
            ),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections",'
            '"formatHash","updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (
                resume_id,
                test_user_id,
                json.dumps({"raw_text": "Vikram. TruEnergy billing."}),
                "hash-pack",
            ),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",NOW(),NOW())',
            (app_id, test_user_id, job_id, resume_id, "interview"),
        )
    db_session.commit()

    result = assemble_interview_pack(
        test_user_id,
        job_id,
        run_missing=False,
        prep_output={
            "jobId": job_id,
            "jobTitle": "Project Manager — Retail Systems Transformation",
            "company": "Next Business Energy",
            "briefing": _briefing(),
            "predictedQuestions": [],
        },
    )
    names = [f.name for f in result.files]
    assert "01-interview-prep.pdf" in names
    assert "02-interview-slides.pdf" in names
    assert "05-briefing.md" in names
    assert not any(n.startswith("03-resume") for n in names)
    assert "04-cover-letter.pdf" not in names
    assert any("résumé" in g.lower() or "resume" in g.lower() for g in result.gaps)
    assert any("cover letter" in g.lower() for g in result.gaps)
    branded = {f.name: f.branded for f in result.files}
    assert branded["01-interview-prep.pdf"] is True
    assert branded["02-interview-slides.pdf"] is True

    blob = load_pack_zip(test_user_id, job_id)
    assert blob
    with zipfile.ZipFile(BytesIO(blob)) as zf:
        inner = zf.namelist()
        assert any(n.endswith("01-interview-prep.pdf") for n in inner)
        prep_name = next(n for n in inner if n.endswith("01-interview-prep.pdf"))
        prep_bytes = zf.read(prep_name)
    import fitz

    extracted = fitz.open(stream=prep_bytes, filetype="pdf")[0].get_text()
    assert "AETHER" in extracted
    assert "Aether CareerAI Agent" in extracted


def test_pack_routes_assemble_and_download(client, auth_headers, db_session, test_user_id):
    job_id, resume_id, app_id = (
        uuid.uuid4().hex,
        uuid.uuid4().hex,
        uuid.uuid4().hex,
    )
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (
                job_id,
                test_user_id,
                "Project Manager",
                "Next Business Energy",
                "Billing platform.",
                "email",
                f"https://example.com/job/{job_id}",
                80.0,
            ),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections",'
            '"formatHash","updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (
                resume_id,
                test_user_id,
                json.dumps({"raw_text": "seed"}),
                "hash-pack-api",
            ),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",NOW(),NOW())',
            (app_id, test_user_id, job_id, resume_id, "interview"),
        )
        cur.execute(
            'INSERT INTO "AgentRun" ("id","userId","agentName","status","output",'
            '"startedAt","completedAt","createdAt") VALUES '
            "(%s,%s,'interviewPrep','completed'::\"AgentRunStatus\",%s::jsonb,"
            "NOW(),NOW(),NOW())",
            (
                uuid.uuid4().hex,
                test_user_id,
                json.dumps(
                    {
                        "jobId": job_id,
                        "jobTitle": "Project Manager",
                        "company": "Next Business Energy",
                        "predictedQuestions": [],
                        "briefing": _briefing(),
                    }
                ),
            ),
        )
    db_session.commit()

    assembled = client.post(
        f"/workspaces/interviews/pack?job_id={job_id}",
        headers=auth_headers,
    )
    assert assembled.status_code == 200, assembled.text
    body = assembled.json()
    assert any(f["name"] == "01-interview-prep.pdf" for f in body["files"])

    prep = client.get("/workspaces/interviews/prep", headers=auth_headers)
    assert prep.status_code == 200
    payload = prep.json()
    assert payload["session"]["company"] == "Next Business Energy"
    assert payload["session"]["format"] in ("Face to face", "not measured", "Phone", "Video")
    assert payload["pack"] is not None
    assert payload["pack"]["files"]
    assert payload.get("briefing") is None or "traps" in (payload.get("briefing") or {})

    zip_resp = client.get(
        f"/workspaces/interviews/pack/download?job_id={job_id}",
        headers=auth_headers,
    )
    assert zip_resp.status_code == 200
    assert zip_resp.headers["content-type"].startswith("application/zip")
    assert zip_resp.content[:2] == b"PK"

    file_resp = client.get(
        f"/workspaces/interviews/pack/file?job_id={job_id}&name=01-interview-prep.pdf",
        headers=auth_headers,
    )
    assert file_resp.status_code == 200
    assert file_resp.content.startswith(b"%PDF")
    import fitz

    extracted = fitz.open(stream=file_resp.content, filetype="pdf")[0].get_text()
    assert "AETHER" in extracted
