"""Resumes router — versioned resume access + diff (P2-S05)."""
from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.middleware.auth import CurrentUser
from app.repositories.resume import ResumeRepository

router = APIRouter()


@router.get("")
def list_resumes(current_user: CurrentUser) -> list[dict[str, Any]]:
    return ResumeRepository().list_by_user(current_user["id"])


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

    score = ATSEngine().score(text, job.get("description") or "")
    return {
        "resume_id": resume_id,
        "job_id": target_job_id,
        "job_title": job.get("title"),
        "company": job.get("company"),
        "overall": round(score.overall, 1),
        "keyword_match": round(score.keyword_match, 1),
        "semantic_similarity": round(score.semantic_similarity, 1),
        "experience_gap": round(score.experience_gap, 1),
        "matched_keywords": score.matched_keywords,
        "missing_keywords": score.missing_keywords,
        "requires_review": score.requires_review,
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
    parent_by_ref = {
        b.get("evidenceRef"): b.get("text", "")
        for b in (parent or {}).get("sections", {}).get("bullets", [])
    }
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
) -> tuple[str, str, str, list[dict[str, Any]]]:
    """Map a stored resume record onto the branded template's inputs.

    Used only on the structured-rendering fallback (no bundled source PDF on
    disk), so the resume is rebuilt from its ``sections`` payload rather than
    edited in place. Name/title/objective come from the parsed contact block
    when present, with the resume label and the first content line as
    fallbacks; every bullet is grouped under a single Experience heading.
    """
    sections = resume.get("sections", {}) or {}
    contact = sections.get("contact", {}) or {}
    raw_lines = [
        line.strip() for line in str(sections.get("raw_text", "")).splitlines() if line.strip()
    ]
    name = str(
        contact.get("name")
        or (raw_lines[0] if raw_lines else "")
        or resume.get("label")
        or "Resume"
    )
    title = str(contact.get("title") or contact.get("headline") or "")
    objective = str(sections.get("objective") or sections.get("summary") or "")
    bullets = [
        str(b.get("text", ""))
        for b in sections.get("bullets", [])
        if str(b.get("text", "")).strip()
    ]
    template_sections = [{"heading": "Experience", "bullets": bullets}] if bullets else []
    return name, title, objective, template_sections


@router.get("/{resume_id}/download")
def download_resume(resume_id: str, current_user: CurrentUser) -> Response:
    """Download a resume as a format-preserving PDF.

    - **Base resume** (no parent): the original bundled PDF bytes, verbatim.
    - **Tailored resume**: the original PDF with *only* the reworded bullets
      redrawn in place — same two-column layout, peach title panel, coral
      accents and fonts — plus a subtle highlight behind each changed bullet.
      Every unchanged element stays byte-for-byte identical to the source.
    - **No bundled source PDF on disk** (e.g. an externally-ingested variant):
      the resume is rebuilt from its structured content with the branded
      two-page template — each reworded bullet washed coral on page 2.
    """
    from app.services.resume_pdf import (
        create_branded_resume_pdf,
        render_tailored_pdf,
        resolve_original_pdf,
    )

    repo = ResumeRepository()
    resume = repo.get_by_id(resume_id, current_user["id"])
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")

    parent_id = resume.get("parentId")
    parent = repo.get_by_id(parent_id, current_user["id"]) if parent_id else None

    # The reworded bullets, diffed against the parent (empty for a base resume).
    changes: list[tuple[str, str]] = []
    if parent is not None:
        parent_by_ref = {
            b.get("evidenceRef"): b.get("text", "")
            for b in parent.get("sections", {}).get("bullets", [])
        }
        for bullet in resume.get("sections", {}).get("bullets", []):
            before = parent_by_ref.get(bullet.get("evidenceRef"))
            after = bullet.get("text", "")
            if before and after and before != after:
                changes.append((before, after))

    original = resolve_original_pdf(
        (parent or resume).get("formatHash") or resume.get("formatHash")
    )

    if original.exists():
        # Source PDF on hand → preserve its exact layout.
        if parent is None:
            pdf_bytes = original.read_bytes()  # base → verbatim bytes
        else:
            pdf_bytes = render_tailored_pdf(original, changes)  # splice in place
    else:
        # No source PDF → structured render with the branded template.
        name, title, objective, sections = _branded_content(resume)
        pdf_bytes = create_branded_resume_pdf(
            name, title, objective, sections, changes or None
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resume-{resume_id[:8]}.pdf"'},
    )