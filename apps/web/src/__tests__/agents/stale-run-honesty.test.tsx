// @vitest-environment jsdom
/**
 * CRITICAL-2 — a dead AgentRun must never render as an ACTIVE one.
 *
 * MEASURED IN PRODUCTION (2026-08-03): one `tailor` AgentRun has sat at
 * status='running' since 2026-07-26 03:41 UTC — 192+ hours. No process is
 * attached to it (aether-worker was restarted on 2026-08-03 00:17, which would
 * have killed any real job), and nothing server-side ever reconciles the row,
 * so it survives restarts forever.
 *
 * Every surface that renders agent-run state read that row's raw
 * `status === "running"` and painted it as work in progress:
 *
 *   - Orchestration workflow graph  → coral "running" badge on the Tailoring node
 *   - Orchestration task queue      → an indefinite `animate-pulse` progressbar
 *   - Orchestration header          → "1 task in queue"
 *   - Agents "Recent runs" table    → amber "running"
 *   - Dashboard Agent Activity feed → "Waiting" badge, "run running · in progress"
 *   - Sidebar Agent Pulse           → "Agents Active · 1 of N agents running"
 *
 * So the product concealed a week of total inactivity behind a spinner: the
 * owner believed an agent had been grinding for hours.
 *
 * The honest signal available on an AgentRun is its own DB-stamped anchor
 * (`startedAt` ?? `createdAt`) — there is no heartbeat column. A run in flight
 * for longer than the staleness window the BACKEND already uses for its
 * BackgroundJob watchdog (apps/api/app/routers/agents.py `_job_stale_thresholds`
 * — processing > 12 min, enqueued > 15 min) has no live worker behind it and
 * must be rendered as STALLED, with how long it has been that way and what the
 * user can do — never as an indefinite spinner.
 *
 * These tests are the fail-before half: they assert the truthful rendering that
 * does not exist yet.
 */
import { act, cleanup, render, screen } from "@testing-library/react";
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

// F-01 (ADR-F01-PROVIDER-CREDENTIAL-AUTHZ): the Agents console now resolves
// isAdmin from /auth/me BEFORE choosing which provider endpoint to call —
// GET /agents/providers (operator, admin-only) or GET /agents/user/providers/catalog
// (customer). This suite exercises the OPERATOR console, so pin the identity;
// without it the page would silently fall to the customer path and the
// fetchProviders assertions below would stop covering anything.
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
import Orchestration from "../../components/agents/Orchestration";
import { describeRun, runBadge } from "../../components/dashboard/feed";
import {
  agentOutputGaps,
  agentPulse,
  isStalledRun,
  outputGapMessage,
  parseServerTime,
  stalledForMs,
  humanizeDuration,
} from "../../lib/agent-run-health";
import type { AgentRun, AgentSummary } from "../../lib/api/agents";
import type { Catalog, Provider } from "../../components/agents/api";

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

