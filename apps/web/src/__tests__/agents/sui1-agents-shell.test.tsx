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
