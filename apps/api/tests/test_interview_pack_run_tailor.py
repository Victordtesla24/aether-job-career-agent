"""The interview pack must start the REAL tailor agent.

``interview_pack._run_tailor`` imported ``TailorAgent`` while the class in
``app.agents.tailor_agent`` is ``TailoringAgent``: the import sat outside the
function's ``try`` block, so assembling a pack whose folder had no tailored
résumé yet failed with an ImportError instead of tailoring one (found by mypy
``attr-defined`` once ruff stopped hiding the step behind lint failures).
"""
from __future__ import annotations

from typing import Any

from app.agents import tailor_agent
from app.repositories import resume as resume_repository
from app.services import interview_pack


class _RecordingRuns:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def start(self, user_id: str, name: str, payload: dict[str, Any], parent_run_id: str | None = None) -> dict[str, str]:
        self.events.append(("start", name))
        return {"id": "run-child"}

    def finish(self, run_id: str, status: str, **_: Any) -> None:
        self.events.append(("finish", status))


def test_run_tailor_starts_tailoring_agent_and_returns_the_new_resume(monkeypatch) -> None:
    runs = _RecordingRuns()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(interview_pack, "AgentRunRepository", lambda: runs)
    monkeypatch.setattr(tailor_agent.TailoringAgent, "__init__", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(
        tailor_agent.TailoringAgent,
        "run",
        lambda self, user_id, job_id, *args, **kwargs: calls.append((user_id, job_id)),
    )
    monkeypatch.setattr(
        resume_repository.ResumeRepository,
        "get_tailored_for_job",
        lambda self, user_id, job_id: {"id": "tailored-1", "sourceJobId": job_id},
    )

    result = interview_pack._run_tailor("user-1", "job-1", "parent-run")

    assert result == {"id": "tailored-1", "sourceJobId": "job-1"}
    assert calls == [("user-1", "job-1")]
    assert runs.events == [("start", "tailor"), ("finish", "completed")]


def test_run_tailor_records_a_failed_child_run_when_the_agent_cannot_run(monkeypatch) -> None:
    runs = _RecordingRuns()
    monkeypatch.setattr(interview_pack, "AgentRunRepository", lambda: runs)
    monkeypatch.setattr(tailor_agent.TailoringAgent, "__init__", lambda self, *args, **kwargs: None)

    def _no_resume(self: object, user_id: str, job_id: str, *args: Any, **kwargs: Any) -> None:
        raise LookupError("no base resume")

    monkeypatch.setattr(tailor_agent.TailoringAgent, "run", _no_resume)

    assert interview_pack._run_tailor("user-1", "job-1", "parent-run") is None
    assert runs.events == [("start", "tailor"), ("finish", "failed")]
