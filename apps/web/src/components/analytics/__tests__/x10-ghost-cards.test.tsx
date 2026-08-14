// @vitest-environment jsdom
/**
 * X-10 (P1) — "3 empty ghost cards at the bottom of Dashboard + Analytics,
 * desktop AND mobile".
 *
 * ROOT CAUSE, MEASURED (not inferred). `<MarketPulse>` is the last element on
 * both `/dashboard` (page.tsx) and `/dashboard/analytics` (page.tsx). Its
 * loading branch rendered three bare boxes:
 *
 *     <div className="grid gap-4 xl:grid-cols-3" data-testid="market-pulse-skeleton">
 *       {[0,1,2].map(i => <div className="glass h-56 animate-pulse rounded-2xl border border-white/10" />)}
 *
 * — no heading, no label, no structure. A live probe against production
 * (`uat/reports/evidence/market-perf/s-ui/b1/before/before-notes.json`) found
 * that skeleton still mounted at 1s, 2s, 4s and 8s after navigation and gone by
 * 15s, on BOTH pages: `GET /api/analytics/market-pulse` takes 8–15s, so those
 * three unlabelled boxes are the state a user sees FIRST, for many seconds.
 * That is why the audit caught it on four separate screenshots and why it is a
 * real defect rather than a capture artifact.
 *
 * THE RULE IT BREAKS: doctrine D-θ ("the empty state is designed") and
 * reference-pack rule 7 ("empty states are shown honestly, not hidden"). An
 * unlabelled card is an implicit claim that content exists there.
 *
 * THE FIX UNDER TEST: the loading state says what it is loading, in words, at
 * the geometry of the real content — so it can never be mistaken for an empty
 * card, and never silently claims content that has not arrived.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMarketPulseMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/workspaces", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/workspaces")>();
  return { ...actual, fetchMarketPulse: (...args: unknown[]) => fetchMarketPulseMock(...args) };
});

// eslint-disable-next-line import/first
import MarketPulse from "../MarketPulse";

beforeEach(() => {
  // The real prod condition: the request is in flight for a long time.
  fetchMarketPulseMock.mockReturnValue(new Promise(() => {}));
});

afterEach(() => {
  cleanup();
  fetchMarketPulseMock.mockReset();
});

describe("X-10 — the market-pulse loading state is never a ghost card", () => {
  it("names what it is loading, so a bordered box is never mistaken for empty content", async () => {
    render(<MarketPulse />);

    const skeleton = await screen.findByTestId("market-pulse-skeleton");
    // The defect, expressed as a test: the loading region carried no text at
    // all. Three bordered boxes with zero characters in them is exactly what
    // an empty card looks like.
    expect(skeleton.textContent?.trim().length ?? 0).toBeGreaterThan(0);
    expect(skeleton.textContent).toMatch(/market pulse/i);
    expect(skeleton.textContent?.toLowerCase()).toMatch(/loading|fetching/);
  });

  it("announces itself to assistive tech as busy, with a name", async () => {
    render(<MarketPulse />);
    const skeleton = await screen.findByTestId("market-pulse-skeleton");

    expect(skeleton.getAttribute("aria-busy")).toBe("true");
    // `aria-busy` on an anonymous region tells a screen-reader user that
    // something is happening but not what.
    const label =
      skeleton.getAttribute("aria-label") ?? skeleton.getAttribute("aria-labelledby");
    expect(label).toBeTruthy();
  });

  it("still resolves to the real panel once the slow request lands", async () => {
    // Guards the fix against the other failure mode: a skeleton so elaborate it
    // stops being a skeleton. The component must still swap to real content.
    fetchMarketPulseMock.mockResolvedValue({
      sources: [],
      sourcesTotal: 0,
      sourcesLabel: "0 jobs",
      topSkills: [],
      activityHeatmap: [],
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
    });

    render(<MarketPulse />);
    await screen.findByTestId("market-pulse");
    await waitFor(() => expect(screen.queryByTestId("market-pulse-skeleton")).toBeNull());
  });
});
