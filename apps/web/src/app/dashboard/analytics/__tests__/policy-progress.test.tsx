// @vitest-environment jsdom
/**
 * U-AX round-3 — R-05 (wayfinding) + R-06 (the two undelivered spec surfaces).
 *
 * R-05: the interview-conversion gap sentence pointed the reader "below" /
 * "see Agent Performance Policy below" while `AgentPolicyPanel` renders ABOVE
 * the conversion section. The tier claim was honest; the directions were not.
 *
 * R-06(a) — U-PLAN.md U-AX BUILD SPEC ADDITIONS item 2(c): "trend of policy
 * tier over time vs the metrics it responds to". Round 2 shipped only the
 * CURRENT tier while labelling the panel "item 2(a)/(c)".
 * R-06(b) — item 3: "interview-conversion threshold progress visible per
 * cohort (applications under each policy tier)" —
 * `Application.policyTierAtSubmission` was write-only.
 *
 * Both surfaces are rendered from the real endpoints
 * (`GET /analytics/agent-policy/history`, `GET /analytics/agent-policy/cohorts`);
 * this file pins the HONEST rendering rules: a withheld rate reads as a
 * withheld rate, an empty history reads as "not recorded yet", and a
 * pre-instrumentation cohort is never folded into a real tier.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
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
const ROI_FIXTURE = { total_cost_usd: 0, total_runs: 0, avg_duration_ms: 0 };
const DASHBOARD_FIXTURE = {
  totalApplications: 40,
  interviews: 2,
  offers: 0,
  jobsFound: 100,
  avgFitScore: 61,
  agentRuns: 12,
  agentCostUsd: 0.4,
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
const FUNNEL_FIXTURE = {
  period: "all", jobs_found: 100, applied: 40, screened: 0, interviewed: 2, offers: 0,
};
const CONVERSION_FIXTURE = {
  period: "all",
  found_to_applied: 40,
  applied_to_screened: 0,
  screened_to_interview: 0,
  interview_to_offer: 0,
  interview_conversion_rate: 5,
  interview_conversion_healthy: false,
};
const POLICY_FIXTURE = {
  tier: "heightened",
  triggers: ["interview conversion 5.0% is below the 20% target"],
  behaviour: "Heightened rigor: résumé tailoring runs up to 7 scoring iterations.",
  knobs: { maxIterations: 7, targetScore: 88, coverLetterRetries: 3 },
  thresholds: { interviewConversionTarget: 0.2, dimensionFloor: 80, minSampleSize: 5 },
  metricSnapshot: {
    sampleSize: 40,
    conversionRate: 5,
    interviewCount: 2,
    dimensionScores: { cultureFit: 72.5 },
    dimensionSampleSize: 12,
    dimensionsEvaluated: 3,
    available: true,
    unavailableReason: null,
  },
  perAgent: [],
};

const HISTORY_FIXTURE = {
  available: true,
  reason: null,
  runsWithoutPolicy: 4,
  thresholds: { interviewConversionTarget: 20, dimensionFloor: 80, minSampleSize: 5 },
  points: [
    {
      at: "2026-08-01T00:00:00Z",
      tier: "insufficient_data",
      runs: 2,
      conversionRate: 0,
      sampleSize: 2,
      interviewCount: 0,
      dimensionsBelowFloor: [],
      dimensionsEvaluated: 0,
      triggers: ["insufficient data: 2 submitted application(s)"],
    },
    {
      at: "2026-08-10T00:00:00Z",
      tier: "heightened",
      runs: 9,
      conversionRate: 5,
      sampleSize: 40,
      interviewCount: 2,
      dimensionsBelowFloor: ["cultureFit"],
      dimensionsEvaluated: 3,
      triggers: ["interview conversion 5.0% is below the 20% target"],
    },
  ],
};

const COHORTS_FIXTURE = {
  target: 20,
  minSampleSize: 5,
  cohorts: [
    {
      tier: "standard",
      label: "Standard rigor",
      // AUD-META-1: prepared (left draft) and transmitted (verified send) are
      // separate counts; the rate is computed over the transmitted one.
      prepared: 24,
      transmitted: 24,
      interviewed: 2,
      conversionRate: 8.33,
      sufficientSample: true,
      meetsTarget: false,
      gapPoints: 11.67,
    },
    {
      tier: "heightened",
      label: "Heightened rigor",
      prepared: 3,
      transmitted: 3,
      interviewed: 0,
      conversionRate: null,
      sufficientSample: false,
      meetsTarget: null,
      gapPoints: null,
    },
  ],
  untagged: {
    prepared: 178,
    transmitted: 178,
    interviewed: 0,
    reason: "prepared before the rigor policy was instrumented",
  },
};

function mockApi(overrides: Record<string, unknown> = {}) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path in overrides) return overrides[path];
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

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
});

describe("R-05 — the conversion gap sentence points where the panel actually is", () => {
  it("never sends the reader 'below' to a panel rendered above it", async () => {
    mockApi();
    const { container } = render(<AnalyticsPage />);

    const gap = await screen.findByTestId("interview-conversion-gap");
    expect(gap.textContent).toMatch(/agent performance policy/i);
    expect(gap.textContent?.toLowerCase()).not.toMatch(/below\)|see below|policy below/);

    const panel = container.querySelector('[data-testid="agent-policy-panel"]');
    const conversion = container.querySelector('[data-testid="conversion-rates"]');
    expect(panel).not.toBeNull();
    expect(conversion).not.toBeNull();
    // Whatever wording is used, it must agree with the real DOM order.
    const panelIsBefore =
      (panel!.compareDocumentPosition(conversion!) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect(panelIsBefore).toBe(true);
    expect(gap.textContent?.toLowerCase()).toMatch(/above/);
  });
});

describe("R-06(a) — policy-tier history over time vs the metrics it responds to", () => {
  it("renders one row per recorded tier point, oldest first, with its metrics", async () => {
    mockApi();
    render(<AnalyticsPage />);
    const panel = await screen.findByTestId("policy-tier-history");

    const rows = within(panel).getAllByTestId("policy-tier-history-point");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent?.toLowerCase()).toMatch(/insufficient data/);
    expect(rows[1].textContent?.toLowerCase()).toMatch(/heightened/);
    // The metric the tier RESPONDS to travels with the point.
    expect(rows[1].textContent).toMatch(/5%/);
    expect(rows[1].textContent).toMatch(/40/);
    // Runs covered by an unchanged tier are stated, not hidden.
    expect(rows[1].textContent).toMatch(/9/);
  });

  it("shows an honest empty state instead of an empty chart when nothing is recorded", async () => {
    mockApi({
      "/analytics/agent-policy/history": {
        available: false,
        reason: "no agent run has recorded a rigor policy yet",
        runsWithoutPolicy: 12,
        thresholds: { interviewConversionTarget: 20, dimensionFloor: 80, minSampleSize: 5 },
        points: [],
      },
    });
    render(<AnalyticsPage />);
    const panel = await screen.findByTestId("policy-tier-history");
    expect(within(panel).queryAllByTestId("policy-tier-history-point")).toHaveLength(0);
    expect(panel.textContent).toMatch(/no agent run has recorded a rigor policy yet/i);
  });
});

describe("R-06(b) — interview-conversion progress per policy-tier cohort", () => {
  it("renders one row per cohort with its rate against the 20% target", async () => {
    mockApi();
    render(<AnalyticsPage />);
    const panel = await screen.findByTestId("policy-cohorts");

    const standard = within(panel).getByTestId("policy-cohort-standard");
    expect(standard.textContent).toMatch(/24/);
    expect(standard.textContent).toMatch(/8\.33%/);
    expect(panel.textContent).toMatch(/20%/);
  });

  it("renders a below-minimum-sample cohort as counts, never as a fabricated rate", async () => {
    mockApi();
    render(<AnalyticsPage />);
    const panel = await screen.findByTestId("policy-cohorts");

    const heightened = within(panel).getByTestId("policy-cohort-heightened");
    expect(heightened.textContent).toMatch(/—/);
    expect(heightened.textContent).not.toMatch(/0%/);
    expect(heightened.textContent?.toLowerCase()).toMatch(/not enough|at least 5/);
  });

  it("keeps pre-instrumentation applications in their own labelled bucket", async () => {
    mockApi();
    render(<AnalyticsPage />);
    const panel = await screen.findByTestId("policy-cohorts");

    const untagged = within(panel).getByTestId("policy-cohort-untagged");
    expect(untagged.textContent).toMatch(/178/);
    expect(untagged.textContent?.toLowerCase()).toMatch(/before the rigor policy/);
  });
});
