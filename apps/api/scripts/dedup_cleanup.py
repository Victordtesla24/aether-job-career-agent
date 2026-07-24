#!/usr/bin/env python3
"""Dedup cleanup script — Phase 2A NULL sourceUrl dedup fix.

Finds and removes duplicate Job records, keeping the OLDEST record and
re-linking any Applications/Resumes from deleted duplicates to the kept record.

Usage:
    # DRY-RUN — report what would happen without modifying anything
    python scripts/dedup_cleanup.py --dry-run

    # REAL RUN — execute the dedup (wrapped in a transaction)
    python scripts/dedup_cleanup.py

The script reads DATABASE_URL from the environment (same .env as the API).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- Path setup: run from repo root or apps/api/ ---
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "apps" / "api" / "app") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
    sys.path.insert(0, str(_REPO_ROOT / "apps" / "api" / "app"))

# Load .env so DATABASE_URL is available
try:
    from dotenv import load_dotenv

    _env_path = _REPO_ROOT / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass  # python-dotenv not installed — expect DATABASE_URL in env already

import psycopg2


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


# ---------------------------------------------------------------------------
# Dedup hashing (mirrors app.services.dedup, standalone for the script)
# ---------------------------------------------------------------------------


def compute_null_source_url_hash(
    user_id: str, title: str, company: str, location: str | None
) -> str:
    key = (
        f"{user_id}|"
        f"{title.lower().strip()}|"
        f"{company.lower().strip()}|"
        f"{(location or '').lower().strip()}"
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


@dataclass
class DuplicateGroup:
    """A group of duplicate job records for the same user."""

    user_id: str
    title: str
    company: str
    locations: str  # "location1 | location2 | ..."
    records: list[dict] = field(default_factory=list)

    @property
    def kept_id(self) -> str:
        """Return the ID of the oldest record (to keep)."""
        return min(self.records, key=lambda r: r["createdAt"])["id"]

    @property
    def removed_ids(self) -> list[str]:
        """Return IDs of records to delete (all except oldest)."""
        kept = self.kept_id
        return [r["id"] for r in self.records if r["id"] != kept]

    @property
    def count(self) -> int:
        return len(self.records)


def find_duplicate_groups(cur) -> list[DuplicateGroup]:
    """Find all duplicate job groups across the database.

    A duplicate is defined as: same userId, same title (case-insensitive
    trimmed), same company (case-insensitive trimmed).  This catches the
    NULL-sourceUrl case AND cases where sourceUrls differ slightly.
    """
    cur.execute(
        """
        SELECT "id", "userId", "title", "company", "location",
               "sourceUrl", "status", "createdAt"
        FROM "Job"
        ORDER BY "userId", LOWER(TRIM("title")), LOWER(TRIM("company")), "createdAt"
        """
    )
    rows = cur.fetchall()
    columns = [col.name for col in cur.description]

    # Group by (userId, normalized_title, normalized_company)
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        record = dict(zip(columns, row))
        key = (
            record["userId"],
            record["title"].lower().strip(),
            record["company"].lower().strip(),
        )
        groups.setdefault(key, []).append(record)

    result = []
    for (user_id, title_norm, company_norm), records in groups.items():
        if len(records) <= 1:
            continue
        # Use the first record's display title/company
        first = records[0]
        locations = " | ".join(
            sorted({(r["location"] or "(none)") for r in records})
        )
        result.append(
            DuplicateGroup(
                user_id=user_id,
                title=first["title"],
                company=first["company"],
                locations=locations,
                records=records,
            )
        )

    return result


def count_linked_records(cur, job_id: str) -> dict[str, int]:
    """Count Applications and Resumes linked to a given job."""
    cur.execute(
        'SELECT COUNT(*) FROM "Application" WHERE "jobId" = %s', (job_id,)
    )
    app_count = cur.fetchone()[0]

    cur.execute(
        'SELECT COUNT(*) FROM "Resume" WHERE "sourceJobId" = %s', (job_id,)
    )
    resume_count = cur.fetchone()[0]

    return {"applications": app_count, "resumes": resume_count}


def relink_records(cur, from_job_id: str, to_job_id: str) -> dict[str, int]:
    """Re-link all Applications and Resumes from `from_job_id` to `to_job_id`.

    Returns dict of {applications: N, resumes: M} for how many were moved.
    """
    cur.execute(
        'UPDATE "Application" SET "jobId" = %s WHERE "jobId" = %s',
        (to_job_id, from_job_id),
    )
    apps_moved = cur.rowcount

    cur.execute(
        'UPDATE "Resume" SET "sourceJobId" = %s WHERE "sourceJobId" = %s',
        (to_job_id, from_job_id),
    )
    resumes_moved = cur.rowcount

    return {"applications": apps_moved, "resumes": resumes_moved}


def delete_job(cur, job_id: str) -> bool:
    """Delete a single job record. Returns True if a row was deleted."""
    cur.execute('DELETE FROM "Job" WHERE "id" = %s', (job_id,))
    return cur.rowcount == 1


def run_dry_run() -> int:
    """Examine duplicates and report what would happen, without modifying data.

    Returns 0 on success (no issues or dry-run completed), 1 if errors.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            groups = find_duplicate_groups(cur)

            if not groups:
                print("✅ No duplicate job groups found.")
                return 0

            print(f"🔍 DRY-RUN: Found {len(groups)} duplicate group(s)\n")
            total_to_remove = 0

            for i, group in enumerate(groups, 1):
                print(f"{'─' * 60}")
                print(f"Group {i}: \"{group.title}\" @ {group.company}")
                print(f"  User: {group.user_id}")
                print(f"  Locations: {group.locations}")
                print(f"  Records: {group.count}")
                kept = group.kept_id
                removed = group.removed_ids

                # Show linked records per job
                for rec in group.records:
                    linked = count_linked_records(cur, rec["id"])
                    marker = " ← KEEP (oldest)" if rec["id"] == kept else " ← DELETE"
                    print(
                        f"    {rec['id']} | status={rec['status']} | "
                        f"sourceUrl={rec.get('sourceUrl', 'NULL')} | "
                        f"created={rec['createdAt'].isoformat() if rec['createdAt'] else 'NULL'}"
                        f"{marker}"
                    )
                    if linked["applications"] or linked["resumes"]:
                        print(
                            f"      ↳ {linked['applications']} application(s), "
                            f"{linked['resumes']} tailored resume(s)"
                        )

                total_to_remove += len(removed)
                print()

            print(f"{'═' * 60}")
            print(f"SUMMARY: {len(groups)} duplicate group(s), "
                  f"{total_to_remove} record(s) would be deleted")
            print()
            print("Run without --dry-run to execute the cleanup.")
            return 0
    finally:
        conn.close()


