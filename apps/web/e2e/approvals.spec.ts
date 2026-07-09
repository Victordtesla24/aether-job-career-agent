import { test, expect } from "@playwright/test";

/**
 * Approvals e2e: the human-in-the-loop queue renders pending requests from
 * the API or the documented empty state — never a broken page.
 */
test.describe("Approvals page", () => {
  test("renders the approval queue or its empty state", async ({ page }) => {
    await page.goto("/dashboard/approvals");

    await expect(page.getByRole("heading", { name: "Approvals", level: 1 })).toBeVisible();
    const card = page.getByTestId("approval-card").first();
    const empty = page.getByTestId("approvals-empty-state");
    await expect(card.or(empty).first()).toBeVisible({ timeout: 20_000 });
  });

  test("pending approvals expose approve/reject actions", async ({ page }) => {
    await page.goto("/dashboard/approvals");

    const card = page.getByTestId("approval-card").first();
    const empty = page.getByTestId("approvals-empty-state");
    await expect(card.or(empty).first()).toBeVisible({ timeout: 20_000 });

    if (await card.isVisible()) {
      await expect(card.getByTestId("approve-btn")).toBeVisible();
      await expect(card.getByTestId("reject-btn")).toBeVisible();
    }
  });
});
