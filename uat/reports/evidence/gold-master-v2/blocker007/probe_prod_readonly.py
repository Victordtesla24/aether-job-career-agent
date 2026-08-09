"""BLOCKER-007 READ-ONLY production probe.

Opens a READ ONLY transaction against the production DB and measures the cost
of the fit-scorer's current read path. Writes NOTHING. Prints no secrets.
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg2
import psycopg2.extras

ROOT = "/home/ubuntu/github_repos/aether-job-career-agent"
sys.path.insert(0, os.path.join(ROOT, "apps", "api"))


def read_prod_url() -> str:
    with open(os.path.join(ROOT, ".env"), "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                return val
    raise SystemExit("DATABASE_URL not found in .env")


def translate(url: str) -> tuple[str, str | None]:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    schema_values = params.pop("schema", None)
    schema = schema_values[0] if schema_values else None
    query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=query)), schema


def main() -> None:
    url = read_prod_url()
    dsn, schema = translate(url)
    if schema != "aether":
        raise SystemExit(f"expected production schema 'aether', got {schema!r}")
    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True, autocommit=False)
    out: dict = {"schema": schema}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')

        cur.execute(
            'SELECT "userId", COUNT(*) AS n, '
            'COUNT(*) FILTER (WHERE "fitScore" IS NULL) AS unscored '
            'FROM "Job" GROUP BY "userId" ORDER BY n DESC LIMIT 5'
        )
        rows = cur.fetchall()
        out["jobs_per_user"] = [dict(r) for r in rows]
        if not rows:
            print(json.dumps(out, indent=2, default=str))
            return
        owner = rows[0]["userId"]
        out["owner_job_count"] = rows[0]["n"]

        # ---- 1. current query under the PRODUCTION statement timeout -------
        from app.repositories.job import (  # noqa: E402
            _JOB_READ_COLUMNS,
            _TAILORED_RESUME_STATUS_SUBQUERY,
            _TAILORED_RESUME_SUBQUERY,
            _autopilot_suppressed_until_subquery,
        )

        current_sql = (
            f'SELECT {_JOB_READ_COLUMNS}, {_TAILORED_RESUME_SUBQUERY}, '
            f'{_TAILORED_RESUME_STATUS_SUBQUERY}, '
            f'{_autopilot_suppressed_until_subquery()} '
            f'FROM "Job" j WHERE "userId" = %s '
            f'ORDER BY "createdAt" DESC NULLS LAST'
        )
        cur.execute("SHOW statement_timeout")
        out["statement_timeout_default"] = cur.fetchone()["statement_timeout"]

        t0 = time.monotonic()
        try:
            cur.execute(current_sql, (owner,))
            cur.fetchall()
            out["current_query_under_default_timeout"] = {
                "outcome": "completed",
                "ms": round((time.monotonic() - t0) * 1000, 1),
            }
        except psycopg2.Error as exc:
            out["current_query_under_default_timeout"] = {
                "outcome": type(exc).__name__,
                "ms": round((time.monotonic() - t0) * 1000, 1),
                "message": str(exc).strip().splitlines()[0],
            }
            conn.rollback()

        # ---- 2. same query with a raised LOCAL timeout, to measure cost ----
        conn.rollback()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c2:
            c2.execute(f'SET search_path TO "{schema}"')
            c2.execute("SET LOCAL statement_timeout = '180s'")
            t0 = time.monotonic()
            try:
                c2.execute(current_sql, (owner,))
                got = c2.fetchall()
                out["current_query_raised_timeout"] = {
                    "outcome": "completed",
                    "ms": round((time.monotonic() - t0) * 1000, 1),
                    "rows": len(got),
                }
            except psycopg2.Error as exc:
                out["current_query_raised_timeout"] = {
                    "outcome": type(exc).__name__,
                    "ms": round((time.monotonic() - t0) * 1000, 1),
                    "message": str(exc).strip().splitlines()[0],
                }
                conn.rollback()

        # ---- 3. proposed narrow query, batched ------------------------------
        conn.rollback()
        narrow_sql = (
            'SELECT "id", "title", "description", "requirements", "status", '
            '"fitScore", "atsScore" '
            'FROM "Job" WHERE "userId" = %s AND "id" > %s '
            'ORDER BY "id" ASC LIMIT %s'
        )
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c3:
            c3.execute(f'SET search_path TO "{schema}"')
            cursor_id = ""
            total = 0
            batches = 0
            slowest = 0.0
            t_all = time.monotonic()
            while True:
                t0 = time.monotonic()
                c3.execute(narrow_sql, (owner, cursor_id, 500))
                got = c3.fetchall()
                dt = (time.monotonic() - t0) * 1000
                slowest = max(slowest, dt)
                batches += 1
                total += len(got)
                if len(got) < 500:
                    break
                cursor_id = got[-1]["id"]
            out["narrow_batched"] = {
                "rows": total,
                "batches": batches,
                "slowest_batch_ms": round(slowest, 1),
                "total_ms": round((time.monotonic() - t_all) * 1000, 1),
            }

        # ---- 4. index support for (userId, id) ------------------------------
        conn.rollback()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c4:
            c4.execute(f'SET search_path TO "{schema}"')
            c4.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = %s AND tablename = 'Job'",
                (schema,),
            )
            out["job_indexes"] = [dict(r) for r in c4.fetchall()]
            c4.execute("EXPLAIN (ANALYZE, BUFFERS) " + narrow_sql, (owner, "", 500))
            out["narrow_explain"] = [r["QUERY PLAN"] for r in c4.fetchall()]

        conn.rollback()
    conn.close()
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
