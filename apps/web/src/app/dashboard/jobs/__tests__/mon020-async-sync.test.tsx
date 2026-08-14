// @vitest-environment jsdom
/**
 * MON-020 (HIGH, user-reported) — the Jobs "Sync Now" button 524s.
 *
 * `runDiscoveryFor` POSTed `/agents/scout/run` and awaited the whole discovery
 * pass in the request. Production measurement (discovery cron log, 1318 runs)
 * puts a real pass at 255-473s with a 968s worst case, while Cloudflare aborts
 * at ~100s and answers with its own HTML error page — which the screen then
 * rendered verbatim in the red banner.
 *
 * The fix owes the user four things, asserted here:
 *   1. the click ENQUEUES (`?background=true`) and returns immediately, then
 *      polls the existing `GET /agents/jobs/{id}` status route;
 *   2. while it polls, the screen says something HONEST about what is
 *      happening and how long it takes — never a fabricated percentage;
 *   3. a completed run reports the REAL counts the backend returned;
 *   4. a failure renders a friendly sentence, never raw gateway markup.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
const getToken = vi.fn();
const apiBaseUrl = vi.fn();
const describeApiError = vi.fn();
const fetchScoutSources = vi.fn();
const fetchSourceAvailability = vi.fn();
const fetchMe = vi.fn();

// Hoisted so the `vi.mock` factory below (which vitest lifts to the top of the
// file) can reference it without a temporal-dead-zone error.
const { FakeApiError } = vi.hoisted(() => ({
  FakeApiError: class extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
}));

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
  apiBaseUrl: () => apiBaseUrl(),
  getToken: () => getToken(),
  ApiError: FakeApiError,
  describeApiError: (...args: unknown[]) =>
    describeApiError(...(args as [unknown, string])),
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

const JOB = {
  id: "job-1",
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

/** Scout job status frames the poller will walk through, in order. */
let jobFrames: Array<Record<string, unknown>> = [];
let scoutPostPaths: string[] = [];

function baseImpl(path: string, init?: { method?: string }) {
  if (path.startsWith("/jobs?")) return Promise.resolve([JOB]);
  if (/^\/jobs\/[^/]+\/insights$/.test(path)) {
    return Promise.reject(new Error("insights unavailable in this fixture"));
  }
  if (path === "/agents") {
    return Promise.resolve([{ name: "scout", last_run: "2026-08-01T00:00:00Z" }]);
  }
  if (path.startsWith("/agents/scout/run")) {
    scoutPostPaths.push(path);
    return Promise.resolve({ job_id: "bg-1", status: "enqueued" });
  }
  if (path.startsWith("/agents/jobs/")) {
    const frame = jobFrames.length > 1 ? jobFrames.shift() : jobFrames[0];
    return Promise.resolve(frame);
  }
  if (path === "/agents/fit-scorer/run") {
    return Promise.resolve({ status: "completed", scored: 3, errors: [] });
  }
  return Promise.reject(new Error(`unexpected apiRequest(${path}) ${init?.method ?? ""}`));
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  scoutPostPaths = [];
  jobFrames = [
    {
      job_id: "bg-1",
      status: "completed",
      agentKey: "scout",
      result: { persisted: 7, updated: 2, errors: [], per_source: [] },
    },
  ];
  apiRequest.mockImplementation(baseImpl);
  getToken.mockResolvedValue("test-token");
  apiBaseUrl.mockReturnValue("http://test.local");
  describeApiError.mockImplementation((e: unknown, fallback: string) =>
    e instanceof Error ? e.message : fallback,
  );
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
  vi.useRealTimers();
  cleanup();
  vi.clearAllMocks();
});

async function renderJobs() {
  render(<JobsPage />);
  await waitFor(() => expect(screen.getByTestId("jobs-stats")).toBeTruthy());
  await waitFor(() => expect(screen.getByTestId("discovery-search-target")).toBeTruthy());
}

describe("MON-020 · Sync Now no longer blocks the request", () => {
  it("enqueues in background mode instead of running the pass in-request", async () => {
    await renderJobs();
    fireEvent.click(screen.getByTestId("run-discovery-btn"));

    await waitFor(() => expect(scoutPostPaths.length).toBe(1));
    expect(scoutPostPaths[0]).toContain("background=true");
  });

  it("shows honest progress copy while the background run is polled", async () => {
    // Hold the job in a non-terminal state so the polling UI is observable.
    jobFrames = [{ job_id: "bg-1", status: "processing", agentKey: "scout" }];
    await renderJobs();
    fireEvent.click(screen.getByTestId("run-discovery-btn"));

    const progress = await waitFor(() => screen.getByTestId("discovery-progress"));
    const text = progress.textContent ?? "";
    expect(text.length).toBeGreaterThan(0);
    // Honest: no fabricated percentage or ETA countdown, and it tells the user
    // the run continues server-side rather than pretending it is instant.
    expect(text).not.toMatch(/\d+\s*%/);
    expect(text.toLowerCase()).toContain("minutes");
    expect(screen.getByTestId("run-discovery-btn").textContent).toContain("Syncing");
  });

  it("reports the REAL counts the completed job returned", async () => {
    await renderJobs();
    fireEvent.click(screen.getByTestId("run-discovery-btn"));

    const done = await waitFor(() => screen.getByTestId("discovery-result"), {
      timeout: 8000,
    });
    expect(done.textContent).toContain("7");
    expect(done.textContent).toContain("2");
    await waitFor(() =>
      expect(screen.queryByTestId("discovery-progress")).toBeNull(),
    );
  });

  it("renders a friendly message for a failed background run, never raw markup", async () => {
    jobFrames = [
      {
        job_id: "bg-1",
        status: "failed",
        agentKey: "scout",
        error: "Discovery could not reach any job board. Please try again shortly.",
      },
    ];
    await renderJobs();
    fireEvent.click(screen.getByTestId("run-discovery-btn"));

    const alert = await waitFor(() => screen.getByRole("alert"), { timeout: 8000 });
    expect(alert.textContent).toContain("could not reach any job board");
    expect(alert.textContent).not.toContain("<");
    await waitFor(() =>
      expect(screen.queryByTestId("discovery-progress")).toBeNull(),
    );
  });

  it("routes the enqueue failure through the shared friendly-error helper", async () => {
    apiRequest.mockImplementation((path: string, init?: { method?: string }) => {
      if (path.startsWith("/agents/scout/run")) {
        return Promise.reject(
          new FakeApiError("The server took too long to respond.", 524),
        );
      }
      return baseImpl(path, init);
    });
    await renderJobs();
    fireEvent.click(screen.getByTestId("run-discovery-btn"));

    const alert = await waitFor(() => screen.getByRole("alert"));
    expect(describeApiError).toHaveBeenCalled();
    expect(alert.textContent).toContain("took too long");
  });
});
