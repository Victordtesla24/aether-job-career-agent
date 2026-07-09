import { test, expect } from "@playwright/test";

/**
 * Story Bank e2e: STAR stories render from the API or the empty state with
 * the extract trigger available.
 */
test.describe("Story Bank page", () => {
  test("renders story cards or the empty state", async ({ page }) => {
    await page.goto("/dashboard/stories");

    await expect(page.getByRole("heading", { name: "Story Bank", level: 1 })).toBeVisible();
    const card = page.getByTestId("story-card").first();
    const empty = page.getByTestId("stories-empty-state");
    await expect(card.or(empty).first()).toBeVisible({ timeout: 20_000 });
  });

  test("exposes the story extractor trigger", async ({ page }) => {
    await page.goto("/dashboard/stories");

    await expect(page.getByTestId("run-extractor-btn")).toBeVisible();
  });
});
