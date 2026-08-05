# ADR-GMV4-STORY-DEDUP-SAFETY — the Story Bank bulk de-dup sweep archives instead of deleting

- **Status:** Accepted, landed
- **Date:** 2026-08-05
- **Findings:** GMV4-story-002 (retroactive-merge gap, HIGH), GMV4-story-004 (latent data-destruction hazard)
- **Supersedes the behaviour of:** `apps/api/app/services/story_dedup_migration.py` @ 119 lines
- **Related:** ADR-TR-1 (lazy additive DDL — this repo has no migration runner),
  `docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md` (why destructive ops need enforced,
  not assumed, preconditions)

## 1. The hazard

`StoryRepository.create` catches a paraphrase duplicate going FORWARD, at create time. It does
nothing for duplicates that had already accumulated before that fix shipped — the evidence
report's real 34-of-36-stories-are-paraphrases case, still visible as 5 near-duplicate clusters
covering 16 of 37 live stories (GMV4-story-002).

`merge_duplicate_stories` was written to clean that up. Two facts about it combined into a
data-destruction hazard:

1. **It hard-deleted.** Every merge ended in
   `cur.execute('DELETE FROM "StoryEntry" WHERE "id" = %s', (row["id"],))`. The losing row's
   content was gone — and story content is *user-authored career history that cannot be
   regenerated*. There was no backup, no snapshot, no undo.
2. **It was driven by a deliberately loose heuristic.** The sweep uses
   `BULK_MIGRATION_THRESHOLDS` (title Jaccard ≥ 0.60), which is *looser on purpose* than the
   create-time preset (≥ 0.70), because paraphrase drift accumulates across many extractor
   re-runs. An over-matching heuristic is an acceptable trade-off for a reviewed, reversible
   operation. Wired to an irreversible `DELETE`, it is not.

The only reason no user had lost data is that **the function had zero production call sites and
had therefore never run** — which was itself the open defect (GMV4-story-002). Closing
story-002 by simply wiring up an entrypoint would have armed story-004.

A further trap: the merge also **overwrites the survivor** with the duplicate's wording. So even
a "keep both rows" fix is insufficient — the survivor's original text is destroyed by the merge
whether or not the loser is deleted. Any real recovery mechanism has to restore *both* sides.

## 2. Decision

Replace the delete with a **recoverable archive**, and put the sweep behind an **enforced human
gate**. Four properties, each with a named owner in the code:

| Property | Mechanism |
|---|---|
| RECOVERABLE | the loser is soft-archived, never deleted; the survivor's pre-merge content is snapshotted |
| PREVIEWABLE | `dry_run=True` returns the exact plan the apply path will execute, and writes nothing |
| PROVABLE | `before_count` / `after_count` re-read from the DB, plus a `reconciled` flag |
| REACHABLE, NOT BY ACCIDENT | `scripts/story_dedup_sweep.py` — dry-run by default, four independent gates before any write |

### 2.1 Where archived rows go

They do not move. The row stays in `"StoryEntry"` with its own content **untouched in place**,
and three additive columns are set (`app.db.ensure_story_archive_columns`, already committed):

- `archivedAt` (timestamptz) — `NULL` means LIVE.
- `mergedIntoId` (text) — the surviving row's id, so an archived row always points at where its
  content went.
- `mergeSnapshot` (jsonb) — the audit + recovery record: `survivor_before` (the survivor's
  content *as it stood before being overwritten* — the only part of a merge that is otherwise
  destroyed), the similarity `signals` that produced the decision, the `thresholds` used, the
  `batch_id`, and the executing `account`/`host`.

DDL is `ADD COLUMN IF NOT EXISTS` with no DEFAULT — metadata-only on PostgreSQL, additive only,
serialized by a transaction-scoped advisory lock. **No backfill is needed or performed:** every
pre-existing row reads `archivedAt = NULL`, which is exactly correct for a row that was never
merged away.

Visibility is split deliberately, and this split is what makes the guarantee testable:

- `StoryRepository.list_by_user` filters `archivedAt IS NULL`. It is the single choke point every
  Story Bank consumer reads through — the Story Bank screen, tailoring evidence selection,
  story-relevance scoring, cover-letter evidence, interview prep, the extractor — so one filter
  hides merged-away rows everywhere at once.
- `StoryRepository.get_by_id` **deliberately includes archived rows**. An archived row must stay
  resolvable, otherwise a "recoverable" merge is not recoverable and there is no way to prove the
  loser's content still exists.
- `StoryRepository.update` returns `None` (→ 404) for an archived id, so archived content can
  neither be re-published through a response body nor mutated out from under a pending restore.

### 2.2 How a merge is reversed

`restore_merged_stories(user_id, *, batch_id=None, story_ids=None, dry_run=True)` — defaults to
dry run, like the sweep.

Each archived row is un-archived (`archivedAt = NULL`, `mergedIntoId = NULL`) and its survivor is
rewritten from `mergeSnapshot.survivor_before`, with the survivor's `contentHash` recomputed from
the restored text. Both sides therefore return to their exact pre-merge state.

