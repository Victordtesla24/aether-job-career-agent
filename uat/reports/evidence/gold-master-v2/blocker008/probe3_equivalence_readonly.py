"""BLOCKER-008 READ-ONLY probe #3 — prove the proposed SET-BASED suppression
query returns EXACTLY the same ``autopilotSuppressedUntil`` as the shipped
per-row correlated subquery, for every one of the owner's production jobs,
and measure its cost.

READ ONLY session. Writes NOTHING, no DDL, prints no secrets.
"""
from __future__ import annotations

import json
import os
import sys
import time

import psycopg2
import psycopg2.extras

ROOT = "/home/ubuntu/github_repos/aether-job-career-agent"
sys.path.insert(0, os.path.join(ROOT, "apps", "api"))
sys.path.insert(0, os.path.join(ROOT, "uat/reports/evidence/gold-master-v2/blocker008"))

from probe_prod_readonly import read_prod_url, translate  # noqa: E402


def main() -> None:
    dsn, schema = translate(read_prod_url())
    assert schema == "aether"
    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True, autocommit=False)
    out: dict = {"probe": "BLOCKER-008 #3 set-based suppression equivalence"}

    from app.repositories.job import (  # noqa: E402
        _autopilot_cover_failure_window_hours,
        _autopilot_max_cover_failures,
        _autopilot_suppressed_until_subquery,
        _JOB_READ_COLUMNS,
    )

    limit = _autopilot_max_cover_failures()
    window = _autopilot_cover_failure_window_hours()
    out["limit"] = limit
    out["window_hours"] = window

    # ---- candidate set-based SQL (the proposal) ---------------------------
    from app.repositories.job import (  # noqa: E402
        _AP_COVER_RUN_PRODUCED_A_LETTER,
        _AP_COVER_RUN_PRODUCED_NO_LETTER,
    )

    set_sql = f'''
        WITH elig AS (
            SELECT j."id", j."coverFailureClearedAt"
            FROM "Job" j
            WHERE j."userId" = %s AND j."id" = ANY(%s)
              AND ( (j."status" = 'tailoring')
                 OR (j."status" IN ('screening','matched') AND j."fitScore" IS NOT NULL) )
              AND j."status" NOT IN ('applied','archived')
              AND NOT EXISTS (SELECT 1 FROM "Application" a
                              WHERE a."jobId" = j."id" AND a."userId" = j."userId")
        ),
        runs AS (
            SELECT (r."input"->>'job_id') AS job_id, r."createdAt",
                   {_AP_COVER_RUN_PRODUCED_A_LETTER.format(run="r").strip()} AS produced_letter,
                   {_AP_COVER_RUN_PRODUCED_NO_LETTER.format(run="r").strip()} AS letterless
            FROM "AgentRun" r
            WHERE r."userId" = %s AND r."agentName" = 'coverLetter'
        ),
        floors AS (
            SELECT job_id, MAX("createdAt") AS last_letter
            FROM runs WHERE produced_letter GROUP BY job_id
        ),
        ranked AS (
            SELECT e."id" AS job_id, x."createdAt",
                   ROW_NUMBER() OVER (PARTITION BY e."id" ORDER BY x."createdAt" DESC) AS rn
            FROM elig e
            JOIN runs x ON x.job_id = e."id"
            LEFT JOIN floors f ON f.job_id = e."id"
            WHERE x.letterless
              AND x."createdAt" >= NOW() - (INTERVAL '1 hour' * {window})
              AND x."createdAt" > GREATEST(
                    COALESCE(f.last_letter, '-infinity'::timestamptz),
                    COALESCE(e."coverFailureClearedAt", '-infinity'::timestamptz))
        )
        SELECT job_id, ("createdAt" + (INTERVAL '1 hour' * {window})) AS expiry
        FROM ranked WHERE rn = {limit}
    '''
    out["set_sql"] = set_sql

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        cur.execute('SELECT "userId", COUNT(*) n FROM "Job" GROUP BY 1 ORDER BY n DESC LIMIT 1')
        owner = cur.fetchone()["userId"]

        cur.execute("SET LOCAL statement_timeout = '180s'")
        cur.execute('SELECT "id" FROM "Job" WHERE "userId" = %s ORDER BY "id"', (owner,))
        ids = [r["id"] for r in cur.fetchall()]
    out["job_ids"] = len(ids)

    # ---- ground truth: the SHIPPED correlated subquery, all rows ----------
    conn.rollback()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        cur.execute("SET LOCAL statement_timeout = '180s'")
        t0 = time.monotonic()
        cur.execute(
            f'SELECT j."id", {_autopilot_suppressed_until_subquery()} '
            f'FROM "Job" j WHERE j."userId" = %s', (owner,))
        truth = {r["id"]: r["autopilotSuppressedUntil"] for r in cur.fetchall()}
        out["shipped_correlated_ms"] = round((time.monotonic() - t0) * 1000, 1)
    out["shipped_non_null"] = sum(1 for v in truth.values() if v is not None)

    # ---- proposal: paged, bounded id-sets ---------------------------------
    for page in (500, 1000):
        conn.rollback()
        got: dict = {}
        slowest, stmts = 0.0, 0
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f'SET search_path TO "{schema}"')
            t_all = time.monotonic()
            for i in range(0, len(ids), page):
                chunk = ids[i:i + page]
                t0 = time.monotonic()
                cur.execute(set_sql, (owner, chunk, owner))
                for r in cur.fetchall():
                    got[r["job_id"]] = r["expiry"]
                slowest = max(slowest, (time.monotonic() - t0) * 1000)
                stmts += 1
            total = round((time.monotonic() - t_all) * 1000, 1)
        mismatches = []
        for jid in ids:
            a, b = truth.get(jid), got.get(jid)
            if a != b:
                mismatches.append({"id": jid, "shipped": str(a), "proposed": str(b)})
        out[f"proposed_page_{page}"] = {
            "statements": stmts,
            "slowest_statement_ms": round(slowest, 1),
            "total_ms": total,
            "non_null": sum(1 for v in got.values() if v is not None),
            "mismatches": len(mismatches),
            "mismatch_sample": mismatches[:5],
        }

    # ---- base page WITH the two tailored subqueries, bounded --------------
    from app.repositories.job import (  # noqa: E402
        _TAILORED_RESUME_STATUS_SUBQUERY,
        _TAILORED_RESUME_SUBQUERY,
    )
    conn.rollback()
    base_page = (
        f'SELECT {_JOB_READ_COLUMNS}, {_TAILORED_RESUME_SUBQUERY}, '
        f'{_TAILORED_RESUME_STATUS_SUBQUERY} FROM "Job" j '
        f'WHERE j."userId" = %s AND j."id" > %s ORDER BY j."id" ASC LIMIT 500'
    )
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        cursor_id, total_rows, stmts, slowest = "", 0, 0, 0.0
        t_all = time.monotonic()
        while True:
            t0 = time.monotonic()
            cur.execute(base_page, (owner, cursor_id))
            rows = cur.fetchall()
            slowest = max(slowest, (time.monotonic() - t0) * 1000)
            stmts += 1
            total_rows += len(rows)
            if not rows:
                break
            cursor_id = rows[-1]["id"]
        out["proposed_base_page_with_tailored"] = {
            "rows": total_rows, "statements": stmts,
            "slowest_statement_ms": round(slowest, 1),
            "total_ms": round((time.monotonic() - t_all) * 1000, 1),
        }

    conn.rollback()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        cur.execute("SET LOCAL statement_timeout = '180s'")
        cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + set_sql, (owner, ids[:500], owner))
        out["explain_set_500"] = [r["QUERY PLAN"] for r in cur.fetchall()]
        conn.rollback()

    conn.close()
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
