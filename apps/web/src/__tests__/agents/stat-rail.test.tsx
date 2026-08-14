// @vitest-environment jsdom
/**
 * S-UI B2 NIT — the Agents console STAT RAIL (`agents-run-health`).
 *
 * The B1/beauty-1 certification praised this rail — "20 ONLINE / 0 RUNNING /
 * 0 STALLED as a proper Mercury figure-over-label pair" — and then noted it
 * carried **no test at all**. A `grep` for `agents-run-health` across
 * `src/__tests__` and `e2e/` returned nothing before this file. That is the
 * gap: the rail is the highest-traffic *numeric claim* on the console (it is
 * `role="status" aria-live="polite"`, so it is also read aloud), and three of
 * its properties are honesty contracts rather than cosmetics:
 *
 *   1. MOTION IS A CLAIM (D-β). The coral `.live-dot` pulse on "running" may
 *      appear only when a run is genuinely in flight. At zero the dot must be
 *      static and `state-neutral` — a pulsing zero would animate nothing
 *      happening.
 *   2. ZERO IS NOT AN ALARM, AND NOT A SUCCESS (Rule D-1). "stalled" turns
 *      `state-warn` only when something really is stalled; at zero it stays
 *      `state-neutral` — never warn (false alarm), never ok-green (a zero is
 *      not an achievement, it is an absence).
 *   3. THE WINDOW IS PART OF THE FIGURE (C-3). The rail counts only the runs
 *      this console actually loaded, and says so with the REAL number and
 *      correct pluralisation — never a rounded or implied "all runs".
 *
 * These are page-level assertions on the real `AgentsPage`; the mock surface is
 * the same one `stale-run-honesty.test.tsx` uses, so both files exercise the
 * console through its genuine data path.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
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
  };
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

import AgentsPage from "../../app/dashboard/agents/page";
import type { AgentRun } from "../../lib/api/agents";
import type { Catalog, Provider } from "../../components/agents/api";

const MIN = 60_000;
const DAY = 24 * 60 * MIN;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

function run(overrides: Partial<AgentRun> & { id: string }): AgentRun {
  const created = overrides.createdAt ?? ago(5 * MIN);
  return {
    agentName: "tailor",
    status: "completed",
    input: null,
    output: null,
    error: null,
    costUsd: null,
    startedAt: created,
    completedAt: created,
    ...overrides,
    createdAt: created,
  };
}

/** A run started 90 s ago and still going — genuinely live. */
const LIVE_RUN = run({
  id: "live",
  status: "running",
  createdAt: ago(90_000),
  startedAt: ago(90_000),
  completedAt: null,
});

/** The production shape of a dead row: "running" since 8 days ago. */
const STALLED_RUN = run({
  id: "stalled",
  status: "running",
  createdAt: ago(8 * DAY),
  startedAt: ago(8 * DAY),
  completedAt: null,
});

const CATALOG: Catalog = {
  agents: [
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
  ],
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

function mockLoad(runs: AgentRun[]) {
  fetchCatalogMock.mockResolvedValue(CATALOG);
  fetchProvidersMock.mockResolvedValue(PROVIDERS);
  fetchAgentStatsMock.mockResolvedValue(STATS);
  fetchAgentsMock.mockResolvedValue([]);
  fetchAgentRunsMock.mockResolvedValue(runs);
  fetchProviderModelsMock.mockResolvedValue([]);
  fetchProviderCatalogMock.mockResolvedValue({ models: [], lastRefreshedAt: null, stale: false });
}

/** The rail, once the console has loaded. */
async function rail() {
  render(<AgentsPage />);
  return screen.findByTestId("agents-run-health");
}

/** The `.ag-stat` block whose label is `word`. */
function stat(el: HTMLElement, word: string): HTMLElement {
  const found = Array.from(el.querySelectorAll<HTMLElement>(".ag-stat")).find((s) =>
    Array.from(s.querySelectorAll(".ag-stat-label")).some(
      (l) => (l.textContent ?? "").trim() === word,
    ),
  );
  if (!found) throw new Error(`no .ag-stat labelled "${word}" in the rail`);
  return found;
}

const figureText = (s: HTMLElement) =>
  (s.querySelector(".ag-stat-figure")?.textContent ?? "").trim();

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockLoad([]);
});

