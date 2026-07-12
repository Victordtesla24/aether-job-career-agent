"""POST /resumes/upload — file ingestion + auto story extraction (SC-ST-03)."""
from __future__ import annotations

RESUME_TEXT = """VIKRAM DESHPANDE
Senior Technical Program Manager — Melbourne, VIC, Australia

EXPERIENCE
- Led a portfolio of delivery programs across banking platforms with 100% compliance.
- Automated a COBOL/mainframe regression harness, lifting test efficiency by 92%.
- Coached three agile squads through a cloud migration with zero missed releases.
"""


def _upload(client, auth_headers, filename: str, content: bytes, mime: str):
    return client.post(
        "/resumes/upload",
        files={"file": (filename, content, mime)},
        headers=auth_headers,
    )


def test_upload_text_resume_creates_root_and_extracts(client, auth_headers):
    before = client.get("/resumes", headers=auth_headers).json()
    res = _upload(client, auth_headers, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain")
    assert res.status_code == 201
    body = res.json()
    assert body["label"].startswith("Uploaded — vik_resume")
    assert body["parentId"] is None
    assert body["sections"]["raw_text"].startswith("VIKRAM DESHPANDE")
    assert len(body["sections"]["bullets"]) >= 3
    # Story extraction is auto-triggered (best-effort) and reported.
    assert "storyExtraction" in body
    after = client.get("/resumes", headers=auth_headers).json()
    assert len(after) == len(before) + 1


def test_upload_rejects_too_short_content(client, auth_headers):
    res = _upload(client, auth_headers, "empty.txt", b"too short", "text/plain")
    assert res.status_code == 422


def test_upload_rejects_unparseable_pdf(client, auth_headers):
    res = _upload(client, auth_headers, "broken.pdf", b"%PDF-1.4 garbage", "application/pdf")
    assert res.status_code == 422


def test_upload_requires_auth(client):
    res = _upload(client, {}, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain")
    assert res.status_code == 401
