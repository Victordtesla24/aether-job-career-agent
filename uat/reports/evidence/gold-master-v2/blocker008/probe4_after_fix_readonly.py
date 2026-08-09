"""BLOCKER-008 READ-ONLY after-fix probe.

Calls the REAL, shipped ``JobRepository.list_by_user`` against the production
database with ``get_connection`` swapped for a READ ONLY equivalent, and
compares its output field-by-field against the pre-fix single-statement
projection over the same rows.

READ ONLY. Writes NOTHING. The two lazy-DDL guards are stubbed out so this
probe cannot issue DDL; both columns already exist in production (the pre-fix
statement selects them). Prints no secrets.
"""
from __future__ import annotations

import contextlib
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

DSN, SCHEMA = translate(read_prod_url())
assert SCHEMA == "aether"

STATEMENTS: list[str] = []


class _Cur:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, q, v=None):
        STATEMENTS.append(q if isinstance(q, str) else str(q))
        return self._cur.execute(q, v)

    def __enter__(self):
        self._cur.__enter__()
        return self

    def __exit__(self, *e):
        return self._cur.__exit__(*e)

    def __getattr__(self, item):
        return getattr(self._cur, item)


class _Conn:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *a, **k):
        return _Cur(self._conn.cursor(*a, **k))

    def __getattr__(self, item):
        return getattr(self._conn, item)


@contextlib.contextmanager
def readonly_connection():
    conn = psycopg2.connect(DSN)
    conn.set_session(readonly=True, autocommit=False)
    try:
        with conn.cursor() as c:
            c.execute(f'SET search_path TO "{SCHEMA}"')
        yield _Conn(conn)
    finally:
        conn.rollback()
        conn.close()


