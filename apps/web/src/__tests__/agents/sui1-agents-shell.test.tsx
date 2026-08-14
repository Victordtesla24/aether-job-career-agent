// @vitest-environment jsdom
/**
 * S-UI-1 — the Agents console's new shell and the orchestration map hero.
 *
 * These cover the BEHAVIOUR the redesign introduces (everything else in the
 * slice is presentation and is covered by the existing, unmodified suites):
 *
 *   1. Tab routing — three linkable `?tab=` panels, Orchestration by default,
 *      Back/Forward correct, and an unknown value degrading to the default
 *      rather than to a blank screen.
 *   2. The accessible rendition is the BASE — with no WebGL context available
 *      (jsdom, and any hardened browser) the DOM/SVG map renders with the
 *      identical data set and the WebGL layer is never mounted.
 *   3. Honest motion — the map's ONLY moving parts belong to runs that are
 *      genuinely in flight. A stalled run produces no motion anywhere, reads
 *      as `warn` with its elapsed time, and a planned agent can never be live.
 *   4. Portal picker parity — moving the model list out of the grid cell must
 *      not change what selecting a model does: still one
 *      `updateAgentConfig(agentKey, { model })`, never `updateProvider`.
 *   5. The BINDING transferred defect (U-AX-V4, S-UI-BINDING-CONSTRAINTS.md:12):
 *      `lastRunStatus` + `lastRunAt` are read from the per-agent, UNWINDOWED
 *      orchestration-map payload — not silently flattened to "Idle" when the
 *      shared 50-row `GET /agents/runs` window happens not to hold that
 *      agent's run — and both fields are rendered on the node.
 *   6. Continuation honesty — a map wider than its content column states which
 *      stages are actually visible and which one is next, and claims nothing
 *      at all until it has measured itself.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  return {
    ...actual,
    fetchAgents: fetchAgentsMock,
    fetchAgentRuns: fetchAgentRunsMock,
    runAgent: runAgentMock,
    runPipeline: runPipelineMock,
  };
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
import OrchestrationMap from "../../components/agents/OrchestrationMap";
import {
  lastRunStatusText,
  nodeBadge,
  relativeRunLabel,
  resolveNodeState,
  visibleStageRange,
} from "../../components/agents/orchestration-map-model";
import type { Catalog, CatalogAgent, Provider } from "../../components/agents/api";
import type { AgentRun } from "../../lib/api/agents";
import type { OrchestrationMapData } from "../../lib/api/agentPolicy";
import { RUNNING_STALE_MS } from "../../lib/agent-run-health";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

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
  counts: { total: AGENTS.length, active: 1, paused: 0, error: 0, planned: 1 },
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

const CATALOG_MODELS = [
  {
    id: "deepseek/deepseek-chat",
    name: "DeepSeek Chat",
    promptPerM: 0.14,
    completionPerM: 0.28,
    contextLength: 128000,
    tier: "budget" as const,
    reasoning: false,
  },
  {
    id: "anthropic/claude-opus",
    name: "Claude Opus",
    promptPerM: 15,
    completionPerM: 75,
    contextLength: 200000,
    tier: "premium" as const,
    reasoning: true,
  },
];

function mockHappyPathLoad() {
  fetchCatalogMock.mockResolvedValue(CATALOG);
  fetchProvidersMock.mockResolvedValue(PROVIDERS);
  fetchAgentStatsMock.mockResolvedValue(STATS);
  fetchAgentsMock.mockResolvedValue([]);
  fetchAgentRunsMock.mockResolvedValue([]);
  fetchProviderModelsMock.mockResolvedValue(CATALOG_MODELS);
  fetchProviderCatalogMock.mockResolvedValue({
    provider: "openrouter",
    count: CATALOG_MODELS.length,
    models: CATALOG_MODELS,
    lastRefreshedAt: "2026-08-14T01:00:00.000Z",
    stale: false,
  });
}

function setSearch(search: string) {
  window.history.replaceState({}, "", `/dashboard/agents${search}`);
}

beforeEach(() => setSearch(""));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  setSearch("");
});

// ---------------------------------------------------------------------------
// 1. Tab routing
// ---------------------------------------------------------------------------

describe("S-UI-1 — the Agents console is three linkable tabs, Orchestration first", () => {
  it("defaults to the Orchestration tab when no ?tab= is present", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    await screen.findByTestId("agents-tabs");
    expect(screen.getByTestId("agents-tabs-tab-orchestration").getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(screen.getByTestId("agents-tabs-tab-agents").getAttribute("aria-selected")).toBe("false");
    // The orchestration panel is the one on screen; the others are hidden but
    // MOUNTED (no refetch on switch, everything stays keyboard-reachable).
    expect(screen.getByTestId("agents-panel-orchestration").hasAttribute("hidden")).toBe(false);
    expect(screen.getByTestId("agents-panel-agents").hasAttribute("hidden")).toBe(true);
    expect(screen.getByTestId("agents-panel-providers").hasAttribute("hidden")).toBe(true);
  });

  it("a ?tab= link opens that tab directly", async () => {
    mockHappyPathLoad();
    setSearch("?tab=providers");
    render(<AgentsPage />);

    await waitFor(() =>
      expect(screen.getByTestId("agents-panel-providers").hasAttribute("hidden")).toBe(false),
    );
    expect(screen.getByTestId("agents-panel-orchestration").hasAttribute("hidden")).toBe(true);
  });

  it("an unknown ?tab= value degrades to Orchestration instead of a blank screen", async () => {
    mockHappyPathLoad();
    setSearch("?tab=not-a-tab");
    render(<AgentsPage />);

    await screen.findByTestId("agents-tabs");
    await waitFor(() =>
      expect(screen.getByTestId("agents-panel-orchestration").hasAttribute("hidden")).toBe(false),
    );
  });

  it("selecting a tab writes ?tab= to the URL, and Back returns to the previous tab", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    await screen.findByTestId("agents-tabs");
    fireEvent.click(screen.getByTestId("agents-tabs-tab-agents"));

    await waitFor(() =>
      expect(screen.getByTestId("agents-panel-agents").hasAttribute("hidden")).toBe(false),
    );
    expect(new URLSearchParams(window.location.search).get("tab")).toBe("agents");

    // jsdom does not implement history traversal, so drive the same event the
    // browser fires on Back — which is what the page actually listens for.
    setSearch("");
    fireEvent.popState(window);
    await waitFor(() =>
      expect(screen.getByTestId("agents-panel-orchestration").hasAttribute("hidden")).toBe(false),
    );
  });

  it("switching tabs issues no new requests — the wiring is untouched", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    await screen.findByTestId("agents-tabs");
    await waitFor(() => expect(fetchCatalogMock).toHaveBeenCalled());
    const before = {
      catalog: fetchCatalogMock.mock.calls.length,
      providers: fetchProvidersMock.mock.calls.length,
      runs: fetchAgentRunsMock.mock.calls.length,
      stats: fetchAgentStatsMock.mock.calls.length,
    };

    fireEvent.click(screen.getByTestId("agents-tabs-tab-agents"));
    fireEvent.click(screen.getByTestId("agents-tabs-tab-providers"));
    fireEvent.click(screen.getByTestId("agents-tabs-tab-orchestration"));

    expect(fetchCatalogMock.mock.calls.length).toBe(before.catalog);
    expect(fetchProvidersMock.mock.calls.length).toBe(before.providers);
    expect(fetchAgentRunsMock.mock.calls.length).toBe(before.runs);
    expect(fetchAgentStatsMock.mock.calls.length).toBe(before.stats);
  });
});

// ---------------------------------------------------------------------------
// 2 + 3. The map: accessible base, identical data, honest motion
// ---------------------------------------------------------------------------

function realAgent(key: string, backend: string) {
  return {
    agentKey: key,
    name: key,
    backend,
    status: "real" as const,
    metricsConsumed: ["conversionRate"],
    thresholds: ["conversion>=20%"],
    lastRunPolicyTier: null,
    trend: null,
  };
}

function plannedAgent(key: string) {
  return {
    agentKey: key,
    name: key,
    backend: null,
    status: "planned" as const,
    metricsConsumed: [],
    thresholds: [],
    lastRunPolicyTier: null,
    trend: null,
  };
}

const MAP_DATA: OrchestrationMapData = {
  maps: [
    {
      key: "application-pipeline",
      name: "Application Pipeline",
      subtitle: "Discover → tailor → submit",
      stages: [
        { stage: "discovery", agents: [realAgent("scout", "scout")] },
        { stage: "tailoring", agents: [realAgent("tailor", "tailor")] },
        { stage: "compliance", agents: [plannedAgent("compliance")] },
      ],
    },
  ],
};

const NOW = Date.parse("2026-08-14T04:00:00.000Z");

function run(overrides: Partial<AgentRun> & { id: string; agentName: string }): AgentRun {
  return {
    status: "running",
    createdAt: new Date(NOW - 60_000).toISOString(),
    startedAt: new Date(NOW - 60_000).toISOString(),
    completedAt: null,
    error: null,
    output: null,
    ...overrides,
  } as AgentRun;
}

describe("S-UI-1 — the orchestration map's accessible rendition is the base, not the fallback", () => {
  it("renders every agent and stage with no WebGL context available", () => {
    render(<OrchestrationMap data={MAP_DATA} runs={[]} now={NOW} />);

    expect(screen.getByTestId("orchestration-map")).toBeTruthy();
    for (const key of ["scout", "tailor", "compliance"]) {
      expect(screen.getByTestId(`orchestration-agent-${key}`)).toBeTruthy();
    }
    expect(screen.getByTestId("orchestration-stage-discovery")).toBeTruthy();
    expect(screen.getByTestId("orchestration-stage-tailoring")).toBeTruthy();
    // The SVG edge layer is always present…
    expect(screen.getByTestId("orchestration-edges-application-pipeline")).toBeTruthy();
    // …and the WebGL layer is never mounted without a context (jsdom has none).
    expect(screen.queryByTestId("orchestration-gl-application-pipeline")).toBeNull();
  });

  it("states the stage order in words as well as in curves", () => {
    render(<OrchestrationMap data={MAP_DATA} runs={[]} now={NOW} />);
    const topology = screen.getByTestId("orchestration-topology-application-pipeline");
    expect(topology.textContent ?? "").toMatch(/discovery then tailoring then compliance/i);
  });

  it("keeps the required 'DEFINED pipeline, not a live trace' disclosure visible, not in a tooltip", () => {
    render(<OrchestrationMap data={MAP_DATA} runs={[]} now={NOW} />);
    const footnote = screen.getByTestId("orchestration-footnote-application-pipeline");
    expect(footnote.textContent ?? "").toContain(
      "Stage order is the DEFINED pipeline, not a live trace.",
    );
  });
});

describe("S-UI-1 — nothing moves on the map unless something is genuinely moving", () => {
  it("marks a node with a live, in-flight run as the ONLY moving node", () => {
    render(
      <OrchestrationMap
        data={MAP_DATA}
        runs={[run({ id: "r1", agentName: "tailor" })]}
        now={NOW}
      />,
    );

    expect(screen.getByTestId("orchestration-agent-tailor").getAttribute("data-motion")).toBe(
      "pulse",
    );
    expect(screen.getByTestId("orchestration-agent-scout").getAttribute("data-motion")).toBe("none");
    expect(screen.getByTestId("orchestration-agent-compliance").getAttribute("data-motion")).toBe(
      "none",
    );
  });

  it("gives a STALLED run no motion at all — it reads as warn, with its elapsed time", () => {
    const stalledStart = new Date(NOW - (RUNNING_STALE_MS + 60 * 60_000)).toISOString();
    render(
      <OrchestrationMap
        data={MAP_DATA}
        runs={[run({ id: "r2", agentName: "tailor", createdAt: stalledStart, startedAt: stalledStart })]}
        now={NOW}
      />,
    );

    const node = screen.getByTestId("orchestration-agent-tailor");
    expect(node.getAttribute("data-motion")).toBe("none");
    expect(node.getAttribute("data-state")).toBe("stalled");
    expect(node.textContent ?? "").toMatch(/stalled/i);
    expect(node.textContent ?? "").not.toMatch(/\brunning\b/i);
    // …and the map says so in the footnote rather than leaving it implied.
    expect(
      screen.getByTestId("orchestration-footnote-application-pipeline").textContent ?? "",
    ).toMatch(/stalled/i);
  });

  it("never lets a planned agent be live, tiered, or anything but 'Planned — roadmap'", () => {
    render(
      <OrchestrationMap
        data={MAP_DATA}
        // A run whose agentName collides with a planned agent's KEY must still
        // not light it up: a planned entry has no backend, so it can never match.
        runs={[run({ id: "r3", agentName: "compliance" })]}
        now={NOW}
      />,
    );

    const node = screen.getByTestId("orchestration-agent-compliance");
    expect(node.getAttribute("data-motion")).toBe("none");
    expect(node.getAttribute("data-state")).toBe("planned");
    expect(node.textContent ?? "").toContain("Planned — roadmap");
    expect(node.textContent ?? "").not.toMatch(/\bactive\b|\brunning\b|\blive\b/i);
  });
});

// ---------------------------------------------------------------------------
// 3b. The gate that decides whether the WebGL layer may run at all
// ---------------------------------------------------------------------------

describe("S-UI-1 — the WebGL layer is gated on capability AND on consent", () => {
  function stubEnvironment({ webgl, reduced }: { webgl: boolean; reduced: boolean }) {
    const realGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function stub(this: HTMLCanvasElement, id: string) {
      if (id === "webgl2" || id === "webgl" || id === "experimental-webgl") {
        return webgl ? ({ getExtension: () => null } as unknown as RenderingContext) : null;
      }
      return realGetContext.call(this, id) as RenderingContext | null;
    } as typeof HTMLCanvasElement.prototype.getContext;

    const realMatchMedia = window.matchMedia;
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: (query: string) => ({
        matches: reduced && query.includes("prefers-reduced-motion"),
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }),
    });

    return () => {
      HTMLCanvasElement.prototype.getContext = realGetContext;
      Object.defineProperty(window, "matchMedia", {
        configurable: true,
        writable: true,
        value: realMatchMedia,
      });
    };
  }

  it("reports allowGl only when a context exists AND the viewer has not asked for less motion", async () => {
    const { renderHook } = await import("@testing-library/react");
    const { useRenderCapabilities } = await import("../../hooks/useRenderCapabilities");

    let restore = stubEnvironment({ webgl: true, reduced: false });
    const ok = renderHook(() => useRenderCapabilities());
    await waitFor(() => expect(ok.result.current.allowGl).toBe(true));
    ok.unmount();
    restore();

    restore = stubEnvironment({ webgl: true, reduced: true });
    const quiet = renderHook(() => useRenderCapabilities());
    await waitFor(() => expect(quiet.result.current.reducedMotion).toBe(true));
    expect(
      quiet.result.current.allowGl,
      "a viewer who asked for reduced motion must not get a GPU particle field",
    ).toBe(false);
    quiet.unmount();
    restore();

    restore = stubEnvironment({ webgl: false, reduced: false });
    const noGl = renderHook(() => useRenderCapabilities());
    await waitFor(() => expect(noGl.result.current.webgl).toBe(false));
    expect(noGl.result.current.allowGl).toBe(false);
    noGl.unmount();
    restore();
  });

  it("survives a context that is refused at construction time — the SVG map below is untouched", async () => {
    // Capability is probed before mounting, but a browser can still refuse the
    // real context (too many live contexts, driver reset). That must degrade
    // silently onto the layer that already drew the same edges.
    const { default: OrchestrationMapGL } = await import(
      "../../components/agents/OrchestrationMapGL"
    );
    expect(() =>
      render(
        <OrchestrationMapGL
          mapKey="application-pipeline"
          width={800}
          height={300}
          edges={[{ key: "e1", state: "active", x1: 0, y1: 10, x2: 200, y2: 10 }]}
          nodes={[{ id: "tailor", x: 0, y: 0, w: 180, h: 92, live: true }]}
        />,
      ),
    ).not.toThrow();
    expect(screen.getByTestId("orchestration-gl-application-pipeline")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// 4. Portal picker parity
// ---------------------------------------------------------------------------

describe("S-UI-1 — the model picker moved out of the grid cell without changing what it does", () => {
  it("renders the picker panel OUTSIDE the agent card (that is the card-height fix)", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    const card = await screen.findByTestId("agent-card-resumeTailoring");
    const picker = await screen.findByTestId("agent-model-picker-resumeTailoring");

    expect(
      card.contains(picker),
      "the model list must not be a DOM descendant of the grid cell — an " +
        "expanding list inside a cell is the root cause of the broken masonry",
    ).toBe(false);
    // The card keeps a compact trigger in its place.
    expect(within(card).getByTestId("agent-model-trigger-resumeTailoring")).toBeTruthy();
  });

  it("still persists a pick with updateAgentConfig(agentKey, {model}) and never updateProvider", async () => {
    mockHappyPathLoad();
    updateAgentConfigMock.mockResolvedValue({
      key: "resumeTailoring",
      enabled: true,
      model: "anthropic/claude-opus",
      provider: null,
      authMode: null,
      credentialRef: null,
      temperature: 0.7,
      thinkingEffort: "medium",
    });
    render(<AgentsPage />);

    const trigger = await screen.findByTestId("agent-model-trigger-resumeTailoring");
    fireEvent.click(trigger);

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
    expect(updateProviderMock).not.toHaveBeenCalled();
  });

  it("opens and closes from the trigger, and Escape closes it", async () => {
    mockHappyPathLoad();
    render(<AgentsPage />);

    const trigger = await screen.findByTestId("agent-model-trigger-resumeTailoring");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(trigger.getAttribute("aria-expanded")).toBe("false"));
  });
});

// ---------------------------------------------------------------------------
// 5. The binding transferred defect (U-AX-V4): lastRunStatus + lastRunAt
//    S-UI-BINDING-CONSTRAINTS.md:12-13 — "Slice-1's NodeCard MUST render
//    lastRunAt (relative time) + lastRunStatus honestly, with test assertions
//    on both fields."
//
//    `GET /agents/runs` is a GLOBAL 50-row window shared by all 22 agents;
//    `GET /agents/orchestration-map` computes lastRunStatus/lastRunAt PER AGENT
//    with no window at all. When an agent's real last run has aged out of the
//    shared window, the unwindowed pair is the only truth left — and reading
//    "idle" instead is the same status-flattening U-AX-V4 was about.
// ---------------------------------------------------------------------------

function isoAt(ms: number): string {
  return new Date(ms).toISOString();
}

/** A real agent whose ONLY evidence is the unwindowed per-agent pair. */
function agentWithLastRun(
  key: string,
  backend: string,
  lastRunStatus: string | null,
  lastRunAt: string | null,
) {
  return { ...realAgent(key, backend), lastRunStatus, lastRunAt };
}

