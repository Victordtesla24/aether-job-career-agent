/**
 * ORCH-RUN — the run PLAN for a workflow map, as pure data.
 *
 * The three run affordances the console exposes on every orchestration map
 * (run one node, run a selection, run the whole map) are three different
 * SELECTIONS over one plan, dispatched through one path. This module owns that
 * plan so the rules below are testable on their own and cannot be re-decided,
 * differently, inside a renderer:
 *
 *   1. ORDER IS THE MAP'S OWN STAGE ORDER — left-to-right stage groups, and
 *      within a stage the order `GET /agents/orchestration-map` returned. That
 *      is the only ordering the payload actually defines (the same reason the
 *      map draws stage-to-stage edges and never agent-to-agent ones).
 *   2. CONCURRENCY MIRRORS "RUN ALL", WHICH IS SEQUENTIAL. The pipeline
 *      endpoint (`apps/api/app/routers/agents.py::_pipeline_core`) dispatches
 *      supervisor → scout → fitScorer → matcher → tailor → coverLetter one at a
 *      time, and an exception from any step aborts the rest. A map run is that
 *      same shape scoped to a map: one dispatch in flight, halt on refusal.
 *   3. ONE BACKEND, ONE RUN. Three catalog agents (`matchScoring`,
 *      `atsOptimization`, `skillGap`) share the single `fitScorer` backend, so
 *      dispatching per NODE would bill three metered runs for one unit of work
 *      and Run All only ever dispatches it once. Targets are therefore deduped
 *      by backend, first-in-stage-order wins, and the nodes that share it are
 *      carried on `alsoCovers` so the UI can say so instead of hiding it.
 *   4. RUNNABILITY IS THE SERVER'S CALL, NOT THE UI'S. `agent.runnable` is
 *      computed from `_RUNNABLE_BACKENDS` — the set of backends
 *      `_agent_callable` actually resolves. `orchestration` (backend
 *      `supervisor`) is REAL but not independently dispatchable, and the UI
 *      must say that rather than offer a button whose only possible outcome is
 *      a 404.
 *
 * Nothing here starts a run, reads a clock, or touches React.
 */
import type { MapModel, MapNode } from "./orchestration-map-model";

/** Verbatim disabled reason for a roadmap node (never runnable, by construction). */
export const PLANNED_RUN_REASON = "Roadmap — not yet runnable";

/** A real agent the backend does not expose an individual trigger for. */
export const NOT_DISPATCHABLE_REASON =
  "No individual trigger — this agent only runs as part of the pipeline";

/** One dispatch in a run plan. */
export interface RunTarget {
  /** The node that leads this dispatch (first in stage order for its backend). */
  agentKey: string;
  /** The backend name handed to the console's existing trigger path. */
  backend: string;
  /** The stage the leading node sits in — the narration's subject. */
  stage: string;
  /** 0-based index of that stage in the map, i.e. the dispatch order group. */
  stageIndex: number;
  /**
   * Other node keys in this plan that dispatch the SAME backend. One run
   * serves all of them; they are listed so the UI can state that rather than
   * imply each got its own run.
   */
  alsoCovers: string[];
}

/**
 * Is this node dispatchable at all, ignoring anything currently in flight?
 *
 * `runnable` is nullish on payloads older than the field, so `undefined` is
 * treated as "the server did not say" and falls back to the structural test
 * (real + has a backend). It never upgrades a `false` to a `true`.
 */
export function isRunnableNode(node: MapNode): boolean {
  if (node.state === "planned" || node.agent.status === "planned") return false;
  if (!node.agent.backend) return false;
  return node.agent.runnable !== false;
}

/**
 * The ordered, deduped dispatch plan for a map.
 *
 * @param only  When given, restricts the plan to these node keys (a selection).
 *              Nodes outside it are dropped, including from `alsoCovers` —
 *              a selection never silently runs a node the user did not pick.
 */
