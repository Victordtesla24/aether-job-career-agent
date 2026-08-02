#!/usr/bin/env python3
"""W-SUB backfill — derive ``Job.applyEmail`` from stored posting descriptions.

Runs the SAME derivation the live path uses
(``app.services.application_submission.derive_apply_recipient``) over every
``Job`` row that has never been checked, and writes ONLY what it can actually
find in the posting's own text. A job whose description publishes no address
is stamped as CHECKED with ``applyEmail = NULL`` — i.e. recorded as "we
looked, the employer published nothing", which is different from "never
looked" and is exactly what the UI needs in order to tell the user honestly
that Aether cannot submit it.

Nothing is invented. There is no ``careers@<company>.com`` fallback: that
would point a real job application at an address the employer never gave.

Usage (from the repo root):

    apps/api/scripts/backfill_job_apply_email.py --dry-run
    apps/api/scripts/backfill_job_apply_email.py

``--dry-run`` reports what WOULD be written and touches nothing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import (  # noqa: E402
    ensure_job_apply_contact_columns,
    get_connection,
    rows_to_dicts,
)
from app.services.application_submission import derive_apply_recipient  # noqa: E402

#: Batch size — the hosted Postgres kills statements over 5 seconds, so the
#: scan is paged rather than run as one giant UPDATE ... FROM.
_BATCH = 200


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report findings without writing anything",
    )
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="also re-derive rows already marked as checked",
    )
    args = parser.parse_args()

    ensure_job_apply_contact_columns()
    scanned = found = 0
    predicate = "" if args.recheck else 'WHERE "applyContactCheckedAt" IS NULL'
    last_id = ""
    while True:
        with get_connection() as conn:
            with conn.cursor() as cur:
                joiner = "AND" if predicate else "WHERE"
                cur.execute(
                    f'SELECT "id", "userId", "title", "company", "description" '
                    f'FROM "Job" {predicate} {joiner} "id" > %s '
                    f'ORDER BY "id" LIMIT {_BATCH}',
                    (last_id,),
                )
                rows = rows_to_dicts(cur)
                if not rows:
                    break
                last_id = rows[-1]["id"]
                for row in rows:
                    scanned += 1
                    derived = derive_apply_recipient(row.get("description"))
                    if derived:
                        found += 1
                        print(
                            f"  FOUND {derived['email']} ({derived['source']}) "
                            f"— {row['title']} @ {row['company']}"
                        )
                    if args.dry_run:
                        continue
                    cur.execute(
                        'UPDATE "Job" SET "applyEmail" = %s, "applyEmailSource" = %s, '
                        '"applyContactCheckedAt" = NOW() WHERE "id" = %s',
                        (
                            derived["email"] if derived else None,
                            derived["source"] if derived else None,
                            row["id"],
                        ),
                    )
            conn.commit()

    verb = "would derive" if args.dry_run else "derived"
    print(
        f"\n{scanned} job(s) scanned; {verb} a real published application "
        f"address for {found}. The remaining {scanned - found} publish none — "
        f"those are NOT auto-submittable and the UI now says so."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
