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

## §6 CHECKPOINT 2026-08-15T20:2xZ (context cutoff — resume here)
- MP-010/011 FIXED+GREEN (vitest verified earlier). MP-012/013 fixes in tree (conftest SalesBrandArtifact truncation; test_admin2_billing try/finally price restore) — NOT yet run.
- MP-020 COMPLETE in tree: RED tests appended to tests/test_sales_agent.py; audit logging added to ALL 6 unaudited sales_agent.py mutations (create/update campaign, run_now, generate, put_config, set_sending_account). Syntax OK. NOT yet run.
- Wave-0 full pytest baseline (clean 49d28fbf) OOM-KILLED at 76% (hermes OOM, pid 125315); partial log: uat/reports/evidence/market-perf/wave0/pytest-full-main-49d28fbf.log — 4 F observed by 76%, consistent with inherited fails. Recorded honestly; authoritative gate = sharded re-run below.
- SHARDED full pytest vs WORKING TREE running detached (flock /tmp/aether-pytest.lock, /tmp/run-pytest-sharded.sh, 8 shards): log uat/reports/evidence/market-perf/wave-a/pytest-full-wavea-worktree.log, DONE_RC= at end. Was in shard 1/8 at cutoff. DO NOT source repo .env before pytest (AETHER_ENV=production trips §REC-04 replay guard).
- Remaining: poll shard log → expect 0 unexpected F (12 blocker010 skips OK); vitest+tsc (run SERIALLY, concurrent runs OOM the box); e2e baseline from /tmp/wt-build (ln -sf repo .env → /tmp/wt-build/.env first); commit hunk-owned; deploy per runbook Complete Deploy Recipe (verify-web-build.sh gate; auto-deploy timer INACTIVE — manual deploy); PROD verify + adversarial review; flip R2.1–R2.5/G1–G7 in /home/ubuntu/aether-market-performance.md.

