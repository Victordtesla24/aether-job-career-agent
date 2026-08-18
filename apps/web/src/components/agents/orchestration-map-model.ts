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
 *
 * THAT LAST LAW IS UNCHANGED, AND U-STORY-3a DOES NOT BEND IT. The cross-map
 * wiring the "Show connections" overlay draws is agent-to-agent, and it is
 * therefore NOT derived from this payload — it could not honestly be. It comes
 * from `workflow-linkage.ts`: a checked-in table where every edge carries the
 * hop-by-hop `file:line` provenance it was read out of the API with, filtered
 * at runtime by `drawableLinkages` so an edge that loses its provenance stops
 * being drawn. Those edges are STRUCTURAL (how the system is wired) and are
 * rendered as such — dotted, labelled, never coral, never animated. Nothing in
 * this module may ever start inferring them from `stages`.
 *
 * A THIRD kind exists since B6: CAUSAL, run-level edges ("this run started
 * that one"), also NOT derived from this module's `runs`/`resolveNodeState`
 * — they come from `causalEdges` in `workflow-linkage.ts`, reading
 * `AgentRun.parentRunId` off the SAME fetched `runs` array this file already
 * takes, matched against other rows in that same array. Still never inferred
 * from `stages`, agent name or timing — only from two real ids matching.
 */
import { catalogScale } from "./catalog-counts";
import {
  ageMs,
  humanizeDuration,
  isInFlight,
  isLiveRun,
  parseServerTime,
  staleLimitFor,
  stalledLabel,
  stalledPhrase,
} from "../../lib/agent-run-health";
import { isProviderRateLimitText } from "../../lib/agents-feedback";
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
  /**
   * The RECORDED status of that run ("completed" / "failed" / "running" /
   * "queued"), whichever source the state was derived from — `null` only when
   * the agent has genuinely never run. Carried explicitly (rather than left
   * implicit in `state`) because U-AX-V4 was exactly this value going missing.
   */
  lastRunStatus: string | null;
  /**
   * The recorded `AgentRun.error` for a FAILED windowed run, or `null` when
   * the failure is catalog-only (no error text) or the last run was not a
   * failure. Used so a lone provider 429 is labelled "Rate limited" (warn)
   * instead of "Last run failed" (danger).
   */
  lastRunError: string | null;
  /** Relative last-run time ("3 hr ago"); `null` when there is no run to date. */
  lastRunText: string | null;
  /**
   * Which evidence produced the state — `"runs"` = the windowed run history,
   * `"catalog"` = the per-agent, UNWINDOWED `lastRunStatus`/`lastRunAt` pair on
   * the orchestration-map payload, `"none"` = no run on record anywhere.
   * Diagnostic only; nothing renders differently because of it.
   */
  source: "runs" | "catalog" | "none";
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
  /**
   * The map's SERVER-computed scale — `engines` (distinct backends placed in
   * it) and `cards` (nodes it renders) — or `null` when the payload carries
   * none (AUD-AGENT-4).
   *
   * IT IS TRANSMITTED, NEVER RECOMPUTED HERE. Summing `stages[].nodes` counts
   * one engine once per facet card: the three `fitScorer` faces in "Fit
   * Scoring" made the Application Pipeline header claim 12 agents for 10. A
   * renderer that has no scale must state no scale — falling back to the node
   * sum is the padded number this fix removes.
   */
  scale: { engines: number; cards: number } | null;
  /** Count of nodes whose run is genuinely in flight right now. */
  liveCount: number;
  /** Count of nodes whose in-flight run has gone stale (no worker attached). */
  stalledCount: number;
}

export function slugifyStage(value: string): string {
  return value.toLowerCase().trim().replace(/\s+/g, "-");
}

/** "3 hr ago" / "just now" — `null` when there is no dateable run at all. */
export function relativeRunLabel(iso: string | null, now: number): string | null {
  const age = ageMs(iso, now);
  if (age === null) return null;
  // Sub-minute ages humanize to "0 min", which reads like a rounding bug.
  return age < 60_000 ? "just now" : `${humanizeDuration(age)} ago`;
}

