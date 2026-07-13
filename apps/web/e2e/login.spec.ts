import { test, expect } from "@playwright/test";

import { requireEnv } from "./env";

/**
 * /login e2e (GAP-P4-051 / C-15): exercises the REAL login page. There is no
 * demo-account prefill in apps/web/src/app/login/page.tsx (both fields
 * initialize to ""), so this suite fills the form itself rather than
 * asserting a prefill that doesn't exist. Runs with a clean (unauthenticated)
 * storageState regardless of the chromium project's saved session, since
 * these specs exercise the sign-in flow itself.
 */
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("Login page", () => {
  test("renders the sign-in form with empty fields", async ({ page }) => {
    const response = await page.goto("/login");
    expect(response?.status()).toBe(200);

    await expect(page.getByRole("heading", { name: "Sign in", level: 1 })).toBeVisible();
    await expect(page.getByLabel("Email")).toHaveValue("");
    await expect(page.getByLabel("Password")).toHaveValue("");
  });

  test("filling the form and submitting signs in and redirects to the dashboard", async ({
    page,
  }) => {
    const email = requireEnv("LOGIN_EMAIL");
    const password = requireEnv("LOGIN_PASSWORD");

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: /sign in/i }).click();

    await page.waitForURL("**/dashboard", { timeout: 20_000 });
    const token = await page.evaluate(() => window.localStorage.getItem("aether_token"));
    expect(token, "JWT stored under the shared aether_token key").toBeTruthy();
  });

  test("shows an error for wrong credentials", async ({ page }) => {
    const email = requireEnv("LOGIN_EMAIL");

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("definitely-wrong-1");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page.getByTestId("login-error")).toContainText(/invalid email or password/i);
    await expect(page).toHaveURL(/\/login$/);
  });
});
