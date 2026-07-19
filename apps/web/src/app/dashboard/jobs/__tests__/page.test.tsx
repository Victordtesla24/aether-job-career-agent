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

// Two AU-located jobs with real salary data, used by the Role/Salary filter
// tests (MV-job-discovery-004) — one below and one at/above a $150k band.
const BACKEND_JOB = {
  id: "job-backend",
  title: "Backend Engineer",
  company: "DataCo",
  location: "Sydney NSW",
  remote: false,
  description: "",
  source: "greenhouse",
  sourceUrl: "https://greenhouse.io/job/4",
  status: "matched",
  fitScore: 70,
  saved: false,
  createdAt: "2026-07-15T00:00:00Z",
  salaryMin: 90000,
  salaryMax: 110000,
  currency: "AUD",
};

const SENIOR_BACKEND_JOB = {
  id: "job-senior-backend",
  title: "Senior Backend Engineer",
  company: "CloudCo",
  location: "Melbourne VIC",
  remote: false,
  description: "",
  source: "lever",
  sourceUrl: "https://lever.co/job/5",
  status: "matched",
  fitScore: 88,
  saved: false,
  createdAt: "2026-07-15T00:00:00Z",
  salaryMin: 150000,
  salaryMax: 180000,
  currency: "AUD",
};

const JOBS_FIXTURE = [AU_JOB, INTL_JOB, SAVED_JOB, BACKEND_JOB, SENIOR_BACKEND_JOB];

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

apiRequest.mockImplementation(
  async (path: string, options?: { method?: string; body?: unknown }) => {
    if (path.startsWith("/jobs?")) return JOBS_FIXTURE;
    const insightsMatch = /^\/jobs\/([^/]+)\/insights$/.exec(path);
    if (insightsMatch) return insightsFor(insightsMatch[1]);
    if (path === "/agents") return [{ name: "scout", last_run: "2026-07-16T00:00:00Z" }];
    const applyMatch = /^\/jobs\/([^/]+)\/apply$/.exec(path);
    if (applyMatch && options?.method === "POST") {
      const job = JOBS_FIXTURE.find((j) => j.id === applyMatch[1]);
      return { job: { ...job, status: "applied" } };
    }
    if (path === "/agents/tailor/run" && options?.method === "POST") {
      // 1 applied / 7 rejected — mirrors the real run observed in
      // TESTING-OUTCOME-REPORT.md (MV-job-discovery-005).
      return { resume_id: "resume-mock-1", changes: 1, rejected: ["b1", "b2", "b3", "b4", "b5", "b6", "b7"] };
    }
    throw new Error(`unexpected apiRequest(${path})`);
  },
);
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

