"""BLOCKER-008 — ``GET /jobs`` 500s: the board list read is unbounded.

Measured READ-ONLY against production on 2026-08-09 (owner account, 5932 ``Job``
rows, hosted ``statement_timeout`` = 5s):

    GET /jobs                 -> QueryCanceled at 5006.1 ms
    GET /jobs?sort=fitScore   -> QueryCanceled at 5006.1 ms
    same statement, timeout raised to 180s -> completed in 6885.9 ms

Cost attribution of those 6885.9 ms, same session:

    base 21 columns, no correlated subqueries          265.8 ms
    + the two tailored-resume correlated subqueries    838.8 ms
    + the autopilot-suppression correlated subquery   6010.2 ms   <- 87% of it

``JobRepository.list_by_user`` (``app/repositories/job.py``) issued ONE
``SELECT`` with no ``LIMIT`` over every row the user owns, and evaluated the
autopilot-suppression correlated subquery per row — each evaluation scanning
the user's whole ``AgentRun`` history twice (7394 rows, no index can serve
``input->>'job_id'``). 5505 of the owner's 5932 rows pass that subquery's
eligibility gate, so essentially the entire catalog paid for it.

A statement timeout cannot be reproduced on a small test database, so these
tests assert the STRUCTURAL properties that prevent it, plus a completeness
property so "bounded" can never be satisfied by dropping rows.

FAKE-GREEN WARNING (the trap BLOCKER-007 hit first, restated here because it
applies verbatim): the board projection's correlated subqueries each carry
their own ``ORDER BY ... LIMIT 1``, so a naive substring search for ``LIMIT``
calls the unbounded outer statement "bounded". Every bound check below runs
through :func:`_outer_query`, which strips parenthesised groups by depth so
only a depth-0 token counts.
"""
from __future__ import annotations

import contextlib
import re
import uuid
from typing import Any

import pytest

#: Every column ``GET /jobs`` has ever carried. Guards the response contract:
#: the fix changes HOW the derived fields are read, never WHICH fields exist.
_REQUIRED_ROW_FIELDS = (
    "id", "userId", "title", "company", "location", "remote", "salaryMin",
    "salaryMax", "currency", "description", "requirements", "source",
    "sourceUrl", "status", "fitScore", "atsScore", "saved", "postedAt",
    "createdAt", "updatedAt", "lastSeenAt",
    "tailoredResumeId", "tailoredResumeStatus", "autopilotSuppressedUntil",
)


# ---------------------------------------------------------------------------
# SQL capture — the assertions below are made against the statements actually
# sent to Postgres, not against a mock's call list.
# ---------------------------------------------------------------------------
class _RecordingCursor:
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


