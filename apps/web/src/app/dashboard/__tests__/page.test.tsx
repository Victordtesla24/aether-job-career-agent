// @vitest-environment jsdom
/**
 * /dashboard page — MV-dashboard-009 (HIGH, wiring).
 *
 * The Agent Activity feed's inline "Approve" button for a `coverLetter` run
 * is driven by `AgentRun.output.approval_status`, a field cached at
 * generation time that is never updated once the linked ApprovalRequest is
 * resolved through another surface (the /dashboard/approvals page, or the
 * Needs Approval widget in a different session). The button stays live
 * indefinitely for an already-resolved approval; clicking it correctly
 * fails closed server-side (409) but the failure was surfaced to the user as
 * a raw, unpolished string: literal HTTP method, endpoint, record id, status
 * code and a raw JSON blob concatenated into the toast.
 *
 * Fix under test:
 *  (a) the inline Approve button must be gated against the live, independently
 *      fetched pending-approvals list (GET /approvals?status=pending), not
 *      just the stale AgentRun.output field — so it disappears once the
 *      approval is resolved anywhere.
 *  (b) on any approve/reject failure, the toast must show a clean,
 *      honest, non-technical message — never the raw HTTP method, path,
 *      status code or JSON body.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../lib/api/client";
import type { AgentRun } from "../../../lib/api/agents";
import type { Approval } from "../../../lib/api/approvals";
import type { Funnel } from "../../../lib/api/analytics";
import type { MarketPulse as MarketPulseData } from "../../../lib/api/workspaces";

const fetchAgentRunsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/agents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/agents")>();
  return { ...actual, fetchAgentRuns: (...args: unknown[]) => fetchAgentRunsMock(...args) };
});

const fetchFunnelMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/analytics", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/analytics")>();
  return { ...actual, fetchFunnel: (...args: unknown[]) => fetchFunnelMock(...args) };
});

const fetchApprovalsMock = vi.hoisted(() => vi.fn());
const decideApprovalMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/approvals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/approvals")>();
  return {
    ...actual,
    fetchApprovals: (...args: unknown[]) => fetchApprovalsMock(...args),
  };
});
vi.mock("../../../components/approvals/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../components/approvals/api")>();
  return {
    ...actual,
    decideApproval: (...args: unknown[]) => decideApprovalMock(...args),
  };
});

const fetchStoriesMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/stories", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/stories")>();
  return { ...actual, fetchStories: (...args: unknown[]) => fetchStoriesMock(...args) };
});

const fetchNetworkingSummaryMock = vi.hoisted(() => vi.fn());
const fetchMarketPulseMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/workspaces", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/workspaces")>();
  return {
    ...actual,
    fetchNetworkingSummary: (...args: unknown[]) => fetchNetworkingSummaryMock(...args),
    fetchMarketPulse: (...args: unknown[]) => fetchMarketPulseMock(...args),
  };
});

const apiRequestMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/client")>();
  return { ...actual, apiRequest: (...args: unknown[]) => apiRequestMock(...args) };
});

const fetchReadinessMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/answer-bank", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/answer-bank")>();
  return {
    ...actual,
    fetchAnswerBankReadiness: (...args: unknown[]) => fetchReadinessMock(...args),
  };
});

// eslint-disable-next-line import/first
import DashboardPage from "../page";

function funnel(overrides: Partial<Funnel> = {}): Funnel {
  return {
    period: "all",
    jobs_found: 10,
    applied: 5,
    screened: 2,
    interviewed: 1,
    offers: 0,
    ...overrides,
  };
}

function marketPulse(): MarketPulseData {
  return {
    sources: [],
    sourcesTotal: 0,
    sourcesLabel: "0 jobs",
    topSkills: [],
    activityHeatmap: [],
    probability: {
      score: null,
      measured: false,
      label: "Job Search Progress",
      note: "",
      methodology: "",
      unmeasuredReason: "Not measured — no signal has data yet.",
      marketDataConnected: false,
      factors: [],
    },
    employerActivity: [],
    recruiterTrends: { series: [], rows: [] },
    // I2 (D-0042/R5): the global `marketDataConnected` flag is optional/deprecated
    // on the wire type — this fixture omits it to match the per-row contract.
    marketVsYou: { comparisons: [], summary: "" },
    trendIndicators: [],
  };
}

function coverLetterRun(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: overrides.id ?? "run-1",
    agentName: "coverLetter",
    status: "completed",
    input: null,
    output: { approval_status: "pending", approval_id: "appr-1" },
    error: null,
    costUsd: null,
    startedAt: "2026-07-17T10:00:00Z",
    completedAt: "2026-07-17T10:00:05Z",
    createdAt: "2026-07-17T10:00:00Z",
    ...overrides,
  };
}

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "appr-1",
    userId: "u1",
    applicationId: null,
    type: "application_submit",
    status: "pending",
    payload: { kind: "cover_letter" },
    createdAt: "2026-07-17T09:00:00Z",
    resolvedAt: null,
    ...overrides,
  };
}

beforeEach(() => {
  fetchFunnelMock.mockResolvedValue(funnel());
  apiRequestMock.mockResolvedValue([]);
  fetchStoriesMock.mockResolvedValue([]);
  fetchNetworkingSummaryMock.mockResolvedValue({
    crmSummary: { activeConversations: 0, followUpsDueToday: 0, warmIntrosPending: 0 },
  });
  fetchMarketPulseMock.mockResolvedValue(marketPulse());
  fetchAgentRunsMock.mockResolvedValue([]);
  fetchApprovalsMock.mockResolvedValue([]);
  fetchReadinessMock.mockResolvedValue({
    seedTotal: 12,
    seedCovered: 10,
    seedRemaining: [],
    essentialTotal: 10,
    essentialCovered: 10,
    setupComplete: true,
    liveAnswers: 10,
    expiredAnswers: 0,
    autoAnswerable: 10,
    gatedAnswers: 0,
    timesAnswered: 0,
    learnedFromApplications: 0,
    applicationsWaiting: 0,
    autoAnswerThreshold: 0.86,
  });
});

afterEach(() => {
  cleanup();
  fetchAgentRunsMock.mockReset();
  fetchFunnelMock.mockReset();
  apiRequestMock.mockReset();
  fetchStoriesMock.mockReset();
  fetchNetworkingSummaryMock.mockReset();
  fetchMarketPulseMock.mockReset();
  fetchApprovalsMock.mockReset();
  decideApprovalMock.mockReset();
  fetchReadinessMock.mockReset();
});

describe("Dashboard agent feed — MV-dashboard-009 stale Approve button", () => {
  it("does NOT show an inline Approve button for a coverLetter run whose approval was already resolved elsewhere", async () => {
    // The AgentRun's cached output still says "pending" (stale), but the
    // live, independently-fetched pending-approvals list no longer contains
    // this approval id — i.e. it was resolved via another surface.
    fetchAgentRunsMock.mockResolvedValue([coverLetterRun()]);
    fetchApprovalsMock.mockResolvedValue([]); // appr-1 is NOT pending anymore

    render(<DashboardPage />);

    const feed = await screen.findByTestId("agent-feed");
    await waitFor(() => expect(feed.textContent).toMatch(/awaiting your approval/i));
    expect(screen.queryByRole("button", { name: /^approve$/i })).toBeNull();
  });

  it("DOES show the inline Approve button while the approval is still genuinely pending", async () => {
    fetchAgentRunsMock.mockResolvedValue([coverLetterRun()]);
    fetchApprovalsMock.mockResolvedValue([approval()]); // still genuinely pending

    render(<DashboardPage />);

    const feed = await screen.findByTestId("agent-feed");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^approve$/i, hidden: false }),
      ).toBeTruthy(),
    );
    expect(feed.textContent).toMatch(/awaiting your approval/i);
  });

  it("shows an honest, non-technical error and never leaks the raw HTTP method/endpoint/JSON when approve 409s", async () => {
    fetchAgentRunsMock.mockResolvedValue([coverLetterRun()]);
    fetchApprovalsMock.mockResolvedValue([approval()]);
    decideApprovalMock.mockRejectedValue(
      new ApiError(
        'POST /approvals/appr-1/approve failed (409): {"detail":"Approval already approved — terminal state"}',
        409,
      ),
    );

    render(<DashboardPage />);

    const approveBtn = await screen.findByRole("button", { name: /^approve$/i });
    fireEvent.click(approveBtn);

    const toast = await screen.findByRole("status");
    expect(toast.textContent).not.toMatch(/POST|GET|\/approvals\/|409|\{.*detail/i);
    expect(toast.textContent).toMatch(/already/i);
  });

  it("shows a clean generic honest message (not raw error text) for a non-409 approve failure", async () => {
    fetchAgentRunsMock.mockResolvedValue([coverLetterRun()]);
    fetchApprovalsMock.mockResolvedValue([approval()]);
    decideApprovalMock.mockRejectedValue(
      new ApiError("POST /approvals/appr-1/approve failed (500): Internal Server Error", 500),
    );

    render(<DashboardPage />);

    const approveBtn = await screen.findByRole("button", { name: /^approve$/i });
    fireEvent.click(approveBtn);

    const toast = await screen.findByRole("status");
    expect(toast.textContent).not.toMatch(/POST|GET|\/approvals\/|500/i);
    expect(toast.textContent).toMatch(/couldn.?t approve/i);
  });

  it("U2c: a below-floor 409 offers Approve-anyway and re-sends with acknowledge, never leaking the raw error", async () => {
    fetchAgentRunsMock.mockResolvedValue([coverLetterRun()]);
    fetchApprovalsMock.mockResolvedValue([approval()]);
    // First approve (no ack) is refused by the quality-floor gate; the second
    // (with ack) succeeds — exactly the live prod flow the dashboard used to
    // leak as a raw 409.
    decideApprovalMock
      .mockRejectedValueOnce(
        new ApiError(
          'POST /approvals/appr-1/approve failed (409): {"detail":"Below quality floor: 3 dimensions did not clear the 80% floor. re-send this decision with acknowledge_below_floor=true"}',
          409,
        ),
      )
      .mockResolvedValueOnce(approval());
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<DashboardPage />);
    const approveBtn = await screen.findByRole("button", { name: /^approve$/i });
    fireEvent.click(approveBtn);

    await waitFor(() => expect(decideApprovalMock).toHaveBeenCalledTimes(2));
    // the retry carried the acknowledgement; the first attempt did not
    expect(decideApprovalMock.mock.calls[1][2]).toEqual({ acknowledgeBelowFloor: true });
    // the human was shown the real reason, not the raw HTTP envelope
    expect(confirmSpy.mock.calls[0][0]).toMatch(/below the quality floor|Below quality floor/i);
    expect(confirmSpy.mock.calls[0][0]).not.toMatch(/POST|\/approvals\/|409/);
    confirmSpy.mockRestore();
  });
});

describe("Dashboard first-run screening prompt (SETUP-1)", () => {
  it("routes a new subscriber whose bank is empty to Settings → Screening Answers", async () => {
    fetchReadinessMock.mockResolvedValue({
      seedTotal: 12,
      seedCovered: 0,
      seedRemaining: [],
      essentialTotal: 10,
      essentialCovered: 0,
      setupComplete: false,
      liveAnswers: 0,
      expiredAnswers: 0,
      autoAnswerable: 0,
      gatedAnswers: 0,
      timesAnswered: 0,
      learnedFromApplications: 0,
      applicationsWaiting: 0,
      autoAnswerThreshold: 0.86,
    });

    render(<DashboardPage />);

    const cta = await screen.findByTestId("screening-setup-cta");
    expect(cta.getAttribute("href")).toBe("/dashboard/settings?section=screening");
  });

  it("does not show the prompt once every reusable answer is saved", async () => {
    render(<DashboardPage />);
    await waitFor(() => expect(fetchReadinessMock).toHaveBeenCalled());
    expect(screen.queryByTestId("screening-setup-prompt")).toBeNull();
  });
});

describe("Needs Approval widget — long job_title containment leak (MV-approval-modal-003)", () => {
  it("wraps a long unbroken job_title in the subtitle instead of blowing out the widget layout", async () => {
    const longTitle = "B".repeat(300);
    fetchApprovalsMock.mockResolvedValue([
      approval({ payload: { job_title: longTitle, company: "Acme" } }),
    ]);

    render(<DashboardPage />);

    const widget = await screen.findByTestId("needs-approval-widget");
    await waitFor(() => expect(widget.textContent).toContain(longTitle));

    const subtitle = Array.from(widget.querySelectorAll("p")).find((p) =>
      p.textContent?.includes(longTitle),
    );
    expect(subtitle).toBeTruthy();
    expect(subtitle!.className).toMatch(/break-words|break-all/);
    expect(subtitle!.parentElement?.className).toMatch(/\bmin-w-0\b/);
  });
});
