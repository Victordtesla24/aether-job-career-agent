# Workstream C — Wave 3 Manifest (CAREFUL: packages/* orphan layer + CI de-wire, root docs, devDeps)

Date: 2026-07-24 (Australia/Melbourne)
Base commit: 708abcc (wave 2)
Wave class: CAREFUL (3 candidates: DEDUP-040+N01, DEDUP-041, DEDUP-042)
Reference traces: `wave-3-traces.txt` (fresh, captured this session BEFORE any deletion)

## Rollback note (written BEFORE touching anything)

This wave is ONE revertible commit. If `pnpm install`, tsc, lint, vitest, or the web build
break after the deletion, roll back wholesale with `git revert <wave-3-sha>` (or
`git reset --hard <wave-2-sha>` if not yet pushed). No partial restore — the packages
deletion + workspace/CI de-wiring are coordinated and must land or revert together.
Production runtime risk is LOW: fresh traces confirm nothing deployed imports `packages/*`
(0 `@aether/*` deps in apps/web, no `transpilePackages`, no path imports, no deploy/ refs,
live `.github/workflows/ci.yml` has zero packages/prisma/pnpm -r references).

## Planned actions (per CONSOLIDATION-PLAN U38/U11/U10, Correction-2)

### DEDUP-040 + N01 (U38) — packages/* TS runtime
- Hard-delete: `packages/agents/`, `packages/queue/`, `packages/shared/` (whole);
  `packages/db/` everything EXCEPT `src/schema.prisma` (DO-NOT-TOUCH carve-out,
  schema-of-record cited by `apps/api/app/db.py:3`) — keep a minimal
  `packages/db/package.json` holding only the `prisma.schema` pointer.
- De-wire: root `.eslintrc.cjs` (existed only for packages lint); root
  `@typescript-eslint/*` + `eslint` devDeps; keep `turbo.json` + root `turbo`
  (still orchestrates `apps/*`); keep `pnpm-workspace.yaml` `packages/*` glob
  (still matches the slimmed `packages/db`).
- CI mirror (N01): update `ci/github-actions-ci.yml` (drop `@aether/db prisma:generate`
  steps at lines 82/158, replace `pnpm -r run …` with `--filter @aether/web`) and
  `ci/README.md` line 17. Live workflow untouched.

### DEDUP-041 (U11) — superseded root docs
- `git mv gap-analysis.json docs/delivery/gap-analysis.json`; fix references
  (`docs/delivery/EXECUTION-REPORT.md:57`, PHASE5-GAP-ANALYSIS.md:8, any others found by grep).
- Delete root `EXECUTION-REPORT.md` (4-line redirect stub; README already links the docs copy
  — update README line 210 note) and `gap_analysis_report.md` (self-declared HISTORICAL/SUPERSEDED);
  fix any dangling references (PHASE7-CLAIM-LEDGER.md:77 mentions them as a pattern — textual
  mention, adjust only if it becomes a broken link).

### DEDUP-042 (U10) — redundant apps/web devDeps
- Drop `@typescript-eslint/eslint-plugin` + `@typescript-eslint/parser` from
  `apps/web/package.json` (transitive via `eslint-config-next` → `next/typescript`;
  `.eslintrc.json` confirmed extends `next/typescript`).
- If lint output changes at all → restore the two deps (low-confidence finding).

## Verification plan
`pnpm install` resolves; `pnpm exec tsc --noEmit`, `pnpm lint` (identical output),
`pnpm test` (567 expected — vitest scope is apps/web only, packages tests were never
in that run), `pnpm build`. No Python touched → no pytest rerun needed for this wave
(wave-2 full run + final pre-deploy verification cover it).

## Execution record

Executed exactly as planned above. Results:
- packages/agents, packages/queue, packages/shared: deleted whole; packages/db reduced to
  `src/schema.prisma` + minimal `package.json` (prisma.schema pointer only).
- Root `.eslintrc.cjs` deleted; root devDeps now `{turbo}` only; apps/web dropped the two
  `@typescript-eslint/*` devDeps (DEDUP-042) — lint output identical (✔ No ESLint warnings or errors).
- CI mirror `ci/github-actions-ci.yml`: both `@aether/db prisma:generate` steps removed;
  `pnpm -r run lint|type-check|test|build` → `pnpm --filter @aether/web run …`. `ci/README.md`
  updated. Post-check: `grep -rn "@aether/db|prisma:generate|pnpm -r" ci/` → 0 hits.
  Live `.github/workflows/ci.yml` untouched (never referenced packages — Correction-2).
- DEDUP-041: `gap-analysis.json` → `docs/delivery/`; root `EXECUTION-REPORT.md` stub +
  `gap_analysis_report.md` (self-declared HISTORICAL) deleted; references fixed in
  `docs/delivery/EXECUTION-REPORT.md:57`, `docs/delivery/PHASE5-GAP-ANALYSIS.md:8`, `README.md:210`.
  `docs/delivery/PHASE7-CLAIM-LEDGER.md:77` mentions the old files as a historical pattern
  (point-in-time ledger snapshot, not a link) — deliberately left verbatim.
- `pnpm install` (lockfile regenerated, −761 lock lines); tsc 0 errors; lint identical;
  vitest **567 passed / 0 failed** (baseline-equal — packages tests were never in the
  apps/web vitest scope); `pnpm build` success. No Python touched (comment-only refs in
  agents.py/db.py left as documentation).
- Net: **69 files changed, +14 / −3,246 lines** (single revertible commit).
