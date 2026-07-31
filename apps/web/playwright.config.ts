import { fileURLToPath } from "node:url";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Dedicated e2e port — deliberately NOT 3000 (the production
// aether-web.service port). ROOT CAUSE of BUILD-RISK-001 (see
// docs/delivery/DEPLOYMENT-RUNBOOK.md §0.4/§0.5): the previous config both
// rebuilt directly into the live `apps/web/.next` AND started on :3000, so
// `reuseExistingServer: !CI` could silently attach Playwright to the running
// PRODUCTION server. A dedicated port makes that structurally impossible —
// nothing this config does can ever collide with what's on :3000.
const E2E_PORT = process.env.AETHER_E2E_PORT ?? "3100";

// scripts/run-e2e-server.sh deliberately does NOT run `pnpm build`. It only
// verifies (via scripts/verify-web-build.sh — reused, not duplicated) that a
// valid, unpoisoned build already exists in apps/web/.next, then runs
// `next start -p <E2E_PORT>` READ-ONLY against it. `next start` never writes
// to `.next/`, so an e2e run can no longer overwrite the build
// `aether-web.service` serves. Callers (local or CI) must run
// `pnpm --dir apps/web build` themselves first — see docs/delivery/
// DEPLOYMENT-RUNBOOK.md "Running the e2e suite".
const E2E_SERVER_SCRIPT = path.resolve(__dirname, "../../scripts/run-e2e-server.sh");

/**
 * Playwright smoke-test config for the dashboard shell (P1-S06).
 *
 * The web server under test is an ALREADY-BUILT production server started
 * via `next start` (read-only against `apps/web/.next`) so the run is
 * deterministic and offline-safe (fonts/icons load via <link>, so no
 * build-time network is required) and can never clobber the live build.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${E2E_PORT}`,
    trace: "on-first-retry",
  },
  projects: [
    {
      // Real login via /login (GAP-P4-051 / C-15): fills the form with
      // LOGIN_EMAIL/LOGIN_PASSWORD and saves the resulting session so the
      // chromium project below doesn't have to log in per-spec.
      name: "setup",
      testMatch: /.*\.setup\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/user.json" },
      dependencies: ["setup"],
    },
  ],
  webServer: {
    command: E2E_SERVER_SCRIPT,
    url: `http://127.0.0.1:${E2E_PORT}/dashboard`,
    reuseExistingServer: !process.env.CI,
    // No build happens here anymore (see E2E_SERVER_SCRIPT above) — the
    // timeout only has to cover `next start` boot time, not a full build.
    timeout: 30_000,
  },
});
