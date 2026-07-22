import { defineConfig, devices } from "@playwright/test";

/**
 * Standalone Playwright config for ML-admin-002 (mobile 390px overflow on
 * /admin/settings + /admin/users).
 *
 * The repo's main ./playwright.config.ts pins a "chromium" project whose
 * "setup" dependency always performs a REAL login against the shared
 * `baseURL: "http://127.0.0.1:3000"` (production port). Reusing it here
 * would perform a live login against the deployed app just to run this
 * one reproduction spec, which this finding does not need and the
 * test-authoring brief explicitly avoids touching. This config instead
 * points at a locally-managed API+web pair on dedicated ports (see the
 * ML-admin-002 test-authoring notes for how those were started) — override
 * with E2E_BASE_URL if pointing at a different already-running instance.
 * The target spec logs in for itself (no shared storageState).
 *
 * Run: apps/web$ ./node_modules/.bin/playwright test \
 *        --config=e2e/ml-admin-002.playwright.config.ts
 */
export default defineConfig({
  testDir: ".",
  testMatch: "ml-admin-002-mobile-overflow.spec.ts",
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3010",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium-local",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // No webServer entry: the API (127.0.0.1:8010) and web (127.0.0.1:3010)
  // processes for this reproduction are started manually, isolated from the
  // production services on ports 8000/3000.
});