function mapWith(agent: ReturnType<typeof agentWithLastRun>): OrchestrationMapData {
  return {
    maps: [
      {
        key: "application-pipeline",
        name: "Application Pipeline",
        subtitle: null,
        stages: [{ stage: "tailoring", agents: [agent] }],
      },
    ],
  };
}

describe("S-UI-1 — lastRunStatus is consulted as ground truth (U-AX-V4, binding)", () => {
  it("reports a FAILED last run from agent.lastRunStatus when the shared run window has no row for that agent", () => {
    const agent = agentWithLastRun("tailor", "tailor", "failed", isoAt(NOW - 3 * 60 * 60_000));

    // The window contains 50 rows belonging to a busier agent — none for this one.
    const node = resolveNodeState(agent, [run({ id: "other", agentName: "scout" })], NOW);

    expect(node.lastRunStatus).toBe("failed");
    expect(node.state).toBe("failed");
    expect(node.source).toBe("catalog");
    expect(node.lastRunAt).toBe(agent.lastRunAt);
    expect(nodeBadge(node).label).toBe("Last run failed");
    expect(nodeBadge(node).tone).toBe("danger");
  });

  it("renders that failed status on the node itself instead of a neutral 'Idle'", () => {
    const agent = agentWithLastRun("tailor", "tailor", "failed", isoAt(NOW - 3 * 60 * 60_000));
    render(<OrchestrationMap data={mapWith(agent)} runs={[]} now={NOW} />);

    const node = screen.getByTestId("orchestration-agent-tailor");
    expect(node.getAttribute("data-state")).toBe("failed");
    expect(node.textContent ?? "").toContain("Last run failed");
    expect(node.textContent ?? "").not.toMatch(/\bidle\b/i);
    // lastRunAt, relative — the second field the binding constraint names.
    expect(screen.getByTestId("orchestration-agent-lastrun-tailor").textContent).toBe(
      "Last run 3 hr ago",
    );
    // …and lastRunStatus stated in words in the detail popover.
    expect(screen.getByTestId("orchestration-node-status-tailor").textContent).toBe("failed");
  });

  it("never turns an unwindowed in-flight lastRunStatus into motion once it is stale", () => {
    const stale = isoAt(NOW - (RUNNING_STALE_MS + 60 * 60_000));
    const agent = agentWithLastRun("tailor", "tailor", "running", stale);
    render(<OrchestrationMap data={mapWith(agent)} runs={[]} now={NOW} />);

    const node = screen.getByTestId("orchestration-agent-tailor");
    expect(node.getAttribute("data-state")).toBe("stalled");
    expect(node.getAttribute("data-motion")).toBe("none");
    expect(node.textContent ?? "").toMatch(/stalled/i);
    // The card face never says "running" for a row nothing is working on…
    expect(node.textContent ?? "").not.toMatch(/\brunning\b/i);
    // …and where the raw value IS quoted, the elapsed time comes first.
    const status = screen.getByTestId("orchestration-node-status-tailor").textContent ?? "";
    expect(status).toMatch(/^stalled for /);
    expect(status).toMatch(/recorded as "running", no worker attached/);
  });

  it("accepts an unwindowed in-flight lastRunStatus as live only inside the staleness window", () => {
    const agent = agentWithLastRun("tailor", "tailor", "running", isoAt(NOW - 60_000));
    const node = resolveNodeState(agent, [], NOW);

    expect(node.state).toBe("live");
    expect(node.lastRunStatus).toBe("running");
    expect(lastRunStatusText(node)).toBe("running");
  });

  it("treats an undateable in-flight lastRunStatus as stalled, never as life", () => {
    const node = resolveNodeState(agentWithLastRun("tailor", "tailor", "running", null), [], NOW);
    expect(node.state).toBe("stalled");
    expect(node.stalledText).toBe("stalled");
  });

  it("prefers the windowed run while it is the freshest evidence (it alone carries a heartbeat)", () => {
    // Catalog remembers an older FAILED run; the window holds a newer completed one.
    const agent = agentWithLastRun("tailor", "tailor", "failed", isoAt(NOW - 3 * 60 * 60_000));
    const newer = run({
      id: "r-new",
      agentName: "tailor",
      status: "completed",
      createdAt: isoAt(NOW - 60_000),
      startedAt: isoAt(NOW - 60_000),
      completedAt: isoAt(NOW - 30_000),
    });

    const node = resolveNodeState(agent, [newer], NOW);
    expect(node.source).toBe("runs");
    expect(node.state).toBe("idle");
    expect(node.lastRunStatus).toBe("completed");
  });

  it("prefers the unwindowed pair when it describes a strictly newer run than the window holds", () => {
    const agent = agentWithLastRun("tailor", "tailor", "failed", isoAt(NOW - 30_000));
    const older = run({
      id: "r-old",
      agentName: "tailor",
      status: "completed",
      createdAt: isoAt(NOW - 6 * 60 * 60_000),
      startedAt: isoAt(NOW - 6 * 60 * 60_000),
      completedAt: isoAt(NOW - 6 * 60 * 60_000),
    });

    const node = resolveNodeState(agent, [older], NOW);
    expect(node.source).toBe("catalog");
    expect(node.state).toBe("failed");
    expect(node.lastRunStatus).toBe("failed");
  });

  it("keeps a planned agent planned even if a lastRunStatus somehow appears on it", () => {
    const planned = { ...plannedAgent("compliance"), lastRunStatus: "running", lastRunAt: isoAt(NOW) };
    const node = resolveNodeState(planned, [], NOW);

    expect(node.state).toBe("planned");
    expect(node.lastRunStatus).toBeNull();
    expect(node.lastRunText).toBeNull();
    expect(lastRunStatusText(node)).toBe("—");
    expect(nodeBadge(node).label).toBe("Planned — roadmap");
  });

  it("says 'No runs recorded yet' only when NEITHER source has a run", () => {
    const agent = agentWithLastRun("tailor", "tailor", null, null);
    const node = resolveNodeState(agent, [], NOW);
    expect(node.source).toBe("none");
    expect(node.lastRunStatus).toBeNull();

    render(<OrchestrationMap data={mapWith(agent)} runs={[]} now={NOW} />);
    expect(screen.getByTestId("orchestration-agent-lastrun-tailor").textContent).toBe(
      "No runs recorded yet",
    );
    expect(screen.getByTestId("orchestration-node-status-tailor").textContent).toBe("—");
  });

  it("formats lastRunAt relatively, and claims nothing when there is no stamp", () => {
    expect(relativeRunLabel(null, NOW)).toBeNull();
    expect(relativeRunLabel(isoAt(NOW - 5_000), NOW)).toBe("just now");
    expect(relativeRunLabel(isoAt(NOW - 14 * 60_000), NOW)).toBe("14 min ago");
    expect(relativeRunLabel(isoAt(NOW - 3 * 60 * 60_000), NOW)).toBe("3 hr ago");
    expect(relativeRunLabel(isoAt(NOW - 8 * 24 * 60 * 60_000), NOW)).toBe("8 days ago");
  });
});

