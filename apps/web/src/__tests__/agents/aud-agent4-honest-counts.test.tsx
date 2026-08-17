// @vitest-environment jsdom
/**
 * AUD-AGENT-4 — no screen may claim 22 standalone agents.
 *
 * THE DEFECT. The agent catalog is a list of CARDS. One deterministic engine
 * (`fitScorer`) is presented as three cards — Match Scoring, ATS Optimization
 * and Skill Gap — so the catalog's card total has never been a count of
 * agents. Two surfaces rendered it as one anyway:
 *
 *   * `app/dashboard/agents/page.tsx` — the hero subline, `{agentCount} agents`
 *     over `catalog.counts.total`;
 *   * `components/agents/AgentConfigGrid.tsx` — the Agent Configuration
 *     header, `${counts.total} agents`;
 *
 * and the "Agents" tab badge carried the same padded total.
 *
 * ROUND 2 — THE THIRD SURFACE, ON THE SAME SCREEN. The first round left the
 * Orchestration tab (the DEFAULT tab of this very page) rendering
 * `{model.stages.reduce((n, s) => n + s.nodes.length, 0)} agents` in each
 * workflow map's header. The "Fit Scoring" stage lists four cards, three of
 * which are the one `fitScorer` backend, so that header was padded by exactly
 * the triple-count this finding names — and none of round 1's tests could see
 * it (they scanned the hero subline, the grid header and the tab badge). The
 * map header now renders the SERVER's per-map `counts.engines` /
 * `counts.cards` as the same dual disclosure.
 *
 * WHAT THESE TESTS PIN.
 *   1. the dual disclosure is DERIVED, not written: "N engines powering M
 *      cards" comes from the SERVER's `counts.engines` / `counts.cards`;
 *   2. a payload with no honest basis produces NO count — never the padded
 *      total, which is the fabrication this fix removes;
 *   3. all THREE surfaces render the pair and none renders "N agents": the
 *      hero subline, the Agent Configuration header, and every workflow map
 *      header in the Orchestration tab;
 *   4. the tab badge labelled "Agents" carries the ENGINE count;
 *   5. the conductor's own "Run everything (N agents / M cards)" label is
 *      untouched and still server-derived, so the two screens agree;
 *   6. `buildMapModel` takes the map's scale from the SERVER payload and never
 *      recomputes it from the nodes it was handed.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
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

vi.mock("../../lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/admin")>();
  return {
    ...actual,
    fetchMe: vi.fn().mockResolvedValue({
      id: "u-operator",
      email: "operator@example.com",
      name: "",
      isAdmin: true,
    }),
  };
});

vi.mock("../../lib/api/agents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/agents")>();
  return { ...actual, fetchAgents: fetchAgentsMock, fetchAgentRuns: fetchAgentRunsMock };
});

const fetchCatalogMock = vi.hoisted(() => vi.fn());
const fetchProvidersMock = vi.hoisted(() => vi.fn());
const fetchAgentStatsMock = vi.hoisted(() => vi.fn());
const fetchProviderModelsMock = vi.hoisted(() => vi.fn());
const fetchProviderCatalogMock = vi.hoisted(() => vi.fn());

vi.mock("../../components/agents/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../components/agents/api")>();
  return {
    ...actual,
    fetchCatalog: fetchCatalogMock,
    fetchProviders: fetchProvidersMock,
    fetchAgentStats: fetchAgentStatsMock,
    fetchProviderModels: fetchProviderModelsMock,
    fetchProviderCatalog: fetchProviderCatalogMock,
  };
});

const fetchOrchestrationMapMock = vi.hoisted(() => vi.fn());

vi.mock("../../lib/api/agentPolicy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api/agentPolicy")>();
  return { ...actual, fetchOrchestrationMap: fetchOrchestrationMapMock };
});

import AgentsPage from "../../app/dashboard/agents/page";
import type { Catalog, CatalogAgent } from "../../components/agents/api";
import {
  catalogScale,
  catalogScaleLabel,
  honestAgentCount,
} from "../../components/agents/catalog-counts";
import { runEverythingLabel } from "../../components/agents/conductor";
import { buildMapModel } from "../../components/agents/orchestration-map-model";
import type {
  OrchestrationMapData,
  OrchestrationMapEntry,
} from "../../lib/api/agentPolicy";
import type { OrchestrationPlan } from "../../lib/api/orchestrationPlan";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// 1 + 2. The derivation itself
// ---------------------------------------------------------------------------

/** The real production shape: 20 distinct engines behind 22 catalog cards. */
const PROD_COUNTS: Catalog["counts"] = {
  total: 22,
  engines: 20,
  cards: 22,
  active: 22,
  paused: 0,
  error: 0,
  planned: 0,
};

