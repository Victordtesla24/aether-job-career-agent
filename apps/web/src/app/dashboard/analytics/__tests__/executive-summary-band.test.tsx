// @vitest-environment jsdom
/**
 * ANALYTICS-VIZ — the executive summary band, rendered by the real page.
 *
 * `lib/analytics/__tests__/executive-summary.test.ts` pins the arithmetic.
 * This file pins the four things only a mounted page can prove:
 *
 *   1. THE BAND IS ABOVE THE TABS. "One glance" is not a property of one view,
 *      so the band must sit outside every tabpanel and stay on screen on all
 *      three tabs — including when a deep link opens straight into Market.
 *   2. NO NEW WIRING. The band added no request. The page issues exactly the
 *      same eight calls it issued before this slice, and switching tabs still
 *      issues none.
 *   3. THE SPARK AND THE CAPTION AGREE. Each tile hands ONE string to its
 *      spark as `windowLabel` (C-3) and renders that same string visibly as
 *      the tile's basis — so a reader and the chart kit can never be looking
 *      at different claims.
 *   4. DEGRADED IS STATED, NOT HIDDEN. When an endpoint fails its tile keeps
 *      its slot, shows the kit's em dash, and says why.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import AnalyticsPage from "../page";

const FUNNEL_FIXTURE = {
  period: "all",
  jobs_found: 8358,
  applied: 287,
  screened: 12,
  interviewed: 2,
  offers: 0,
};
const CONVERSION_FIXTURE = {
  period: "all",
  found_to_applied: 3.4,
  applied_to_screened: 4.2,
  screened_to_interview: 16.7,
  interview_to_offer: 0,
  interview_conversion_rate: 0.7,
  interview_conversion_healthy: false,
};
const ATS_FIXTURE = {
  buckets: [
    { range: "0-9", count: 0 },
    { range: "70-79", count: 9 },
    { range: "80-89", count: 6 },
  ],
  total: 15,
};
const ROI_FIXTURE = { total_cost_usd: 8.16, total_runs: 8781, avg_duration_ms: 166000 };
const DASHBOARD_FIXTURE = {
  totalApplications: 460,
  interviews: 2,
  offers: 0,
  jobsFound: 8358,
  avgFitScore: 61,
  agentRuns: 8781,
  agentCostUsd: 8.16,
};
const POLICY_FIXTURE = {
  tier: "heightened",
  triggers: ["conversion_below_20pct_target"],
  behaviour: "Heightened rigor: résumé tailoring runs up to 7 scoring iterations.",
  knobs: { maxIterations: 7 },
  thresholds: { interviewConversionTarget: 0.2, dimensionFloor: 80, minSampleSize: 5 },
  metricSnapshot: {
    sampleSize: 287,
    conversionRate: 0.7,
    interviewCount: 2,
    dimensionScores: { cultureFit: 72.5 },
    dimensionSampleSize: 42,
    dimensionsEvaluated: 1,
    available: true,
    unavailableReason: null,
  },
  perAgent: [],
};
const HISTORY_FIXTURE = {
  available: true,
  reason: null,
  runsWithoutPolicy: 8781,
  thresholds: { interviewConversionTarget: 20, dimensionFloor: 80, minSampleSize: 5 },
  points: [
    {
      at: "2026-08-01T00:00:00Z",
      tier: "standard",
      runs: 2,
      conversionRate: 0,
      sampleSize: 2,
      interviewCount: 0,
      dimensionsBelowFloor: [],
      dimensionsEvaluated: 0,
      triggers: [],
    },
    {
      at: "2026-08-10T00:00:00Z",
      tier: "heightened",
      runs: 18,
      conversionRate: 0.7,
      sampleSize: 287,
      interviewCount: 2,
      dimensionsBelowFloor: ["cultureFit"],
      dimensionsEvaluated: 1,
      triggers: ["conversion_below_20pct_target"],
    },
  ],
};
const COHORTS_FIXTURE = {
  target: 20,
  minSampleSize: 5,
  cohorts: [],
  untagged: { submitted: 0, interviewed: 0, reason: null },
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

function mockApi(overrides: Record<string, unknown> = {}) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path in overrides) {
      const value = overrides[path];
      if (value instanceof Error) throw value;
      return value;
    }
    if (path.startsWith("/analytics/funnel")) return FUNNEL_FIXTURE;
    if (path === "/analytics/ats-distribution") return ATS_FIXTURE;
    if (path === "/analytics/agent-roi") return ROI_FIXTURE;
    if (path.startsWith("/analytics/conversion")) return CONVERSION_FIXTURE;
    if (path.startsWith("/analytics/dashboard")) return DASHBOARD_FIXTURE;
    if (path === "/analytics/market-pulse") return MARKET_PULSE_FIXTURE;
    if (path === "/analytics/agent-policy/history") return HISTORY_FIXTURE;
    if (path === "/analytics/agent-policy/cohorts") return COHORTS_FIXTURE;
    if (path === "/analytics/agent-policy") return POLICY_FIXTURE;
    throw new Error(`unexpected apiRequest(${path})`);
  });
}

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
});

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
});

const TILE_IDS = ["pipeline", "conversion", "quality", "spend", "rigor"] as const;

describe("the band is above the tabs, on every tab", () => {
  it("renders outside every tabpanel, so no view can hide it", async () => {
    mockApi();
    const { container } = render(<AnalyticsPage />);
    const band = await screen.findByTestId("executive-summary");
    expect(band.closest('[role="tabpanel"]')).toBeNull();
    // And it precedes the view switcher in the DOM.
    const tabs = container.querySelector('[data-testid="analytics-tabs"]');
    expect(tabs).not.toBeNull();
    expect(
      (band.compareDocumentPosition(tabs!) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
    ).toBe(true);
  });

  it("stays mounted with the same five tiles after switching to another view", async () => {
    mockApi();
    render(<AnalyticsPage />);
    const band = await screen.findByTestId("executive-summary");
    for (const id of TILE_IDS) expect(within(band).getByTestId(`exec-tile-${id}`)).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: /market/i }));
    await screen.findByTestId("analytics-panel-market");
    const after = screen.getByTestId("executive-summary");
    expect(after.closest("[hidden]")).toBeNull();
    for (const id of TILE_IDS) expect(within(after).getByTestId(`exec-tile-${id}`)).toBeTruthy();
  });
});

describe("no new wiring (S-UI binding constraint 1)", () => {
  it("issues exactly the endpoints the page issued before the band existed", async () => {
    mockApi();
    render(<AnalyticsPage />);
    await screen.findByTestId("executive-summary");
    await screen.findByTestId("policy-cohorts");

    const called = apiRequest.mock.calls.map((c) => String(c[0])).sort();
    expect(called).toEqual([
      "/analytics/agent-policy",
      "/analytics/agent-policy/cohorts",
      "/analytics/agent-policy/history",
      "/analytics/agent-roi",
      "/analytics/ats-distribution",
      "/analytics/conversion?period=all",
      "/analytics/dashboard?period=all",
      "/analytics/funnel?period=all",
      "/analytics/market-pulse",
    ]);
  });

  it("issues no request at all when the reader changes view", async () => {
    mockApi();
    render(<AnalyticsPage />);
    await screen.findByTestId("policy-cohorts");
    apiRequest.mockClear();

    fireEvent.click(screen.getByRole("tab", { name: /quality/i }));
    await screen.findByTestId("analytics-panel-quality");
    expect(apiRequest).not.toHaveBeenCalled();
  });
});

describe("every tile is measured, and says what it was measured on", () => {
  it("renders the real figures, not placeholders", async () => {
    mockApi();
    render(<AnalyticsPage />);
    await screen.findByTestId("executive-summary");

    expect(screen.getByTestId("exec-tile-pipeline-value").textContent).toBe("287");
    expect(screen.getByTestId("exec-tile-conversion-value").textContent).toBe("0.7%");
    // 6 of 15 scored jobs reach the 80+ band.
    expect(screen.getByTestId("exec-tile-quality-value").textContent).toBe("40%");
    expect(screen.getByTestId("exec-tile-spend-value").textContent).toBe("8.16USD");
    expect(screen.getByTestId("exec-tile-rigor-value").textContent).toBe("Heightened");
  });

  it("gives each tile one deterministic insight line and one visible basis", async () => {
    mockApi();
    render(<AnalyticsPage />);
    await screen.findByTestId("executive-summary");

    // 2 interviews carried 0 offers — a measured 0%, and steeper than the
    // 3.4% at Jobs found → Applied. The line names the stage the numbers
    // actually point at, not the one with the biggest absolute loss.
    expect(screen.getByTestId("exec-tile-pipeline-insight").textContent).toBe(
      "Steepest drop-off Interviewed → Offers: 0% carried through.",
    );
    expect(screen.getByTestId("exec-tile-conversion-insight").textContent).toBe(
      "Rigor escalated to heightened until this closes.",
    );
    expect(screen.getByTestId("exec-tile-quality-insight").textContent).toBe(
      "Most jobs land in the 70-79 band (9).",
    );
    for (const id of TILE_IDS) {
      expect(screen.getByTestId(`exec-tile-${id}-insight`).getAttribute("data-prose")).toBe(
        "insight",
      );
      expect(screen.getByTestId(`exec-tile-${id}-basis`).getAttribute("data-prose")).toBe(
        "caption",
      );
    }
  });

  it("hands the spark the SAME window string it prints under the tile (C-3)", async () => {
    mockApi();
    render(<AnalyticsPage />);
    await screen.findByTestId("executive-summary");

    for (const id of TILE_IDS) {
      const tile = screen.getByTestId(`exec-tile-${id}`);
      const basis = within(tile).getByTestId(`exec-tile-${id}-basis`).textContent;
      const spark = within(tile).getByTestId("spark");
      expect(spark.getAttribute("data-window")).toBe(basis);
      expect(spark.getAttribute("aria-label")).toContain(`Sample window: ${basis}.`);
    }
  });

  it("wears a delta chip only where a target or a prior measurement exists", async () => {
    mockApi();
    render(<AnalyticsPage />);
    await screen.findByTestId("executive-summary");

    expect(screen.getByTestId("exec-tile-conversion-delta").textContent).toContain(
      "19.3 pts to target",
    );
    expect(screen.getByTestId("exec-tile-rigor-delta").textContent).toContain("from Standard");
    // The pipeline tile has no target and no prior measurement — it gets no
    // chip rather than an approximated one.
    expect(screen.queryByTestId("exec-tile-pipeline-delta")).toBeNull();
  });
});

describe("degradation is stated, never hidden", () => {
  it("keeps a failed endpoint's tile in place, dashed, with its reason", async () => {
    mockApi({ "/analytics/agent-policy": new Error("policy endpoint down") });
    render(<AnalyticsPage />);
    await screen.findByTestId("executive-summary");

    const rigor = screen.getByTestId("exec-tile-rigor");
    expect(rigor.getAttribute("data-measured")).toBe("false");
    expect(within(rigor).getByTestId("exec-tile-rigor-value").textContent).toBe("—");
    expect(within(rigor).getByTestId("exec-tile-rigor-insight").textContent).toContain(
      "has not loaded yet",
    );
    // The band did not reflow: all five slots are still there.
    for (const id of TILE_IDS) expect(screen.getByTestId(`exec-tile-${id}`)).toBeTruthy();
  });
});
