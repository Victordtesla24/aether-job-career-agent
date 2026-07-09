import { test, expect } from "@playwright/test";

/**
 * Resume Studio e2e: version list panel and the tailor controls render, and
 * the version list resolves from the API (cards or the documented empty state).
 */
test.describe("Resume studio", () => {
  test("renders the versions panel and tailor controls", async ({ page }) => {
    await page.goto("/dashboard/resume");

    await expect(page.getByRole("heading", { name: "Resume", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Versions" })).toBeVisible();
    await expect(page.getByTestId("tailor-job-select")).toBeVisible();
    await expect(page.getByTestId("run-tailor-btn")).toBeVisible();
  });

  test("version list resolves from the API (cards or empty state)", async ({ page }) => {
    await page.goto("/dashboard/resume");

    const versionCard = page.getByTestId("resume-version-card").first();
    const emptyState = page.getByText(/no resume versions yet/i);
    await expect(versionCard.or(emptyState).first()).toBeVisible({ timeout: 20_000 });
  });
});
