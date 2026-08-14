// @vitest-environment jsdom
/**
 * MON-018 / U-UI (responsive) — ANALYTICS-STAT-TILE-OVERFLOW.
 *
 * Live audit at a 390x844 mobile viewport found the "Agent ROI" stat row
 * (dl.mt-4.grid > div.rounded-xl.border > dd.mono.flex — Total spend / Agent
 * runs / Avg duration) measurably too narrow for its own values:
 * "$8.16" needs 90px in a 61px box (+48%), "8632" needs 83px in 61px
 * (+36%), "166.0s" needs 97px in 61px (+59%); the row itself (dl.mt-4.grid)
 * is 336px wide inside a 316px container (+20px over the viewport-safe
 * width). Root cause: `<dl className="mt-4 grid grid-cols-3 gap-4">` in
 * app/dashboard/analytics/page.tsx locks in 3 columns at EVERY breakpoint —
 * no narrower mobile layout at all — so three tiles are forced to share a
 * 390px-wide column at any width. Recurs identically in base/nav-open/
 * bell-open states (findings-fresh.json OF-23..30/38..45/53..60), confirming
 * it's a persistent layout defect, not state-dependent.
 *
 * jsdom does not compute real layout/scrollWidth, so this pins the
 * structural contract instead (same convention as
 * src/components/__tests__/topbar.test.tsx MV-mobile-dashboard-001): the
 * grid must not be a bare, breakpoint-less `grid-cols-3` — it needs a
 * narrower mobile-first default that only reaches 3 columns at a wider
 * breakpoint, mirroring the pattern already used one section up in this
 * same file for the funnel/summary grids.
 */
import { cleanup, render, screen } from "@testing-library/react";
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

const ROI_FIXTURE = { total_cost_usd: 8.16, total_runs: 8632, avg_duration_ms: 166000 };

const CONVERSION_FIXTURE = {
  period: "all",
  found_to_applied: 50,
  applied_to_screened: 60,
  screened_to_interview: 66.67,
  interview_to_offer: 50,
  interview_conversion_rate: 40,
  interview_conversion_healthy: true,
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
  probability: {
    score: null,
    measured: false,
    label: "Job Search Progress",
    note: "",
    methodology: "",
    unmeasuredReason: "Not measured — no signal has data yet.",
    marketDataConnected: false,
    factors: [],
  },
  employerActivity: [],
  recruiterTrends: { series: [], rows: [] },
  marketVsYou: { comparisons: [], summary: "" },
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

/*
 * SELECTOR MAPPING (ANALYTICS-VIZ round 3, F3) — 1:1, the contract kept.
 *
 * The judge's must-fix deleted the stat row this defect lived in: "Total
 * spend" and "Agent runs" duplicated the executive summary band's spend tile,
 * and the cost-per ratios were re-expressed as a `<BulletChart>`. So the
 * anchor this file used — `getByText("$8.16")`, the Total spend tile's value —
 * no longer exists, and the assertions re-point to the structure that replaced
 * it, one for one:
 *
 *   `$8.16` → its `dd` → its `dl`   →  the ROI panel itself, which must now
 *                                      contain NO `dl` numeral grid at all
 *   no unprefixed `grid-cols-3`     →  no descendant carries `grid-cols-3` at
 *                                      any breakpoint: three fixed columns can
 *                                      no longer be reached, rather than being
 *                                      deferred to `sm`
 *   a responsive `sm:grid-cols-3`   →  the replacement's value rows WRAP, so a
 *                                      390px viewport reflows them instead of
 *                                      dividing itself into 61px boxes
 *
 * The defect this file was written for (a value measurably wider than its box)
 * is therefore closed structurally, and a regression to a fixed numeral grid in
 * this panel still fails here.
 */
describe("Agent ROI panel layout (ANALYTICS-STAT-TILE-OVERFLOW)", () => {
  it("cannot lock into a fixed 3-column numeral grid at any viewport", async () => {
    render(<AnalyticsPage />);
    const roi = await screen.findByTestId("agent-roi");

    expect(roi.querySelector("dl")).toBeNull();
    expect(roi.querySelector('[class*="grid-cols-3"]')).toBeNull();

    const rows = Array.from(roi.querySelectorAll('[data-testid^="roi-cost-per-"]'));
    expect(rows).toHaveLength(2);
    rows.forEach((row) => {
      expect(row.className.split(/\s+/)).toContain("flex-wrap");
    });
  });
});
