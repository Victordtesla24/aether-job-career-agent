#!/usr/bin/env python3
"""One-off, IDEMPOTENT migration of the external growth-engine Google-Sheet
export into the native Sales Agent tables. Safe to re-run any number of times.

Inputs (all optional — each section is skipped with an honest note if its
source file is missing):

* ``~/growth_sheet_export/Suppression_List.csv`` → ``SalesSuppressionList``
  (direct SQL so the ORIGINAL ``suppressedAt`` dates are preserved — the
  repository's ``suppress()`` would stamp NOW(), which would falsify history).
* ``~/growth_sheet_export/Prospects.csv`` → ``SalesLead`` via the repo's
  consent-validating ``create_lead`` (source ``inbound_email``, consent
  ``inbound_signal``, evidence = the REAL Gmail message id from the sheet).
* LinkedIn content calendar (Google Doc export) → ``SalesOutreachLog`` rows,
  channel ``linkedin_draft`` / outcome ``draft_queued``, one per historical
  post, tagged ``imported:linkedin-calendar:post-NN`` in ``detail`` (the
  idempotency marker — an existing row with the same marker is never
  duplicated).
* ``Email_Log.csv`` / ``Learnings.csv`` have NO destination table by design —
  the email log describes sends made by the OLD external engine (not this
  agent; inventing ``sent`` rows here would fabricate this agent's audit
  trail) and learnings are prose. Both are noted in the delivery doc instead.

Usage (repo root):  python3 scripts/migrate_growth_sheet.py [--calendar PATH]
Prints a JSON summary of inserted / already-present counts.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "apps" / "api"
EXPORT_DIR = Path.home() / "growth_sheet_export"


def load_env(env_file: Path) -> None:
    """Repo .env loader — existing environment variables win (no override)."""
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def migrate_suppressions(path: Path) -> dict[str, int]:
    """Direct SQL insert preserving the sheet's original suppression dates."""
    from app.db import get_connection  # noqa: PLC0415

    inserted = existing = 0
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    with get_connection() as conn:
        with conn.cursor() as cur:
            for row in rows:
                email = (row.get("Email") or row.get("email") or "").strip().lower()
                if not email:
                    continue
                date = (row.get("Date_Suppressed") or row.get("date") or "").strip()
                reason = (row.get("Reason") or "requested").strip().lower()
                thread = (row.get("Source_Thread_Id") or row.get("Thread_ID") or "").strip() or None
                # Original sheet dates are date-only; midday AEST keeps the
                # calendar day stable regardless of the reader's timezone.
                cur.execute(
                    '''
                    INSERT INTO "SalesSuppressionList"
                        ("email","reason","suppressedAt","sourceThreadId")
                    VALUES (%s, %s, (%s || ' 12:00:00+10')::timestamptz, %s)
                    ON CONFLICT ("email") DO NOTHING
                    ''',
                    (email, reason, date, thread),
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    existing += 1
        conn.commit()
    return {"inserted": inserted, "alreadyPresent": existing}


def migrate_prospects(path: Path) -> dict[str, int]:
    """Prospects → SalesLead through the consent-validating repository."""
    from app.repositories.sales import SalesRepository  # noqa: PLC0415

    from app.db import get_connection  # noqa: PLC0415

    repo = SalesRepository()
    inserted = existing = 0
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        email = (row.get("Email_or_LinkedIn") or row.get("Email") or "").strip().lower()
        if not email or "@" not in email:
            continue  # LinkedIn-only prospects have no email — nothing to store
        # Honest insert/already-present split: pre-check by email (create_lead
        # itself is ON CONFLICT DO NOTHING, so a re-run never duplicates).
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT 1 FROM "SalesLead" WHERE LOWER("email") = %s LIMIT 1',
                    (email,),
                )
                if cur.fetchone() is not None:
                    existing += 1
                    continue
        name = (row.get("Name") or "").strip() or None
        msgid = (row.get("Consent_Evidence") or "").strip()
        thread = msgid or None
        status = (row.get("Status") or "new").strip().lower()
        repo.create_lead(
            email=email,
            consent_type="inbound_signal",
            consent_evidence=(
                f"gmail message {msgid} — imported from external growth-sheet "
                "Prospects export"
            ),
            source="inbound_email",
            name=name,
            source_thread_id=thread,
            status=status,
        )
        inserted += 1
    return {"inserted": inserted, "alreadyPresent": existing}


_POST_RE = re.compile(r"^Post (\d+) — (.+)$")
_BATCH_RE = re.compile(r"^Batch \d+ — (\d{4}-\d{2}-\d{2})$")


def parse_calendar(text: str) -> list[dict[str, str]]:
    """Split the calendar export into posts: number, title, batch date, body."""
    posts: list[dict[str, str]] = []
    batch_date = ""
    current: dict[str, str] | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal current, body
        if current is not None:
            current["body"] = "\n".join(body).strip()
            posts.append(current)
        current, body = None, []

    for line in text.splitlines():
        stripped = line.strip().lstrip("\ufeff")
        m = _BATCH_RE.match(stripped)
        if m:
            flush()
            batch_date = m.group(1)
            continue
        m = _POST_RE.match(stripped)
        if m:
            flush()
            current = {"num": m.group(1), "title": m.group(2), "date": batch_date}
            continue
        if current is not None:
            body.append(line.rstrip())
    flush()
    return posts


def migrate_linkedin(calendar_path: Path) -> dict[str, int]:
    from app.db import get_connection  # noqa: PLC0415
    from app.repositories.sales import SalesRepository  # noqa: PLC0415

    repo = SalesRepository()
    posts = parse_calendar(calendar_path.read_text(encoding="utf-8"))
    inserted = existing = 0
    for post in posts:
        marker = f"imported:linkedin-calendar:post-{int(post['num']):02d}"
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT 1 FROM "SalesOutreachLog" WHERE "detail" LIKE %s LIMIT 1',
                    (marker + "%",),
                )
                found = cur.fetchone() is not None
        if found:
            existing += 1
            continue
        repo.record_outreach(
            channel="linkedin_draft",
            outcome="draft_queued",
            subject=f"LinkedIn draft (imported) — {post['title']}",
            body=post["body"],
            detail=f"{marker} (batch {post['date']}) — historical draft imported "
                   "from the external content-calendar doc; posting stays manual",
        )
        inserted += 1
    return {"posts": len(posts), "inserted": inserted, "alreadyPresent": existing}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--calendar",
        default="/tmp/linkedin_calendar.txt",
        help="path to the plain-text LinkedIn calendar export",
    )
    args = ap.parse_args()
    load_env(REPO_ROOT / ".env")
    sys.path.insert(0, str(API_DIR))

    summary: dict[str, object] = {}

    supp = EXPORT_DIR / "Suppression_List.csv"
    summary["suppressions"] = (
        migrate_suppressions(supp) if supp.is_file() else "skipped — file missing"
    )

    pros = EXPORT_DIR / "Prospects.csv"
    summary["prospects"] = (
        migrate_prospects(pros) if pros.is_file() else "skipped — file missing"
    )

    cal = Path(args.calendar)
    summary["linkedinDrafts"] = (
        migrate_linkedin(cal) if cal.is_file() else "skipped — file missing"
    )

    summary["emailLogAndLearnings"] = (
        "not migrated by design — no destination table; noted in delivery doc"
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
