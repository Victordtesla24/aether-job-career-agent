// @vitest-environment jsdom
/**
 * F-02 (PROD-UAT-2026-08-03, MAJOR) — "Sync Now" ran a hardcoded search that
 * ignored the signed-in customer entirely.
 *
 * `runDiscovery()` posted a literal
 *   { query: "delivery lead, product owner, program manager, business analyst",
 *     location: "Australia" }
 * for EVERY user. A NEW-FREE persona with a Senior Data Scientist résumé and an
 * empty `targetRole` got 1,621 project-management postings dumped into their
 * account — none scored, none filtered — under a heading that called them
 * "matches".
 *
 * These tests drive the real JobsPage and assert three things the fix owes the
 * customer:
 *   1. the POST body is derived from THIS user's profile (and two different
 *      users therefore produce two different searches);
 *   2. with nothing configured the screen ASKS instead of silently running
 *      somebody else's search;
 *   3. the header counts stop calling unscored discoveries "matches".
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
const getToken = vi.fn();
const apiBaseUrl = vi.fn();
const fetchScoutSources = vi.fn();
const fetchSourceAvailability = vi.fn();
const fetchMe = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
  apiBaseUrl: () => apiBaseUrl(),
  getToken: () => getToken(),
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

vi.mock("../../../../lib/api/admin", () => ({
  fetchMe: (...args: unknown[]) => fetchMe(...args),
}));

// eslint-disable-next-line import/first
import JobsPage from "../page";

/** A scored job and an unscored one — the exact mix the labelling test needs. */
const SCORED_JOB = {
  id: "job-scored",
  title: "Senior Data Scientist",
  company: "Atlassian",
  location: "Sydney NSW",
  remote: false,
  description: "",
  source: "greenhouse",
  sourceUrl: "https://greenhouse.io/job/1",
  status: "matched",
  fitScore: 88,
  saved: false,
  createdAt: "2026-08-01T00:00:00Z",
};

const UNSCORED_JOB_A = {
  ...SCORED_JOB,
  id: "job-unscored-a",
  title: "Delivery Lead",
  company: "Telstra",
  fitScore: null,
};

const UNSCORED_JOB_B = {
  ...SCORED_JOB,
  id: "job-unscored-b",
  title: "Program Manager",
  company: "NAB",
  fitScore: null,
};

const JOBS_FIXTURE = [SCORED_JOB, UNSCORED_JOB_A, UNSCORED_JOB_B];

/**
 * Every scout POST body this render observed, in call order.
 *
 * MON-020 moved the screen onto the background mode of the same endpoint
 * (`/agents/scout/run?background=true`), so the path is matched by prefix. What
 * F-02 is about — the BODY being derived from the signed-in user — is unchanged.
 */
function scoutRunBodies(): Array<Record<string, unknown>> {
  return apiRequest.mock.calls
    .filter((call) => String(call[0]).startsWith("/agents/scout/run"))
    .map((call) => (call[1] as { body?: Record<string, unknown> })?.body ?? {});
}

async function defaultApiRequestImpl(path: string) {
  if (path.startsWith("/jobs?")) return JOBS_FIXTURE;
  if (/^\/jobs\/[^/]+\/insights$/.test(path)) {
    throw new Error("insights unavailable in this fixture");
  }
  if (path === "/agents") return [{ name: "scout", last_run: "2026-08-01T00:00:00Z" }];
  if (path.startsWith("/agents/scout/run")) {
    // MON-020 enqueue envelope: 202 + job id, polled below.
    return { job_id: "bg-f02", status: "enqueued" };
  }
  if (path.startsWith("/agents/jobs/")) {
    return {
      job_id: "bg-f02",
      status: "completed",
      agentKey: "scout",
      result: { status: "accepted", persisted: 0, updated: 0, errors: [] },
    };
  }
  if (path === "/agents/fit-scorer/run") return { status: "completed", scored: 0, errors: [] };
  throw new Error(`unexpected apiRequest(${path})`);
}

