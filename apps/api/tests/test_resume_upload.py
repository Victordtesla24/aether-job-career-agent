"""POST /resumes/upload — file ingestion + OPT-IN story extraction (SC-ST-03).

F-03 (PROD-UAT-2026-08-03): extraction used to be dispatched unconditionally,
so an upload silently spent a metered agent run. It is now opt-in via the
``extract_stories`` form flag (default off) — see
``apps/api/app/routers/resumes.py`` and
``tests/test_f03_upload_silent_quota_spend.py``, which owns the quota
assertions. The GAP-P6-RESFIX cases below are re-pointed at the path that
still dispatches (``extract_stories=true``) so every one of their original
assertions keeps its full force.

U2a (2026-08-13, R-F1 + R-F3 + MON-012 — doc-pipeline foundation, TDD-first):
the block at the bottom of this file pins the NEW immutable-baseline-storage
contract, written BEFORE the implementation exists (expected RED against
current code):

* R-F1 STORAGE — ``Resume`` gains ``originalFile``/``originalFilename``/
  ``originalContentType`` (the raw upload bytes + their identity) and
  ``formatHash`` becomes the FULL SHA-256 hex digest of those bytes (today's
  ``/resumes/upload`` truncates to 16 hex chars — ``compute_format_hash``
  elsewhere in the codebase already uses the full digest, so this is an
  honesty/consistency fix, not a new convention). A new
  ``GET /resumes/{id}/original`` streams those bytes back byte-identical
  with the real Content-Type/filename; a resume with no stored bytes (every
  pre-existing row) 404s HONESTLY instead of fabricating a file.
* IMMUTABILITY — no later pipeline step (a tailoring run, in particular) may
  ever rewrite a baseline's ``originalFile``/``formatHash``.
* R-F3 DOCX INGESTION — a real ``.docx`` upload is parsed with ``python-docx``
  into clean ``sections.raw_text`` (real words, not decode garbage) and its
  bytes are stored exactly like a PDF's.
* MON-012 HONEST REJECTION — undecodable/unsupported uploads (junk bytes
  behind a ``.docx``/``.doc``/``.rtf`` extension, or an image file) now 422
  with an honest error instead of silently decoding as UTF-8 replacement-
  character garbage and creating a Resume row of noise.
* SIZE CAP — uploads over 10MB are rejected honestly (413/422), not silently
  accepted and persisted.
"""
from __future__ import annotations

import hashlib
import os
import struct
import zipfile
from io import BytesIO

RESUME_TEXT = """VIKRAM DESHPANDE
Senior Technical Program Manager — Melbourne, VIC, Australia

EXPERIENCE
- Led a portfolio of delivery programs across banking platforms with 100% compliance.
- Automated a COBOL/mainframe regression harness, lifting test efficiency by 92%.
- Coached three agile squads through a cloud migration with zero missed releases.
"""


def _upload(
    client,
    auth_headers,
    filename: str,
    content: bytes,
    mime: str,
    *,
    extract_stories: bool = False,
):
    return client.post(
        "/resumes/upload",
        files={"file": (filename, content, mime)},
        data={"extract_stories": "true" if extract_stories else "false"},
        headers=auth_headers,
    )


