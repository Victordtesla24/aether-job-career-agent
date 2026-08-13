// @vitest-environment jsdom
/**
 * PROD-UAT-2026-08-03 F-04 — the job-search score panel must not claim market
 * evidence, must not present a not-measured signal as a number, and must not
 * contradict its OWN market-data-availability state.
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
 *
 * R5 DECOUPLING (I2 slice, D-0042): `marketVsYou.marketDataConnected` (the
 * transitional global flag on the OTHER panel) is REMOVED/optional and no
 * longer exists as a per-row concept — each `marketVsYou.comparisons[]` row
 * now carries its own `connected`/`dataAsOf` state (see MarketPulse.test.tsx).
 * `probability.marketDataConnected` is DECOUPLED from it by design: the
 * probability model has zero market evidence and stays a flat `false`
 * regardless of whether Market vs. You has real, live, connected rows. The
 * two panels are therefore explicitly allowed — expected — to disagree once
 * Market vs. You has live data. The tests below assert the probability
 * caveat is driven ONLY by `probability.marketDataConnected`, using
 * per-row `marketVsYou` fixtures that carry NO reliance on any global flag.
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

const INTERVIEW_FOOTNOTE = "No external interview-conversion benchmark provider currently exists.";

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
    // Per-row shape only — no global flag anywhere in this fixture.
    comparisons: [
      {
        label: "Interview rate",
        market: null,
        you: 0,
        unit: "%",
        connected: false,
        dataAsOf: null,
        footnote: INTERVIEW_FOOTNOTE,
      },
    ],
    summary: "No market data source connected — showing your own figures only.",
  },
  trendIndicators: [],
};

/** A live, connected Market vs. You row — real Adzuna data flowing — while
 * `probability.marketDataConnected` stays its permanent `false` (R5). */
const MARKET_VS_YOU_CONNECTED: MarketPulseData["marketVsYou"] = {
  comparisons: [
    {
      label: "Applications / month",
      market: 42,
      you: 7,
      connected: true,
      dataAsOf: "2026-08-13T12:00:00+00:00",
      marketNote: "Market = 42 job ads posted in the last 30 days (Adzuna Australia).",
    },
    {
      label: "Interview rate",
      market: null,
      you: 25,
      unit: "%",
      connected: false,
      dataAsOf: null,
      footnote: INTERVIEW_FOOTNOTE,
    },
  ],
  summary: "Market data: Adzuna Australia — 42 live postings (last 30 days) for your target role.",
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
});

describe("probability market-data caveat is driven ONLY by probability.marketDataConnected (R5 decoupling)", () => {
  it("keeps the caveat when probability.marketDataConnected is false, even though a Market vs. You row IS connected", async () => {
    fetchMarketPulse.mockResolvedValue({
      ...BASE,
      probability: { ...BASE.probability, marketDataConnected: false },
      marketVsYou: MARKET_VS_YOU_CONNECTED,
    });
    render(<MarketPulse />);

    const panel = await screen.findByTestId("probability-score");
    expect(panel.textContent?.toLowerCase()).toContain("market data: not connected");
    expect(panel.querySelector('[data-testid="probability-market-data-state"]')).not.toBeNull();
  });

  it("drops the caveat when probability.marketDataConnected is true, even though every Market vs. You row is disconnected", async () => {
    fetchMarketPulse.mockResolvedValue({
      ...BASE,
      probability: { ...BASE.probability, marketDataConnected: true },
      // marketVsYou unchanged from BASE: every row is connected: false.
    });
    render(<MarketPulse />);

    const panel = await screen.findByTestId("probability-score");
    expect(panel.querySelector('[data-testid="probability-market-data-state"]')).toBeNull();
  });
});

describe("Market vs. You connection state is governed ONLY by its own rows, independent of probability.marketDataConnected (R5 decoupling)", () => {
  it("still shows the disconnected amber banner when probability.marketDataConnected is true but no row is connected", async () => {
    fetchMarketPulse.mockResolvedValue({
      ...BASE,
      probability: { ...BASE.probability, marketDataConnected: true },
      // marketVsYou unchanged: every row connected: false.
    });
    render(<MarketPulse />);

    const banner = await screen.findByTestId("market-vs-you");
    expect(banner.textContent).toMatch(/external market benchmark unavailable/i);
  });

  it("hides the amber banner (shows the connected attribution) when a row is connected, even though probability.marketDataConnected stays false", async () => {
    fetchMarketPulse.mockResolvedValue({
      ...BASE,
      probability: { ...BASE.probability, marketDataConnected: false },
      marketVsYou: MARKET_VS_YOU_CONNECTED,
    });
    render(<MarketPulse />);

    const banner = await screen.findByTestId("market-vs-you");
    expect(banner.textContent).not.toMatch(/external market benchmark unavailable/i);
    expect(banner.querySelector('[data-testid="market-vs-you-attribution"]')).not.toBeNull();
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
