// @vitest-environment jsdom
/**
 * U5 NO-PREPARED-ONLY — the honest half of the invariant must be VISIBLE.
 *
 * U-PLAN "U5 MANDATE SHARPENED" rule 1: every approved application reaches
 * either TRANSMITTED (evidence + timestamp + channel) or an HONEST, ACTIONABLE
 * state — "never silently stuck in prepared". The backend records that second
 * outcome on the row (apps/api/app/services/apply_executor.py
 * `record_manual_step` → manualStepReason/manualStepDetail/manualStepAt) and
 * GET /applications now selects it (apps/api/app/routers/applications.py
 * `_COLUMNS`). This test pins the last link in that chain: that the board card
 * and the detail panel actually SHOW the obstacle, with the employer's own
 * words, instead of rendering the same misleading "prepared only" copy a row
 * with no attempt gets.
 *
 * The screening-question case is the safety-critical one: Aether refuses to
 * fabricate an answer, so the user must read the REAL question verbatim.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import ApplicationsPage from "../page";

/** The verbatim question an Ashby form asked that no stored profile answer
 *  could honestly answer — fabricating one is forbidden, so it must surface. */
const QUESTION = "How many years of hands-on Kubernetes operations do you have?";

const BASE_APP = {
  id: "app-1",
  jobId: "job-1",
  resumeId: "resume-1",
  status: "draft",
  coverLetter: "Dear Hiring Manager,",
  jobTitle: "Senior Product Owner",
  company: "Acme Corp",
  applyUrl: "https://jobs.ashbyhq.com/acme/1",
  createdAt: "2026-08-10T00:00:00Z",
  updatedAt: "2026-08-13T00:00:00Z",
  answers: {},
  fitScore: 88,
  transmitted: false,
  submissionState: "not_transmitted",
  transmittedAt: null,
  transmittedTo: null,
  transmissionChannel: null,
  transmissionRef: null,
  autoSubmittable: false,
  applyEmail: null,
  applyEmailSource: null,
  applyChannel: null,
  manualStepReason: null,
  manualStepDetail: null,
  manualStepAt: null,
};

/** Approved, attempted for real, blocked by a question Aether won't invent. */
const MANUAL_STEP_APP = {
  ...BASE_APP,
  applyChannel: "ashby",
  manualStepReason: "unknown_required_question",
  manualStepDetail: QUESTION,
  manualStepAt: "2026-08-13T09:30:00Z",
};

/** Approved, attempted, blocked by a CAPTCHA — no verbatim question to show. */
const CAPTCHA_APP = {
  ...BASE_APP,
  applyChannel: "greenhouse",
  manualStepReason: "captcha",
  manualStepDetail: null,
  manualStepAt: "2026-08-13T09:30:00Z",
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

describe("U5 — a blocked application is shown as actionable, never as 'prepared only'", () => {
  it("the board card flags the manual step instead of the approval prompt", async () => {
    mockBoard(MANUAL_STEP_APP);
    render(<ApplicationsPage />);

    const badge = await screen.findByTestId("ready-manual-step-badge");
    expect(badge.textContent).toContain("A required question needs your answer");
    // The card must NOT claim nothing has happened yet: this application was
    // approved and really attempted.
    expect(screen.queryByTestId("request-approval-button")).toBeNull();
  });

  it("the detail panel renders the manual-step block with the employer's own words", async () => {
    mockBoard(MANUAL_STEP_APP);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByText("Senior Product Owner"));

    const block = await screen.findByTestId("application-manual-step-block");
    expect(block.textContent).toContain("A required question needs your answer");

    const detail = await screen.findByTestId("application-manual-step-detail");
    // Verbatim, not paraphrased — the user answers the real question.
    expect(detail.textContent).toContain(QUESTION);

    // And the top line must not repeat the misleading "prepared only" copy.
    const line = await screen.findByTestId("application-transmission-line");
    expect(line.textContent).toContain("ran into an obstacle");
    expect(line.textContent).not.toContain("prepared only");
  });

  it("offers the assist package so the user can finish the application themselves", async () => {
    mockBoard(MANUAL_STEP_APP);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByText("Senior Product Owner"));

    expect(await screen.findByTestId("manual-step-download-resume-btn")).toBeTruthy();
  });

  it("shows a detail-free obstacle (CAPTCHA) without inventing a question", async () => {
    mockBoard(CAPTCHA_APP);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByText("Senior Product Owner"));

    const block = await screen.findByTestId("application-manual-step-block");
    expect(block.textContent).toContain("A CAPTCHA blocked automatic submission");
    // No manualStepDetail was recorded, so no quoted text may be fabricated.
    expect(screen.queryByTestId("application-manual-step-detail")).toBeNull();
  });

  it("an application with no attempt still reads as prepared — no false alarm", async () => {
    mockBoard(BASE_APP);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByText("Senior Product Owner"));

    expect(screen.queryByTestId("application-manual-step-block")).toBeNull();
    const line = await screen.findByTestId("application-transmission-line");
    expect(line.textContent).toContain("prepared only");
  });
});
