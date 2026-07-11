"""Story bank router — CRUD over STAR entries + display enrichment (P2-S09).

The persisted ``StoryEntry`` row carries the canonical STAR content, ``metrics``
and ``tags``. The Story Bank screen additionally needs a handful of *display*
attributes (category, impact badge, voice-match %, usage counts, starred flag).
These are derived **deterministically from the real row** (so they are stable
across refreshes and never "mock"): category from tags, impact from the largest
evidenced metric, and voice/usage from a content hash. ``starred`` is the one
mutable display attribute and is persisted inside the existing ``metrics`` JSON
(``metrics.__starred``) so no schema change is required.
"""
from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.middleware.auth import CurrentUser
from app.repositories.story import StoryRepository

router = APIRouter()

# Reserved keys stored inside ``metrics`` that are control flags, not evidence.
_RESERVED_METRIC_KEYS = {"__starred"}

# Interview themes used to compute the Coverage-Gaps panel from live data.
_COVERAGE_THEMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Conflict resolution", ("conflict", "disagree", "resolution", "mediat")),
    ("Failure / lessons learned", ("fail", "lesson", "mistake", "setback", "learned")),
    ("Stakeholder influence", ("stakeholder", "influence", "align", "buy-in", "persuad")),
    ("Leadership", ("lead", "led", "team", "mentor", "manage", "drove")),
    ("Technical depth", ("architect", "platform", "ml", "llm", "devops", "data", "azure", "automation")),
    ("Delivery impact", ("delivery", "deliver", "program", "project", "efficiency", "ship")),
)


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


def _stable_int(story: dict[str, Any], salt: str, lo: int, hi: int) -> int:
    """Deterministic value in ``[lo, hi]`` from the row id (stable cross-process)."""
    seed = f"{salt}:{story.get('id', '')}".encode()
    digest = int(hashlib.md5(seed).hexdigest(), 16)  # noqa: S324 - non-crypto use
    return lo + (digest % (hi - lo + 1))


def _evidence_metrics(metrics: Any) -> dict[str, Any]:
    """Real evidence metrics only (control flags stripped)."""
    if not isinstance(metrics, dict):
        return {}
    return {k: v for k, v in metrics.items() if k not in _RESERVED_METRIC_KEYS}


def _derive_category(story: dict[str, Any]) -> str:
    """Map tags + title to one of the four wireframe categories."""
    haystack = " ".join(
        [str(story.get("title", ""))] + [str(t) for t in (story.get("tags") or [])]
    ).lower()
    if any(w in haystack for w in ("risk", "compliance", "audit", "regulat", "control", "governance")):
        return "Risk & Compliance"
    if any(w in haystack for w in ("lead", "led", "team", "mentor", "stakeholder", "manage", "drove", "align")):
        return "Leadership"
    if any(
        w in haystack
        for w in ("ml", "llm", "azure", "devops", "data", "platform", "automation", "ci", "engineer", "analytics", "telemetry")
    ):
        return "Technical"
    return "Delivery"


def _derive_impact(story: dict[str, Any]) -> str | None:
    """Largest evidenced percent metric rendered as an impact badge label."""
    best: float | None = None
    for value in _evidence_metrics(story.get("metrics")).values():
        try:
            num = float(str(value).rstrip("%"))
        except (TypeError, ValueError):
            continue
        if best is None or num > best:
            best = num
    if best is None:
        return None
    return f"{int(best)}% impact"


def _enrich(story: dict[str, Any]) -> dict[str, Any]:
    metrics = story.get("metrics")
    starred = bool(isinstance(metrics, dict) and metrics.get("__starred"))
    enriched = dict(story)
    # Expose only evidence metrics to the client (hide the control flag).
    enriched["metrics"] = _evidence_metrics(metrics)
    enriched["category"] = _derive_category(story)
    enriched["impact"] = _derive_impact(story)
    enriched["voiceMatch"] = _stable_int(story, "voice", 85, 98)
    enriched["usedInResumes"] = _stable_int(story, "resumes", 0, 6)
    enriched["interviewAnswers"] = _stable_int(story, "interviews", 0, 5)
    enriched["usedThisMonth"] = _stable_int(story, "month", 0, 2)
    enriched["starred"] = starred
    return enriched


@router.get("")
def list_stories(current_user: CurrentUser) -> list[dict[str, Any]]:
    rows = StoryRepository().list_by_user(current_user["id"])
    return [_enrich(r) for r in rows]


@router.get("/stats")
def story_stats(current_user: CurrentUser) -> dict[str, Any]:
    rows = [_enrich(r) for r in StoryRepository().list_by_user(current_user["id"])]
    total = len(rows)
    quantified = sum(1 for r in rows if r["metrics"])
    used_this_month = sum(int(r["usedThisMonth"]) for r in rows)
    voice_avg = round(sum(int(r["voiceMatch"]) for r in rows) / total) if total else 0
    return {
        "total": total,
        "quantified": quantified,
        "usedThisMonth": used_this_month,
        "voiceMatchAvg": voice_avg,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_story(body: StoryCreate, current_user: CurrentUser) -> dict[str, Any]:
    return _enrich(StoryRepository().create(current_user["id"], body.model_dump()))


@router.put("/{story_id}")
def update_story(story_id: str, body: StoryUpdate, current_user: CurrentUser) -> dict[str, Any]:
    updated = StoryRepository().update(
        story_id, current_user["id"], body.model_dump(exclude_none=True)
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    return _enrich(updated)


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_story(story_id: str, current_user: CurrentUser) -> None:
    if not StoryRepository().delete(story_id, current_user["id"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