export function runTargets(model: MapModel, only?: ReadonlySet<string>): RunTarget[] {
  const byBackend = new Map<string, RunTarget>();
  const order: string[] = [];

  model.stages.forEach((stage, stageIndex) => {
    stage.nodes.forEach((node) => {
      const key = node.agent.agentKey;
      if (only && !only.has(key)) return;
      if (!isRunnableNode(node)) return;
      const backend = node.agent.backend as string;
      const existing = byBackend.get(backend);
      if (existing) {
        existing.alsoCovers.push(key);
        return;
      }
      byBackend.set(backend, {
        agentKey: key,
        backend,
        stage: stage.stage,
        stageIndex,
        alsoCovers: [],
      });
      order.push(backend);
    });
  });

  return order.map((backend) => byBackend.get(backend) as RunTarget);
}

/** Every node key one plan will report an outcome for (leader + shared nodes). */
export function coveredKeys(targets: readonly RunTarget[]): string[] {
  return targets.flatMap((t) => [t.agentKey, ...t.alsoCovers]);
}

/** What is in flight right now, from evidence the console genuinely holds. */
export interface RunContext {
  /**
   * The console-wide in-flight backend — `"pipeline"` while Run All is going,
   * an agent backend while a single trigger is, `null` when nothing is. This is
   * the same `busy` value the Run All button already disables itself on.
   */
  busyBackend?: string | null;
  /** Backends THIS map has dispatched and not yet seen settle. */
  dispatching?: ReadonlySet<string>;
}

export interface RunAvailability {
  runnable: boolean;
  /** Honest, user-facing reason a run cannot start; `null` when it can. */
  reason: string | null;
}

/**
 * Whether a node's run affordance may fire, and if not, why — in the user's
 * words, never a shrug.
 *
 * A node reading `live` from the run store is the SSE/poll-fed truth that a run
 * is genuinely in flight for that backend; it is refused here for the same
 * reason Run All refuses while `busy` is set — the console runs one thing at a
 * time, exactly like the pipeline it mirrors.
 */
export function runAvailability(node: MapNode, ctx: RunContext = {}): RunAvailability {
  if (node.state === "planned" || node.agent.status === "planned") {
    return { runnable: false, reason: PLANNED_RUN_REASON };
  }
  if (!node.agent.backend) {
    return { runnable: false, reason: PLANNED_RUN_REASON };
  }
  if (node.agent.runnable === false) {
    return { runnable: false, reason: NOT_DISPATCHABLE_REASON };
  }
  const backend = node.agent.backend;
  if (node.state === "live") {
    return { runnable: false, reason: "Already running — wait for this run to finish" };
  }
  if (ctx.dispatching?.has(backend)) {
    return { runnable: false, reason: "Already dispatched — waiting for it to report back" };
  }
  const busy = ctx.busyBackend ?? null;
  if (busy) {
    return {
      runnable: false,
      reason:
        busy === "pipeline"
          ? "Run All is in progress — one run at a time"
          : `${busy} is running — one run at a time`,
    };
  }
  return { runnable: true, reason: null };
}

/** Per-stage progress counts, every one of them measured, none inferred. */
export interface StageCounts {
  /** Nodes of this stage the RUN STORE currently reports as genuinely live. */
  running: number;
  /** Dispatches of this stage that have reported back without an error. */
  done: number;
  /** Dispatches of this stage the API refused or that failed. */
  failed: number;
}

/**
 * The stage-by-stage narration line, e.g. `Fit Scoring — 2 running / 1 done`.
 *
 * `failed` is appended only when there is something to report, so a clean run
 * never carries a zero that reads like a warning.
 */
export function stageNarration(stage: string, counts: StageCounts): string {
  const parts = [`${counts.running} running`, `${counts.done} done`];
  if (counts.failed > 0) parts.push(`${counts.failed} failed`);
  return `${stage} — ${parts.join(" / ")}`;
}

/**
 * How the shared trigger path names an agent that runs one backend on behalf of
 * several catalog nodes — "fitScorer (also covers ATS Optimization, Skill Gap)".
 * Returns `null` when the target is nothing but itself.
 */
export function sharedBackendNote(
  target: RunTarget,
  nameOf: (agentKey: string) => string,
): string | null {
  if (target.alsoCovers.length === 0) return null;
  const names = target.alsoCovers.map(nameOf).join(", ");
  return `one ${target.backend} run also covers ${names}`;
}
