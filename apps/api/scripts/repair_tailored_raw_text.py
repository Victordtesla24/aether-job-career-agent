#!/usr/bin/env python3
"""Repair tailored résumé versions whose stored ``raw_text`` lost content.

U2b round 3. Until the fix in :mod:`app.services.resume_document`, every
tailored version persisted its ``raw_text`` as ``strip_bullet_lines(parent) +
the tracked rewrites`` — a bullet-free skeleton with the tailoring loop's own
bullets appended as one flat trailing block. On the live artifact (résumé
``c12187d107bf994471844e09a``) that deleted two skills bullets and an entire
academic degree outright, emptied both ``SKILLS`` sections and
``CERTIFICATIONS`` to bare headings, and re-parented the surviving skills
bullets under ``WORK EXPERIENCE``. The fix stops NEW versions being written that
way; it does nothing for versions already stored, and the download a subscriber
sends an employer is drawn from exactly those.

This script is that missing half. For every tailored version whose parent is
still intact, it re-derives the text the FIXED pipeline would have written —
parent document + this version's own persisted bullets — and, with ``--apply``,
stores it.

  * DRY RUN IS THE DEFAULT. Without ``--apply`` nothing is written: the census
    is printed (and optionally saved with ``--report-out``) naming, per résumé,
    exactly which headings, bullets, lines and contact details its stored text
    no longer states.
  * NOTHING IS DESTROYED. The damaged text is kept verbatim at
    ``sections["rawTextRepair"]["previousRawText"]`` alongside what was found
    missing and when, so any repair can be audited or reversed. The persisted
    bullets — the approved rewrites — are not touched at all, and neither is
    the parent, whose uploaded bytes and ``formatHash`` are immutable anyway
    (``ResumeRepository.update_sections`` re-passes the row's own hash).
  * A VERSION THAT LOST NOTHING IS LEFT ALONE. Rewriting an intact record
    would churn history for no reason and bury the real repairs.
  * THE RESULT IS RE-VERIFIED. After each write the stored row is re-read and
    re-censused; a version that still reports losses is reported as FAILED and
    makes the run exit non-zero, so a partial repair can never read as success.

USAGE::

    # Census only — reads nothing but the résumé rows.
    python scripts/repair_tailored_raw_text.py --report-out census.json

    # Repair one résumé, then everything else once that looks right.
    python scripts/repair_tailored_raw_text.py --resume-id <ID> --apply
    python scripts/repair_tailored_raw_text.py --apply

Run it with ``DATABASE_URL`` pointing at the database to repair; it reads no
secrets of its own.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_connection, rows_to_dicts  # noqa: E402
from app.repositories.resume import ResumeRepository  # noqa: E402
from app.services.resume_repair import raw_text_losses, repair_sections  # noqa: E402


def _tailored_versions(resume_id: str | None) -> list[dict[str, Any]]:
    """``(id, userId, parentId)`` for every tailored version, newest first."""
    sql = (
        'SELECT "id", "userId", "parentId" FROM "Resume" '
        'WHERE "parentId" IS NOT NULL'
    )
    params: tuple[Any, ...] = ()
    if resume_id:
        sql += ' AND "id" = %s'
        params = (resume_id,)
    sql += ' ORDER BY "createdAt" DESC'
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return rows_to_dicts(cur)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-id", help="repair only this tailored version")
    parser.add_argument(
        "--apply", action="store_true", help="write the repairs (default: census only)"
    )
    parser.add_argument("--report-out", help="write the census/result JSON here")
    args = parser.parse_args()

    repo = ResumeRepository()
    report: list[dict[str, Any]] = []
    failed = 0
    for row in _tailored_versions(args.resume_id):
        resume = repo.get_by_id(row["id"], row["userId"])
        parent = repo.get_by_id(row["parentId"], row["userId"])
        if resume is None or parent is None:
            report.append({"id": row["id"], "status": "skipped-no-parent"})
            continue
        losses = raw_text_losses(resume, parent)
        if not losses:
            report.append({"id": row["id"], "status": "intact"})
            continue
        entry: dict[str, Any] = {
            "id": row["id"],
            "parentId": row["parentId"],
            "status": "damaged",
            "lost": list(losses),
        }
        if args.apply:
            repaired = repair_sections(resume, parent)
            if repaired is None:
                # Unreachable while losses is non-empty; raising rather than
                # writing keeps a future divergence loud instead of silent.
                raise RuntimeError(f"{row['id']}: censused as damaged, no repair built")
            stored = repo.update_sections(
                row["id"], row["userId"], repaired, resume.get("formatHash") or ""
            )
            after = raw_text_losses(stored or resume, parent)
            entry["status"] = "repaired" if not after else "FAILED"
            entry["remaining"] = list(after)
            failed += 1 if after else 0
        report.append(entry)

    summary = {
        "applied": args.apply,
        "examined": len(report),
        "damaged": sum(1 for e in report if e["status"] != "intact"),
        "repaired": sum(1 for e in report if e["status"] == "repaired"),
        "failed": failed,
        "resumes": report,
    }
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.report_out:
        Path(args.report_out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