/**
 * Resolve one catalog agent's honest node state from the real run history.
 *
 * TWO SOURCES, AND WHY BOTH ARE NEEDED (U-AX-V4 / S-UI-1 review finding 1).
 *
 * 1. `runs` — `GET /agents/runs`, a GLOBAL window (default `limit=50`) shared
 *    by all 22 agent cards, newest-first. Richer per row: it carries `heartbeatAt`,
 *    which is the only positive evidence that a long run is genuinely alive.
 *    But one busy agent can push every other agent out of a 50-row window, and
 *    an agent missing from the window is NOT an agent that has not run.
 * 2. `agent.lastRunStatus` / `agent.lastRunAt` — computed per agent by the
 *    backend with NO window at all (`last_policy_run_by_agent`, see
 *    `apps/api/app/routers/agents.py::orchestration_map`). Authoritative about
 *    WHICH run was last and HOW it ended, for every agent, always.
 *
 * Reading only (1) — what shipped in S-UI-1 — silently flattened an agent whose
 * last run genuinely FAILED into a neutral "Idle" badge the moment that run
 * aged out of the shared window: the same status-flattening class of defect
 * U-AX-V4 named. So the windowed run is used when it is the freshest evidence,
 * and the unwindowed catalog record is used whenever it is not (no match at
 * all, or a strictly newer run than the window holds).
 *
 * The catalog record carries no heartbeat, so its liveness verdict falls back
 * to the same status+timestamp rule the sidebar pulse already applies
 * (`agentPulse`): in-flight inside its window ⇒ live, outside it or undateable
 * ⇒ STALLED, never live. That is fail-safe in the honest direction — the
 * fallback can under-claim life, never over-claim it.
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
    return {
      agent,
      state: "planned",
      stalledText: null,
      lastRunAt: null,
      lastRunStatus: null,
      lastRunError: null,
      lastRunText: null,
      source: "none",
    };
  }

  const node = (
    state: NodeState,
    stalledText: string | null,
    lastRunAt: string | null,
    lastRunStatus: string | null,
    source: MapNode["source"],
    lastRunError: string | null = null,
  ): MapNode => ({
    agent,
    state,
    stalledText,
    lastRunAt,
    lastRunStatus,
    lastRunError,
    lastRunText: relativeRunLabel(lastRunAt, now),
    source,
  });

  const backend = agent.backend ?? null;
  // `runs` arrives newest-first (GET /agents/runs orders by createdAt DESC),
  // so this is the agent's newest run WITHIN THAT WINDOW, never an older one.
  const newest = backend ? runs.find((r) => r.agentName === backend) : undefined;
  const catalogAt = agent.lastRunAt ?? null;
  const catalogStatus = agent.lastRunStatus ?? null;

  // The window is only preferred while it is the freshest thing we hold. The
  // two endpoints are fetched separately, so the catalog record can legitimately
  // describe a NEWER run than the run list the page loaded moments earlier.
  const windowedAt = newest?.createdAt ?? newest?.startedAt ?? null;
  const catalogIsNewer =
    catalogAt !== null &&
    (windowedAt === null ||
      (parseServerTime(catalogAt) ?? 0) > (parseServerTime(windowedAt) ?? 0));

  if (newest && !catalogIsNewer) {
    const at = newest.startedAt ?? newest.createdAt ?? null;
    if (isInFlight(newest)) {
      if (isLiveRun(newest, now)) {
        return node("live", null, at, newest.status, "runs");
      }
      // CRITICAL-2: an in-flight row older than the staleness window has no
      // worker behind it. It is reported, with how long — and it never moves.
      return node("stalled", stalledLabel(newest, now), at, newest.status, "runs");
    }
    if (newest.status === "failed") {
      return node("failed", null, at, newest.status, "runs", newest.error ?? null);
    }
    return node("idle", null, at, newest.status, "runs");
  }

  if (catalogStatus === null && catalogAt === null) {
    // Nothing anywhere has a run for this agent. "Idle" here means "no run on
    // record", which is what the card then says in words.
    return node("idle", null, null, null, "none");
  }

  if (catalogStatus === "running" || catalogStatus === "queued") {
    const age = ageMs(catalogAt, now);
    if (age !== null && age < staleLimitFor(catalogStatus)) {
      return node("live", null, catalogAt, catalogStatus, "catalog");
    }
    return node("stalled", stalledPhrase(age), catalogAt, catalogStatus, "catalog");
  }
  if (catalogStatus === "failed") {
    return node("failed", null, catalogAt, catalogStatus, "catalog");
  }
  return node("idle", null, catalogAt, catalogStatus, "catalog");
}

/**
 * The recorded status of the last run, worded so it can never read as live work
 * the UI has already judged dead (CRITICAL-2).
 *
 * A STALLED node states the elapsed time FIRST and only then quotes the raw
 * recorded value, so "running" can never stand alone on a row nothing is
 * working on.
 */
