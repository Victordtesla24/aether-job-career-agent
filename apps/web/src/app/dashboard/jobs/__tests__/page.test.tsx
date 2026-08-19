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
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

/**
 * The shared default mock body — factored out (rather than inlined only at
 * module load) so any describe block can restore it in a `beforeEach`. Tests
 * further down the file (e.g. MV-adv-A-002) install a narrower, test-local
 * `mockImplementation` and `apiRequest.mockClear()` in the top-level
 * `afterEach` does NOT reset that override — only restoring THIS function
 * puts the mock back to its full-endpoint default for tests appended later
 * in file order.
 */
async function defaultApiRequestImpl(path: string, options?: { method?: string; body?: unknown }) {
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
}

apiRequest.mockImplementation(defaultApiRequestImpl);
getToken.mockResolvedValue("test-token");
apiBaseUrl.mockReturnValue("http://test.local");
fetchScoutSources.mockResolvedValue([]);

/** Default backend availability: full adapter registry (live + gated +
 * fixture-only). Individual tests override this to prove the FE is
 * backend-driven, not hardcoded (ML-audit-seek-fe-hardcode-001). */
const DEFAULT_AVAILABILITY = [
  { source: "adzuna", available: true, reason: null },
  { source: "ashby", available: true, reason: null },
  { source: "greenhouse", available: true, reason: null },
  { source: "indeed", available: false, reason: "no live discovery implementation (fixture-only legacy adapter)" },
  { source: "lever", available: true, reason: null },
  { source: "linkedin", available: false, reason: "no live discovery implementation (fixture-only legacy adapter)" },
  { source: "remoteok", available: true, reason: null },
  { source: "remotive", available: true, reason: null },
  { source: "seek", available: false, reason: "compliance-gated (ADR-P6-SEEK): ToS-prohibited scraping; enable only via AETHER_ENABLE_SEEK" },
  { source: "smartrecruiters", available: true, reason: null },
  { source: "wellfound", available: true, reason: null },
  { source: "workable", available: true, reason: null },
];
fetchSourceAvailability.mockResolvedValue(DEFAULT_AVAILABILITY);

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
  fetchSourceAvailability.mockClear();
  fetchSourceAvailability.mockResolvedValue(DEFAULT_AVAILABILITY);
});

function sourceOption(name: string): HTMLOptionElement {
  const select = screen.getByTestId("job-source-filter") as HTMLSelectElement;
  const option = Array.from(select.options).find((o) => o.value === name);
  if (!option) throw new Error(`option '${name}' not found`);
  return option;
}

