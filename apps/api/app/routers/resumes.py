"""Resumes router — versioned resume access + diff (P2-S05)."""
from __future__ import annotations

import hashlib
import os
import urllib.parse
from dataclasses import dataclass
from typing import Any

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.middleware.auth import CurrentUser
from app.repositories.resume import ResumeRepository
from app.services.resume_docx import DOCX_CONTENT_TYPE

router = APIRouter()

#: Hard ceiling on an uploaded résumé (U2a). The bytes are now persisted whole
#: in ``Resume.originalFile``, so an unbounded upload would be an unbounded row;
#: 10MB is far above any real résumé (the bundled reference PDFs are ~100KB)
#: while still refusing an accidental or hostile large-file POST. Enforced on a
#: BOUNDED read, so an oversized body is never fully buffered.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

_PDF_MAGIC = b"%PDF"

_PDF_CONTENT_TYPE = "application/pdf"
#: Re-exported from the DOCX engine so ingestion and rendering name the same
#: WordprocessingML media type (U2b).
_DOCX_CONTENT_TYPE = DOCX_CONTENT_TYPE
_TEXT_EXTENSIONS = (".txt", ".text", ".md", ".markdown")

#: Honest rejection copy (MON-012). Before U2a, ANY non-PDF upload was decoded
#: with ``errors="replace"``, so a .docx, a screenshot or a corrupt file was
#: silently persisted as a Resume row full of U+FFFD replacement characters and
#: presented to the user as their résumé. Naming the formats Aether genuinely
#: supports is the honest answer; guessing is not.
_UNSUPPORTED_FORMAT_DETAIL = (
    "Unsupported file format. Aether reads PDF (.pdf), Word (.docx) and "
    "plain-text (.txt/.md) résumés; this file is not a readable document in "
    "any of those formats."
)


@router.get("")
def list_resumes(current_user: CurrentUser) -> list[dict[str, Any]]:
    repo = ResumeRepository()
    return _with_format_preserved(
        repo.list_by_user(current_user["id"]),
        repo.original_meta_by_user(current_user["id"]),
    )


def _with_format_preserved(
    resumes: list[dict[str, Any]], original_meta: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Stamp each résumé with an honest ``formatPreserved`` + ``formatFidelity``.

    ``formatPreserved`` is ``True`` ONLY when ``GET /resumes/{id}/download``
    would genuinely reproduce the user's own document, ``False`` when it
    re-renders in Aether's template, and ``None`` when the source version
    cannot be resolved at all (MON-011 + U2b). ``formatFidelity`` — ``{method,
    confidence, note}`` — says WHICH mechanism produces that outcome and states
    it in the user's own terms, because R-F4 forbids a silent claim: a
    docx-native preservation and a low-confidence PDF re-flow used to render
    identical copy in Resume Studio.

    The decision itself lives in :mod:`app.services.resume_format`, shared with
    the download endpoint below, so the claim can never drift from the render.

    Before MON-011, the Resume Studio "Format Integrity Check" panel inferred a
    preservation claim from ``formatHash === baseHash`` — a self-comparison
    that is trivially true for a base résumé and says nothing about the
    download path — so every paying user was told their typography, spacing,
    columns and margins were preserved for a file that re-flows.

    The parent lookup reads the SAME list (a résumé's parent is another of that
    user's own versions), so this adds no query; ``original_meta`` is one extra
    metadata-only query per listing and never loads a stored blob.
    """
    from app.services.resume_format import stamp_fidelity
    from app.services.resume_pdf import bundled_format_hashes

    return stamp_fidelity(resumes, bundled_format_hashes(), original_meta or {})


class ResumeIngestRequest(BaseModel):
    """Register an additional root resume for the authenticated user.

    Used to ingest alternate resume variants (e.g. the BA-positioned resume)
    so they live in the database, appear in Resume Studio, and are selectable
    for tailoring runs. ``raw_text`` is the full extracted resume text —
    bullets are derived server-side so the anti-fabrication evidence index
    stays consistent with the tailoring service.
    """

    label: str = Field(min_length=1, max_length=120)
    raw_text: str = Field(min_length=50)
    contact: dict[str, Any] | None = None
    format_hash: str | None = Field(default=None, max_length=64)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_resume(body: ResumeIngestRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Ingest a new root resume version (Phase-2 audit Section C)."""
    from app.services.resume_tailor import extract_bullets

    sections = {
        "raw_text": body.raw_text,
        "bullets": [
            {"text": b, "evidenceRef": f"bullet-{i}"}
            for i, b in enumerate(extract_bullets(body.raw_text))
        ],
        "contact": body.contact or {},
    }
    format_hash = body.format_hash or hashlib.sha256(body.raw_text.encode()).hexdigest()[:16]
    repo = ResumeRepository()
    return repo.create(
        current_user["id"],
        sections,
        format_hash,
        label=body.label,
        version=repo.next_version(current_user["id"]),
    )


def _looks_like_docx(data: bytes) -> bool:
    """True when ``data`` really is an OOXML word-processing package.

    Checked by CONTENT, never by the client's filename or Content-Type: the
    bytes must be a readable ZIP that contains the WordprocessingML part
    (``word/document.xml``). Random bytes behind a ``.docx`` extension fail
    here and are rejected honestly instead of being decoded into garbage text.

    Defined once, in :mod:`app.services.resume_docx`, so ingestion and the
    format-preserving render agree byte-for-byte on what a .docx is.
    """
    from app.services.resume_docx import looks_like_docx

    return looks_like_docx(data)


def _extract_pdf_text(data: bytes) -> str:
    import fitz

    try:
        doc = fitz.open(stream=data, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not parse PDF: {exc}"
        ) from exc


def _extract_docx_text(data: bytes) -> str:
    """Real WordprocessingML text extraction (U2a / R-F3).

    Reads the document's own paragraph and table model via ``python-docx``, so
    a .docx yields the actual words the user wrote. Paragraph order and blank
    lines are preserved because ``extract_bullets`` uses line structure (marker
    lines, all-caps section banners) to reassemble bullets. Table cells are
    appended after the body paragraphs — ``document.paragraphs`` covers only
    body-level paragraphs, so nothing is emitted twice.

    A damaged package fails HONESTLY with a 422, exactly like the sibling
    ``_extract_pdf_text``. A corrupt .docx surfaces low-level errors from every
    layer python-docx sits on, and they share no useful base class: a malformed
    ``[Content_Types].xml`` raises ``lxml.etree.XMLSyntaxError`` (a
    ``SyntaxError``), a damaged deflate stream inside ``word/document.xml``
    raises ``zlib.error``. Enumerating that family is a losing game and every
    miss is an unhandled 500 instead of the honest rejection MON-012 promises,
    so any parse failure is reported as an unprocessable entity.

    U2b: the paragraph walk lives in :mod:`app.services.resume_docx` and now
    marks Word's OWN list items with a ``"• "`` prefix. Word stores a bullet
    glyph in ``numbering.xml``, not in the paragraph text, so a .docx résumé
    previously extracted ZERO bullets through ``extract_bullets`` (a
    line-marker state machine) — the upload succeeded and then nothing in it
    could ever be tailored.
    """
    from app.services.resume_docx import extract_docx_lines

    try:
        lines = extract_docx_lines(data)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not parse DOCX: {exc}"
        ) from exc
    return "\n".join(lines)


def _extract_upload_text(filename: str, data: bytes) -> tuple[str, str]:
    """Extract résumé text from an upload, and report the format Aether VERIFIED.

    Returns ``(raw_text, content_type)`` where ``content_type`` is derived from
    what the bytes actually are (or, for plain text, from the extension) — never
    echoed from the client's Content-Type header, which is unverified input.
    Anything that is not a readable PDF, DOCX or UTF-8 text document raises an
    honest 422 (MON-012) rather than being force-decoded into noise.
    """
    lowered = filename.lower()
    if data.startswith(_PDF_MAGIC) or lowered.endswith(".pdf"):
        return _extract_pdf_text(data), _PDF_CONTENT_TYPE
    if _looks_like_docx(data):
        return _extract_docx_text(data), _DOCX_CONTENT_TYPE
    if lowered.endswith(_TEXT_EXTENSIONS):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "This file is not valid UTF-8 text, so it cannot be read as a "
                "plain-text résumé. Supported formats: PDF (.pdf), Word (.docx) "
                "and UTF-8 text (.txt/.md).",
            ) from exc
        content_type = (
            "text/markdown; charset=utf-8"
            if lowered.endswith((".md", ".markdown"))
            else "text/plain; charset=utf-8"
        )
        return text, content_type
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _UNSUPPORTED_FORMAT_DETAIL)


