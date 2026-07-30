// @vitest-environment jsdom
/**
 * GAP-P6-WIRE-001 regression guard (Cluster B, /dashboard/applications).
 *
 * probe-06-interactions.json flagged "Board View", "Sankey Flow" and
 * "Timeline" as RENDERED-BUT-NO-EFFECT: clicking them produced no network
 * call and no observable state change. This test renders the real
 * ApplicationsPage, drives each of the three view-toggle tabs, and asserts
 * the visible view actually swaps (kanban board -> sankey chart -> timeline
 * list) so a regression that silently disconnects a tab's onClick handler
 * from the rendered view is caught here, not just in a prop-level test.
 *
 * FEAT-CLEAR: also covers the "Clear Pipeline" button + confirmation gate —
 * the button only renders on the Board view when there are pipeline job cards
 * (Discovered / Evaluating / Tailoring), the gate opens with honest
 * soft-archive copy, Cancel/Escape never call the API, Confirm calls
 * POST /applications/pipeline/clear with {confirm: true} and shows the
 * returned archived count, and a failure surfaces the error + keeps the board.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import ApplicationsPage from "../page";

const APP_FIXTURE = {
  id: "app-1",
  jobId: "job-1",
  resumeId: "resume-1",
  status: "submitted",
  coverLetter: null,
  jobTitle: "Senior Product Owner",
  company: "Acme Corp",
  applyUrl: "https://boards.example.com/acme/1",
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-14T00:00:00Z",
  answers: {},
  fitScore: 88,
};

const SANKEY_FIXTURE = {
  stages: [
    { key: "discovered", label: "Discovered", value: 847, color: "#4F46E5" },
    { key: "applied", label: "Applied", value: 412, color: "#818CF8" },
  ],
  dropoffs: [{ after: "discovered", count: 435, reason: "not pursued" }],
  insight: "Most drop-off happens before application.",
};

/** Two agent-pipeline jobs (status 'discovered') with no application — the
 * cards that populate the Discovered column and make the Clear Pipeline
 * button visible. */
const PIPELINE_JOBS = [0, 1].map((i) => ({
  id: `pipeline-job-${i}`,
  title: `Sourced Role ${i}`,
  company: "Sourced Co",
  location: "Remote",
  remote: true,
  description: "",
  requirements: [],
  source: "seek",
  sourceUrl: null,
  status: "discovered",
  fitScore: null,
  atsScore: null,
  saved: false,
  postedAt: null,
  createdAt: "2026-07-01T00:00:00Z",
  updatedAt: "2026-07-01T00:00:00Z",
}));

/** Default mock: 1 submitted application + 2 pipeline jobs. */
function defaultMock(extra: Record<string, unknown> = {}) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/applications") return [APP_FIXTURE];
    if (path === "/jobs") return PIPELINE_JOBS;
    if (path.startsWith("/approvals")) return [];
    if (path === "/workspaces/settings") {
      return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
    }
    if (path === "/applications/funnel/sankey") return SANKEY_FIXTURE;
    if (path === "/applications/pipeline/clear") {
      return { archived: 2, jobIds: ["pipeline-job-0", "pipeline-job-1"] };
    }
    if (extra[path] !== undefined) return extra[path];
    throw new Error(`unexpected apiRequest(${path})`);
  });
}

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("Application Tracker view toggles (GAP-P6-WIRE-001)", () => {
  it("Board View / Sankey Flow / Timeline each render a distinct, non-dead view", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/applications") return [APP_FIXTURE];
      if (path === "/jobs") return [];
      if (path.startsWith("/approvals")) return [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      if (path === "/applications/funnel/sankey") return SANKEY_FIXTURE;
      throw new Error(`unexpected apiRequest(${path})`);
    });

    render(<ApplicationsPage />);

    // Default view: Board — the kanban columns render, seeded from the fixture.
    await screen.findByTestId("applications-kanban");
    expect(screen.getByTestId("view-board").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("Senior Product Owner")).not.toBeNull();

    // Sankey Flow: clicking swaps the DOM to the sankey chart and fetches
    // the canonical funnel data — a real network call + real state change.
    fireEvent.click(screen.getByTestId("view-sankey"));
    expect(screen.getByTestId("view-sankey").getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByTestId("applications-kanban")).toBeNull();
    await screen.findByTestId("sankey-svg");
    expect(apiRequest).toHaveBeenCalledWith(
      "/applications/funnel/sankey",
      expect.anything(),
    );

    // Timeline: swaps again to a chronological list of the same applications.
    fireEvent.click(screen.getByTestId("view-timeline"));
    expect(screen.getByTestId("view-timeline").getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByTestId("sankey-svg")).toBeNull();
    const timeline = await screen.findByTestId("timeline-view");
    expect(timeline.textContent).toContain("Senior Product Owner");

    // Back to Board — the toggle round-trips cleanly.
    fireEvent.click(screen.getByTestId("view-board"));
    await screen.findByTestId("applications-kanban");
    expect(screen.queryByTestId("timeline-view")).toBeNull();
  });
});

