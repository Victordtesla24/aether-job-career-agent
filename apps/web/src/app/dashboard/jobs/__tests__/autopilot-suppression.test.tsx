// @vitest-environment jsdom
/**
 * ML-W25 (QA #4 residual) — "autopilot goes quiet ~24h with no in-app
 * explanation". The board-sweep autopilot's cover-failure backoff
 * (RT-007/ML-W19) now surfaces per-job as `job.autopilotSuppressedUntil`
 * (nullable ISO timestamp, wired in apps/api/app/repositories/job.py). This
 * renders the honest, muted hint on both the job card and the detail panel
 * when suppressed, and renders NOTHING when null — this is the fail-
 * before/pass-after render test for both states.
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
}));

vi.mock("../../../../lib/api/jobs", () => ({
  fetchScoutSources: (...args: unknown[]) => fetchScoutSources(...args),
  fetchSourceAvailability: (...args: unknown[]) => fetchSourceAvailability(...args),
}));

// eslint-disable-next-line import/first
import JobsPage from "../page";

const SUPPRESSED_JOB = {
  id: "job-suppressed",
  title: "Suppressed Program Manager",
  company: "Wedged Co",
  location: "Sydney NSW",
  remote: false,
  description: "",
  source: "greenhouse",
  sourceUrl: "https://greenhouse.io/job/suppressed",
  status: "screening",
  fitScore: 80,
  saved: false,
  createdAt: "2026-07-29T00:00:00Z",
  autopilotSuppressedUntil: "2026-07-30T19:25:00Z",
};

const CLEAN_JOB = {
  id: "job-clean",
  title: "Clean Delivery Lead",
  company: "Healthy Co",
  location: "Melbourne VIC",
  remote: false,
  description: "",
  source: "lever",
  sourceUrl: "https://lever.co/job/clean",
  status: "screening",
  fitScore: 85,
  saved: false,
  createdAt: "2026-07-29T00:00:00Z",
  autopilotSuppressedUntil: null,
};

const JOBS_FIXTURE = [SUPPRESSED_JOB, CLEAN_JOB];

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
    matchedSkills: [],
    missingSkills: [],
    skillGap: null,
    narrative: "Strong match.",
    dimensions: [],
    riskSignals: [],
    isAustralia: true,
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
fetchSourceAvailability.mockResolvedValue([
  { source: "greenhouse", available: true, reason: null },
  { source: "lever", available: true, reason: null },
]);

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
});

describe("Autopilot suppression visibility (ML-W25, QA #4 residual)", () => {
  it("renders the honest paused hint on the card AND detail panel for a suppressed job", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("Suppressed Program Manager").length).toBeGreaterThan(0));

    // Card hint (list column).
    const cardHint = screen.getByTestId("autopilot-suppressed-hint");
    expect(cardHint.textContent).toContain("Autopilot paused for this job until");
    expect(cardHint.textContent).toContain("recent generation attempts couldn't produce a letter");

    // The suppressed job is the first visible AU job, so it is auto-selected
    // into the detail panel — the SAME honest copy must appear there too.
    await waitFor(() => {
      const detailHint = screen.getByTestId("autopilot-suppressed-hint-detail");
      expect(detailHint.textContent).toContain("Autopilot paused for this job until");
    });
  });

  it("renders NOTHING for a clean (non-suppressed) job", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("Clean Delivery Lead").length).toBeGreaterThan(0));

    // Only ONE card hint exists in the whole tree (the suppressed job's) —
    // the clean job's card must carry no hint element at all.
    const cardHints = screen.getAllByTestId("autopilot-suppressed-hint");
    expect(cardHints).toHaveLength(1);

    // Selecting the clean job's detail must show no detail hint.
    const cleanTitleButton = screen.getByRole("button", {
      name: /Clean Delivery Lead at Healthy Co, view details/i,
    });
    cleanTitleButton.click();

    await waitFor(() => expect(screen.getAllByText("Clean Delivery Lead").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("autopilot-suppressed-hint-detail")).toBeNull();
  });
});
