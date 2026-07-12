"""Resumes router — versioned resume access + diff (P2-S05)."""
from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, HTTPException, status
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
def download_resume(resume_id: str, current_user: CurrentUser):
    """Generate a side-by-side PDF: original vs tailored resume comparison."""
    from io import BytesIO

    from fastapi.responses import StreamingResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    repo = ResumeRepository()
    resume = repo.get_by_id(resume_id, current_user["id"])
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")

    parent_id = resume.get("parentId")
    parent = repo.get_by_id(parent_id, current_user["id"]) if parent_id else None

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm)
    styles = getSampleStyleSheet()
    body = []

    title_style = styles["Heading1"]
    heading_style = styles["Heading2"]
    normal_style = styles["Normal"]

    body.append(Paragraph("Resume Comparison — Original vs Tailored", title_style))
    body.append(Spacer(1, 6 * mm))

    row_data = [Paragraph("<b>Original Resume</b>", heading_style),
                Paragraph("<b>Tailored Resume</b>", heading_style)]

    orig_bullets = []
    if parent:
        for b in parent.get("sections", {}).get("bullets", []):
            orig_bullets.append(Paragraph(b.get("text", ""), normal_style))
    elif resume.get("sections", {}).get("raw_text"):
        for line in resume["sections"]["raw_text"].splitlines():
            stripped = line.strip()
            if stripped.startswith(("•", "●", "▪", "- ")):
                orig_bullets.append(Paragraph(stripped.lstrip("•●▪- "), normal_style))

    tailored_bullets = []
    tailored_sections = resume.get("sections", {})
    for b in tailored_sections.get("bullets", []):
        text = b.get("text", "")
        ref = b.get("evidenceRef")
        parent_bullets = (parent or {}).get("sections", {}).get("bullets", [])
        matched = any(o.get("evidenceRef") == ref for o in parent_bullets) if parent else False
        if matched:
            tailored_bullets.append(Paragraph(text, normal_style))
        else:
            tailored_bullets.append(Paragraph(f"<b>{text}</b>", normal_style))

    max_len = max(len(orig_bullets), len(tailored_bullets))
    for i in range(max_len):
        left = orig_bullets[i] if i < len(orig_bullets) else Paragraph("", normal_style)
        right = tailored_bullets[i] if i < len(tailored_bullets) else Paragraph("", normal_style)
        row_data.extend([left, right])

    tbl = Table([row_data[i:i + 2] for i in range(0, len(row_data), 2)],
                colWidths=[doc.width / 2 - 5 * mm, doc.width / 2 - 5 * mm])
    tbl.setStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                  ("GRID", (0, 0), (-1, -1), 0.5, "#CCCCCC"),
                  ("TOPPADDING", (0, 0), (-1, -1), 4)])

    body.append(tbl)
    doc.build(body)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=resume-{resume_id[:8]}.pdf"},
    )