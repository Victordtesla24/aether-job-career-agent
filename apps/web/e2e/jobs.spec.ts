import { test, expect } from "@playwright/test";

/**
 * Jobs page e2e (post-review hardening): the page must render real job cards
 * fetched from the API (seeded demo data), expose the discovery trigger and
 * support toggling the save state of a job.
 */
test.describe("Jobs page", () => {
  test("renders job cards from the API", async ({ page }) => {
    await page.goto("/dashboard/jobs");

    await expect(page.getByRole("heading", { name: "Job Discovery", level: 1 })).toBeVisible();
    const cards = page.getByTestId("job-card");
    await expect(cards.first()).toBeVisible({ timeout: 20_000 });
    expect(await cards.count()).toBeGreaterThan(0);
  });

  test("exposes the run-discovery button and filter bar", async ({ page }) => {
    await page.goto("/dashboard/jobs");

    await expect(page.getByTestId("run-discovery-btn")).toBeVisible();
    await expect(page.getByTestId("job-filter-bar")).toBeVisible();
  });

  test("save button toggles a job's saved state", async ({ page }) => {
    await page.goto("/dashboard/jobs");

    const firstSave = page.getByTestId("save-job-btn").first();
    await expect(firstSave).toBeVisible({ timeout: 20_000 });
    const before = (await firstSave.getAttribute("aria-pressed")) ?? "false";
    const after = before === "true" ? "false" : "true";

    await firstSave.click();
    await expect(firstSave).toHaveAttribute("aria-pressed", after, { timeout: 15_000 });

    // Toggle back so the test is idempotent against the seeded data.
    await firstSave.click();
    await expect(firstSave).toHaveAttribute("aria-pressed", before, { timeout: 15_000 });
  });
});
