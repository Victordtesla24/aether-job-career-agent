// @vitest-environment jsdom
/**
 * MV-analytics-004 regression guard.
 *
 * The 7d/30d/90d/All period selector only re-fetched the Application Funnel
 * and Stage Conversion panels; the Dashboard-summary metric cards never
 * received a period parameter at all (the backend has always accepted one),
 * and ATS Score Distribution / Agent ROI have no period support server-side
 * yet carried no visual cue that they are exempt from the selector above
 * them. This test renders the real AnalyticsPage, drives the period
 * selector, and asserts:
 *   1. GET /analytics/dashboard is now called WITH the selected period.
 *   2. The ATS distribution and Agent ROI panels honestly label themselves
 *      as "all time" / unaffected by the selector, instead of silently
 *      implying they respect it.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import AnalyticsPage from "../page";

const FUNNEL_FIXTURE = {
  period: "all",
  jobs_found: 10,
  applied: 5,
  screened: 3,
  interviewed: 2,
  offers: 1,
};

const ATS_FIXTURE = {
  buckets: Array.from({ length: 10 }, (_, i) => ({ range: `${i * 10}-${i * 10 + 10}`, count: 0 })),
  total: 0,
};

const ROI_FIXTURE = { total_cost_usd: 1.23, total_runs: 4, avg_duration_ms: 500 };

const CONVERSION_FIXTURE = {
  period: "all",
  found_to_applied: 50,
  applied_to_screened: 60,
  screened_to_interview: 66.67,
  interview_to_offer: 50,
};

const DASHBOARD_FIXTURE = {
  totalApplications: 7,
  interviews: 2,
  offers: 1,
  jobsFound: 10,
  avgFitScore: 72,
  agentRuns: 4,
  agentCostUsd: 1.23,
};

const MARKET_PULSE_FIXTURE = {
  sources: [],
  sourcesTotal: 0,
  sourcesLabel: "jobs sourced",
  topSkills: [],
  activityHeatmap: [[0, 0, 0, 0, 0, 0, 0]],
  probability: { score: 0, label: "—", note: "", factors: [] },
  employerActivity: [],
  recruiterTrends: { series: [], rows: [] },
  marketVsYou: { marketDataConnected: false, comparisons: [], summary: "" },
  trendIndicators: [],
};

apiRequest.mockImplementation(async (path: string) => {
  if (path.startsWith("/analytics/funnel")) return FUNNEL_FIXTURE;
  if (path === "/analytics/ats-distribution") return ATS_FIXTURE;
  if (path === "/analytics/agent-roi") return ROI_FIXTURE;
  if (path.startsWith("/analytics/conversion")) return CONVERSION_FIXTURE;
  if (path.startsWith("/analytics/dashboard")) return DASHBOARD_FIXTURE;
  if (path === "/analytics/market-pulse") return MARKET_PULSE_FIXTURE;
  throw new Error(`unexpected apiRequest(${path})`);
});

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
});

describe("Analytics period selector (MV-analytics-004)", () => {
  it("forwards the selected period to GET /analytics/dashboard", async () => {
    render(<AnalyticsPage />);

    await screen.findByTestId("dashboard-summary");
    expect(apiRequest).toHaveBeenCalledWith(
      "/analytics/dashboard?period=all",
      expect.anything(),
    );

    apiRequest.mockClear();
    fireEvent.click(screen.getByText("7d"));

    await screen.findByText(/application funnel \(7d\)/i);
    expect(apiRequest).toHaveBeenCalledWith(
      "/analytics/dashboard?period=7d",
      expect.anything(),
    );
  });

  it("ATS distribution and Agent ROI panels honestly label themselves as all-time, unaffected by the period selector", async () => {
    render(<AnalyticsPage />);

    const ats = await screen.findByTestId("ats-distribution");
    expect(ats.textContent?.toLowerCase()).toMatch(/all time/);

    const roi = screen.getByTestId("agent-roi");
    expect(roi.textContent?.toLowerCase()).toMatch(/all time/);
  });

  it("dashboard-summary now respects the period selector, so its 'Applications' tooltip no longer claims all-time and the section shows a period indicator like its siblings (review rework, MV-analytics-004/005)", async () => {
    render(<AnalyticsPage />);

    const summary = await screen.findByTestId("dashboard-summary");
    // Matches the sibling "Application funnel ({period})" / "Stage
    // conversion ({period})" headers instead of leaving this the only
    // section with no period indicator.
    expect(within(summary).getByText(/dashboard summary \(all\)/i)).toBeTruthy();

    // The "Applications" stat card's tooltip must not claim "all time
    // periods" now that the value genuinely changes with the selector.
    const appsLabel = within(summary).getByText("Applications");
    const card = appsLabel.closest("div");
    expect(card).not.toBeNull();
    const tooltip = card!.querySelector('[data-testid="metric-tooltip-popover"]');
    expect(tooltip?.textContent?.toLowerCase()).not.toMatch(
      /all time|all sources and time periods/,
    );
    expect(tooltip?.textContent?.toLowerCase()).toMatch(/selected period/);

    // The period indicator itself updates when the selector changes.
    fireEvent.click(screen.getByText("7d"));
    await within(summary).findByText(/dashboard summary \(7d\)/i);
  });
});