describe("Bulk apply confirmation gate (MV-job-discovery-002)", () => {
  it("opens a confirmation dialog before applying, and does NOT apply on cancel", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByLabelText("Select AU Product Manager"));
    expect(screen.getByTestId("selected-count").textContent).toContain("1 selected");

    fireEvent.click(screen.getByTestId("bulk-apply"));

    // The gate must appear, and apply must NOT have fired yet.
    await screen.findByTestId("bulk-apply-gate");
    expect(apiRequest).not.toHaveBeenCalledWith(
      "/jobs/job-au/apply",
      expect.objectContaining({ method: "POST" }),
    );

    // Cancel closes the gate without ever applying.
    fireEvent.click(screen.getByTestId("bulk-apply-cancel"));
    await waitFor(() => expect(screen.queryByTestId("bulk-apply-gate")).toBeNull());
    expect(apiRequest).not.toHaveBeenCalledWith(
      "/jobs/job-au/apply",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("applies only after explicit confirmation", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByLabelText("Select AU Product Manager"));
    fireEvent.click(screen.getByTestId("bulk-apply"));
    await screen.findByTestId("bulk-apply-gate");

    // The dialog discloses which job(s) and that tailoring will not run.
    expect(screen.getByTestId("bulk-apply-gate-list").textContent).toContain("AU Product Manager");
    expect(screen.getByRole("dialog").textContent?.toLowerCase()).toContain("untailored");

    fireEvent.click(screen.getByTestId("bulk-apply-confirm"));

    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith(
        "/jobs/job-au/apply",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("routes the Saved view's Apply-to-all through the same confirmation gate", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByTestId("market-tab-saved"));
    await screen.findByTestId("saved-view");

    fireEvent.click(screen.getByTestId("saved-apply-all"));

    await screen.findByTestId("bulk-apply-gate");
    expect(apiRequest).not.toHaveBeenCalledWith(
      "/jobs/job-saved/apply",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("Role and Salary filters (MV-job-discovery-004)", () => {
  it("Role filter narrows the visible list by job title", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Backend Engineer").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Senior Backend Engineer").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByTestId("job-role-filter"), { target: { value: "Engineer" } });

    await waitFor(() => expect(screen.queryAllByText("AU Product Manager")).toHaveLength(0));
    expect(screen.getAllByText("Backend Engineer").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Senior Backend Engineer").length).toBeGreaterThan(0);
  });

  it("Salary filter narrows the visible list by minimum salary band", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("Senior Backend Engineer").length).toBeGreaterThan(0));

    fireEvent.change(screen.getByTestId("job-salary-filter"), { target: { value: "150" } });

    // Job with no salary data and job below the $150k band both drop out;
    // the job whose band clears $150k remains.
    await waitFor(() => expect(screen.queryAllByText("AU Product Manager")).toHaveLength(0));
    expect(screen.queryAllByText("Backend Engineer")).toHaveLength(0);
    expect(screen.getAllByText("Senior Backend Engineer").length).toBeGreaterThan(0);
  });

  it("Clear all resets Role and Salary filters", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    fireEvent.change(screen.getByTestId("job-role-filter"), { target: { value: "Engineer" } });
    fireEvent.change(screen.getByTestId("job-salary-filter"), { target: { value: "150" } });
    await waitFor(() => expect(screen.queryAllByText("AU Product Manager")).toHaveLength(0));

    fireEvent.click(screen.getByTestId("clear-filters"));

    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));
    expect((screen.getByTestId("job-role-filter") as HTMLInputElement).value).toBe("");
    expect((screen.getByTestId("job-salary-filter") as HTMLSelectElement).value).toBe("0");
  });
});

describe("Tailoring honesty note (MV-job-discovery-005)", () => {
  it("explains why most proposed edits were rejected when few are applied", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByTestId("tailor-resume"));
    await screen.findByTestId("apply-step2");

    const note = screen.getByTestId("tailor-rejected-note").textContent ?? "";
    expect(note).toMatch(/1 of 8/);
    expect(note.toLowerCase()).toMatch(/unsupported/);
  });
});

describe("Jobs-board no-op honesty (MV-adv-A-002)", () => {
  it("surfaces a full-rejection tailor no-op as an informational notice, never a red error with a leaked exception-class name", async () => {
    apiRequest.mockImplementation(
      async (path: string, options?: { method?: string; body?: unknown }) => {
        if (path.startsWith("/jobs?")) return JOBS_FIXTURE;
        const insightsMatch = /^\/jobs\/([^/]+)\/insights$/.exec(path);
        if (insightsMatch) return insightsFor(insightsMatch[1]);
        if (path === "/agents") return [{ name: "scout", last_run: "2026-07-16T00:00:00Z" }];
        if (path === "/agents/tailor/run" && options?.method === "POST") {
          // The honest no-op body BOTH the synchronous /tailor/run route and
          // (post MV-adv-A-002 fix) the async worker's completed
          // BackgroundJob result return — never a thrown "NoChangesApplied:
          // ..." error (MV-resume-studio-003 parity).
          return {
            resume_id: null,
            changes: 0,
            rejected: ["b1", "b2"],
            conversionMetrics: null,
            noChangesApplied: true,
            approvalRequired: false,
            message:
              "No verifiable changes could be applied — every suggested edit was unsupported by your evidence, so your résumé is unchanged and you were not charged.",
          };
        }
        throw new Error(`unexpected apiRequest(${path})`);
      },
    );

    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByTestId("tailor-resume"));

    const notice = await screen.findByTestId("tailor-notice");
    expect(notice.textContent?.toLowerCase()).toContain("no verifiable changes");
    // NEVER the raw Python exception-class prefix a user should never see.
    expect(notice.textContent?.toLowerCase()).not.toContain("nochangesapplied");

    // Never the red error banner, and never a fabricated "tailored" success
    // state (0 changes is not a success worth a green checkmark) — the flow
    // resets to "idle" so the user can retry, exactly like Resume Studio.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("apply-step2")).toBeNull();
    expect(screen.getByTestId("tailor-resume")).not.toBeNull();
  });
});
