"""v5 — the evidence gate must also RETIRE the scores it was written for.

``557739e`` added ``has_scorable_evidence`` so a posting with no real text is
never GIVEN a fit score. It changed nothing about the scores that were already
persisted before it shipped, and ``FitScorerAgent.run`` skips any job that
already carries one (``if job.get("fitScore") is not None and not rescore``),
so those rows were unreachable by design.

MEASURED IN PRODUCTION 2026-08-03, at the commit that shipped the gate:

    scored rows whose evidence text is below the gate : 48
        seek-alert      45   (avg 15 chars of description, every one scored)
        smartrecruiters  3
    the top of that set scored 76.76 / 74.63 / 73.51 — above EVERY row that
    carries a real description (those top out at ~56).

The board ranks by ``fitScore DESC NULLS LAST``, so the gate's own refusals
(NULL) sort last while the pre-gate junk sorts FIRST. The user's board is
still led by postings the engine now refuses to score at all.

These tests pin the remediation: every persisted score whose evidence is below
the gate is cleared, automatically, by both paths that can reach it — the app's
own startup and any fit-scorer run — and rows that DO carry real evidence keep
(or get) a genuine score.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.fit_scorer import FitScorerAgent
from app.db import get_connection

_RICH = (
    "We are seeking a Senior Business Analyst to lead requirements discovery "
    "across our payments platform. You will partner with product and "
    "engineering, run stakeholder workshops, define acceptance criteria and "
    "support delivery through to release. Experience with agile delivery and "
    "large-scale platform modernisation is essential."
)
#: The real shape of the contaminating production rows (seek-alert): a salary
#: teaser line, ~15 chars of description.
_THIN = "$142,790 p.a."


# ---------------------------------------------------------------------------
# 1. The agent path — a fit-scorer run retires the stale scores it now refuses
#    to compute, instead of walking straight past them.
# ---------------------------------------------------------------------------


class _RecordingEngine:
    def __init__(self, overall: float = 61.0):
        self.scored: list[str] = []
        self._overall = overall

    def score(self, resume_text, job_text):
        self.scored.append(job_text)
        return type("S", (), {"overall": self._overall})()


class _StubRepo:
    def __init__(self, jobs):
        self._jobs = jobs
        self.persisted: list[tuple[str, float]] = []
        self.cleared: list[str] = []

    def iter_scoring_candidates(self, user_id):
        """The scorer's bounded read path (BLOCKER-007) — the real repository
        pages this in keyset batches; the stub yields the same rows."""
        return iter(self._jobs)

    def update_fit_score(self, job_id, fit, ats):
        self.persisted.append((job_id, fit))

    def clear_fit_score(self, job_id):
        self.cleared.append(job_id)

    def advance_status(self, job_id, status, allowed_from=None):
        return None


@pytest.fixture()
def _own_resume(monkeypatch):
    monkeypatch.setattr(
        "app.agents.fit_scorer.require_user_resume_text",
        lambda uid, msg: "a real resume " * 40,
    )


def test_run_clears_a_pre_gate_score_on_a_thin_posting(_own_resume):
    """THE BLOCKER: a job scored BEFORE the gate keeps its score forever."""
    stale = {
        "id": "stale-1",
        "title": "Senior Agile Business Analyst",
        "description": _THIN,
        "requirements": [],
        "fitScore": 76.76,
        "atsScore": 76.76,
    }
    repo = _StubRepo([stale])
    engine = _RecordingEngine()

    result = FitScorerAgent(repository=repo, engine=engine).run("user-1")

    assert repo.cleared == ["stale-1"], (
        "the pre-gate score on an unscorable posting survived a fit-scorer run"
    )
    assert result.cleared_no_evidence == 1
    assert result.skipped_no_evidence == 1
    assert result.scored == 0
    assert repo.persisted == []
    assert engine.scored == [], "an unscorable posting must never reach the engine"


def test_rescore_run_also_clears_instead_of_leaving_the_old_number(_own_resume):
    """``rescore=True`` reaches the scoring branch, which REFUSES the row — the
    refusal must retire the stale number, not leave it standing."""
    stale = {
        "id": "stale-2",
        "title": "Business Architect",
        "description": "",
        "requirements": [],
        "fitScore": 74.63,
        "atsScore": 74.63,
    }
    repo = _StubRepo([stale])

    result = FitScorerAgent(repository=repo, engine=_RecordingEngine()).run(
        "user-1", rescore=True
    )

    assert repo.cleared == ["stale-2"]
    assert result.cleared_no_evidence == 1
    assert repo.persisted == []


def test_a_row_with_real_evidence_keeps_its_score(_own_resume):
    """Idempotence/safety: remediation touches ONLY evidence-free rows."""
    good = {
        "id": "good-1",
        "title": "Business Analyst",
        "description": _RICH,
        "requirements": [],
        "fitScore": 54.2,
        "atsScore": 54.2,
    }
    repo = _StubRepo([good])

    result = FitScorerAgent(repository=repo, engine=_RecordingEngine()).run("user-1")

    assert repo.cleared == []
    assert result.cleared_no_evidence == 0
    assert repo.persisted == []  # already scored, not rescored


def test_a_cleared_row_is_re_derived_once_it_carries_real_evidence(_own_resume):
    """Requirement 3: clearing is not a dead end. When the description is later
    backfilled (the SmartRecruiters case, db30f33), the next run scores it."""
    backfilled = {
        "id": "was-thin-1",
        "title": "Senior Solutions Architect",
        "description": _RICH,
        "requirements": [],
        "fitScore": None,  # cleared by an earlier remediation
        "atsScore": None,
    }
    repo = _StubRepo([backfilled])

    result = FitScorerAgent(repository=repo, engine=_RecordingEngine(63.5)).run("user-1")

    assert repo.persisted == [("was-thin-1", 63.5)]
    assert result.scored == 1
    assert repo.cleared == []


# ---------------------------------------------------------------------------
# 2. The migration path — real rows, real database.
# ---------------------------------------------------------------------------


def _seed_job(conn, user_id: str, description: str, fit: float | None) -> str:
    job_id = uuid.uuid4().hex[:25]
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description",'
            '"requirements","source","sourceUrl","status","fitScore","atsScore",'
            '"createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::"JobStatus",%s,%s,NOW(),NOW())',
            (
                job_id,
                user_id,
                "Senior Business Analyst",
                "Acme",
                description,
                "[]",
                "seek-alert",
                f"https://example.com/job/{job_id}",
                "screening",
                fit,
                fit,
            ),
        )
    conn.commit()
    return job_id


def _score_of(conn, job_id: str) -> tuple:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "fitScore", "atsScore" FROM "Job" WHERE "id" = %s', (job_id,)
        )
        return cur.fetchone()


def test_migration_clears_only_the_evidence_free_scores(
    client, auth_headers, test_user_id, db_session
):
    from app.services.fit_score_remediation import remediate_unscorable_fit_scores

    thin = _seed_job(db_session, test_user_id, _THIN, 76.76)
    empty = _seed_job(db_session, test_user_id, "", 74.63)
    rich = _seed_job(db_session, test_user_id, _RICH, 54.2)
    unscored_thin = _seed_job(db_session, test_user_id, _THIN, None)

    outcome = remediate_unscorable_fit_scores()

    assert outcome.before_scored_without_evidence == 2, outcome
    assert outcome.cleared == 2, outcome
    assert outcome.after_scored_without_evidence == 0, outcome

    assert _score_of(db_session, thin) == (None, None)
    assert _score_of(db_session, empty) == (None, None)
    assert _score_of(db_session, rich) == (54.2, 54.2)
    assert _score_of(db_session, unscored_thin) == (None, None)


def test_migration_is_idempotent(client, auth_headers, test_user_id, db_session):
    from app.services.fit_score_remediation import remediate_unscorable_fit_scores

    _seed_job(db_session, test_user_id, _THIN, 76.76)
    rich = _seed_job(db_session, test_user_id, _RICH, 54.2)

    first = remediate_unscorable_fit_scores()
    second = remediate_unscorable_fit_scores()

    assert first.cleared == 1
    assert second.cleared == 0, "a second sweep must find nothing left to do"
    assert second.before_scored_without_evidence == 0
    assert second.after_scored_without_evidence == 0
    assert _score_of(db_session, rich) == (54.2, 54.2)


def test_migration_can_be_scoped_to_one_user(
    client, auth_headers, test_user_id, db_session
):
    """Scoping exists so a per-user run can never touch another user's rows."""
    from app.repositories.user import UserRepository
    from app.security import hash_password
    from app.services.fit_score_remediation import remediate_unscorable_fit_scores

    other = UserRepository().create(
        f"other-{uuid.uuid4().hex[:8]}@example.com", hash_password("Sup3rSecret")
    )
    mine = _seed_job(db_session, test_user_id, _THIN, 70.0)
    theirs = _seed_job(db_session, other["id"], _THIN, 71.0)

    outcome = remediate_unscorable_fit_scores(user_id=test_user_id)

    assert outcome.cleared == 1
    assert _score_of(db_session, mine) == (None, None)
    assert _score_of(db_session, theirs) == (71.0, 71.0)