def _safe_upload_filename(filename: str) -> str:
    """The upload's own name, stripped of anything that is not a file name.

    Drops directory components (a browser or a hostile client may send a path),
    non-printable characters and quotes — the same characters that would let a
    stored name break out of the ``Content-Disposition`` header when it is
    served back by ``GET /resumes/{id}/original``.
    """
    base = os.path.basename(filename.replace("\\", "/")).strip()
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in '"\\')
    return cleaned[:255] or "resume"


def _content_disposition(filename: str) -> str:
    """An ``attachment`` disposition carrying the original file name.

    Non-latin-1 names cannot travel in a bare ``filename=`` parameter, so they
    are emitted as RFC 5987 ``filename*=UTF-8''…`` instead of being mangled.
    """
    try:
        filename.encode("latin-1")
    except UnicodeEncodeError:
        quoted = urllib.parse.quote(filename, safe="")
        return f"attachment; filename*=UTF-8''{quoted}"
    return f'attachment; filename="{filename}"'


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_resume(
    current_user: CurrentUser,
    file: UploadFile = File(...),
    extract_stories: bool = Form(default=False),
) -> dict[str, Any]:
    """Upload a resume file as a new root version (SC-ST-03).

    Extracts text server-side and registers a new ROOT resume through the same
    section-building path as JSON ingestion. Uploading, on its own, makes no
    LLM call and consumes NOTHING of the caller's metered run allowance.

    U2a (R-F1/R-F3/MON-012) — what the upload now does with the FILE, not just
    its text:

    * The exact bytes are stored on the new résumé (``originalFile``) with
      their name and their VERIFIED content type, and ``formatHash`` becomes the
      full SHA-256 of those bytes. That upload is the user's immutable baseline
      document: it is written once here and no code path ever rewrites it, so
      every later tailoring run derives from a source that still exists.
      ``GET /resumes/{id}/original`` serves it back byte-identical.
    * Format is decided by CONTENT, not by the client's claims: ``%PDF`` magic
      → PyMuPDF, an OOXML ZIP containing ``word/`` → python-docx paragraph and
      table text, ``.txt``/``.md`` → strict UTF-8. Anything else is a 422 that
      names the supported formats. Previously every non-PDF upload was decoded
      with ``errors="replace"``, so a real .docx, a screenshot, or a corrupt
      file became a Resume row of U+FFFD garbage presented back as the user's
      résumé (MON-012).
    * Uploads over ``MAX_UPLOAD_BYTES`` are refused with 413 on a bounded read.

    ``extract_stories`` (F-03, PROD-UAT-2026-08-03) — OPT-IN, default OFF.
    This endpoint used to dispatch the ``storyExtractor`` agent
    unconditionally so the Story Bank would reflect the new base resume
    (SC-SB-01). That agent is genuine LLM work (STRUCTURED tier, one
    ``complete_json`` call per four résumé bullets), so it is metered: a
    single deliberate upload silently produced an unrequested agent run
    (``costUsd 0.0010``, ``billingAudit.quotaPath "metered_api"``) and burned
    one of a Free plan's five monthly runs, with no warning before the fact
    and no way to decline. Exempting the agent from metering was the wrong
    remedy — it really does call a model, and the exemption seam
    (``_DETERMINISTIC_BACKENDS`` / ``_OPTIONAL_LLM_BY_BACKEND``) exists only
    for calls that reach NO model — so extraction is now the caller's explicit
    choice, priced and disclosed before they commit. When it IS requested the
    dispatch is unchanged: same agent, same atomic reserve, same audit row,
    same GAP-P6-RESFIX entitlement propagation. The capability itself is not
    lost — ``POST /agents/story-extractor/run`` (the Story Bank's "Draft
    missing stories" trigger) runs exactly the same extraction on demand.

    The response reports both halves honestly: ``storyExtractionRequested``
    says whether extraction was asked for, and ``storyExtraction`` carries the
    run result — ``None`` when it was not requested, so no caller can render
    after-the-fact copy claiming a run that never happened.
    """
    # Bounded read: one byte past the cap is enough to prove the file is over
    # it, so an oversized upload is never fully buffered or persisted.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Resume file is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB "
            "upload limit.",
        )
    filename = _safe_upload_filename(file.filename or "resume")
    raw_text, content_type = _extract_upload_text(filename, data)
    if len(raw_text.strip()) < 50:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Extracted resume text is too short to be a resume",
        )
    from app.services.resume_tailor import extract_bullets

    stem = filename.rsplit(".", 1)[0][:100] or "Uploaded resume"
    sections = {
        "raw_text": raw_text,
        "bullets": [
            {"text": b, "evidenceRef": f"bullet-{i}"}
            for i, b in enumerate(extract_bullets(raw_text))
        ],
        "contact": {},
    }
    repo = ResumeRepository()
    resume = repo.create(
        current_user["id"],
        sections,
        # FULL SHA-256 of the stored bytes (U2a / R-F1). This used to be
        # truncated to 16 hex chars; the digest now identifies a document we
        # actually keep, and matches resume_parser.compute_format_hash's
        # long-standing convention. resolve_original_pdf accepts both widths,
        # so pre-existing truncated hashes keep resolving.
        hashlib.sha256(data).hexdigest(),
        label=f"Uploaded — {stem}",
        version=repo.next_version(current_user["id"]),
        original_file=data,
        original_filename=filename,
        original_content_type=content_type,
    )
    extraction: dict[str, Any] | None = None
    if extract_stories:
        try:
            from app.routers.agents import _dispatch

            extraction = _dispatch(current_user["id"], "storyExtractor", {})
        except HTTPException:
            # An HTTPException here (e.g. the 402 subscription-required paywall
            # gate in _record_run) is a real API error, not an extraction
            # failure — it must propagate to the client so a non-subscriber is
            # routed to /pricing instead of getting a 200 with the error buried
            # in storyExtraction.error (GAP-P6-RESFIX).
            raise
        except Exception as exc:  # noqa: BLE001 — upload must survive extraction issues
            # B1c (ORCH-B1-BLUEPRINT-2026-08-14.md §3.3 "the missed
            # surface"): the corrective loop itself never raises a new
            # exception here (a failed correction is a dropped story with a
            # recorded reason) — this branch stays reachable only for a
            # genuine, unexpected extractor failure. Recording the exception
            # TYPE alongside its message keeps a swallowed failure at least
            # as diagnosable as the honest verdicts the success path already
            # surfaces, without changing this response's existing shape.
            extraction = {"error": str(exc), "errorType": type(exc).__name__}
    return {
        **resume,
        "storyExtraction": extraction,
        "storyExtractionRequested": extract_stories,
    }


