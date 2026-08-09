"""BLOCKER-007 AFTER-FIX cost probe: runs the SHIPPED repository method
(JobRepository.iter_scoring_candidates) against PRODUCTION in a READ ONLY
session. Writes nothing. Prints no secrets.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg2

ROOT = "/home/ubuntu/github_repos/aether-job-career-agent"
sys.path.insert(0, os.path.join(ROOT, "apps", "api"))


def read_prod_url() -> str:
    with open(os.path.join(ROOT, ".env"), "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DATABASE_URL not found")


url = read_prod_url()
parsed = urlparse(url)
params = parse_qs(parsed.query)
schema = params.pop("schema", ["?"])[0]
if schema != "aether":
    raise SystemExit(f"expected production schema 'aether', got {schema!r}")
DSN = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in params.items()})))

STATEMENTS: list[tuple[str, float]] = []


class _TimingCursor:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, query, vars=None):
        t0 = time.monotonic()
        try:
            return self._cur.execute(query, vars)
        finally:
            STATEMENTS.append((str(query)[:70], (time.monotonic() - t0) * 1000))

    def __enter__(self):
        self._cur.__enter__()
        return self

    def __exit__(self, *exc):
        return self._cur.__exit__(*exc)

    def __getattr__(self, item):
        return getattr(self._cur, item)


class _Conn:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *a, **k):
        return _TimingCursor(self._conn.cursor(*a, **k))

    def __getattr__(self, item):
        return getattr(self._conn, item)


@contextlib.contextmanager
def readonly_connection():
    conn = psycopg2.connect(DSN, options=f"-csearch_path={schema}")
    conn.set_session(readonly=True)
    try:
        yield _Conn(conn)
    finally:
        conn.close()


from app.repositories import job as job_repo  # noqa: E402

job_repo.get_connection = readonly_connection

with readonly_connection() as c:
    with c.cursor() as cur:
        cur.execute('SELECT "userId", COUNT(*) FROM "Job" GROUP BY "userId" '
                    'ORDER BY 2 DESC LIMIT 1')
        owner, total = cur.fetchone()
STATEMENTS.clear()

t0 = time.monotonic()
rows = list(job_repo.JobRepository().iter_scoring_candidates(owner))
wall = (time.monotonic() - t0) * 1000

selects = [s for s in STATEMENTS if s[0].startswith("SELECT")]
print(json.dumps({
    "owner_job_count": total,
    "rows_yielded": len(rows),
    "all_rows_covered": len(rows) == total,
    "distinct_ids": len({r["id"] for r in rows}),
    "columns_returned": sorted(rows[0].keys()) if rows else [],
    "statements": len(selects),
    "slowest_statement_ms": round(max(s[1] for s in selects), 1) if selects else None,
    "total_wall_ms": round(wall, 1),
    "statement_timeout_headroom_x": (
        round(5000 / max(s[1] for s in selects), 1) if selects else None
    ),
}, indent=2))
