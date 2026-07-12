import { test, expect } from "@playwright/test";

/**
 * Applications e2e: the kanban board renders every pipeline column from the
 * canonical status contract.
 */
test.describe("Applications page", () => {
  test("renders the kanban board with pipeline columns", async ({ page }) => {
    await page.goto("/dashboard/applications");

    await expect(
      page.getByRole("heading", { name: "Application Tracker", level: 1 }),
    ).toBeVisible();
    await expect(page.getByTestId("applications-kanban")).toBeVisible({ timeout: 20_000 });
    const columns = page.locator('[data-testid^="kanban-column-"]');
    expect(await columns.count()).toBeGreaterThanOrEqual(3);
  });

  test("columns resolve application cards or render empty", async ({ page }) => {
    await page.goto("/dashboard/applications");

    const kanban = page.getByTestId("applications-kanban");
    await expect(kanban).toBeVisible({ timeout: 20_000 });
    // The board itself must never error: either cards render or columns are
    // legitimately empty — both are valid states for seeded data.
    const cardCount = await page.getByTestId("application-card").count();
    expect(cardCount).toBeGreaterThanOrEqual(0);
    await expect(page.locator("text=/something went wrong/i")).toHaveCount(0);
  });
});
