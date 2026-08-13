// @vitest-environment jsdom
/**
 * U1X-b — failing tests for the Anthropic model-select gap and the
 * Orchestrator role-picker gap (U-PLAN.md "U1X BUILD PLAN" SLICES →
 * U1X-b), matching the backend contract pinned in
 * apps/api/tests/test_u1x_a_anthropic_catalog.py and
 * apps/api/tests/test_u1x_b_orchestrator_role.py.
 *
 * RCA (agents-uplift discovery, anthropic-card scout):
 *  - ProviderConnections.tsx renders a plain `<select disabled=
 *    {p.models.length===0}>` for every non-openrouter provider and NEVER
 *    fetches anything itself (by design — "This component never fetches").
 *    page.tsx mounts the live-catalog `<ModelPicker>` ONLY for the
 *    `openrouter` provider (`openrouterProvider`, page.tsx) — nothing in the
 *    FE ever calls `fetchProviderModels('anthropic')`, even though that
 *    endpoint already answers 200 with 3 real models unconditionally.
 *  - `providerModelDisabledReason` (logic.ts) emits "... has no selectable
 *    models yet — configure its credentials ..." keyed PURELY on
 *    `provider.models.length === 0` — dishonest for anthropic's actual live
 *    shape today: connected + verified (source=database,
 *    authMode=oauth_token, lastVerifyStatus=ok) yet `models: []`.
 *  - The per-agent picker (`AgentConfigGrid` → `AgentModelPicker`) is
 *    already generic and already works for ANY catalog entry (proven green
 *    today by ml-catalog-fix1.test.tsx), but ALL agent cards — including a
 *    future "orchestration" card — share ONE `catalogModels` array fetched
 *    exclusively from `fetchProviderModels(CATALOG_PROVIDER)` where
 *    `CATALOG_PROVIDER = "openrouter"` (page.tsx, hardcoded constant). The
 *    orchestrator's flagship default (`claude-opus-4-8`) and its downshift
 *    options (`claude-sonnet-4-6`, `claude-haiku-4-5`) are bare anthropic
 *    ids that do not exist in the OpenRouter catalog, so even once the
 *    backend seeds `modelOverridable: true` + a flagship `recommended`
 *    (U1X-b backend contract), the orchestrator card's picker would still
 *    offer the WRONG catalog — hundreds of unrelated OpenRouter models,
 *    none of which are the real anthropic tier options.
 *
 * Test-authorship only — no fix is implemented in this file.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

/** The 3-model static anthropic catalog (llm_client._STATIC_MODEL_CATALOG),
 * exactly the shape GET /agents/providers/anthropic/models already returns. */
