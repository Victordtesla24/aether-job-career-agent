// @vitest-environment jsdom
/**
 * BLOCKER (second surface) — `apps/web/src/app/dashboard/agents/page.tsx`
 * hardcoded `RUN_PARAMS.emailAgent = { mode: "triage" }`, so the Email Agent's
 * "Run" button on the agent console could only ever trigger triage. The
 * `job_alerts` mode — a real, tested backend that turns the candidate's own
 * job-alert mail into Job rows — was unreachable from this screen entirely.
 *
 * These tests pin the Agents console's own affordance for it, and pin that the
 * honest degrade (no Gmail connected) is reported as a problem rather than as
 * a completed scan.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}));

const fetchAgentsMock = vi.hoisted(() => vi.fn());
const fetchAgentRunsMock = vi.hoisted(() => vi.fn());
const runAgentMock = vi.hoisted(() => vi.fn());
const runPipelineMock = vi.hoisted(() => vi.fn());

vi.mock("../../lib/api/agents", () => ({
  fetchAgents: fetchAgentsMock,
  fetchAgentRuns: fetchAgentRunsMock,
  runAgent: runAgentMock,
  runPipeline: runPipelineMock,
}));

const fetchCatalogMock = vi.hoisted(() => vi.fn());
const fetchProvidersMock = vi.hoisted(() => vi.fn());
const fetchAgentStatsMock = vi.hoisted(() => vi.fn());
const updateAgentConfigMock = vi.hoisted(() => vi.fn());
const updateProviderMock = vi.hoisted(() => vi.fn());
const fetchProviderModelsMock = vi.hoisted(() => vi.fn());
const refreshProviderModelsMock = vi.hoisted(() => vi.fn());
const fetchProviderCatalogMock = vi.hoisted(() => vi.fn());

vi.mock("../../components/agents/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../components/agents/api")>();
  return {
    ...actual,
    fetchCatalog: fetchCatalogMock,
    fetchProviders: fetchProvidersMock,
    fetchAgentStats: fetchAgentStatsMock,
    updateAgentConfig: updateAgentConfigMock,
    updateProvider: updateProviderMock,
    fetchProviderModels: fetchProviderModelsMock,
    refreshProviderModels: refreshProviderModelsMock,
    fetchProviderCatalog: fetchProviderCatalogMock,
  };
});

// eslint-disable-next-line import/first
import AgentsPage from "../../app/dashboard/agents/page";
// eslint-disable-next-line import/first
import type { Catalog, CatalogAgent, Provider } from "../../components/agents/api";

const AGENTS: CatalogAgent[] = [
  {
    key: "emailAgent",
    name: "Email Agent",
    icon: "fa-envelope",
    accent: "coral",
    model: "claude-sonnet-4",
    recommended: "claude-sonnet-4",
    tip: "Real Gmail-backed inbox triage.",
    runnable: true,
    backend: "emailAgent",
    enabled: true,
    status: "active",
    last_run: null,
  },
];

const CATALOG: Catalog = {
  agents: AGENTS,
  counts: { total: 1, active: 1, paused: 0, error: 0, planned: 0 },
};

const PROVIDERS: Provider[] = [
  {
    id: "openrouter",
    name: "OpenRouter",
    auth: "API Key",
    status: "connected",
    model: "",
    detail: "Connected",
    models: [],
    icon: "fa-route",
    color: "#6467F2",
    source: "database",
  },
];

const STATS = {
  spendUsd: 0,
  avgCostPerRun: 0,
  providerCount: 1,
  tokensTotal: 0,
  tokensIn: 0,
  tokensOut: 0,
  mostActiveAgent: null,
  successRate: 0,
  taskCount: 0,
};

function mockLoad() {
  fetchCatalogMock.mockResolvedValue(CATALOG);
  fetchProvidersMock.mockResolvedValue(PROVIDERS);
  fetchAgentStatsMock.mockResolvedValue(STATS);
  fetchAgentsMock.mockResolvedValue([]);
  fetchAgentRunsMock.mockResolvedValue([]);
  fetchProviderModelsMock.mockResolvedValue([]);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Agents console — the job-alert intake is reachable here too", () => {
  it("runs mode job_alerts (not triage) and reports the real counts", async () => {
    mockLoad();
    runAgentMock.mockResolvedValue({
      mode: "job_alerts",
      connected: true,
      degraded: false,
      message: "Read 2 job-alert email(s) across 1 mailbox(es): 6 posting(s) extracted, 4 new job(s) added, 2 already known, 0 skipped for missing data.",
      accounts_scanned: 1,
      messages_scanned: 88,
      alert_emails: 2,
      postings_extracted: 6,
      postings_skipped: 0,
      jobs_created: 4,
      jobs_updated: 2,
      platforms: { seek: 2 },
      per_account: [],
      notes: [],
    });

    render(<AgentsPage />);
    const btn = await screen.findByTestId("agents-scan-job-alerts");
    fireEvent.click(btn);

    await waitFor(() => expect(runAgentMock).toHaveBeenCalled());
    const [name, params] = runAgentMock.mock.calls[0]!;
    expect(name).toBe("email");
    expect((params as Record<string, unknown>).mode).toBe("job_alerts");

    const notice = await screen.findByTestId("agents-job-alerts-notice");
    expect(notice.textContent).toContain("4 new jobs added to your board");
    expect(notice.textContent).toContain("6 posting(s) extracted");
  });

  it("no Gmail connected is reported as a problem, never as a finished scan", async () => {
    mockLoad();
    runAgentMock.mockResolvedValue({
      mode: "job_alerts",
      connected: false,
      degraded: true,
      message: "Connect Gmail to read your job-alert emails — no mailbox is connected, so there is nothing to scan.",
      accounts_scanned: 0,
      messages_scanned: 0,
      alert_emails: 0,
      postings_extracted: 0,
      postings_skipped: 0,
      jobs_created: 0,
      jobs_updated: 0,
      platforms: {},
      per_account: [],
      notes: [],
    });

    render(<AgentsPage />);
    fireEvent.click(await screen.findByTestId("agents-scan-job-alerts"));

    const notice = await screen.findByTestId("agents-job-alerts-notice");
    expect(notice.getAttribute("data-tone")).toBe("warning");
    expect(notice.textContent).toContain("No Gmail mailbox connected");
    expect(notice.textContent).not.toMatch(/added to your board/i);
  });

  it("a failed run surfaces the real error, not a summary", async () => {
    mockLoad();
    runAgentMock.mockRejectedValue(new Error("502 Gmail unavailable"));

    render(<AgentsPage />);
    fireEvent.click(await screen.findByTestId("agents-scan-job-alerts"));

    const notice = await screen.findByTestId("agents-job-alerts-notice");
    expect(notice.getAttribute("data-tone")).toBe("warning");
    expect(notice.textContent).toContain("502 Gmail unavailable");
  });
});