@router.get("/{resume_id}")
def get_resume(resume_id: str, current_user: CurrentUser) -> dict[str, Any]:
    resume = ResumeRepository().get_by_id(resume_id, current_user["id"])
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    return resume


@router.get("/{resume_id}/ats")
def ats_score(
    resume_id: str, current_user: CurrentUser, job_id: str | None = None
) -> dict[str, Any]:
    """Deterministic ATS score of this resume version against a job description.

    Scores against the version's source job by default (``?job_id=`` overrides).
    The breakdown is the real ATS engine output — keyword coverage, semantic
    similarity, experience gap — never a fabricated number (SC-RS-05).
    """
    repo = ResumeRepository()
    resume = repo.get_by_id(resume_id, current_user["id"])
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    target_job_id = job_id or resume.get("sourceJobId")
    if not target_job_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Resume has no target job — tailor it against a job or pass ?job_id=",
        )
    from app.repositories.job import JobRepository

    job = JobRepository().get_by_id(target_job_id, current_user["id"])
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target job not found")
    sections = resume.get("sections") or {}
    text = sections.get("raw_text") or "\n".join(
        b.get("text", "") for b in sections.get("bullets", [])
    )
    if not text.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Resume has no scoreable text"
        )
    from app.services.ats_engine import ATSEngine
    from app.services.fit_evidence import job_evidence_text

    # F-UAX-01: score against the SAME JD text `GET /jobs/{id}/insights` uses
    # (title + description + requirements, `job_evidence_text`) — not the
    # description alone. Both endpoints feed the Resume Studio before/after
    # panel for the same job, so a JD-corpus mismatch here would leak into
    # every displayed ATS and dimension delta as a spurious term that has
    # nothing to do with the tailoring itself.
    score = ATSEngine().score(text, job_evidence_text(job))
    return {
        "resume_id": resume_id,
        "job_id": target_job_id,
        "job_title": job.get("title"),
        "company": job.get("company"),
        "overall": round(score.overall, 1),
        "keyword_match": round(score.keyword_match, 1),
        "semantic_similarity": round(score.semantic_similarity, 1),
        # GMV4-ats-002: which path actually produced semantic_similarity —
        # "local"/"hf_api" (genuine) or "degraded" (neutral placeholder, see
        # ats_engine.py's ATSScore.semantic_path). Without this, a degraded
        # score is indistinguishable from a real measurement to any caller.
        "semantic_path": score.semantic_path,
        # Unambiguous, client-branchable boolean twin of semantic_path —
        # never requires the client to know the sentinel string. Round 3:
        # WHITELIST — only "local"/"hf_api" count as measured; "degraded",
        # "untracked" and any unrecognised value all read as degraded.
        "semantic_degraded": score.semantic_path not in ("local", "hf_api"),
        "experience_gap": round(score.experience_gap, 1),
        "matched_keywords": score.matched_keywords,
        "missing_keywords": score.missing_keywords,
        "requires_review": score.requires_review,
    }


def _resume_scoreable_text(resume: dict[str, Any]) -> str:
    sections = resume.get("sections") or {}
    return sections.get("raw_text") or "\n".join(
        b.get("text", "") for b in sections.get("bullets", [])
    )


