// @vitest-environment jsdom
/**
 * GOLD-MASTER V4 §6 / G-C regression guard.
 *
 * `interview_conversion_rate` (and its companion `interview_conversion_healthy`
 * flag) are real, correct fields the backend already returns from
 * GET /analytics/conversion (interviews booked over applications SUBMITTED,
 * §5.3.5). But the frontend's `ConversionSchema` (apps/web/src/lib/api/
 * analytics.ts) is a `z.object` that never declared either field, so
 * `.parse()` silently strips both before the Analytics page ever sees them —
 * the metric is computed correctly end-to-end and then thrown away on the
 * client. This test renders the real AnalyticsPage against a mocked API
 * response that DOES include both fields and asserts they actually reach
 * the screen, honestly, in three scenarios:
 *
 *   1. Zero applications yet → an honest 0%, with NO "needs improvement"
 *      framing (misleading on a brand-new account with nothing to convert).
 *   2. Applications exist and the rate clears the >=1:5 (20%) floor → a
 *      positive/healthy framing, sourced from the API's own
 *      `interview_conversion_healthy` flag (never recomputed client-side).
 *   3. Applications exist and the rate misses the floor → an honest
 *      "needs improvement" framing (this is NOT the misleading case above,
 *      because there is real denominator data behind it).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import AnalyticsPage from "../page";

const ATS_FIXTURE = {
  buckets: Array.from({ length: 10 }, (_, i) => ({ range: `${i * 10}-${i * 10 + 10}`, count: 0 })),
  total: 0,
};

const ROI_FIXTURE = { total_cost_usd: 1.23, total_runs: 4, avg_duration_ms: 500 };

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

function mockApiWith(funnel: Record<string, unknown>, conversion: Record<string, unknown>) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path.startsWith("/analytics/funnel")) return funnel;
    if (path === "/analytics/ats-distribution") return ATS_FIXTURE;
    if (path === "/analytics/agent-roi") return ROI_FIXTURE;
    if (path.startsWith("/analytics/conversion")) return conversion;
    if (path.startsWith("/analytics/dashboard")) return DASHBOARD_FIXTURE;
    if (path === "/analytics/market-pulse") return MARKET_PULSE_FIXTURE;
    throw new Error(`unexpected apiRequest(${path})`);
  });
}

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
});

describe("interview_conversion_rate reaches the Analytics screen (GOLD-MASTER V4 §6 / G-C)", () => {
  it("renders a truthful 0% with a neutral (non-alarming) framing when there are zero applications yet", async () => {
    mockApiWith(
      { period: "all", jobs_found: 3, applied: 0, screened: 0, interviewed: 0, offers: 0 },
      {
        period: "all",
        found_to_applied: 0,
        applied_to_screened: 0,
        screened_to_interview: 0,
        interview_to_offer: 0,
        interview_conversion_rate: 0,
        interview_conversion_healthy: false,
      },
    );

    render(<AnalyticsPage />);

    const tile = await screen.findByTestId("interview-conversion-rate");
    expect(tile.textContent).toMatch(/0%/);
    // Zero applications is not evidence of underperformance — must not carry
    // the same "needs improvement" alarm as a real below-floor rate.
    expect(tile.textContent?.toLowerCase()).not.toMatch(/needs improvement/);
  });

  it("renders the API-derived healthy framing (>=1:5) without recomputing the rate client-side", async () => {
    mockApiWith(
      { period: "all", jobs_found: 20, applied: 10, screened: 8, interviewed: 3, offers: 1 },
      {
        period: "all",
        found_to_applied: 50,
        applied_to_screened: 80,
        screened_to_interview: 37.5,
        interview_to_offer: 33.33,
        interview_conversion_rate: 30,
        interview_conversion_healthy: true,
      },
    );

    render(<AnalyticsPage />);

    const tile = await screen.findByTestId("interview-conversion-rate");
    expect(tile.textContent).toMatch(/30%/);
    expect(tile.textContent?.toLowerCase()).toMatch(/on track/);
  });

  it("renders an honest needs-improvement framing when applications exist but the rate misses the floor", async () => {
    mockApiWith(
      { period: "all", jobs_found: 20, applied: 10, screened: 6, interviewed: 1, offers: 0 },
      {
        period: "all",
        found_to_applied: 50,
        applied_to_screened: 60,
        screened_to_interview: 16.67,
        interview_to_offer: 0,
        interview_conversion_rate: 10,
        interview_conversion_healthy: false,
      },
    );

    render(<AnalyticsPage />);

    const tile = await screen.findByTestId("interview-conversion-rate");
    expect(tile.textContent).toMatch(/10%/);
    expect(tile.textContent?.toLowerCase()).toMatch(/needs improvement/);
  });
});
