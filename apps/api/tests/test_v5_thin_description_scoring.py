"""v5 — a posting with no real text must not be scored as a perfect match.

MEASURED IN PRODUCTION (2026-08-02), which is why this exists:

    rows with <200 chars of description : 52 rows, avg fitScore 58.9, max 78.6
    rows with a real description        : 59 rows, avg fitScore 40.8, max 56.5

A posting whose description was EMPTY scored 74.63 — the highest on the board.
The engine scores keyword overlap plus semantic similarity, so with almost no
text there is nearly nothing to mismatch and emptiness reads as a perfect fit.

That inverts the v5 qualification architecture, which ranks by fitScore: the
LEAST informative jobs float to the top of the user's board, and they drag the
adaptive median cut upward with them.

The fix is an honest refusal — leave the score NULL and let the job show
unranked — rather than persisting a number that means nothing.
"""
from __future__ import annotations

from app.agents.fit_scorer import (
    MIN_SCORABLE_CHARS,
    FitScorerAgent,
    has_scorable_evidence,
)


def test_a_teaser_line_is_not_scorable_evidence():
    """The real shape of the contaminating rows: a salary teaser from an alert
    email card, ~15-40 chars."""
    assert has_scorable_evidence("VPSG6 $142,790 - $191,084 p.a. + super") is False
    assert has_scorable_evidence("") is False
    assert has_scorable_evidence("   ") is False
    assert has_scorable_evidence(None) is False


def test_a_real_job_description_is_scorable():
    real = (
        "We are seeking a Senior Business Analyst to lead requirements discovery "
        "across our payments platform. You will partner with product and "
        "engineering, run stakeholder workshops, define acceptance criteria and "
        "support delivery through to release. Experience with agile delivery and "
        "large-scale platform modernisation is essential."
    )
    assert len(real) >= MIN_SCORABLE_CHARS
    assert has_scorable_evidence(real) is True


def test_job_text_of_a_thin_posting_stays_below_the_gate():
    """Title + teaser must not sneak past the gate just because the title is long."""
    job = {
        "title": "Senior Product Manager - Subscriptions Lifecycle",
        "description": "Excellent salary with annual performance bonus",
        "requirements": [],
    }
    assert has_scorable_evidence(FitScorerAgent._job_text(job)) is False


class _RecordingEngine:
    def __init__(self):
        self.scored: list[str] = []

    def score(self, resume_text, job_text):
        self.scored.append(job_text)
        return type("S", (), {"overall": 74.63})()


class _StubRepo:
    def __init__(self, jobs):
        self._jobs = jobs
        self.persisted: list[tuple[str, float]] = []

    def list_by_user(self, user_id):
        return self._jobs

    def update_fit_score(self, job_id, fit, ats):
        self.persisted.append((job_id, fit))

    def advance_status(self, job_id, status, allowed_from=None):
        return None


def test_thin_postings_are_never_scored_or_persisted(monkeypatch):
    """The core guarantee: no fitScore is written from a stub, and the run says
    so rather than silently dropping the row."""
    monkeypatch.setattr(
        "app.agents.fit_scorer.require_user_resume_text", lambda uid, msg: "a real resume " * 40
    )
    thin = {"id": "thin-1", "title": "Product Manager", "description": "$150k + super", "requirements": []}
    rich = {
        "id": "rich-1",
        "title": "Business Analyst",
        "description": "Lead requirements discovery across the payments platform. " * 6,
        "requirements": [],
    }
    repo = _StubRepo([thin, rich])
    engine = _RecordingEngine()

    result = FitScorerAgent(repository=repo, engine=engine).run("user-1")

    assert result.skipped_no_evidence == 1
    assert [job_id for job_id, _ in repo.persisted] == ["rich-1"]
    assert all("150k" not in text for text in engine.scored), (
        "the thin posting reached the engine — it must be refused before scoring"
    )


def test_the_refusal_is_counted_not_silent(monkeypatch):
    monkeypatch.setattr(
        "app.agents.fit_scorer.require_user_resume_text", lambda uid, msg: "a real resume " * 40
    )
    jobs = [
        {"id": f"thin-{i}", "title": "PM", "description": "$1", "requirements": []}
        for i in range(4)
    ]
    repo = _StubRepo(jobs)
    result = FitScorerAgent(repository=repo, engine=_RecordingEngine()).run("user-1")

    assert result.skipped_no_evidence == 4
    assert result.scored == 0
    assert repo.persisted == []
