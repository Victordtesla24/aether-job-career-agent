"""Purge demo-seeded jobs so the Jobs page shows only REAL postings (D11).

Removes every job whose sourceUrl points at the fake ``demo.aether.dev``
domain (created by scripts/seed_demo.py) along with dependent rows
(applications cascade via FK). Also deletes any duplicate job rows sharing
the same (userId, company, title) triple, keeping the newest.

Idempotent — safe to run repeatedly. Usage:

    /opt/abacus-python/bin/python scripts/purge_demo_jobs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_connection  # noqa: E402

DEMO_URL_PREFIX = "https://demo.aether.dev/%"
DEMO_DESCRIPTION = "Demo-seeded job posting for the analytics funnel."


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Demo-seeded jobs (fake URLs / seeded description).
            cur.execute(
                'DELETE FROM "Job" WHERE "sourceUrl" LIKE %s OR "description" = %s',
                (DEMO_URL_PREFIX, DEMO_DESCRIPTION),
            )
            purged = cur.rowcount
            # 2. Duplicate (userId, company, title) rows — keep the newest.
            cur.execute(
                '''
                DELETE FROM "Job" WHERE "id" IN (
                    SELECT "id" FROM (
                        SELECT "id", ROW_NUMBER() OVER (
                            PARTITION BY "userId", LOWER("company"), LOWER("title")
                            ORDER BY "createdAt" DESC
                        ) AS rn
                        FROM "Job"
                    ) ranked WHERE ranked.rn > 1
                )
                '''
            )
            deduped = cur.rowcount
            conn.commit()
            cur.execute('SELECT COUNT(*) FROM "Job"')
            remaining = cur.fetchone()[0]
    print(f"purged {purged} demo jobs, removed {deduped} duplicates, {remaining} jobs remain")


if __name__ == "__main__":
    main()