describe("Tracker header label honesty (MV-adv-A-001)", () => {
  it("labels the board's full pipeline count honestly, never 'active applications'", async () => {
    // 2 sourced jobs with no application yet (early board columns, fed by
    // Job.status) + 10 applications (2 draft, 3 submitted, 3 interview, 1
    // offer, 1 rejected). Board-card (activeCount) total = 2 jobs + 9
    // non-closed applications (rejected is excluded to the "Closed" strip)
    // = 11 — while the canonical submitted count shown elsewhere
    // (dashboard/mobile/analytics, get_application_counts()['submitted']) for
    // the SAME account/moment is 8 (everything but the 2 drafts: 3 submitted
    // + 3 interview + 1 offer + 1 rejected). 11 !== 8, so the header must not
    // read "11 active applications" — that collides with the "8 active
    // applications" label used on every other surface for a different count.
    const pendingJobs = [0, 1].map((i) => ({
      id: `pending-job-${i}`,
      title: `Sourced Role ${i}`,
      company: "Sourced Co",
      location: "Remote",
      remote: true,
      description: "",
      requirements: [],
      source: "seek",
      sourceUrl: null,
      status: "discovered",
      fitScore: null,
      atsScore: null,
      saved: false,
      postedAt: null,
      createdAt: "2026-07-01T00:00:00Z",
      updatedAt: "2026-07-01T00:00:00Z",
    }));

    const makeApp = (i: number, status: string) => ({
      id: `app-${i}`,
      jobId: `job-${i}`,
      resumeId: "resume-1",
      status,
      coverLetter: null,
      jobTitle: `Role ${i}`,
      company: "Acme Corp",
      applyUrl: null,
      createdAt: "2026-07-10T00:00:00Z",
      updatedAt: "2026-07-14T00:00:00Z",
      answers: {},
      fitScore: 80,
    });

    const apps = [
      makeApp(1, "draft"),
      makeApp(2, "draft"),
      makeApp(3, "submitted"),
      makeApp(4, "submitted"),
      makeApp(5, "submitted"),
      makeApp(6, "interview"),
      makeApp(7, "interview"),
      makeApp(8, "interview"),
      makeApp(9, "offer"),
      makeApp(10, "rejected"),
    ];

    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/applications") return apps;
      if (path === "/jobs") return pendingJobs;
      if (path.startsWith("/approvals")) return [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      throw new Error(`unexpected apiRequest(${path})`);
    });

    render(<ApplicationsPage />);

    const subtitle = await screen.findByTestId("tracker-subtitle");
    expect(subtitle.textContent).toContain("11");
    expect(subtitle.textContent?.toLowerCase()).not.toMatch(/active application/);
  });
});

describe("Clear Pipeline button visibility (FEAT-CLEAR)", () => {
  it("does not render the button when there are no pipeline jobs", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/applications") return [APP_FIXTURE];
      if (path === "/jobs") return [];
      if (path.startsWith("/approvals")) return [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      throw new Error(`unexpected apiRequest(${path})`);
    });

    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");
    expect(screen.queryByTestId("clear-pipeline-btn")).toBeNull();
  });

  it("renders the button with a count when pipeline jobs exist", async () => {
    defaultMock();
    render(<ApplicationsPage />);
    const btn = await screen.findByTestId("clear-pipeline-btn");
    expect(btn.textContent).toContain("Clear Pipeline");
    // The pipeline-job count badge shows 2.
    expect(btn.textContent).toContain("2");
  });

  it("hides the button on non-board views", async () => {
    defaultMock();
    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");
    // Button is visible on board view.
    expect(screen.getByTestId("clear-pipeline-btn")).not.toBeNull();
    // Switch to sankey — button disappears.
    fireEvent.click(screen.getByTestId("view-sankey"));
    await screen.findByTestId("sankey-svg");
    expect(screen.queryByTestId("clear-pipeline-btn")).toBeNull();
  });
});

