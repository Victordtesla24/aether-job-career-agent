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


@router.get("/{resume_id}/download")
def download_resume(resume_id: str, current_user: CurrentUser) -> Response:
    """Download a resume as a format-preserving PDF.

    - **Base resume** (no parent): the original bundled PDF bytes, verbatim.
    - **Tailored resume**: the original PDF with *only* the reworded bullets
      redrawn in place — same two-column layout, peach title panel, coral
      accents and fonts — plus a subtle highlight behind each changed bullet.
      Every unchanged element stays byte-for-byte identical to the source.
    """
    from app.services.resume_pdf import render_tailored_pdf, resolve_original_pdf

    repo = ResumeRepository()
    resume = repo.get_by_id(resume_id, current_user["id"])
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")

    parent_id = resume.get("parentId")
    parent = repo.get_by_id(parent_id, current_user["id"]) if parent_id else None

    if parent is None:
        # Non-tailored root resume → original PDF bytes, unmodified.
        original = resolve_original_pdf(resume.get("formatHash"))
        pdf_bytes = original.read_bytes()
    else:
        # Tailored version → splice the reworded bullets into the source PDF.
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
        original = resolve_original_pdf(parent.get("formatHash") or resume.get("formatHash"))
        pdf_bytes = render_tailored_pdf(original, changes)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resume-{resume_id[:8]}.pdf"'},
    )