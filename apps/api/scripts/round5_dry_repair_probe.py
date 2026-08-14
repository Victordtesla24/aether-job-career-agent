#!/usr/bin/env python3
"""READ-ONLY proof that the round-5 census is repairable, before any write.

Builds each damaged version's repaired ``sections`` IN MEMORY (never stored) and
re-censuses the result, so the operator can see whether a bulk ``--apply`` would
converge — the script's own post-write re-census, run before the write instead
of after it. Nothing is inserted, updated or deleted; the only SQL issued is the
same ``SELECT`` ``repair_tailored_raw_text.py`` uses.
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
from app.repositories.resume import ResumeRepository  # noqa: E402
from app.services.resume_repair import raw_text_losses, repair_sections  # noqa: E402


def _rows(limit: int | None) -> list[dict[str, Any]]:
    sql = (
        'SELECT "id", "userId", "parentId" FROM "Resume" '
        'WHERE "parentId" IS NOT NULL ORDER BY "createdAt" DESC'
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return rows_to_dicts(cur)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report-out", required=True)
    args = parser.parse_args()

    repo = ResumeRepository()
    report: list[dict[str, Any]] = []
    for row in _rows(args.limit):
        resume = repo.get_by_id(row["id"], row["userId"])
        parent = repo.get_by_id(row["parentId"], row["userId"])
        if resume is None or parent is None:
            report.append({"id": row["id"], "outcome": "skipped-no-parent"})
            continue
        before = raw_text_losses(resume, parent)
        if not before:
            report.append({"id": row["id"], "outcome": "intact"})
            continue
        repaired = repair_sections(resume, parent)
        if repaired is None:
            report.append({"id": row["id"], "outcome": "no-repair-built"})
            continue
        after = raw_text_losses({**resume, "sections": repaired}, parent)
        report.append(
            {
                "id": row["id"],
                "outcome": "would-repair" if not after else "would-REMAIN-damaged",
                "lostBefore": len(before),
                "remainingAfter": list(after)[:5],
                "previousRawTextPreserved": (
                    repaired["rawTextRepair"]["previousRawText"]
                    == str((resume.get("sections") or {}).get("raw_text", "") or "")
                ),
            }
        )

    summary = {
        "wrote_anything": False,
        "examined": len(report),
        "outcomes": dict(Counter(entry["outcome"] for entry in report)),
        "resumes": report,
    }
    Path(args.report_out).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "resumes"}, indent=2))
    return 1 if summary["outcomes"].get("would-REMAIN-damaged") else 0


if __name__ == "__main__":
    raise SystemExit(main())
