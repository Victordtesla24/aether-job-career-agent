// @vitest-environment jsdom
/**
 * PROD-UAT-2026-08-03 F-04 — the job-search score panel must not claim market
 * evidence, must not present a not-measured signal as a number, and must not
 * contradict the "Market data: not connected" state shown on the same screen.
 *
 * Production evidence
 * (uat/reports/evidence/prod-uat-2026-08-03/s13-probability-score-inconsistency.json):
 * "YOUR JOB PROBABILITY SCORE 34% — Likelihood of landing an offer in the next
 * 60 days", factors {Application volume 3, Interview conversion 0, Market
 * demand 100, Skill match 0}, rendered inches from "External market benchmark
 * unavailable / Provider: none configured".
 *
 * A backend-only test cannot catch the half of this defect that lives in the
 * component: the heading and tooltip copy ("blending ... current market
 * conditions") were HARDCODED here, so the server could stop claiming market
 * evidence while the screen kept claiming it. These tests render the real
 * component.
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

const BASE: MarketPulseData = {
  sources: [],
  sourcesTotal: 1637,
  sourcesLabel: "jobs sourced",
  topSkills: [],
  activityHeatmap: [[0, 0, 0, 0, 0, 0, 0]],
  probability: {
    score: 17,
    measured: true,
    label: "Job Search Progress",
    note: "Average of the measured signals below — all from your own applications.",
    methodology: "Not an offer-likelihood estimate. Aether has no offer-outcome model.",
    unmeasuredReason: null,
    marketDataConnected: false,
    factors: [
      { label: "Application volume", value: 3, measured: true },
      { label: "Interview conversion", value: 0, measured: true },
      { label: "Skill match", value: null, measured: false },
    ],
  },
  employerActivity: [],
  recruiterTrends: { series: [1, 2], rows: [] },
  marketVsYou: {
    marketDataConnected: false,
    comparisons: [{ label: "Interview rate", market: null, you: 0, unit: "%" }],
    summary: "No market data source connected — showing your own figures only.",
  },
  trendIndicators: [],
};

afterEach(() => {
  cleanup();
  fetchMarketPulse.mockReset();
});

describe("score panel makes no market-evidence claim (F-04)", () => {
  it("shows no 'Market demand' factor and no offer-likelihood promise", async () => {
    fetchMarketPulse.mockResolvedValue(BASE);
    render(<MarketPulse />);

    const panel = await screen.findByTestId("probability-score");
    const text = (panel.textContent ?? "").toLowerCase();

    expect(text).not.toContain("market demand");
    expect(text).not.toMatch(/likelihood of landing an offer/);
    expect(text).not.toMatch(/job probability score/);
  });

  it("states the same market-data availability as the Market vs. You banner", async () => {
    fetchMarketPulse.mockResolvedValue(BASE);
    render(<MarketPulse />);

    // Both surfaces read the same server flag, so a confident score can never
    // sit next to an unqualified "not connected" banner again.
    const panel = await screen.findByTestId("probability-score");
    expect(panel.textContent?.toLowerCase()).toContain("market data: not connected");

    const banner = await screen.findByTestId("market-vs-you");
    expect(banner.textContent?.toLowerCase()).toContain("market data: not connected");
  });

  it("drops the market-data caveat when a provider really is connected", async () => {
    fetchMarketPulse.mockResolvedValue({
      ...BASE,
      probability: { ...BASE.probability, marketDataConnected: true },
      marketVsYou: { ...BASE.marketVsYou, marketDataConnected: true },
    });
    render(<MarketPulse />);

    const panel = await screen.findByTestId("probability-score");
    expect(panel.querySelector('[data-testid="probability-market-data-state"]')).toBeNull();
  });
});

describe("not-measured signals are never rendered as numbers (F-04)", () => {
  it('badges a null factor "not measured" instead of 0, and draws no bar for it', async () => {
    fetchMarketPulse.mockResolvedValue(BASE);
    render(<MarketPulse />);

    const panel = await screen.findByTestId("probability-score");
    const rows = Array.from(panel.querySelectorAll(".space-y-2 > div"));

    const skill = rows.find((r) => r.textContent?.includes("Skill match"));
    expect(skill).toBeDefined();
    expect(skill?.textContent?.toLowerCase()).toContain("not measured");
    // A measured zero still gets a number and a (0-width) bar; a not-measured
    // one gets neither, so the two are distinguishable on screen.
    expect(skill?.querySelector(".bg-aether-green")).toBeNull();

    const conversion = rows.find((r) => r.textContent?.includes("Interview conversion"));
    expect(conversion?.textContent?.toLowerCase()).not.toContain("not measured");
    expect(conversion?.querySelector(".bg-aether-green")).not.toBeNull();
  });

  it("degrades the headline to 'not measured' rather than a confident 0%", async () => {
    fetchMarketPulse.mockResolvedValue({
      ...BASE,
      probability: {
        ...BASE.probability,
        score: null,
        measured: false,
        unmeasuredReason:
          "Not measured — none of these signals has data yet. Apply to a job to start.",
        factors: BASE.probability.factors.map((f) => ({ ...f, value: null, measured: false })),
      },
    });
    render(<MarketPulse />);

    const panel = await screen.findByTestId("probability-score");
    expect(await screen.findByTestId("probability-not-measured")).toBeTruthy();
    expect(panel.textContent).not.toContain("0%");
    expect(panel.textContent?.toLowerCase()).toContain("none of these signals has data yet");
    // The green progress ring must be gone — an empty ring still reads as a
    // measurement of zero.
    expect(panel.querySelector('svg[role="img"]')).toBeNull();
  });

  it("renders the measured score and the API's own copy when there is data", async () => {
    fetchMarketPulse.mockResolvedValue(BASE);
    render(<MarketPulse />);

    const panel = await screen.findByTestId("probability-score");
    expect(panel.textContent).toContain("17%");
    expect(panel.textContent).toContain("Job Search Progress");
    expect(panel.textContent).toContain(BASE.probability.note);
    expect(panel.querySelector('[data-testid="probability-not-measured"]')).toBeNull();
  });
});
