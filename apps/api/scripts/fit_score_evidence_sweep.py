#!/usr/bin/env python3
"""v5 — report (and, with ``--apply``, force) the fit-score evidence sweep.

THIS SCRIPT IS NOT THE FIX. The remediation runs by itself on every application
start (``app.main._remediate_unscorable_fit_scores``) and inside every
fit-scorer run (``FitScorerAgent.run``), so no operator has to remember
anything. This entrypoint exists to MEASURE the live database — the before/after
evidence an operator or reviewer can reproduce — and to force the sweep between
restarts.

It calls exactly the same functions those two automatic paths call
(:mod:`app.services.fit_score_remediation`); it re-implements nothing.

Usage (from the repo root, with DATABASE_URL pointing at the target DB)::

    apps/api/scripts/fit_score_evidence_sweep.py                # report only
    apps/api/scripts/fit_score_evidence_sweep.py --apply        # sweep now
    apps/api/scripts/fit_score_evidence_sweep.py --user-id <ID> # one account

Report mode writes NOTHING.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_connection, rows_to_dicts  # noqa: E402
from app.services.fit_evidence import (  # noqa: E402
    MIN_SCORABLE_CHARS,
    job_evidence_text,
)
from app.services.fit_score_remediation import (  # noqa: E402
    count_rescorable,
    remediate_unscorable_fit_scores,
    scored_without_evidence,
)


def _breakdown(job_ids: list[str]) -> list[tuple[str, int]]:
    """Per-source counts for the offending ids (report only)."""
    if not job_ids:
        return []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "source", count(*) AS n FROM "Job" WHERE "id" = ANY(%s) '
                'GROUP BY "source" ORDER BY n DESC',
                (job_ids,),
            )
            rows = rows_to_dicts(cur)
    return [(row["source"], row["n"]) for row in rows]


def _worst(job_ids: list[str], limit: int = 5) -> list[tuple[float | None, int, str]]:
    if not job_ids:
        return []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id", "title", "description", "requirements", "fitScore" '
                'FROM "Job" WHERE "id" = ANY(%s) ORDER BY "fitScore" DESC NULLS LAST '
                'LIMIT %s',
                (job_ids, limit),
            )
            rows = rows_to_dicts(cur)
    return [
        (row["fitScore"], len(job_evidence_text(row)), row["title"]) for row in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="clear the offending scores now"
    )
    parser.add_argument("--user-id", default=None, help="scope to one account")
    args = parser.parse_args()

    scope = args.user_id or "all users"
    offenders = scored_without_evidence(args.user_id)
    print(f"gate: >= {MIN_SCORABLE_CHARS} chars of evidence text  (scope: {scope})")
    print(f"scored rows below the gate BEFORE : {len(offenders)}")
    for source, n in _breakdown(offenders):
        print(f"    {source:<20} {n}")
    for score, chars, title in _worst(offenders):
        # ``fitScore`` can be NULL on a half-written pair (atsScore only) —
        # print what is actually there rather than crashing the report.
        shown = f"{score:.2f}" if score is not None else "atsScore only"
        print(f"    top offender: {shown} on {chars} chars — {title!r}")
    print(f"rows with real evidence awaiting a score: {count_rescorable(args.user_id)}")

    if not args.apply:
        print("\nreport only — nothing written (pass --apply to sweep now).")
        return 0

    outcome = remediate_unscorable_fit_scores(args.user_id)
    print(
        f"\nswept: scanned={outcome.scanned} cleared={outcome.cleared} "
        f"before={outcome.before_scored_without_evidence} "
        f"after={outcome.after_scored_without_evidence}"
    )
    print(f"rows with real evidence awaiting a score: {count_rescorable(args.user_id)}")
    if outcome.after_scored_without_evidence:
        print("FAILED: scored rows below the gate remain", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
