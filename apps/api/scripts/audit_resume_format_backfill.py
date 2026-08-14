#!/usr/bin/env python3
"""READ-ONLY backfill audit: how many résumé rows can still be format-preserved.

MODELS-LIVE R-FMT binding scope item 6 / SYNTHESIS §3 item 5: the retention
migration (U2a, ``originalFile``) cannot reach backward, so some existing rows
have no source document to preserve. This audit COUNTS those rows — it never
writes — so an operator knows how large the "re-upload to restore format" legacy
population is before any messaging or bulk action.

A row is *format-preservable* on download when the document it derives from has
a source we can reproduce:

* it stores its own ``originalFile`` bytes (a post-U2a upload), OR
* its ``formatHash`` matches a bundled operator asset on disk
  (``resolve_original_pdf`` — the download endpoint's OWN rule), OR
* it is a tailored child whose PARENT satisfies either of the above (the
  download resolves a child's format through its parent).

Everything else — ``originalFile IS NULL`` AND no bundled-hash match AND (for a
child) a parent in the same state — is the legacy population that must be told to
re-upload, exactly as the download/Studio now says. Rows are resolved against
their parent so a child is never miscounted as unrecoverable when its baseline is
fine.

The only SQL issued is a single ``SELECT``; nothing is inserted, updated or
deleted. Run it against production READ credentials to size the population.

Usage:
    python scripts/audit_resume_format_backfill.py [--report-out PATH] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_connection, rows_to_dicts  # noqa: E402
from app.services.resume_pdf import bundled_format_hashes  # noqa: E402


def _rows(limit: int | None) -> list[dict[str, Any]]:
    sql = (
        'SELECT "id", "parentId", "formatHash", "label", "sourceJobId", '
        '"originalFile" IS NOT NULL AS "hasOriginal" '
        'FROM "Resume" ORDER BY "createdAt" ASC'
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return rows_to_dicts(cur)


def _own_preservable(row: dict[str, Any], bundled: set[str]) -> bool:
    """True when THIS row (ignoring any parent) has a reproducible source."""
    if row.get("hasOriginal"):
        return True
    format_hash = row.get("formatHash")
    return bool(format_hash) and format_hash in bundled


def classify(rows: list[dict[str, Any]], bundled: set[str]) -> list[dict[str, Any]]:
    by_id = {row["id"]: row for row in rows}
    classified: list[dict[str, Any]] = []
    for row in rows:
        parent = by_id.get(row.get("parentId")) if row.get("parentId") else None
        is_tailored = row.get("parentId") is not None
        if _own_preservable(row, bundled):
            reason = (
                "retained-original"
                if row.get("hasOriginal")
                else "bundled-hash-match"
            )
            preservable = True
        elif parent is not None and _own_preservable(parent, bundled):
            reason = "via-parent-original"
            preservable = True
        elif is_tailored and parent is None:
            # A child whose parent row is not in this result set (e.g. a --limit
            # cut, or an orphaned parentId). We cannot prove preservability, so it
            # is reported honestly as unresolved rather than assumed either way.
            reason = "parent-unresolved"
            preservable = False
        else:
            reason = "needs-reupload"
            preservable = False
        classified.append(
            {
                "id": row["id"],
                "isTailored": is_tailored,
                "hasOriginal": bool(row.get("hasOriginal")),
                "preservable": preservable,
                "reason": reason,
            }
        )
    return classified


def summarise(classified: list[dict[str, Any]]) -> dict[str, Any]:
    base = [r for r in classified if not r["isTailored"]]
    tailored = [r for r in classified if r["isTailored"]]
    needs_reupload = [r for r in classified if r["reason"] == "needs-reupload"]
    return {
        "wrote_anything": False,
        "examined": len(classified),
        "base_rows": len(base),
        "tailored_rows": len(tailored),
        "preservable": sum(1 for r in classified if r["preservable"]),
        "affected_needs_reupload": len(needs_reupload),
        "affected_needs_reupload_base": sum(
            1 for r in needs_reupload if not r["isTailored"]
        ),
        "affected_needs_reupload_tailored": sum(
            1 for r in needs_reupload if r["isTailored"]
        ),
        "reasons": dict(Counter(r["reason"] for r in classified)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--report-out",
        default=None,
        help="Optional path to write the full per-row classification as JSON.",
    )
    args = parser.parse_args()

    bundled = bundled_format_hashes()
    classified = classify(_rows(args.limit), bundled)
    summary = summarise(classified)

    if args.report_out:
        Path(args.report_out).write_text(
            json.dumps({**summary, "resumes": classified}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