def main() -> None:
    from app.repositories import job as job_repo

    job_repo.get_connection = readonly_connection
    job_repo.ensure_job_cover_suppression_column = lambda: None
    job_repo.ensure_job_last_seen_column = lambda: None

    out: dict = {"probe": "BLOCKER-008 after-fix, shipped code path"}

    with psycopg2.connect(DSN) as raw:
        raw.set_session(readonly=True)
        with raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f'SET search_path TO "{SCHEMA}"')
            cur.execute('SELECT "userId", COUNT(*) n FROM "Job" '
                        "GROUP BY 1 ORDER BY n DESC LIMIT 1")
            row = cur.fetchone()
            owner, owner_n = row["userId"], row["n"]
    out["owner_job_count"] = owner_n

    # ---- the shipped path -------------------------------------------------
    for sort in ("createdAt", "fitScore"):
        STATEMENTS.clear()
        t0 = time.monotonic()
        rows = job_repo.JobRepository().list_by_user(owner, sort=sort)
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        ids = [r["id"] for r in rows]
        vals = [r[sort] for r in rows]
        non_null = [v for v in vals if v is not None]
        out[f"list_by_user_{sort}"] = {
            "total_ms": elapsed,
            "rows": len(rows),
            "distinct_ids": len(set(ids)),
            "all_rows_covered": len(set(ids)) == owner_n,
            "statements": len(STATEMENTS),
            "nulls_last_ok": vals[: len(non_null)] == non_null,
            "descending_ok": non_null == sorted(non_null, reverse=True),
            "suppressed_non_null": sum(
                1 for r in rows if r["autopilotSuppressedUntil"] is not None),
            "tailored_non_null": sum(
                1 for r in rows if r["tailoredResumeId"] is not None),
            "keys": sorted(rows[0].keys()) if rows else [],
        }
        if sort == "createdAt":
            new_rows = {r["id"]: r for r in rows}

    # ---- per-statement cost of the shipped path ---------------------------
    STATEMENTS.clear()
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            page_sql = (
                f'SELECT {job_repo._JOB_READ_COLUMNS}, '
                f'{job_repo._TAILORED_RESUME_SUBQUERY}, '
                f'{job_repo._TAILORED_RESUME_STATUS_SUBQUERY} '
                f'FROM "Job" j WHERE "userId" = %s AND "id" > %s '
                f'ORDER BY "id" ASC LIMIT {job_repo._BOARD_PAGE_SIZE}'
            )
            worst_page, worst_supp, last_id, pages = 0.0, 0.0, "", 0
            while True:
                t0 = time.monotonic()
                cur.execute(page_sql, (owner, last_id))
                page = job_repo.rows_to_dicts(cur)
                worst_page = max(worst_page, (time.monotonic() - t0) * 1000)
                if not page:
                    break
                pages += 1
                t0 = time.monotonic()
                job_repo._autopilot_suppression_map(
                    cur, owner, [r["id"] for r in page])
                worst_supp = max(worst_supp, (time.monotonic() - t0) * 1000)
                last_id = page[-1]["id"]
    out["per_statement"] = {
        "pages": pages,
        "slowest_page_statement_ms": round(worst_page, 1),
        "slowest_suppression_statement_ms": round(worst_supp, 1),
    }

    # ---- field-by-field equality vs the PRE-FIX projection ----------------
    with psycopg2.connect(DSN) as raw:
        raw.set_session(readonly=True)
        with raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f'SET search_path TO "{SCHEMA}"')
            cur.execute("SET statement_timeout = '180s'")
            limit = job_repo._autopilot_max_cover_failures()
            window = job_repo._autopilot_cover_failure_window_hours()
            since = f'''
                GREATEST(
                    COALESCE(
                        (SELECT MAX(r2."createdAt") FROM "AgentRun" r2
                         WHERE r2."userId" = j."userId"
                           AND r2."agentName" = 'coverLetter'
                           AND {job_repo._AP_COVER_RUN_PRODUCED_A_LETTER.format(run="r2").strip()}
                           AND (r2."input"->>'job_id') = j."id"),
                        '-infinity'::timestamptz),
                    COALESCE(j."coverFailureClearedAt", '-infinity'::timestamptz))
            '''
            prefix_ap = f'''
                (CASE WHEN (
                        ( (j."status" = 'tailoring')
                       OR (j."status" IN ('screening', 'matched')
                           AND j."fitScore" IS NOT NULL) )
                        AND j."status" NOT IN ('applied', 'archived')
                        AND NOT EXISTS (
                              SELECT 1 FROM "Application" a
                              WHERE a."jobId" = j."id" AND a."userId" = j."userId")
                      )
                      THEN (
                        SELECT r."createdAt" + (INTERVAL '1 hour' * {window})
                        FROM "AgentRun" r
                        WHERE r."userId" = j."userId"
                          AND r."agentName" = 'coverLetter'
                          AND {job_repo._AP_COVER_RUN_PRODUCED_NO_LETTER.format(run="r")}
                          AND r."createdAt" >= NOW() - (INTERVAL '1 hour' * {window})
                          AND (r."input"->>'job_id') = j."id"
                          AND r."createdAt" > {since}
                        ORDER BY r."createdAt" DESC
                        OFFSET {limit - 1} LIMIT 1)
                      ELSE NULL
                 END) AS "autopilotSuppressedUntil"
            '''
            t0 = time.monotonic()
            cur.execute(
                f'SELECT {job_repo._JOB_READ_COLUMNS}, '
                f'{job_repo._TAILORED_RESUME_SUBQUERY}, '
                f'{job_repo._TAILORED_RESUME_STATUS_SUBQUERY}, {prefix_ap} '
                f'FROM "Job" j WHERE "userId" = %s '
                f'ORDER BY "createdAt" DESC NULLS LAST', (owner,))
            old_rows = {r["id"]: dict(r) for r in cur.fetchall()}
            out["prefix_projection_ms_with_timeout_raised"] = round(
                (time.monotonic() - t0) * 1000, 1)

    diffs = []
    for jid, old in old_rows.items():
        new = new_rows.get(jid)
        if new is None:
            diffs.append({"id": jid, "reason": "missing from new read"})
            continue
        if set(old) != set(new):
            diffs.append({"id": jid, "reason": "field set differs",
                          "only_old": sorted(set(old) - set(new)),
                          "only_new": sorted(set(new) - set(old))})
            continue
        for key in old:
            if old[key] != new[key]:
                diffs.append({"id": jid, "field": key,
                              "old": str(old[key]), "new": str(new[key])})
    out["field_by_field_comparison"] = {
        "rows_compared": len(old_rows),
        "extra_rows_in_new": sorted(set(new_rows) - set(old_rows))[:5],
        "differences": len(diffs),
        "sample": diffs[:5],
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