def test_rescorable_rows_are_reported_not_silently_left(
    client, auth_headers, test_user_id, db_session
):
    """Requirement 3, at the migration layer: rows with REAL evidence and no
    score are counted, so 'nothing was re-derived' can never hide."""
    from app.services.fit_score_remediation import (
        count_rescorable,
        remediate_unscorable_fit_scores,
    )

    _seed_job(db_session, test_user_id, _RICH, None)
    _seed_job(db_session, test_user_id, _RICH, None)
    _seed_job(db_session, test_user_id, _THIN, 76.76)

    remediate_unscorable_fit_scores()

    # The two rich unscored rows are re-derivable; the cleared thin row is not.
    assert count_rescorable() == 2


# ---------------------------------------------------------------------------
# 3. It runs BY ITSELF — nobody has to remember a script.
# ---------------------------------------------------------------------------


def test_application_startup_remediates_without_anyone_running_anything(
    client, auth_headers, test_user_id, db_session
):
    """Pinned through the real boot path (``TestClient(create_app())`` →
    ``app.main._lifespan``), not by calling the migration directly."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    thin = _seed_job(db_session, test_user_id, _THIN, 76.76)
    rich = _seed_job(db_session, test_user_id, _RICH, 54.2)
    assert _score_of(db_session, thin) == (76.76, 76.76)

    with TestClient(create_app()) as booted:
        assert booted.get("/health").status_code == 200

    assert _score_of(db_session, thin) == (None, None), (
        "application startup did not remediate the pre-gate scores"
    )
    assert _score_of(db_session, rich) == (54.2, 54.2)


def test_a_remediation_failure_at_startup_cannot_take_the_api_down(monkeypatch):
    """Availability guard, mirroring BLOCKER-001: a broken remediation must be
    logged and skipped, never crash-loop the service."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    def _boom(*_a, **_kw):
        raise RuntimeError("database went away mid-sweep")

    monkeypatch.setattr(
        "app.services.fit_score_remediation.remediate_unscorable_fit_scores", _boom
    )
    with TestClient(create_app()) as booted:
        assert booted.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# 4. The READ path — found while remediating the write path.
