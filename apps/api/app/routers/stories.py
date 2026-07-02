"""Story bank router — CRUD over STAR entries (P2-S09)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.middleware.auth import CurrentUser
from app.repositories.story import StoryRepository

router = APIRouter()


class StoryCreate(BaseModel):
    title: str = Field(min_length=1)
    situation: str = Field(min_length=1)
    task: str = Field(min_length=1)
    action: str = Field(min_length=1)
    result: str = Field(min_length=1)
    metrics: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)


class StoryUpdate(BaseModel):
    title: str | None = None
    situation: str | None = None
    task: str | None = None
    action: str | None = None
    result: str | None = None
    metrics: dict[str, Any] | None = None
    tags: list[str] | None = None


@router.get("")
def list_stories(current_user: CurrentUser) -> list[dict[str, Any]]:
    return StoryRepository().list_by_user(current_user["id"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_story(body: StoryCreate, current_user: CurrentUser) -> dict[str, Any]:
    return StoryRepository().create(current_user["id"], body.model_dump())


@router.put("/{story_id}")
def update_story(story_id: str, body: StoryUpdate, current_user: CurrentUser) -> dict[str, Any]:
    updated = StoryRepository().update(
        story_id, current_user["id"], body.model_dump(exclude_none=True)
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    return updated


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_story(story_id: str, current_user: CurrentUser) -> None:
    if not StoryRepository().delete(story_id, current_user["id"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
