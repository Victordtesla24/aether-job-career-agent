# ORCH Reconciliation Delta — 2026-08-15b (ORCH-MP Wave 0)

Produced per `aether-admin-sales-agent-execution-prompt.md` §0.1/§0.2/§0.7 by session **ORCH-MP**
(read-only recon 2026-08-15T17:55–18:20Z, reconciliation actions 18:20Z+). Baseline evidence:
`uat/reports/evidence/market-perf/wave0/`. Governance range: GOV-060–079; ticket prefix MP-*.
This document records every observed delta between the execution prompt's §0 authoring-time
snapshot and the live state, plus the autonomous rulings taken to reconcile them.

## 1. Deltas vs §0 (observed state, with evidence)

| # | §0 claim | Observed 2026-08-15T18:1xZ | Impact |
|---|---|---|---|
| **D1** | §0.1: main @ a8cb21f8, 16 ahead of origin, ~70 uncommitted files; second worktree `aether-wt-u5d4` @ 48446945 | Tree **CLEAN** (0 dirty), main @ a4800b65, **24 ahead / 0 behind** origin/main (48446945); `aether-wt-u5d4` worktree and its local branch **removed**. A prior consolidation session (~13:41–15:25Z, backups at `/home/ubuntu/aether-backups/orchestrator-consolidation-20260815/`) committed 8 feature commits (0444bcf0 footer editor, de0b3591 branded posters, cc2986bb catalog pricing editor, 75fcb6a6 Gmail contacts import, 35d56baf template render fix, 78c0c0a0 chore, e218a90a lifecycle live-scope gate, a4800b65 analytics guidance), stashed the remaining ~70-file WIP as `stash@{0}` "orch-preserve-pre-consolidation-2026-08-15" (parent a8cb21f8; 46 M + 14 D + 13 untracked), and removed the u5d4 worktree. | §0.1's hazard already half-resolved; remaining work = land stash + preserve u5d4 (done, §2). Waves A/C/D have **partial pre-implementations on main** — later waves must verify/harden, not rebuild. |
| **D2** | §0.2: `aether-sales-agent.timer` DEAD | Timer **ACTIVE (waiting)** since 15:25:13Z, fires `*:15/30`, last 17:45Z, next 18:15Z; runs from this (clean) tree. | Re-armed by the consolidation session. No action needed in Wave 0; R3 verification later. |
| **D3** | Production serves main | Services active: api 10:29:47Z, web 10:29:50Z, worker 09:08:47Z; health `{"status":"ok","version":"0.2.0"}`. Prod does **NOT** serve the 8 consolidation commits (authored 14:10Z+) nor the stash content — served build predates them. | Not a Wave-0 problem (prompt forbids restarts this wave). A deploy window in a later wave must ship reconciled main. |
| **D4** | u5d4 worktree holds unpushed branch work | Branch existed **nowhere** as a ref (origin has only `main`); work survived only in `patches/u5d4.diff` (SHA256-verified, applies cleanly): `apply_executor.py` +525 verification-code-loop, tracker-lib + tests. | Preserved as branch, §2 R-2. |
| **D5** | ui-brand session may be live | Sessions 42a0f0a8 (Wave E owner) + peer (socket 2331, Wave C/D) **TERMINATED**: no `claude` processes ~7 h; their 11:2xZ claimed restart window (ETA 30–60 min) never executed; tmux sessions idle. | Liveness ruling GOV-060, §2 R-1. Their SESSION-COORDINATION claims released; exclusive wipe claim void (flag resolutions F1–F5 carry forward as operator decisions). |
| **D6** | — | `aether-autodeploy.timer`, `aether-backup.timer`, `aether-email-agent.timer` enabled-but-inactive (NEXT=−). Deploys are currently manual. | Recorded; ops item for a later wave. |
| **D7** | Backups preserve untracked files | The 3 `untracked/*.tar.gz` in the consolidation backup are **empty** (45-byte headers, zero entries). | See D9. |
| **D8** | r2 patches pending | `r2-catalog.diff` landed as cc2986bb; r2-template remediation superseded/landed via 35d56baf + 78c0c0a0 (reverse-apply partial failure = later evolution, not loss). | No action. |
| **D9** | — | u5d4's untracked `apps/api/tests/test_u5d4_verification_code_email.py` is **LOST**: absent from `u5d4.diff`, from the empty untracked tarballs, from all platform snapshot commits, and from the filesystem. | Only genuine data loss found. The verification-code-loop implementation itself is preserved (D4); its dedicated test must be re-authored when that branch is taken up. |
| **D10** | §0.7 names `docs/delivery/PROD-PRISTINE-WIPE-MANIFEST-2026-08-15.md` | File was **missing from the tree and from all refs** — it existed only as an uncommitted file captured in platform snapshot cb38dbac (05:05Z) and was dropped during the consolidation. | Restored byte-exact and committed (31bb058b, GOV-061). R5 unblocked. |