const ANTHROPIC_MODELS: ProviderModel[] = [
  { id: "claude-opus-4-8", name: "Claude Opus 4.8", promptPerM: 15, completionPerM: 75, contextLength: 200000, tier: "premium", reasoning: true },
  { id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6", promptPerM: 3, completionPerM: 15, contextLength: 200000, tier: "standard", reasoning: true },
  { id: "claude-haiku-4-5", name: "Claude Haiku 4.5", promptPerM: 1, completionPerM: 5, contextLength: 200000, tier: "budget", reasoning: false },
];

/** Anthropic's REAL live shape today (connected + verified, per the RCA's
 * live probe) — `models: []` is exactly the bug, not a fixture mistake. */
const CONNECTED_ANTHROPIC: Provider = {
  id: "anthropic",
  name: "Anthropic Claude",
  auth: "API Key",
  status: "connected",
  model: "",
  detail: "Credential stored in the encrypted vault (…oat01)",
  models: [],
  icon: "fa-a",
  color: "#D97757",
  source: "database",
  authMode: "oauth_token",
  secretHint: "…oat01",
  lastVerifiedAt: "2026-08-13T12:36:27Z",
  lastVerifyStatus: "ok",
  needsReauth: false,
};

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
  fetchProvidersMock.mockResolvedValue([CONNECTED_ANTHROPIC]);
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
// (a) anthropic card renders a real model select fed by
//     fetchProviderModels('anthropic') when connected
// --------------------------------------------------------------------------- #

describe("U1X-b (a) — Anthropic card gets a real, live-fed model select", () => {
  it("calls fetchProviderModels('anthropic') when a connected anthropic provider is on screen", async () => {
    render(<AgentsPage />);
    await waitFor(() => expect(screen.getByTestId("provider-anthropic")).toBeTruthy());

    // FAILS NOW: nothing in page.tsx ever calls fetchProviderModels with
    // "anthropic" — only CATALOG_PROVIDER ("openrouter") is ever fetched.
    await waitFor(() =>
      expect(fetchProviderModelsMock).toHaveBeenCalledWith("anthropic"),
      { timeout: 2000 },
    );
  });

  it("renders a real, non-disabled model select for anthropic instead of the placeholder", async () => {
    render(<AgentsPage />);
    await waitFor(() => expect(screen.getByTestId("provider-anthropic")).toBeTruthy());

    // FAILS NOW: ProviderConnections renders
    // <select disabled={p.models.length===0}> for anthropic because
    // `providers[].models` is still [] — "No preset models — configure
    // below" is exactly what's on screen for a genuinely connected+verified
    // credential.
    await waitFor(() => {
      const select = screen.getByTestId("provider-model-anthropic") as HTMLSelectElement;
      expect(select.disabled).toBe(false);
    });
    expect(screen.queryByText("No preset models — configure below")).toBeNull();
    expect(screen.getByText(/claude-opus-4-8/)).toBeTruthy();
  });
});

// --------------------------------------------------------------------------- #
// (b) providerModelDisabledReason no longer claims "no selectable models
//     yet" for a CONNECTED provider
// --------------------------------------------------------------------------- #

describe("U1X-b (b) — providerModelDisabledReason honesty", () => {
  it("does not claim 'no selectable models yet' for anthropic's real connected+verified shape", () => {
    // FAILS NOW: keys purely on `provider.models.length === 0`, so it
    // dishonestly tells a genuinely connected+verified user to "configure
    // its credentials" — advice that makes no sense since they already did.
    const reason = providerModelDisabledReason(CONNECTED_ANTHROPIC);
    expect(reason).toBeNull();
  });

  it("(contrast guard) still explains a genuinely UNCONFIGURED provider's locked select", () => {
    const reason = providerModelDisabledReason({ ...CONNECTED_ANTHROPIC, status: "unconfigured", models: [] });
    expect(reason).not.toBeNull();
    expect(reason).toContain("no selectable models yet");
  });
});

// --------------------------------------------------------------------------- #
// (c) Orchestrator role picker: flagship default + cost-labeled ANTHROPIC
//     options (not the shared OpenRouter list) + PUTs the override
// --------------------------------------------------------------------------- #

describe("U1X-b (c) — Orchestrator role picker", () => {
  /** The POST-FIX backend catalog shape (U1X-b backend contract, pinned in
   * apps/api/tests/test_u1x_b_orchestrator_role.py): `recommended`/`model`
   * default to the flagship anthropic id and `modelOverridable` is true. */
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

  beforeEach(() => {
    fetchCatalogMock.mockResolvedValue({
      agents: [ORCHESTRATION_AGENT],
      counts: { total: 1, active: 1, paused: 0, error: 0, planned: 0 },
    });
  });

  it("offers the ANTHROPIC catalog's cost-labeled options, not the shared OpenRouter list", async () => {
    render(<AgentsPage />);
    const picker = await waitFor(() => screen.getByTestId("agent-model-picker-orchestration"));

    // The flagship default is visible.
    expect(picker.textContent).toContain("claude-opus-4-8");

    // FAILS NOW: the orchestration card's picker is fed the ONE shared
    // `catalogModels` state, populated only from
    // fetchProviderModels(CATALOG_PROVIDER === "openrouter") — it never
    // fetches "anthropic", so the real downshift options never appear.
    await waitFor(() =>
      expect(fetchProviderModelsMock).toHaveBeenCalledWith("anthropic"),
      { timeout: 2000 },
    );
    await waitFor(() => expect(screen.getByTestId("model-option-claude-sonnet-4-6")).toBeTruthy());
    expect(screen.getByText(/\$3\.00\/M in/)).toBeTruthy();
  });

  it("PUTs the selected downshift model via updateAgentConfig('orchestration', {model})", async () => {
    updateAgentConfigMock.mockResolvedValue({ ...ORCHESTRATION_AGENT, model: "claude-sonnet-4-6" });
    render(<AgentsPage />);
    await waitFor(() => expect(screen.getByTestId("agent-model-picker-orchestration")).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId("model-option-claude-sonnet-4-6")).toBeTruthy());

    fireEvent.click(screen.getByTestId("model-option-claude-sonnet-4-6"));

    await waitFor(() =>
      expect(updateAgentConfigMock).toHaveBeenCalledWith("orchestration", { model: "claude-sonnet-4-6" }),
    );
  });
});