@router.get("/{resume_id}/tailoring-impact")
def tailoring_impact(
    resume_id: str, current_user: CurrentUser, job_id: str | None = None
) -> dict[str, Any]:
    """The before/after pair for one tailored version — ONE authority (R-01/R-03).

    U-AX build spec item 3 ("BEFORE/AFTER HONESTY"). Both halves are produced
    HERE, by the same blend and the same rounding authority
    (``routers/jobs.py::build_fit_dimensions`` / ``_round``: integer, clamped
    [0,100]), against the same JD corpus (``job_evidence_text``):

    * ``before`` — the baseline résumé vs this job, delegated verbatim to
      ``_build_insights``, i.e. the identical payload the Job Discovery fit
      radar renders. Not a re-implementation; literally the same call.
    * ``after`` — the tailored version's own re-score, blended by the same
      function.

    Round 2 computed the "after" half in the BROWSER from the wire's
    already-1-decimal subscores while the "before" half arrived pre-rounded to
    integers server-side. That duplicated blend put up to ±0.5 of rounding
    artefact into every displayed delta (~25% of the product's measured ~2-point
    average lift) and had to re-derive the provenance rules by hand, which is
    how a placeholder-contaminated baseline reached the screen flagged as
    measured. There is now nothing left to duplicate.

    PROVENANCE: a half whose ATS is not a genuine measurement reports
    ``ats: null`` + ``atsMeasured: false``. The number is WITHHELD rather than
    flagged, so no consumer can render it as a bold headline the way the panel
    did in round 2 — the untrustworthy arm simply carries no number.
    """
    from app.repositories.job import JobRepository
    from app.routers.jobs import _build_insights, _round, build_fit_dimensions
    from app.services.ats_engine import ATSEngine
    from app.services.fit_evidence import job_evidence_text

    repo = ResumeRepository()
    resume = repo.get_by_id(resume_id, current_user["id"])
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    target_job_id = job_id or resume.get("sourceJobId")
    if not target_job_id:
        # Picking a job would fabricate the comparison: a before/after pair is
        # only meaningful against the posting the version was tailored for.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Resume has no target job — tailor it against a job or pass ?job_id=",
        )
    job = JobRepository().get_by_id(target_job_id, current_user["id"])
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target job not found")
    text = _resume_scoreable_text(resume)
    if not text.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Resume has no scoreable text"
        )

    before = _build_insights(job, current_user["id"])
    before_measured = bool(
        before.get("scored")
        and before.get("atsMeasured")
        and not before.get("semanticDegraded")
    )

    try:
        score = ATSEngine().score(text, job_evidence_text(job))
        after_trusted = score.semantic_path in ("local", "hf_api")
        after_dimensions = build_fit_dimensions(
            job,
            keyword_match=float(score.keyword_match),
            semantic=float(score.semantic_similarity),
            experience=float(score.experience_gap),
            overall=float(score.overall),
            semantic_trusted=after_trusted,
            resume_measured=True,
        )
        after_ats = _round(float(score.overall)) if after_trusted else None
        after_measured = after_trusted
        after_reason = (
            None
            if after_trusted
            else "the semantic scoring model was unavailable for this run"
        )
    except Exception:  # noqa: BLE001 — an unscoreable half is reported, never faked
        # No engine output at all: unlike the job panel there is no stored
        # fitScore to fall back on for a tailored version, and inventing one
        # is exactly the defect this endpoint exists to close.
        after_dimensions = build_fit_dimensions(
            job,
            keyword_match=0.0, semantic=0.0, experience=0.0, overall=0.0,
            semantic_trusted=False, resume_measured=False,
        )
        after_ats = None
        after_measured = False
        after_reason = "the ATS scoring engine could not score this version"

    before_reason = (
        None
        if before_measured
        else (
            "the ATS scoring engine could not score your baseline résumé "
            "against this posting"
            if not before.get("atsMeasured")
            else "the semantic scoring model was unavailable for the baseline score"
        )
    )
    return {
        "resumeId": resume_id,
        "jobId": target_job_id,
        "jobTitle": job.get("title"),
        "company": job.get("company"),
        # Stated on the wire so a client cannot reintroduce a second rounding
        # hop without contradicting the payload it is rendering.
        "granularity": "integer_0_100",
        "before": {
            "label": "Baseline résumé",
            "ats": before["overall"] if before_measured else None,
            "atsMeasured": before_measured,
            "unmeasuredReason": before_reason,
            "dimensions": before["dimensions"],
        },
        "after": {
            "label": "Tailored version",
            "ats": after_ats,
            "atsMeasured": after_measured,
            "unmeasuredReason": after_reason,
            "dimensions": after_dimensions,
        },
    }


