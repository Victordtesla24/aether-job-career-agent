// @vitest-environment jsdom
/**
 * Review re-fix regression tests for F-2/F-3/F-4 (U1X FE review round,
 * 2026-08-13). U1X-a/b's own build already covers the RCA's "no models
 * shown at all" gap (u1x_b_provider_and_role.test.tsx); this file pins the
 * NEW defects the built fix introduced.
 *
 * F-2 [BLOCKER]: AgentModelPicker's anthropic billing-disclosure copy
 * claimed "assigning one runs this role directly against the connected
 * Anthropic credential" — false twice (the Orchestrator role makes NO LLM
 * call, and the catalog it lists is credential-INDEPENDENT so a card with
 * no connected credential showed the identical claim).
 *
 * F-3 [BLOCKER]: ProviderConnections' anthropic <select> preferred the
 * live, credential-independent catalog UNCONDITIONALLY, so the backend's
 * deliberate honest-empty-list gating (D-0020) for an unconfigured / needs-
 * reauth anthropic card was dead — the select showed all 3 real models,
 * ENABLED, while its own tooltip said "has no selectable models yet".
 *
 * F-4 [MAJOR]: providerModelDisabledReason returned null for ANY
 * `status === "connected"` provider regardless of how many options were
 * actually about to render, so a genuinely locked select (live fetch
 * failed, seed empty) rendered with no explanation at all.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

const fetchMeMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/admin")>();
  return { ...actual, fetchMe: fetchMeMock };
});

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

import AgentsPage from "../../app/dashboard/agents/page";
import type { CatalogAgent, Provider, ProviderModel } from "../../components/agents/api";
import { providerModelDisabledReason } from "../../components/agents/logic";
import AgentModelPicker from "../../components/agents/AgentModelPicker";

const ANTHROPIC_MODELS: ProviderModel[] = [
  { id: "claude-opus-4-8", name: "Claude Opus 4.8", promptPerM: 15, completionPerM: 75, contextLength: 200000, tier: "premium", reasoning: true },
  { id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6", promptPerM: 3, completionPerM: 15, contextLength: 200000, tier: "standard", reasoning: true },
  { id: "claude-haiku-4-5", name: "Claude Haiku 4.5", promptPerM: 1, completionPerM: 5, contextLength: 200000, tier: "budget", reasoning: false },
];

function anthropicProvider(overrides: Partial<Provider>): Provider {
  return {
    id: "anthropic",
    name: "Anthropic Claude",
    auth: "API Key",
    status: "unconfigured",
    model: "",
    detail: "You have not added your own Anthropic Claude key.",
    models: [],
    icon: "fa-a",
    color: "#D97757",
    source: "none",
    authMode: null,
    secretHint: null,
    lastVerifiedAt: null,
    lastVerifyStatus: null,
    needsReauth: false,
    ...overrides,
  };
}

const CATALOG_EMPTY = { agents: [], counts: { total: 0, active: 0, paused: 0, error: 0, planned: 0 } };
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

beforeEach(() => {
  vi.clearAllMocks();
  fetchMeMock.mockResolvedValue({ id: "u-op", email: "op@example.com", name: "", isAdmin: true });
  fetchCatalogMock.mockResolvedValue(CATALOG_EMPTY);
  fetchAgentStatsMock.mockResolvedValue(STATS);
  fetchAgentsMock.mockResolvedValue([]);
  fetchAgentRunsMock.mockResolvedValue([]);
  fetchProviderModelsMock.mockImplementation((provider: string) =>
    Promise.resolve(provider === "anthropic" ? ANTHROPIC_MODELS : []),
  );
  fetchProviderCatalogMock.mockResolvedValue({
    provider: "openrouter",
    count: 0,
    models: [],
    lastRefreshedAt: null,
    stale: false,
  });
});

afterEach(cleanup);

// --------------------------------------------------------------------------- #
// F-3 / D-0020: an UNCONFIGURED or needs-reauth anthropic card must NOT show
// the credential-independent live catalog as selectable options, even though
// fetchProviderModels('anthropic') genuinely resolves 3 real models.
// --------------------------------------------------------------------------- #

describe("F-3 — anthropic select stays honestly empty when not connected", () => {
  it("an UNCONFIGURED anthropic card renders a disabled, empty select despite the live catalog resolving", async () => {
    fetchProvidersMock.mockResolvedValue([anthropicProvider({ status: "unconfigured", models: [] })]);
    render(<AgentsPage />);
    await waitFor(() => expect(screen.getByTestId("provider-anthropic")).toBeTruthy());

    // Prove the live, credential-independent fetch really did resolve with
    // real models — the bug was never about the fetch failing.
    await waitFor(() => expect(fetchProviderModelsMock).toHaveBeenCalledWith("anthropic"));

    const select = (await screen.findByTestId("provider-model-anthropic")) as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    expect(select.textContent).not.toContain("claude-opus-4-8");
    // The lock reason backs the select's `title` tooltip (not visible text).
    expect(select.title ?? "").toMatch(/no selectable models yet/i);
  });

  it("a needs-reauth (warning) anthropic card also stays honestly locked", async () => {
    fetchProvidersMock.mockResolvedValue([
      anthropicProvider({ status: "warning", models: [], needsReauth: true, source: "database" }),
    ]);
    render(<AgentsPage />);
    await waitFor(() => expect(screen.getByTestId("provider-anthropic")).toBeTruthy());

    const select = (await screen.findByTestId("provider-model-anthropic")) as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    expect(select.textContent).not.toContain("claude-opus-4-8");
  });

  it("(contrast guard) a genuinely CONNECTED anthropic card still shows the real, enabled catalog", async () => {
    fetchProvidersMock.mockResolvedValue([
      anthropicProvider({
        status: "connected",
        source: "database",
        authMode: "oauth_token",
        secretHint: "…oat01",
        lastVerifiedAt: "2026-08-13T12:36:27Z",
        lastVerifyStatus: "ok",
      }),
    ]);
    render(<AgentsPage />);
    await waitFor(() => expect(screen.getByTestId("provider-anthropic")).toBeTruthy());

    const select = (await screen.findByTestId("provider-model-anthropic")) as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    expect(select.textContent).toContain("claude-opus-4-8");
  });
});

// --------------------------------------------------------------------------- #
// F-4: providerModelDisabledReason must key on the ACTUAL option count, not
// a blanket "connected ⇒ never locked" rule — a connected-but-currently-
// optionless card must still get an honest reason.
// --------------------------------------------------------------------------- #

describe("F-4 — providerModelDisabledReason keys on the real option count", () => {
  it("returns a reason for a CONNECTED provider with zero actual options", () => {
    const connectedButEmpty = anthropicProvider({ status: "connected", models: [] });
    const reason = providerModelDisabledReason(connectedButEmpty, 0);
    expect(reason).not.toBeNull();
    expect(reason).toContain("no selectable models yet");
  });

  it("returns null for a connected provider once real options are counted", () => {
    const connected = anthropicProvider({ status: "connected", models: ["claude-opus-4-8"] });
    expect(providerModelDisabledReason(connected, 3)).toBeNull();
  });

  it("(contrast guard) default optionCount still falls back to provider.models.length", () => {
    const unconfigured = anthropicProvider({ status: "unconfigured", models: [] });
    expect(providerModelDisabledReason(unconfigured)).not.toBeNull();
  });
});

// --------------------------------------------------------------------------- #
// F-2: the Orchestrator role card's billing-disclosure copy must not claim
// an LLM call runs immediately, and must not assert an unconditional
// "connected" credential.
// --------------------------------------------------------------------------- #

describe("F-2 — Orchestrator role picker billing copy is honest", () => {
  const ORCHESTRATION_AGENT: CatalogAgent = {
    key: "orchestration",
    name: "Orchestration Agent",
    icon: "fa-sitemap",
    accent: "indigo",
    model: "claude-opus-4-8",
    recommended: "claude-opus-4-8",
    tip: "Plans and sequences the live pipeline.",
    runnable: false,
    backend: "supervisor",
    enabled: true,
    status: "active",
    modelOverridable: true,
    last_run: null,
  };

  it("never claims the assignment runs directly against a connected credential", () => {
    render(
      <AgentModelPicker
        agentKey={ORCHESTRATION_AGENT.key}
        currentModel={ORCHESTRATION_AGENT.model}
        models={ANTHROPIC_MODELS}
        loading={false}
        error={null}
        saving={false}
        overridable
        catalogProvider="anthropic"
        onSelect={() => {}}
      />,
    );
    expect(screen.queryByText(/runs this role directly against the connected/i)).toBeNull();
    // Honest replacement: no LLM call happens from the assignment alone, and
    // a real call only ever runs against a credential that is CONNECTED (a
    // conditional requirement, never an assertion of the current state).
    expect(screen.getByText(/costs nothing until a real planning call runs/i)).toBeTruthy();
  });
});
