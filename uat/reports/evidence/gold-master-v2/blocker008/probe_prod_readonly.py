"""BLOCKER-008 READ-ONLY production probe — ``GET /jobs`` (JobRepository.list_by_user).

Opens a READ ONLY psycopg2 session against the production DB and measures the
cost of the board list read, decomposed so the actual cost driver is identified
rather than guessed. Writes NOTHING, issues NO DDL, prints NO secrets.
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
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DATABASE_URL not found in .env")


def translate(url: str) -> tuple[str, str | None]:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    schema_values = params.pop("schema", None)
    schema = schema_values[0] if schema_values else None
    query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=query)), schema


def timed(conn, schema, sql, params, label, out, timeout=None, fetch=True):
    conn.rollback()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        if timeout:
            cur.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        t0 = time.monotonic()
        try:
            cur.execute(sql, params)
            rows = cur.fetchall() if fetch else []
            out[label] = {
                "outcome": "completed",
                "ms": round((time.monotonic() - t0) * 1000, 1),
                "rows": len(rows),
            }
            return rows
        except psycopg2.Error as exc:
            out[label] = {
                "outcome": type(exc).__name__,
                "ms": round((time.monotonic() - t0) * 1000, 1),
                "message": str(exc).strip().splitlines()[0],
            }
            conn.rollback()
            return None


def main() -> None:
    dsn, schema = translate(read_prod_url())
    if schema != "aether":
        raise SystemExit(f"expected production schema 'aether', got {schema!r}")
    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True, autocommit=False)
    out: dict = {"schema": schema, "probe": "BLOCKER-008 GET /jobs"}

    from app.repositories.job import (  # noqa: E402
        _JOB_READ_COLUMNS,
        _TAILORED_RESUME_STATUS_SUBQUERY,
        _TAILORED_RESUME_SUBQUERY,
        _autopilot_suppressed_until_subquery,
    )

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        cur.execute("SHOW statement_timeout")
        out["statement_timeout_default"] = cur.fetchone()["statement_timeout"]
        cur.execute(
            'SELECT "userId", COUNT(*) AS n FROM "Job" GROUP BY "userId" '
            "ORDER BY n DESC LIMIT 5"
        )
        rows = cur.fetchall()
        out["jobs_per_user"] = [dict(r) for r in rows]
        owner = rows[0]["userId"]
        out["owner_job_count"] = rows[0]["n"]

        # How many rows the active feed would actually keep (diagnostic only —
        # this SQL is NOT the fix; the real filter stays in Python).
        cur.execute(
            'SELECT COUNT(*) AS n FROM "Job" WHERE "userId" = %s '
            "AND lower(COALESCE(\"source\",'')) <> 'seek' "
            "AND \"status\"::text NOT IN ('applied','archived') "
            'AND COALESCE("lastSeenAt", "updatedAt", "createdAt") '
            ">= NOW() - INTERVAL '30 days'",
            (owner,),
        )
        out["approx_active_feed_rows"] = cur.fetchone()["n"]

    ap = _autopilot_suppressed_until_subquery()
    full = (
        f'SELECT {_JOB_READ_COLUMNS}, {_TAILORED_RESUME_SUBQUERY}, '
        f'{_TAILORED_RESUME_STATUS_SUBQUERY}, {ap} '
        f'FROM "Job" j WHERE "userId" = %s ORDER BY {{col}} DESC NULLS LAST'
    )

    # ---- 1. exactly what GET /jobs runs today, default statement timeout ----
    timed(conn, schema, full.format(col='"createdAt"'), (owner,),
          "current_default_sort_prod_timeout", out)
    timed(conn, schema, full.format(col='"fitScore"'), (owner,),
          "current_fitScore_sort_prod_timeout", out)

    # ---- 2. same, timeout raised, to measure the real cost -----------------
    timed(conn, schema, full.format(col='"createdAt"'), (owner,),
          "current_default_sort_raised_timeout", out, timeout="180s")

    # ---- 3. decompose the cost --------------------------------------------
    base = (f'SELECT {_JOB_READ_COLUMNS} FROM "Job" j WHERE "userId" = %s '
            f'ORDER BY "createdAt" DESC NULLS LAST')
    timed(conn, schema, base, (owner,), "base_columns_only_no_subqueries", out,
          timeout="180s")

    tailored = (
        f'SELECT {_JOB_READ_COLUMNS}, {_TAILORED_RESUME_SUBQUERY}, '
        f'{_TAILORED_RESUME_STATUS_SUBQUERY} '
        f'FROM "Job" j WHERE "userId" = %s ORDER BY "createdAt" DESC NULLS LAST'
    )
    timed(conn, schema, tailored, (owner,), "base_plus_tailored_subqueries", out,
          timeout="180s")

    autop = (
        f'SELECT {_JOB_READ_COLUMNS}, {ap} '
        f'FROM "Job" j WHERE "userId" = %s ORDER BY "createdAt" DESC NULLS LAST'
    )
    timed(conn, schema, autop, (owner,), "base_plus_autopilot_subquery", out,
          timeout="180s")

    # ---- 4. proposed: keyset-paged base read, then enrich the survivors ----
    conn.rollback()
    page = int(os.environ.get("PROBE_PAGE", "500"))
    base_page = (
        f'SELECT {_JOB_READ_COLUMNS} FROM "Job" j '
        f'WHERE "userId" = %s AND "id" > %s ORDER BY "id" ASC LIMIT {page}'
    )
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        cursor_id, total, batches, slowest = "", 0, 0, 0.0
        ids: list[str] = []
        t_all = time.monotonic()
        while True:
            t0 = time.monotonic()
            cur.execute(base_page, (owner, cursor_id))
            got = cur.fetchall()
            slowest = max(slowest, (time.monotonic() - t0) * 1000)
            batches += 1
            total += len(got)
            ids.extend(r["id"] for r in got)
            if not got:
                break
            cursor_id = got[-1]["id"]
        out["proposed_base_keyset_walk"] = {
            "rows": total, "distinct_ids": len(set(ids)), "statements": batches,
            "slowest_statement_ms": round(slowest, 1),
            "total_ms": round((time.monotonic() - t_all) * 1000, 1),
        }

    # enrichment of N ids in one bounded statement (worst case: ALL rows)
    enrich = (
        f'SELECT j."id", {_TAILORED_RESUME_SUBQUERY}, '
        f'{_TAILORED_RESUME_STATUS_SUBQUERY}, {ap} '
        f'FROM "Job" j WHERE j."userId" = %s AND j."id" = ANY(%s)'
    )
    for n in (100, 200, 500):
        timed(conn, schema, enrich, (owner, ids[:n]), f"enrich_{n}_ids", out,
              timeout="180s")
    timed(conn, schema, enrich, (owner, ids), "enrich_ALL_ids_one_statement", out)

    # ---- 5. indexes + EXPLAIN ---------------------------------------------
    conn.rollback()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        cur.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = %s AND tablename IN ('Job','Resume','AgentRun','Application') "
            "ORDER BY tablename, indexname",
            (schema,),
        )
        out["indexes"] = [dict(r) for r in cur.fetchall()]
        cur.execute("SET LOCAL statement_timeout = '180s'")
        cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + base_page, (owner, ""))
        out["explain_base_page"] = [r["QUERY PLAN"] for r in cur.fetchall()]
        cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + enrich, (owner, ids[:500]))
        out["explain_enrich_500"] = [r["QUERY PLAN"] for r in cur.fetchall()]
        conn.rollback()

    conn.close()
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
