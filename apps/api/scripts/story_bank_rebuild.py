#!/usr/bin/env python3
"""Story Bank rebuild — audit, back up, clear, regenerate. Reversible.

STORY-BANK-REBUILD-2026-08-02. Audited live against the production database:
the owner's Story Bank held 43 rows describing only ~10 distinct achievements
(33 near-duplicate re-tellings, e.g. four separate rows for the single "JIRA
Analytics Dashboard" résumé bullet), two of them carrying no metric at all,
while ~17 genuinely distinct résumé achievements had no story whatsoever. That
bank is not reusable material for the tailoring and cover-letter agents that
consume it; it is noise that crowds out the evidence they need.

This script rebuilds it from the user's OWN résumé through the source-grounded
extractor (``app.agents.story_extractor``), whose stories cite a real résumé
bullet, carry only metrics that bullet evidences, and are deduped on a stable
per-user achievement key.

WHY "CLEAR" HERE MEANS ARCHIVE, NOT DELETE
------------------------------------------
Verified before writing a line of this script, on the live database:

* NO foreign key anywhere in the schema references ``StoryEntry``
  (``SELECT ... FROM pg_constraint WHERE contype='f' AND
  confrelid='"StoryEntry"'::regclass`` → 0 rows), and no column in any table
  is named ``*story*``. Nothing structurally depends on a story row.
* BUT 17 ``AgentRun`` rows (15 ``storyExtractor``, 2 ``interviewPrep``)
  embed story ids inside their ``output`` JSON. ``interviewPrep`` in
  particular persists ``suggestedStoryId`` handles into its run output, which
  the Interviews screen renders. A physical DELETE would leave those audit
  and prep records pointing at ids that no longer resolve — silently
  destroying the provenance of work the user has already seen.

So the rows are ARCHIVED, using the archive columns the bulk de-dup sweep
already established (``archivedAt`` / ``mergeSnapshot``;
``app.db.ensure_story_archive_columns``). An archived row is invisible to
every listing, evidence-selection and scoring path (they all read through
``StoryRepository.list_by_user``, which filters ``archivedAt IS NULL``), so
the bank is genuinely "cleared" from the product's point of view — while
``StoryRepository.get_by_id`` still resolves it, so those 17 AgentRun
references stay meaningful and ``--restore-batch`` can put every row back.

A full JSON dump of every row is ALSO written before anything is touched.

SAFETY
------
* DRY RUN IS THE DEFAULT. Without ``--apply`` the script only reads: it
  prints the audit, writes the backup file, and stops.
* WRITING NEEDS THE USER ID RE-STATED (``--confirm-user-id``) and a backup
  file that was successfully written first.
* Before/after live-row counts are printed and reconciled.
* ``--restore-batch <id>`` un-archives everything a given clear archived.

USAGE::

    # 1. Audit + backup only (writes nothing to the database).
    python scripts/story_bank_rebuild.py --user-id <ID> --backup-dir /path

    # 2. Clear + regenerate (real LLM run, real résumé).
    python scripts/story_bank_rebuild.py --user-id <ID> --apply \\
        --confirm-user-id <ID> --operator "vikram" --backup-dir /path

    # Reverse a clear.
    python scripts/story_bank_rebuild.py --user-id <ID> \\
        --restore-batch <BATCH_ID> --apply --confirm-user-id <ID>
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import (  # noqa: E402
    ensure_story_achievement_column,
    ensure_story_archive_columns,
    get_connection,
    rows_to_dicts,
)
from app.services.resume_bullets import (  # noqa: E402
    achievement_key,
    extract_resume_bullets,
)
from app.services.resume_grounding import resolve_user_resume_text  # noqa: E402

_ALL_COLUMNS = (
    '"id", "userId", "title", "situation", "task", "action", "result", '
    '"metrics", "tags", "createdAt", "updatedAt", "contentHash", '
    '"archivedAt", "mergedIntoId", "mergeSnapshot", "achievementKey"'
)

_CLEAR_REASON = "story-bank-rebuild: superseded by source-grounded regeneration"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _executing_account() -> dict[str, str]:
    try:
        account = getpass.getuser()
    except Exception:  # noqa: BLE001 — a nameless account must not abort a run
        account = str(os.getuid())
    return {"account": account, "host": socket.gethostname()}


def _fetch(user_id: str, *, live_only: bool) -> list[dict[str, Any]]:
    ensure_story_archive_columns()
    ensure_story_achievement_column()
    sql = f'SELECT {_ALL_COLUMNS} FROM "StoryEntry" WHERE "userId" = %s'
    if live_only:
        sql += ' AND "archivedAt" IS NULL'
    sql += ' ORDER BY "createdAt"'
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id,))
            return rows_to_dicts(cur)


def _audit(rows: list[dict[str, Any]], user_id: str, resume_text: str) -> dict[str, Any]:
    """Real, countable facts about the current bank — no estimates."""
    bullets = extract_resume_bullets(resume_text)
    keys = {achievement_key(user_id, b["text"]): b["id"] for b in bullets}
    evidence_metrics = [
        {k: v for k, v in (r["metrics"] or {}).items() if not k.startswith("__")}
        for r in rows
    ]
    covered: dict[str, list[str]] = {}
    for row in rows:
        key = row.get("achievementKey")
        if key in keys:
            covered.setdefault(keys[key], []).append(row["id"])
    return {
        "live_rows": len(rows),
        "unquantified_rows": sum(1 for m in evidence_metrics if not m),
        "rows_with_achievement_key": sum(1 for r in rows if r.get("achievementKey")),
        "resume_bullets": len(bullets),
        "bullets_covered": len(covered),
        "bullets_uncovered": [b["id"] for b in bullets if b["id"] not in covered],
        "duplicate_bullets": {k: v for k, v in covered.items() if len(v) > 1},
        "titles": [r["title"] for r in rows],
    }


def _write_backup(directory: Path, user_id: str, rows: list[dict[str, Any]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"storyentry-backup-{user_id}-{stamp}.json"
    path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return path


def _clear(user_id: str, batch_id: str, operator: str | None, backup: Path) -> int:
    """Archive every LIVE row. Returns how many were archived."""
    ensure_story_archive_columns()
    snapshot_base = {
        "batch_id": batch_id,
        "reason": _CLEAR_REASON,
        "cleared_at": _now_iso(),
        "operator": operator,
        "backup_file": str(backup),
        "executed_by": _executing_account(),
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","title","situation","task","action","result",'
                '"metrics","tags" FROM "StoryEntry" '
                'WHERE "userId" = %s AND "archivedAt" IS NULL',
                (user_id,),
            )
            live = rows_to_dicts(cur)
            for row in live:
                cur.execute(
                    'UPDATE "StoryEntry" SET "archivedAt" = NOW(), '
                    '"mergeSnapshot" = %s::jsonb, "updatedAt" = NOW() '
                    'WHERE "id" = %s AND "userId" = %s AND "archivedAt" IS NULL',
                    (
                        json.dumps(
                            {**snapshot_base, "survivor_before": row}, default=str
                        ),
                        row["id"],
                        user_id,
                    ),
                )
        conn.commit()
    return len(live)


def _restore(user_id: str, batch_id: str) -> int:
    ensure_story_archive_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "StoryEntry" SET "archivedAt" = NULL, "updatedAt" = NOW() '
                'WHERE "userId" = %s AND "archivedAt" IS NOT NULL '
                'AND "mergeSnapshot"->>\'batch_id\' = %s '
                'AND "mergeSnapshot"->>\'reason\' = %s',
                (user_id, batch_id, _CLEAR_REASON),
            )
            restored = cur.rowcount
        conn.commit()
    return restored


def _load_env() -> None:
    """Load the repo-root ``.env`` WITHOUT overriding anything already set.

    Called from :func:`main` only — never at import time — so importing this
    module (e.g. for a unit test) can never pull the production
    ``DATABASE_URL`` into the process. Mirrors
    ``scripts/clear_cover_suppression.py``.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover — expect the vars already exported
        return
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--apply", action="store_true", help="actually write")
    parser.add_argument("--confirm-user-id", default=None)
    parser.add_argument("--operator", default=None)
    parser.add_argument(
        "--backup-dir",
        default=str(Path.home() / "aether-backups" / "story-bank"),
        help="where the pre-change JSON dump is written",
    )
    parser.add_argument("--restore-batch", default=None)
    parser.add_argument(
        "--no-regenerate",
        action="store_true",
        help="clear only; do not run the extractor afterwards",
    )
    parser.add_argument(
        "--regenerate-only",
        action="store_true",
        help=(
            "skip the clear and only run the extractor. Safe to repeat: the "
            "achievement key makes a covered bullet refresh in place, and "
            "uncovered bullets are attempted first, so repeated runs converge "
            "on full résumé coverage without ever duplicating a story."
        ),
    )
    args = parser.parse_args(argv)

    user_id = args.user_id
    if args.restore_batch:
        if not args.apply:
            print("DRY RUN — pass --apply to restore.")
            return 0
        if args.confirm_user_id != user_id:
            print("REFUSED: --confirm-user-id must repeat --user-id.")
            return 2
        restored = _restore(user_id, args.restore_batch)
        print(f"restored {restored} archived row(s) from batch {args.restore_batch}")
        return 0

    resume_text = resolve_user_resume_text(user_id, allow_operator_fallback=False)
    if not resume_text.strip():
        print("REFUSED: this user has no résumé of their own to ground stories on.")
        return 2

    before = _fetch(user_id, live_only=True)
    audit = _audit(before, user_id, resume_text)
    print("=== AUDIT (before) ===")
    print(json.dumps({k: v for k, v in audit.items() if k != "titles"}, indent=2))

    backup = _write_backup(Path(args.backup_dir), user_id, _fetch(user_id, live_only=False))
    print(f"backup written: {backup} ({backup.stat().st_size} bytes)")

    if not args.apply:
        print("DRY RUN — nothing written to the database. Pass --apply to rebuild.")
        return 0
    if args.confirm_user_id != user_id:
        print("REFUSED: --confirm-user-id must repeat --user-id.")
        return 2

    if args.regenerate_only:
        print("regenerate-only — the existing bank is left in place.")
    else:
        batch_id = uuid.uuid4().hex
        archived = _clear(user_id, batch_id, args.operator, backup)
        print(f"cleared (archived) {archived} row(s) — batch {batch_id}")
        print(
            f"reverse with: --restore-batch {batch_id} --apply "
            f"--confirm-user-id {user_id}"
        )

    if args.no_regenerate:
        return 0

    # Dispatch through the SAME entrypoint the product uses, not the agent
    # class directly: that is what records the run as an ``AgentRun`` with its
    # real model and real cost. A maintenance run that spends the user's LLM
    # budget invisibly would make the billing ledger wrong by exactly that
    # amount.
    from app.routers.agents import _dispatch

    output = _dispatch(user_id, "storyExtractor", {})
    print("=== REGENERATION ===")
    print(json.dumps(output, indent=2, default=str))
    created = int(output.get("created") or 0)

    after = _fetch(user_id, live_only=True)
    print("=== AUDIT (after) ===")
    print(
        json.dumps(
            {k: v for k, v in _audit(after, user_id, resume_text).items() if k != "titles"},
            indent=2,
        )
    )
    if not args.regenerate_only and len(after) != created:
        print(
            f"WARNING: {len(after)} live rows but the run reports {created} "
            "created — investigate before trusting this bank."
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — operator entrypoint
    raise SystemExit(main())
