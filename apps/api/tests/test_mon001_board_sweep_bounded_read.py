"""MON-001 — board-sweep target selection must be a BOUNDED read, or it 500s.

Evidence (MONITORING-LEDGER.md, MON-001): prod ``worker.log`` shows
``psycopg2.errors.QueryCanceled: canceling statement due to statement
timeout`` from the arq ``board_sweep_user`` task — 100% failure for one
user's sweep, on every ~10-minute cron tick.

RCA (this read, ``board_sweep._next_target`` / ``_saturated_job_ids``):
both issue ONE statement that selects candidate ``"Job"`` rows (status +
``NOT EXISTS`` Application) and filters/orders them using a CORRELATED
subquery evaluated per candidate row — ``_COVER_RUN_PRODUCED_NO_LETTER``
wrapped by ``_SINCE_LAST_SUCCESS_OR_CLEAR``, itself two MORE correlated
subqueries against ``"AgentRun"`` with an unindexed JSONB text extraction
(``r."input"->>'job_id'``). Postgres cannot apply ``_next_target``'s
``ORDER BY ... LIMIT 1`` until every matching candidate row has paid for that
subquery, and ``_saturated_job_ids`` carries no ``LIMIT`` at all. Cost scales
with (eligible Job rows) x (AgentRun rows for that user) — exactly the shape
BLOCKER-007 already fixed once for ``FitScorerAgent``'s read
(``apps/api/tests/test_blocker007_fit_scorer_read_path.py``): "the board's
projection: N columns plus per-row correlated subqueries and no LIMIT" is the
same disease as here.

This suite mimics the BLOCKER-007 precedent's method exactly: a timeout
itself is not reproducible against a small test database, so these tests
assert the STRUCTURAL property that prevents it — the AgentRun correlation
must not be embedded, unbounded, inside the statement that also has to
satisfy candidate selection + ordering for the WHOLE eligible set. The fix
must move that filtering into a separately bounded step (a pre-limited
candidate batch, a single aggregated GROUP BY, or equivalent) — HOW it does
that is left to the implementation; THAT it does not keep today's shape is
what these tests pin down.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any

import pytest

from app.workers import board_sweep


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(conn, user_id: str, *, status: str = "screening",
              fit: float | None = 80.0, title: str = "Engineer") -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, title, "Acme", "Build.", "greenhouse",
             f"https://example.com/job/{job_id}", status, fit),
        )
    conn.commit()
    return job_id


def _seed_cover_run(conn, user_id: str, job_id: str, *, status: str,
                     output: dict | None = None, minutes_ago: float = 0.0) -> str:
    run_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "AgentRun" '
            '("id","userId","agentName","status","input","output","createdAt","startedAt") '
            "VALUES (%s,%s,'coverLetter',%s::\"AgentRunStatus\",%s,%s,"
            "NOW() - (%s || ' minutes')::interval, NOW())",
            (run_id, user_id, status, json.dumps({"job_id": job_id}),
             json.dumps(output) if output is not None else None, minutes_ago),
        )
    conn.commit()
    return run_id


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
def sweep_sql(monkeypatch) -> list[str]:
    """Records every statement issued through ``app.db.get_connection`` —
    ``board_sweep`` imports it lazily (``from app.db import get_connection``)
    inside each function body, so patching the module attribute is picked up
    fresh on every call."""
    from app import db as db_module

    real_get_connection = db_module.get_connection
    sink: list[str] = []

    @contextlib.contextmanager
    def _recording():
        with real_get_connection() as conn:
            yield _RecordingConnection(conn, sink)

    monkeypatch.setattr(db_module, "get_connection", _recording)
    return sink


def _job_selects(sink: list[str]) -> list[str]:
    return [
        stmt
        for stmt in sink
        if stmt.lstrip().upper().startswith("SELECT") and 'FROM "Job"' in stmt
    ]


def _seed_realistic_board(conn, user_id: str, *, eligible_jobs: int = 15,
                           runs_per_job: int = 4) -> list[str]:
    """A user with a non-trivial eligible board AND a real AgentRun history —
    the shape production has at scale (many candidate jobs, many past
    coverLetter attempts) that makes the correlated subquery expensive."""
    job_ids = [
        _seed_job(conn, user_id, status="screening", fit=50.0 + index)
        for index in range(eligible_jobs)
    ]
    for job_id in job_ids:
        for run_index in range(runs_per_job):
            _seed_cover_run(
                conn, user_id, job_id, status="completed",
                output={"cover_letter_id": None, "coverLetterUnavailable": True,
                        "reason": "['x']", "message": "withheld"},
                minutes_ago=float(run_index * 5),
            )
    return job_ids


def test_next_target_query_does_not_correlate_agentrun_per_candidate_row(
    db_session, user_id, sweep_sql
):
    """FAILS on the pre-fix code: ``_next_target`` issues ONE statement that
    selects/orders the FULL eligible ``"Job"`` set while filtering each
    candidate through a correlated ``"AgentRun"`` subquery — cost scales with
    (eligible jobs) x (that user's AgentRun rows), which is exactly what the
    hosted 5s statement_timeout kills at production volume (MON-001).

    The fix must resolve candidates through a statement that does not embed
    this correlation — e.g. a pre-limited candidate batch or a separate,
    already-bounded lookup — so the Job-selecting statement's cost no longer
    scales with the user's total AgentRun history.
    """
    _seed_realistic_board(db_session, user_id, eligible_jobs=15, runs_per_job=4)

    sweep_sql.clear()
    board_sweep._next_target(user_id, set())

    selects = _job_selects(sweep_sql)
    assert selects, "_next_target must read candidates through a Job SELECT"
    offenders = [s for s in selects if 'FROM "AgentRun"' in s]
    assert not offenders, (
        "_next_target's Job-selecting statement must not embed a correlated "
        "AgentRun subquery evaluated per candidate row (MON-001 — this is the "
        "shape that blows the hosted 5s statement timeout at production "
        f"volume); offending statement(s): {offenders}"
    )


def test_saturated_job_ids_query_does_not_correlate_agentrun_per_candidate_row(
    db_session, user_id, sweep_sql
):
    """FAILS on the pre-fix code for the same reason, on the sibling read.

    ``_saturated_job_ids`` is called by ``sweep_user_stretch`` on every tick
    where ``_next_target`` returns ``None`` (board exhausted or all remaining
    jobs failure-suppressed) — the common steady-state case for a heavily
    autopiloted board — and it carries NO LIMIT at all in addition to the
    same per-row AgentRun correlation, making it the more severe of the two.
    """
    _seed_realistic_board(db_session, user_id, eligible_jobs=15, runs_per_job=4)

    sweep_sql.clear()
    board_sweep._saturated_job_ids(user_id, set())

    selects = _job_selects(sweep_sql)
    assert selects, "_saturated_job_ids must read candidates through a Job SELECT"
    offenders = [s for s in selects if 'FROM "AgentRun"' in s]
    assert not offenders, (
        "_saturated_job_ids's Job-selecting statement must not embed a "
        "correlated AgentRun subquery evaluated per candidate row (MON-001); "
        f"offending statement(s): {offenders}"
    )


def test_next_target_still_finds_the_correct_job_across_a_realistic_board(
    db_session, user_id, sweep_sql
):
    """Anti-regression / honesty guard for whatever bounded shape the fix
    takes: bounding the read must never silently drop the genuinely eligible,
    non-saturated job. One job (seeded LAST, so it is not first in id/creation
    order) has zero AgentRun history and must still be the selected target
    among many failure-saturated peers.
    """
    _seed_realistic_board(db_session, user_id, eligible_jobs=12, runs_per_job=4)
    winner = _seed_job(db_session, user_id, status="screening", fit=99.0,
                        title="The One True Match")

    target = board_sweep._next_target(user_id, set())
    assert target is not None, "a genuinely eligible, non-saturated job exists"
    assert target["job_id"] == winner, (
        f"expected the non-saturated highest-fitScore job {winner!r} to win, "
        f"got {target!r}"
    )


def _set_fit(conn, job_id: str, fit: float) -> None:
    with conn.cursor() as cur:
        cur.execute('UPDATE "Job" SET "fitScore" = %s WHERE "id" = %s',
                    (fit, job_id))
    conn.commit()


def test_candidate_walk_pages_and_resumes_on_the_keyset_without_gaps_or_dupes(
    db_session, user_id, sweep_sql, monkeypatch
):
    """MULTI-PAGE keyset resumption — the property ``_CANDIDATE_PAGE_SIZE``
    exists for, and the one a single-page seed can never observe.

    The other tests in this file seed well under the real 500-row page size,
    so they only ever exercise the FIRST page: a walk that dropped its cursor,
    re-read page 1 forever, or stopped after one page would pass them all.
    Shrinking the constant (rather than seeding 500+ rows, which would put a
    multi-minute insert into every run of this suite) forces the loop to
    round-trip four times over ten eligible jobs and pins the three things the
    ``id > last_id`` cursor has to deliver: every eligible job appears EXACTLY
    once, in ascending id order, and each statement still carries the bound.
    """
    monkeypatch.setattr(board_sweep, "_CANDIDATE_PAGE_SIZE", 3)
    job_ids = [
        _seed_job(db_session, user_id, status="screening", fit=50.0 + index)
        for index in range(10)
    ]

    sweep_sql.clear()
    pages = list(board_sweep._iter_candidate_pages(user_id, set()))

    assert [len(page) for page in pages] == [3, 3, 3, 1], (
        "ten eligible jobs at a page size of 3 must be walked as 4 bounded "
        f"pages, got page sizes {[len(page) for page in pages]}"
    )
    walked = [row["id"] for page in pages for row in page]
    assert walked == sorted(job_ids), (
        "the keyset walk must yield every eligible job exactly once in "
        f"ascending id order; got {len(walked)} rows "
        f"({len(set(walked))} distinct) for {len(job_ids)} eligible jobs"
    )

    selects = _job_selects(sweep_sql)
    assert len(selects) == len(pages) + 1, (
        "each page is one bounded statement, plus the terminating empty read; "
        f"got {len(selects)} Job SELECTs for {len(pages)} pages"
    )
    assert all("LIMIT 3" in stmt for stmt in selects), (
        "every page statement must carry the per-statement row bound; "
        f"got {selects}"
    )


def test_next_target_selects_a_winner_that_lives_beyond_the_first_page(
    db_session, user_id, sweep_sql, monkeypatch
):
    """Bounded must not mean truncated ACROSS pages either: the best-fit job
    is forced onto the LAST page (highest id ⇒ last in the keyset order), so a
    walk that only ever consumed page 1 would return a worse job and fail.
    """
    monkeypatch.setattr(board_sweep, "_CANDIDATE_PAGE_SIZE", 3)
    job_ids = [
        _seed_job(db_session, user_id, status="screening", fit=50.0 + index)
        for index in range(10)
    ]
    winner = max(job_ids)
    _set_fit(db_session, winner, 99.0)

    sweep_sql.clear()
    target = board_sweep._next_target(user_id, set())

    assert target is not None, "ten eligible, non-saturated jobs exist"
    assert target["job_id"] == winner, (
        f"expected the highest-fitScore job {winner!r} — deliberately the "
        f"LAST id, i.e. on the final page — to win, got {target!r}"
    )
    assert len([s for s in _job_selects(sweep_sql) if "LIMIT 3" in s]) > 1, (
        "the target must have been chosen over a genuinely multi-page walk"
    )
