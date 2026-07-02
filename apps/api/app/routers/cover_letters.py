"""Cover letters router (P2-S06)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.middleware.auth import CurrentUser
from app.repositories.cover_letter import CoverLetterRepository

router = APIRouter()


@router.get("")
def list_cover_letters(current_user: CurrentUser) -> list[dict[str, Any]]:
    return CoverLetterRepository().list_by_user(current_user["id"])


@router.get("/{letter_id}")
def get_cover_letter(letter_id: str, current_user: CurrentUser) -> dict[str, Any]:
    letter = CoverLetterRepository().get_by_id(letter_id, current_user["id"])
    if letter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cover letter not found")
    return letter
