"""Resumes router — versioned resume access + diff (P2-S05)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.middleware.auth import CurrentUser
from app.repositories.resume import ResumeRepository

router = APIRouter()


@router.get("")
def list_resumes(current_user: CurrentUser) -> list[dict[str, Any]]:
    return ResumeRepository().list_by_user(current_user["id"])


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


@router.post("/{resume_id}/download", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def download_resume(resume_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """PDF regeneration is a later slice — explicit 501 keeps the contract honest."""
    return {
        "detail": "Resume PDF export is not implemented yet (planned in a later phase)",
        "resume_id": resume_id,
    }
