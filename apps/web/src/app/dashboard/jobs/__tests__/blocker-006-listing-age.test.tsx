// @vitest-environment jsdom
/**
 * BLOCKER-006 — the job board must never lie about a listing's age, and must
 * never present an empty board as an empty account.
 *
 * The active feed no longer hides a listing for being old: an ATS board API
 * publishes only roles that are still open, so a role advertised 187 days ago
 * and returned by that board seconds ago is fully applicable (production
 * evidence in apps/api/tests/test_blocker_006_empty_feed.py). Showing those
 * roles is only honest if the card states how old the advertisement is —
 * previously the card rendered `timeAgo(job.createdAt)`, the date WE first
 * saw the row, unlabelled, so a 187-day-old listing read "11d ago".
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
  // MON-020: the page renders API failures through the shared friendly-error
  // helper (which strips a proxy's raw HTML error page). Pass-through here —
  // that helper has its own dedicated tests in lib/api/__tests__.
  describeApiError: (e: unknown, fallback: string) =>
    e instanceof Error ? e.message : fallback,
}));

vi.mock("../../../../lib/api/jobs", () => ({
  fetchScoutSources: (...args: unknown[]) => fetchScoutSources(...args),
  fetchSourceAvailability: (...args: unknown[]) => fetchSourceAvailability(...args),
}));

// eslint-disable-next-line import/first
import JobsPage from "../page";

/** Discovered 11 days ago, advertised 187 days ago, board-confirmed today. */
const OLD_BUT_LIVE = {
  id: "job-old-live",
  title: "GTM Technology Product Owner",
  company: "Harvey",
  location: "Sydney NSW",
  remote: false,
  description: "",
  source: "ashby",
  sourceUrl: "https://jobs.ashbyhq.com/harvey/gtm",
  status: "screening",
  fitScore: 82,
  saved: false,
  postedAt: "2026-01-26T19:00:46Z",
  createdAt: "2026-07-21T01:14:33Z",
  postedAgeDays: 187,
  lastConfirmedAt: "2026-08-01T21:31:32Z",
  autopilotSuppressedUntil: null,
};

/** No posting date on record — the age must read as unknown, not invented. */
const UNKNOWN_AGE = {
  ...OLD_BUT_LIVE,
  id: "job-unknown-age",
  title: "Delivery Manager",
  company: "Acme",
  sourceUrl: "https://lever.co/acme/dm",
  source: "lever",
  postedAt: null,
  postedAgeDays: null,
};

function insightsFor(jobId: string) {
  return {
    jobId, scored: true, overall: 80, keywordMatch: 80, semantic: 80,
    experience: 80, skillsMatched: 4, skillsTotal: 5, matchedSkills: [],
    missingSkills: [], skillGap: null, narrative: "Strong match.",
    dimensions: [], riskSignals: [], isAustralia: true,
  };
}

function mockApi(feed: unknown[], history: unknown[] = feed) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/jobs?include_stale=true") return history;
    if (path.startsWith("/jobs?")) return feed;
    const m = /^\/jobs\/([^/]+)\/insights$/.exec(path);
    if (m) return insightsFor(m[1]);
    if (path === "/agents") return [{ name: "scout", last_run: "2026-07-16T00:00:00Z" }];
    throw new Error(`unexpected apiRequest(${path})`);
  });
}

getToken.mockResolvedValue("test-token");
apiBaseUrl.mockReturnValue("http://test.local");
fetchScoutSources.mockResolvedValue([]);
fetchSourceAvailability.mockResolvedValue([
  { source: "ashby", available: true, reason: null },
  { source: "lever", available: true, reason: null },
]);

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("BLOCKER-006 — honest listing age on the job board", () => {
  it("states the ADVERTISEMENT's age, not the date we discovered the row", async () => {
    mockApi([OLD_BUT_LIVE]);
    render(<JobsPage />);
    await waitFor(() =>
      expect(screen.getAllByText("GTM Technology Product Owner").length).toBeGreaterThan(0),
    );

    const age = screen.getAllByTestId("job-listing-age")[0];
    expect(age.textContent).toBe("Posted 187 days ago");
    // The discovery date must never stand in for the posting date: this
    // listing was discovered 11 days ago and used to render "11d ago".
    expect(age.textContent).not.toContain("11d");
  });

  it("says which date it is showing when the posting date is unknown", async () => {
    mockApi([UNKNOWN_AGE]);
    render(<JobsPage />);
    await waitFor(() =>
      expect(screen.getAllByText("Delivery Manager").length).toBeGreaterThan(0),
    );

    const age = screen.getAllByTestId("job-listing-age")[0];
    expect(age.textContent).toMatch(/^Found /);
    expect(age.textContent).not.toMatch(/^Posted /);
  });

  it("explains an empty board when rows exist in history", async () => {
    mockApi([], [OLD_BUT_LIVE, UNKNOWN_AGE]);
    render(<JobsPage />);

    await waitFor(() => {
      const empty = screen.getByTestId("jobs-empty-state");
      expect(empty.textContent).toContain("None of your 2 saved roles");
    });
    expect(screen.getByTestId("jobs-empty-history-link").textContent).toContain(
      "View all 2",
    );
  });

  it("still tells a genuinely new user to sync", async () => {
    mockApi([], []);
    render(<JobsPage />);

    await waitFor(() => {
      const empty = screen.getByTestId("jobs-empty-state");
      expect(empty.textContent).toContain("Run Sync");
    });
    expect(screen.queryByTestId("jobs-empty-history-link")).toBeNull();
  });
});