## 2. Rulings (autonomous, per prompt §0.1 shared-tree hazard rule)

- **R-1 (GOV-060) — foreign sessions terminated.** Evidence: zero `claude` processes for ~7 h; claimed
  restart window never executed (`aether-web` ExecMainStart unchanged at 10:29:50Z); idle tmux.
  Their preserved work is therefore landed by ORCH-MP **with attribution** (commit messages name the
  authoring sessions), and their coordination claims are released (recorded in SESSION-COORDINATION.md).
- **R-2 (MP-001) — u5d4 preserved, not merged.** Branch `feat/u5d4-verification-code-loop` recreated at
  48446945 + `u5d4.diff` applied (SHA256-verified) → commit 51016fee, **pushed to origin**. Not merged
  to main in Wave 0 (unfinished feature; its test was lost, D9).
- **R-3 (MP-002) — ui-brand stash landed with curation.** Branch `land/ui-brand-20260815` from a8cb21f8,
  `stash apply` → curated commit ab3bdedb → merged main into branch (df025e4b, zero conflicts) →
  merged to main (2a124a52). Curation per GOV-062: platform-metadata hunk excluded; the stash's
  **14 evidence-log deletions rejected** (evidence retention beats foreign cleanup intent);
  platform-autogenerated .docx/.pdf prompt previews excluded; duplicate wipe-manifest copy dropped
  (identical to main's). **BLOCKER-001/GATE-31 guard verified present** in the landed
  `repositories/admin.py` (15 marker mentions) pre- and post-merge. Stash@{0} retained (not dropped)
  until Wave-0 close is verified green.
- **R-4 (GOV-061) — wipe manifest restored** from snapshot cb38dbac (see D10); diff vs snapshot = 0 lines.
- **R-5 — no production restarts in Wave 0.** Prod continues serving the pre-consolidation build (D3);
  shipping reconciled main is deferred to a claimed deploy window in a later wave.

## 3. Git end-state (Wave 0)

- `main` = merge 2a124a52 (24 prior commits + GOV-061 restore 31bb058b + claim 3f59b169 + ui-brand
  landing ab3bdedb/df025e4b), **pushed to origin** (0 ahead / 0 behind at close — see §5).
- `origin/feat/u5d4-verification-code-loop` = 51016fee (preservation branch).
- `origin/land/ui-brand-20260815` = pushed for audit trail (see §5).
- Working tree: clean except deliberately retained items listed at close (§5).
- stash@{0} retained deliberately until close verification.

## 4. G1 regression baseline (recorded on reconciled main)

Prior-session baseline for attribution (ORCH-RUN-REPORT-2026-08-15.md): backend 3F/4011P ·
vitest 100% · e2e 58P/23F (21 pre-existing: spec-locator drift + S-UI-B4-MOBILE) · build PASS.

| Gate | Commit | Result | Attribution |
|---|---|---|---|
| Web build (`next build`, isolated worktree `/tmp/wt-build`, never the served `.next`) | 49d28fbf | **PASS**, BUILD_ID `5XZ7TTl2XrvNQR1G3TO-g` (`webbuild-main-49d28fbf.log`) | — |
| tsc `--noEmit` (apps/web) | 2a124a52 | **PASS** (rc 0) | — |
| vitest full (apps/web) | 2a124a52 | **1957 P / 2 F** (223/225 files) (`vitest-postmerge.log`) | Both **INHERITED**, not introduced by the ui-brand landing: every input file (test, `workflow-linkage.ts`, `routers/agents.py`, `prose-census` inputs) is byte-identical between origin/main@48446945 (prior session's verified-green close) and post-merge main — the merge only changed `rounded-2xl→rounded-[14px]` on the analytics page. (1) `prose-census` fails on the "What this tells you / What to do next" prose a4800b65 added without census roles → routed **MP-010** (R1.2 work, Wave A). (2) `workflow-linkage-provenance` — 2 citations stale vs `agents.py` line positions unchanged since 8a20d031; the prior "provenance 58/58" claim does not reproduce on main as-is → routed **MP-011**. |
| pytest targeted post-merge batch (10 admin/sales files) | 2a124a52 | 13 F initially → after GOV-063 quarantine: **2 F / 115 P / 12 skipped** (`attribution-pytest-*.log`) | (a) 9 F in `test_blocker010_board_sweep_abort_recovery.py` — **branch-introduced by the landing**: spec authored against a BLOCKER-010 implementation that never landed (moved aside 2026-08-13, `FOREIGN-WIP-MOVED.md`); quarantined via module skip (**GOV-063**, commit 49d28fbf) until the preserved fix lands. (b) `test_admin_creates_branded_poster_and_identical_request_reuses_it` (201 vs 200) and (c) `test_billing_summary_counts_only_stripe_backed_non_admin_subscribers` — both reproduce IDENTICALLY at pre-merge a4800b65 (`attribution-pytest-pair-premerge-a4800b65.log`) → **INHERITED** from consolidation commits de0b3591/cc2986bb-era work → routed **MP-012 / MP-013** (Wave A/C hardening). 2 further batch failures were pollution from the unquarantined blocker010 module (pass in isolation and post-quarantine). |
| pytest full backend (apps/api, ~4k tests) | 49d28fbf | see close-out §5 (`pytest-full-main-49d28fbf.log`) | vs prior baseline 3 F / 4011 P |
| e2e Playwright (read-only `next start :3100` against the isolated build) | 49d28fbf | see close-out §5 | vs prior baseline 58 P / 23 F (21 pre-existing incl. S-UI-B4-MOBILE) |

## 5. Close-out

<!-- CLOSE-OUT: filled at Wave-0 close -->
**Wave-0 checkpoint 2026-08-15T19:4xZ (run cut at platform time limit):**
- Reconciliation COMPLETE: main = 49d28fbf pushed (0 ahead / 0 behind); branches
  `feat/u5d4-verification-code-loop` (51016fee) and `land/ui-brand-20260815` pushed to origin;
  stash@{0} retained; tree clean apart from this doc + evidence (committed at this checkpoint).
- Gates recorded: build PASS (BUILD_ID 5XZ7TTl2XrvNQR1G3TO-g), tsc PASS, vitest 1957P/2F (both
  inherited, MP-010/011), targeted pytest 115P/2F/12skip (2 inherited MP-012/013; GOV-063 quarantine).
- **Full backend pytest is RUNNING detached** (setsid, `pytest-full-main-49d28fbf.log`, ~13% at cut;
  survives this session — read its tail + DONE_RC for the final count, attribute vs 3F/4011P).
- **e2e NOT yet run** — next session: `pnpm exec playwright test` from `/tmp/wt-build/apps/web`
  (isolated build already present there); attribute vs 58P/23F.
- Production untouched this wave: api 10:29:47Z / web 10:29:50Z / worker 09:08:47Z, health ok 0.2.0,
  sales timer ACTIVE; no restarts, no timer changes.