// ---------------------------------------------------------------------------
// 6. The map states how much of itself is visible (S-UI-1 review finding 2)
// ---------------------------------------------------------------------------

describe("S-UI-1 — a map wider than its column announces the stages past the fold", () => {
  const columns = [
    { left: 0, right: 136 },
    { left: 156, right: 292 },
    { left: 312, right: 448 },
    { left: 468, right: 604 },
    { left: 624, right: 760 },
    { left: 780, right: 916 },
    { left: 936, right: 1072 },
  ];

  it("reports only the stages that are FULLY visible — a half-clipped stage counts as hidden", () => {
    // 926px of content column: the width the review measured at a 1280px viewport.
    expect(visibleStageRange(columns, 0, 926)).toEqual({ first: 0, last: 5, hidden: 1 });
  });

  it("moves the window as the viewer scrolls", () => {
    expect(visibleStageRange(columns, 146, 926)).toEqual({ first: 1, last: 6, hidden: 1 });
  });

  it("reports every stage visible once the map fits, which is when no hint is shown", () => {
    expect(visibleStageRange(columns, 0, 1086)).toEqual({ first: 0, last: 6, hidden: 0 });
  });

  it("claims no window at all before anything has been measured", () => {
    expect(visibleStageRange([], 0, 926)).toBeNull();
    expect(visibleStageRange(columns, 0, 0)).toBeNull();
  });

  it("renders no scroll hint and no scrims in an unmeasured layout (jsdom) — never a guess", () => {
    render(<OrchestrationMap data={MAP_DATA} runs={[]} now={NOW} />);
    expect(screen.queryByTestId("orchestration-scroll-hint-application-pipeline")).toBeNull();
    expect(screen.queryByTestId("orchestration-scrim-right-application-pipeline")).toBeNull();
    // The scrollable region stays keyboard-reachable in its own right (WCAG 2.1.1).
    const graph = screen.getByTestId("orchestration-graph-application-pipeline");
    expect(graph.getAttribute("tabindex")).toBe("0");
    expect(graph.getAttribute("role")).toBe("group");
  });
});
