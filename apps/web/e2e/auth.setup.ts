import { test as setup, expect } from "@playwright/test";
import path from "node:path";

import { requireEnv } from "./env";

/**
 * Playwright auth setup (GAP-P4-051 / C-15).
 *
 * The old auth.setup.ts assumed /login prefilled the demo credentials and
 * just clicked "Sign in" — but apps/web/src/app/login/page.tsx has always
 * initialized both fields to "" (the lib/api/client.ts DEMO_CREDENTIALS
 * export it relied on was never consumed by the page, and was removed
 * entirely by GAP-P4-068 for hardcoding the demo password), so that click
 * submitted an empty form and the wait for /dashboard timed out (see
 * uat/reports/evidence/phase4/preflight__tests__20260713T114254Z.log).
 *
 * This performs a REAL login: navigate to /login, fill the form with
 * LOGIN_EMAIL/LOGIN_PASSWORD (repo .env or process env — never hardcoded
 * here), submit, wait for the redirect to /dashboard, and persist the
 * resulting session so the rest of the chromium project runs authenticated.
 */
// apps/web has "type": "module" (no __dirname); Playwright always runs from
// apps/web, so resolve relative to process.cwd() instead.
const AUTH_FILE = path.join(process.cwd(), "e2e", ".auth", "user.json");

setup("authenticate", async ({ page }) => {
  const email = requireEnv("LOGIN_EMAIL");
  const password = requireEnv("LOGIN_PASSWORD");

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();

  await page.waitForURL("**/dashboard", { timeout: 20_000 });

  const token = await page.evaluate(() => window.localStorage.getItem("aether_token"));
  expect(token, "JWT stored under the shared aether_token key after a real login").toBeTruthy();

  await page.context().storageState({ path: AUTH_FILE });
});