describe("Agents stat rail — it is a live region, and it counts", () => {
  it("is announced politely, because these numbers change under the reader", async () => {
    const el = await rail();
    expect(el.getAttribute("role")).toBe("status");
    expect(el.getAttribute("aria-live")).toBe("polite");
  });

  it("labels all three figures in words, so colour is never the only signal (C-5)", async () => {
    const el = await rail();
    for (const word of ["online", "running", "stalled"]) {
      expect(within(el).getByText(word)).toBeTruthy();
    }
  });
});

describe("Agents stat rail — motion is a claim (D-β)", () => {
  it("pulses the running dot ONLY while a run is genuinely in flight", async () => {
    mockLoad([LIVE_RUN]);
    const el = await rail();
    const running = stat(el, "running");
    expect(figureText(running)).toBe("1");
    // `.live-dot` is the pulse-ring animation. It is earned here.
    expect(running.querySelector(".live-dot")).not.toBeNull();
  });

  it("does NOT pulse at zero — a breathing dot beside a 0 animates nothing happening", async () => {
    mockLoad([run({ id: "done" })]);
    const el = await rail();
    const running = stat(el, "running");
    expect(figureText(running)).toBe("0");
    expect(running.querySelector(".live-dot")).toBeNull();
    // …and the static dot is neutral, not coral: coral is reserved for live.
    expect(running.innerHTML).toContain("bg-state-neutral");
    expect(running.innerHTML).not.toContain("bg-aether-coral");
  });

  it("counts a STALLED run as running=0 — a dead row is not work in progress (CRITICAL-2)", async () => {
    mockLoad([STALLED_RUN]);
    const el = await rail();
    expect(figureText(stat(el, "running"))).toBe("0");
    expect(stat(el, "running").querySelector(".live-dot")).toBeNull();
    expect(figureText(stat(el, "stalled"))).toBe("1");
  });
});

describe("Agents stat rail — zero is neither an alarm nor an achievement (Rule D-1)", () => {
  it("keeps 'stalled' neutral at zero: no warn tone, and never an ok-green", async () => {
    mockLoad([run({ id: "done" })]);
    const el = await rail();
    const stalled = stat(el, "stalled");
    expect(figureText(stalled)).toBe("0");
    expect(stalled.className).not.toContain("text-state-warn");
    expect(stalled.innerHTML).toContain("bg-state-neutral");
    expect(stalled.innerHTML).not.toContain("bg-state-warn");
    expect(stalled.innerHTML).not.toContain("bg-state-ok");
  });

  it("turns 'stalled' warn ONLY when something really is stalled", async () => {
    mockLoad([STALLED_RUN]);
    const el = await rail();
    const stalled = stat(el, "stalled");
    expect(figureText(stalled)).toBe("1");
    expect(stalled.className).toContain("text-state-warn");
    expect(stalled.innerHTML).toContain("bg-state-warn");
  });
});

describe("Agents stat rail — the window is part of the figure (C-3)", () => {
  it("states the REAL number of runs it counted, not an implied 'all'", async () => {
    mockLoad([run({ id: "a" }), run({ id: "b" }), run({ id: "c" })]);
    const el = await rail();
    expect(el.textContent ?? "").toContain("Counted from the 3 most recent runs this console loaded.");
  });

  it("says 'run', singular, when it counted exactly one", async () => {
    mockLoad([run({ id: "only" })]);
    const el = await rail();
    expect(el.textContent ?? "").toContain("Counted from the 1 most recent run this console loaded.");
    expect(el.textContent ?? "").not.toContain("most recent runs");
  });

  it("still discloses its window when it counted nothing", async () => {
    mockLoad([]);
    const el = await rail();
    // The disclosure is unconditional: an empty console must not silently drop
    // the sentence that explains what the zeroes above are counted from.
    expect(el.textContent ?? "").toContain("Counted from the 0 most recent runs this console loaded.");
    expect(figureText(stat(el, "running"))).toBe("0");
    expect(figureText(stat(el, "stalled"))).toBe("0");
  });
});
