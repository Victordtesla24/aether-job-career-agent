// @vitest-environment jsdom
/**
 * GAP-P4-058 regression guard, plus I2 (Market vs. You live Adzuna wiring,
 * D-0042 / R2-R11) contract tests for the FRONTEND per-row payload shape.
 *
 * As of the I1 backend slice (analytics.py `market_pulse`, live-verified
 * 2026-08-13), `marketVsYou.comparisons[]` items carry their OWN provenance —
 * `connected: boolean`, `dataAsOf: string | null`, plus optional `marketNote`
 * / `footnote` — instead of a single global `marketVsYou.marketDataConnected`
 * flag. This file is written BEFORE the I2 frontend slice (workspaces.ts
 * type + MarketPulse.tsx) exists, so the new assertions below are expected
 * to be RED: the current component does not yet read `connected`, `dataAsOf`,
 * `marketNote` or `footnote` off a comparison row, still branches on the
 * removed global flag, and always renders a "you" bar even when `you` is
 * `null`. The literal object fixtures below also violate the CURRENT
 * (pre-I2) `MarketPulseData["marketVsYou"]["comparisons"]` element type
 * (`connected`/`dataAsOf`/`marketNote`/`footnote` are unknown keys on it, and
 * `you` is typed `number`, not `number | null`) — a `tsc --noEmit` red is
 * expected alongside the runtime red until workspaces.ts is updated.
 *
 * Contract this file fixes for the I2 implementation (BRIEF-B):
 *   - Per comparison row, a `data-testid="market-comparison-row-<index>"`
 *     container (index = position in `comparisons`).
 *   - Within a row: `connected && market !== null` renders the market value
 *     + (when present) `marketNote` text + a `<time dateTime="<dataAsOf>">`
 *     freshness label (human-readable text, not the raw ISO string).
 *   - Within a row: NOT `(connected && market !== null)` renders the exact
 *     "Market data: not connected" copy — regardless of any OTHER row's
 *     connection state.
 *   - `footnote`, when present, renders under the row regardless of
 *     `connected`.
 *   - `you === null` renders no coral "you" bar and no raw "NaN"/"null" text.
 *   - When ANY row is `connected`, a `data-testid="market-vs-you-attribution"`
 *     element replaces the amber banner, containing "Adzuna Australia" text
 *     and a `<time dateTime="...">` for the freshest connected row.
 *   - When NO row is `connected`, the EXACT pre-existing amber banner still
 *     renders (copy unchanged).
 *   - An unparseable `dataAsOf` string must not throw and must not render
 *     "NaN" or "Invalid Date".
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MarketPulse as MarketPulseData } from "../../../lib/api/workspaces";

const fetchMarketPulse = vi.fn();

vi.mock("../../../lib/api/workspaces", () => ({
  fetchMarketPulse: (...args: unknown[]) => fetchMarketPulse(...args),
}));

// eslint-disable-next-line import/first
import MarketPulse from "../MarketPulse";

/** Fixed instant well clear of any UTC-offset day boundary (year is a safe,
 * TZ-independent substring for any reasonable date rendering of it). */
const NOW_ISO = "2026-08-13T12:00:00+00:00";

const POSTINGS_NOTE =
  "Market = 42 job ads posted in the last 30 days in New South Wales for " +
  "Business Analyst (Adzuna Australia) — employer demand, not applications " +
  "sent by other candidates.";
const INTERVIEW_FOOTNOTE = "No external interview-conversion benchmark provider currently exists.";
const SALARY_FOOTNOTE = "No disclosed salary data in your saved jobs yet.";

