"""BLOCKER-007 — the fit-scorer's job read must be BOUNDED, or it 500s.

MEASURED IN PRODUCTION (read-only probe, 2026-08-09, schema ``aether``):

    owner account "Job" rows                                 5848 (1116 unscored)
    hosted Postgres statement_timeout                        5s
    FitScorerAgent's read (JobRepository.list_by_user)       CANCELED at 5005.9 ms
      ... same statement with the timeout raised to 180s     completed in 5701.5 ms
    narrow keyset-paged read, 500-row batches                12 batches,
                                                             slowest batch 31.1 ms,
                                                             180.7 ms for all 5848

``list_by_user`` is the board's READ projection: the full column set plus THREE
correlated subqueries evaluated per row (``tailoredResumeId``,
``tailoredResumeStatus``, ``autopilotSuppressedUntil`` — the last one itself
containing three more correlated scans of ``AgentRun``), with NO ``LIMIT``. The
fit-scorer uses none of those three values; it reads only
``id``/``title``/``description``/``requirements``/``fitScore``/``atsScore``.

So every discovery cycle since the catalog crossed the threshold has died the
same way — 66 consecutive 500s over 32.5 hours, zero jobs scored:

    psycopg2.errors.QueryCanceled: canceling statement due to statement timeout
      app/agents/fit_scorer.py:74 -> app/repositories/job.py:380

These tests assert the STRUCTURAL property that prevents it, because a timeout
itself is not reproducible on a small test database: the read path must be
bounded per statement and must not carry the per-row subqueries it never reads.
The batching must also be HONEST — completeness across batches is asserted
separately, so "bounded" can never be satisfied by silently dropping rows.
"""
from __future__ import annotations

import contextlib
import uuid
from typing import Any

import pytest

_HEAVY_SUBQUERY_MARKERS = (
    "tailoredResumeId",
    "tailoredResumeStatus",
    "autopilotSuppressedUntil",
)

#: Comfortably over ``MIN_SCORABLE_CHARS`` (200) so every seeded row passes the
#: v5 evidence gate and is genuinely scored — otherwise "all rows scored" would
#: be vacuously true.
_REAL_DESCRIPTION = (
    "We are seeking a senior Python engineer to design, build and operate "
    "large-scale data pipelines across our payments platform. You will partner "
    "with product and engineering, run stakeholder workshops, define acceptance "
    "criteria, and support delivery through to release. Experience with agile "
    "delivery, PostgreSQL and platform modernisation is essential."
)


class _RecordingCursor:
    """Delegating psycopg2 cursor wrapper that records every SQL string."""

    def __init__(self, cursor: Any, sink: list[str]) -> None:
        self._cursor = cursor
        self._sink = sink

    def execute(self, query: Any, vars: Any = None) -> Any:  # noqa: A002
        self._sink.append(query if isinstance(query, str) else str(query))
        return self._cursor.execute(query, vars)

    def __enter__(self) -> "_RecordingCursor":
        self._cursor.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self._cursor.__exit__(*exc)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._cursor, item)


class _RecordingConnection:
    def __init__(self, conn: Any, sink: list[str]) -> None:
        self._conn = conn
        self._sink = sink

    def cursor(self, *args: Any, **kwargs: Any) -> _RecordingCursor:
        return _RecordingCursor(self._conn.cursor(*args, **kwargs), self._sink)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._conn, item)


@pytest.fixture()
def job_sql(monkeypatch) -> list[str]:
    """Records every statement ``JobRepository`` issues, against the real DB."""
    from app.repositories import job as job_repo

    real_get_connection = job_repo.get_connection
    sink: list[str] = []

    @contextlib.contextmanager
    def _recording():
        with real_get_connection() as conn:
            yield _RecordingConnection(conn, sink)

    monkeypatch.setattr(job_repo, "get_connection", _recording)
    return sink


class _StubEngine:
    """Deterministic stand-in for the ATS engine — this suite is about SQL."""

    def __init__(self) -> None:
        self.scored: list[str] = []

    def score(self, resume_text: str, job_text: str) -> Any:
        self.scored.append(job_text)
        return type("S", (), {"overall": 61.5})()


def _seed_user(client, auth_headers) -> str:
    from conftest import seed_own_resume

    seed_own_resume(client, auth_headers)
    me = client.get("/auth/me", headers=auth_headers)
    assert me.status_code == 200, me.text
    return me.json()["id"]


def _seed_scorable_jobs(user_id: str, count: int) -> list[str]:
    from app.repositories.job import JobRepository

    repo = JobRepository()
    ids: list[str] = []
    for index in range(count):
        row = repo.create(
            user_id,
            {
                "title": f"Senior Python Engineer {index}",
                "company": "Acme Payments",
                "location": "Sydney",
                "remote": False,
                "description": _REAL_DESCRIPTION,
                "requirements": ["python", "postgresql", "agile"],
                "source": "fixture",
                "sourceUrl": f"https://example.test/job/{uuid.uuid4().hex}",
            },
        )
        ids.append(row["id"])
    return ids


def _job_selects(sink: list[str]) -> list[str]:
    return [
        stmt
        for stmt in sink
        if stmt.lstrip().upper().startswith("SELECT") and 'FROM "Job"' in stmt
    ]