## §7 CHECKPOINT 2026-08-15T21:5xZ (context cutoff 2 — resume here)
GATE RESULTS (Wave A tree, all evidence under uat/reports/evidence/market-perf/wave-a/ unless noted):
- Full backend pytest (sharded, pytest-full-wavea-worktree.log): **4235 passed / 2 failed / 13 skipped**, DONE_RC=1. The 2 fails = tests/test_u5b_apply_executor.py::TestSuccessfulTransmission (both) — ManualStepRequired "Pronouns; Location" (Playwright combobox fill vs Ashby replay fixture). REPRODUCED IDENTICALLY on clean main 61738ea9 from /tmp/wt-main61 worktree (pytest-u5b-main61738ea9-inherited.log; isolated idle rerun pytest-u5b-isolated-inherited.log) → **INHERITED, ownership-routed as MP-021** (apply-executor domain = Wave D). MP-012/MP-013 fixes VERIFIED GREEN (test_admin2_billing in shard 1 RC=0; test_sales_agent incl. MP-020 RED→GREEN tests all passed in shards).
- tsc --noEmit: PASS (DONE_RC=0, /tmp/wave-a-logs/tsc.log).
- Full vitest: **1959/1959 PASS** (/tmp/wave-a-logs/vitest2.log; first run had 1 load-flake in catalog-pricing-page.test.tsx that passes isolated + on full rerun — flake, not regression).
- e2e G1 baseline RUNNING DETACHED at cutoff from /tmp/wt-build/apps/web (./node_modules/.bin/playwright test; log uat/reports/evidence/market-perf/wave0/e2e-main-49d28fbf.log, DONE_RC= appended). NOTE: to make it run, /tmp/wt-build/scripts/run-e2e-server.sh line 76 patched IN THE THROWAWAY WORKTREE ONLY (pnpm exec next start → ./node_modules/.bin/next start; pnpm's verify-deps-before-run aborts with no TTY in the worktree); /tmp/wt-build/.env symlinked to repo .env. Repo copy of script UNCHANGED. Compare vs baseline 58P/23F (21 pre-existing incl. S-UI-B4-MOBILE).
REMAINING (in order): poll e2e DONE_RC + attribute; hunk-owned commits (1: MP-010/011 web fixes; 2: MP-012/013 test-isolation; 3: MP-020 audit logging feat+tests; 4: docs) + push main; claim deploy window in SESSION-COORDINATION.md; deploy per runbook Complete Deploy Recipe (build in served tree apps/web, verify-web-build.sh gate, fresh BUILD_ID != 5XZ7TTl2XrvNQR1G3TO-g, restart api→web→worker, ExecMainStartTimestamp re-check, health); PROD verify + adversarial review (non-admin 401/403 on /api/admin+/api/sales-agent, footer illegal edit 422, audit rows present, deleted-user default-view leakage); flip R2.1–R2.5 + G1–G7 in /home/ubuntu/aether-market-performance.md with proof links; update SESSION-COORDINATION.md.

## §8 G1 e2e baseline FINAL (2026-08-15T22:0xZ)
- e2e (82 tests, 16.6m, read-only next start :3100 against isolated build 49d28fbf / BUILD_ID 5XZ7TTl2XrvNQR1G3TO-g): **60 passed / 22 failed** (log: uat/reports/evidence/market-perf/wave0/e2e-main-49d28fbf.log).
- Attribution vs prior baseline 58P/23F: all 22 failures are in the SAME pre-existing spec files/classes (analytics/S-UI locator drift: analytics, auth-recipe-proof, dashboard root-redirect, gap_p7_def_b, launch-b1-approvals-remove, phase7-route-sweep, wg-admin-login-path; mobile-overflow S-UI-B4 class: ml-admin-002, ml-agents-refix, ml-fe-polish, mobile-regression). **0 new failures introduced**; net −1F/+2P vs prior run = run-environment variance, consistent with the prior run report's own caveat. G1 e2e verdict: **no regression**.

## §9 Deploy + PROD verify + adversarial review (2026-08-15T22:4xZ) — AND SCOPE CHANGE
- **Deploy (runbook Complete Deploy Recipe, window claimed in SESSION-COORDINATION.md):** main@bdf24ea8; pip deps current; `pnpm install --frozen-lockfile` up to date; served-tree web build RC=0; `scripts/verify-web-build.sh` **PASS**, fresh **BUILD_ID DeEIFhAWVOahh35jcflP9** (prior isolated baseline 5XZ7TTl2XrvNQR1G3TO-g); restarts under flock /tmp/aether-deploy.lock: api 22:42:32Z → web 22:42:34Z → worker 22:42:39Z; all `is-active` incl. redis-server.
- **PROD verify:** public `/api/health` = `{"status":"ok","version":"0.2.0"}`; root 200; next-rewrite :3000 health 200; api-direct :8000/health 200. journalctl -p err since restart: **no entries** (all 3 services). Admin API sweep with owner bearer (secrets parsed programmatically, never printed): users?view=active 200 (9), plans 200 (4), admin/sales-agent/brand/templates 200 (5), promos 200 (4), audit-log 200 (5), hygiene 200. Evidence: `uat/reports/evidence/market-perf/wave-a/prod-verify-endpoints.txt`. Note: edge blocks default python UA (403) — probes require a browser UA.
- **Adversarial review (independent-verifier persona): 20/20 probes PASS, 0 findings.** Anon → 401 ×6; fresh non-admin user → 403 ×6 (throwaway then soft-deleted via typed-confirm DELETE, 200; active view restored to 9, no probe residue); illegal footer PUT → 422 with template byte-identical after; benign PUT config → 200 and `sales_agent_config.updated` is newest audit row (MP-020 live-verified); active∩deleted user id sets = ∅; BLOCKER-001/GATE-31 guard literals intact in repositories/admin.py; .env confirmed gitignored; post-probe err-log scan clean. Evidence: `uat/reports/evidence/market-perf/wave-a/adversarial-review.md`.
- **SCOPE CHANGE (operator directive, 2026-08-15T22:5xZ): ledger flips WITHHELD.** The operator now requires, before ANY completion claim: the 22 e2e failures (previously attributed pre-existing / ownership-routed, incl. S-UI-B4 mobile class) **fixed to green**, plus a production-codebase-wide sweep proving zero placeholder/mock/duplicate code, zero hardcoded/dummy credentials or test data, and zero dry-run simulations. R2.1–R2.5 and G1–G7 therefore remain `[ ]` pending that re-scoped work; the deploy + verify facts above stand as recorded evidence, not as a completion claim.


## §10 Directive wave (MP-030+): 22-e2e-failure triage (2026-08-16)

Baseline log: `uat/reports/evidence/market-perf/wave0/e2e-main-49d28fbf.log` (82 tests, 60P/22F, vs isolated build 49d28fbf on :3100). Every failing spec file and the runtime code it exercises was read in full before ruling. Rulings use three classes: **real defect** (product code wrong), **stale expectation** (test asserts a UI/behaviour contract that was intentionally changed — fix the test, justify here), **harness** (test infrastructure/wait-strategy/server-topology problem — fix the harness, assertions unchanged).

| # | Spec / test | Observed failure | Class | Ruling & fix |
|---|---|---|---|---|
| 1 | `analytics.spec.ts:16` funnel renders live numbers | Strict-mode violation: `funnel.getByText("Jobs Found")` resolves 3 elements | Stale expectation | The product INTENTIONALLY renders the "Jobs found" label three times inside `funnel-chart` (visible bar label, honesty footnote added with the C-3 caption work, sr-only accessible data-table rowheader in `ChartFrame`). Assertion intent = "the label is rendered" → `.first()` with a comment. No product change. MP-030. |
| 2 | `auth-recipe-proof.spec.ts:24` | `waitForNavigation({waitUntil:'networkidle'})` 30s timeout post-login on PROD | Harness | The authenticated dashboard legitimately polls (live agent/approval data), so `networkidle` can never settle — Playwright's own docs mark `networkidle` DISCOURAGED for tests. Replace with `page.waitForURL(/\/dashboard/)`; assertions (URL, token, authed chrome) unchanged. MP-031. |
| 3 | `dashboard.spec.ts:40` anonymous `/` → `/pricing` | Landed on `/dashboard` | Harness (authed-context leak) | The test's own comment says "a fresh (anonymous) context has no session", but it runs inside the `chromium` project whose `storageState` injects the logged-in `aether_token` — so `src/app/page.tsx` correctly routes the AUTHENTICATED context to /dashboard. Product behaviour verified correct by source read. Fix: scope the test to an empty `storageState`. MP-032. |
| 4 | `gap_p7_def_b.spec.ts:97` | `expect.soft` precondition: stored email is the owner's real address, not `@aether.local` | Stale expectation | The spec's own header says a non-`@aether.local` account should "soft-check rather than hard-fail so the test still exercises the save path" — but `expect.soft` still fails the test at the end, contradicting the documented intent. The seeded `admin@aether.local` row no longer exists (BLOCKER-001 revocation + real owner email). Convert the precondition to a `test.info()` annotation; the REAL assertions (save succeeds; invalid email blocked client-side) unchanged; the reserved-TLD backend contract stays pinned by `apps/api/tests/test_gap_p7_def_b_email_validation.py`. MP-033. |
| 5,6 | `launch-b1-approvals-remove.spec.ts:25,122` | 30s timeout waiting for `getByRole('button', {name:'rejected'/'all'})` | Stale expectation | The approvals filter strip was intentionally migrated (B2 global-controls pass) from `aria-pressed` buttons to the shared `<SegmentedControl>` — `role="tablist"`/`role="tab"` with capitalized labels. Update locators to `getByRole("tab", {name:"Rejected"/"All"})`. Assertions unchanged. MP-034. |
| 7,8 | `ml-admin-002-mobile-overflow.spec.ts` | `ERR_CONNECTION_REFUSED http://127.0.0.1:3010` | Harness | Spec (by design, per header) targets a separately-started isolated API+web pair on the `aether_test` schema; no automation ever started it, so it has never run inside the main suite. Fix: automated companion stack (see §10.1) + run with the spec's documented `E2E_BASE_URL`/`E2E_ADMIN_EMAIL`/`E2E_ADMIN_PASSWORD` overrides. MP-035. |
| 9,10 | `ml-agents-refix.spec.ts` | `ERR_CONNECTION_REFUSED :3012` | Harness | Same class as #7 (documented in runbook §0.5 as residual risk). Signup-based throwaway users MUST NOT be created in the prod DB, so the companion stack serves an `aether_test`-schema API. MP-035. |
| 11–15 | `ml-fe-polish.spec.ts` (5 tests) | `ERR_CONNECTION_REFUSED :3091` | Harness | Same as #9. MP-035. |
| 16–19 | `mobile-regression.spec.ts` (4 tests) | `goto networkidle` timeouts on /dashboard, /dashboard/approvals at 390px; console_errors/layout recorded FAIL | Harness (+ verify) | Same `networkidle`-vs-polling-dashboard problem as #2 — navigation never "settles" so the run times out before layout is even measured. Replace with `load` + explicit content sentinels; console-error/layout assertions unchanged and re-adjudicated on the re-run (any REAL console error or layout overflow that then surfaces is fixed as a product defect, S-UI-B4-MOBILE overlap noted). MP-036. |
| 20 | `phase7-route-sweep.spec.ts:161` | (a) `networkidle` 45s nav timeouts on /dashboard,/analytics,/applications; (b) console errors incl. ChunkLoadError/MIME text/html for a prod `_next` chunk on /dashboard/agents; (c) accumulated soft-assert | Harness (+ prod re-verify) | (a) same networkidle-vs-polling class → `load` + settle window, listeners unchanged. (b) sweep ran against PROD mid-window on build `5XZ7TTl2…` while HTML/chunk versions skewed (stale HTML referencing purged chunks) — prod has since been redeployed (BUILD_ID `DeEIFhAWVOahh35jcflP9`); re-verified on the re-run; if ChunkLoadError persists on current prod it is escalated as a REAL defect, not papered over. MP-037. |
| 21,22 | `wg-admin-login-path.spec.ts` | `ERR_CONNECTION_REFUSED :3095` | Harness | Same isolated-pair class as #7; fixture admin/user rows are register+SQL-promote in `aether_test` (never seeded `admin`, never owner creds). Covered by companion stack + `WG_E2E_*` overrides. MP-035. |

### §10.1 Companion-stack design (MP-035)
One automated, torn-down-after stack replaces the "manually started pair" residual risk (runbook §0.5): a dedicated uvicorn API on **:8300** pointed at `DATABASE_URL_TEST` (`aether_test` schema; admin-rotation envs pinned out, LLM replay mode, credential key test-scoped — mirrors `apps/api/tests/conftest.py`), plus a companion `next start` on **:3110** serving a build whose `/api` rewrite was BAKED with `AETHER_API_PROXY=http://127.0.0.1:8300` into a separate dist dir (`.next-companion`, gitignored; `next.config.ts` gains an env-driven `distDir` so the production `.next` is never touched). Fixture users (ml-admin-002 admin, wg admin+user) are registered via the API then SQL-promoted in the test schema. The full-suite runner exports the specs' documented `E2E_BASE_URL`/`WG_E2E_BASE_URL`/credential env overrides pointing at :3110. All signup-created throwaway users land in `aether_test`, never in prod.

### §10.2 Directive wave — FINAL gate results (2026-08-16T00:1xZ)
- **e2e: 82/82 PASSED** (full-suite runner `scripts/run-e2e-full.sh`: main stack :3100 + companion stack :3110/:8300; evidence `uat/reports/evidence/market-perf/directive-sweep/e2e-82of82-run2.log`). All 22 baseline failures fixed per §10 rulings (MP-030..037); zero product assertions weakened.
- **Full backend pytest: 4237 passed / 0 failed / 13 skipped.** Sharded run (evidence `directive-sweep/pytest-sharded-full.log`) surfaced ONE real defect: `test_admin_sets_a_password_hashes_it_and_invalidates_sessions` — root-caused as **MP-038 clock-skew** (DB clock measured ~0.78s ahead of API; `passwordChangedAt` stamped by DB `now()` vs JWT `iat` from API clock falsely 401'd a fresh post-change login for its whole TTL). Fixed by same-clock stamping (`to_timestamp(time.time())`) in `repositories/user.py::set_password` + `repositories/admin.py::create_user_row`; ruff+mypy clean. Shards 1–3 rerun clean after fix: 657P/13S, 555P, 397P RC=0 (evidence `directive-sweep/pytest-rerun-shards123-clean.log`); shards 4–8: 559+447+447+674+501 all RC=0. The 2 other shard fails in the first pass were contamination from concurrent debug sessions against the shared `aether_test` schema — both files green in the rerun.
- **tsc --noEmit: PASS. vitest: 1959/1959 (225 files).**
- **Cleanliness sweep: 0 FIX-ruled items** in production code (`directive-sweep/SWEEP-FINDINGS.md`) — every placeholder/mock/credential-pattern hit ruled legitimate (anti-fabrication machinery, test-only fixtures, operator identifiers, error logging).
- **MP-021 fixed** (was ownership-routed): apply-executor combobox honest fallback for zero-option lists; 20/20 in `test_u5b_apply_executor.py`.
- Commits: `e5d85c92` (e2e MP-030..037), `7a9c7663` (MP-021), `5c8a7428` (MP-035 companion stack), `d09fc071` (MP-038 clock-skew). Pushed `ab44f11a..d09fc071`.
