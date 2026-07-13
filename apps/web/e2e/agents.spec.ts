import { test, expect } from "@playwright/test";

/**
 * Agents console e2e: the agent grid renders from GET /agents and the recent
 * runs section resolves from GET /agents/runs (table or empty state).
 */
test.describe("Agents page", () => {
  test("renders the agents grid from the API", async ({ page }) => {
    await page.goto("/dashboard/agents");

    await expect(page.getByRole("heading", { name: "Agents", level: 1 })).toBeVisible();
    // Configurable agent cards carry per-agent testids (agent-card-scout, …).
    const cards = page.locator('[data-testid^="agent-card-"]');
    await expect(cards.first()).toBeVisible({ timeout: 20_000 });
    // Canonical registry: supervisor, scout, matcher, fitScorer, tailor,
    // coverLetter, storyExtractor.
    expect(await cards.count()).toBeGreaterThanOrEqual(7);
    await expect(page.getByTestId("run-pipeline-btn")).toBeVisible();
  });

  test("recent runs log resolves (table or empty state)", async ({ page }) => {
    await page.goto("/dashboard/agents");

    await expect(page.getByRole("heading", { name: "Recent runs" })).toBeVisible();
    const table = page.getByTestId("agent-runs-table");
    const empty = page.getByText(/no agent runs recorded yet/i);
    await expect(table.or(empty).first()).toBeVisible({ timeout: 20_000 });
  });
});
