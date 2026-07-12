"""Story bank router — CRUD over STAR entries + display enrichment (P2-S09).

The persisted ``StoryEntry`` row carries the canonical STAR content, ``metrics``
and ``tags``. The Story Bank screen additionally needs a few *display*
attributes (category, impact badge, starred flag), all derived from the real
row: category from tags/title, impact from the largest evidenced percent
metric. No usage or voice metrics are exposed — nothing tracks them yet, and
invented numbers must never be presented as real. ``starred`` is the one
mutable display attribute and is persisted inside the existing ``metrics`` JSON
(``metrics.__starred``) so no schema change is required.
"""
from __future__ import annotations

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
    ("Technical depth", (
        "architect", "platform", "ml", "llm", "devops", "data", "azure", "automation"
    )),
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
    risk_words = ("risk", "compliance", "audit", "regulat", "control", "governance")
    lead_words = ("lead", "led", "team", "mentor", "stakeholder", "manage", "drove", "align")
    tech_words = (
        "ml", "llm", "azure", "devops", "data", "platform", "automation",
        "ci", "engineer", "analytics", "telemetry"
    )
    if any(w in haystack for w in risk_words):
        return "Risk & Compliance"
    if any(w in haystack for w in lead_words):
        return "Leadership"
    if any(w in haystack for w in tech_words):
        return "Technical"
    return "Delivery"


def _derive_impact(story: dict[str, Any]) -> str | None:
    """Largest evidenced PERCENT metric rendered as an impact badge label.

    Only values that are actually percentages qualify — either the value ends
    with ``%`` or the metric key names a percentage. A "$5M" or "75 hours"
    metric must never be rendered as "75% impact".
    """
    best: float | None = None
    for key, value in _evidence_metrics(story.get("metrics")).items():
        text = str(value).strip()
        key_is_pct = "percent" in key.lower() or "pct" in key.lower()
        if not text.endswith("%") and not key_is_pct:
            continue
        try:
            num = float(text.rstrip("%"))
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
    starred = sum(1 for r in rows if r["starred"])
    categories = len({r["category"] for r in rows})
    return {
        "total": total,
        "quantified": quantified,
        "starred": starred,
        "categories": categories,
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