describe("AUD-AGENT-4 — catalog scale is a dual disclosure, never 'N agents'", () => {
  it("states both server numbers", () => {
    expect(catalogScaleLabel(PROD_COUNTS)).toBe("20 engines powering 22 cards");
    expect(catalogScale(PROD_COUNTS)).toEqual({ engines: 20, cards: 22 });
  });

  it("never blends the two into a single agent count", () => {
    expect(catalogScaleLabel(PROD_COUNTS)).not.toMatch(/\d+ agents/);
  });

  it("reports the ENGINE count — each backend once — as the agent count", () => {
    expect(honestAgentCount(PROD_COUNTS)).toBe(20);
    // The padded card total is never the answer.
    expect(honestAgentCount(PROD_COUNTS)).not.toBe(PROD_COUNTS.total);
  });

  it("states NO count when the server sent no honest basis — never the padded total", () => {
    const legacy: Catalog["counts"] = {
      total: 22,
      active: 22,
      paused: 0,
      error: 0,
      planned: 0,
    };
    expect(catalogScaleLabel(legacy)).toBeNull();
    expect(honestAgentCount(legacy)).toBeNull();
    expect(catalogScaleLabel(null)).toBeNull();
    expect(honestAgentCount(undefined)).toBeNull();
  });

  it("tracks whatever the server derived — the numbers are not written here", () => {
    expect(catalogScaleLabel({ ...PROD_COUNTS, engines: 4, cards: 5 })).toBe(
      "4 engines powering 5 cards",
    );
    expect(catalogScaleLabel({ ...PROD_COUNTS, engines: 1, cards: 1 })).toBe(
      "1 engine powering 1 card",
    );
  });
});

// ---------------------------------------------------------------------------
// 5. The conductor label is the same arithmetic and stays server-derived
// ---------------------------------------------------------------------------

describe("AUD-AGENT-4 — the conductor's counts stay server-derived", () => {
  it("keeps reading the plan's own two numbers", () => {
    const plan = { agentCount: 19, cardCount: 21 } as OrchestrationPlan;
    expect(runEverythingLabel(plan)).toBe("Run everything (19 agents / 21 cards)");
    expect(runEverythingLabel(null)).toBe("Run everything");
  });
});

// ---------------------------------------------------------------------------
// 3 + 4. The rendered screen
// ---------------------------------------------------------------------------

function card(key: string, backend: string, name: string): CatalogAgent {
  return {
    key,
    name,
    icon: "fa-robot",
    accent: "indigo",
    model: "deterministic",
    recommended: "deterministic",
    tip: "",
    runnable: true,
    backend,
    enabled: true,
    status: "active",
    modelOverridable: false,
    last_run: null,
  };
}

// Three cards, ONE engine — the exact padding AUD-AGENT-4 names, scaled down
// so a wrong number ("3 agents") is unmistakable in the assertion.
const AGENTS: CatalogAgent[] = [
  card("matchScoring", "fitScorer", "Match Scoring Agent"),
  card("atsOptimization", "fitScorer", "ATS Optimization Agent"),
  card("skillGap", "fitScorer", "Skill Gap Agent"),
];

const CATALOG: Catalog = {
  agents: AGENTS,
  counts: { total: 3, engines: 1, cards: 3, active: 3, paused: 0, error: 0, planned: 0 },
};

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

function mockLoad() {
  fetchCatalogMock.mockResolvedValue(CATALOG);
  fetchProvidersMock.mockResolvedValue([]);
  fetchAgentStatsMock.mockResolvedValue(STATS);
  fetchAgentsMock.mockResolvedValue([]);
  fetchAgentRunsMock.mockResolvedValue([]);
  fetchProviderModelsMock.mockResolvedValue([]);
  fetchProviderCatalogMock.mockResolvedValue({
    provider: "openrouter",
    count: 0,
    models: [],
    lastRefreshedAt: null,
    stale: false,
  });
  // No maps unless a test supplies them — the Orchestration tab then renders
  // nothing rather than a half-built section.
  fetchOrchestrationMapMock.mockResolvedValue({ maps: [] });
}

// ---------------------------------------------------------------------------
// 6 + 3(third surface). The Orchestration tab — the SAME screen, round 2
// ---------------------------------------------------------------------------

function mapAgent(agentKey: string, backend: string | null, name: string) {
  return {
    agentKey,
    name,
    backend,
    status: (backend ? "real" : "planned") as "real" | "planned",
    runnable: Boolean(backend),
    metricsConsumed: [],
    thresholds: [],
    lastRunPolicyTier: null,
    lastRunAt: null,
    lastRunStatus: null,
    trend: null,
  };
}

/**
 * FOUR cards, TWO engines — the production padding in miniature.
 *
 * "Fit Scoring" holds the three `fitScorer` facets exactly as
 * `_ORCHESTRATION_MAPS` does, so a header that sums nodes says "4 agents"
 * while the truth is two engines. The wrong number is unmistakable.
 */
