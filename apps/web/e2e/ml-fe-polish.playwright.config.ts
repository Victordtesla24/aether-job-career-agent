import { defineConfig, devices } from "@playwright/test";

/**
 * Standalone Playwright config for the ML-fe-polish live-repro specs
 * (MODELS-LIVE §7 step 2, batch-4 FE-polish findings):
 *
 *   - ML-settings-001 (overflow half) — oversized-field 422 error banner
 *     causing horizontal overflow on /dashboard/settings.
 *   - ML-resume-002 — 16px overflow at 390px on /dashboard/resume.
 *   - ML-agents-006 — 255px overflow at 390px on /dashboard/agents, from
 *     the Agent Orchestration panel's 3-column grid.
 *
 * Mirrors the ML-admin-002 / ml-agents-refix local-repro pattern: the
 * repo's main ./playwright.config.ts pins `baseURL: "http://127.0.0.1:3000"`
 * (the DEPLOYED production port) with a shared authenticated storageState.
 * Reusing it here would run against the live deployment with a shared
 * session — these findings need their own throwaway users and must never
 * touch production. Points instead at a locally-managed API+web pair on
 * dedicated ports 8091/3091 — distinct from the deployed 8000/3000 and every
 * other known local-repro pair (8010/3010 ML-admin-002, 8012/3012
 * ml-agents-refix) — whose API's DATABASE_URL is the shared `aether_test`
 * schema, individually exported (never a blanket `source .env`); see
 * ml-fe-polish-start-{api,web}.sh in the scratchpad for how those were
 * started.
 *
 * Run: apps/web$ ./node_modules/.bin/playwright test \
 *        --config=e2e/ml-fe-polish.playwright.config.ts
 * (override E2E_BASE_URL to point at a different already-running instance.)
 */
export default defineConfig({
  testDir: ".",
  testMatch: "ml-fe-polish.spec.ts",
  fullyParallel: false,
  reporter: "list",
  // next dev's on-demand per-route compilation can take well past the
  // default 30s navigation timeout on a page's FIRST hit (resume.tsx in
  // particular pulls in the hero/diff/ATS/conversion-metrics panels) —
  // generous enough that a slow first compile never masquerades as this
  // finding's actual (already-fast, already-compiled) overflow measurement.
  timeout: 120_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3091",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium-local",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // No webServer entry: the API (127.0.0.1:8091) and web (127.0.0.1:3091)
  // processes for this reproduction are started manually, isolated from the
  // deployed services on ports 8000/3000.
});