describe("Clear Pipeline confirmation gate (FEAT-CLEAR)", () => {
  it("opens the confirmation modal when 'Clear Pipeline' is clicked", async () => {
    defaultMock();
    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");

    expect(screen.queryByTestId("clear-pipeline-gate")).toBeNull();

    fireEvent.click(screen.getByTestId("clear-pipeline-btn"));

    expect(screen.getByTestId("clear-pipeline-gate")).not.toBeNull();
    expect(screen.getByTestId("clear-pipeline-confirm")).not.toBeNull();
    expect(screen.getByTestId("clear-pipeline-cancel")).not.toBeNull();
    expect(screen.getByText("Clear the entire pipeline?")).not.toBeNull();
    // Honest contract: soft-archive, not "irreversible" / "permanently delete".
    expect(screen.getByText(/archive/)).not.toBeNull();
    expect(screen.getByText(/soft-deleted/)).not.toBeNull();
    // Applications + closed items are explicitly left untouched.
    expect(screen.getByText("left untouched")).not.toBeNull();
  });

  it("closes the modal without calling the API when Cancel is clicked", async () => {
    let clearCalled = false;
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/applications") return [APP_FIXTURE];
      if (path === "/jobs") return PIPELINE_JOBS;
      if (path.startsWith("/approvals")) return [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      if (path === "/applications/pipeline/clear") {
        clearCalled = true;
        return { archived: 2, jobIds: ["pipeline-job-0", "pipeline-job-1"] };
      }
      throw new Error(`unexpected apiRequest(${path})`);
    });

    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");

    fireEvent.click(screen.getByTestId("clear-pipeline-btn"));
    expect(screen.getByTestId("clear-pipeline-gate")).not.toBeNull();

    fireEvent.click(screen.getByTestId("clear-pipeline-cancel"));

    expect(screen.queryByTestId("clear-pipeline-gate")).toBeNull();
    expect(clearCalled).toBe(false);
  });

  it("closes the modal without calling the API when Escape is pressed", async () => {
    let clearCalled = false;
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/applications") return [APP_FIXTURE];
      if (path === "/jobs") return PIPELINE_JOBS;
      if (path.startsWith("/approvals")) return [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      if (path === "/applications/pipeline/clear") {
        clearCalled = true;
        return { archived: 2, jobIds: ["pipeline-job-0", "pipeline-job-1"] };
      }
      throw new Error(`unexpected apiRequest(${path})`);
    });

    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");

    fireEvent.click(screen.getByTestId("clear-pipeline-btn"));
    expect(screen.getByTestId("clear-pipeline-gate")).not.toBeNull();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByTestId("clear-pipeline-gate")).toBeNull();
    expect(clearCalled).toBe(false);
  });

  it("calls clearPipeline on confirm and shows success with returned count", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/applications") return [APP_FIXTURE];
      if (path === "/jobs") return PIPELINE_JOBS;
      if (path.startsWith("/approvals")) return [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      if (path === "/applications/pipeline/clear") {
        return { archived: 2, jobIds: ["pipeline-job-0", "pipeline-job-1"] };
      }
      throw new Error(`unexpected apiRequest(${path})`);
    });

    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");

    fireEvent.click(screen.getByTestId("clear-pipeline-btn"));
    expect(screen.getByTestId("clear-pipeline-gate")).not.toBeNull();

    fireEvent.click(screen.getByTestId("clear-pipeline-confirm"));

    const success = await screen.findByTestId("clear-pipeline-success");
    expect(success.textContent).toContain("2");
    expect(success.textContent).toContain("Archived");
    expect(success.textContent).toContain("pipeline job");

    expect(screen.queryByTestId("clear-pipeline-confirm")).toBeNull();

    expect(apiRequest).toHaveBeenCalledWith(
      "/applications/pipeline/clear",
      expect.objectContaining({ method: "POST", body: { confirm: true } }),
    );
  });

  it("shows error on failed clearPipeline call and keeps the board visible", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/applications") return [APP_FIXTURE];
      if (path === "/jobs") return PIPELINE_JOBS;
      if (path.startsWith("/approvals")) return [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      if (path === "/applications/pipeline/clear") {
        throw new Error("Server error: database connection lost");
      }
      throw new Error(`unexpected apiRequest(${path})`);
    });

    render(<ApplicationsPage />);
    await screen.findByTestId("applications-kanban");

    fireEvent.click(screen.getByTestId("clear-pipeline-btn"));
    fireEvent.click(screen.getByTestId("clear-pipeline-confirm"));

    await screen.findByText("Server error: database connection lost");
    expect(screen.queryByTestId("clear-pipeline-gate")).toBeNull();

    // Board must still be visible — no optimistic clear.
    expect(screen.getByTestId("applications-kanban")).not.toBeNull();
    expect(screen.getByText("Senior Product Owner")).not.toBeNull();
  });
});