describe("Backend-driven source availability (ML-audit-seek-fe-hardcode-001)", () => {
  it("disables and labels sources the BACKEND reports unavailable", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    // The FE must actually consult the backend availability endpoint —
    // hardcoded availability is the exact defect this row closes.
    await waitFor(() => expect(fetchSourceAvailability).toHaveBeenCalled());

    await waitFor(() => {
      for (const src of ["seek", "linkedin", "indeed"]) {
        const option = sourceOption(src);
        expect(option.disabled).toBe(true);
        expect(option.textContent).toContain("(unavailable)");
      }
    });
    for (const src of ["greenhouse", "lever", "remotive", "remoteok", "ashby", "adzuna"]) {
      const option = sourceOption(src);
      expect(option.disabled).toBe(false);
      expect(option.textContent).not.toContain("(unavailable)");
    }
  });

  it("lists every registry board including ashby/adzuna and never invents jora/workforce", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));
    await waitFor(() => expect(fetchSourceAvailability).toHaveBeenCalled());

    await waitFor(() => {
      expect(sourceOption("ashby")).toBeTruthy();
      expect(sourceOption("adzuna")).toBeTruthy();
      expect(sourceOption("smartrecruiters")).toBeTruthy();
      expect(sourceOption("workable")).toBeTruthy();
      expect(sourceOption("wellfound")).toBeTruthy();
    });

    const select = screen.getByTestId("job-source-filter") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).not.toContain("jora");
    expect(values).not.toContain("workforce");
  });

  it("re-enables seek when the backend reports it available (env gate ON)", async () => {
    fetchSourceAvailability.mockResolvedValue(
      DEFAULT_AVAILABILITY.map((row) =>
        row.source === "seek" ? { source: "seek", available: true, reason: null } : row,
      ),
    );

    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    await waitFor(() => {
      const option = sourceOption("seek");
      expect(option.disabled).toBe(false);
      expect(option.textContent).not.toContain("(unavailable)");
    });
    // Fixture-only sources stay honestly disabled.
    expect(sourceOption("linkedin").disabled).toBe(true);
  });

  it("degrades honestly when the availability fetch fails: options stay enabled, the backend's 422 remains the truth-teller", async () => {
    fetchSourceAvailability.mockRejectedValue(new Error("network down"));

    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));
    await waitFor(() => expect(fetchSourceAvailability).toHaveBeenCalled());

    // Unknown availability must NOT be presented as a made-up "(unavailable)"
    // label — leave options selectable; a filter on a dead source then gets
    // the backend's honest 422 instead of a fabricated FE claim.
    for (const src of ["seek", "linkedin", "indeed", "greenhouse"]) {
      const option = sourceOption(src);
      expect(option.disabled).toBe(false);
      expect(option.textContent).not.toContain("(unavailable)");
    }
  });
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

  it("MON-010: the filter-reset button reads 'Clear filters' (not the ambiguous 'Clear all')", async () => {
    // MON-010 (MONITORING-LEDGER.md): a user reported "Clear all" as "not
    // working"; repro found the button IS a correctly-functioning FILTER
    // reset, not a board-clearing action — the label just overstates what it
    // does and reads as ambiguous next to board-level actions elsewhere in
    // the product. Fix: rename the label to say exactly what it does. The
    // testid (clear-filters) and behaviour are unchanged — only the visible
    // copy changes, so this is a pure text assertion.
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    const resetButton = screen.getByTestId("clear-filters");
    expect(resetButton.textContent?.trim()).toBe("Clear filters");
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

describe("Per-card Apply button (GOV-010 / GMV2 §10.2)", () => {
  // MV-adv-A-002 (above) installs a test-local apiRequest.mockImplementation
  // that has no /apply handler and never restores the default — mockClear()
  // in the top-level afterEach only clears call history, not the
  // implementation. Restore the full-endpoint default so these tests are
  // self-contained regardless of file execution order.
  beforeEach(() => {
    apiRequest.mockImplementation(defaultApiRequestImpl);
  });

  /** Locates the list `job-card` (not the detail panel) for a given title. */
  function cardFor(title: string): HTMLElement {
    const match = screen.getAllByText(title)[0];
    const card = match.closest('[data-testid="job-card"]');
    if (!card) throw new Error(`job-card not found for "${title}"`);
    return card as HTMLElement;
  }

  it("renders an Apply button on every job card, alongside the existing source link", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    const cards = screen.getAllByTestId("job-card");
    expect(cards.length).toBeGreaterThan(0);
    for (const card of cards) {
      expect(within(card).getByTestId("job-card-apply")).not.toBeNull();
      // Item 6 — the secondary "View on [source]" link must survive.
      expect(within(card).getByTestId("job-source-link")).not.toBeNull();
    }
  });

  it("opens the SAME confirmation gate the detail panel's Review & Apply uses — no second modal, no apply before confirm", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    fireEvent.click(within(cardFor("AU Product Manager")).getByTestId("job-card-apply"));

    const dialog = await screen.findByTestId("submit-gate");
    expect(dialog.textContent).toContain("AU Product Manager");
    // Un-tailored entry point — the gate must say so honestly rather than
    // always claiming a tailored resume is attached.
    expect(screen.getByTestId("gate-resume-status").textContent).toContain("Current (not tailored)");
    expect(apiRequest).not.toHaveBeenCalledWith(
      "/jobs/job-au/apply",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("cancel never applies", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    fireEvent.click(within(cardFor("AU Product Manager")).getByTestId("job-card-apply"));
    await screen.findByTestId("submit-gate");

    fireEvent.click(screen.getByTestId("submit-cancel"));
    await waitFor(() => expect(screen.queryByTestId("submit-gate")).toBeNull());
    expect(apiRequest).not.toHaveBeenCalledWith(
      "/jobs/job-au/apply",
      expect.objectContaining({ method: "POST" }),
    );
    // No optimistic success from merely opening/cancelling the gate.
    expect(screen.queryByTestId("job-card-applied")).toBeNull();
  });

  it("confirm delegates to the same POST handler, updates the job's applied state, and shows a success toast", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    fireEvent.click(within(cardFor("AU Product Manager")).getByTestId("job-card-apply"));
    await screen.findByTestId("submit-gate");
    fireEvent.click(screen.getByTestId("submit-confirm"));

    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith(
        "/jobs/job-au/apply",
        expect.objectContaining({ method: "POST" }),
      ),
    );

    const toast = await screen.findByTestId("jobs-toast");
    expect(toast.textContent?.toLowerCase()).toContain("applied");

    await waitFor(() =>
      expect(within(cardFor("AU Product Manager")).getByTestId("job-card-applied")).not.toBeNull(),
    );
    expect(within(cardFor("AU Product Manager")).queryByTestId("job-card-apply")).toBeNull();
  });

  it("on apply failure shows an honest inline error and never marks the job applied (no optimistic success)", async () => {
    apiRequest.mockImplementation(
      async (path: string, options?: { method?: string; body?: unknown }) => {
        if (path.startsWith("/jobs?")) return JOBS_FIXTURE;
        const insightsMatch = /^\/jobs\/([^/]+)\/insights$/.exec(path);
        if (insightsMatch) return insightsFor(insightsMatch[1]);
        if (path === "/agents") return [{ name: "scout", last_run: "2026-07-16T00:00:00Z" }];
        if (path === "/jobs/job-au/apply" && options?.method === "POST") {
          throw new Error("Apply failed: upstream source unreachable");
        }
        throw new Error(`unexpected apiRequest(${path})`);
      },
    );

    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));

    fireEvent.click(within(cardFor("AU Product Manager")).getByTestId("job-card-apply"));
    await screen.findByTestId("submit-gate");
    fireEvent.click(screen.getByTestId("submit-confirm"));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Apply failed"));
    expect(within(cardFor("AU Product Manager")).queryByTestId("job-card-applied")).toBeNull();
    expect(within(cardFor("AU Product Manager")).getByTestId("job-card-apply")).not.toBeNull();
  });
});

