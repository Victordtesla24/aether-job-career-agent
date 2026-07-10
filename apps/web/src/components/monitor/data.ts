/**
 * Pure data-mapping layer for the Agent Monitor screen (AGT-MONITOR).
 *
 * These helpers turn the two live endpoints the screen consumes —
 * `GET /agents` (roster) and `GET /agents/runs` (audit trail) — into the exact
 * view models the panels render. Keeping them React-free makes every derived
 * value unit-testable under the plain-node vitest environment and guarantees no
 * panel ever shows a hard-coded fixture: each number traces to a run row.
 */
import type { AgentRun, AgentSummary } from "../../lib/api/agents";

export type NodeTone = "green" | "coral" | "yellow" | "red" | "dim";

export interface WorkflowNode {
  /** Stable key. */
  id: string;
  /** Display label from the wireframe. */
  label: string;
  /** Font Awesome 6 icon class. */
  icon: string;
  /** Backing agent name(s) in the API roster. */
  agents: string[];
  /** Grid position (percentage of the graph box), from the wireframe layout. */
  x: number;
  y: number;
}

export interface NodeState extends WorkflowNode {
  status: string;
  tone: NodeTone;
  /** True for the node currently processing — drives the pulse animation. */
  pulse: boolean;
}

/**
 * The six product-level pipeline nodes shown in the wireframe, mapped onto the
 * seven real agents in the backend registry. Positions mirror
 * design/screens/agent-monitor.html (expressed as % so the graph scales).
 */
export const WORKFLOW_NODES: WorkflowNode[] = [
  { id: "discovery", label: "Discovery", icon: "fa-solid fa-magnifying-glass", agents: ["scout"], x: 12, y: 15 },
  { id: "evaluator", label: "Evaluator", icon: "fa-solid fa-scale-balanced", agents: ["fitScorer", "matcher"], x: 50, y: 15 },
  { id: "tailoring", label: "Tailoring", icon: "fa-solid fa-file-pen", agents: ["tailor"], x: 50, y: 48 },
  { id: "submission", label: "Submission", icon: "fa-solid fa-paper-plane", agents: ["coverLetter"], x: 82, y: 48 },
  { id: "learning", label: "Learning", icon: "fa-solid fa-graduation-cap", agents: ["storyExtractor"], x: 50, y: 80 },
  { id: "memory", label: "Memory", icon: "fa-solid fa-database", agents: ["supervisor"], x: 12, y: 80 },
];

/** Directed edges (from node id → to node id) describing the pipeline topology. */
export const WORKFLOW_EDGES: ReadonlyArray<readonly [string, string]> = [
  ["discovery", "evaluator"],
  ["evaluator", "tailoring"],
  ["tailoring", "submission"],
  ["tailoring", "learning"],
  ["discovery", "memory"],
  ["memory", "learning"],
];

const STATUS_PRIORITY: Record<string, number> = {
  running: 5,
  queued: 4,
  failed: 3,
  completed: 2,
  idle: 1,
};

/** Pick the most "active" status among a node's backing agents. */
function dominantStatus(statuses: string[]): string {
  return statuses.reduce(
    (best, s) => ((STATUS_PRIORITY[s] ?? 0) > (STATUS_PRIORITY[best] ?? 0) ? s : best),
    "idle",
  );
}

function toneFor(nodeId: string, status: string): { label: string; tone: NodeTone; pulse: boolean } {
  switch (status) {
    case "running":
      return { label: "active", tone: "coral", pulse: true };
    case "queued":
      return { label: "waiting", tone: "yellow", pulse: false };
    case "failed":
      return { label: "error", tone: "red", pulse: false };
    case "completed":
      return nodeId === "memory"
        ? { label: "synced", tone: "green", pulse: false }
        : { label: "working", tone: "green", pulse: false };
    default:
      return { label: "idle", tone: "dim", pulse: false };
  }
}

/** Resolve each workflow node's live state from the agent roster. */
export function mapAgentsToNodes(agents: AgentSummary[]): NodeState[] {
  const byName = new Map(agents.map((a) => [a.name, a.status]));
  return WORKFLOW_NODES.map((node) => {
    const status = dominantStatus(node.agents.map((n) => byName.get(n) ?? "idle"));
    const { label, tone, pulse } = toneFor(node.id, status);
    return { ...node, status: label, tone, pulse };
  });
}

