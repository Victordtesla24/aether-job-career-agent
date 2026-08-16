import { test, expect } from "@playwright/test";

/**
 * Analytics e2e: the funnel renders live numbers from /analytics/funnel
 * (seeded canonical funnel) and the period selector switches periods.
 *
 * URL MAPPING (1:1, per Binding Constraint 1's selector-change carve-out;
 * orchestrator ruling 2026-08-14, precedent: e2e/agents.spec.ts f4b6ddc):
 * The page now presents three linkable views via ?tab=; ATS distribution and
 * agent ROI both live on the "Quality & ROI" view. Assertions unchanged.
 *
 *   /dashboard/analytics              →  (default Overview view — funnel tests, unchanged)
 *   /dashboard/analytics [ats+roi]    →  /dashboard/analytics?tab=quality
 */
test.describe("Analytics page", () => {
  test("renders the funnel with live numbers from the API", async ({ page }) => {
    await page.goto("/dashboard/analytics");

    await expect(page.getByRole("heading", { name: "Analytics", level: 1 })).toBeVisible();
    const funnel = page.getByTestId("funnel-chart");
    // MP-030: the product INTENTIONALLY renders the "Jobs found" label three
    // times inside funnel-chart (visible bar label, the C-3 honesty footnote,
    // and ChartFrame's sr-only data-table rowheader), so an unqualified
    // getByText is a strict-mode violation. The assertion's intent is simply
    // "the top-of-funnel label rendered" — pin the first occurrence.
    await expect(funnel.getByText("Jobs Found").first()).toBeVisible({ timeout: 20_000 });
    // Jobs are discovered live from real sources, so both the top-of-funnel
    // and applied counts drift; assert they match the live API values
    // instead of hardcoded numbers.
    const res = await page.request.get("http://127.0.0.1:8000/analytics/funnel", {
      headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("aether_token") ?? "")}` },
    });
    const body = (await res.json()) as { jobs_found: number; applied: number };
    // MP-030 (part 2): the funnel renders counts through the chart kit's
    // locale-stable formatter (`formatNumber` — Intl.NumberFormat("en-AU"),
    // src/components/charts/geometry.ts), so once a count crosses 999 the
    // visible text is "8,836", never "8836". Assert the product's own
    // formatting of the live API value — same exact-live-number intent.
    const enAu = new Intl.NumberFormat("en-AU");
    await expect(
      funnel.getByText(enAu.format(body.jobs_found), { exact: true }).first(),
    ).toBeVisible();
    await expect(
      funnel.getByText(enAu.format(body.applied), { exact: true }).first(),
    ).toBeVisible();
  });

  test("period selector switches the funnel period", async ({ page }) => {
    await page.goto("/dashboard/analytics");

    const selector = page.getByTestId("period-selector");
    await expect(selector).toBeVisible();
    // Scoped to level 2: the section's own period-scoped heading ("Application
    // funnel (…)"). `<ChartFrame>` (used by `<FunnelChart>` inside this same
    // section) always renders its own complementary h3 `chart-title`
    // ("Volume by stage" — see the comment above the h2 in
    // dashboard/analytics/page.tsx), so an unqualified `getByRole("heading")`
    // is a strict-mode violation: 2 headings live inside `funnel-chart`.
    const funnelHeading = page.getByTestId("funnel-chart").getByRole("heading", { level: 2 });
    await expect(funnelHeading).toContainText(/all/i, { timeout: 20_000 });

    await selector.getByRole("button", { name: "30d" }).click();
    await expect(funnelHeading).toContainText(/30d/i, { timeout: 20_000 });
  });

  test("renders the ATS distribution and agent ROI sections", async ({ page }) => {
    await page.goto("/dashboard/analytics?tab=quality");

    await expect(page.getByTestId("ats-distribution")).toBeVisible();
    await expect(page.getByTestId("agent-roi")).toBeVisible();
  });
});
