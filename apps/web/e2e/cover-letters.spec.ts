import { test, expect } from "@playwright/test";

/**
 * Cover Letters e2e: list + generation controls render, wired to the API.
 */
test.describe("Cover Letters page", () => {
  test("renders the list or empty state from the API", async ({ page }) => {
    await page.goto("/dashboard/cover-letters");

    await expect(
      page.getByRole("heading", { name: "Cover Letter Studio", level: 1 }),
    ).toBeVisible();
    const card = page.getByTestId("cover-letter-card").first();
    const empty = page.getByTestId("cover-letters-empty-state");
    await expect(card.or(empty).first()).toBeVisible({ timeout: 20_000 });
  });

  test("exposes the job selector and generate button", async ({ page }) => {
    await page.goto("/dashboard/cover-letters");

    const select = page.getByTestId("cover-letter-job-select");
    await expect(select).toBeVisible();
    await expect(page.getByTestId("run-cover-letter-btn")).toBeVisible();
    // The selector is populated from the seeded jobs list.
    await expect
      .poll(async () => await select.locator("option").count(), { timeout: 20_000 })
      .toBeGreaterThan(1);
  });
});
