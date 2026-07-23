# W-C Wave 1 manifest — SAFE (web/TS dead exports & files)

- Date: 2026-07-24 | Base: `8e8e2a2` (main) | Executor: dedup-surgeon (W-C)
- Inventory source: `uat/reports/evidence/dedup/DEDUP-INVENTORY.md` (53 candidates, discovered at `aa5c241`), corrections in `uat/reports/evidence/dedup/CONSOLIDATION-PLAN.md`.
- Fresh sweep on THIS tree (8e8e2a2): `npx knip@5 --exports --reporter json` → `knip-fresh-pre-8e8e2a2.json` (44 unused exports + 88 unused exported types — includes new W-B-era symbols, e.g. `PurgeExpiredResultSchema`, `PipelineMoveResultSchema`).

## Candidates in this wave (6)

| Candidate | Class | Fresh refs-proof (at 8e8e2a2) | Disposition |
|---|---|---|---|
| DEDUP-002 dead auth barrel `lib/auth/index.ts` | SAFE | **Inventory correction found during fresh trace:** barrel WAS live via relative import `./index` in `next-auth-options.ts` (inventory grep only covered `@/lib/auth`); `authorizeCredentials`/`StoredUser`/`SESSION_MAX_AGE_SECONDS` re-pointed to leaf modules (`credentials.ts`, `options.ts`), then barrel = 0 refs → deleted. `createTestSession` 0 refs → deleted. `createTestToken` is LIVE (`__tests__/auth/require-auth.test.ts:4`) → **kept** (inventory's DEDUP-002 note "reachable only through the barrel" was wrong for it). | deleted (barrel), kept createTestToken |
| DEDUP-003 dead exported functions | SAFE | Per-symbol grep across `src`, `e2e`, `__tests__`, `packages`, `scripts`: 8 functions with 0 refs beyond def (`fetchAgentConfigList`, `putUserCredential`, `deleteUserCredential`, `verifyUserCredential`, `fetchResume`, `fetchInterviewPrep`, `fetchGmailAccounts`, `fetchOAuthStatus`) → deleted. 5 flagged functions are used **in-file** (`pollJob`, `fetchGoogleLoginUrl`, `loadSearchIndex`, `isGateExempt`, `isBusy`) → `export` keyword dropped only. | deleted 8 fns; export-dropped 5 |
| DEDUP-004 unused exported Zod schemas | SAFE | knip-fresh list; each symbol verified used in-file via `z.infer` → `export` dropped, const kept. | consolidated (export-dropped) |
| DEDUP-005 unused exported constants | SAFE | knip-fresh list; in-file usage verified per symbol. | export-dropped |
| DEDUP-006 unused exported types | SAFE | knip-fresh list (88 types incl. new since discovery); export-dropped where used in-file; 5 declarations with 0 remaining refs after the function deletions (`InterviewPrep`, `GstBreakdown`, `GmailAccount`, `OAuthStatus`, `ApplicationStatus`) fully deleted. | export-dropped + 5 decls deleted |
| DEDUP-012 stale `ml-*.playwright.config.ts` ×3 | SAFE | grep across repo/CI/scripts: only self-refs + doc comments in their paired specs; default `playwright.config.ts` `testDir ./e2e` still discovers the specs (verified: `playwright test --list` finds 9 ml-* tests post-delete). | deleted (3 files) |

Total wave diff: 44 files, +97/−205 lines (net −108 in-tree; 5 files removed incl. barrel + 3 configs; ~99 export keywords dropped).

## Verification (all green, vs baseline `runtime/baseline-suites.md`)

- `pnpm exec tsc --noEmit` → 0 errors (after the two live-ref corrections above; the intermediate tsc failure is what CAUGHT them).
- `pnpm lint` → 0 warnings/errors.
- `pnpm test` (vitest) → **567 passed / 0 failed** = baseline (81 files).
- `pnpm build` → success.
- `playwright test --list` → 86 tests/24 files, ml-* specs discoverable.
- pytest NOT run this wave: zero Python files touched (wave is apps/web-only); full pytest runs at the Python wave + final pre-deploy gate.
