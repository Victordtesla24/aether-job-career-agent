import { test, expect } from "@playwright/test";

/**
 * Analytics e2e: the funnel renders live numbers from /analytics/funnel
 * (seeded canonical funnel) and the period selector switches periods.
 */
test.describe("Analytics page", () => {
  test("renders the funnel with live numbers from the API", async ({ page }) => {
    await page.goto("/dashboard/analytics");

    await expect(page.getByRole("heading", { name: "Analytics", level: 1 })).toBeVisible();
    const funnel = page.getByTestId("funnel-chart");
    await expect(funnel.getByText("Jobs Found")).toBeVisible({ timeout: 20_000 });
    // Canonical seeded top-of-funnel: 847 jobs found. The applied count
    // drifts upward as pipeline runs create draft applications, so assert
    // it matches the live API value instead of a hardcoded number.
    await expect(funnel.getByText("847")).toBeVisible();
    const res = await page.request.get("http://127.0.0.1:8000/analytics/funnel", {
      headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("aether_token") ?? "")}` },
    });
    const body = (await res.json()) as { applied: number };
    expect(body.applied).toBeGreaterThan(0);
    await expect(funnel.getByText(String(body.applied), { exact: true })).toBeVisible();
  });

  test("period selector switches the funnel period", async ({ page }) => {
    await page.goto("/dashboard/analytics");

    const selector = page.getByTestId("period-selector");
    await expect(selector).toBeVisible();
    const funnelHeading = page.getByTestId("funnel-chart").getByRole("heading");
    await expect(funnelHeading).toContainText(/all/i, { timeout: 20_000 });

    await selector.getByRole("button", { name: "30d" }).click();
    await expect(funnelHeading).toContainText(/30d/i, { timeout: 20_000 });
  });

  test("renders the ATS distribution and agent ROI sections", async ({ page }) => {
    await page.goto("/dashboard/analytics");

    await expect(page.getByTestId("ats-distribution")).toBeVisible();
    await expect(page.getByTestId("agent-roi")).toBeVisible();
  });
});
