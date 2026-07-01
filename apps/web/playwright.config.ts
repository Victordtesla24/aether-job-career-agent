import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright smoke-test config for the dashboard shell (P1-S06).
 *
 * The web server is built and started in production mode so the run is
 * deterministic and offline-safe (fonts/icons load via <link>, so no build-time
 * network is required). CI can reuse an already-running server via
 * `PLAYWRIGHT_REUSE_SERVER=1`.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "pnpm run build && pnpm exec next start -p 3000",
    url: "http://127.0.0.1:3000/dashboard",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
