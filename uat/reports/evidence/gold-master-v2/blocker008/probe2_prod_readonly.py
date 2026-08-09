"""BLOCKER-008 READ-ONLY probe #2 — isolate WHY the autopilot subquery costs 5.7 s,
and measure the REAL active-feed output size using the shipped Python filter.

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

from probe_prod_readonly import read_prod_url, translate, timed  # noqa: E402


def main() -> None:
    dsn, schema = translate(read_prod_url())
    assert schema == "aether"
    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True, autocommit=False)
    out: dict = {"probe": "BLOCKER-008 #2 cost attribution"}

    from app.repositories.job import (  # noqa: E402
        _JOB_READ_COLUMNS,
        _TAILORED_RESUME_STATUS_SUBQUERY,
        _TAILORED_RESUME_SUBQUERY,
        _autopilot_suppressed_until_subquery,
    )
    from app.services.discovery.active_feed import active_feed  # noqa: E402

    ap = _autopilot_suppressed_until_subquery()

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        cur.execute('SELECT "userId", COUNT(*) n FROM "Job" GROUP BY 1 ORDER BY n DESC LIMIT 1')
        owner = cur.fetchone()["userId"]
        cur.execute('SELECT "status"::text s, COUNT(*) n FROM "Job" WHERE "userId"=%s '
                    "GROUP BY 1 ORDER BY n DESC", (owner,))
        out["job_status_distribution"] = [dict(r) for r in cur.fetchall()]
        cur.execute('SELECT COUNT(*) n FROM "AgentRun" WHERE "userId"=%s', (owner,))
        out["agentrun_rows_for_owner"] = cur.fetchone()["n"]
        cur.execute('SELECT COUNT(*) n FROM "AgentRun" WHERE "userId"=%s '
                    "AND \"agentName\"='coverLetter'", (owner,))
        out["agentrun_coverletter_rows"] = cur.fetchone()["n"]
        cur.execute('SELECT COUNT(*) n FROM "Resume" WHERE "userId"=%s '
                    'AND "sourceJobId" IS NOT NULL', (owner,))
        out["resume_rows_with_sourceJobId"] = cur.fetchone()["n"]
        # rows that pass the autopilot CASE gate (cheap part only)
        cur.execute(
            'SELECT COUNT(*) n FROM "Job" j WHERE j."userId"=%s AND ('
            '  ((j."status" = \'tailoring\') OR (j."status" IN (\'screening\',\'matched\') '
            '    AND j."fitScore" IS NOT NULL))'
            '  AND j."status" NOT IN (\'applied\',\'archived\')'
            '  AND NOT EXISTS (SELECT 1 FROM "Application" a WHERE a."jobId"=j."id" '
            '                  AND a."userId"=j."userId"))', (owner,))
        out["autopilot_gate_eligible_rows"] = cur.fetchone()["n"]

    # full query restricted to the gate-eligible statuses only
    gated = (
        f'SELECT {_JOB_READ_COLUMNS}, {ap} FROM "Job" j WHERE j."userId" = %s '
        "AND j.\"status\" IN ('tailoring','screening','matched')"
    )
    timed(conn, schema, gated, (owner,), "autopilot_over_gate_statuses_only", out,
          timeout="180s")

    # the two tailored subqueries alone, replaced by ONE bulk Resume read
    bulk_resume = (
        'SELECT DISTINCT ON (r."sourceJobId") r."sourceJobId", r."id", r."approvalStatus" '
        'FROM "Resume" r WHERE r."userId" = %s AND r."sourceJobId" IS NOT NULL '
        'AND r."approvalStatus" != \'rejected\' ORDER BY r."sourceJobId", r."version" DESC'
    )
    timed(conn, schema, bulk_resume, (owner,), "bulk_resume_one_statement", out)

    # ---- REAL active-feed size, using the shipped Python filter -------------
    conn.rollback()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f'SET search_path TO "{schema}"')
        cur.execute("SET LOCAL statement_timeout = '180s'")
        cur.execute(
            f'SELECT {_JOB_READ_COLUMNS} FROM "Job" j WHERE "userId" = %s '
            'ORDER BY "createdAt" DESC NULLS LAST', (owner,))
        rows = [dict(r) for r in cur.fetchall()]
    out["rows_from_db"] = len(rows)
    fed = active_feed(rows)
    out["real_active_feed_rows"] = len(fed)
    out["active_feed_status_mix"] = {}
    for r in fed:
        k = str(r.get("status"))
        out["active_feed_status_mix"][k] = out["active_feed_status_mix"].get(k, 0) + 1
    out["active_feed_ids_needing_autopilot_check"] = sum(
        1 for r in fed if str(r.get("status")) in ("tailoring", "screening", "matched"))
    out["approx_response_bytes_full_rows"] = len(
        json.dumps(fed, default=str).encode("utf-8"))

    # enrichment cost over ONLY the surviving feed ids
    ids = [r["id"] for r in fed]
    enrich = (
        f'SELECT j."id", {_TAILORED_RESUME_SUBQUERY}, '
        f'{_TAILORED_RESUME_STATUS_SUBQUERY}, {ap} '
        f'FROM "Job" j WHERE j."userId" = %s AND j."id" = ANY(%s)'
    )
    for n in (len(ids), 500, 250):
        if n and n <= len(ids):
            timed(conn, schema, enrich, (owner, ids[:n]), f"enrich_feed_{n}_ids", out)

    conn.close()
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
