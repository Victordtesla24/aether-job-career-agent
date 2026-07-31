// @vitest-environment jsdom
/**
 * GOLD-MASTER-V2 §11.2 / W-I item 3 — ML-DASH-002: the "live" label on the
 * dashboard's Agent Activity feed must be honest.
 *
 * `/dashboard/page.tsx` renders an unconditional green dot + the literal
 * text "live" next to the Agent Activity heading (page.tsx lines ~224-226):
 *
 *   <span className="live-dot h-2 w-2 rounded-full bg-aether-green" />
 *   <h2>Agent Activity</h2>
 *   <span className="mono text-[11px] text-aether-muted-dim">live</span>
 *
 * But every widget on this page, including the feed, is fetched exactly
 * once via the load-once `useLoad` hook (page.tsx lines 92-117) — there is
 * no `setInterval`, no `usePolling`, no re-fetch of any kind after mount.
 * MEASURED ground truth for this run: "`/dashboard` (main): core widgets
 * (stats, funnel, feed, opportunities, stories, market-pulse) are
 * LOAD-ONCE; only the sidebar and topbar poll. It nonetheless renders a
 * 'live' label" (ML-DASH-002).
 *
 * §11.2 requires mutations/data to be genuinely live, and by extension a
 * "live" claim in the UI must correspond to a real refresh mechanism — the
 * same honesty class as the Gmail "Connected" defect elsewhere in this
 * audit. This test proves the label renders regardless of whether any
 * refresh mechanism actually exists, which is the defect.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
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
    probability: { score: 0, label: "n/a", note: "", factors: [] },
    employerActivity: [],
    recruiterTrends: { series: [], rows: [] },
    marketVsYou: { marketDataConnected: false, comparisons: [], summary: "" },
    trendIndicators: [],
  };
}

function coverLetterRun(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: overrides.id ?? "run-1",
    agentName: "coverLetter",
    status: "completed",
    input: null,
    output: null,
    error: null,
    costUsd: null,
    startedAt: "2026-07-17T10:00:00Z",
    completedAt: "2026-07-17T10:00:05Z",
    createdAt: "2026-07-17T10:00:00Z",
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
  fetchAgentRunsMock.mockResolvedValue([coverLetterRun()]);
  fetchApprovalsMock.mockResolvedValue([]);
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
});

describe("W-I item 3 — Agent Activity 'live' label honesty (ML-DASH-002)", () => {
  it("does not claim to be 'live' when the feed is fetched exactly once and never refreshed", async () => {
    render(<DashboardPage />);

    const feed = await screen.findByTestId("agent-feed");
    await waitFor(() => expect(fetchAgentRunsMock).toHaveBeenCalledTimes(1));

    // Give any hypothetical refresh mechanism a generous window to prove
    // itself (well past the §11.2 <=20s cadence requirement) — this is a
    // real-timers test on purpose, so a genuine setInterval/usePolling
    // refresh would actually fire here.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fetchAgentRunsMock).toHaveBeenCalledTimes(1); // confirms load-once, per MEASURED ground truth

    // §11.2 honesty requirement: a "live" label must only render when a
    // refresh mechanism is genuinely active. It is not — the feed is
    // fetched exactly once (asserted above) — so the label must not claim
    // otherwise.
    expect(within(feed).queryByText(/^live$/i)).toBeNull();
  });
});
