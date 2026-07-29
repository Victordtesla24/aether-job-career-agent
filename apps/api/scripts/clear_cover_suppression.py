#!/usr/bin/env python3
"""Board-sweep cover-failure suppression clear script (ML-W-12).

The board-sweep autopilot (``app/workers/board_sweep.py``, RT-007)
permanently excludes a job from its next-target selection once it accrues
``AETHER_BOARD_SWEEP_MAX_COVER_FAILURES`` (default 3) LETTERLESS coverLetter
``AgentRun`` rows inside ``AETHER_BOARD_SWEEP_COVER_FAILURE_WINDOW_HOURS``
(default 24h) since the job's own last genuine success/clear. "Letterless"
means ``status='failed'`` OR a ``status='completed'`` row carrying the honest
``output.coverLetterUnavailable`` degrade flag (ML-W-19). That backoff is
correct for a job whose cover letter is genuinely unfabricatable — but if the
failures were actually caused by a pipeline BUG that has since been fixed and
deployed, every job that failed under the old broken code stays wedged for
the rest of the window: because the job is excluded from selection, the
sweep can never re-attempt it to earn the new success that would otherwise
auto-clear it (board_sweep.py only counts letterless runs AFTER a job's own
last coverLetter run that genuinely produced a letter, or its own last clear
stamp — see ``Job.coverFailureClearedAt``, added by ``app.db.
ensure_job_cover_suppression_column``).

This script is the ops escape hatch for exactly that incident: it stamps
``Job.coverFailureClearedAt = NOW()`` on every job CURRENTLY suppressed by
the cover-failure backoff (optionally scoped to one user/job), so the next
board-sweep tick treats that job's failure history as starting fresh.

  * It NEVER touches the historical ``AgentRun`` audit trail — failed runs
    stay recorded as failed; only what counts GOING FORWARD changes.
  * It is fully idempotent — a job that is not currently suppressed is left
    untouched, and re-running the script after a clear is a no-op until that
    job accrues a fresh batch of failures.
  * It agrees with the running service on what "suppressed" means: it reads
    the SAME ``AETHER_BOARD_SWEEP_MAX_COVER_FAILURES`` /
    ``AETHER_BOARD_SWEEP_COVER_FAILURE_WINDOW_HOURS`` overrides
    ``board_sweep.py`` itself honours.

Usage:
    # DRY-RUN — report which jobs would be cleared, without modifying anything
    python scripts/clear_cover_suppression.py --dry-run

    # REAL RUN — clear every currently-suppressed job, all users
    python scripts/clear_cover_suppression.py

    # Scope to one user and/or one job
    python scripts/clear_cover_suppression.py --user-id c123... --dry-run
    python scripts/clear_cover_suppression.py --job-id c456...

The script reads ``DATABASE_URL`` from the environment (same ``.env`` as the
API) and never modifies data when ``--dry-run`` is passed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# --- Path setup: run from repo root or apps/api/ (mirrors dedup_cleanup.py) ---
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "apps" / "api") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

# Load .env so DATABASE_URL is available (never sources the WHOLE shell env —
# see scripts/run-tests.sh's incident writeup for why that matters).
try:
    from dotenv import load_dotenv

    _env_path = _REPO_ROOT / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass  # python-dotenv not installed — expect DATABASE_URL in env already

import psycopg2

#: Defaults mirror ``app.workers.board_sweep.MAX_COVER_FAILURES`` /
#: ``COVER_FAILURE_WINDOW_HOURS`` exactly — kept as plain constants (rather
#: than importing the FastAPI app) so this script has zero import-time
#: side effects, same convention as ``dedup_cleanup.py``.
_DEFAULT_MAX_FAILURES = 3
_DEFAULT_WINDOW_HOURS = 24


# ---------------------------------------------------------------------------
# Database helpers (mirrors app.db, but standalone so the script has zero
# import-time side effects)
# ---------------------------------------------------------------------------


def _translate_prisma_url(url: str) -> tuple[str, str | None]:
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    schema_values = params.pop("schema", None)
    schema = schema_values[0] if schema_values else None
    query = urlencode({k: v[0] for k, v in params.items()})
    dsn = urlunparse(parsed._replace(query=query))
    return dsn, schema


def get_connection():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set — source .env or export it")
    dsn, schema = _translate_prisma_url(url)
    options = f"-csearch_path={schema}" if schema else None
    return psycopg2.connect(dsn, options=options)


def _max_failures() -> int:
    try:
        return max(1, int(os.environ.get(
            "AETHER_BOARD_SWEEP_MAX_COVER_FAILURES", str(_DEFAULT_MAX_FAILURES))))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_FAILURES


def _window_hours() -> int:
    try:
        return max(1, int(os.environ.get(
            "AETHER_BOARD_SWEEP_COVER_FAILURE_WINDOW_HOURS", str(_DEFAULT_WINDOW_HOURS))))
    except (TypeError, ValueError):
        return _DEFAULT_WINDOW_HOURS


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def ensure_column(cur) -> None:
    """Idempotently add ``Job.coverFailureClearedAt`` if missing.

    Mirrors ``app.db.ensure_job_cover_suppression_column`` — this script is
    standalone by design (module docstring), so it re-issues the same
    additive, no-default ``ADD COLUMN IF NOT EXISTS`` rather than importing
    the FastAPI app. Safe to run every invocation (including --dry-run):
    it is a metadata-only no-op once the column exists.
    """
    cur.execute(
        'ALTER TABLE "Job" ADD COLUMN IF NOT EXISTS "coverFailureClearedAt" timestamptz'
    )


def find_suppressed_jobs(cur, *, user_id: str | None, job_id: str | None) -> list[dict]:
    """Jobs currently excluded from board-sweep selection SOLELY by the
    cover-failure backoff: otherwise-eligible board work (tailoring, or
    screening/matched with a fitScore), no Application yet, and
    ``max_cover_failures()``+ LETTERLESS coverLetter AgentRuns inside the
    window since the job's own last GENUINE success/clear — the EXACT
    predicate ``app.workers.board_sweep._saturated_job_ids`` uses.

    ML-W-19 (kept in LOCKSTEP with
    ``board_sweep._COVER_RUN_PRODUCED_NO_LETTER`` /
    ``_COVER_RUN_PRODUCED_A_LETTER``): "letterless" is NOT just
    ``status='failed'``. A fabrication/structural guard rejection is recorded
    as ``status='completed'`` with ``output.coverLetterUnavailable = true``
    (GAP-P4-002), and that is the dominant mode in production — counting only
    ``failed`` made this script blind to exactly the jobs ops needs to clear.
    Symmetrically, only a run carrying a NON-NULL letter id counts as the
    success that floors the window; a letterless ``completed`` run must not
    clear the count it is supposed to contribute to.
    """
    limit = _max_failures()
    window = _window_hours()
    cur.execute(
        '''
        SELECT j."id", j."userId", j."title", j."company"
        FROM "Job" j
        WHERE (
                (j."status" = 'tailoring')
             OR (j."status" IN ('screening','matched') AND j."fitScore" IS NOT NULL)
              )
          AND j."status" NOT IN ('applied','archived')
          AND NOT EXISTS (
                SELECT 1 FROM "Application" a
                WHERE a."jobId" = j."id" AND a."userId" = j."userId"
              )
          AND (%s::text IS NULL OR j."userId" = %s)
          AND (%s::text IS NULL OR j."id" = %s)
          AND (
                SELECT count(*) FROM "AgentRun" r
                WHERE r."userId" = j."userId"
                  AND r."agentName" = 'coverLetter'
                  AND (r."status" = 'failed'
                       OR (r."status" = 'completed'
                           AND (r."output"->'coverLetterUnavailable' = 'true'::jsonb
                                OR r."output"->'cover_letter_unavailable' = 'true'::jsonb)))
                  AND r."createdAt" >= NOW() - INTERVAL '%s hours'
                  AND (r."input"->>'job_id') = j."id"
                  AND r."createdAt" > GREATEST(
                        COALESCE(
                            (SELECT MAX(r2."createdAt") FROM "AgentRun" r2
                             WHERE r2."userId" = j."userId" AND r2."agentName" = 'coverLetter'
                               AND r2."status" = 'completed'
                               AND (r2."output"->>'cover_letter_id' IS NOT NULL
                                    OR r2."output"->>'coverLetterId' IS NOT NULL)
                               AND (r2."input"->>'job_id') = j."id"),
                            '-infinity'::timestamptz),
                        COALESCE(j."coverFailureClearedAt", '-infinity'::timestamptz))
              ) >= %s
        ORDER BY j."userId", j."createdAt"
        ''',
        (user_id, user_id, job_id, job_id, window, limit),
    )
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def clear_jobs(cur, job_ids: list[str]) -> int:
    if not job_ids:
        return 0
    cur.execute(
        'UPDATE "Job" SET "coverFailureClearedAt" = NOW() WHERE "id" = ANY(%s)',
        (job_ids,),
    )
    return cur.rowcount


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clear the board-sweep cover-failure suppression (ML-W-12)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="report what would be cleared without modifying anything",
    )
    parser.add_argument("--user-id", default=None, help="scope to one user id")
    parser.add_argument("--job-id", default=None, help="scope to one job id")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            ensure_column(cur)
        conn.commit()  # additive DDL only — harmless even under --dry-run

        with conn.cursor() as cur:
            jobs = find_suppressed_jobs(cur, user_id=args.user_id, job_id=args.job_id)
            if not jobs:
                print("✅ No currently-suppressed jobs found. Nothing to do.")
                return 0

            print(f"🔍 Found {len(jobs)} currently-suppressed job(s):")
            for j in jobs:
                print(f"  {j['id']} | user={j['userId']} | \"{j['title']}\" @ {j['company']}")

            if args.dry_run:
                print("\nDry run — no changes made. Re-run without --dry-run to clear.")
                return 0

            cleared = clear_jobs(cur, [j["id"] for j in jobs])
        conn.commit()
        print(f"\n✅ Cleared {cleared} job(s) — coverFailureClearedAt stamped NOW().")
        print("The next board-sweep tick will treat their failure history as reset.")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"\n❌ Error: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
