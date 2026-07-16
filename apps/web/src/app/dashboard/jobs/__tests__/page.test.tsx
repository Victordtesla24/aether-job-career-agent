// @vitest-environment jsdom
/**
 * GAP-P6-WIRE-001 regression guard (Cluster B, /dashboard/jobs).
 *
 * probe-06-interactions.json flagged the "Australia (Local)", "International"
 * and "Saved" market tabs as RENDERED-BUT-NO-EFFECT. This test renders the
 * real JobsPage against a fixture list spanning all three partitions and
 * drives each tab, asserting the visible job list actually re-partitions —
 * catching a regression that silently disconnects a tab's onClick from the
 * rendered market filter.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
const getToken = vi.fn();
const apiBaseUrl = vi.fn();
const fetchScoutSources = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
  apiBaseUrl: () => apiBaseUrl(),
  getToken: () => getToken(),
}));

vi.mock("../../../../lib/api/jobs", () => ({
  fetchScoutSources: (...args: unknown[]) => fetchScoutSources(...args),
}));

// eslint-disable-next-line import/first
import JobsPage from "../page";

const AU_JOB = {
  id: "job-au",
  title: "AU Product Manager",
  company: "Sydney Co",
  location: "Sydney NSW",
  remote: false,
  description: "",
  source: "seek",
  sourceUrl: "https://seek.com.au/job/1",
  status: "matched",
  fitScore: 82,
  saved: false,
  createdAt: "2026-07-15T00:00:00Z",
};

const INTL_JOB = {
  id: "job-intl",
  title: "US Program Manager",
  company: "SF Co",
  location: "San Francisco, CA",
  remote: true,
  description: "",
  source: "linkedin",
  sourceUrl: "https://linkedin.com/jobs/2",
  status: "matched",
  fitScore: 74,
  saved: false,
  createdAt: "2026-07-15T00:00:00Z",
};

const SAVED_JOB = {
  id: "job-saved",
  title: "Saved Business Analyst",
  company: "Remote Co",
  location: "Remote",
  remote: true,
  description: "",
  source: "greenhouse",
  sourceUrl: "https://greenhouse.io/job/3",
  status: "matched",
  fitScore: 90,
  saved: true,
  createdAt: "2026-07-15T00:00:00Z",
};

const JOBS_FIXTURE = [AU_JOB, INTL_JOB, SAVED_JOB];

function insightsFor(jobId: string) {
  return {
    jobId,
    scored: true,
    overall: 80,
    keywordMatch: 80,
    semantic: 80,
    experience: 80,
    skillsMatched: 4,
    skillsTotal: 5,
    matchedSkills: ["TypeScript"],
    missingSkills: ["Kubernetes"],
    skillGap: "Kubernetes",
    narrative: "Strong match.",
    dimensions: [],
    riskSignals: [],
    isAustralia: jobId === AU_JOB.id,
  };
}

apiRequest.mockImplementation(async (path: string) => {
  if (path.startsWith("/jobs?")) return JOBS_FIXTURE;
  const insightsMatch = /^\/jobs\/([^/]+)\/insights$/.exec(path);
  if (insightsMatch) return insightsFor(insightsMatch[1]);
  if (path === "/agents") return [{ name: "scout", last_run: "2026-07-16T00:00:00Z" }];
  throw new Error(`unexpected apiRequest(${path})`);
});
getToken.mockResolvedValue("test-token");
apiBaseUrl.mockReturnValue("http://test.local");
fetchScoutSources.mockResolvedValue([]);

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
});

describe("Job Discovery market tabs (GAP-P6-WIRE-001)", () => {
  it("Australia / International / Saved each re-partition the visible list", async () => {
    render(<JobsPage />);

    // Default tab is Australia — only the AU-located job is visible (it
    // renders twice: once in the list card, once in the detail panel).
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));
    expect(screen.queryAllByText("US Program Manager")).toHaveLength(0);
    expect(screen.queryAllByText("Saved Business Analyst")).toHaveLength(0);
    expect(screen.getByTestId("market-tab-au").getAttribute("aria-selected")).toBe("true");

    // International — the AU job drops out, the US job appears.
    fireEvent.click(screen.getByTestId("market-tab-intl"));
    expect(screen.getByTestId("market-tab-intl").getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(screen.queryAllByText("AU Product Manager")).toHaveLength(0));
    expect(screen.getAllByText("US Program Manager").length).toBeGreaterThan(0);

    // Saved — switches to the dedicated saved-jobs view with only the
    // bookmarked job, regardless of its location.
    fireEvent.click(screen.getByTestId("market-tab-saved"));
    expect(screen.getByTestId("market-tab-saved").getAttribute("aria-selected")).toBe("true");
    await screen.findByTestId("saved-view");
    expect(screen.getAllByText("Saved Business Analyst").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("US Program Manager")).toHaveLength(0);

    // Back to Australia — round-trips cleanly.
    fireEvent.click(screen.getByTestId("market-tab-au"));
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("saved-view")).toBeNull();
  });
});