/**
 * P0-3 approvals deadlock fix: a draft card in "Ready to Apply" must only
 * claim "needs approval" when a LIVE pending approval exists. When the
 * approval expired / was purged (48h window), the card previously showed a
 * static badge with NO route back into the queue — a deadlock. The fix
 * surfaces the EXISTING re-request path (POST /approvals, idempotent
 * server-side per job+kind).
 */
describe("Ready-column approval re-request (P0-3)", () => {
  const DRAFT_APP = {
    ...APP_FIXTURE,
    id: "app-draft-1",
    jobId: "job-draft-1",
    status: "draft",
    jobTitle: "Staff Engineer",
    company: "Peloton",
  };

  const PENDING_APPROVAL = {
    id: "appr-1",
    userId: "user-1",
    applicationId: "app-draft-1",
    type: "application_submit",
    status: "pending",
    payload: { job_id: "job-draft-1", job_title: "Staff Engineer", company: "Peloton" },
    createdAt: "2026-07-30T00:00:00Z",
    resolvedAt: null,
  };

  function mockWith(approvals: unknown[], onCreate?: (options: unknown) => unknown) {
    apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
      if (path === "/approvals" && options?.method === "POST") {
        if (onCreate) return onCreate(options);
        return PENDING_APPROVAL;
      }
      if (path === "/applications") return [DRAFT_APP];
      if (path === "/jobs") return [];
      if (path.startsWith("/approvals")) return approvals;
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      throw new Error(`unexpected apiRequest(${path})`);
    });
  }

  it("shows 'needs approval' ONLY when a live pending approval exists", async () => {
    mockWith([PENDING_APPROVAL]);
    render(<ApplicationsPage />);
    await screen.findByText("Staff Engineer");

    expect(await screen.findByTestId("needs-approval-badge")).not.toBeNull();
    expect(screen.queryByTestId("approval-expired-badge")).toBeNull();
    expect(screen.queryByTestId("request-approval-button")).toBeNull();
  });

  it("shows the re-request affordance instead of a false badge when no pending approval exists", async () => {
    mockWith([]); // approval expired / purged — nothing pending
    render(<ApplicationsPage />);
    await screen.findByText("Staff Engineer");

    // FAILS before the fix: the old code rendered a static "needs approval"
    // badge here regardless of the approval queue's actual state.
    expect(await screen.findByTestId("approval-expired-badge")).not.toBeNull();
    expect(screen.queryByTestId("needs-approval-badge")).toBeNull();
    expect(screen.getByTestId("request-approval-button")).not.toBeNull();
  });

  it("POSTs /approvals with the application context and reconciles on click", async () => {
    let created = false;
    apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
      if (path === "/approvals" && options?.method === "POST") {
        created = true;
        return PENDING_APPROVAL;
      }
      if (path === "/applications") return [DRAFT_APP];
      if (path === "/jobs") return [];
      if (path.startsWith("/approvals")) return created ? [PENDING_APPROVAL] : [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      throw new Error(`unexpected apiRequest(${path})`);
    });

    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByTestId("request-approval-button"));

    // The badge flips to the live "needs approval" state after the reload —
    // the card is back inside the approval queue, deadlock broken.
    expect(await screen.findByTestId("needs-approval-badge")).not.toBeNull();
    expect(screen.queryByTestId("request-approval-button")).toBeNull();

    expect(apiRequest).toHaveBeenCalledWith(
      "/approvals",
      expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({
          type: "application_submit",
          application_id: "app-draft-1",
          payload: expect.objectContaining({
            job_id: "job-draft-1",
            job_title: "Staff Engineer",
            company: "Peloton",
          }),
        }),
      }),
    );
  });
});
