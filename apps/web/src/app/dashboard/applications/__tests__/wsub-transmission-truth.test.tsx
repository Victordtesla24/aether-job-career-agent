// @vitest-environment jsdom
/**
 * W-SUB — the Submitted column must not imply a send that never happened.
 *
 * GROUND TRUTH (production, 2026-08-02): 86 `Application` rows sat in the
 * board's "Submitted" column while Aether had never transmitted a single
 * application anywhere — `POST /approvals/{id}/execute` returned
 * `{"status": "executed"}` without acting, `Job` had no recipient column at
 * all, and `ApprovalRequest.executedAt` was NULL on all 133 rows.
 *
 * The stored status is history and is NOT rewritten. What this test pins is
 * that the card and the detail panel now STATE which of the two very
 * different things actually happened, and that a genuinely transmitted
 * application is the only one allowed to read as sent.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import ApplicationsPage from "../page";

const BASE_APP = {
  id: "app-1",
  jobId: "job-1",
  resumeId: "resume-1",
  status: "submitted",
  coverLetter: "Dear Hiring Manager,",
  jobTitle: "Senior Product Owner",
  company: "Acme Corp",
  applyUrl: "https://boards.example.com/acme/1",
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-14T00:00:00Z",
  answers: {},
  fitScore: 88,
};

/** The 86 historical rows: marked submitted, never actually transmitted. */
const NEVER_TRANSMITTED = {
  ...BASE_APP,
  transmitted: false,
  submissionState: "not_transmitted",
  transmittedAt: null,
  transmittedTo: null,
  transmissionChannel: null,
  transmissionRef: null,
  autoSubmittable: false,
  applyEmail: null,
  applyEmailSource: null,
};

/** A real send: the employer published an address and Aether emailed it. */
const TRANSMITTED = {
  ...BASE_APP,
  transmitted: true,
  submissionState: "transmitted",
  transmittedAt: "2026-08-02T04:00:00Z",
  transmittedTo: "careers@acmecorp.com",
  transmissionChannel: "gmail",
  transmissionRef: "gmail-msg-1",
  autoSubmittable: true,
  applyEmail: "careers@acmecorp.com",
  applyEmailSource: "description_mailto",
};

function mockBoard(app: Record<string, unknown>) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/applications") return [app];
    if (path === "/jobs") return [];
    if (path.startsWith("/approvals")) return [];
    if (path === "/workspaces/settings") {
      return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
    }
    if (path === "/applications/funnel/sankey") {
      return { stages: [], dropoffs: [], insight: "" };
    }
    if (path.startsWith("/applications/app-1")) return app;
    return {};
  });
}

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("W-SUB — truthful submission state on the board", () => {
  it("marks a never-transmitted application as NOT sent by Aether", async () => {
    mockBoard(NEVER_TRANSMITTED);
    render(<ApplicationsPage />);
    const badge = await screen.findByTestId("submission-not-transmitted-badge");
    expect(badge.textContent).toContain("Not sent by Aether");
    expect(screen.queryByTestId("submission-transmitted-badge")).toBeNull();
  });

  it("only a really-transmitted application reads as sent", async () => {
    mockBoard(TRANSMITTED);
    render(<ApplicationsPage />);
    const badge = await screen.findByTestId("submission-transmitted-badge");
    expect(badge.textContent).toContain("Sent by Aether");
    expect(screen.queryByTestId("submission-not-transmitted-badge")).toBeNull();
  });

  it("the detail panel explains WHY nothing was sent, without a bare 'submitted'", async () => {
    mockBoard(NEVER_TRANSMITTED);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByText("Senior Product Owner"));
    const line = await screen.findByTestId("application-transmission-line");
    expect(line.textContent).toContain("Not sent by Aether");
    expect(line.textContent).toContain("publishes no application email address");
  });

  it("the detail panel cites checkable evidence for a real send", async () => {
    mockBoard(TRANSMITTED);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByText("Senior Product Owner"));
    const line = await screen.findByTestId("application-transmission-line");
    expect(line.textContent).toContain("careers@acmecorp.com");
    expect(line.textContent).toContain("gmail-msg-1");
  });
});

// HIGH-6 (re-review): the "Applied Jobs" history list shows a green "applied"
// chip next to the SAME badge that, on the board, invites the user to
// approve a card for automatic submission — on a job the user already told
// Aether they applied to some other way, that invitation is a duplicate-apply
// nudge and contradicts the chip beside it.
describe("W-SUB — Applied Jobs history view never invites a duplicate apply", () => {
  it("does not tell the user to approve-for-automatic-submission on an already-applied card", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/applications") return [];
      if (path.startsWith("/applications?include_applied=true")) return [NEVER_TRANSMITTED];
      if (path === "/jobs") return [];
      if (path.startsWith("/approvals")) return [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      if (path === "/applications/funnel/sankey") {
        return { stages: [], dropoffs: [], insight: "" };
      }
      return {};
    });
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByTestId("view-applied"));
    const badge = await screen.findByTestId("submission-not-transmitted-badge");
    expect(badge.title).not.toContain("Approve it in Approvals");
    expect(badge.title).not.toContain("automatically");
    // The chip beside it still honestly says "applied" — this only checks the
    // badge next to it stops contradicting it.
    expect(await screen.findByText("applied")).toBeTruthy();
  });
});