// U-UI JOBS-HEIGHT-BLOWOUT-MOBILE / JOBS-SCREENSHOT-TIMEOUT-DESKTOP: a real
// account with ~3,800 discovered jobs rendered all of them into the DOM at
// once (2,921 unvirtualized cards), blowing document.body.scrollHeight out
// to ~870x the viewport height. Only the first page of matches is now
// mounted as cards; "Load more" grows the window.
describe("Job list render window (U-UI JOBS-HEIGHT-BLOWOUT-MOBILE)", () => {
  const MANY_JOBS = Array.from({ length: 75 }, (_, i) => ({
    id: `job-many-${i}`,
    title: `AU Job ${i}`,
    company: `Co ${i}`,
    location: "Sydney NSW",
    remote: false,
    description: "",
    source: "greenhouse",
    sourceUrl: `https://greenhouse.io/job/many-${i}`,
    status: "matched",
    fitScore: 80,
    saved: false,
    createdAt: "2026-07-15T00:00:00Z",
  }));

  beforeEach(() => {
    apiRequest.mockImplementation(
      async (path: string) => {
        if (path.startsWith("/jobs?")) return MANY_JOBS;
        const insightsMatch = /^\/jobs\/([^/]+)\/insights$/.exec(path);
        if (insightsMatch) return insightsFor(insightsMatch[1]);
        if (path === "/agents") return [{ name: "scout", last_run: "2026-07-16T00:00:00Z" }];
        throw new Error(`unexpected apiRequest(${path})`);
      },
    );
  });

  afterEach(() => {
    // Restore the shared default so later-defined tests in this file (were
    // any appended after this block) aren't affected by this override.
    apiRequest.mockImplementation(defaultApiRequestImpl);
  });

  it("renders only the first page of matches, not all 75, and offers Load more", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByTestId("job-card").length).toBeGreaterThan(0));

    const cards = screen.getAllByTestId("job-card");
    expect(cards.length).toBe(60);
    const loadMore = screen.getByTestId("jobs-load-more");
    expect(loadMore.textContent).toMatch(/15 remaining/);
  });

  it("grows the render window when Load more is clicked, without re-fetching", async () => {
    render(<JobsPage />);
    await waitFor(() => expect(screen.getAllByTestId("job-card").length).toBe(60));
    apiRequest.mockClear();

    fireEvent.click(screen.getByTestId("jobs-load-more"));

    await waitFor(() => expect(screen.getAllByTestId("job-card").length).toBe(75));
    expect(screen.queryByTestId("jobs-load-more")).toBeNull();
    expect(apiRequest).not.toHaveBeenCalled();
  });
});