beforeEach(() => {
  apiRequest.mockImplementation(defaultApiRequestImpl);
  getToken.mockResolvedValue("test-token");
  apiBaseUrl.mockReturnValue("http://test.local");
  fetchScoutSources.mockResolvedValue([]);
  fetchSourceAvailability.mockResolvedValue([]);
  fetchMe.mockResolvedValue({
    id: "u-1",
    email: "data@example.com",
    name: "Dara",
    isAdmin: false,
    targetRole: "Senior Data Scientist",
    location: "Sydney, Australia",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/**
 * Render and wait for the board AND the profile lookup to settle.
 *
 * `discovery-search-target` only renders once the /auth/me read has resolved
 * (either way), so waiting on it removes the race between the click and the
 * profile — without which a pass could mean "the profile hadn't arrived yet".
 */
async function renderJobs() {
  render(<JobsPage />);
  await waitFor(() => expect(screen.getByTestId("jobs-stats")).toBeTruthy());
  await waitFor(() => expect(fetchMe).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByTestId("discovery-search-target")).toBeTruthy());
}

describe("F-02 · the search is the signed-in user's own", () => {
  it("posts a query derived from THIS user's profile, not a hardcoded persona", async () => {
    await renderJobs();

    fireEvent.click(screen.getByTestId("run-discovery-btn"));
    await waitFor(() => expect(scoutRunBodies().length).toBe(1));

    expect(scoutRunBodies()[0]).toEqual({
      query: "Senior Data Scientist",
      location: "Sydney, Australia",
    });
  });

  it("never sends the hardcoded delivery-lead persona", async () => {
    await renderJobs();

    fireEvent.click(screen.getByTestId("run-discovery-btn"));
    await waitFor(() => expect(scoutRunBodies().length).toBe(1));

    const serialised = JSON.stringify(scoutRunBodies()[0]).toLowerCase();
    for (const persona of ["delivery lead", "product owner", "program manager", "business analyst"]) {
      expect(serialised).not.toContain(persona);
    }
  });

  it("gives two different customers two different searches", async () => {
    await renderJobs();
    fireEvent.click(screen.getByTestId("run-discovery-btn"));
    await waitFor(() => expect(scoutRunBodies().length).toBe(1));
    const first = scoutRunBodies()[0];

    cleanup();
    vi.clearAllMocks();
    apiRequest.mockImplementation(defaultApiRequestImpl);
    getToken.mockResolvedValue("test-token");
    apiBaseUrl.mockReturnValue("http://test.local");
    fetchScoutSources.mockResolvedValue([]);
    fetchSourceAvailability.mockResolvedValue([]);
    fetchMe.mockResolvedValue({
      id: "u-2",
      email: "nurse@example.com",
      name: "Ana",
      isAdmin: false,
      targetRole: "Registered Nurse",
      location: "Auckland, New Zealand",
    });

    await renderJobs();
    fireEvent.click(screen.getByTestId("run-discovery-btn"));
    await waitFor(() => expect(scoutRunBodies().length).toBe(1));
    const second = scoutRunBodies()[0];

    expect(second).toEqual({ query: "Registered Nurse", location: "Auckland, New Zealand" });
    expect(second).not.toEqual(first);
  });

  it("states plainly what Sync Now will search for, and where it came from", async () => {
    await renderJobs();
    const summary = screen.getByTestId("discovery-search-target").textContent ?? "";
    expect(summary).toContain("Senior Data Scientist");
    expect(summary).toContain("Sydney, Australia");
    expect(summary.toLowerCase()).toContain("profile");
  });
});

describe("F-02 · empty profile is answered honestly, never substituted", () => {
  beforeEach(() => {
    fetchMe.mockResolvedValue({
      id: "u-new",
      email: "new@example.com",
      name: "New",
      isAdmin: false,
      targetRole: "",
      location: "",
    });
  });

  it("runs NO search when the user has told us nothing — it asks instead", async () => {
    await renderJobs();

    fireEvent.click(screen.getByTestId("run-discovery-btn"));
    // Give any (incorrect) fire-and-forget request a chance to be issued.
    await waitFor(() => expect(screen.getByTestId("discovery-target-prompt")).toBeTruthy());

    expect(scoutRunBodies()).toEqual([]);
    expect(
      apiRequest.mock.calls.some((call) => call[0] === "/agents/fit-scorer/run"),
    ).toBe(false);
  });

  it("says plainly that nothing is configured rather than implying a search happened", async () => {
    await renderJobs();
    fireEvent.click(screen.getByTestId("run-discovery-btn"));
    await waitFor(() => expect(screen.getByTestId("discovery-target-prompt")).toBeTruthy());

    const prompt = screen.getByTestId("discovery-target-prompt").textContent ?? "";
    expect(prompt.toLowerCase()).toContain("target role");
    // Must not name a role the user never asked for.
    expect(prompt.toLowerCase()).not.toContain("delivery lead");
  });

  it("searches exactly what the user types into the prompt", async () => {
    await renderJobs();
    fireEvent.click(screen.getByTestId("run-discovery-btn"));
    await waitFor(() => expect(screen.getByTestId("discovery-target-prompt")).toBeTruthy());

    fireEvent.change(screen.getByTestId("discovery-role-input"), {
      target: { value: "Senior Data Scientist" },
    });
    fireEvent.change(screen.getByTestId("discovery-location-input"), {
      target: { value: "Melbourne, Australia" },
    });
    fireEvent.click(screen.getByTestId("discovery-target-submit"));

    await waitFor(() => expect(scoutRunBodies().length).toBe(1));
    expect(scoutRunBodies()[0]).toEqual({
      query: "Senior Data Scientist",
      location: "Melbourne, Australia",
    });
  });

  it("will not run on a half-filled prompt", async () => {
    await renderJobs();
    fireEvent.click(screen.getByTestId("run-discovery-btn"));
    await waitFor(() => expect(screen.getByTestId("discovery-target-prompt")).toBeTruthy());

    fireEvent.change(screen.getByTestId("discovery-role-input"), {
      target: { value: "Senior Data Scientist" },
    });
    fireEvent.click(screen.getByTestId("discovery-target-submit"));

    await waitFor(() => expect(screen.getByTestId("discovery-target-prompt")).toBeTruthy());
    expect(scoutRunBodies()).toEqual([]);
  });

  it("asks (never guesses) when the profile could not be loaded at all", async () => {
    fetchMe.mockRejectedValue(new Error("network down"));
    await renderJobs();

    fireEvent.click(screen.getByTestId("run-discovery-btn"));
    await waitFor(() => expect(screen.getByTestId("discovery-target-prompt")).toBeTruthy());
    expect(scoutRunBodies()).toEqual([]);
  });
});

describe("F-02 · unscored discoveries are not labelled matches", () => {
  it("counts scored and unscored rows separately in the header", async () => {
    await renderJobs();

    const stats = screen.getByTestId("jobs-stats").textContent ?? "";
    // 1 of the 3 fixture rows carries a fitScore.
    expect(stats).toMatch(/\b1\b[^·]*scored/);
    expect(stats).toMatch(/\b2\b[^·]*not yet scored/);
  });

  it("never calls the whole unscored pile 'matches'", async () => {
    await renderJobs();

    const stats = screen.getByTestId("jobs-stats").textContent ?? "";
    expect(stats).not.toMatch(/\b3\s+matches\b/);
    expect(stats.toLowerCase()).not.toContain("matches across markets");
  });
});