/** True when any run is currently executing (drives edge flow animation + live dot). */
export function anyRunning(runs: AgentRun[]): boolean {
  return runs.some((r) => r.status === "running" || r.status === "queued");
}

export interface HeaderStats {
  agentsOnline: number;
  tasksInQueue: number;
  successRate: string;
}

export function deriveHeaderStats(agents: AgentSummary[], runs: AgentRun[]): HeaderStats {
  const tasksInQueue = runs.filter((r) => r.status === "running" || r.status === "queued").length;
  return {
    agentsOnline: agents.length,
    tasksInQueue,
    successRate: successRate(runs),
  };
}

export interface QueueItem {
  id: string;
  label: string;
  agentName: string;
  status: "running" | "queued";
}

/** In-flight and queued runs, newest first. */
export function deriveTaskQueue(runs: AgentRun[]): QueueItem[] {
  return runs
    .filter((r): r is AgentRun & { status: "running" | "queued" } =>
      r.status === "running" || r.status === "queued",
    )
    .sort((a, b) => tsOf(b.createdAt) - tsOf(a.createdAt))
    .map((r) => ({
      id: r.id,
      agentName: r.agentName,
      label: humanAgent(r.agentName),
      status: r.status,
    }));
}

export interface Performance {
  tasksDone: number;
  avgTime: string;
  successRate: string;
}

export function derivePerformance(runs: AgentRun[]): Performance {
  const completed = runs.filter((r) => r.status === "completed");
  return {
    tasksDone: completed.length,
    avgTime: avgDuration(completed),
    successRate: successRate(runs),
  };
}

export type LogLevel = "ERR" | "WRN" | "OK";

export interface LogEntry {
  id: string;
  level: LogLevel;
  time: string;
  message: string;
}

/** Recent run outcomes as an operator-readable log, newest first. */
export function deriveErrorLog(runs: AgentRun[], limit = 8): LogEntry[] {
  return [...runs]
    .sort((a, b) => tsOf(b.createdAt) - tsOf(a.createdAt))
    .slice(0, limit)
    .map((r) => {
      const time = clock(r.createdAt);
      if (r.status === "failed") {
        return { id: r.id, level: "ERR", time, message: `${humanAgent(r.agentName)} — ${r.error ?? "run failed"}` };
      }
      if (r.status === "completed" && approvalRequired(r)) {
        return { id: r.id, level: "WRN", time, message: `${humanAgent(r.agentName)} output awaiting approval` };
      }
      if (r.status === "completed") {
        return { id: r.id, level: "OK", time, message: `${humanAgent(r.agentName)} completed` };
      }
      return { id: r.id, level: "WRN", time, message: `${humanAgent(r.agentName)} ${r.status}` };
    });
}

// --- internals -------------------------------------------------------------

function approvalRequired(run: AgentRun): boolean {
  return Boolean(run.output && (run.output as Record<string, unknown>).approvalRequired);
}

function successRate(runs: AgentRun[]): string {
  const terminal = runs.filter((r) => r.status === "completed" || r.status === "failed");
  if (terminal.length === 0) return "—";
  const ok = terminal.filter((r) => r.status === "completed").length;
  return `${Math.round((ok / terminal.length) * 1000) / 10}%`;
}

function avgDuration(completed: AgentRun[]): string {
  const durations = completed
    .map(durationMs)
    .filter((d): d is number => d !== null && d >= 0);
  if (durations.length === 0) return "—";
  const meanMs = durations.reduce((sum, d) => sum + d, 0) / durations.length;
  return meanMs >= 1000 ? `${(meanMs / 1000).toFixed(1)}s` : `${Math.round(meanMs)}ms`;
}

function durationMs(run: AgentRun): number | null {
  const out = run.output as Record<string, unknown> | null | undefined;
  if (out && typeof out.duration_ms === "number") return out.duration_ms;
  if (run.startedAt && run.completedAt) {
    return tsOf(run.completedAt) - tsOf(run.startedAt);
  }
  return null;
}

function tsOf(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? 0 : t;
}

function clock(iso: string | null | undefined): string {
  const t = tsOf(iso);
  if (t === 0) return "--:--";
  return new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

const AGENT_LABELS: Record<string, string> = {
  scout: "Discover",
  fitScorer: "Evaluate",
  matcher: "Match",
  tailor: "Tailor",
  coverLetter: "Cover Letter",
  storyExtractor: "Story Extract",
  supervisor: "Supervisor",
};

function humanAgent(name: string): string {
  return AGENT_LABELS[name] ?? name;
}
