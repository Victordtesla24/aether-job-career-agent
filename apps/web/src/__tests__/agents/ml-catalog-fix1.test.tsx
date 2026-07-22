// @vitest-environment jsdom
/**
 * MODELS-LIVE FIX-1 (§3.3) — failing tests for the catalog gaps found in the
 * Phase-0 current-state audit (uat/reports/evidence/models-live/catalog/
 * CURRENT-STATE.md, dispatch #10) on the REAL Agents dashboard page
 * (apps/web/src/app/dashboard/agents/page.tsx):
 *
 *   * ML-catalog-001 (HIGH) — today there is exactly ONE model picker on the
 *     page (`#openrouter-model-picker` / `data-testid="model-picker"` inside
 *     `ModelPicker.tsx`), and it saves via `updateProvider()` to the
 *     PROVIDER-GLOBAL `AgentProvider.model` row. §3 requires a picker PER
 *     AGENT that saves to that agent's `AgentConfig.model`.
 *   * ML-catalog-002 (MED) — no "catalog last refreshed at …" freshness note
 *     anywhere on the page.
 *   * ML-catalog-003 (MED) — no manual "Refresh catalog" control anywhere.
 *
 * PINNED CONTRACT for the fixer (match these EXACTLY or these tests will
 * legitimately still fail after implementation — see
 * apps/api/tests/test_ml_catalog_fix1.py for the matching backend contract):
 *
 *   - `data-testid="agent-model-picker-<agentKey>"` — rendered on EVERY
 *     agent card whose `status !== "planned"` (mirrors the existing
 *     precedent in AgentConfigGrid/AgentCard, which already skips rendering
 *     any settings/run/toggle controls for `status === "planned"` — a
 *     backend-less catalog entry has nothing to configure). `agentKey` is
 *     the catalog `.key` (e.g. "resumeTailoring"), NOT the backend name
 *     ("tailor").
 *   - `data-testid="agent-model-search-<agentKey>"` — a text input inside
 *     that per-agent picker that filters its model list by name/id
 *     (mirrors the existing `model-search` convention in ModelPicker.tsx).
 *   - Each rendered model row inside the per-agent picker shows its price
 *     (a `$…/M` substring) and context length — asserted via visible text
 *     content, not a specific sub-testid, to stay robust to markup choices.
 *   - `data-testid="catalog-last-refreshed"` — visible text containing the
 *     freshness timestamp the backend now returns as `lastRefreshedAt`.
 *   - `data-testid="catalog-refresh-btn"` — a manual-refresh control whose
 *     accessible name matches /refresh/i; clicking it calls the NEW
 *     `refreshProviderModels` function this FIX-1 adds to
 *     `components/agents/api.ts` (POST
 *     .../providers/{provider}/models/refresh — see the backend test file).
 *
 * Selecting a model in a per-agent picker MUST persist via
 * `updateAgentConfig(agentKey, { model })` — never `updateProvider()` — so
 * two different agents can hold two different models simultaneously (the
 * per-agent, not global, contract already pinned on the backend).
 *
 * All of the above is currently MISSING from the real page: only the single
 * global `ModelPicker` section exists (see AgentConfigGrid.tsx / AgentCard —
 * no `agent-model-picker-*` testid anywhere in the component tree, and
 * ModelPicker.tsx has no freshness note or refresh control). Every test
 * below fails against current code for that reason.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Next's <Link> needs no router in a plain render — stub it to an anchor
// (same technique as __tests__/dashboard/subscription-gate.test.tsx).
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
// NOT YET EXPORTED by the real components/agents/api.ts — undefined until
// FIX-1 adds it. Included in the mock so a fixed implementation that imports
// it resolves to this spy instead of crashing on an unknown import.
const refreshProviderModelsMock = vi.hoisted(() => vi.fn());

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
  };
});

import AgentsPage from "../../app/dashboard/agents/page";
import type { Catalog, CatalogAgent, Provider } from "../../components/agents/api";

const AGENTS: CatalogAgent[] = [
  {
    key: "resumeTailoring",
    name: "Resume Tailoring Agent",
    icon: "fa-file-pen",
    accent: "coral",
    model: "claude-sonnet-4",
    recommended: "claude-sonnet-4",
    tip: "Best with a strong reasoning model.",
    runnable: true,
    backend: "tailor",
    enabled: true,
    status: "active",
    last_run: null,
  },
  {
    key: "coverLetter",
    name: "Cover Letter Agent",
    icon: "fa-envelope-open-text",
    accent: "indigo",
    model: "claude-sonnet-4",
    recommended: "claude-sonnet-4",
    tip: "Best with a strong reasoning model.",
    runnable: true,
    backend: "coverLetter",
    enabled: true,
    status: "active",
    last_run: null,
  },
  {
    key: "jobDiscovery",
    name: "Job Discovery Agent",
    icon: "fa-magnifying-glass",
    accent: "green",
    model: "deterministic",
    recommended: "deterministic",
    tip: "No LLM — deterministic scraping.",
    runnable: true,
    backend: "scout",
    enabled: true,
    status: "active",
    last_run: null,
  },
  {
    key: "compliance",
    name: "Compliance Agent",
    icon: "fa-shield",
    accent: "amber",
    model: "—",
    recommended: "claude-sonnet-4",
    tip: "Planned — no backend yet.",
    runnable: false,
    backend: null,
    enabled: false,
    status: "planned",
    last_run: null,
  },
];

const CATALOG: Catalog = {
  agents: AGENTS,
  counts: { total: AGENTS.length, active: 3, paused: 0, error: 0, planned: 1 },
};

const OPENROUTER_PROVIDER: Provider = {
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
};

const PROVIDERS: Provider[] = [OPENROUTER_PROVIDER];

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

const CATALOG_MODELS = [
  { id: "deepseek/deepseek-chat", name: "DeepSeek Chat", promptPerM: 0.14, completionPerM: 0.28,
    contextLength: 128000, tier: "budget" as const, reasoning: false },
  { id: "anthropic/claude-opus", name: "Claude Opus", promptPerM: 15, completionPerM: 75,
    contextLength: 200000, tier: "premium" as const, reasoning: true },
];

function mockHappyPathLoad() {
  fetchCatalogMock.mockResolvedValue(CATALOG);
  fetchProvidersMock.mockResolvedValue(PROVIDERS);
  fetchAgentStatsMock.mockResolvedValue(STATS);
  fetchAgentsMock.mockResolvedValue([]);
  fetchAgentRunsMock.mockResolvedValue([]);
  fetchProviderModelsMock.mockResolvedValue(CATALOG_MODELS);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ML-catalog-001 — per-agent (not global-only) model picker", () => {
  it("renders a per-agent model picker for EVERY non-planned agent row", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    await waitFor(() => expect(screen.getByTestId("agent-configuration")).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId(`agent-card-resumeTailoring`)).toBeTruthy());

    for (const key of ["resumeTailoring", "coverLetter", "jobDiscovery"]) {
      expect(
        screen.queryByTestId(`agent-model-picker-${key}`),
        `expected a per-agent model picker for "${key}" — only the single ` +
          `global #openrouter-model-picker exists today`,
      ).toBeTruthy();
    }
  });

  it("selecting a model in one agent's picker persists via updateAgentConfig(key, {model}) — NOT updateProvider", async () => {
    mockHappyPathLoad();
    updateAgentConfigMock.mockResolvedValue({
      key: "resumeTailoring", enabled: true, model: "anthropic/claude-opus",
      provider: null, authMode: null, credentialRef: null, temperature: 0.7,
      thinkingEffort: "medium",
    });
    render(<AgentsPage />);

    const picker = await screen.findByTestId("agent-model-picker-resumeTailoring");
    const option = await waitFor(() => {
      const el = picker.querySelector('[data-testid="model-option-anthropic/claude-opus"]');
      if (!el) throw new Error("model option not rendered yet");
      return el as HTMLElement;
    });
    fireEvent.click(option);

    await waitFor(() =>
      expect(updateAgentConfigMock).toHaveBeenCalledWith(
        "resumeTailoring",
        expect.objectContaining({ model: "anthropic/claude-opus" }),
      ),
    );
    // The provider-global save path must NOT be used for a per-agent pick.
    expect(updateProviderMock).not.toHaveBeenCalled();
  });

  it("two different agents can simultaneously show two different selected models (proves per-agent, not provider-global)", async () => {
    mockHappyPathLoad();
    // Two agents already have DIFFERENT persisted models in the catalog fed
    // to the page (resumeTailoring vs coverLetter, set above in AGENTS).
    const distinctAgents = AGENTS.map((a) =>
      a.key === "resumeTailoring"
        ? { ...a, model: "deepseek/deepseek-chat" }
        : a.key === "coverLetter"
          ? { ...a, model: "anthropic/claude-opus" }
          : a,
    );
    fetchCatalogMock.mockResolvedValue({ ...CATALOG, agents: distinctAgents });

    render(<AgentsPage />);
    const tailorPicker = await screen.findByTestId("agent-model-picker-resumeTailoring");
    const coverPicker = await screen.findByTestId("agent-model-picker-coverLetter");

    // Each picker must reflect ITS OWN agent's current selection, not a
    // single shared/global value.
    expect(tailorPicker.textContent).toContain("deepseek/deepseek-chat");
    expect(coverPicker.textContent).toContain("anthropic/claude-opus");
    expect(tailorPicker.textContent).not.toContain("anthropic/claude-opus");
  });
});

describe("ML-catalog-002 — catalog freshness surfaced in the UI", () => {
  it("shows a 'catalog last refreshed at' timestamp", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    await waitFor(() => expect(screen.getByTestId("agent-configuration")).toBeTruthy());
    const note = await screen.findByTestId("catalog-last-refreshed");
    expect(note.textContent ?? "").toMatch(/refresh/i);
    // NOTE for the fixer: the backend's stale-serve contract is pinned
    // precisely in apps/api/tests/test_ml_catalog_fix1.py
    // (`test_models_endpoint_serves_stale_cache_on_upstream_failure`) — when
    // that response's `stale: true` flag comes back, this same
    // `catalog-last-refreshed` element (or an adjacent one) should honestly
    // say so (e.g. "last refreshed … (stale — showing cached data)"). No
    // separate FE testid is pinned for that sub-state here since the exact
    // fetch-helper return shape needed to drive it is an implementation
    // choice left to the fixer (see file header + PR notes).
  });
});

describe("ML-catalog-003 — manual refresh control", () => {
  it("a 'Refresh catalog' control exists and calls the refresh API", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    await waitFor(() => expect(screen.getByTestId("agent-configuration")).toBeTruthy());
    const btn = await screen.findByTestId("catalog-refresh-btn");
    expect(btn.textContent ?? "").toMatch(/refresh/i);

    fireEvent.click(btn);
    await waitFor(() => expect(refreshProviderModelsMock).toHaveBeenCalled());
  });
});

describe("ML-catalog-001/§3.2.1 — per-agent picker is searchable and shows name+context+price", () => {
  it("has a search input and renders price + context length per agent", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    const picker = await screen.findByTestId("agent-model-picker-resumeTailoring");
    const search = await waitFor(() => {
      const el = picker.querySelector('[data-testid="agent-model-search-resumeTailoring"]');
      if (!el) throw new Error("search input not rendered yet");
      return el as HTMLInputElement;
    });

    // Price ($…/M) and context length are visible somewhere in the picker.
    expect(picker.textContent ?? "").toMatch(/\$\d/);
    expect(picker.textContent ?? "").toMatch(/(K|M)\s*(context|tokens)?/i);

    // Search actually filters — mirrors ModelPicker.tsx's `filterModels`.
    fireEvent.change(search, { target: { value: "opus" } });
    await waitFor(() => {
      expect(picker.querySelector('[data-testid="model-option-anthropic/claude-opus"]')).toBeTruthy();
      expect(picker.querySelector('[data-testid="model-option-deepseek/deepseek-chat"]')).toBeNull();
    });
  });
});
