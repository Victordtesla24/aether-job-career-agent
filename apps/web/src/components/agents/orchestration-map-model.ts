/**
 * S-UI §4.1 — the orchestration map's DATA MODEL, shared verbatim by the
 * static SVG/CSS rendition and the WebGL rendition.
 *
 * Both renditions read this one module so the enhanced layer can never drift
 * from the accessible one: an edge is "active" in three.js for exactly the
 * same reason it is "active" in the SVG fallback, and neither can invent a
 * relationship the API did not describe.
 *
 * HONESTY RULES ENCODED HERE (not in a renderer, so they cannot be styled
 * away):
 *   - A node is LIVE only when a run for that agent's backend is genuinely
 *     in flight AND not stalled (`isInFlight && isLiveRun` — the same
 *     `lib/agent-run-health` predicates the task queue and the run monitor
 *     already obey, CRITICAL-2).
 *   - A STALLED run never produces motion anywhere. It produces a `warn`
 *     node and an elapsed-time label instead.
 *   - `status === "planned"` can never be live, can never carry a policy tier,
 *     and its inbound/outbound edge is always `planned` (dashed).
 *   - Edges are STAGE-to-STAGE, because stage order is the only relationship
 *     `GET /agents/orchestration-map` actually defines. Drawing agent-to-agent
 *     arrows would be a fabricated topology.
 */
import { isInFlight, isLiveRun, stalledLabel } from "../../lib/agent-run-health";
import type { AgentRun } from "../../lib/api/agents";
import type {
  OrchestrationMapAgent,
  OrchestrationMapEntry,
} from "../../lib/api/agentPolicy";

/** Required, always-visible disclosure under every map (S-UI §4.1 honesty rule 2). */
export const STAGE_ORDER_FOOTNOTE =
  "Stage order is the DEFINED pipeline, not a live trace.";

export type NodeState = "live" | "stalled" | "failed" | "idle" | "planned";

export interface MapNode {
  agent: OrchestrationMapAgent;
  state: NodeState;
  /** Human elapsed-time label for a stalled run; `null` otherwise. */
  stalledText: string | null;
  /** ISO stamp of the run this state was derived from, if any. */
  lastRunAt: string | null;
}

export type EdgeState = "active" | "idle" | "planned";

export interface MapEdge {
  key: string;
  fromStage: string;
  toStage: string;
  state: EdgeState;
}

export interface MapModel {
  key: string;
  name: string;
  subtitle: string | null;
  stages: Array<{ stage: string; nodes: MapNode[] }>;
  edges: MapEdge[];
  /** Count of nodes whose run is genuinely in flight right now. */
  liveCount: number;
  /** Count of nodes whose in-flight run has gone stale (no worker attached). */
  stalledCount: number;
}

export function slugifyStage(value: string): string {
  return value.toLowerCase().trim().replace(/\s+/g, "-");
}

/**
 * Resolve one catalog agent's honest node state from the real run history.
 *
 * `AgentRun.agentName` carries the BACKEND name (e.g. "tailor"), which is what
 * the orchestration-map payload exposes as `agent.backend` — a planned agent
 * has `backend: null` and therefore can never match a run, structurally.
 */
export function resolveNodeState(
  agent: OrchestrationMapAgent,
  runs: AgentRun[],
  now: number,
): MapNode {
  if (agent.status === "planned") {
    return { agent, state: "planned", stalledText: null, lastRunAt: null };
  }
  const backend = agent.backend ?? null;
  // `runs` arrives newest-first (GET /agents/runs orders by createdAt DESC),
  // so this is the agent's CURRENT run, never an older one.
  const newest = backend ? runs.find((r) => r.agentName === backend) : undefined;
  if (newest && isInFlight(newest)) {
    if (isLiveRun(newest, now)) {
      return {
        agent,
        state: "live",
        stalledText: null,
        lastRunAt: newest.startedAt ?? newest.createdAt ?? null,
      };
    }
    // CRITICAL-2: an in-flight row older than the staleness window has no
    // worker behind it. It is reported, with how long — and it never moves.
    return {
      agent,
      state: "stalled",
      stalledText: stalledLabel(newest, now),
      lastRunAt: newest.startedAt ?? newest.createdAt ?? null,
    };
  }
  if (newest?.status === "failed") {
    return { agent, state: "failed", stalledText: null, lastRunAt: newest.startedAt ?? null };
  }
  return {
    agent,
    state: "idle",
    stalledText: null,
    lastRunAt: newest?.startedAt ?? agent.lastRunAt ?? null,
  };
}

/** Build the render model for a single map entry from live run history. */
export function buildMapModel(
  entry: OrchestrationMapEntry,
  runs: AgentRun[],
  now: number,
): MapModel {
  const stages = entry.stages.map((s) => ({
    stage: s.stage,
    nodes: s.agents.map((a) => resolveNodeState(a, runs, now)),
  }));

  const edges: MapEdge[] = [];
  for (let i = 0; i < stages.length - 1; i++) {
    const from = stages[i];
    const to = stages[i + 1];
    // A transition whose source or target stage is entirely roadmap is itself
    // roadmap — it is drawn dashed and can never pulse.
    const allPlanned =
      from.nodes.every((n) => n.state === "planned") ||
      to.nodes.every((n) => n.state === "planned");
    const anyLive = from.nodes.some((n) => n.state === "live");
    edges.push({
      key: `${entry.key}:${slugifyStage(from.stage)}->${slugifyStage(to.stage)}`,
      fromStage: from.stage,
      toStage: to.stage,
      state: allPlanned ? "planned" : anyLive ? "active" : "idle",
    });
  }

  const flat = stages.flatMap((s) => s.nodes);
  return {
    key: entry.key,
    name: entry.name,
    subtitle: entry.subtitle ?? null,
    stages,
    edges,
    liveCount: flat.filter((n) => n.state === "live").length,
    stalledCount: flat.filter((n) => n.state === "stalled").length,
  };
}

/** Badge wording per node state. The WORD carries the meaning (Rule D-8). */
export function nodeBadge(node: MapNode): { tone: "ok" | "warn" | "danger" | "neutral"; label: string } {
  switch (node.state) {
    case "live":
      // "Running" is claimed ONLY for a run that could still plausibly be alive.
      return { tone: "ok", label: "Running" };
    case "stalled":
      return { tone: "warn", label: node.stalledText ?? "Stalled" };
    case "failed":
      return { tone: "danger", label: "Last run failed" };
    case "planned":
      // Verbatim, unchanged from the shipped contract.
      return { tone: "neutral", label: "Planned — roadmap" };
    default:
      return { tone: "neutral", label: "Idle" };
  }
}

/** Direction glyph + word for a trend, or `null` when nothing was measured. */
export function trendLabel(agent: OrchestrationMapAgent): string | null {
  const trend = agent.trend;
  if (!trend || !trend.direction) return null;
  const arrow =
    trend.direction === "improving" ? "↑" : trend.direction === "declining" ? "↓" : "→";
  return `${arrow} ${trend.direction}${trend.metric ? ` (${trend.metric})` : ""}`;
}
