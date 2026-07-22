// @vitest-environment jsdom
/**
 * MODELS-LIVE §7 step 2 — failing test for ML-agents-001 (BLOCKER), FE half.
 *
 * storyExtraction runs on the STRUCTURED model tier
 * (apps/api/app/services/llm_client.py `_USER_OVERRIDABLE_TIERS` deliberately
 * excludes STRUCTURED — `get_model("STRUCTURED")` never honours a per-run
 * user override), so picking a model for it in the per-agent picker silently
 * no-ops at run time. AgentConfigGrid.tsx currently locks the picker (the
 * honest "fixed model / not user-selectable" indicator from ML-catalog-008/N2)
 * ONLY for `agent.recommended === "deterministic"`:
 *
 *   deterministic={agent.recommended === "deterministic"}    // AgentConfigGrid.tsx:197
 *
 * storyExtraction's `recommended` is a REAL model id
 * ("claude-haiku-4-5-20251001"), not the "deterministic" sentinel, so this
 * check is FALSE for it and it renders the exact same FUNCTIONAL
 * search+select picker as a genuinely overridable agent (tailor/coverLetter/
 * emailAgent) — the N2 lock's blind spot this finding reports.
 *
 * PINNED CONTRACT for the fixer (backend half pinned in
 * apps/api/tests/test_ml_agents_refix.py): the backend catalog response gains
 * an authoritative per-agent `modelOverridable: boolean` field (derived from
 * the agent's tier + deterministic flag — never hardcoded agent names client-
 * side). AgentConfigGrid must lock the picker whenever
 * `agent.modelOverridable === false` — covering BOTH fully-deterministic
 * backends AND non-overridable LLM tiers (STRUCTURED) — not just the old
 * `recommended === "deterministic"` sentinel check.
 *
 * FAILS NOW: storyExtraction's picker renders the functional
 * `agent-model-search-storyExtraction` input and `model-option-*` rows
 * exactly like an overridable agent — because the component reads
 * `agent.recommended`, not `agent.modelOverridable` (a field the fixture
 * below sets to `false` to describe the CORRECT backend contract; the
 * component ignores it today).
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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

import AgentsPage from "../../app/dashboard/agents/page";
import type { Catalog, CatalogAgent, Provider } from "../../components/agents/api";

// `modelOverridable` is NOT part of today's `CatalogAgentSchema` — added here
// (and cast through the fixture) to describe the CORRECT backend contract
// this test pins; the component under test ignores it today, which is
// exactly the bug. Real fields (key/backend/recommended/status/...) mirror
// the actual AGENT_CATALOG entries in apps/api/app/routers/agents.py.
type FixtureAgent = CatalogAgent & { modelOverridable: boolean };

const AGENTS: FixtureAgent[] = [
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
    modelOverridable: true, // REASONING tier — user-overridable at run time.
  },
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
    modelOverridable: true, // REASONING tier — user-overridable at run time.
  },
  {
    key: "storyExtraction",
    name: "Story Extraction Agent",
    icon: "fa-book-bookmark",
    accent: "coral",
    model: "claude-haiku-4-5-20251001",
    recommended: "claude-haiku-4-5-20251001",
    tip: "Mines the base resume into STAR+R evidence stories — runs on the "
      + "STRUCTURED model tier.",
    runnable: true,
    backend: "storyExtractor",
    enabled: true,
    status: "active",
    last_run: null,
    // STRUCTURED tier — `_USER_OVERRIDABLE_TIERS` excludes it, so a picked
    // model is NEVER read at run time. `recommended` is deliberately a REAL
    // model id (not "deterministic") — that's the whole point of this gap.
    modelOverridable: false,
  },
  {
    key: "jobDiscovery",
    name: "Job Discovery Agent",
    icon: "fa-magnifying-glass",
    accent: "indigo",
    model: "deterministic",
    recommended: "deterministic",
    tip: "No LLM — deterministic scraping.",
    runnable: true,
    backend: "scout",
    enabled: true,
    status: "active",
    last_run: null,
    modelOverridable: false,
  },
];

const CATALOG: Catalog = {
  agents: AGENTS,
  counts: { total: AGENTS.length, active: 4, paused: 0, error: 0, planned: 0 },
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

describe("ML-agents-001 — the model-selectable lock must cover STRUCTURED-tier agents too", () => {
  it("storyExtraction (STRUCTURED tier — model never honoured at run time) shows the honest fixed/locked indicator, NOT a functional picker", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    // Wait for the shared catalog fetch to finish loading before inspecting
    // storyExtraction's picker (avoids a false pass during the loading state).
    await screen.findByTestId("agent-model-search-resumeTailoring");
    const picker = screen.getByTestId("agent-model-picker-storyExtraction");

    // FAILS NOW: AgentConfigGrid.tsx gates the lock on
    // `agent.recommended === "deterministic"` — storyExtraction's
    // `recommended` is a real model id, so this renders the exact same
    // functional search+select surface as tailor/emailAgent below.
    expect(
      picker.querySelector('[data-testid="agent-model-search-storyExtraction"]'),
      "storyExtraction runs on the STRUCTURED tier (not user-overridable at " +
        "run time) — its picker must NOT offer a functional search+select " +
        "surface that silently no-ops",
    ).toBeNull();
    expect(
      picker.querySelector('[data-testid^="model-option-"]'),
      "storyExtraction's picker must NOT render selectable model rows",
    ).toBeNull();
    expect(
      picker.textContent ?? "",
      "expected an honest 'fixed/tuned model, not user-selectable' " +
        "indicator for a non-overridable (STRUCTURED-tier) agent",
    ).toMatch(/not user-selectable|no LLM|fixed model|tuned model|not applicable/i);
  });

  it("tailor and emailAgent (REASONING tier — genuinely overridable) keep the functional picker", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    for (const key of ["resumeTailoring", "emailAgent"]) {
      const picker = await screen.findByTestId(`agent-model-picker-${key}`);
      await waitFor(() => {
        expect(
          picker.querySelector(`[data-testid="agent-model-search-${key}"]`),
          `${key} is genuinely user-overridable (REASONING tier) and must ` +
            "keep its functional search+select picker",
        ).toBeTruthy();
      });
    }
  });
});
