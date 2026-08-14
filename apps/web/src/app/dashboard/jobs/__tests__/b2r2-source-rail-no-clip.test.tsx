// @vitest-environment jsdom
/**
 * S-UI B2 ROUND 2, judge item 1 (closes OBS-B2-02) — the Connected Job Boards
 * rail must not clip a board card at its column edge.
 *
 * B2's two-pane restructuring narrowed this band into the ~640px list column,
 * and the rail was a `flex … overflow-x-auto` strip of `w-[172px] shrink-0`
 * cards. Four cards plus their gaps no longer fit, so at 1600 the 4th board was
 * sliced mid-word ("smar… 486 li… discove") and at 834 the 5th was a bare
 * fragment — with no fade, chevron or "+N more" chip to say the row continued.
 * Reachable by keyboard, but it read as unfinished on the flagship page's
 * above-the-fold band.
 *
 * jsdom has no layout engine, so this cannot assert rendered pixels — the
 * pixel proof is the fresh crop in the B2 round-2 evidence. What it CAN assert,
 * and what actually regressed, is the containing structure:
 *   1. every connected board renders (nothing is dropped to make room);
 *   2. the rail is a wrapping grid, not a horizontally-scrolling strip — the
 *      geometry that produced the clip is gone;
 *   3. no card is pinned to a fixed width it cannot shrink out of;
 *   4. nothing advertises a scroll that no longer exists (the old
 *      `role="region"` + tabIndex + "(scrollable)" label would now be a lie to
 *      a screen-reader user);
 *   5. the source counts and the sync-note copy are still there, verbatim.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
const getToken = vi.fn();
const apiBaseUrl = vi.fn();
const fetchScoutSources = vi.fn();
const fetchSourceAvailability = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
  apiBaseUrl: () => apiBaseUrl(),
  getToken: () => getToken(),
  ApiError: class ApiError extends Error {},
  describeApiError: (e: unknown, fallback: string) =>
    e instanceof Error ? e.message : fallback,
}));

vi.mock("../../../../lib/api/jobs", () => ({
  fetchScoutSources: (...args: unknown[]) => fetchScoutSources(...args),
  fetchSourceAvailability: (...args: unknown[]) => fetchSourceAvailability(...args),
}));

// eslint-disable-next-line import/first
import JobsPage from "../page";

/**
 * The six sources actually present in the production capture the judge cropped
 * (adzuna / Greenhouse / ashby / smartrecruiters / remotive + one more), which
 * is the count that overflowed the column.
 */
const SOURCES = ["adzuna", "greenhouse", "ashby", "smartrecruiters", "remotive", "lever"];

function job(source: string, i: number) {
  return {
    id: `job-${source}-${i}`,
    title: `Role ${i}`,
    company: `Co ${i}`,
    location: "Sydney NSW",
    remote: false,
    description: "",
    source,
    sourceUrl: `https://example.test/${source}/${i}`,
    status: "screening",
    fitScore: 80,
    saved: false,
    postedAt: "2026-08-01T00:00:00Z",
    createdAt: "2026-08-10T00:00:00Z",
    postedAgeDays: 9,
    lastConfirmedAt: "2026-08-13T00:00:00Z",
    autopilotSuppressedUntil: null,
  };
}

/** One job per source, so `sourceCards` has exactly one card per board. */
const JOBS = SOURCES.map((s, i) => job(s, i));

getToken.mockResolvedValue("test-token");
apiBaseUrl.mockReturnValue("http://test.local");
fetchSourceAvailability.mockResolvedValue(
  SOURCES.map((source) => ({ source, available: true, reason: null })),
);
fetchScoutSources.mockResolvedValue([]);

function mockApi() {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/agents") return [{ name: "scout", last_run: "2026-08-14T01:00:00Z" }];
    if (path.startsWith("/jobs")) return JOBS;
    return [];
  });
}

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("Connected Job Boards rail — no card is clipped at the column edge", () => {
  it("renders one fully-present card per connected board", async () => {
    mockApi();
    render(<JobsPage />);

    const grid = await waitFor(() => screen.getByTestId("source-card-grid"));
    // Every board is in the DOM in full — no board is dropped, and no board is
    // reachable only by scrolling a strip sideways.
    expect(grid.children.length).toBe(SOURCES.length);
    for (const source of SOURCES) {
      // Label OR raw source id (the page falls back to the id for boards not in
      // SOURCE_LABEL — e.g. "ashby", "smartrecruiters"), and the honest count
      // line beside it.
      expect(grid.textContent?.toLowerCase()).toContain(source.slice(0, 6));
    }
    expect(within(grid).getAllByText(/live jobs? discovered/).length).toBe(SOURCES.length);
  });

  it("wraps instead of scrolling sideways, and pins no card to a fixed width", async () => {
    mockApi();
    render(<JobsPage />);

    const grid = await waitFor(() => screen.getByTestId("source-card-grid"));
    // The geometry that produced the clip: a horizontal scroller of fixed-width
    // non-shrinking cards. Both halves must be gone.
    expect(grid.className).toMatch(/\bgrid\b/);
    expect(grid.className).not.toMatch(/overflow-x-auto|overflow-x-scroll/);
    for (const card of Array.from(grid.children)) {
      expect(card.className).not.toMatch(/\bw-\[\d+px\]/);
      expect(card.className).not.toMatch(/\bshrink-0\b/);
    }
  });

  it("no longer claims a scroll affordance the rail does not have", async () => {
    mockApi();
    render(<JobsPage />);

    await waitFor(() => screen.getByTestId("source-card-grid"));
    // The old container announced itself as a scrollable region and took a tab
    // stop. With nothing to scroll, both would mislead.
    expect(screen.queryByLabelText(/Connected job board cards \(scrollable\)/)).toBeNull();
    const bar = screen.getByTestId("source-bar");
    expect(bar.querySelector('[tabindex="0"]')).toBeNull();
    // The section itself still names the region for assistive tech.
    expect(bar.getAttribute("aria-label")).toBe("Connected job boards");
  });

  it("keeps the sync note copy verbatim, now attached as a caption", async () => {
    mockApi();
    render(<JobsPage />);

    const bar = await waitFor(() => screen.getByTestId("source-bar"));
    expect(bar.textContent).toContain(
      "Counts reflect live discovered jobs per source — run Sync Now to refresh from all connected boards",
    );
  });
});
