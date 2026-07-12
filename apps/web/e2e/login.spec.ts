import { test, expect } from "@playwright/test";

/**
 * /login e2e: the page renders (no more 404), is prefilled with the demo
 * account, and a successful sign-in stores the JWT and lands on /dashboard.
 */
test.describe("Login page", () => {
  test("renders the sign-in form prefilled with the demo account", async ({ page }) => {
    const response = await page.goto("/login");
    expect(response?.status()).toBe(200);

    await expect(page.getByRole("heading", { name: "Sign in", level: 1 })).toBeVisible();
    await expect(page.getByLabel("Email")).toHaveValue("demo@aether.dev");
    await expect(page.getByLabel("Password")).toHaveValue("AetherDemo1");
    await expect(page.getByText(/demo environment/i)).toBeVisible();
  });

  test("signs in with demo credentials and redirects to the dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: /sign in/i }).click();

    await page.waitForURL("**/dashboard", { timeout: 20_000 });
    const token = await page.evaluate(() => window.localStorage.getItem("aether_token"));
    expect(token, "JWT stored under the shared aether_token key").toBeTruthy();
  });

  test("shows an error for wrong credentials", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Password").fill("definitely-wrong-1");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page.getByTestId("login-error")).toContainText(/invalid email or password/i);
    await expect(page).toHaveURL(/\/login$/);
  });
});