const PIPELINE_ENTRY: OrchestrationMapEntry = {
  key: "application-pipeline",
  name: "Application Pipeline",
  subtitle: null,
  counts: { engines: 2, cards: 4 },
  stages: [
    { stage: "Discovery", agents: [mapAgent("jobDiscovery", "scout", "Job Discovery Agent")] },
    {
      stage: "Fit Scoring",
      agents: [
        mapAgent("matchScoring", "fitScorer", "Match Scoring Agent"),
        mapAgent("atsOptimization", "fitScorer", "ATS Optimization Agent"),
        mapAgent("skillGap", "fitScorer", "Skill Gap Agent"),
      ],
    },
  ],
};

describe("AUD-AGENT-4 — a workflow map's scale is the server's, not a node sum", () => {
  it("carries the payload's engines/cards, not the count of nodes it holds", () => {
    const model = buildMapModel(PIPELINE_ENTRY, [], Date.now());
    const nodeTotal = model.stages.reduce((n, s) => n + s.nodes.length, 0);

    expect(nodeTotal).toBe(4);
    expect(model.scale).toEqual({ engines: 2, cards: 4 });
    // The old header rendered `nodeTotal` as "agents". It never can again.
    expect(model.scale?.engines).not.toBe(nodeTotal);
  });

  it("transmits, never recomputes — it tracks the server even when they differ", () => {
    const model = buildMapModel(
      { ...PIPELINE_ENTRY, counts: { engines: 7, cards: 9 } },
      [],
      Date.now(),
    );
    expect(model.scale).toEqual({ engines: 7, cards: 9 });
  });

  it("states NO scale when the server sent no honest basis", () => {
    const legacy = { ...PIPELINE_ENTRY };
    delete (legacy as { counts?: unknown }).counts;
    expect(buildMapModel(legacy, [], Date.now()).scale).toBeNull();
  });
});

describe("AUD-AGENT-4 — the Orchestration tab claims no standalone agents", () => {
  it("renders the map header as the server-derived dual disclosure", async () => {
    mockLoad();
    fetchOrchestrationMapMock.mockResolvedValue({
      maps: [PIPELINE_ENTRY],
    } as OrchestrationMapData);
    render(<AgentsPage />);

    const section = await screen.findByTestId("orchestration-map-application-pipeline");
    const scale = within(section).getByTestId(
      "orchestration-map-scale-application-pipeline",
    );
    expect(scale.textContent).toContain("2 engines powering 4 cards");
  });

  it("never says 'N agents' anywhere in the map it renders", async () => {
    mockLoad();
    fetchOrchestrationMapMock.mockResolvedValue({
      maps: [PIPELINE_ENTRY],
    } as OrchestrationMapData);
    render(<AgentsPage />);

    const section = await screen.findByTestId("orchestration-map-application-pipeline");
    const text = section.textContent ?? "";
    // Both candidate claims are named literally: "4 agents" is the node sum
    // this fix removes, "2 agents" would be the engine count relabelled as a
    // standalone agent count instead of disclosed as one half of a pair.
    // (A regex is deliberately NOT used here: `textContent` concatenates
    // sibling nodes with no separator, so "…4 agentsRun workflow" defeats a
    // trailing \b and the assertion would silently never fire.)
    expect(text).not.toContain("4 agents");
    expect(text).not.toContain("2 agents");
    expect(text).toContain("2 engines powering 4 cards");

    // Including the run control's own tooltip, which is not rendered text.
    const run = within(section).getByTestId(
      "orchestration-run-workflow-application-pipeline",
    );
    const title = run.getAttribute("title") ?? "";
    expect(title).not.toMatch(/\d+\s+(?:\S+\s+){0,2}agents?\b/i);
  });
});

describe("AUD-AGENT-4 — the Agents screen never claims a padded agent count", () => {
  it("renders the dual disclosure in the hero subline and the grid header", async () => {
    mockLoad();
    render(<AgentsPage />);

    const subline = await screen.findByTestId("agents-subline");
    await waitFor(() =>
      expect(subline.textContent).toContain("1 engine powering 3 cards"),
    );
    expect(subline.textContent).not.toMatch(/\d+ agents/);

    const scale = await screen.findByTestId("catalog-scale");
    expect(scale.textContent).toBe("1 engine powering 3 cards");
    expect(scale.textContent).not.toMatch(/\d+ agents/);
  });

  it("puts the ENGINE count on the tab badge labelled 'Agents'", async () => {
    mockLoad();
    render(<AgentsPage />);

    const tab = await screen.findByTestId("agents-tabs-tab-agents");
    // One engine behind three cards: the badge says 1, never 3.
    await waitFor(() => expect(tab.textContent).toBe("Agents1"));
    expect(tab.textContent).not.toContain("3");
  });
});
