// @vitest-environment jsdom
/**
 * F-02, second call site — the Agents console's per-agent "Run" button.
 *
 * `RUN_PARAMS.scout` was a second hardcoded persona,
 * `{ query: "software engineer", location: "Australia" }`, sent for every
 * customer who pressed Run on the Scout card. Same defect class as the Job
 * Discovery "Sync Now" hardcode (jobs/page.tsx:616), a different literal — so
 * fixing only the one the UAT happened to click would have left the product
 * still searching for the wrong job.
 *
 * The console must derive the scout run from the signed-in user's profile, and
 * must refuse (honestly, with a message that points at Settings) rather than
 * invent one when the profile says nothing.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
const fetchAgentRuns = vi.fn();
const fetchAgents = vi.fn();
const runAgent = vi.fn();
const runPipeline = vi.fn();
const fetchAgentStats = vi.fn();
const fetchCatalog = vi.fn();
const fetchProviders = vi.fn();
const updateAgentConfig = vi.fn();
const updateProvider = vi.fn();
const fetchMe = vi.fn();

vi.mock("../../../../lib/api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../../../lib/api/client")>(
      "../../../../lib/api/client",
    );
  return { ...actual, apiRequest: (...args: unknown[]) => apiRequest(...args) };
});

vi.mock("../../../../lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/admin")>();
  return { ...actual, fetchMe: (...args: unknown[]) => fetchMe(...args) };
});

vi.mock("../../../../lib/api/agents", () => ({
  fetchAgentRuns: (...args: unknown[]) => fetchAgentRuns(...args),
  fetchAgents: (...args: unknown[]) => fetchAgents(...args),
  runAgent: (...args: unknown[]) => runAgent(...args),
  runPipeline: (...args: unknown[]) => runPipeline(...args),
}));

vi.mock("../../../../components/agents/api", () => ({
  fetchAgentStats: (...args: unknown[]) => fetchAgentStats(...args),
  fetchCatalog: (...args: unknown[]) => fetchCatalog(...args),
  fetchProviders: (...args: unknown[]) => fetchProviders(...args),
  updateAgentConfig: (...args: unknown[]) => updateAgentConfig(...args),
  updateProvider: (...args: unknown[]) => updateProvider(...args),
}));

// eslint-disable-next-line import/first
import AgentsPage from "../page";

const STATS = {
  spendUsd: 0,
  avgCostPerRun: 0,
  providerCount: 0,
  tokensTotal: 0,
  tokensIn: 0,
  tokensOut: 0,
  mostActiveAgent: null,
  successRate: 0,
  taskCount: 0,
};

const SCOUT_AGENT = {
  key: "scout",
  name: "Scout",
  icon: "fa-binoculars",
  accent: "indigo",
  model: "gpt-5.5",
  recommended: "gpt-5.5",
  tip: "Finds roles",
  runnable: true,
  backend: "scout",
  enabled: true,
  status: "active" as const,
  last_run: null,
};

beforeEach(() => {
  fetchCatalog.mockResolvedValue({
    agents: [SCOUT_AGENT],
    counts: { total: 1, active: 1, paused: 0, error: 0, planned: 0 },
  });
  fetchProviders.mockResolvedValue([]);
  fetchAgentStats.mockResolvedValue(STATS);
  fetchAgents.mockResolvedValue([]);
  fetchAgentRuns.mockResolvedValue([]);
  runAgent.mockResolvedValue({ status: "accepted", persisted: 0, errors: [] });
  apiRequest.mockResolvedValue([]);
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

async function renderAgents() {
  render(<AgentsPage />);
  await waitFor(() => expect(screen.getByTestId("agent-run-scout")).toBeTruthy());
}

describe("F-02 · Agents console Scout run", () => {
  it("runs the signed-in user's own search, not 'software engineer'", async () => {
    await renderAgents();

    fireEvent.click(screen.getByTestId("agent-run-scout"));
    await waitFor(() => expect(runAgent).toHaveBeenCalled());

    // MON-020 added two trailing arguments (request options, then the
    // background opt-in that keeps a multi-minute scout off the request path).
    // What F-02 is about — the params being the signed-in user's own — is
    // asserted on the first two arguments exactly as before.
    expect(runAgent).toHaveBeenCalledWith(
      "scout",
      { query: "Senior Data Scientist", location: "Sydney, Australia" },
      {},
      { background: true },
    );
    expect(JSON.stringify(runAgent.mock.calls[0]).toLowerCase()).not.toContain("software engineer");
  });

  it("refuses honestly instead of inventing a search for an empty profile", async () => {
    fetchMe.mockResolvedValue({
      id: "u-new",
      email: "new@example.com",
      name: "New",
      isAdmin: false,
      targetRole: "",
      location: "",
    });
    await renderAgents();

    fireEvent.click(screen.getByTestId("agent-run-scout"));
    await waitFor(() =>
      expect(screen.getByText(/target role/i)).toBeTruthy(),
    );
    expect(runAgent).not.toHaveBeenCalled();
  });
});
