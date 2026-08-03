#!/usr/bin/env python3
"""Story Bank NARRATIVE grounding — audit, and remediate. Reversible.

STORY-NARRATIVE-GROUNDING-2026-08-03. The extractor's anti-fabrication guard
inspected only the ``metrics`` dict, while the agents that consume the Story
Bank (``tailor_agent.build_story_evidence``, the cover-letter evidence block)
read the STAR PROSE. Measured with this script against the production database
before the fix, on the owner's 17 live stories:

* 15 of 17 carried a number in situation/task/action/result that their own
  cited résumé bullet does not evidence;
* 7 of 17 carried a number that appears NOWHERE in the résumé at all;
* 1 carried an employer tag belonging to a different job entirely.

This script is both halves of closing that: the MEASUREMENT (so the before /
after claim is reproducible by anyone, not asserted) and the REMEDIATION of
the rows that are already polluted.

WHAT REMEDIATION DOES — and what it deliberately does not
---------------------------------------------------------
Every decision is made by the SAME code the live guard uses
(``StoryExtractorAgent._ground_narrative``), so the bank cannot end up in a
state the extractor would refuse to produce:

* FABRICATED number (nowhere in the résumé) -> the row is ARCHIVED. Not
  edited: a story that invented a measurement has proven the prose around it
  is not derived from the résumé either.
* BORROWED number (real, but belongs to another bullet) -> the ONE sentence
  carrying it is deleted. Nothing is rewritten, nothing is added; if what
  survives is too thin to be a usable story the row is archived instead.
* An unevidenced METRIC entry is dropped; if that empties the metrics of a
  story whose bullet IS quantified, the row is archived (the extractor would
  not have created it).
* A tag naming a résumé employer that is NOT the employer of the cited
  bullet's own section is removed.

Nothing here writes new prose. The only edits are deletions, so no remediated
story can assert anything the user's own résumé does not already state.

REVERSIBILITY
-------------
* A full JSON dump of every row (live and archived) is written BEFORE any
  write, and the path is printed.
* Every row this script touches also gets a ``mergeSnapshot`` carrying the
  complete pre-image and the batch id, so ``--restore-batch`` restores the
  exact prior content — including rows that were only stripped, which is why
  the snapshot is written on live rows too.
* The snapshot key is ``remediation_before``, deliberately NOT the
  ``survivor_before`` the de-dup sweep uses, so the sweep's restore path
  (``story_dedup_migration.restore_merged_stories``) treats these rows as none
  of its business rather than trying to unwind them as merges.
* Archiving is a soft archive: the row stays resolvable by id, so the
  ``AgentRun`` outputs that embed story ids keep their provenance.

SAFETY
------
* DRY RUN IS THE DEFAULT. Without ``--apply`` the script only reads.
* Writing needs the user id restated (``--confirm-user-id``) and a backup file
  that was successfully written first.
* Before/after audits are printed and the after-audit must show ZERO
  unevidenced narrative numbers, or the script exits non-zero.

USAGE::

    # Audit only — writes nothing to the database.
    python scripts/story_narrative_audit.py --user-id <ID>

    # Remediate.
    python scripts/story_narrative_audit.py --user-id <ID> --apply \\
        --confirm-user-id <ID> --operator vikram

    # Reverse a remediation.
    python scripts/story_narrative_audit.py --user-id <ID> \\
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

from app.agents.story_extractor import (  # noqa: E402
    _STAR_FIELDS,
    StoryExtractorAgent,
)
from app.db import (  # noqa: E402
    ensure_story_achievement_column,
    ensure_story_archive_columns,
    get_connection,
    rows_to_dicts,
)
from app.repositories.story import StoryRepository  # noqa: E402
from app.services.dedup import compute_story_content_hash  # noqa: E402
from app.services.resume_bullets import (  # noqa: E402
    achievement_key,
    bullet_numbers,
    claim_numbers,
    extract_resume_bullets,
    is_quantified,
    organisation_matches,
    resume_employers,
    unevidenced_claims,
)
from app.services.resume_grounding import resolve_user_resume_text  # noqa: E402

_ALL_COLUMNS = (
    '"id", "userId", "title", "situation", "task", "action", "result", '
    '"metrics", "tags", "createdAt", "updatedAt", "contentHash", '
    '"archivedAt", "mergedIntoId", "mergeSnapshot", "achievementKey"'
)

_REASON ="story-narrative-grounding: claim not evidenced by the cited resume bullet"
_SNAPSHOT_FIELDS = ("title", "situation", "task", "action", "result", "metrics", "tags")


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


def _evidence_metrics(metrics: Any) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        return {}
    return {
        str(k): v for k, v in metrics.items()
        if not str(k).startswith("__") and str(v).strip()
    }


def _finding(
    row: dict[str, Any],
    bullet: dict[str, Any] | None,
    resume_numbers: set[str],
    all_employers: list[str],
) -> dict[str, Any]:
    """What is wrong with ONE story, and what remediating it would do."""
    finding: dict[str, Any] = {
        "story_id": row["id"],
        "title": row["title"],
        "bullet": bullet["id"] if bullet else None,
        "fabricated": {},
        "borrowed": {},
        "unevidenced_metrics": {},
        "foreign_employer_tags": [],
        "verdict": "clean",
        "reason": "",
    }
    if bullet is None:
        # Unanchored: the achievement key matches no bullet in the CURRENT
        # résumé, so there is no evidence to check the prose against. Reported,
        # never silently rewritten — a résumé edit must not archive history.
        finding["verdict"] = "unanchored"
        finding["reason"] = "cites no bullet in the user's current resume"
        return finding

    evidenced = bullet_numbers(bullet["text"])
    for name in _STAR_FIELDS:
        unevidenced = unevidenced_claims(str(row.get(name) or ""), evidenced)
        invented = [n for n in unevidenced if n not in resume_numbers]
        borrowed = [n for n in unevidenced if n in resume_numbers]
        if invented:
            finding["fabricated"][name] = invented
        if borrowed:
            finding["borrowed"][name] = borrowed

    metrics = _evidence_metrics(row.get("metrics"))
    for key, value in metrics.items():
        bad = [n for n in claim_numbers(f"{key} {value}") if n not in evidenced]
        if bad:
            finding["unevidenced_metrics"][key] = bad

    employers = list(bullet.get("employers") or [])
    if employers:
        finding["foreign_employer_tags"] = [
            tag
            for tag in (row.get("tags") or [])
            if organisation_matches(str(tag), all_employers)
            and not organisation_matches(str(tag), employers)
        ]

    # The verdict is decided by the LIVE GUARD, not by a second opinion.
    _, reason, note = StoryExtractorAgent._ground_narrative(
        row, bullet, resume_numbers
    )
    surviving = {k: v for k, v in metrics.items() if k not in finding["unevidenced_metrics"]}
    if reason is not None:
        finding["verdict"] = "archive"
        finding["reason"] = reason
    elif is_quantified(bullet["text"]) and metrics and not surviving:
        finding["verdict"] = "archive"
        finding["reason"] = (
            f"every metric is unevidenced by source bullet {bullet['id']}, and "
            "that bullet is quantified — the extractor would not create this"
        )
    elif note or finding["unevidenced_metrics"] or finding["foreign_employer_tags"]:
        finding["verdict"] = "strip"
        finding["reason"] = note or "unevidenced metric / foreign employer tag"
    return finding


def _audit(
    rows: list[dict[str, Any]], user_id: str, resume_text: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bullets = extract_resume_bullets(resume_text)
    by_key = {achievement_key(user_id, b["text"]): b for b in bullets}
    resume_numbers = bullet_numbers(resume_text)
    all_employers = resume_employers(resume_text)
    findings = [
        _finding(row, by_key.get(row.get("achievementKey")), resume_numbers, all_employers)
        for row in rows
    ]
    summary = {
        "live_rows": len(rows),
        "resume_bullets": len(bullets),
        "resume_employers": all_employers,
        "rows_with_narrative_numbers_not_in_their_cited_bullet": sum(
            1 for f in findings if f["fabricated"] or f["borrowed"]
        ),
        "rows_with_numbers_absent_from_the_whole_resume": sum(
            1 for f in findings if f["fabricated"]
        ),
        "rows_with_unevidenced_metrics": sum(
            1 for f in findings if f["unevidenced_metrics"]
        ),
        "rows_with_a_foreign_employer_tag": sum(
            1 for f in findings if f["foreign_employer_tags"]
        ),
        "rows_unanchored_to_any_current_bullet": sum(
            1 for f in findings if f["verdict"] == "unanchored"
        ),
        "verdicts": {
            verdict: sum(1 for f in findings if f["verdict"] == verdict)
            for verdict in ("clean", "strip", "archive", "unanchored")
        },
    }
    return summary, findings


def _write_backup(directory: Path, user_id: str, rows: list[dict[str, Any]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"storyentry-narrative-{user_id}-{stamp}.json"
    path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return path


def _snapshot(row: dict[str, Any], batch_id: str, operator: str | None,
              backup: Path, action: str, reason: str) -> str:
    return json.dumps(
        {
            "batch_id": batch_id,
            "reason": _REASON,
            "action": action,
            "detail": reason,
            "remediated_at": _now_iso(),
            "operator": operator,
            "backup_file": str(backup),
            "executed_by": _executing_account(),
            "remediation_before": {f: row.get(f) for f in _SNAPSHOT_FIELDS},
        },
        default=str,
    )


def _remediate(
    user_id: str,
    rows: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    resume_text: str,
    batch_id: str,
    operator: str | None,
    backup: Path,
) -> dict[str, int]:
    bullets = extract_resume_bullets(resume_text)
    by_key = {achievement_key(user_id, b["text"]): b for b in bullets}
    resume_numbers = bullet_numbers(resume_text)
    by_id = {r["id"]: r for r in rows}
    stories = StoryRepository()
    counts = {"archived": 0, "stripped": 0}

    for finding in findings:
        row = by_id[finding["story_id"]]
        bullet = by_key.get(row.get("achievementKey"))
        if finding["verdict"] == "archive":
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        'UPDATE "StoryEntry" SET "archivedAt" = NOW(), '
                        '"mergeSnapshot" = %s::jsonb, "updatedAt" = NOW() '
                        'WHERE "id" = %s AND "userId" = %s AND "archivedAt" IS NULL',
                        (
                            _snapshot(row, batch_id, operator, backup, "archive",
                                      finding["reason"]),
                            row["id"],
                            user_id,
                        ),
                    )
                conn.commit()
            counts["archived"] += 1
            continue
        if finding["verdict"] != "strip":
            continue

        grounded, reason, _ = StoryExtractorAgent._ground_narrative(
            row, bullet, resume_numbers
        )
        if reason is not None:  # pragma: no cover — the audit already ruled
            raise RuntimeError(f"{row['id']}: verdict/apply disagree: {reason}")
        patch: dict[str, Any] = {
            name: grounded[name]
            for name in _STAR_FIELDS
            if grounded.get(name) != row.get(name)
        }
        if finding["unevidenced_metrics"]:
            patch["metrics"] = {
                k: v
                for k, v in _evidence_metrics(row.get("metrics")).items()
                if k not in finding["unevidenced_metrics"]
            }
        if finding["foreign_employer_tags"]:
            foreign = set(finding["foreign_employer_tags"])
            patch["tags"] = [t for t in (row.get("tags") or []) if t not in foreign]
        # Snapshot FIRST: the pre-image must be durable before the row moves,
        # so an interrupted run can never leave an edited row with no way back.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "StoryEntry" SET "mergeSnapshot" = %s::jsonb '
                    'WHERE "id" = %s AND "userId" = %s AND "archivedAt" IS NULL',
                    (
                        _snapshot(row, batch_id, operator, backup, "strip",
                                  finding["reason"]),
                        row["id"],
                        user_id,
                    ),
                )
            conn.commit()
        stories.update(row["id"], user_id, patch)
        counts["stripped"] += 1
    return counts


def _restore(user_id: str, batch_id: str) -> tuple[int, list[str]]:
    """Put every row this batch touched back exactly as it was.

    Returns ``(restored, blocked_ids)``. A row can be BLOCKED: if the extractor
    has since written a fresh story for the same achievement, un-archiving this
    one would put two live rows on one ``achievementKey``, which the partial
    unique index forbids (``app.db.ensure_story_achievement_column``) — and
    rightly so, that is the duplicate the key exists to prevent. Those rows are
    reported by id and left archived rather than crashing the restore or
    silently deleting the newer story; archive the newer row first if the older
    content is genuinely wanted back.
    """
    ensure_story_archive_columns()
    ensure_story_achievement_column()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id", "mergeSnapshot", "achievementKey", "archivedAt" '
                'FROM "StoryEntry" '
                'WHERE "userId" = %s AND "mergeSnapshot"->>\'batch_id\' = %s '
                'AND "mergeSnapshot"->>\'reason\' = %s',
                (user_id, batch_id, _REASON),
            )
            targets = cur.fetchall()
            cur.execute(
                'SELECT "achievementKey" FROM "StoryEntry" WHERE "userId" = %s '
                'AND "archivedAt" IS NULL AND "achievementKey" IS NOT NULL',
                (user_id,),
            )
            live_keys = {row[0] for row in cur.fetchall()}
            blocked: list[str] = []
            restored = 0
            for story_id, snapshot, key, archived_at in targets:
                if archived_at is not None and key in live_keys:
                    blocked.append(story_id)
                    continue
                restored += 1
                before = (snapshot or {}).get("remediation_before") or {}
                cur.execute(
                    'UPDATE "StoryEntry" SET "archivedAt" = NULL, "title" = %s, '
                    '"situation" = %s, "task" = %s, "action" = %s, "result" = %s, '
                    '"metrics" = %s::jsonb, "tags" = %s, "contentHash" = %s, '
                    '"updatedAt" = NOW() WHERE "id" = %s AND "userId" = %s',
                    (
                        before.get("title"), before.get("situation"),
                        before.get("task"), before.get("action"),
                        before.get("result"),
                        json.dumps(before.get("metrics") or {}),
                        list(before.get("tags") or []),
                        # The strip path recomputed this; a restore that left
                        # the new hash behind would leave the row's content
                        # identity describing text it no longer holds, and the
                        # next create() dedup lookup would miss it.
                        compute_story_content_hash(
                            user_id, *(before.get(f) or "" for f in _STAR_FIELDS)
                        ),
                        story_id, user_id,
                    ),
                )
        conn.commit()
    return restored, blocked


def _load_env() -> None:
    """Load the repo-root ``.env`` WITHOUT overriding anything already set.

    Called from :func:`main` only — never at import time — so importing this
    module can never pull the production ``DATABASE_URL`` into a test process.
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
        default=str(Path.home() / "aether-backups" / "story-narrative"),
    )
    parser.add_argument("--restore-batch", default=None)
    parser.add_argument(
        "--json", action="store_true", help="print the per-story findings too"
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
        restored, blocked = _restore(user_id, args.restore_batch)
        print(f"restored {restored} row(s)")
        if blocked:
            print(
                f"BLOCKED {len(blocked)} row(s) — a live story already covers "
                f"the same achievement: {', '.join(blocked)}"
            )
            return 1
        return 0

    resume_text = resolve_user_resume_text(user_id, allow_operator_fallback=False)
    if not resume_text.strip():
        print("REFUSED: this user has no résumé of their own to check stories against.")
        return 2

    rows = _fetch(user_id, live_only=True)
    summary, findings = _audit(rows, user_id, resume_text)
    print("=== NARRATIVE AUDIT (before) ===")
    print(json.dumps(summary, indent=2))
    if args.json or not args.apply:
        for finding in findings:
            if finding["verdict"] != "clean":
                print(json.dumps(finding, indent=2, default=str))

    if not args.apply:
        print("DRY RUN — nothing written. Pass --apply to remediate.")
        return 0
    if args.confirm_user_id != user_id:
        print("REFUSED: --confirm-user-id must repeat --user-id.")
        return 2

    backup = _write_backup(
        Path(args.backup_dir), user_id, _fetch(user_id, live_only=False)
    )
    print(f"backup written: {backup} ({backup.stat().st_size} bytes)")

    batch_id = uuid.uuid4().hex
    counts = _remediate(
        user_id, rows, findings, resume_text, batch_id, args.operator, backup
    )
    print(f"batch {batch_id}: {counts}")
    print(
        f"reverse with: --restore-batch {batch_id} --apply "
        f"--confirm-user-id {user_id}"
    )

    after_summary, after_findings = _audit(
        _fetch(user_id, live_only=True), user_id, resume_text
    )
    print("=== NARRATIVE AUDIT (after) ===")
    print(json.dumps(after_summary, indent=2))
    for finding in after_findings:
        if finding["verdict"] != "clean":
            print(json.dumps(finding, indent=2, default=str))
    if after_summary["rows_with_narrative_numbers_not_in_their_cited_bullet"]:
        print("FAILED: unevidenced narrative numbers survived the remediation.")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — operator entrypoint
    raise SystemExit(main())