const BASE_NON_MARKET_FIELDS: Omit<MarketPulseData, "marketVsYou"> = {
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
    measured: true,
    label: "Job Search Progress",
    note: "Based on recent activity.",
    methodology: "Not an offer-likelihood estimate.",
    unmeasuredReason: null,
    marketDataConnected: false,
    factors: [{ label: "Fit", value: 80, measured: true }],
  },
  employerActivity: [{ company: "Acme", event: "posted a new role", when: "2h ago", signal: "hot" }],
  recruiterTrends: {
    series: [1, 2, 3],
    rows: [{ label: "Views", delta: "+3%", direction: "up", deltaKind: "percent" }],
  },
  trendIndicators: [
    { label: "Postings", delta: "+2%", direction: "up", deltaKind: "percent", series: [1, 2, 3] },
  ],
};

/** All rows disconnected — the honest no-provider state (R10). */
const FIXTURE: MarketPulseData = {
  ...BASE_NON_MARKET_FIELDS,
  marketVsYou: {
    comparisons: [
      { label: "Applications / month", market: null, you: 7, connected: false, dataAsOf: null },
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
    summary: "No market data source connected — showing your own figures only.",
  },
};

/** Row 0 (postings) and row 2 (salary, you=null) connected; row 1 (interview)
 * permanently disconnected per R4 even though other rows are connected. */
const CONNECTED_FIXTURE: MarketPulseData = {
  ...BASE_NON_MARKET_FIELDS,
  marketVsYou: {
    comparisons: [
      {
        label: "Applications / month",
        market: 42,
        you: 7,
        connected: true,
        dataAsOf: NOW_ISO,
        marketNote: POSTINGS_NOTE,
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
      {
        label: "Advertised salary (mean)",
        market: 147925,
        you: null,
        unit: "A$",
        connected: true,
        dataAsOf: NOW_ISO,
        footnote: SALARY_FOOTNOTE,
      },
    ],
    summary:
      "Market data: Adzuna Australia — 42 live postings (last 30 days) for your target role in New South Wales.",
  },
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

describe("MarketPulse unavailable external market data state (GAP-P4-004, R10)", () => {
  it("all rows disconnected renders the EXACT amber banner copy", async () => {
    fetchMarketPulse.mockResolvedValue(FIXTURE);
    render(<MarketPulse />);

    const marketComparison = await screen.findByTestId("market-vs-you");
    expect(marketComparison.textContent).toMatch(/external market benchmark unavailable/i);
    expect(marketComparison.textContent).toMatch(/provider: none configured/i);
    expect(marketComparison.textContent).toMatch(/your figures are derived from your saved jobs and applications/i);

    // The new "connected" attribution line must NOT appear when nothing is connected.
    expect(marketComparison.querySelector('[data-testid="market-vs-you-attribution"]')).toBeNull();
  });
});

describe("MarketPulse per-row connected state (R2, R5, R7-R11)", () => {
  it("a connected row renders its market value, marketNote, and a freshness label derived from dataAsOf", async () => {
    fetchMarketPulse.mockResolvedValue(CONNECTED_FIXTURE);
    render(<MarketPulse />);

    const panel = await screen.findByTestId("market-vs-you");
    // Banner is gone, replaced by an attribution line, once any row connects.
    expect(panel.textContent).not.toMatch(/external market benchmark unavailable/i);

    const row0 = within(panel).getByTestId("market-comparison-row-0");
    expect(row0.textContent).toContain("42");
    expect(row0.textContent).toContain(POSTINGS_NOTE);

    const freshness = row0.querySelector(`time[datetime="${NOW_ISO}"]`);
    expect(freshness).not.toBeNull();
    expect(freshness?.textContent?.trim()).not.toBe("");
    expect(freshness?.textContent).not.toBe(NOW_ISO);
    expect(freshness?.textContent?.toLowerCase()).not.toContain("invalid date");
    expect(freshness?.textContent).not.toContain("NaN");
  });

  it("shows a top-level Adzuna attribution + freshness label once any row is connected", async () => {
    fetchMarketPulse.mockResolvedValue(CONNECTED_FIXTURE);
    render(<MarketPulse />);

    const attribution = await screen.findByTestId("market-vs-you-attribution");
    expect(attribution.textContent?.toLowerCase()).toContain("adzuna australia");
    expect(attribution.querySelector(`time[datetime="${NOW_ISO}"]`)).not.toBeNull();
  });

  it("the interview row stays 'not connected' with its own footnote EVEN WHEN another row is connected (R4)", async () => {
    fetchMarketPulse.mockResolvedValue(CONNECTED_FIXTURE);
    render(<MarketPulse />);

    const panel = await screen.findByTestId("market-vs-you");
    const interviewRow = within(panel).getByTestId("market-comparison-row-1");
    expect(interviewRow.textContent).toMatch(/market data: not connected/i);
    expect(interviewRow.textContent).toContain(INTERVIEW_FOOTNOTE);

    // The connected postings row must NOT show the disconnected copy.
    const postingsRow = within(panel).getByTestId("market-comparison-row-0");
    expect(postingsRow.textContent).not.toMatch(/market data: not connected/i);
  });

  it("a row with you=null renders honest no-data copy: no you-bar, no NaN, no literal 'null'", async () => {
    fetchMarketPulse.mockResolvedValue(CONNECTED_FIXTURE);
    render(<MarketPulse />);

    const panel = await screen.findByTestId("market-vs-you");
    const salaryRow = within(panel).getByTestId("market-comparison-row-2");

    expect(salaryRow.textContent).toContain(SALARY_FOOTNOTE);
    expect(salaryRow.querySelector(".bg-aether-coral")).toBeNull();
    expect(salaryRow.textContent).not.toContain("NaN");
    expect(salaryRow.textContent?.toLowerCase()).not.toMatch(/\bnull\b/);
  });

  it("an unparseable dataAsOf string does not crash the component and never renders NaN/Invalid Date", async () => {
    const brokenFixture: MarketPulseData = {
      ...BASE_NON_MARKET_FIELDS,
      marketVsYou: {
        comparisons: [
          {
            label: "Applications / month",
            market: 10,
            you: 1,
            connected: true,
            dataAsOf: "not-a-real-date",
          },
        ],
        summary: "Market data: Adzuna Australia — 10 live postings (last 30 days) for your target role.",
      },
    };
    fetchMarketPulse.mockResolvedValue(brokenFixture);

    expect(() => render(<MarketPulse />)).not.toThrow();

    const panel = await screen.findByTestId("market-vs-you");
    expect(panel.textContent).not.toContain("NaN");
    expect(panel.textContent?.toLowerCase()).not.toContain("invalid date");

    // Ties the crash-guard to the same new per-row contract as the other
    // tests above, so this is a genuine red against the current component
    // (which does not render this testid at all) rather than a vacuous pass
    // that only exercises code paths that do not exist yet.
    const row0 = within(panel).getByTestId("market-comparison-row-0");
    expect(row0.textContent).not.toContain("NaN");
    expect(row0.textContent?.toLowerCase()).not.toContain("invalid date");
  });
});

describe("MarketPulse top-skills honest empty state (MV-mobile-dashboard-006, MV-analytics-006)", () => {
  it("shows explanatory copy instead of a silent blank area when topSkills is empty", async () => {
    fetchMarketPulse.mockResolvedValue({ ...FIXTURE, topSkills: [] });
    render(<MarketPulse />);

    const widget = await screen.findByTestId("top-skills");
    // The heading still renders...
    expect(widget.textContent).toMatch(/top skills in demand/i);
    // ...but the content area must not be a bare, message-less empty <div>.
    expect(widget.querySelector(".space-y-3")).toBeNull();
    expect(widget.textContent?.toLowerCase()).toMatch(/not enough job data|no skill data/);
  });

  it("still renders the skill bars when topSkills has data", async () => {
    fetchMarketPulse.mockResolvedValue(FIXTURE);
    render(<MarketPulse />);

    const widget = await screen.findByTestId("top-skills");
    expect(widget.textContent).toContain("TypeScript");
    expect(widget.textContent?.toLowerCase()).not.toMatch(/not enough job data|no skill data/);
  });
});

describe("MarketPulse trend indicator tooltip honesty (MON-016)", () => {
  it("the 'vs. the prior period' tooltip claim must agree with the direction implied by the indicator's own last two data points", async () => {
    // Live prod evidence, 2026-08-13 U-AX audit
    // (api_market-pulse_20260813T130014Z.json): the backend served
    // "Your application velocity" as delta="+134%"/direction="up" for
    // series=[44,43,290,103] — the FIRST vs LAST point of the whole
    // lookback window. Its own tile tooltip
    // (MarketPulse.tsx:148, `${t.label}: percentage change vs. the prior
    // period.`) literally claims the badge describes the change vs. the
    // prior period. Rendering a direction that disagrees with the real
    // prior-period comparison is a live, reproducible dishonesty defect.
    const fixture: MarketPulseData = {
      ...FIXTURE,
      trendIndicators: [
        {
          label: "Your application velocity",
          delta: "+134%",
          direction: "up",
          deltaKind: "percent",
          series: [44, 43, 290, 103],
        },
      ],
    };
    fetchMarketPulse.mockResolvedValue(fixture);
    render(<MarketPulse />);

    const container = await screen.findByTestId("trend-indicators");
    const badgeValue = within(container).getByText("+134%");
    const wrapper = badgeValue.closest('[data-testid="metric-tooltip"]');
    expect(wrapper).not.toBeNull();

    const popover = within(wrapper as HTMLElement).getByTestId("metric-tooltip-popover");
    expect(popover.textContent).toMatch(/vs\. the prior period/i);

    const series = fixture.trendIndicators[0].series;
    // AX-REV-01 (2026-08-13 re-audit): series' LAST point (103) is always
    // the current, still-in-progress Melbourne week — never a complete
    // period — so the TRUE "prior period" comparison is the last TWO
    // COMPLETE points (indices -2 and -3: 290 vs 43), not the raw tail
    // (-1 and -2: 290 vs 103) the original MON-016 fix still used. That
    // raw-tail comparison is exactly what let a request landing mid-week
    // keep showing the wrong sign even after the MON-016 fix shipped.
    const truePriorPeriodChange = series.at(-2)! - series.at(-3)!; // 290 - 43
    const trueDirection = truePriorPeriodChange >= 0 ? "up" : "down";
    expect(trueDirection).toBe("up"); // sanity: excluding the in-progress
    // point flips this from the raw tail's spurious "down" to a genuine rise

    // The badge's color/direction is the ONLY signal next to a tooltip that
    // literally says "vs. the prior period" — it must match the TRUE
    // last-COMPLETE-vs-prior-COMPLETE direction, not a comparison that
    // treats the in-progress current week as if it were finished.
    // R1: gold is never a state, so a falling delta wears the danger tone.
    expect((wrapper as HTMLElement).className).toContain(
      trueDirection === "up" ? "text-aether-green" : "text-state-danger"
    );
  });
});

describe("MarketPulse trend indicator sparkline honesty (R-03)", () => {
  it("renders the trailing in-progress week as a visually distinct (reduced-opacity) segment, separate from the completed-week line", async () => {
    // R-03 (AX re-review round 2): the sparkline used to plot the trailing,
    // still-in-progress week as an ordinary, indistinguishable point on the
    // same solid polyline as every completed week — contradicting the
    // badge/tooltip next to it, which both exclude that week from the
    // delta (RULING-A). The chart must now visually agree: the final
    // segment (connecting the last completed point to the in-progress
    // point) renders separately, at reduced opacity.
    const fixture: MarketPulseData = {
      ...FIXTURE,
      trendIndicators: [
        {
          label: "Your application velocity",
          delta: "+400%",
          direction: "up",
          deltaKind: "percent",
          series: [0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 10, 1],
        },
      ],
    };
    fetchMarketPulse.mockResolvedValue(fixture);
    render(<MarketPulse />);

    const tile = await screen.findByTestId("trend-indicator-tile");
    const svg = tile.querySelector("svg");
    expect(svg).not.toBeNull();

    const partial = within(tile).getByTestId("trend-partial-segment");
    expect(partial.getAttribute("stroke-opacity")).toBe("0.35");

    // The partial segment must be a SEPARATE element from the main
    // (completed-weeks) polyline(s) — not the same fully-opaque path — so
    // the chart cannot render the in-progress week as if it were finished.
    const allPolylines = svg!.querySelectorAll("polyline");
    expect(allPolylines.length).toBeGreaterThanOrEqual(2);
    const mainPolylines = Array.from(allPolylines).filter(
      (p) => p.getAttribute("data-testid") !== "trend-partial-segment",
    );
    for (const p of mainPolylines) {
      expect(p.getAttribute("stroke-opacity")).not.toBe("0.35");
    }
  });

  it("renders a genuine gap (no fabricated line) for a null week in an average series, never a flat-zero segment", async () => {
    // R-01 companion: an AVERAGE series (e.g. "Avg job fit score") carries
    // honest `null` gaps. The chart must not draw a line through a null
    // point as if it were a real 0 — the two known points must render as
    // disconnected segments, not one continuous polyline that dips to 0.
    const fixture: MarketPulseData = {
      ...FIXTURE,
      trendIndicators: [
        {
          label: "Avg job fit score",
          delta: "insufficient data",
          direction: "flat",
          deltaKind: "insufficient-data",
          series: [null, null, null, null, null, null, null, null, 55, null, null, null],
        },
      ],
    };
    fetchMarketPulse.mockResolvedValue(fixture);
    render(<MarketPulse />);

    const tile = await screen.findByTestId("trend-indicator-tile");
    const svg = tile.querySelector("svg");
    // No trailing partial segment: the final (in-progress) week itself is
    // null — there is nothing there to draw, which is itself honest.
    expect(within(tile).queryByTestId("trend-partial-segment")).toBeNull();
    // A single known point with no adjacent known point on either side has
    // no line to draw at all.
    expect(svg!.querySelectorAll("polyline").length).toBe(0);
  });
});

describe("MarketPulse trend indicator neutral badge for non-percent deltas (R-04/RULING-C)", () => {
  it("renders a neutral (non-green/coral) badge and matching tooltip copy for a zero-base 'new' delta, never through percent styling", async () => {
    const fixture: MarketPulseData = {
      ...FIXTURE,
      trendIndicators: [
        {
          label: "Your application velocity",
          delta: "new activity",
          direction: "up",
          deltaKind: "new",
          series: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 1],
        },
      ],
    };
    fetchMarketPulse.mockResolvedValue(fixture);
    render(<MarketPulse />);

    const container = await screen.findByTestId("trend-indicators");
    const badgeValue = within(container).getByText("new activity");
    const wrapper = badgeValue.closest('[data-testid="metric-tooltip"]') as HTMLElement;
    expect(wrapper.className).not.toContain("text-aether-green");
    expect(wrapper.className).not.toContain("text-aether-coral");

    const popover = within(wrapper).getByTestId("metric-tooltip-popover");
    expect(popover.textContent?.toLowerCase()).toMatch(/new activity/);
    expect(popover.textContent?.toLowerCase()).not.toMatch(/percentage change/);
  });

  it("renders a neutral badge and matching tooltip copy for 'insufficient-data', never through percent styling", async () => {
    const fixture: MarketPulseData = {
      ...FIXTURE,
      trendIndicators: [
        {
          label: "Avg job fit score",
          delta: "insufficient data",
          direction: "flat",
          deltaKind: "insufficient-data",
          series: [null, null, null, null, null, null, null, null, null, null, null, null],
        },
      ],
    };
    fetchMarketPulse.mockResolvedValue(fixture);
    render(<MarketPulse />);

    const container = await screen.findByTestId("trend-indicators");
    const badgeValue = within(container).getByText("insufficient data");
    const wrapper = badgeValue.closest('[data-testid="metric-tooltip"]') as HTMLElement;
    expect(wrapper.className).not.toContain("text-aether-green");
    expect(wrapper.className).not.toContain("text-aether-coral");

    const popover = within(wrapper).getByTestId("metric-tooltip-popover");
    expect(popover.textContent?.toLowerCase()).toMatch(/not enough completed-period data/);
    expect(popover.textContent?.toLowerCase()).not.toMatch(/percentage change/);
  });
});

describe("MarketPulse recruiter-trends sparkline + badge honesty (MUST-FIX-1, AX round-3 final re-review)", () => {
  it("renders the trailing in-progress week as a visually distinct partial segment, same remedy as the Trend Indicators tiles (R-03 extended)", async () => {
    const fixture: MarketPulseData = {
      ...FIXTURE,
      recruiterTrends: {
        series: [0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 10, 1],
        rows: [
          { label: "Agent runs (last 12 wks)", delta: "15 total", direction: "flat", deltaKind: "total" },
          { label: "Avg runs / week", delta: "1.3 · +400%", direction: "up", deltaKind: "percent" },
        ],
      },
    };
    fetchMarketPulse.mockResolvedValue(fixture);
    render(<MarketPulse />);

    const card = await screen.findByTestId("recruiter-trends");
    const svg = card.querySelector("svg");
    expect(svg).not.toBeNull();

    const partial = within(card).getByTestId("trend-partial-segment");
    expect(partial.getAttribute("stroke-opacity")).toBe("0.35");

    // The partial segment must be a SEPARATE element from the main
    // (completed-weeks) polyline(s) — not the same fully-opaque path — so
    // the chart cannot render the in-progress week as if it were finished.
    const allPolylines = svg!.querySelectorAll("polyline");
    expect(allPolylines.length).toBeGreaterThanOrEqual(2);
    const mainPolylines = Array.from(allPolylines).filter(
      (p) => p.getAttribute("data-testid") !== "trend-partial-segment",
    );
    for (const p of mainPolylines) {
      expect(p.getAttribute("stroke-opacity")).not.toBe("0.35");
    }
  });

  it("never paints a non-percent ('total') delta green or coral — the cumulative-count row is always neutral", async () => {
    const fixture: MarketPulseData = {
      ...FIXTURE,
      recruiterTrends: {
        series: [1, 1, 1],
        rows: [{ label: "Agent runs (last 12 wks)", delta: "3 total", direction: "flat", deltaKind: "total" }],
      },
    };
    fetchMarketPulse.mockResolvedValue(fixture);
    render(<MarketPulse />);

    const card = await screen.findByTestId("recruiter-trends");
    const badge = within(card).getByText("3 total");
    expect(badge.className).not.toContain("text-aether-green");
    expect(badge.className).not.toContain("text-aether-coral");
  });

  it("colors a genuine percent delta by its real direction, matching the sibling Trend Indicators tile convention, instead of always green", async () => {
    const fixture: MarketPulseData = {
      ...FIXTURE,
      recruiterTrends: {
        series: [1, 1, 1],
        rows: [{ label: "Avg runs / week", delta: "2.0 · -50%", direction: "down", deltaKind: "percent" }],
      },
    };
    fetchMarketPulse.mockResolvedValue(fixture);
    render(<MarketPulse />);

    const card = await screen.findByTestId("recruiter-trends");
    const badge = within(card).getByText("2.0 · -50%");
    expect(badge.className).toContain("text-state-danger");
    expect(badge.className).not.toContain("text-aether-green");
    // R1: gold is a brand colour, never a state.
    expect(badge.className).not.toContain("text-aether-coral");
  });
});