def run_real() -> int:
    """Execute the dedup cleanup in a transaction.

    Steps per duplicate group:
    1. Re-link Applications from removed → kept
    2. Re-link Resumes from removed → kept
    3. Delete removed job records
    All within a single transaction so it rolls back on any error.

    Returns 0 on success, 1 on error.
    """
    conn = get_connection()
    deletions_log: list[dict] = []

    try:
        with conn:
            with conn.cursor() as cur:
                groups = find_duplicate_groups(cur)

                if not groups:
                    print("✅ No duplicate job groups found. Nothing to do.")
                    return 0

                print(f"🔧 Cleaning {len(groups)} duplicate group(s)...\n")
                total_removed = 0

                for i, group in enumerate(groups, 1):
                    kept_id = group.kept_id
                    removed_ids = group.removed_ids

                    print(f"{'─' * 60}")
                    print(f"Group {i}: \"{group.title}\" @ {group.company}")
                    print(f"  User: {group.user_id}")
                    print(f"  KEEP:  {kept_id} (oldest)")
                    print(f"  DELETE: {', '.join(removed_ids)}")

                    for rem_id in removed_ids:
                        # Re-link before deleting
                        linked = relink_records(cur, rem_id, kept_id)
                        if linked["applications"] or linked["resumes"]:
                            print(
                                f"    ↳ Re-linked from {rem_id}: "
                                f"{linked['applications']} app(s), "
                                f"{linked['resumes']} resume(s)"
                            )

                        # Delete
                        deleted = delete_job(cur, rem_id)
                        if deleted:
                            log_entry = {
                                "action": "DELETE",
                                "removed_id": rem_id,
                                "kept_id": kept_id,
                                "title": group.title,
                                "company": group.company,
                                "user_id": group.user_id,
                                "apps_relinked": linked["applications"],
                                "resumes_relinked": linked["resumes"],
                            }
                            deletions_log.append(log_entry)
                            total_removed += 1
                            print(f"    ✅ Deleted {rem_id}")
                        else:
                            print(f"    ⚠️  Failed to delete {rem_id}")

                    print()

                print(f"{'═' * 60}")
                print(f"SUMMARY: Cleaned {len(groups)} duplicate group(s), "
                      f"deleted {total_removed} record(s)")

                # Print full deletion log
                if deletions_log:
                    print(f"\n📋 Full deletion log:")
                    for entry in deletions_log:
                        print(
                            f"  DELETE {entry['removed_id']} → KEPT {entry['kept_id']} "
                            f"({entry['title']} @ {entry['company']}, "
                            f"user={entry['user_id']}, "
                            f"apps={entry['apps_relinked']}, "
                            f"resumes={entry['resumes_relinked']})"
                        )

            conn.commit()
            print("\n✅ Dedup cleanup committed successfully.")
            return 0

    except Exception as exc:
        print(f"\n❌ Error during cleanup: {exc}")
        print("Transaction rolled back — no changes were persisted.")
        return 1
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Dedup cleanup for Job table")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report what would happen without modifying data (default: False)",
    )
    args = parser.parse_args()

    if args.dry_run:
        sys.exit(run_dry_run())
    else:
        sys.exit(run_real())


if __name__ == "__main__":
    main()
