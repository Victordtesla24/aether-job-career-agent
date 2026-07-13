// @vitest-environment jsdom
/**
 * GAP-P4-058 regression guard. The "sources" widget on /dashboard and
 * /dashboard/analytics visualizes a Job-source breakdown (analytics.py:
 * SELECT source, COUNT(*) FROM "Job" GROUP BY source), never an applications
 * count. A prior fix only relabeled the API's `sourcesLabel` field and the
 * center caption, leaving the widget's *primary* section heading and the
 * SVG's accessible name hardcoded as "Applications by Source" — a mislabel a
 * backend-only test cannot see. This test renders the real component and
 * asserts the visible heading and the donut's accessible name at the layer
 * where the defect actually ships.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MarketPulse as MarketPulseData } from "../../../lib/api/workspaces";

const fetchMarketPulse = vi.fn();

vi.mock("../../../lib/api/workspaces", () => ({
  fetchMarketPulse: (...args: unknown[]) => fetchMarketPulse(...args),
}));

// eslint-disable-next-line import/first
import MarketPulse from "../MarketPulse";

const FIXTURE: MarketPulseData = {
  sources: [
    { label: "LinkedIn", value: 60, color: "#818CF8" },
    { label: "Indeed", value: 40, color: "#34D399" },
  ],
  sourcesTotal: 149,
  sourcesLabel: "jobs sourced",
  topSkills: [{ skill: "TypeScript", demand: 80 }],
  activityHeatmap: [[0, 1, 2, 3, 4, 0, 1]],
  probability: {
    score: 72,
    label: "Good",
    note: "Based on recent activity.",
    factors: [{ label: "Fit", value: 80 }],
  },
  employerActivity: [{ company: "Acme", event: "posted a new role", when: "2h ago", signal: "hot" }],
  recruiterTrends: { series: [1, 2, 3], rows: [{ label: "Views", delta: "+3%" }] },
  marketVsYou: {
    marketDataConnected: false,
    comparisons: [{ label: "Response rate", market: null, you: 12, unit: "%" }],
    summary: "Market data: not connected.",
  },
  trendIndicators: [{ label: "Postings", delta: "+2%", direction: "up", series: [1, 2, 3] }],
};

afterEach(() => {
  cleanup();
  fetchMarketPulse.mockReset();
});

describe("MarketPulse sources widget label", () => {
  it("labels the jobs-by-source donut honestly, not as 'applications'", async () => {
    fetchMarketPulse.mockResolvedValue(FIXTURE);
    render(<MarketPulse />);

    const heading = await screen.findByText(/jobs by source/i);
    expect(heading.textContent?.toLowerCase()).not.toContain("application");

    const donut = await screen.findByRole("img", { name: /jobs by source/i });
    expect(donut.getAttribute("aria-label")?.toLowerCase()).not.toContain("application");
  });
});