@router.get("/{resume_id}/diff")
def diff_resume(resume_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Bullet-level diff of a tailored resume against its parent."""
    repo = ResumeRepository()
    resume = repo.get_by_id(resume_id, current_user["id"])
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    if not resume.get("parentId"):
        return {"resume_id": resume_id, "parent_id": None, "changes": []}
    parent = repo.get_by_id(resume["parentId"], current_user["id"])
    # First occurrence wins for duplicated refs (pre-fix tailored versions),
    # matching the tailor service's healing — the diff stays consistent with
    # the originals each rewrite was actually validated against.
    parent_by_ref: dict[Any, str] = {}
    for b in (parent or {}).get("sections", {}).get("bullets", []):
        parent_by_ref.setdefault(b.get("evidenceRef"), b.get("text", ""))
    changes = []
    for bullet in resume.get("sections", {}).get("bullets", []):
        ref = bullet.get("evidenceRef")
        original = parent_by_ref.get(ref, "")
        if bullet.get("text") != original:
            changes.append(
                {"evidenceRef": ref, "before": original, "after": bullet.get("text")}
            )
    return {"resume_id": resume_id, "parent_id": resume["parentId"], "changes": changes}


def _branded_content(
    resume: dict[str, Any],
) -> tuple[str, str, str, list[dict[str, Any]], list[str]]:
    """Map a stored résumé record onto the branded template's inputs — ALL of it.

    Used on the structured-rendering fallback (no bundled source PDF on disk, or
    an in-document rewrite that could not complete), so the résumé is rebuilt
    from its ``sections`` payload rather than edited in place.

    CRITICAL (2026-08-14): this function used to map a résumé onto its FIRST RAW
    LINE plus a single "Experience" heading and throw the rest away, so the
    download a subscriber would have sent an employer carried no contact
    details, no education, no skills and no certifications — and, because the
    renderer also truncated at one page, only 17 of 25 bullets
    (``uat/reports/evidence/agents-uplift/u2b/verify-final/CRITICAL-FINDING-content-loss.json``).
    The mapping now goes through :func:`parse_resume_document`, the same whole-
    document model the completeness verifier measures the produced file against.
    """
    from app.services.resume_document import parse_resume_document

    document = parse_resume_document(resume)
    template_sections = [
        {
            "heading": section.heading,
            "items": [
                {"kind": item.kind, "text": item.text} for item in section.items
            ],
        }
        for section in document.sections
    ]
    return (
        document.name,
        document.title,
        document.objective,
        template_sections,
        list(document.contact),
    )


def _tailored_text_document(
    data: bytes, changes: list[tuple[str, str]]
) -> tuple[bytes, int]:
    """A plain-text/Markdown résumé with ONLY the reworded lines replaced.

    R-F4's "TXT/MD trivially preserved" case: the file has no layout beyond its
    own characters, so preserving the format means returning the user's own
    bytes with the changed sentences substituted in place — line order,
    indentation, blank lines and every untouched line survive exactly.

    Returns ``(bytes, applied_count)``; the caller compares the count against
    the number of requested changes, because a download that quietly drops a
    rewrite would hand the user a file that is neither their baseline nor their
    tailored résumé.
    """
    text = data.decode("utf-8", errors="strict")
    applied = 0
    for before, after in changes:
        if before and before in text:
            text = text.replace(before, after, 1)
            applied += 1
    return text.encode("utf-8"), applied


@dataclass(frozen=True)
class _RenderedResume:
    """A produced download plus the VERIFIED fidelity report for it."""

    content: bytes
    media_type: str
    filename: str
    fidelity: Any  # app.services.resume_format.FormatFidelity


def _tailoring_changes(
    resume: dict[str, Any], parent: dict[str, Any] | None
) -> list[tuple[str, str]]:
    """The reworded bullets of ``resume``, diffed against its parent."""
    if parent is None:
        return []
    parent_by_ref = {
        b.get("evidenceRef"): b.get("text", "")
        for b in parent.get("sections", {}).get("bullets", [])
    }
    changes: list[tuple[str, str]] = []
    for bullet in resume.get("sections", {}).get("bullets", []):
        before = parent_by_ref.get(bullet.get("evidenceRef"))
        after = bullet.get("text", "")
        if before and after and before != after:
            changes.append((before, after))
    return changes


def _inplace_render_or_fallback(
    rendered: bytes,
    media_type: str,
    filename: str,
    changes: list[tuple[str, str]],
    source: dict[str, Any],
    base_report: Any,
    *,
    stored_original: bool,
) -> tuple[_RenderedResume | None, Any]:
    """Decide whether an in-place render ships, or falls to the branded render.

    MODELS-LIVE R-FMT §2/§3 — the format-preservation ruling that replaces the
    U2b all-or-nothing gate. An in-place render (PDF splice / DOCX-native /
    text-native) reproduces the user's OWN document, so it SHIPS with every
    rewrite it could place; a rewrite it could not place keeps the baseline
    wording and is disclosed as residue (``changesDropped`` + the honest note),
    NEVER a reason to drop the whole preserved layout to the branded template.

    It falls back to the branded render in exactly two honest cases, both of
    which the branded (content-complete) render handles better than a preserved
    layout would:

    * the produced file cannot be re-read at all (corruption we did not cause);
    * the render lost part of the user's WHOLE original document — a dropped
      heading, a vanished contact line, an eaten untracked bullet. That is
      measured against the parent's own document with only the PLACED rewrites
      substituted (:func:`build_applied_content`), so an unplaceable rewrite
      whose original wording still stands is NOT mistaken for content loss (the
      false positive that used to nuke the layout), while a genuine loss still
      routes to the complete branded render — the U2b CRITICAL guarantee, intact.

    Returns ``(rendered_resume, None)`` to ship, or ``(None, fallback_report)``
    to continue to the branded render with an honest reason.
    """
    from app.services.format_verification import verify_changes
    from app.services.resume_completeness import (
        build_applied_content,
        verify_completeness,
    )
    from app.services.resume_format import native_fallback_fidelity, verified_fidelity

    verification = verify_changes(rendered, media_type, changes)
    if not verification.text_extracted:
        return None, native_fallback_fidelity(
            unreadable=True, stored_original=stored_original
        )
    applied_changes = [
        (outcome.before, outcome.after)
        for outcome in verification.outcomes
        if outcome.applied
    ]
    completeness = verify_completeness(
        rendered, media_type, build_applied_content(source, applied_changes)
    )
    if not completeness.complete:
        # TRUE whole-document loss (not a mere unplaceable rewrite) → the branded
        # render carries this version's complete content; ship that instead.
        return None, native_fallback_fidelity(
            content_incomplete=True, stored_original=stored_original
        )
    return (
        _RenderedResume(
            content=rendered,
            media_type=media_type,
            filename=filename,
            fidelity=verified_fidelity(
                base_report,
                verification,
                completeness=completeness,
                partial_preserves_format=True,
            ),
        ),
        None,
    )


def _render_resume(
    resume_id: str, user_id: str, *, branded: bool = False, highlight: bool = False
) -> _RenderedResume:
    """Produce a résumé download AND verify the fidelity claim made about it.

    Shared by ``GET /resumes/{id}/download`` and ``GET /resumes/{id}/fidelity``
    so the report and the file can never disagree: the report is derived from
    THIS artifact, by re-reading it, not from the résumé's metadata. ``highlight``
    is part of that pact — both endpoints default it to ``False`` and pass the
    caller's own value through, so the report always describes the exact variant
    the same request would have downloaded.

    ``highlight`` selects the Résumé Studio DIFF PREVIEW (the peach/coral wash
    behind each reworded line) instead of the clean, employer-facing document.
    It defaults to ``False`` on EVERY render path below — splice, branded opt-in
    and branded fallback alike — because a résumé sent to an employer must not
    carry diff marking (RFMT-2; live production shipped the wash on nine bullets
    across all three pages of a tailored download). Nothing else about any path
    changes with the flag: the redaction, the in-place splice, the completeness
    check and the fidelity contract are byte-for-byte the same work.

    That distinction is not academic. Until this round the splice branch
    described itself from a formatHash match alone and claimed "every other
    element is identical to the source document" — a claim live production
    falsified, because the in-place engine only edits right-column work bullets
    and had silently skipped a rewrite aimed at the left rail
    (uat/reports/evidence/agents-uplift/u2b/verify/, 2026-08-14).
    """
    from app.services.format_verification import verify_changes
    from app.services.resume_completeness import build_resume_content, verify_completeness
    from app.services.resume_docx import (
        DOCX_CONTENT_TYPE,
        DocxParseError,
        render_tailored_docx_report,
    )
    from app.services.resume_format import (
        branded_optin_fidelity,
        describe_fidelity,
        is_docx_content_type,
        is_pdf_content_type,
        is_text_content_type,
        native_fallback_fidelity,
        verified_fidelity,
    )
    from app.services.resume_pdf import (
        PdfRenderError,
        create_branded_resume_pdf,
        render_tailored_pdf,
        resolve_original_pdf,
    )

    repo = ResumeRepository()
    resume = repo.get_by_id(resume_id, user_id)
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    parent_id = resume.get("parentId")
    parent = repo.get_by_id(parent_id, user_id) if parent_id else None
    is_tailored = parent is not None
    changes = _tailoring_changes(resume, parent)
    source = parent or resume

    if branded:
        # EXPLICIT OPT-IN (``?branded=true``) — MODELS-LIVE R-FMT binding scope
        # item 5. The branded template is a design the user CHOSE ("re-style my
        # résumé"), never the silent fallback for a retained-original row: it is
        # reachable only by asking for it here, is labelled ``branded-optin`` (not
        # ``reflow-template``), and is reported ``preserved: False`` so it can
        # never masquerade as the user's own layout. It is still the LAST render,
        # so its completeness is REPORTED, not routed around.
        from app.services.format_verification import verify_changes
        from app.services.resume_completeness import (
            build_resume_content as _brc,
        )
        from app.services.resume_completeness import (
            verify_completeness as _vc,
        )

        name, title, objective, sections, contact = _branded_content(resume)
        pdf_bytes = create_branded_resume_pdf(
            name, title, objective, sections, changes or None,
            contact=contact, highlight=highlight,
        )
        return _RenderedResume(
            content=pdf_bytes,
            media_type=_PDF_CONTENT_TYPE,
            filename=f"resume-{resume_id[:8]}.pdf",
            fidelity=verified_fidelity(
                branded_optin_fidelity(),
                verify_changes(pdf_bytes, _PDF_CONTENT_TYPE, changes),
                completeness=_vc(
                    pdf_bytes, _PDF_CONTENT_TYPE, _brc(resume, parent)
                ),
            ),
        )
    #: What this résumé OWES the user — every section heading, every bullet
    #: (tracked or not), every line of prose and every contact detail. Each
    #: produced artifact is measured against it before it is served, because the
    #: per-change check cannot see content nobody asked to rewrite (U2b
    #: CRITICAL, verify-final/). For a tailored version the ground truth is the
    #: PARENT's document with the approved rewrites mapped in, never the child's
    #: own parse: a child whose stored text has already lost a section has
    #: nothing left to report missing, which is exactly how the live loss
    #: passed verification (U2b round-2 review, critical/).
    content = build_resume_content(resume, parent)

    original = resolve_original_pdf(source.get("formatHash") or resume.get("formatHash"))
    data: bytes | None = None
    content_type: str | None = None
    #: Set when a native in-document rewrite could not be completed, so the
    #: branded render below reports WHY it happened instead of the generic
    #: "not yet available for this upload type" copy.
    fallback_report = None

    if original is None:
        # The user's OWN stored upload backs this version — a tailored child
        # derives from its parent's stored document, which is where the bytes
        # live (a child is never itself an upload).
        stored = repo.get_original_file(source["id"], user_id)
        data = (stored or {}).get("originalFile")
        content_type = (stored or {}).get("originalContentType")
        native_report = describe_fidelity(
            bundled_match=False,
            has_original=bool(data),
            content_type=content_type,
            is_tailored=is_tailored,
        )
        # COMPLETENESS RULE for both native paths: the native render is served
        # only when EVERY reworded bullet is verified present in the produced
        # document. A partial splice would return a file that is neither the
        # baseline nor the tailored résumé — a silent content loss, which is
        # worse than an honest re-format — so an incomplete rewrite falls
        # through to the branded template render, which is built from the
        # résumé's structured content and therefore always content-complete.
        if data and is_docx_content_type(content_type):
            try:
                if not is_tailored:
                    return _RenderedResume(
                        content=bytes(data),
                        media_type=DOCX_CONTENT_TYPE,
                        filename=f"resume-{resume_id[:8]}.docx",
                        fidelity=verified_fidelity(
                            native_report, None, byte_identical=True
                        ),
                    )
                rendered, _applied = render_tailored_docx_report(data, changes)
                shipped, fallback_report = _inplace_render_or_fallback(
                    rendered,
                    DOCX_CONTENT_TYPE,
                    f"resume-{resume_id[:8]}.docx",
                    changes,
                    source,
                    native_report,
                    stored_original=True,
                )
                if shipped is not None:
                    return shipped
            except DocxParseError:
                # Stored bytes that no longer open as a package (they passed the
                # upload gate, so this is corruption we did not cause): the user
                # still gets their tailored content through the branded render
                # instead of a 500.
                fallback_report = native_fallback_fidelity(unreadable=True)
        elif data and is_text_content_type(content_type):
            media_type = str(content_type)
            suffix = "md" if "markdown" in media_type else "txt"
            try:
                if not is_tailored:
                    return _RenderedResume(
                        content=bytes(data),
                        media_type=media_type,
                        filename=f"resume-{resume_id[:8]}.{suffix}",
                        fidelity=verified_fidelity(
                            native_report, None, byte_identical=True
                        ),
                    )
                rewritten, _applied_count = _tailored_text_document(data, changes)
                shipped, fallback_report = _inplace_render_or_fallback(
                    rewritten,
                    media_type,
                    f"resume-{resume_id[:8]}.{suffix}",
                    changes,
                    source,
                    native_report,
                    stored_original=True,
                )
                if shipped is not None:
                    return shipped
            except UnicodeDecodeError:
                fallback_report = native_fallback_fidelity(unreadable=True)
        elif data and is_pdf_content_type(content_type):
            # A genuine, non-bundled PDF upload — the MAJORITY real-world case
            # and the exact format of the live cfe7a0f→c12187 incident. Its
            # ``formatHash`` is a digest of the USER's own bytes, so
            # ``resolve_original_pdf`` returns None and the stored ``originalFile``
            # bytes (the parent's, for a tailored child) must be spliced DIRECTLY
            # rather than via a bundled path. Before this slice these bytes were
            # only ever consumed by the DOCX/text branches, so every PDF upload
            # dropped straight to the branded template — the relaxed in-place gate
            # was never even reached (ML-RFMT PDF splice gap).
            try:
                if not is_tailored:
                    return _RenderedResume(
                        content=bytes(data),  # base → the user's own PDF, verbatim
                        media_type=_PDF_CONTENT_TYPE,
                        filename=f"resume-{resume_id[:8]}.pdf",
                        fidelity=verified_fidelity(
                            native_report, None, byte_identical=True
                        ),
                    )
                spliced = render_tailored_pdf(
                    bytes(data), changes, highlight=highlight
                )
                shipped, fallback_report = _inplace_render_or_fallback(
                    spliced,
                    _PDF_CONTENT_TYPE,
                    f"resume-{resume_id[:8]}.pdf",
                    changes,
                    source,
                    native_report,
                    stored_original=True,
                )
                if shipped is not None:
                    return shipped
            except PdfRenderError:
                # Stored bytes that no longer open as a PDF (they passed the
                # upload gate, so this is corruption we did not cause): the user
                # still gets their tailored content through the branded render
                # rather than a 500.
                fallback_report = native_fallback_fidelity(unreadable=True)

    if original is not None and original.exists():
        # A bundled source PDF backs THIS résumé (seeded base / BA variant) →
        # preserve its exact layout.
        splice_report = describe_fidelity(
            bundled_match=True,
            has_original=bool(data),
            content_type=content_type,
            is_tailored=is_tailored,
        )
        if not is_tailored:
            return _RenderedResume(
                content=original.read_bytes(),  # base → verbatim bytes
                media_type=_PDF_CONTENT_TYPE,
                filename=f"resume-{resume_id[:8]}.pdf",
                fidelity=verified_fidelity(splice_report, None, byte_identical=True),
            )
        spliced = render_tailored_pdf(  # splice in place
            original, changes, highlight=highlight
        )
        # MODELS-LIVE R-FMT §2/§3 — the format-preservation ruling that replaces
        # the U2b all-or-nothing gate here. The in-place engine only redraws
        # right-column work bullets, so a rewrite aimed at the left rail cannot
        # be placed; under the old gate ONE such rewrite dropped the ENTIRE
        # two-column layout to the branded single-column template (the live
        # cfe7a0f→c12187 divergence). The splice preserves the user's own layout
        # and keeps the baseline wording of any rewrite it could not place, so it
        # SHIPS with the changes it CAN place and discloses the rest as residue —
        # falling back to the branded render only when the file is unreadable or
        # the WHOLE document lost content (measured against the placed rewrites).
        shipped, fallback_report = _inplace_render_or_fallback(
            spliced,
            _PDF_CONTENT_TYPE,
            f"resume-{resume_id[:8]}.pdf",
            changes,
            source,
            splice_report,
            stored_original=False,
        )
        if shipped is not None:
            return shipped

    # No bundled source PDF for this résumé — a user-authored upload/ingest
    # (NF-final-B-005) — or a native/in-place rewrite that could not be
    # completed → render from the résumé's OWN structured content with the
    # branded template; never serve the operator's bundled PDF bytes.
    name, title, objective, sections, contact = _branded_content(resume)
    pdf_bytes = create_branded_resume_pdf(
        name, title, objective, sections, changes or None,
        contact=contact, highlight=highlight,
    )
    reflow_report = fallback_report or describe_fidelity(
        bundled_match=False,
        has_original=bool(data),
        content_type=content_type,
        is_tailored=is_tailored,
    )
    # There is no further fallback beneath this render, so its completeness is
    # REPORTED rather than routed around: a loss here degrades the fidelity
    # claim and names what is missing, instead of being passed off as the
    # 9-of-10-changes success live production reported over a document with no
    # contact details in it.
    return _RenderedResume(
        content=pdf_bytes,
        media_type=_PDF_CONTENT_TYPE,
        filename=f"resume-{resume_id[:8]}.pdf",
        fidelity=verified_fidelity(
            reflow_report,
            verify_changes(pdf_bytes, _PDF_CONTENT_TYPE, changes),
            completeness=verify_completeness(pdf_bytes, _PDF_CONTENT_TYPE, content),
        ),
    )


def _fidelity_headers(fidelity: Any) -> dict[str, str]:
    """ASCII-safe fidelity summary for a binary download response.

    The body of a download is a file, so the honest report has to travel
    somewhere a client (or an operator verifying production) can read it
    without a second call. The note itself is not header-safe (it carries the
    user's own résumé wording and typographic punctuation), so only the
    machine-readable summary is emitted; the full report lives at
    ``GET /resumes/{id}/fidelity``.
    """
    return {
        "X-Aether-Format-Method": str(fidelity.method),
        "X-Aether-Format-Confidence": str(fidelity.confidence),
        "X-Aether-Changes-Requested": str(fidelity.changes_requested or 0),
        "X-Aether-Changes-Applied": str(fidelity.changes_applied or 0),
        "X-Aether-Changes-Dropped": str(fidelity.changes_dropped or 0),
        # Whole-document completeness, so an operator verifying a production
        # download sees content loss without a second call (U2b CRITICAL).
        "X-Aether-Content-Complete": (
            "unverified"
            if fidelity.content_complete is None
            else str(fidelity.content_complete).lower()
        ),
        "X-Aether-Content-Missing": str(len(fidelity.missing_content)),
    }


#: The explicit branded opt-in shared by ``/download`` and ``/fidelity`` — the
#: ONLY way to reach the Aether template for a résumé that has a preservable
#: original (MODELS-LIVE R-FMT binding scope item 5). Default ``False`` so the
#: format-preserving render is always what a plain download returns.
_BRANDED_OPTIN = Query(
    False,
    description=(
        "Explicitly re-style this résumé in the Aether branded template instead "
        "of preserving its own format. Honest opt-in: the response is reported "
        "as branded-optin / formatPreserved:false, never a silent fallback."
    ),
)


#: The Résumé Studio diff-preview opt-in shared by ``/download`` and
#: ``/fidelity`` (RFMT-2). Default ``False``, so what a plain download returns is
#: the clean, employer-facing document: no peach splice wash, no coral branded
#: wash, no diff marking of any kind. Studio asks for ``?diff=true`` when it
#: wants to SHOW the subscriber which lines were reworded; the Download button
#: never does.
_DIFF_PREVIEW = Query(
    False,
    description=(
        "Return the Résumé Studio diff preview — the same document with the "
        "reworded lines washed in the tailoring highlight. Off by default: the "
        "file a subscriber sends to an employer carries no diff marking."
    ),
)


def _diff_requested(value: Any) -> bool:
    """Resolve the ``diff`` option safely for IN-PROCESS handler calls.

    ``download_resume`` is not only an HTTP route: the email / auto-submission
    path calls it directly (``services/email_attachments.py``), where FastAPI
    never resolves the defaults and the parameter arrives as the ``Query``
    object itself — which is TRUTHY. A plain ``if diff:`` would therefore turn
    the diff preview ON for every emailed and auto-submitted résumé: the one
    document with the least excuse for carrying diff marking, since it goes
    straight to an employer and the subscriber never sees it.

    So only a genuine ``True`` — a request that actually asked for the preview
    — counts. Anything else (the unresolved default, ``?diff=false``, ``None``)
    is the clean employer-facing render.
    """
    return value is True


@router.get("/{resume_id}/fidelity")
def resume_fidelity(
    resume_id: str,
    current_user: CurrentUser,
    branded: bool = _BRANDED_OPTIN,
    diff: bool = _DIFF_PREVIEW,
) -> dict[str, Any]:
    """What a download of THIS version really does — verified, not asserted.

    Renders the version exactly as ``/download`` would (honouring the same
    ``branded`` and ``diff`` options), re-reads the produced document, and
    reports per-change whether the tailored wording is genuinely in it:
    ``changesRequested`` / ``changesApplied`` / ``changesDropped``, plus the
    rewrites that could not be applied.
    Resume Studio renders this report for the version the user opened;
    the listing (which cannot re-render every version) says the check is pending
    rather than claiming an outcome.
    """
    rendered = _render_resume(
        resume_id, current_user["id"], branded=branded, highlight=_diff_requested(diff)
    )
    return {
        "resume_id": resume_id,
        "formatPreserved": rendered.fidelity.preserved,
        **rendered.fidelity.as_dict(),
    }


@router.get("/{resume_id}/download")
def download_resume(
    resume_id: str,
    current_user: CurrentUser,
    branded: bool = _BRANDED_OPTIN,
    diff: bool = _DIFF_PREVIEW,
) -> Response:
    """Download a résumé in the baseline document's OWN format (U2b / R-F4).

    The baseline the user uploaded is the immutable source of truth for content
    AND format, so a tailored download changes words only — never the design:

    - **Bundled-asset PDF** (the seeded operator résumés): base → the original
      bytes verbatim; tailored → the original PDF with *only* the reworded
      bullets redrawn in place (same two-column layout, panel, accents, fonts).
    - **Stored PDF upload** (a genuine, non-bundled user PDF): base → the user's
      own file, byte-identical; tailored → the same PDF with only the reworded
      work bullets redrawn in place (``render_tailored_pdf`` on the stored
      bytes). A rewrite the splice cannot place keeps its baseline wording and is
      disclosed as residue — the layout is preserved, never dropped to branded.
    - **Stored .docx upload** → the flagship format-preserving path: base → the
      user's own file, byte-identical; tailored → native run-level text
      replacement inside their own document (``services/resume_docx.py``), so
      styles, numbering, tables, headers and every untouched run are carried
      through unchanged.
    - **Stored .txt/.md upload** → the same idea, trivially: their own file with
      the reworded lines substituted.
    - **No stored original** (text ingested through ``POST /resumes``, or
      uploaded before U2a kept files): rebuilt from the résumé's structured
      content with the branded template. This is a genuine re-format, so
      ``GET /resumes`` reports it as ``formatPreserved: false`` and tells the
      user to re-upload their source file to restore format-preserving
      tailoring, rather than implying fidelity it does not have (R-F2).

    An in-place render falls back to that branded template ONLY when the stored
    file cannot be re-read or the whole document lost content (the U2b CRITICAL
    guarantee) — both reported honestly, never silently. The branded template is
    otherwise reachable only by EXPLICIT opt-in (``?branded=true``), a user
    "re-style my résumé" choice reported as ``branded-optin`` /
    ``formatPreserved: false`` (binding scope item 5).

    Whichever branch runs, the produced file is re-read before it is returned
    and the response carries the VERIFIED summary — ``X-Aether-Format-Method``,
    ``X-Aether-Format-Confidence`` and the requested/applied/dropped change
    counts. The full report (including any rewrite that could not be applied)
    is at ``GET /resumes/{id}/fidelity``.

    The file this returns is UNMARKED (RFMT-2). Whichever branch renders it, the
    tailoring's own diff highlight — the peach wash behind a spliced bullet, the
    coral wash behind a branded one — is NOT drawn: this is the document a
    subscriber sends to an employer, and a recruiter opening a tinted file sees
    an annotated draft rather than a résumé. Résumé Studio asks for that marking
    explicitly with ``?diff=true`` when it is showing the subscriber what
    changed; the Download button does not, and never should.
    """
    rendered = _render_resume(
        resume_id, current_user["id"], branded=branded, highlight=_diff_requested(diff)
    )
    return Response(
        content=rendered.content,
        media_type=rendered.media_type,
        headers={
            "Content-Disposition": _content_disposition(rendered.filename),
            **_fidelity_headers(rendered.fidelity),
        },
    )


@router.get("/{resume_id}/original")
def download_original_resume(resume_id: str, current_user: CurrentUser) -> Response:
    """Download the résumé EXACTLY as it was uploaded (U2a / R-F1).

    This is the immutable baseline document — the same bytes, the same content
    type, the same file name the user gave us. It is deliberately distinct from
    ``/download``, which RENDERS a résumé (verbatim bundled PDF, in-place
    tailored splice, or the branded template) and can therefore return a
    document that never existed on the user's disk.

    Owner-only, exactly like every other ``/resumes/{id}`` route: another
    account's résumé is indistinguishable from a non-existent one (404).

    A résumé with no stored bytes 404s with an honest explanation instead of
    synthesising a stand-in file. That is the state of every row created before
    this slice (original bytes were never kept), of every JSON-ingested résumé
    (``POST /resumes`` carries text, not a file), and of every tailored child
    version (produced by the pipeline, never uploaded).
    """
    record = ResumeRepository().get_original_file(resume_id, current_user["id"])
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    data = record["originalFile"]
    if not data:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No original file is stored for this résumé. It was created without "
            "a file upload (typed/ingested text or a tailored version), or it "
            "was uploaded before Aether began preserving original documents — "
            "those bytes no longer exist, so there is nothing to return.",
        )
    filename = _safe_upload_filename(record["originalFilename"] or f"resume-{resume_id[:8]}")
    return Response(
        content=data,
        media_type=record["originalContentType"] or "application/octet-stream",
        headers={"Content-Disposition": _content_disposition(filename)},
    )