export function lastRunStatusText(node: MapNode): string {
  if (node.agent.status === "planned") return "—";
  if (!node.lastRunStatus) return "—";
  if (node.state === "stalled") {
    return `${node.stalledText ?? "stalled"} — recorded as "${node.lastRunStatus}", no worker attached`;
  }
  return node.lastRunStatus;
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
    scale: catalogScale(entry.counts),
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
      // LOOP-429: a lone provider rate-limit is transient. Catalog-only
      // failures have no error text and stay danger — we cannot invent a
      // rate-limit we did not observe.
      if (isProviderRateLimitText(node.lastRunError)) {
        return { tone: "warn", label: "Rate limited" };
      }
      return { tone: "danger", label: "Last run failed" };
    case "planned":
      // Verbatim, unchanged from the shipped contract.
      return { tone: "neutral", label: "Planned — roadmap" };
    default:
      return { tone: "neutral", label: "Idle" };
  }
}

// ---------------------------------------------------------------------------
// Horizontal continuation (S-UI-1 review finding 2)
// ---------------------------------------------------------------------------

export interface StageWindow {
  /** 0-based index of the first fully visible stage column. */
  first: number;
  /** 0-based index of the last fully visible stage column. */
  last: number;
  /** How many stage columns are NOT fully visible right now. */
  hidden: number;
}

/**
 * Which stage columns a viewer can actually see right now.
 *
 * The map is wider than the content column on narrow desktops (7 stages ×
 * a legible card cannot fit under ~1440 px — measured, see slice-1 evidence),
 * so it scrolls. A silent clip is the defect: the SUBMISSION stage vanished at
 * the viewport edge with nothing saying more existed. This computes the honest
 * "showing 1–5 of 7" statement from MEASURED geometry — it never guesses, and
 * returns `null` before anything has been measured (SSR, hidden tab, jsdom)
 * rather than claiming a window it cannot see.
 *
 * "Visible" means FULLY visible: a half-clipped column is exactly what the
 * viewer must be told about, so it counts as hidden.
 */
export function visibleStageRange(
  columns: Array<{ left: number; right: number }>,
  scrollLeft: number,
  viewportWidth: number,
): StageWindow | null {
  if (columns.length === 0 || viewportWidth <= 0) return null;
  const TOL = 1; // sub-pixel layout rounding, not a fudge factor
  const start = scrollLeft - TOL;
  const end = scrollLeft + viewportWidth + TOL;

  let first = -1;
  let last = -1;
  columns.forEach((c, i) => {
    if (c.left >= start && c.right <= end) {
      if (first === -1) first = i;
      last = i;
    }
  });

  if (first === -1) {
    // Nothing fits whole (a column wider than the viewport). Report the one
    // occupying the most screen instead of claiming nothing is shown.
    let bestIdx = 0;
    let bestOverlap = -1;
    columns.forEach((c, i) => {
      const overlap = Math.min(c.right, end) - Math.max(c.left, start);
      if (overlap > bestOverlap) {
        bestOverlap = overlap;
        bestIdx = i;
      }
    });
    first = bestIdx;
    last = bestIdx;
  }

  return { first, last, hidden: columns.length - (last - first + 1) };
}

/** Direction glyph + word for a trend, or `null` when nothing was measured. */
export function trendLabel(agent: OrchestrationMapAgent): string | null {
  const trend = agent.trend;
  if (!trend || !trend.direction) return null;
  const arrow =
    trend.direction === "improving" ? "↑" : trend.direction === "declining" ? "↓" : "→";
  return `${arrow} ${trend.direction}${trend.metric ? ` (${trend.metric})` : ""}`;
}