/** An ISO timestamp `ms` milliseconds in the past, relative to real `now`. */
function ago(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

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

/** The exact production row: tailor, running, started 192.6 h (8 days) ago. */
const DEAD_RUN: AgentRun = run({
  id: "ca44687a029bb1f622b71fa06",
  agentName: "tailor",
  status: "running",
  createdAt: ago(8 * DAY),
  startedAt: ago(8 * DAY),
  completedAt: null,
});

const FRESH_RUN: AgentRun = run({
  id: "fresh",
  agentName: "tailor",
  status: "running",
  createdAt: ago(90_000), // 90 s — a genuinely live run
  startedAt: ago(90_000),
  completedAt: null,
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// 1. The shared classifier
// ---------------------------------------------------------------------------

describe("agent-run-health — a run with no recent heartbeat is stalled, not active", () => {
  it("classifies the 8-day-old production 'running' row as stalled", () => {
    expect(isStalledRun(DEAD_RUN)).toBe(true);
    const ms = stalledForMs(DEAD_RUN);
    expect(ms).not.toBeNull();
    expect(Math.round((ms as number) / DAY)).toBe(8);
  });

  it("leaves a genuinely live run alone", () => {
    expect(isStalledRun(FRESH_RUN)).toBe(false);
    expect(stalledForMs(FRESH_RUN)).toBeNull();
  });

  it("never calls a terminal run stalled, however old", () => {
    expect(isStalledRun(run({ id: "old", createdAt: ago(30 * DAY) }))).toBe(false);
    expect(isStalledRun(run({ id: "oldfail", status: "failed", createdAt: ago(30 * DAY) }))).toBe(
      false,
    );
  });

  it("never calls a run stalled while its worker is still stamping a heartbeat", () => {
    // A genuinely long run (AgentRun.heartbeatAt, stamped by the executing
    // worker) must be untouchable however old it is — proof of life outranks
    // wall-clock age. Anything else would replace one lie with another.
    const longButAlive = run({
      id: "alive",
      status: "running",
      createdAt: ago(8 * DAY),
      startedAt: ago(8 * DAY),
      completedAt: null,
      heartbeatAt: ago(20_000),
    });
    expect(isStalledRun(longButAlive)).toBe(false);
    const heartbeatDied = run({
      id: "hbdead",
      status: "running",
      createdAt: ago(30 * MIN),
      startedAt: ago(30 * MIN),
      completedAt: null,
      heartbeatAt: ago(25 * MIN),
    });
    expect(isStalledRun(heartbeatDied)).toBe(true);
  });

  it("gives a queued run the backend's own 15-minute enqueue window, not the 12-minute one", () => {
    // Mirrors apps/api/app/routers/agents.py `_job_stale_thresholds`.
    const q13 = run({ id: "q13", status: "queued", createdAt: ago(13 * MIN), startedAt: null });
    const q16 = run({ id: "q16", status: "queued", createdAt: ago(16 * MIN), startedAt: null });
    expect(isStalledRun(q13)).toBe(false);
    expect(isStalledRun(q16)).toBe(true);
  });

  it("reads the API's naive UTC stamps as UTC, not as the viewer's local time", () => {
    // GET /agents/runs serialises naive Postgres `timestamp` columns with NO
    // timezone designator — verified against production:
    //   {"agentName":"fitScorer","status":"running",
    //    "startedAt":"2026-08-03T04:36:35.695000", ...}
    // ECMAScript reads that form as LOCAL time. For this product's owner
    // (en-AU, UTC+10) a run started sixty seconds ago would therefore be read
    // as ten hours old and reported as stalled — a fresh lie replacing the old
    // one. The offset-less stamp must be anchored to UTC.
    const iso = "2026-08-03T04:36:35.695000";
    expect(parseServerTime(iso)).toBe(Date.parse("2026-08-03T04:36:35.695Z"));
    // A stamp that does carry an offset is respected untouched.
    expect(parseServerTime("2026-08-03T04:36:35.695Z")).toBe(
      Date.parse("2026-08-03T04:36:35.695Z"),
    );
    expect(parseServerTime("2026-08-03T14:36:35.695+10:00")).toBe(
      Date.parse("2026-08-03T04:36:35.695Z"),
    );
    // And the classifier built on it agrees: a naive stamp one minute old is a
    // LIVE run, whatever timezone the browser is in.
    const nowUtc = Date.parse("2026-08-03T04:37:35.695Z");
    const fresh = run({
      id: "naive",
      status: "running",
      createdAt: iso,
      startedAt: iso,
      completedAt: null,
    });
    expect(isStalledRun(fresh, nowUtc)).toBe(false);
  });

  it("humanizes a duration in the units a person reads", () => {
    expect(humanizeDuration(8 * DAY)).toMatch(/8 days/);
    expect(humanizeDuration(3 * HOUR)).toMatch(/3 hr/);
    expect(humanizeDuration(14 * MIN)).toMatch(/14 min/);
  });
});

// ---------------------------------------------------------------------------
// 2. Orchestration — the queue and the error log
//
// ORCH-DEDUP (2026-08-14): this section used to also cover the node-graph
// (`workflow-node-tailoring`) and the component's own header status line
// ("N tasks in queue" / "N stalled") — both removed from Orchestration.tsx
// by that ruling (node-graph superseded by OrchestrationMap; header
// superseded by the page-level stat rail in page.tsx). The two node-graph
// tests and the one header-only test were deleted with what they covered.
// The fifth test ("keeps counting a genuinely live run as queued work") is
// KEPT but trimmed to drop its header-scoped assertion — its task-queue
// progressbar assertion still covers real, un-duplicated behaviour (a
// genuinely live run keeps its indeterminate spinner). See git history for
// the removed/original assertions.
// ---------------------------------------------------------------------------

const AGENT_SUMMARIES: AgentSummary[] = [
  { name: "supervisor", status: "active", last_run: null, approval_gated: false },
];

describe("Orchestration — a stalled run must not read as work in progress", () => {
  it("never renders an indefinite spinner for a stalled run in the task queue", () => {
    render(<Orchestration agents={AGENT_SUMMARIES} runs={[DEAD_RUN]} />);
    const queue = screen.getByTestId("task-queue");
    expect(queue.textContent ?? "").not.toMatch(/in progress/i);
    expect(queue.textContent ?? "").toMatch(/stalled/i);
    expect(queue.textContent ?? "").toMatch(/8 days/);
    expect(
      queue.querySelector('[role="progressbar"]'),
      "a dead run must not keep an indeterminate progress indicator alive",
    ).toBeNull();
    expect(queue.querySelector(".animate-pulse")).toBeNull();
  });

  it("tags a stalled run in the error log as stalled, not as a run still going", () => {
    render(<Orchestration agents={AGENT_SUMMARIES} runs={[DEAD_RUN]} />);
    const log = screen.getByTestId("error-log");
    expect(log.textContent ?? "").toMatch(/stalled/i);
    expect(log.querySelector(".text-aether-green")).toBeNull();
  });

  it("keeps a genuinely live run's indeterminate spinner in the task queue", () => {
    render(<Orchestration agents={AGENT_SUMMARIES} runs={[FRESH_RUN]} />);
    expect(screen.getByTestId("task-queue").querySelector('[role="progressbar"]')).not.toBeNull();
  });
});

describe("Orchestration — the spinner must never be indefinite", () => {
  it("flips a run from 'in progress' to 'stalled' while the screen stays open, with no reload", async () => {
    // The realtime channel carries SERVER changes; a run going stale is not one
    // — no row moves, no event fires. Without a clock the screen would hold an
    // "in progress" line forever for a run whose worker died mid-session.
    vi.useFakeTimers();
    try {
      const started = new Date(Date.now() - 11 * MIN).toISOString();
      const almostStale = run({
        id: "aging",
        status: "running",
        createdAt: started,
        startedAt: started,
        completedAt: null,
      });
      render(<Orchestration agents={AGENT_SUMMARIES} runs={[almostStale]} />);
      expect(screen.getByTestId("task-queue").textContent ?? "").toMatch(/in progress/i);

      // Cross the 12-minute window with no user action and no refetch.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2 * MIN);
      });
      const queue = screen.getByTestId("task-queue");
      expect(queue.textContent ?? "").not.toMatch(/in progress/i);
      expect(queue.textContent ?? "").toMatch(/stalled/i);
      expect(queue.querySelector('[role="progressbar"]')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

// ---------------------------------------------------------------------------
// 3. Dashboard Agent Activity feed helpers
// ---------------------------------------------------------------------------

describe("dashboard feed — a stalled run is not 'Waiting'", () => {
  it("badges a stalled run honestly", () => {
    expect(runBadge(DEAD_RUN).label).toMatch(/stalled/i);
    expect(runBadge(FRESH_RUN).label).toMatch(/waiting|running/i);
  });

  it("describes a stalled run as abandoned, never as 'in progress'", () => {
    const desc = describeRun(DEAD_RUN);
    expect(desc.metric ?? "").not.toMatch(/in progress/i);
    expect(`${desc.text} ${desc.metric ?? ""}`).toMatch(/stalled/i);
    expect(`${desc.text} ${desc.metric ?? ""}`).toMatch(/8 days/);
  });
});

// ---------------------------------------------------------------------------
// 4. Sidebar Agent Pulse
// ---------------------------------------------------------------------------

describe("agentPulse — the sidebar must not call a dead agent active", () => {
  it("does not count an agent whose last run started 8 days ago as running", () => {
    const summaries: AgentSummary[] = [
      { name: "tailor", status: "running", last_run: ago(8 * DAY), approval_gated: false },
      { name: "scout", status: "completed", last_run: ago(2 * MIN), approval_gated: false },
    ];
    const pulse = agentPulse(summaries);
    expect(pulse.running).toBe(0);
    expect(pulse.stalled).toBe(1);
    expect(pulse.total).toBe(2);
  });

  it("still counts a genuinely running agent", () => {
    const summaries: AgentSummary[] = [
      { name: "tailor", status: "running", last_run: ago(60_000), approval_gated: false },
    ];
    expect(agentPulse(summaries)).toMatchObject({ running: 1, stalled: 0 });
  });
});

// ---------------------------------------------------------------------------
// 5. "This agent has produced nothing since <date>"
// ---------------------------------------------------------------------------

describe("agentOutputGaps — an agent that has produced nothing must say so", () => {
  it("reports the gap with the real date of the last output", () => {
    const producedAt = ago(8 * DAY);
    const runs: AgentRun[] = [
      run({ id: "f1", agentName: "tailor", status: "failed", createdAt: ago(1 * HOUR) }),
      run({ id: "f2", agentName: "tailor", status: "failed", createdAt: ago(2 * HOUR) }),
      run({ id: "ok", agentName: "tailor", status: "completed", createdAt: producedAt }),
    ];
    const gaps = agentOutputGaps(runs);
    expect(gaps).toHaveLength(1);
    expect(gaps[0].agent).toBe("tailor");
    expect(gaps[0].lastProducedAt).toBe(producedAt);
    expect(gaps[0].attempts).toBe(2);
    expect(outputGapMessage(gaps[0])).toMatch(/produced nothing since/i);
  });

  it("says nothing when the agent produced output recently", () => {
    const runs: AgentRun[] = [
      run({ id: "f1", agentName: "tailor", status: "failed", createdAt: ago(1 * HOUR) }),
      run({ id: "ok", agentName: "tailor", status: "completed", createdAt: ago(2 * HOUR) }),
    ];
    expect(agentOutputGaps(runs)).toHaveLength(0);
  });

  it("does not claim a date it does not have when no output is in the window", () => {
    const runs: AgentRun[] = [
      run({ id: "f1", agentName: "tailor", status: "failed", createdAt: ago(1 * HOUR) }),
      run({ id: "f2", agentName: "tailor", status: "failed", createdAt: ago(9 * DAY) }),
    ];
    const gaps = agentOutputGaps(runs);
    expect(gaps).toHaveLength(1);
    expect(gaps[0].lastProducedAt).toBeNull();
    expect(outputGapMessage(gaps[0])).toMatch(/no output/i);
    expect(outputGapMessage(gaps[0])).not.toMatch(/produced nothing since\s*$/i);
  });

  it("counts a letterless coverLetter degrade as 'produced nothing', not as output", () => {
    const runs: AgentRun[] = [
      run({
        id: "d1",
        agentName: "coverLetter",
        status: "completed",
        createdAt: ago(1 * HOUR),
        output: { coverLetterUnavailable: true, cover_letter_id: null },
      }),
      run({ id: "ok", agentName: "coverLetter", status: "completed", createdAt: ago(9 * DAY) }),
    ];
    const gaps = agentOutputGaps(runs);
    expect(gaps.map((g) => g.agent)).toContain("coverLetter");
  });
});

// ---------------------------------------------------------------------------
// 6. The Agents screen, end to end
// ---------------------------------------------------------------------------

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

describe("Agents screen — the honest state of a dead run", () => {
  it("shows 'stalled' with its age in the Recent runs table, never a bare 'running'", async () => {
    mockLoad([DEAD_RUN]);
    render(<AgentsPage />);
    const table = await screen.findByTestId("agent-runs-table");
    expect(table.textContent ?? "").toMatch(/stalled/i);
    expect(table.textContent ?? "").toMatch(/8 days/);
    expect(table.textContent ?? "").not.toMatch(/\brunning\b/i);
  });

  it("banners the stalled run with how long it has been that way and what to do", async () => {
    mockLoad([DEAD_RUN]);
    render(<AgentsPage />);
    const banner = await screen.findByTestId("agents-stalled-banner");
    expect(banner.textContent ?? "").toMatch(/tailor/i);
    expect(banner.textContent ?? "").toMatch(/8 days/);
    expect(banner.textContent ?? "").toMatch(/never finish|no longer|nothing is working on it/i);
    expect(banner.textContent ?? "").toMatch(/run|start/i);
  });

  it("shows no stalled banner when nothing is stalled", async () => {
    mockLoad([FRESH_RUN]);
    render(<AgentsPage />);
    await screen.findByTestId("agent-runs-table");
    expect(screen.queryByTestId("agents-stalled-banner")).toBeNull();
  });

  it("says the agent has produced nothing since a real date when that is true", async () => {
    const producedAt = ago(8 * DAY);
    mockLoad([
      run({ id: "f1", agentName: "tailor", status: "failed", createdAt: ago(1 * HOUR) }),
      run({ id: "ok", agentName: "tailor", status: "completed", createdAt: producedAt }),
    ]);
    render(<AgentsPage />);
    const note = await screen.findByTestId("agents-no-output");
    expect(note.textContent ?? "").toMatch(/tailor/i);
    expect(note.textContent ?? "").toMatch(/produced nothing since/i);
  });

  it("says nothing about output gaps when every agent is producing", async () => {
    mockLoad([run({ id: "ok", agentName: "tailor", status: "completed", createdAt: ago(5 * MIN) })]);
    render(<AgentsPage />);
    await screen.findByTestId("agent-runs-table");
    expect(screen.queryByTestId("agents-no-output")).toBeNull();
  });
});
