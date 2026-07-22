import { defineConfig, devices } from "@playwright/test";

/**
 * Standalone Playwright config for the ML-agents-refix live-repro specs
 * (ML-agents-002 save+reload model persistence, ML-agents-005 mobile 390px
 * overflow in the per-agent model picker).
 *
 * Mirrors the ML-admin-002 local-repro pattern (see
 * uat/reports/evidence/models-live/ML-admin-002__local-repro-setup-notes.md):
 * the repo's main ./playwright.config.ts pins `baseURL:
 * "http://127.0.0.1:3000"` (the DEPLOYED production port) with a shared
 * authenticated storageState. Reusing it here would run against the live
 * deployment and mutate real AgentConfig rows for whatever account the
 * shared session belongs to — this finding needs its own throwaway user and
 * must never touch production. Points instead at a locally-managed API+web
 * pair on dedicated ports (8012/3012 — distinct from both the deployed
 * 8000/3000 AND the ML-admin-002 pair's 8010/3010) whose API's DATABASE_URL
 * is the shared `aether_test` schema, individually exported (never a
 * blanket `source .env`) — see ml-agents-refix-start-api.sh /
 * ml-agents-refix-start-web.sh in the scratchpad for how those were started.
 *
 * Run: apps/web$ ./node_modules/.bin/playwright test \
 *        --config=e2e/ml-agents-refix.playwright.config.ts
 * (override E2E_BASE_URL to point at a different already-running instance.)
 */
export default defineConfig({
  testDir: ".",
  testMatch: "ml-agents-refix.spec.ts",
  fullyParallel: false,
  reporter: "list",
  timeout: 60_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3012",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium-local",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // No webServer entry: the API (127.0.0.1:8012) and web (127.0.0.1:3012)
  // processes for this reproduction are started manually, isolated from the
  // deployed services on ports 8000/3000.
});