def _outer_query(sql: str) -> str:
    """``sql`` with every parenthesised group removed.

    Needed because the board projection's correlated subqueries each carry
    their own ``LIMIT 1`` (``ORDER BY r."version" DESC LIMIT 1``), so a naive
    substring search for ``LIMIT`` calls the unbounded outer query bounded.
    Only a ``LIMIT`` at depth 0 bounds the number of rows the statement scans.
    """
    out: list[str] = []
    depth = 0
    for char in sql:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(char)
    return "".join(out)


def test_fit_scorer_read_is_bounded_per_statement(client, auth_headers, job_sql):
    """Every ``Job`` SELECT the fit-scorer issues must carry a LIMIT.

    FAILS on the pre-fix code because ``JobRepository.list_by_user`` emits one
    unbounded ``SELECT ... FROM "Job" j WHERE "userId" = %s ORDER BY ...`` whose
    cost grows without limit with the catalog — the statement production kills
    at 5 s.
    """
    from app.agents.fit_scorer import FitScorerAgent
    from app.repositories.job import JobRepository

    user_id = _seed_user(client, auth_headers)
    _seed_scorable_jobs(user_id, 3)

    job_sql.clear()
    FitScorerAgent(repository=JobRepository(), engine=_StubEngine()).run(user_id)

    selects = _job_selects(job_sql)
    assert selects, "the fit-scorer must read jobs through JobRepository"
    unbounded = [s for s in selects if " LIMIT " not in _outer_query(s).upper()]
    assert not unbounded, (
        "the fit-scorer's job read must be bounded per statement (a LIMIT on "
        f"the OUTER query, not inside a subquery); {len(unbounded)} unbounded "
        f"SELECT(s) found: {unbounded}"
    )


def test_fit_scorer_read_omits_the_board_only_correlated_subqueries(
    client, auth_headers, job_sql
):
    """The three per-row correlated subqueries are board-UI payload only.

    ``FitScorerAgent.run`` reads exactly ``id``, ``fitScore``, ``atsScore`` and
    the evidence text (``title``/``description``/``requirements``); it never
    touches ``tailoredResumeId``, ``tailoredResumeStatus`` or
    ``autopilotSuppressedUntil``. Paying for them per row is the bulk of the
    5.7 s measured on production.
    """
    from app.agents.fit_scorer import FitScorerAgent
    from app.repositories.job import JobRepository

    user_id = _seed_user(client, auth_headers)
    _seed_scorable_jobs(user_id, 3)

    job_sql.clear()
    FitScorerAgent(repository=JobRepository(), engine=_StubEngine()).run(user_id)

    offenders = [
        stmt
        for stmt in _job_selects(job_sql)
        if any(marker in stmt for marker in _HEAVY_SUBQUERY_MARKERS)
    ]
    assert not offenders, (
        "the fit-scorer must not request the per-row correlated subqueries it "
        f"never reads {_HEAVY_SUBQUERY_MARKERS}; offending SELECT(s): {offenders}"
    )


def test_fit_scorer_does_not_use_the_board_list_query(client, auth_headers):
    """Anti-regression: the scorer must not fall back to ``list_by_user``."""
    from app.agents.fit_scorer import FitScorerAgent
    from app.repositories.job import JobRepository

    user_id = _seed_user(client, auth_headers)
    _seed_scorable_jobs(user_id, 2)

    repo = JobRepository()

    def _forbidden(*args: Any, **kwargs: Any):
        raise AssertionError(
            "FitScorerAgent must not read through JobRepository.list_by_user — "
            "that is the unbounded board projection (BLOCKER-007)."
        )

    repo.list_by_user = _forbidden  # type: ignore[method-assign]
    FitScorerAgent(repository=repo, engine=_StubEngine()).run(user_id)


def test_batched_read_is_honest_every_job_is_still_visited(
    client, auth_headers, job_sql, monkeypatch
):
    """Bounding the read must never become a silent truncation.

    With the batch size forced to 2 and 5 scorable jobs seeded, the scorer must
    issue MORE THAN ONE bounded read and end with all 5 rows scored — i.e. the
    batching walks the whole catalog inside a single run, it does not stop at
    the first page.
    """
    from app.agents.fit_scorer import FitScorerAgent
    from app.repositories import job as job_repo
    from app.repositories.job import JobRepository

    monkeypatch.setattr(job_repo, "_SCORING_BATCH_SIZE", 2)

    user_id = _seed_user(client, auth_headers)
    seeded = _seed_scorable_jobs(user_id, 5)

    job_sql.clear()
    engine = _StubEngine()
    result = FitScorerAgent(repository=JobRepository(), engine=engine).run(user_id)

    assert result.errors == [], result.errors
    assert result.scored == len(seeded), (
        f"expected all {len(seeded)} scorable jobs scored, got {result.scored} — "
        "a bounded read must not silently drop rows"
    )
    assert len(engine.scored) == len(seeded)
    assert len(_job_selects(job_sql)) > 1, (
        "with a batch size of 2 and 5 jobs the scorer must page through several "
        "bounded reads, not issue a single one"
    )

    persisted = JobRepository().list_by_user(user_id)
    assert {row["id"] for row in persisted} == set(seeded)
    assert all(row["fitScore"] is not None for row in persisted), persisted
