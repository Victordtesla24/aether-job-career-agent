#!/usr/bin/env python3
"""U5d — reclassify claimed-submitted-without-proof applications (ops one-shot).

WHAT IT REMEDIATES. Before U5d the Submission Agent (and the Apply write it
reused) recorded ``Application.status = 'submitted'`` and told the user
*"Submitted your application for …"* while transmitting nothing. Production
census 2026-08-14T07:35:45Z (``uat/reports/evidence/agents-uplift/u5d/
CENSUS.json``): 346 rows claim ``submitted``; **0 of 606 rows has ever carried
a ``transmittedAt``**.

WHAT IT DOES. Sets ``submissionTruthState = 'recorded_transmission_unverified'``
— *"recorded — transmission unverified (pre-fix)"* — on exactly those rows, and
prints the count.

WHAT IT NEVER DOES. It does not rewrite ``Application.status`` (the user's own
tracker data), does not delete a row, does not touch status-event history, and
cannot write a positive claim: no code path here can set ``transmittedAt``.
Idempotent — a second run reclassifies 0.

USAGE (DRY RUN IS THE DEFAULT — it only ever runs SELECTs):

    cd apps/api && python3 ../../scripts/backfill_submission_truth.py
    cd apps/api && python3 ../../scripts/backfill_submission_truth.py --apply

``DATABASE_URL`` comes from the environment (``os.environ`` only — never a
literal in source). ``--user-id`` scopes the pass to one owner.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the reclassification (default: dry run, SELECT only)",
    )
    parser.add_argument("--user-id", default=None, help="scope to one owner")
    parser.add_argument(
        "--sample", type=int, default=10, help="how many matching ids to print"
    )
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set in the environment.", file=sys.stderr)
        return 2

    from app.services.submission_truth import (  # noqa: PLC0415 - after sys.path
        NOTE_UNVERIFIED,
        STATE_UNVERIFIED,
        backfill_unverified_submissions,
        count_unverified_submissions,
        unverified_submission_ids,
    )

    before = count_unverified_submissions(args.user_id)
    report = {
        "mode": "apply" if args.apply else "dry-run",
        "scope": args.user_id or "all-users",
        "state": STATE_UNVERIFIED,
        "note": NOTE_UNVERIFIED,
        "matching_before": before,
        "sample_ids": unverified_submission_ids(args.user_id, limit=args.sample),
    }
    if args.apply:
        report.update(backfill_unverified_submissions(args.user_id))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
