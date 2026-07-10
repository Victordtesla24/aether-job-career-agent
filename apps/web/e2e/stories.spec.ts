import { test, expect } from "@playwright/test";

/**
 * Story Bank e2e: the wireframe-faithful screen renders its header, live stat
 * strip, category filters and insights rail, plus either story cards or the
 * empty state with the import/extract triggers.
 */
test.describe("Story Bank page", () => {
  test("renders the header, stats and insights", async ({ page }) => {
    await page.goto("/dashboard/stories");

    await expect(
      page.getByRole("heading", { name: "Achievement & Narrative Library", level: 1 }),
    ).toBeVisible();
    await expect(page.getByTestId("story-stats")).toBeVisible();
    await expect(page.getByTestId("story-insights")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Interview Question Mapper" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Coverage Gaps" })).toBeVisible();
  });

  test("renders story cards or the empty state", async ({ page }) => {
    await page.goto("/dashboard/stories");

    const card = page.getByTestId("story-card").first();
    const empty = page.getByTestId("stories-empty-state");
    await expect(card.or(empty).first()).toBeVisible({ timeout: 20_000 });
  });

  test("exposes the story extractor and new-story triggers", async ({ page }) => {
    await page.goto("/dashboard/stories");

    await expect(page.getByTestId("run-extractor-btn")).toBeVisible();
    await expect(page.getByTestId("add-story-btn")).toBeVisible();
  });

  test("opens the manual creation form", async ({ page }) => {
    await page.goto("/dashboard/stories");

    await page.getByTestId("add-story-btn").click();
    await expect(page.getByTestId("create-story-panel")).toBeVisible();
    await expect(page.getByTestId("story-form-title")).toBeVisible();
  });
});