def test_upload_text_resume_creates_root_without_running_extraction(
    client, auth_headers
):
    before = client.get("/resumes", headers=auth_headers).json()
    res = _upload(client, auth_headers, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain")
    assert res.status_code == 201
    body = res.json()
    assert body["label"].startswith("Uploaded — vik_resume")
    assert body["parentId"] is None
    assert body["sections"]["raw_text"].startswith("VIKRAM DESHPANDE")
    assert len(body["sections"]["bullets"]) >= 3
    # F-03: extraction is opt-in, so a plain upload runs none and says so.
    assert body["storyExtractionRequested"] is False
    assert body["storyExtraction"] is None
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


# ---------------------------------------------------------------------------
# GAP-P6-RESFIX: the storyExtractor auto-trigger must not bury a 402
# subscription-required entitlement error inside a 200 response (the extractor
# call runs through app.routers.agents._dispatch -> _record_run, which raises
# HTTPException BEFORE the extraction ever executes). Only genuine extractor
# failures for an entitled subscriber may be swallowed into storyExtraction.error.
# ---------------------------------------------------------------------------


def _set_plan(user_id: str, plan_id: str, status: str) -> None:
    """Force the user's Subscription row to (plan_id, status) with a matching
    UsageQuota ceiling — mirrors the helper in test_gap_p6_paywall.py."""
    from app.db import get_connection
    from app.repositories.billing import ensure_user_billing

    ensure_user_billing(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=%s,"updatedAt"=now() '
                'WHERE "userId"=%s',
                (plan_id, status, user_id),
            )
            cur.execute(
                'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=100,'
                '"updatedAt"=now() WHERE "userId"=%s',
                (plan_id, user_id),
            )
        conn.commit()


def test_upload_propagates_402_for_non_subscriber(
    client, auth_headers, test_user_id, monkeypatch
):
    """A non-subscriber's resume upload must surface the real 402 — not a
    200 with the paywall error buried in storyExtraction.error."""
    from app.repositories.billing import ensure_user_billing

    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    ensure_user_billing(test_user_id)  # Free/active by default -> NOT paid
    res = _upload(
        client, auth_headers, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain",
        extract_stories=True,
    )
    assert res.status_code == 402, res.text
    body = res.json()
    assert body["detail"]["error"] == "subscription_required"
    assert body["detail"]["upgradeUrl"] == "/pricing"


def test_upload_still_succeeds_for_paid_subscriber(
    client, auth_headers, test_user_id, monkeypatch
):
    """A paid subscriber's opt-in upload is unaffected — it still succeeds with
    a real storyExtraction result (no entitlement error to swallow)."""
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_plan(test_user_id, "pro", "active")
    res = _upload(
        client, auth_headers, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain",
        extract_stories=True,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["storyExtractionRequested"] is True
    extraction = body["storyExtraction"]
    assert extraction is not None
    assert "error" not in extraction


def test_upload_still_swallows_genuine_extractor_error_for_subscriber(
    client, auth_headers, test_user_id, monkeypatch
):
    """A real (non-HTTPException) extractor failure for an entitled
    subscriber must still be swallowed into storyExtraction.error — the
    upload itself must not fail."""
    from app.agents.story_extractor import StoryExtractorAgent

    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_plan(test_user_id, "pro", "active")

    def _boom(self, user_id):
        raise RuntimeError("synthetic extractor failure")

    monkeypatch.setattr(StoryExtractorAgent, "run", _boom)
    res = _upload(
        client, auth_headers, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain",
        extract_stories=True,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["storyExtraction"]["error"] == "synthetic extractor failure"


# ---------------------------------------------------------------------------
# U2a (2026-08-13) — R-F1 immutable baseline storage + GET /resumes/{id}/original
# ---------------------------------------------------------------------------

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

#: A real, distinctive résumé body — deliberately NOT the bundled operator
#: résumé (mirrors JORDAN_RESUME_TEXT's convention in conftest.py) so byte
#: round-trips can never be mistaken for a fallback/fixture PDF.
U2A_PDF_LINES = [
    "MORGAN CHEN",
    "Senior Data Engineer — Sydney, NSW, Australia",
    "",
    "EXPERIENCE",
    "- Built a streaming ETL pipeline processing 4 million events per day.",
    "- Reduced warehouse query latency by 63 percent through partitioning.",
    "- Mentored four junior engineers through a Snowflake migration.",
]

U2A_DOCX_PARAGRAPHS = [
    "TAYLOR OKONKWO",
    "Senior Product Manager — Brisbane, QLD, Australia",
    "EXPERIENCE",
    "Led discovery and delivery for a payments platform used by 2 million customers.",
    "Shipped a fraud-detection feature that cut chargeback losses by 31 percent.",
    "Ran quarterly roadmap reviews across five cross-functional squads.",
]


def _make_pdf_bytes(lines: list[str]) -> bytes:
    """A real, parseable single-page PDF (reportlab) — never a %PDF stub."""
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    y = 740
    for line in lines:
        c.drawString(72, y, line)
        y -= 16
    c.showPage()
    c.save()
    return buf.getvalue()


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    """A real .docx (python-docx) — a genuine OOXML zip, not junk bytes."""
    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_upload_pdf_stores_full_sha256_format_hash_of_original_bytes(
    client, auth_headers
):
    """R-F1: ``formatHash`` on an uploaded résumé is the full SHA-256 hex
    digest of the ORIGINAL bytes — matching ``compute_format_hash``'s
    convention used everywhere else in the codebase (resume_parser.py), not
    the 16-char truncation ``/resumes/upload`` currently computes."""
    pdf_bytes = _make_pdf_bytes(U2A_PDF_LINES)
    res = _upload(client, auth_headers, "morgan_resume.pdf", pdf_bytes, "application/pdf")
    assert res.status_code == 201, res.text
    body = res.json()
    expected_hash = hashlib.sha256(pdf_bytes).hexdigest()
    assert body["formatHash"] == expected_hash, (
        "formatHash must be the full SHA-256 hex digest of the original "
        f"upload bytes (got {body['formatHash']!r}, len={len(body['formatHash'])})"
    )


def test_download_original_returns_byte_identical_pdf(client, auth_headers):
    """R-F1: ``GET /resumes/{id}/original`` streams the ORIGINAL upload back
    byte-for-byte, with the real Content-Type and filename — never a
    re-rendered/re-flowed document (that is what ``/download`` is for)."""
    pdf_bytes = _make_pdf_bytes(U2A_PDF_LINES)
    created = _upload(
        client, auth_headers, "morgan_resume.pdf", pdf_bytes, "application/pdf"
    ).json()
    res = client.get(f"/resumes/{created['id']}/original", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.content == pdf_bytes, "original bytes must round-trip byte-identical"
    assert res.headers["content-type"].startswith("application/pdf")
    assert "morgan_resume.pdf" in res.headers.get("content-disposition", "")


def test_download_original_requires_auth(client):
    res = client.get("/resumes/whatever-id/original")
    assert res.status_code == 401


def test_download_original_404s_for_unknown_resume(client, auth_headers):
    res = client.get("/resumes/not-a-real-resume-id/original", headers=auth_headers)
    assert res.status_code == 404


def test_download_original_404s_for_another_users_resume(client, auth_headers):
    """Ownership must be enforced exactly like every other /resumes/{id}
    route (get_resume returns 404, not another account's bytes)."""
    import uuid

    pdf_bytes = _make_pdf_bytes(U2A_PDF_LINES)
    created = _upload(
        client, auth_headers, "morgan_resume.pdf", pdf_bytes, "application/pdf"
    ).json()

    other_email = f"fixture-user-{uuid.uuid4().hex[:8]}@example.com"
    other_creds = {"email": other_email, "password": "Sup3rSecret2"}
    assert client.post("/auth/register", json=other_creds).status_code == 201
    other_login = client.post("/auth/login", json=other_creds)
    assert other_login.status_code == 200
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}

    res = client.get(f"/resumes/{created['id']}/original", headers=other_headers)
    assert res.status_code == 404


def test_download_original_404s_honestly_for_resume_without_stored_bytes(
    client, auth_headers
):
    """A résumé created via the JSON-ingestion path (``POST /resumes``) has
    no file bytes to serve — EVERY pre-existing row is like this (R-F1 scout
    finding: original bytes were never stored before this slice). The
    endpoint must 404 with an honest JSON detail explaining the real gap,
    never fabricate/synthesize a file to satisfy the request."""
    created = client.post(
        "/resumes",
        json={"label": "Typed resume", "raw_text": RESUME_TEXT},
        headers=auth_headers,
    ).json()

    res = client.get(f"/resumes/{created['id']}/original", headers=auth_headers)
    assert res.status_code == 404, res.text
    content_type = res.headers.get("content-type", "")
    assert content_type.startswith("application/json"), (
        "a 404 for a missing original file must return an honest JSON "
        f"detail, never stream fabricated bytes (got content-type={content_type!r})"
    )
    detail = str(res.json().get("detail", "")).lower()
    assert "original" in detail, f"404 detail must name the real gap: {detail!r}"
    assert detail != "resume not found", (
        "the resume DOES exist (created above) — this 404 must be distinct "
        "from the generic 'no such resume' 404, or it is not honest about why"
    )


def test_tailoring_run_does_not_mutate_baseline_original_bytes_or_hash(
    client, auth_headers, monkeypatch
):
    """IMMUTABILITY: a tailoring run must create a NEW child résumé version —
    it must never rewrite the baseline's stored original bytes or formatHash.
    Uses the same explicit-``resume_id`` tailor path + deterministic
    ``ResumeTailorService.tailor`` stub as
    ``test_resume_ingest.py::test_tailor_run_accepts_explicit_resume_id``."""
    from app.services.resume_tailor import ResumeTailorService, TailorResult

    pdf_bytes = _make_pdf_bytes(U2A_PDF_LINES)
    baseline = _upload(
        client, auth_headers, "morgan_resume.pdf", pdf_bytes, "application/pdf"
    ).json()
    hash_before = baseline["formatHash"]

    run = client.post(
        "/agents/scout/run",
        json={"query": "data engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202, run.text
    job = client.get("/jobs", headers=auth_headers).json()[0]

    def _one_change(self, resume_text, job_description, originals=None, evidence_extra=""):
        original = {
            "text": "Reduced warehouse query latency by 63 percent through partitioning.",
            "evidenceRef": "bullet-0",
        }
        changed = {
            "text": "Reduced warehouse query latency by 63 percent through partitioning, "
            "aligned to the target role.",
            "evidenceRef": "bullet-0",
        }
        return TailorResult(bullets=[changed], changes=1, rejected=[], originals=[original])

    monkeypatch.setattr(ResumeTailorService, "tailor", _one_change)

    resp = client.post(
        "/agents/tailor/run",
        json={"job_id": job["id"], "resume_id": baseline["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    child = client.get(f"/resumes/{resp.json()['resume_id']}", headers=auth_headers).json()
    assert child["parentId"] == baseline["id"]  # a genuinely NEW row, not an in-place edit

    reloaded = client.get(f"/resumes/{baseline['id']}", headers=auth_headers).json()
    assert reloaded["formatHash"] == hash_before, (
        "tailoring rewrote the baseline's formatHash — the baseline is no "
        "longer immutable"
    )

    original_after = client.get(f"/resumes/{baseline['id']}/original", headers=auth_headers)
    assert original_after.status_code == 200, original_after.text
    assert original_after.content == pdf_bytes, (
        "tailoring rewrote the baseline's stored original bytes — the "
        "baseline is no longer immutable"
    )


def test_upload_docx_extracts_clean_text_and_stores_original_bytes(client, auth_headers):
    """R-F3: a real .docx is parsed with python-docx into clean text — real
    words, not the UTF-8-replacement-character garbage MON-012 found — and
    its original bytes are stored/round-trippable exactly like a PDF's.

    RED-confirmation note: against current (unfixed) code this fails at the
    very first assertion with 422 "unsupported NUL (0x00) character" — a
    REAL, unrelated pre-existing guard (app/db.py) tripped because a genuine
    .docx is a ZIP archive whose compressed bytes, decoded as UTF-8 replace-
    on-error text (today's only non-PDF path), happen to contain NUL bytes.
    That is still an honest RED for the right high-level reason — there is no
    real DOCX ingestion path today, so a genuine .docx upload cannot
    currently succeed at all (this NUL-guard trip, or MON-012 garbage-201 for
    a docx that happens not to hit it, are the only two possible outcomes).
    """
    docx_bytes = _make_docx_bytes(U2A_DOCX_PARAGRAPHS)
    res = _upload(client, auth_headers, "taylor_resume.docx", docx_bytes, DOCX_CONTENT_TYPE)
    assert res.status_code == 201, res.text
    body = res.json()
    raw_text = body["sections"]["raw_text"]
    assert "�" not in raw_text, "raw_text contains the UTF-8 replacement character (MON-012 garbage decode)"
    assert "TAYLOR OKONKWO" in raw_text
    assert "fraud-detection feature that cut chargeback losses by 31 percent" in raw_text
    assert body["formatHash"] == hashlib.sha256(docx_bytes).hexdigest()

    original = client.get(f"/resumes/{body['id']}/original", headers=auth_headers)
    assert original.status_code == 200, original.text
    assert original.content == docx_bytes
    assert "wordprocessingml" in original.headers["content-type"]
    assert "taylor_resume.docx" in original.headers.get("content-disposition", "")


def _nul_free_random_bytes(n: int) -> bytes:
    """``n`` random bytes with every NUL (0x00) byte nudged to 0x01.

    Postgres text/jsonb columns reject an embedded NUL character outright
    (``psycopg2.errors.CharacterNotInRepertoire`` / the API's "unsupported
    NUL (0x00) character" 422 guard) — real ``os.urandom`` junk contains a
    NUL roughly every 256 bytes, so an un-adjusted sample would 422 for that
    unrelated pre-existing guard rather than for the MON-012 format-honesty
    behaviour this test exists to pin (a false-positive RED/pass either way).
    Nudging keeps the sample equally undecodable as a resume while removing
    that confound.
    """
    return bytes(b or 0x01 for b in os.urandom(n))


#: A 422 detail must not merely contain the substring "supported" — the
#: pre-existing unrelated NUL-byte guard's own message ("...an unsupported
#: NUL (0x00) character") contains it too, which would make a naive
#: substring check pass for the WRONG reason. Require one of these more
#: specific, honestly-scoped phrases instead.
_HONEST_FORMAT_REJECTION_MARKERS = (
    "pdf", "docx", "unsupported format", "unsupported file",
    "supported format", "supported file",
)


def _assert_honest_format_rejection_detail(detail: str) -> None:
    lowered = detail.lower()
    assert "nul" not in lowered and "0x00" not in lowered, (
        f"422 detail is the unrelated NUL-byte guard, not an honest format "
        f"rejection: {detail!r}"
    )
    assert any(marker in lowered for marker in _HONEST_FORMAT_REJECTION_MARKERS), (
        f"422 detail must honestly name supported formats, got: {detail!r}"
    )


def test_upload_rejects_undecodable_docx_junk_honestly(client, auth_headers):
    """MON-012: random bytes behind a ``.docx`` extension are not a valid
    OOXML zip and must not silently decode as UTF-8-replacement-character
    garbage into a new Resume row — reject 422 with an honest error naming
    supported formats, and create nothing."""
    junk = _nul_free_random_bytes(4096)
    before = len(client.get("/resumes", headers=auth_headers).json())
    res = _upload(client, auth_headers, "corrupt.docx", junk, DOCX_CONTENT_TYPE)
    assert res.status_code == 422, res.text
    _assert_honest_format_rejection_detail(str(res.json().get("detail", "")))
    after = len(client.get("/resumes", headers=auth_headers).json())
    assert after == before, "a rejected upload must not create a garbage Resume row"


def _make_docx_with_malformed_content_types() -> bytes:
    """A ZIP that LOOKS like a .docx but whose ``[Content_Types].xml`` is truncated.

    This is the shape a partially-written or truncated OOXML package really
    has: valid ZIP magic and a ``word/`` member (so ``_looks_like_docx``
    accepts it), but python-docx's package reader hits ``lxml.etree.
    XMLSyntaxError`` parsing the content-types part — an exception that is a
    ``SyntaxError``, sharing no base class with ``PackageNotFoundError`` /
    ``KeyError`` / ``ValueError`` / ``zipfile.BadZipFile``.
    """
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types><Override")
        archive.writestr("_rels/.rels", "<?xml version='1.0'?><Relationships/>")
        archive.writestr("word/document.xml", "<?xml version='1.0'?><document/>")
    return buf.getvalue()


def _corrupt_docx_deflate_stream(data: bytes, member: str = "word/document.xml") -> bytes:
    """A genuine .docx with bytes flipped INSIDE ``member``'s deflate stream.

    ZIP headers and the central directory are left intact, so the file still
    opens as an archive and lists its members (``_looks_like_docx`` passes) —
    the damage only surfaces when python-docx decompresses the part, which
    raises ``zlib.error`` ("invalid bit length repeat"). That is the realistic
    truncated-download / bit-rot corruption case, and ``zlib.error`` inherits
    only from ``Exception``.
    """
    info = zipfile.ZipFile(BytesIO(data)).getinfo(member)
    header_offset = info.header_offset
    name_len, extra_len = struct.unpack("<HH", data[header_offset + 26: header_offset + 30])
    start = header_offset + 30 + name_len + extra_len
    assert info.compress_size > 48, (
        "the .docx main part is unexpectedly tiny — this helper needs a real "
        f"deflate stream to damage (compress_size={info.compress_size})"
    )
    corrupted = bytearray(data)
    for i in range(start + 8, start + 40):
        corrupted[i] ^= 0xFF
    return bytes(corrupted)


def test_upload_rejects_docx_with_malformed_content_types_honestly(client, auth_headers):
    """A .docx whose OOXML package is malformed must 422 honestly, not 500.

    BE review finding (2026-08-13): ``_extract_docx_text`` caught only
    ``(PackageNotFoundError, KeyError, ValueError, zipfile.BadZipFile)``, so a
    real corrupt package raised ``lxml.etree.XMLSyntaxError`` straight through
    the endpoint as an unhandled 500 — the opposite of MON-012's honest
    rejection, and inconsistent with the sibling ``_extract_pdf_text``.
    """
    before = len(client.get("/resumes", headers=auth_headers).json())
    res = _upload(
        client,
        auth_headers,
        "malformed.docx",
        _make_docx_with_malformed_content_types(),
        DOCX_CONTENT_TYPE,
    )
    assert res.status_code == 422, res.text
    _assert_honest_format_rejection_detail(str(res.json().get("detail", "")))
    after = len(client.get("/resumes", headers=auth_headers).json())
    assert after == before, "a rejected upload must not create a garbage Resume row"


def test_upload_rejects_docx_with_corrupted_deflate_stream_honestly(client, auth_headers):
    """A genuine .docx damaged mid-stream must 422 honestly, not 500.

    Same BE review finding as above, second reproduction: the archive opens
    and lists ``word/document.xml``, but decompressing it raises ``zlib.error``
    — also outside the old narrow ``except`` tuple.
    """
    corrupted = _corrupt_docx_deflate_stream(_make_docx_bytes(U2A_DOCX_PARAGRAPHS))
    before = len(client.get("/resumes", headers=auth_headers).json())
    res = _upload(client, auth_headers, "truncated.docx", corrupted, DOCX_CONTENT_TYPE)
    assert res.status_code == 422, res.text
    _assert_honest_format_rejection_detail(str(res.json().get("detail", "")))
    after = len(client.get("/resumes", headers=auth_headers).json())
    assert after == before, "a rejected upload must not create a garbage Resume row"


def test_upload_rejects_undecodable_binary_with_image_extension(client, auth_headers):
    """MON-012: a PNG (or any non-text binary) is honestly not a résumé —
    it must not silently decode into a garbage-text Resume row either."""
    png_bytes = b"\x89PNG\r\n\x1a\n" + _nul_free_random_bytes(2048)
    before = len(client.get("/resumes", headers=auth_headers).json())
    res = _upload(client, auth_headers, "screenshot.png", png_bytes, "image/png")
    assert res.status_code == 422, res.text
    after = len(client.get("/resumes", headers=auth_headers).json())
    assert after == before, "a rejected upload must not create a garbage Resume row"


def test_upload_rejects_files_over_10mb(client, auth_headers):
    """SIZE CAP: an oversized upload is rejected honestly (413/422), never
    silently accepted and persisted whole into the database."""
    ten_mb = 10 * 1024 * 1024
    chunk = b"Experienced engineer delivering complex platform outcomes. "
    oversized = chunk * (ten_mb // len(chunk) + 10)
    assert len(oversized) > ten_mb

    before = len(client.get("/resumes", headers=auth_headers).json())
    res = _upload(client, auth_headers, "huge_resume.txt", oversized, "text/plain")
    # Truncated failure message on purpose: an accepted (201) oversized upload
    # would otherwise echo the whole multi-megabyte persisted body back into
    # the assertion/CI log.
    assert res.status_code in (413, 422), f"status={res.status_code} body[:300]={res.text[:300]!r}"
    after = len(client.get("/resumes", headers=auth_headers).json())
    assert after == before, "an oversized upload rejected for size must not create a Resume row"


# --- U2a Settings badge: GET /workspaces/settings.resume.originalStored ---
#
# apps/web/src/app/dashboard/settings/settings-client.tsx renders an honest
# "Original stored ✓" / "Re-upload to enable format preservation" badge on
# the active-resume summary card, derived from this field. It must reflect
# the ACTUAL presence of the stored original bytes, never default to true.


def test_settings_reports_original_stored_true_after_a_fresh_upload(client, auth_headers):
    res = _upload(client, auth_headers, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain")
    assert res.status_code == 201, res.text

    settings = client.get("/workspaces/settings", headers=auth_headers).json()
    assert settings["resume"]["originalStored"] is True
    assert settings["resume"]["activeFile"] == res.json()["label"]


def test_settings_reports_original_stored_false_for_a_json_ingested_resume(client, auth_headers):
    """A resume created via POST /resumes (JSON ingest — no uploaded file
    bytes at all, e.g. registering an alternate resume variant) genuinely has
    no original stored; the settings badge must say so honestly instead of
    defaulting to true."""
    res = client.post(
        "/resumes",
        json={"label": "BA-positioned variant", "raw_text": RESUME_TEXT},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text

    settings = client.get("/workspaces/settings", headers=auth_headers).json()
    assert settings["resume"]["originalStored"] is False
    assert settings["resume"]["activeFile"] == "BA-positioned variant"


def test_settings_reports_original_stored_false_when_user_has_no_resume_at_all(
    client, auth_headers
):
    settings = client.get("/workspaces/settings", headers=auth_headers).json()
    assert settings["resume"]["activeFile"] is None
    assert settings["resume"]["originalStored"] is False
