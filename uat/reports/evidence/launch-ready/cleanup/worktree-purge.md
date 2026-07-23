# PHASE 0 — Approved Worktree Purge (root cause of ledger row ML-env-001)

- Timestamp: 2026-07-23T15:43Z
- Scope: exactly the stale git worktrees under `/tmp`, the empty `/home/ubuntu/github_repos/aether-job-career-agent-review-worktree/`, fully-merged stale local branches, and `git remote prune origin`. Nothing else touched.

## BEFORE — `git worktree list` (12 entries)

```
/home/ubuntu/github_repos/aether-job-career-agent                                            03c0c50 [main]
/tmp/aether-baseline-53f0e08                                                                 53f0e08 (detached HEAD)
/tmp/claude-2000/.../dddecd22.../scratchpad/baseline-wt                                      9968ac4 (detached HEAD)
/tmp/claude-2000/.../dddecd22.../scratchpad/wt-dedup-safe                                    03c0c50 [fix/dedup-safe]
/tmp/claude-2000/.../dddecd22.../scratchpad/wt-err001fix                                     c50450c [fix/ml-agents-err-001-status]
/tmp/claude-2000/.../dddecd22.../scratchpad/wt-sources                                       32733f5 [fix/ml-source-disclosure]
/tmp/claude-2000/.../dddecd22.../scratchpad/wt-story                                         d1b3cb0 [fix/ml-story-operator-leak]
/tmp/claude-2000/.../ed97cdcc.../scratchpad/wt/b1                                            f68a4e6 (detached HEAD)
/tmp/claude-2000/.../ed97cdcc.../scratchpad/wt/b2                                            0f4c4b8 (detached HEAD)
/tmp/claude-2000/.../ed97cdcc.../scratchpad/wt/b3                                            bf8cbc3 (detached HEAD)
/tmp/claude-2000/.../ed97cdcc.../scratchpad/wt/base                                          d313d23 (detached HEAD)
/tmp/prefix-scratch                                                                          7ebc731 (detached HEAD)
```

## BEFORE — local branches

```
+ fix/dedup-safe               03c0c50 (checked out in wt-dedup-safe)   ← in `git branch --merged main`
+ fix/ml-agents-err-001-status c50450c (checked out in wt-err001fix)    ← NOT in --merged
+ fix/ml-source-disclosure     32733f5 (checked out in wt-sources)      ← NOT in --merged
+ fix/ml-story-operator-leak   d1b3cb0 (checked out in wt-story)        ← NOT in --merged
* main                         03c0c50 [origin/main]
```

## Actions executed

1. `git worktree remove --force <path>` for all 11 `/tmp` worktrees — all succeeded.
2. `git worktree prune` — clean.
3. `rmdir /home/ubuntu/github_repos/aether-job-career-agent-review-worktree` (was empty) — succeeded.
4. `git branch -d fix/dedup-safe` — deleted (was 03c0c50, identical to main tip; listed by `git branch --merged main`).
5. **KEPT** `fix/ml-agents-err-001-status` (c50450c): NOT listed by `git branch --merged main`. Its changes landed in main *folded into batch commit ef7df30* (per docs commit 9968ac4 and `git cherry` non-equivalence), so git cannot prove full merge — per instruction, left in place and noted.
6. **KEPT** (not on the deletion list): `fix/ml-source-disclosure`, `fix/ml-story-operator-leak` — also folded into ef7df30 per the batch commit message, but out of this purge's approved scope; flagged for a later cleanup adjudication.
7. `git remote prune origin` — no stale remote-tracking refs pruned. Note: a second remote `origin-local` exists (remote-tracking `origin-local/main`) — out of scope here; flagged for Workstream D adjudication.

## AFTER — `git worktree list`

```
/home/ubuntu/github_repos/aether-job-career-agent  03c0c50 [main]
```

## AFTER — local branches

```
  fix/ml-agents-err-001-status c50450c   (kept — not provably merged)
  fix/ml-source-disclosure     32733f5   (kept — out of approved scope)
  fix/ml-story-operator-leak   d1b3cb0   (kept — out of approved scope)
* main                         03c0c50 [origin/main]
```

`[VERIFIED-WITH-FRESH-EVIDENCE]` — worktree registry reduced 12 → 1 (main tree only); nothing outside the approved list was touched.
