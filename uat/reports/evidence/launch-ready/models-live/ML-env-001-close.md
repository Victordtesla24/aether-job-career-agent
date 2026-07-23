# ML-env-001 — CLOSE (stale-worktree pytest nondeterminism)

- Re-verified: 2026-07-23T16:39:06Z (Workstream A ledger-close pass)
- Verdict: CLOSED on Phase 0 evidence; fresh re-verification shows zero residue.

## Fresh re-verification (this pass, 2026-07-23T16:39:06Z)
```
$ git worktree list
/home/ubuntu/github_repos/aether-job-career-agent  41f08c0 [main]

$ git branch
  fix/ml-agents-err-001-status
  fix/ml-source-disclosure
  fix/ml-story-operator-leak
* main

$ ls -d /tmp/*worktree* /tmp/worktree-agent-* /tmp/fix-mv-* 2>/dev/null
/tmp/cleanup-worktree.sh
(no matches — only /tmp/cleanup-worktree.sh, a leftover purge SCRIPT, not a worktree)

$ pgrep -f "[p]ytest"
(no pytest running)
```

- Remaining 3 `fix/*` local branches are the deliberately-retained UNMERGED fix branches documented in the Phase 0 purge (not stale merged residue).

## Phase 0 evidence relied on
- Purge transcript: `uat/reports/evidence/launch-ready/cleanup/worktree-purge.md` (12 → 1 worktrees, merged branches deleted, remote pruned, 2026-07-23T15:43Z)
- Deterministic full-suite baseline AFTER purge: `uat/reports/evidence/launch-ready/runtime/baseline-suites.md` — pytest **1118 passed / 0 failed** under flock (single serialized run, no concurrent pytest), vitest 556/556.

## Conclusion
The environmental cause (~35 stale /tmp worktrees sharing the aether_test schema) is gone and the full backend suite is deterministic (1118/1118). No code change required. Status → VERIFIED-CLOSED-LIVE (environmental row; "LIVE" = the shared prod/test VM environment itself, verified this pass).
