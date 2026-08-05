#!/usr/bin/env python3
"""Story Bank bulk paraphrase de-dup sweep — the production entrypoint.

GMV4-story-002: ``app.services.story_dedup_migration.merge_duplicate_stories``
had ZERO call sites and had therefore never run, leaving real near-duplicate
clusters sitting in live Story Banks. This script is that missing entrypoint.

GMV4-story-004: the sweep is driven by a similarity preset that is
DELIBERATELY looser than the create-time one, over user-authored career
history that cannot be regenerated. The merge itself is now recoverable (the
losing row is archived, never deleted — see the service module), and this
script is the second half of that safety story: it makes the risk officer's
pre-conditions ENFORCEABLE rather than optional.

  * DRY RUN IS THE DEFAULT. With no ``--apply`` the script only reads: it
    prints every proposed pair with the similarity signals behind it and
    writes a plan file. Nothing in the database moves.
  * WRITING NEEDS FOUR INDEPENDENT THINGS, so no single slip can mutate story
    data: ``--apply``, a ``--plan`` file produced by a prior dry run, that
    plan signed by a human (``reviewed_by`` filled in by hand), and the user
    id re-stated via ``--confirm-user-id``.
  * THE PLAN IS RE-VERIFIED, BEFORE AND AFTER. Before writing, the sweep
    recomputes the merge plan against the live database and refuses if it
    differs by so much as one pair from the plan the human signed — a Story
    Bank that changed after review is an unreviewed sweep.

    Be precise about what that buys, because an earlier revision of this
    docstring overstated it (round-2 review finding 4). The verification and
    the write are two INDEPENDENT re-plans, so this is a check-then-act, not
    an atomic execute-the-verified-object: a write landing in the millisecond
    gap between them would not be caught by the pre-check. What closes that
    gap is the SECOND comparison — after the apply, the plan the sweep
    actually executed is digested again and compared to the reviewed one, and
    any divergence is reported with the batch id and the exact command to
    reverse it. The window is not eliminated; it is made impossible to pass
    through UNNOTICED, over an operation that is fully reversible anyway.
  * COUNTS ARE RECONCILED. Before/after row counts are printed and checked;
    a mismatch is a non-zero exit.
  * RESTORE IS GATED LIKE APPLY. Reversing merges overwrites live content
    just as much as applying them does, so ``--restore --apply`` requires the
    same four things: a reviewed plan file from a restore dry run, its
    digest re-verified against the live archive, the re-stated user id, and a
    count reconciliation afterwards (round-2 review finding 5).
  * ``--expect-account`` lets a cron wrapper pin the OS account allowed to
    run this; the executing account and host are recorded on every archived
    row regardless, so execution is auditable after the fact.

USAGE — the two-step flow (there is no one-step flow, by design)::

    # 1. DRY RUN (default). Reads only. Writes ./plan.json.
    python scripts/story_dedup_sweep.py --user-id <ID> --plan-out plan.json

    # 2. A HUMAN reads plan.json, and if the proposals are right, edits it:
    #       "reviewed_by": "vikram sarkar 2026-07-31"
    #
    # 3. APPLY.
    python scripts/story_dedup_sweep.py --user-id <ID> --apply \\
        --plan plan.json --confirm-user-id <ID> --operator "vikram"

    # Reverse a batch — SAME two-step flow, for the same reason:
    python scripts/story_dedup_sweep.py --user-id <ID> --restore \\
        --batch-id <BATCH> --plan-out restore.json
    #   ... human sets "reviewed_by" in restore.json ...
    python scripts/story_dedup_sweep.py --user-id <ID> --restore \\
        --batch-id <BATCH> --apply --plan restore.json --confirm-user-id <ID>

    # Inspect what is archived:
    python scripts/story_dedup_sweep.py --user-id <ID> --list-archived

``DATABASE_URL`` is read from the environment / repo-root .env, exactly like
the API. The resolved target is printed before anything happens so an operator
can see which database they are pointed at.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# --- Path setup: runnable from the repo root or from apps/api/ ---
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_API_DIR = _REPO_ROOT / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

try:
    from dotenv import load_dotenv

    _env_path = _REPO_ROOT / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:  # python-dotenv absent — expect DATABASE_URL already set
    pass

from app.services.story_dedup_migration import (  # noqa: E402
    list_archived_merges,
    merge_duplicate_stories,
    restore_merged_stories,
)
from app.services.story_paraphrase import (  # noqa: E402
    BULK_MIGRATION_THRESHOLDS,
    CREATE_TIME_THRESHOLDS,
)


def _target_description() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "DATABASE_URL is NOT SET"
    parsed = urlparse(url)
    schema = ""
    if "schema=" in (parsed.query or ""):
        schema = "?" + [p for p in parsed.query.split("&") if p.startswith("schema=")][0]
    return f"{parsed.hostname}{parsed.path}{schema}"


def _plan_digest(proposals: list[dict]) -> str:
    """Stable digest of WHICH pairs merge and WHAT content the survivor ends
    up with. Any change to either — a new pair, a dropped pair, or the same
    pair now producing different merged text — changes the digest and so
    invalidates a human's signature on the old plan."""
    payload = sorted(
        (
            p["survivor_id"],
            p["duplicate_id"],
            json.dumps(p["merged"], sort_keys=True, default=str),
        )
        for p in proposals
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _restore_digest(plan_entries: list[dict]) -> str:
    """Stable digest of WHICH archived rows come back and WHAT each survivor is
    rewritten to. ``survivor_restored_hash`` is the content hash of the exact
    ``survivor_before`` text the restore will write, so a survivor whose
    snapshot resolves differently — or an archived row appearing/disappearing
    from the batch — invalidates a human's signature on the old plan."""
    payload = sorted(
        (
            e["story_id"],
            str(e["survivor_id"]),
            str(e["survivor_restored_hash"]),
        )
        for e in plan_entries
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _require_reviewed_plan(args, kind: str, digest_key: str) -> tuple[dict, str]:
    """Shared apply-time gate for BOTH the merge and the restore paths.

    Returns ``(plan, reviewed_by)`` or exits. Restore used to be protected by
    ``--confirm-user-id`` alone while being just as capable of overwriting
    live story content as a merge (round-2 review finding 5); both now pass
    through here.
    """
    if args.confirm_user_id != args.user_id:
        sys.exit(
            "REFUSING TO WRITE: --confirm-user-id does not match --user-id "
            "(re-state the user id exactly to confirm the target)."
        )
    if not args.plan:
        sys.exit(
            f"REFUSING TO WRITE: --apply requires --plan <file> from a {kind} "
            "dry run."
        )
    plan_path = Path(args.plan)
    if not plan_path.exists():
        sys.exit(f"REFUSING TO WRITE: plan file {plan_path} does not exist.")
    plan = json.loads(plan_path.read_text())
    if plan.get("plan_kind") != kind:
        sys.exit(
            f"REFUSING TO WRITE: {plan_path} is a {plan.get('plan_kind')!r} "
            f"plan, not a {kind!r} plan."
        )
    if plan.get("user_id") != args.user_id:
        sys.exit(
            f"REFUSING TO WRITE: plan was generated for user "
            f"{plan.get('user_id')!r}, not {args.user_id!r}."
        )
    if digest_key not in plan:
        sys.exit(f"REFUSING TO WRITE: {plan_path} carries no {digest_key}.")
    reviewed_by = plan.get("reviewed_by")
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        sys.exit(
            "REFUSING TO WRITE: the plan has not been reviewed. A human must "
            'open it and set "reviewed_by" to their name — that review is the '
            "control that bounds an operation which rewrites story content."
        )
    return plan, reviewed_by


def _write_plan(args, plan: dict, default_name: str) -> Path:
    out = Path(args.plan_out or default_name)
    out.write_text(json.dumps(plan, indent=2, default=str))
    print(f"\nplan written to {out}")
    return out


def _print_proposals(result: dict) -> None:
    proposals = result.get("proposed") or []
    if not proposals:
        print("  (no duplicate pairs qualify under these thresholds)")
        return
    for i, p in enumerate(proposals, 1):
        s = p["signals"]
        print(f"  [{i}] score {s['score']}")
        print(f"      KEEP    {p['survivor_id']}  {p['survivor_title']!r}")
        print(f"      ARCHIVE {p['duplicate_id']}  {p['duplicate_title']!r}")
        print(
            f"      title jaccard {s['title_jaccard']} "
            f"(shared {s['title_shared']}), achievement jaccard "
            f"{s['achievement_jaccard']} (shared {s['achievement_shared']})"
        )
        print(f"      survivor text AFTER merge -> {p['merged']['title']!r}")


def _check_account(expected: str | None) -> None:
    if expected is None:
        return
    import getpass

    actual = getpass.getuser()
    if actual != expected:
        sys.exit(
            f"REFUSING TO RUN: --expect-account {expected!r} but this process "
            f"runs as {actual!r}."
        )


def _run_sweep(args: argparse.Namespace) -> int:
    thresholds = CREATE_TIME_THRESHOLDS if args.conservative else BULK_MIGRATION_THRESHOLDS
    label = "CREATE_TIME (conservative)" if args.conservative else "BULK_MIGRATION"

    if not args.apply:
        result = merge_duplicate_stories(
            args.user_id, dry_run=True, thresholds=thresholds
        )
        print(f"DRY RUN — thresholds: {label} {result['thresholds']}")
        print(f"stories now: {result['before_count']}")
        print(f"would merge: {result['would_merge']}")
        print(f"would leave: {result['projected_after_count']}")
        _print_proposals(result)
        plan = dict(result)
        plan["plan_kind"] = "merge"
        plan["plan_digest"] = _plan_digest(result["proposed"])
        plan["conservative"] = bool(args.conservative)
        plan["reviewed_by"] = None
        _write_plan(args, plan, "story-dedup-plan.json")
        print(
            "NOTHING WAS WRITTEN TO THE DATABASE. To apply: review the plan, "
            'set its "reviewed_by" field to your name, then re-run with '
            "--apply --plan <file> --confirm-user-id <id>."
        )
        return 0

    # ---- apply path: every gate below must pass ----
    plan, reviewed_by = _require_reviewed_plan(args, "merge", "plan_digest")
    plan_path = Path(args.plan)
    if bool(plan.get("conservative")) != bool(args.conservative):
        sys.exit(
            "REFUSING TO WRITE: plan was generated with a different threshold "
            "preset than this invocation requests."
        )

    live = merge_duplicate_stories(args.user_id, dry_run=True, thresholds=thresholds)
    live_digest = _plan_digest(live["proposed"])
    if live_digest != plan.get("plan_digest"):
        print("REFUSING TO WRITE: the Story Bank changed since the plan was reviewed.")
        print(f"  reviewed plan digest: {plan.get('plan_digest')}")
        print(f"  live plan digest:     {live_digest}")
        print(f"  reviewed pairs: {len(plan.get('proposed') or [])}, live pairs: "
              f"{len(live['proposed'])}")
        print("Re-run the dry run, review the new plan, then apply.")
        return 2

    print(f"APPLYING — thresholds: {label}")
    print(f"plan {plan_path} reviewed by: {reviewed_by}")
    _print_proposals(live)
    result = merge_duplicate_stories(
        args.user_id,
        dry_run=False,
        thresholds=thresholds,
        operator=args.operator or reviewed_by,
    )
    print(f"\nbatch_id:     {result['batch_id']}")
    print(f"before_count: {result['before_count']}")
    print(f"merged:       {result['merged']}  (archived, restorable)")
    print(f"after_count:  {result['after_count']}")
    print(f"reconciled:   {result['reconciled']}")
    reverse_cmd = (
        f"--restore --batch-id {result['batch_id']} --apply "
        f"--plan <reviewed restore plan> --confirm-user-id {args.user_id}"
    )
    # The pre-flight digest check above and this write were two independent
    # re-plans (see the module docstring). Digest what was ACTUALLY executed
    # and compare it to what was reviewed, so a plan that shifted inside that
    # window cannot pass through silently.
    executed_digest = _plan_digest(result["proposed"])
    if executed_digest != plan.get("plan_digest"):
        print(
            "\nEXECUTED PLAN DIVERGED FROM THE REVIEWED PLAN: the Story Bank "
            "changed between the pre-flight verification and the write."
        )
        print(f"  reviewed digest: {plan.get('plan_digest')}")
        print(f"  executed digest: {executed_digest}")
        print(f"  batch_id:        {result['batch_id']}")
        print(f"REVERSE IT: {reverse_cmd}")
        return 5
    if not result["reconciled"]:
        print(
            "COUNT RECONCILIATION FAILED: after_count != before_count - merged. "
            "Investigate before treating this sweep as successful."
        )
        return 3
    print(f"\nTo reverse: {reverse_cmd}")
    return 0


def _print_restore_result(args: argparse.Namespace, result: dict) -> None:
    print(f"{'RESTORE' if args.apply else 'RESTORE DRY RUN'} — user {args.user_id}")
    print(f"restorable: {result['restorable']}  restored: {result['restored']}")
    for item in result["plan"]:
        print(
            f"  un-archive {item['story_id']} {item['story_title']!r}; survivor "
            f"{item['survivor_id']} back to {item['survivor_restored_title']!r}"
        )
    for bad in result["unrestorable"]:
        print(f"  UNRESTORABLE {bad['story_id']}: {bad['reason']}")
    for bad in result.get("blocked") or []:
        print(
            f"  BLOCKED {bad['story_id']}: survivor {bad['survivor_id']} also "
            f"absorbed later merge(s) {bad['blocked_by']} (batches "
            f"{bad['blocked_by_batches']}) that this restore leaves archived — "
            "restoring it alone would silently discard them. Include those "
            "rows in the restore."
        )


def _run_restore(args: argparse.Namespace) -> int:
    """Reverse merges. Gated exactly like the merge apply path (finding 5).

    A restore rewrites live survivor content, so ``--confirm-user-id`` alone
    was never proportionate protection: the dry run now writes a reviewable
    plan, and the apply path re-verifies that plan's digest against the live
    archive, refuses on any ``blocked`` chain, and reconciles counts.
    """
    if not args.apply:
        result = restore_merged_stories(
            args.user_id, batch_id=args.batch_id, dry_run=True
        )
        _print_restore_result(args, result)
        plan = dict(result)
        plan["plan_kind"] = "restore"
        plan["restore_digest"] = _restore_digest(result["plan"])
        plan["batch_id"] = args.batch_id
        plan["reviewed_by"] = None
        _write_plan(args, plan, "story-restore-plan.json")
        print(
            "NOTHING WAS WRITTEN TO THE DATABASE. To apply: review the plan, "
            'set its "reviewed_by" field to your name, then re-run with '
            "--restore --apply --plan <file> --confirm-user-id <id>."
        )
        if result.get("blocked"):
            return 5
        return 4 if result["unrestorable"] else 0

    plan, reviewed_by = _require_reviewed_plan(args, "restore", "restore_digest")
    if plan.get("batch_id") != args.batch_id:
        sys.exit(
            f"REFUSING TO WRITE: plan was generated for batch "
            f"{plan.get('batch_id')!r}, not {args.batch_id!r}."
        )

    live = restore_merged_stories(args.user_id, batch_id=args.batch_id, dry_run=True)
    live_digest = _restore_digest(live["plan"])
    if live_digest != plan.get("restore_digest"):
        print("REFUSING TO WRITE: the archive changed since the plan was reviewed.")
        print(f"  reviewed restore digest: {plan.get('restore_digest')}")
        print(f"  live restore digest:     {live_digest}")
        print(f"  reviewed rows: {len(plan.get('plan') or [])}, live rows: "
              f"{len(live['plan'])}")
        print("Re-run the restore dry run, review the new plan, then apply.")
        return 2
    if live.get("blocked"):
        _print_restore_result(args, live)
        print(
            "REFUSING TO WRITE: this restore would silently discard later "
            "merges from a survivor (see BLOCKED above). NOTHING WAS WRITTEN."
        )
        return 5

    print(f"APPLYING RESTORE — plan {Path(args.plan)} reviewed by: {reviewed_by}")
    try:
        result = restore_merged_stories(
            args.user_id, batch_id=args.batch_id, dry_run=False
        )
    except RuntimeError as exc:
        # The service performs the same chain check immediately before writing
        # and aborts without a connection; surface it as a clean refusal
        # rather than a traceback.
        print(f"REFUSING TO WRITE: {exc}")
        return 5
    _print_restore_result(args, result)
    print(f"before_count: {result['before_count']}")
    print(f"after_count:  {result['after_count']}")
    print(f"reconciled:   {result['reconciled']}")
    if not result["reconciled"]:
        print(
            "COUNT RECONCILIATION FAILED: after_count != before_count + "
            "restored. Investigate before treating this restore as successful."
        )
        return 3
    return 4 if result["unrestorable"] else 0


def _run_list_archived(args: argparse.Namespace) -> int:
    rows = list_archived_merges(args.user_id, batch_id=args.batch_id)
    print(f"{len(rows)} archived (merged-away) row(s) for user {args.user_id}")
    for row in rows:
        snapshot = row.get("mergeSnapshot") or {}
        print(
            f"  {row['id']}  archived {row['archivedAt']}  -> "
            f"{row['mergedIntoId']}  batch {snapshot.get('batch_id')}  "
            f"by {snapshot.get('account')}@{snapshot.get('host')}"
        )
        print(f"      {row['title']!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Story Bank bulk paraphrase de-dup sweep (dry-run by default).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--user-id", required=True, help="target user id")
    parser.add_argument(
        "--apply", action="store_true",
        help="PERFORM WRITES. Without this the run is a dry run.",
    )
    parser.add_argument(
        "--confirm-user-id", default=None,
        help="must equal --user-id; required with --apply",
    )
    parser.add_argument("--plan", default=None, help="reviewed plan file (with --apply)")
    parser.add_argument(
        "--plan-out", default="story-dedup-plan.json",
        help="where a dry run writes its plan (default: ./story-dedup-plan.json)",
    )
    parser.add_argument("--operator", default=None, help="who is running this")
    parser.add_argument(
        "--conservative", action="store_true",
        help="use CREATE_TIME_THRESHOLDS instead of the looser bulk preset",
    )
    parser.add_argument(
        "--expect-account", default=None,
        help="refuse to run unless the OS account matches (for cron pinning)",
    )
    parser.add_argument("--restore", action="store_true", help="reverse merges")
    parser.add_argument("--batch-id", default=None, help="batch to restore/list")
    parser.add_argument(
        "--list-archived", action="store_true", help="list archived rows and exit"
    )
    args = parser.parse_args(argv)

    _check_account(args.expect_account)
    print(f"[story_dedup_sweep] target database: {_target_description()}")

    if args.list_archived:
        return _run_list_archived(args)
    if args.restore:
        return _run_restore(args)
    return _run_sweep(args)


if __name__ == "__main__":
    raise SystemExit(main())
