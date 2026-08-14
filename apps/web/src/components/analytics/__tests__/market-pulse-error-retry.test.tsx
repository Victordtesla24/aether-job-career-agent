// @vitest-environment jsdom
/**
 * S-UI-REBUILD-SPEC §5.1 — "per-widget error card with retry (one widget
 * failing must never blank the page)".
 *
 * MarketPulse had the error card and not the retry. Its whole render was:
 *
 *   if (error) return <p className="rounded-xl border border-red-500/30 …">{error}</p>;
 *
 * — a dead red strip at the bottom of BOTH flagship screens (Dashboard and
 * Analytics both mount this component), with no way back short of a full page
 * reload. `GET /analytics/market-pulse` is the slowest call on either page
 * (8–15s measured in production — `b1/before/before-notes.json`), which is
 * exactly the profile of a request that intermittently times out, so this is
 * the widget least able to afford having no retry.
 *
 * These assertions were RED before the fix (`market-pulse-retry` did not
 * exist and the failure branch rendered a bare <p>) and are GREEN after.
 *
 * What they pin, beyond "a button exists":
 *   - the server's own message survives VERBATIM (polish never softens truth —
 *     Binding Constraint 1, honesty contracts);
 *   - retry re-issues the SAME call, and a second call is made only because a
 *     user asked for it — mount still issues exactly one (behavioral parity,
 *     §6.3 item 2);
 *   - a successful retry actually resolves into the real panel, so the
 *     affordance is not decorative.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MarketPulse as MarketPulseData } from "../../../lib/api/workspaces";

const fetchMarketPulse = vi.fn();

vi.mock("../../../lib/api/workspaces", () => ({
  fetchMarketPulse: (...args: unknown[]) => fetchMarketPulse(...args),
}));

// eslint-disable-next-line import/first
import MarketPulse from "../MarketPulse";

const FIXTURE: MarketPulseData = {
  sources: [{ label: "Adzuna", value: 100, color: "#818CF8" }],
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
  marketVsYou: {
    comparisons: [
      { label: "Applications / month", market: null, you: 7, connected: false, dataAsOf: null },
    ],
    summary: "No market data source connected — showing your own figures only.",
  },
};

const SERVER_MESSAGE = "502 Bad Gateway — /analytics/market-pulse";

afterEach(() => {
  cleanup();
  fetchMarketPulse.mockReset();
});

describe("MarketPulse per-widget error card (S-UI-REBUILD-SPEC §5.1)", () => {
  it("draws a labelled error card carrying the server's message verbatim", async () => {
    fetchMarketPulse.mockRejectedValue(new Error(SERVER_MESSAGE));
    render(<MarketPulse />);

    const card = await screen.findByTestId("market-pulse-error");
    // The panel names itself — a user must be able to tell WHICH widget failed.
    expect(card.textContent).toMatch(/Real-Time Market Pulse/);
    // ...and that the rest of the page is still trustworthy.
    expect(card.textContent).toMatch(/only this panel failed to load/i);
    // The recorded failure, not a friendlier substitute.
    expect(screen.getByTestId("market-pulse-error-detail").textContent).toBe(SERVER_MESSAGE);
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("offers a retry, and mount alone issues exactly one request", async () => {
    fetchMarketPulse.mockRejectedValue(new Error(SERVER_MESSAGE));
    render(<MarketPulse />);

    await screen.findByTestId("market-pulse-retry");
    // Behavioral parity: nothing about this fix makes the page chattier on
    // its own. The second call below happens only because a user asks.
    expect(fetchMarketPulse).toHaveBeenCalledTimes(1);
  });

  it("re-issues the same call on retry and resolves into the real panel", async () => {
    fetchMarketPulse.mockRejectedValueOnce(new Error(SERVER_MESSAGE));
    fetchMarketPulse.mockResolvedValueOnce(FIXTURE);
    render(<MarketPulse />);

    const retry = await screen.findByTestId("market-pulse-retry");
    fireEvent.click(retry);

    await waitFor(() => expect(fetchMarketPulse).toHaveBeenCalledTimes(2));
    // Same call, no arguments smuggled in on the retry path.
    expect(fetchMarketPulse.mock.calls[1]).toEqual([]);

    // The affordance is real: the panel actually arrives.
    await screen.findByTestId("market-pulse");
    expect(screen.queryByTestId("market-pulse-error")).toBeNull();
  });

  it("shows the new failure verbatim when a retry fails again", async () => {
    const second = "503 Service Unavailable — /analytics/market-pulse";
    fetchMarketPulse.mockRejectedValueOnce(new Error(SERVER_MESSAGE));
    fetchMarketPulse.mockRejectedValueOnce(new Error(second));
    render(<MarketPulse />);

    fireEvent.click(await screen.findByTestId("market-pulse-retry"));

    await waitFor(() =>
      expect(screen.getByTestId("market-pulse-error-detail").textContent).toBe(second),
    );
  });
});