**Order matters, and `archivedAt` alone cannot supply it.** A whole sweep runs in ONE transaction
and PostgreSQL's `NOW()` is the *transaction* timestamp, so every row archived by one batch
carries an identical `archivedAt`. `_restore_order_key` therefore breaks the tie on
`mergeSnapshot.merged_at`, which is stamped per proposal inside the merge loop. Rows are restored
**newest-merge-first**, so a chain of merges into one survivor unwinds in the exact reverse order
it was applied. A row with no usable `merged_at` sorts equal to its siblings, which makes it
mutually blocking — an unknown merge order is treated as unsafe, never as safe.

**Partial restores are refused, not half-applied.** If survivor S absorbed D1 and then D2,
restoring only D1 would rewrite S with content predating D2's merge, silently discarding D2's
contribution while D2 stays archived — no error, no warning, and invisible, because the only
record of it was S's own text. `_blocking_merges` detects this; a dry run lists the blockers, and
the apply path **raises and writes nothing at all**, naming the exact rows to include.

Two refusal classes are always reported, never silent: `unrestorable` (no complete
`survivor_before` in the snapshot) and `blocked` (the chain case above).

### 2.3 The entrypoint gate

`apps/api/scripts/story_dedup_sweep.py` closes GMV4-story-002 by being the missing production
call site — without re-arming story-004:

- **Dry run is the default.** No `--apply` ⇒ reads only, prints every proposed pair with its real
  similarity signals, writes a plan file.
- **Writing needs four independent things,** so no single slip mutates story data: `--apply`, a
  `--plan` file from a prior dry run, that plan signed by a human (`reviewed_by` filled in by
  hand), and the user id re-stated via `--confirm-user-id`.
- **The plan is re-verified before and after.** A digest over *which pairs merge and what content
  the survivor ends up with* is compared against the live database before writing, and the
  actually-executed plan is digested and compared again afterwards. This is a check-then-act, not
  an atomic operation — the second comparison exists precisely because the window cannot be
  eliminated, only made impossible to pass through unnoticed, over an operation that is reversible
  anyway.
- **Restore is gated exactly like apply**, since reversing merges overwrites live content just as
  much as applying them does.
- `--expect-account` lets a cron wrapper pin the OS account; the executing account and host are
  recorded on every archived row regardless, so execution is auditable after the fact.

The script's default target is whatever `DATABASE_URL` resolves to (repo-root `.env`, i.e.
production) — it is a production ops tool. It prints the resolved target before doing anything,
and `load_dotenv(..., override=False)` means an explicitly exported `DATABASE_URL` wins.

### 2.4 Threshold re-decision (kept at 0.60)

`BULK_MIGRATION_THRESHOLDS` stays at title Jaccard 0.60. When it drove an irreversible `DELETE`
its looseness was indefensible; it no longer does. The human review gate — not the ratio — is now
what bounds a false merge, and it is *enforced* rather than merely asserted in a docstring.
Tightening to 0.70 would buy no protection the gate does not already give, while silently missing
the verified-real duplicate clusters that sit between the two values (the ANZ pair: title Jaccard
0.667) — which is the entire defect story-002 reports. `--conservative` runs the sweep with
`CREATE_TIME_THRESHOLDS` for an operator who wants harder machine pre-filtering.

## 3. Evidence

Guards in `apps/api/tests/test_story_dedup_invocation.py`, RED at HEAD `9032429` in a pristine
detached worktree (empty working tree), GREEN after this change:

| Guard | RED at HEAD |
|---|---|
| `TestProductionInvocationPath` | AST scan of `app/` + `scripts/` found ZERO call sites |
| `TestDryRun` | `found only ['user_id']` — no `dry_run` parameter |
| `TestNeverDeletes` | `story row 'c44bfca4db4fa60649a360b95' … was PHYSICALLY DELETED` |
| `TestBeforeAfterCounts` | `result is missing 'before_count'` |

`restore_merged_stories` had **zero test coverage anywhere in the suite**. Since an archive nobody
can reverse is worse than an honest `DELETE` — it looks safe while the content is just as
unreachable — `apps/api/tests/test_story_dedup_archive_restore.py` was added to prove the reverse
path against a real database: dry run changes nothing, a merge archives recoverably with a
snapshot, a restore returns **both** sides byte-exactly, a partial chain restore is refused and
writes nothing, and a full chain unwinds in reverse merge order.

Suites: 199 passed (10 story suites, 96; 7 `StoryRepository`-consumer suites, 103). `ruff` and
`mypy` clean.

The sweep CLI was additionally exercised end-to-end against `schema=aether_test`: dry run left
both rows live; `--apply` without `--plan`, without `--confirm-user-id`, with a mismatched
`--confirm-user-id`, with an unsigned plan, and with a mismatched `--expect-account` all refused
and wrote nothing; a signed plan merged 1 row with `reconciled: True`; re-applying the now-stale
plan was refused on digest mismatch; and the restore flow returned the survivor to its original
title with counts reconciled.

## 4. Consequences

- A merge is now reversible, so the loose bulk threshold is a recoverable judgement call rather
  than an irreversible one.
- `StoryEntry` accumulates archived rows. They are invisible to every product surface, but they
  are real rows — a future retention policy for archived merges is a known follow-up, not
  something this ADR settles.
- Every path that reads or writes the three archive columns **must** call
  `ensure_story_archive_columns()` before the statement naming them; skipping it is the
  `UndefinedColumn` → HTTP 500 failure mode recorded as WIP-BRANCH-AUDIT-2026-07-29 blocker #2.
- The sweep has an entrypoint but **has still never been run against production data**. Running it
  is a separate, human-gated operator action.
