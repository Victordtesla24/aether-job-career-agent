"""Story extractor agent — STAR entries from resume bullets (P2-S09).

Uses the STRUCTURED model tier through the record-replay LLM client. Every
extracted metric is validated against the resume text: a story whose metrics
contain numbers that do not appear in the resume is dropped (metrics must be
evidenced, never invented).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.fit_scorer import get_base_resume_path
from app.repositories.story import StoryRepository
from app.services.llm_client import LLMClient, get_model
from app.services.resume_parser import parse_resume_pdf

SYSTEM_PROMPT = (
    "You are a career-story analyst. Extract STAR (Situation, Task, Action, "
    "Result) stories from the candidate's resume bullets. Use ONLY facts and "
    "numbers present in the resume — never invent metrics. Respond with JSON: "
    '{"stories": [{"title": "...", "situation": "...", "task": "...", '
    '"action": "...", "result": "...", "metrics": {"...": "..."}, '
    '"tags": ["..."]}]}'
)

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

_STAR_FIELDS = ("title", "situation", "task", "action", "result")


@dataclass
class StoryExtractionResult:
    created: int = 0
    dropped: list[str] = field(default_factory=list)
    story_ids: list[str] = field(default_factory=list)


class StoryExtractorAgent:
    def __init__(
        self, llm: LLMClient | None = None, stories: StoryRepository | None = None
    ) -> None:
        self._llm = llm or LLMClient()
        self._stories = stories or StoryRepository()

    def run(self, user_id: str) -> StoryExtractionResult:
        resume_text = parse_resume_pdf(get_base_resume_path())["raw_text"]
        raw = self._llm.complete_json(
            "story_extractor",
            SYSTEM_PROMPT,
            f"Resume:\n{resume_text}",
            model=get_model("STRUCTURED"),
            temperature=0.0,
        )
        resume_numbers = set(_NUMBER_RE.findall(resume_text))
        # Dedupe against existing stories — re-running extraction must not
        # re-insert the same stories.
        existing_titles = {
            str(s.get("title", "")).strip().lower()
            for s in self._stories.list_by_user(user_id)
        }
        result = StoryExtractionResult()
        for story in raw.get("stories", []):
            if not all((story.get(f) or "").strip() for f in _STAR_FIELDS):
                result.dropped.append(story.get("title", "<untitled>"))
                continue
            if not self._metrics_evidenced(story.get("metrics") or {}, resume_numbers):
                result.dropped.append(story.get("title", "<untitled>"))
                continue
            title_key = str(story.get("title", "")).strip().lower()
            if title_key in existing_titles:
                result.dropped.append(story.get("title", "<untitled>"))
                continue
            existing_titles.add(title_key)
            created = self._stories.create(user_id, story)
            result.story_ids.append(created["id"])
            result.created += 1
        return result

    @staticmethod
    def _metrics_evidenced(metrics: dict[str, Any], resume_numbers: set[str]) -> bool:
        """Every number appearing in a metric value must exist in the resume."""
        for value in metrics.values():
            for number in _NUMBER_RE.findall(str(value)):
                if number not in resume_numbers:
                    return False
        return True