#
# ``GET /jobs/{id}/insights`` runs the ATS engine on demand, with its own copy
# of the job-text builder and NO evidence gate. Remediating the database alone
# would have left the detail panel still showing a ~75% "Role Alignment" for an
# empty posting whose card now honestly shows no score — the same fabricated
# number, on the surface a user actually reads, and now self-contradictory.
# ---------------------------------------------------------------------------


def test_insights_refuses_to_score_a_posting_with_no_evidence(
    client, auth_headers, test_user_id, db_session
):
    from conftest import seed_own_resume

    seed_own_resume(client, auth_headers)
    thin = _seed_job(db_session, test_user_id, _THIN, None)

    resp = client.get(f"/jobs/{thin}/insights", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["scored"] is False, body
    assert body["overall"] == 0
    assert body["matchedSkills"] == []
    assert body["missingSkills"] == []
    assert body["needsResume"] is False, "the user HAS a resume — the posting is the problem"
    by_label = {d["label"]: d for d in body["dimensions"]}
    for label in ("Technical Skills", "Role Alignment", "North Star Align"):
        assert by_label[label]["degraded"] is True, by_label[label]
    # ...and the résumé-independent facts are still measured honestly.
    assert by_label["Location Match"]["degraded"] is False
    assert any("description" in r["label"].lower() for r in body["riskSignals"]), body


def test_insights_still_scores_a_posting_that_carries_real_evidence(
    client, auth_headers, test_user_id, db_session
):
    from conftest import seed_own_resume

    seed_own_resume(client, auth_headers)
    rich = _seed_job(db_session, test_user_id, _RICH, None)

    body = client.get(f"/jobs/{rich}/insights", headers=auth_headers).json()

    assert body["scored"] is True, body
    assert body["overall"] > 0


# ---------------------------------------------------------------------------
# 5. Ranking — the actual user-visible harm.
# ---------------------------------------------------------------------------


def test_a_thin_posting_no_longer_outranks_a_real_one_on_the_board(
    client, auth_headers, test_user_id, db_session
):
    from app.services.fit_score_remediation import remediate_unscorable_fit_scores

    _seed_job(db_session, test_user_id, _THIN, 76.76)
    _seed_job(db_session, test_user_id, _RICH, 54.2)

    before = client.get("/jobs?sort=fitScore&include_stale=true", headers=auth_headers)
    assert before.json()[0]["fitScore"] == 76.76  # the harm, reproduced

    remediate_unscorable_fit_scores()

    after = client.get("/jobs?sort=fitScore&include_stale=true", headers=auth_headers)
    top = after.json()[0]
    assert top["fitScore"] == 54.2, [
        (j["fitScore"], len(j["description"])) for j in after.json()
    ]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "Job" WHERE "userId" = %s AND "fitScore" '
                'IS NOT NULL AND length("description") < 200',
                (test_user_id,),
            )
            assert cur.fetchone()[0] == 0