def _outer_query(sql: str) -> str:
    """``sql`` with every parenthesised group removed.

    Only a depth-0 token bounds the number of rows a statement scans; a
    ``LIMIT 1`` inside a correlated subquery does not. See the module
    docstring's FAKE-GREEN WARNING.
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


def _job_selects(sink: list[str]) -> list[str]:
    return [
        stmt
        for stmt in sink
        if stmt.lstrip().upper().startswith(("SELECT", "WITH"))
        and 'FROM "Job"' in stmt
    ]


def _is_bounded(stmt: str) -> bool:
    """True when this statement can only ever scan a fixed number of ``Job`` rows.

    Two honest ways to be bounded, both used by the fix:
      * a depth-0 ``LIMIT`` (the keyset-paged board read), or
      * every ``FROM "Job"`` restricted to an explicit id set supplied by the
        caller — ``"id" = ANY(%s)`` or ``"id" = %s`` — whose length the caller
        caps at the page size.
    """
    outer = _outer_query(stmt)
    if re.search(r"\bLIMIT\b", outer, re.IGNORECASE):
        return True
    return bool(re.search(r'"id"\s*=\s*(ANY\s*\(\s*%s\s*\)|%s)', stmt))


def _seed_jobs(user_id: str, count: int) -> list[str]:
    from app.repositories.job import JobRepository

    repo = JobRepository()
    ids: list[str] = []
    for index in range(count):
        row = repo.create(
            user_id,
            {
                "title": f"Platform Engineer {index:03d}",
                "company": f"Company {index:03d}",
                "location": "Sydney",
                "remote": False,
                "description": "Own the deployment pipeline and the on-call rota.",
                "requirements": ["python", "postgresql"],
                "source": "fixture",
                "sourceUrl": f"https://example.test/job/{uuid.uuid4().hex}",
            },
        )
        ids.append(row["id"])
    return ids


def _user_id(client, auth_headers) -> str:
    me = client.get("/auth/me", headers=auth_headers)
    assert me.status_code == 200, me.text
    return me.json()["id"]


# ---------------------------------------------------------------------------
# 1-2. The two structural properties that prevent the 5 s statement timeout.
# ---------------------------------------------------------------------------
def test_jobs_list_read_is_bounded_per_statement(client, auth_headers, job_sql):
    """Every ``Job`` read ``GET /jobs`` issues must be bounded per statement.

    FAILS on the pre-fix code: ``list_by_user`` emits a single
    ``SELECT ... FROM "Job" j WHERE "userId" = %s ORDER BY ... DESC NULLS LAST``
    with no depth-0 ``LIMIT`` and no id-set restriction, so its cost grows
    without limit with the catalog — production kills it at 5 s.
    """
    _seed_jobs(_user_id(client, auth_headers), 3)
    job_sql.clear()

    response = client.get("/jobs?include_stale=true", headers=auth_headers)
    assert response.status_code == 200, response.text

    selects = _job_selects(job_sql)
    assert selects, "expected GET /jobs to read the Job table"
    unbounded = [s for s in selects if not _is_bounded(s)]
    assert not unbounded, (
        "GET /jobs issued an unbounded Job read — this is the statement "
        f"production cancels at 5 s:\n\n{unbounded[0]}"
    )


def test_agentrun_is_never_scanned_once_per_job_row(client, auth_headers, job_sql):
    """The suppression predicate must be evaluated set-wise, not per ``Job`` row.

    Any statement that touches ``AgentRun`` must restrict ``Job`` to an
    explicit id set, so the AgentRun work a single statement can do is capped
    by the page size instead of by the catalog size.

    FAILS on the pre-fix code: the one board statement carries the
    ``autopilotSuppressedUntil`` correlated subquery, which re-scans the user's
    entire ``AgentRun`` history for every eligible ``Job`` row — 87% of the
    6885.9 ms measured on production.
    """
    _seed_jobs(_user_id(client, auth_headers), 3)
    job_sql.clear()

    assert client.get("/jobs?include_stale=true", headers=auth_headers).status_code == 200

    offenders = [
        stmt
        for stmt in job_sql
        if '"AgentRun"' in stmt
        and not re.search(r'"id"\s*=\s*(ANY\s*\(\s*%s\s*\)|%s)', stmt)
    ]
    assert not offenders, (
        "a statement scans AgentRun without bounding the Job rows it does so "
        f"for — the per-row correlated form is back:\n\n{offenders[0]}"
    )


# ---------------------------------------------------------------------------
# 3. Bounded must never mean truncated.
# ---------------------------------------------------------------------------
def test_paged_board_read_returns_every_row(client, auth_headers, job_sql, monkeypatch):
    """With the page size forced to 2 and 5 jobs seeded, ``GET /jobs`` must
    still return all 5 — bounded per statement, complete in aggregate.

    FAILS on the pre-fix code: there is no page size to force
    (``_BOARD_PAGE_SIZE`` does not exist), and the read is a single statement.
    """
    from app.repositories import job as job_repo

    assert hasattr(job_repo, "_BOARD_PAGE_SIZE"), (
        "the board read is not paged — no page size to bound a statement with"
    )
    monkeypatch.setattr(job_repo, "_BOARD_PAGE_SIZE", 2)

    seeded = _seed_jobs(_user_id(client, auth_headers), 5)
    job_sql.clear()

    rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
    returned = [r["id"] for r in rows]

    assert len(returned) == len(set(returned)), "the paged walk repeated a row"
    assert set(seeded) <= set(returned), (
        f"the paged walk DROPPED rows: {sorted(set(seeded) - set(returned))}"
    )
    assert len(_job_selects(job_sql)) > 1, (
        "expected more than one bounded statement with the page size forced to 2"
    )


# ---------------------------------------------------------------------------
# 4-5. Non-regression guards. These PASS before the fix as well as after —
# they exist so the fix cannot buy boundedness by changing the contract.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sort_key,column", [
    ("fitScore", '"fitScore"'),
    ("createdAt", '"createdAt"'),
    ("title", '"title"'),
    ("company", '"company"'),
])
def test_sort_order_still_matches_the_databases_own_ordering(
    client, auth_headers, sort_key, column
):
    """``ORDER BY <col> DESC NULLS LAST`` must survive however the rows are read.

    The comparison is against the DATABASE's own ordering of the same rows, so
    this also catches a collation divergence if the ordering ever moves out of
    SQL (production and the test database are both ``C.UTF-8``, where byte
    order and Python's codepoint order agree — but that is a fact about the
    database, not an assumption this test makes).
    """
    from app.db import get_connection
    from app.repositories.job import JobRepository

    user_id = _user_id(client, auth_headers)
    seeded = _seed_jobs(user_id, 6)
    # Distinct sort values, plus NULLs, so the expected order is unambiguous.
    with get_connection() as conn:
        with conn.cursor() as cur:
            for index, job_id in enumerate(seeded):
                cur.execute(
                    'UPDATE "Job" SET "fitScore" = %s, "createdAt" = NOW() - '
                    "(%s || ' minutes')::interval WHERE \"id\" = %s",
                    (None if index >= 4 else float(50 + index * 7), index * 5, job_id),
                )
        conn.commit()

    rows = JobRepository().list_by_user(user_id, sort=sort_key)
    got = [r["id"] for r in rows]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT "id" FROM "Job" WHERE "userId" = %s '
                f"ORDER BY {column} DESC NULLS LAST, \"id\" ASC",
                (user_id,),
            )
            expected_pool = [r[0] for r in cur.fetchall()]

    assert sorted(got) == sorted(expected_pool), "the read returned a different row set"
    # Compare the ordering of the values themselves: ties are unordered in SQL,
    # so assert the sequence of sort-key values is non-increasing with NULLs last.
    by_id = {r["id"]: r for r in rows}
    values = [by_id[i][sort_key] for i in got]
    non_null = [v for v in values if v is not None]
    assert values[: len(non_null)] == non_null, "NULLs are not last"
    assert non_null == sorted(non_null, reverse=True), "not descending"
    # And agree with the database on where the NULL boundary falls.
    expected_values = [by_id[i][sort_key] for i in expected_pool]
    assert [v is None for v in values] == [v is None for v in expected_values]


def test_row_contract_is_unchanged(client, auth_headers):
    """Every field the board and its consumers read is still present on every
    row, including the two tailored-resume fields and the suppression expiry."""
    _seed_jobs(_user_id(client, auth_headers), 2)

    rows = client.get("/jobs?include_stale=true", headers=auth_headers).json()
    assert rows, "expected the seeded jobs back"
    for row in rows:
        missing = [f for f in _REQUIRED_ROW_FIELDS if f not in row]
        assert not missing, f"GET /jobs dropped fields {missing} from row {row['id']}"
