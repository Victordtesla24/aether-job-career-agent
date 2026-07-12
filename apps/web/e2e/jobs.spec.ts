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

  test("detail-panel save button toggles the selected job's saved state", async ({ page }) => {
    await page.goto("/dashboard/jobs");

    // Selecting the first card opens the detail panel with its save toggle.
    await page.getByTestId("job-card").first().click();
    const save = page.getByTestId("detail-save");
    await expect(save).toBeVisible({ timeout: 20_000 });
    const before = (await save.getAttribute("aria-pressed")) ?? "false";
    const after = before === "true" ? "false" : "true";

    await save.click();
    await expect(save).toHaveAttribute("aria-pressed", after, { timeout: 15_000 });

    // Toggle back so the test is idempotent against live data.
    await save.click();
    await expect(save).toHaveAttribute("aria-pressed", before, { timeout: 15_000 });
  });
});
