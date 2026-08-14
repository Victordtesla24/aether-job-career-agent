"use client";

/**
 * Agent Orchestration workflow map(s) — S-UI §4.1 TAB 1 (the hero).
 *
 * Renders `GET /agents/orchestration-map`: every catalog agent placed into one
 * or more DEFINED end-to-end workflow maps (the backend ships 3 —
 * application-pipeline / learning-loop / enrichment — per
 * `apps/api/app/routers/agents.py::_ORCHESTRATION_MAPS`), each agent showing
 * its stage, its real-vs-planned status, the metrics it consumes, its
 * threshold responsibilities, its last-run policy tier and its trend.
 *
 * DISTINCT from `components/agents/Orchestration.tsx` (the task-queue /
 * performance / error-log widget) — this is the workflow GRAPH, not the live
 * run monitor.
 *
 * WHAT CHANGED IN S-UI-1 (presentation only — the data contract, the fetch and
 * every honesty rule are untouched): the previous rendition was a stack of
 * text lists. This is a stage-column graph with a real edge layer, per-node
 * detail popovers, and an OPTIONAL WebGL enhancement layer.
 *
 * THE ACCESSIBLE RENDITION IS THE BASE, NOT THE FALLBACK. The DOM node cards,
 * the SVG edges and the semantic stage/agent lists below are what always
 * render — on the server, on the first client paint, with `prefers-reduced-
 * motion: reduce`, and in any browser without WebGL. `OrchestrationMapGL` is
 * mounted on top of that base and draws the SAME edges from the SAME model
 * (`orchestration-map-model.ts`); it carries no fact of its own, so losing it
 * loses nothing.
 *
 * HONESTY INVARIANTS (enforced in the model module, echoed here):
 *   - a `planned` agent NEVER renders an "Implemented"/live badge, never a
 *     policy-tier chip, never a run affordance, and its edge is dashed;
 *   - motion is meaning: an edge pulses only when the source stage has a
 *     genuinely in-flight, NON-stalled run. A stalled run is rendered inert,
 *     in `warn`, with its elapsed time — never as movement (CRITICAL-2);
 *   - "Stage order is the DEFINED pipeline, not a live trace." is always
 *     visible, never hidden in a tooltip.
 *
 * ORCH-RUN (2026-08-14 mandate: "users must be able to run individual,
 * multiple agents or the whole workflow from the Agent Orchestration —
 * Workflow UI"). The map gained three run affordances — per node, per
 * selection, per map — and NOT ONE line of new run machinery. `onRunAgent` is
 * the console's existing `trigger(agent.backend)` path handed in as a prop; it
 * resolves with the SAME truthful `agents-feedback` Notice the banner above the
 * map is already showing, which is what a node quotes when the API refuses. The
 * ordering/dedup/refusal rules live in `orchestration-run-plan.ts`.
 *
 * The telemetry law survives intact: a node's live bloom is still driven by
 * `node.state`, i.e. by the run store, and by nothing this component dispatched.
 * A dispatch in flight disables buttons and narrates itself in words; it never
 * lights a node up. Nothing here can make a node look alive that the run store
 * does not independently report as alive.
 */
import dynamic from "next/dynamic";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { useNow } from "../../hooks/useNow";
import { useRenderCapabilities } from "../../hooks/useRenderCapabilities";
import { parseServerTime } from "../../lib/agent-run-health";
import { runErrorNotice, type Notice } from "../../lib/agents-feedback";
import type { AgentRun } from "../../lib/api/agents";
import type { OrchestrationMapData } from "../../lib/api/agentPolicy";
import StatusBadge from "../ui/StatusBadge";
import {
  buildMapModel,
  lastRunStatusText,
  nodeBadge,
  slugifyStage,
  STAGE_ORDER_FOOTNOTE,
  trendLabel,
  visibleStageRange,
  type EdgeState,
  type MapModel,
  type MapNode,
} from "./orchestration-map-model";
import {
  coveredKeys,
  runAvailability,
  runTargets,
  sharedBackendNote,
  stageNarration,
  type RunTarget,
} from "./orchestration-run-plan";

/**
 * Binding constraint 2 — the three.js layer is code-split and NEVER server
 * rendered. `ssr: false` also guarantees three is absent from the initial HTML
 * payload and from every route that does not mount this component.
 */
const OrchestrationMapGL = dynamic(() => import("./OrchestrationMapGL"), {
  ssr: false,
  loading: () => null,
});

/**
 * Fixed NodeCard height, so every stage column's rows align (S-UI §3.7).
 *
 * 104, not the spec's original 92: the binding U-AX-V4 constraint puts a THIRD
 * line on the face (last-run time), and at the narrowest column a long badge
 * ("LAST RUN FAILED") plus a tier chip legitimately wrap onto two rows. At 92
 * the column-flex card silently shrank that new line to zero height and the
 * `truncate` overflow hid it — MEASURED, not assumed: `after-1600-*` before this
 * change showed "Last run 16 min ago" on the idle cards and nothing at all on
 * the running/failed ones. Cards stay uniform, so the columns still align.
 */
const NODE_H = 104;

/**
 * MEASURED geometry only — deliberately carries NO run state.
 *
 * Run state (which edge is active, which node is live) is merged in at render
 * time instead. That separation matters: `useNow` re-renders this tree every
 * 30s so a run crossing the staleness window is surfaced without a refetch,
 * and if state lived in here every one of those ticks would produce a new
 * geometry object, tear the WebGL context down and build it back up. Geometry
 * now changes only when the layout genuinely changes.
 */
interface ColumnGeom {
  left: number;
  right: number;
  top: number;
  height: number;
}

interface NodeGeom {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Geometry {
  width: number;
  height: number;
  columns: ColumnGeom[];
  nodes: NodeGeom[];
}

const EMPTY_GEOMETRY: Geometry = { width: 0, height: 0, columns: [], nodes: [] };

interface EdgeGeom {
  key: string;
  state: EdgeState;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function sameGeometry(a: Geometry, b: Geometry): boolean {
  if (a.width !== b.width || a.height !== b.height) return false;
  if (a.columns.length !== b.columns.length || a.nodes.length !== b.nodes.length) return false;
  return (
    a.columns.every((c, i) => {
      const o = b.columns[i];
      return c.left === o.left && c.right === o.right && c.top === o.top && c.height === o.height;
    }) &&
    a.nodes.every((n, i) => {
      const o = b.nodes[i];
      return n.id === o.id && n.x === o.x && n.y === o.y && n.w === o.w && n.h === o.h;
    })
  );
}

function edgePath(e: EdgeGeom): string {
  const dx = Math.max(24, (e.x2 - e.x1) * 0.5);
  return `M ${e.x1} ${e.y1} C ${e.x1 + dx} ${e.y1}, ${e.x2 - dx} ${e.y2}, ${e.x2} ${e.y2}`;
}

function formatRunTime(iso: string | null): string {
  const ms = parseServerTime(iso);
  // parseServerTime, not `new Date`: the API's naive UTC stamps carry no
  // timezone designator, so a bare parse renders ten hours out for en-AU.
  return ms === null ? "—" : new Date(ms).toLocaleString("en-AU");
}

// ---------------------------------------------------------------------------
// Node detail popover — portal, re-measured on open (AGENTS-PHANTOM-OVERFLOW-01)
// ---------------------------------------------------------------------------

/**
 * The proven portal + re-measure-on-open pattern (`AgentTip`, `MetricTooltip`).
 * Rendered to `document.body`, never as a DOM descendant of the node, so a
 * closed popover can never inflate the map's scrollable-overflow region, and
 * re-measured while open so a scroll mid-hover cannot leave it pinned to a
 * stale viewport position.
 */
function NodeDetail({
  node,
  open,
  anchor,
  id,
  sharedNote,
}: {
  node: MapNode;
  open: boolean;
  anchor: HTMLElement | null;
  id: string;
  /** "one fitScorer run also covers …" — stated, never left as a surprise. */
  sharedNote: string | null;
}) {
  const [mounted, setMounted] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  useLayoutEffect(() => setMounted(true), []);

  const measure = useCallback(() => {
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect();
    const width = 280;
    const left = Math.min(
      Math.max(8, rect.left),
      Math.max(8, (typeof window === "undefined" ? width + 16 : window.innerWidth) - width - 8),
    );
    setPos({ top: rect.bottom + 8, left });
  }, [anchor]);

  useLayoutEffect(() => {
    if (!open) return;
    measure();
    window.addEventListener("scroll", measure, { passive: true, capture: true });
    window.addEventListener("resize", measure, { passive: true });
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open, measure]);

  if (!mounted) return null;

  const agent = node.agent;
  const trend = trendLabel(agent);
  const badge = nodeBadge(node);

  return createPortal(
    <span
      data-testid={`orchestration-node-detail-${agent.agentKey}`}
      style={{ top: pos.top, left: pos.left }}
      className="pointer-events-none fixed z-50"
    >
      <span
        id={id}
        role="tooltip"
        className={`elev-3 block w-[280px] max-w-[calc(100vw-1rem)] rounded-lg p-3 text-[12px] leading-[1.45] text-aether-muted ${
          open ? "opacity-100" : "hidden opacity-0"
        }`}
      >
        <span className="mb-1.5 flex items-center justify-between gap-2">
          <span className="min-w-0 truncate font-semibold text-aether-text">{agent.name}</span>
          <StatusBadge tone={badge.tone}>{badge.label}</StatusBadge>
        </span>

        {agent.status === "planned" ? (
          <span className="block text-[11px] text-aether-muted-dim">
            A roadmap stage. It has no backend implementation, so it never runs, never
            consumes a metric and never reports a tier.
          </span>
        ) : (
          <>
            <span className="block">
              <span className="text-aether-muted-dim">Consumes: </span>
              {agent.metricsConsumed.length > 0 ? agent.metricsConsumed.join(", ") : "—"}
            </span>
            <span className="mt-0.5 block">
              <span className="text-aether-muted-dim">Threshold: </span>
              {agent.thresholds.length > 0 ? agent.thresholds.join("; ") : "—"}
            </span>
            <span className="mt-0.5 block">
              <span className="text-aether-muted-dim">Last-run tier: </span>
              <span className="font-mono tabular-nums">{agent.lastRunPolicyTier ?? "—"}</span>
            </span>
            <span className="mt-0.5 block">
              <span className="text-aether-muted-dim">Trend: </span>
              {trend ?? "—"}
            </span>
            {/* Binding constraint (U-AX-V4): lastRunAt as RELATIVE time, with
                the absolute stamp kept beside it — a relative label alone is
                unauditable, an absolute one alone is unreadable. */}
            <span className="mt-0.5 block">
              <span className="text-aether-muted-dim">Last run: </span>
              <span className="tabular-nums">{node.lastRunText ?? "—"}</span>
              {node.lastRunAt ? (
                <span className="ml-1 font-mono text-[10px] tabular-nums text-aether-muted-dim">
                  ({formatRunTime(node.lastRunAt)})
                </span>
              ) : null}
            </span>
            {/* …and lastRunStatus, the field U-AX-V4 was about, stated in
                words. `lastRunStatusText` never lets a recorded "running" on a
                dead row stand on its own. */}
            <span className="mt-0.5 block">
              <span className="text-aether-muted-dim">Last status: </span>
              <span data-testid={`orchestration-node-status-${agent.agentKey}`}>
                {lastRunStatusText(node)}
              </span>
            </span>
            {/* ORCH-RUN: three catalog agents share the single `fitScorer`
                backend. Running any of them is ONE metered run that serves all
                three — said here rather than discovered from a bill. */}
            {sharedNote ? (
              <span className="mt-1 block text-[11px] text-aether-muted-dim">
                Shared backend — {sharedNote}.
              </span>
            ) : null}
            {!agent.lastRunPolicyTier && !trend && node.lastRunAt === null ? (
              <span className="mt-1 block text-[11px] text-state-neutral">
                No runs recorded yet — nothing has been measured for this agent.
              </span>
            ) : null}
          </>
        )}
      </span>
    </span>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// NodeCard
// ---------------------------------------------------------------------------

/** Everything a node needs to offer (or honestly refuse) a run of its own. */
interface NodeRunProps {
  /** Whether a run may start right now, and the reason when it may not. */
  runnable: boolean;
  reason: string | null;
  /** This node's backend is the one currently being dispatched by this map. */
  dispatching: boolean;
  /** The truthful notice the LAST dispatch of this node returned; else null. */
  outcome: Notice | null;
  /** "one fitScorer run also covers …", or null. */
  sharedNote: string | null;
  onRun: () => void;
}

function NodeCard({
  node,
  selected,
  onToggleSelect,
  run,
}: {
  node: MapNode;
  /** Part of the current multi-run selection. Never true for a roadmap node. */
  selected: boolean;
  onToggleSelect: ((key: string) => void) | null;
  /** `null` when the console handed the map no trigger — then no run UI exists. */
  run: NodeRunProps | null;
}) {
  const detailId = useId();
  const [hovered, setHovered] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  const agent = node.agent;
  const isPlanned = node.state === "planned";
  const badge = nodeBadge(node);
  const open = hovered;
  const selectable = onToggleSelect !== null && (run?.runnable || selected);

  return (
    <div className="ag-node-shell relative">
      <div className="relative" style={{ height: NODE_H }}>
      <button
        ref={ref}
        type="button"
        data-testid={`orchestration-agent-${agent.agentKey}`}
        data-node-id={agent.agentKey}
        data-state={node.state}
        // Motion is a claim. `data-motion` is the single place that claim is
        // made, so a reviewer can grep it: only a genuinely in-flight,
        // non-stalled run is ever "pulse".
        data-motion={node.state === "live" ? "pulse" : "none"}
        data-selected={selected || undefined}
        aria-describedby={detailId}
        aria-expanded={open}
        aria-pressed={selectable ? selected : undefined}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        // ORCH-RUN: click SELECTS, for the multi-run bar. A node that cannot be
        // run cannot be selected either — putting a roadmap stage in a "Run 3
        // selected" count would be a promise the plan can never keep. The
        // detail popover is unaffected: it opens on hover AND on focus, and a
        // click focuses, so tapping a node on a touch device still reveals it.
        onClick={() => {
          if (selectable && onToggleSelect) onToggleSelect(agent.agentKey);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setHovered(false);
        }}
        // `.ag-node` (agents-console.css) carries the shell: 1px hairline, a
        // top-edge highlight, a soft top-light wash, and — for a node whose
        // `data-motion` is "pulse", i.e. a genuinely in-flight non-stalled run
        // and nothing else — the breathing coral bloom.
        className={`ag-node group relative flex h-full w-full flex-col justify-between p-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/70 ${
          run ? "pr-9" : ""
        } ${isPlanned ? "ag-node-planned opacity-75" : selected ? "ag-node-selected" : ""}`}
      >
        <span className="flex shrink-0 items-start justify-between gap-2">
          <span className="flex min-w-0 items-start gap-1.5">
            <i
              className={`fa-solid fa-circle-nodes mt-[3px] shrink-0 text-[10px] ${
                node.state === "live"
                  ? "text-aether-coral"
                  : node.state === "stalled"
                    ? "text-state-warn"
                    : node.state === "failed"
                      ? "text-state-danger"
                      : "text-state-neutral"
              }`}
              aria-hidden="true"
            />
            {/* Two lines, not one truncated one: at the map's narrowest column
                "Job Discovery Agent" / "ATS Optimization Agent" were being cut
                to "Job Discovery A…". The card height is unchanged (NODE_H) —
                the second line fits inside the existing budget. */}
            <span
              title={agent.name}
              className="line-clamp-2 min-w-0 text-[12px] font-semibold leading-[1.25] tracking-[-0.01em] text-aether-text"
            >
              {agent.name}
            </span>
          </span>
          {/* The ONLY animated element on a node, and only for a run that is
              genuinely in flight. `.live-dot` is frozen by the global
              prefers-reduced-motion block; the badge word beside it is what
              actually carries the fact. */}
          {node.state === "live" ? (
            <span
              className="live-dot mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-aether-coral"
              aria-hidden="true"
            />
          ) : null}
        </span>

        {/* U-AX-V4 (binding): the card itself states WHEN this agent last ran,
            relatively — the defect it transfers from was 18/22 agents reading
            "No runs recorded yet." while the payload knew otherwise. A planned
            agent gets no line at all: it has nothing to be late for. */}
        {isPlanned ? null : (
          <span
            data-testid={`orchestration-agent-lastrun-${agent.agentKey}`}
            // `shrink-0`: this line is a fact, not slack. Without it the column
            // flex box collapses it to zero height whenever the badge row wraps,
            // and `truncate`'s overflow:hidden then hides it completely.
            className="shrink-0 truncate text-[10px] leading-[1.3] tabular-nums text-aether-muted-dim"
          >
            {node.lastRunText ? `Last run ${node.lastRunText}` : "No runs recorded yet"}
          </span>
        )}

        <span className="flex shrink-0 flex-wrap items-center gap-1.5">
          <StatusBadge tone={badge.tone}>{badge.label}</StatusBadge>
          {/* A planned agent never carries a tier chip — it has never run. */}
          {!isPlanned && agent.lastRunPolicyTier ? (
            <span className="rounded border border-hairline-strong px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-aether-muted-dim">
              {agent.lastRunPolicyTier}
            </span>
          ) : null}
        </span>
      </button>

      {/* ---- ORCH-RUN: the per-node run affordance ----
          A real button in the card's right-hand gutter, revealed on hover and
          on keyboard focus (`.ag-node-run`, agents-console.css — never
          `display:none`, so it stays in the tab order). It is DISABLED, with
          the reason in its own tooltip and accessible name, whenever
          `runAvailability` says a run cannot start: a roadmap stage, an agent
          the server does not expose an individual trigger for, an agent whose
          run the store already reports in flight, or a console that is busy
          with something else. It carries no spinner: the request being in
          flight is stated in words on the map's progress line, while the
          node's own live signal keeps coming from the run store alone. */}
      {run ? (
        <button
          type="button"
          data-testid={`orchestration-run-${agent.agentKey}`}
          data-runnable={run.runnable ? "true" : "false"}
          data-persist={run.dispatching || run.outcome ? "true" : undefined}
          disabled={!run.runnable}
          aria-busy={run.dispatching || undefined}
          title={run.reason ?? `Run ${agent.name} now`}
          aria-label={run.reason ? `${agent.name} — ${run.reason}` : `Run ${agent.name} now`}
          onClick={run.onRun}
          className="ag-node-run absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md border border-hairline bg-surface-1 text-aether-muted outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:bg-surface-3 hover:text-aether-text focus-visible:ring-2 focus-visible:ring-aether-coral/70 disabled:cursor-not-allowed disabled:opacity-45"
        >
          <i
            className={`fa-solid ${run.runnable ? "fa-play" : "fa-ban"} text-[9px]`}
            aria-hidden="true"
          />
        </button>
      ) : null}
      </div>

      {/* The result of the LAST dispatch of this node, verbatim — it is the
          same `agents-feedback` Notice the console banner shows, so a quota
          wall, a spend cap or an approval gate reads here in the API's own
          words rather than in a summary this component invented. */}
      {run?.outcome ? (
        <p
          data-testid={`orchestration-run-outcome-${agent.agentKey}`}
          data-tone={run.outcome.kind}
          role={run.outcome.kind === "error" ? "alert" : "status"}
          title={run.outcome.text}
          className={`mt-1.5 rounded-md border px-2 py-1.5 text-[10.5px] leading-[1.45] ${
            run.outcome.kind === "error"
              ? "border-state-danger/30 bg-state-danger/10 text-state-danger"
              : "border-hairline bg-surface-1 text-aether-muted"
          }`}
        >
          {run.outcome.text}
        </p>
      ) : null}

      <NodeDetail
        node={node}
        open={open}
        anchor={ref.current}
        id={detailId}
        sharedNote={run?.sharedNote ?? null}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// One map: stage columns + edge layer (+ optional GL enhancement)
// ---------------------------------------------------------------------------

interface ScrollState {
  left: number;
  client: number;
  total: number;
}

const NO_SCROLL: ScrollState = { left: 0, client: 0, total: 0 };

/**
 * The run surface one map is given, or `null` when the console handed the map
 * no trigger — in which case no run control renders anywhere on it.
 */
interface MapRunApi {
  /** Console-wide in-flight backend ("pipeline" while Run All runs), or null. */
  busyBackend: string | null;
  /** The backend this map is dispatching right now, or null. */
  dispatchingBackend: string | null;
  /** Truthful notices from the current/last batch, keyed by agent key. */
  outcomes: Record<string, Notice>;
  /** Node keys currently selected for a multi-run (this map only). */
  selected: ReadonlySet<string>;
  onToggleSelect: (agentKey: string) => void;
  onRunNode: (agentKey: string) => void;
}

function MapGraph({
  model,
  allowGl,
  runApi,
}: {
  model: MapModel;
  allowGl: boolean;
  runApi: MapRunApi | null;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const stageRefs = useRef<Array<HTMLLIElement | null>>([]);
  const [geometry, setGeometry] = useState<Geometry>(EMPTY_GEOMETRY);
  const [scroll, setScroll] = useState<ScrollState>(NO_SCROLL);

  const stageCount = model.stages.length;

  /**
   * Which nodes share a backend with which — the map's own dedup table, built
   * once per model so a node can disclose "one fitScorer run also covers …"
   * without every card recomputing the whole plan.
   */
  const sharedNotes = useMemo(() => {
    const out: Record<string, string> = {};
    if (!runApi) return out;
    const nameOf = new Map(
      model.stages.flatMap((s) => s.nodes.map((n) => [n.agent.agentKey, n.agent.name] as const)),
    );
    runTargets(model).forEach((target) => {
      const note = sharedBackendNote(target, (key) => nameOf.get(key) ?? key);
      if (!note) return;
      [target.agentKey, ...target.alsoCovers].forEach((key) => {
        out[key] = note;
      });
    });
    return out;
  }, [model, runApi]);

  /** Where the horizontal viewport currently sits — the input to the honest
   *  "showing stages X–Y of N" statement and to the edge scrims. */
  const readScroll = useCallback(() => {
    const host = hostRef.current;
    if (!host) return;
    const next: ScrollState = {
      left: Math.round(host.scrollLeft),
      client: Math.round(host.clientWidth),
      total: Math.round(host.scrollWidth),
    };
    setScroll((prev) =>
      prev.left === next.left && prev.client === next.client && prev.total === next.total
        ? prev
        : next,
    );
  }, []);

  const measure = useCallback(() => {
    const host = hostRef.current;
    if (!host) return;
    const hostRect = host.getBoundingClientRect();
    // A hidden tab panel (or jsdom) reports a zero box. Draw nothing rather
    // than a degenerate graph; the ResizeObserver re-fires when it is shown.
    if (hostRect.width === 0 || hostRect.height === 0) {
      setGeometry((prev) => (prev === EMPTY_GEOMETRY ? prev : EMPTY_GEOMETRY));
      return;
    }

    // CONTENT coordinates, not viewport ones: `getBoundingClientRect` moves
    // with the scroll offset, so a re-measure taken while the map is scrolled
    // would otherwise shift every edge and every stage window by `scrollLeft`.
    const originX = hostRect.left - host.scrollLeft;

    const columns: ColumnGeom[] = [];
    for (let i = 0; i < stageCount; i++) {
      const el = stageRefs.current[i];
      if (!el) break;
      const r = el.getBoundingClientRect();
      columns.push({
        left: r.left - originX,
        right: r.right - originX,
        top: r.top - hostRect.top,
        height: r.height,
      });
    }

    const nodes: NodeGeom[] = [];
    host.querySelectorAll<HTMLElement>("[data-node-id]").forEach((el) => {
      const r = el.getBoundingClientRect();
      nodes.push({
        id: el.dataset.nodeId ?? "",
        x: r.left - originX,
        y: r.top - hostRect.top,
        w: r.width,
        h: r.height,
      });
    });

    // The drawing surface spans the whole CONTENT, not just the visible box:
    // sized to the visible box, every edge past the right-hand fold fell
    // outside the viewBox and simply was not drawn. It is derived from the
    // measured stage columns and NEVER from `host.scrollWidth`, because the
    // edge layer is itself a child of that scroller — feeding its own width
    // back in would latch the map at the widest size it had ever been and
    // manufacture an overflow that is not there.
    const contentRight = columns.reduce((max, c) => Math.max(max, c.right), 0);

    const next: Geometry = {
      width: Math.max(hostRect.width, contentRight),
      height: hostRect.height,
      columns,
      nodes,
    };
    // Identity stability is what keeps the WebGL layer from remounting on a
    // clock tick or a no-op ResizeObserver callback.
    setGeometry((prev) => (sameGeometry(prev, next) ? prev : next));
    readScroll();
  }, [stageCount, readScroll]);

  useLayoutEffect(() => {
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const host = hostRef.current;
    if (!host) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(host);
    return () => ro.disconnect();
  }, [measure]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onResize = () => measure();
    window.addEventListener("resize", onResize, { passive: true });
    return () => window.removeEventListener("resize", onResize);
  }, [measure]);

  // Scroll fires far faster than React can usefully re-render; one frame's
  // worth of coalescing keeps the scrims and the stage counter honest without
  // turning a drag into a render storm.
  const rafRef = useRef(0);
  const onScroll = useCallback(() => {
    if (typeof requestAnimationFrame === "undefined") {
      readScroll();
      return;
    }
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      readScroll();
    });
  }, [readScroll]);

  useEffect(
    () => () => {
      if (rafRef.current && typeof cancelAnimationFrame !== "undefined") {
        cancelAnimationFrame(rafRef.current);
      }
    },
    [],
  );

  // Measured geometry × resolved run state, merged here and nowhere else, so
  // the SVG rendition and the WebGL rendition are drawing from one array.
  const edgeGeoms = useMemo<EdgeGeom[]>(() => {
    const out: EdgeGeom[] = [];
    model.edges.forEach((edge, i) => {
      const a = geometry.columns[i];
      const b = geometry.columns[i + 1];
      if (!a || !b) return;
      out.push({
        key: edge.key,
        state: edge.state,
        x1: a.right,
        y1: a.top + Math.min(a.height, NODE_H) / 2 + 22,
        x2: b.left,
        y2: b.top + Math.min(b.height, NODE_H) / 2 + 22,
      });
    });
    return out;
  }, [geometry, model.edges]);

  const liveNodeIds = useMemo(
    () =>
      new Set(
        model.stages.flatMap((s) => s.nodes.filter((n) => n.state === "live").map((n) => n.agent.agentKey)),
      ),
    [model.stages],
  );

  const hasGeometry = geometry.width > 0 && edgeGeoms.length > 0;

  // ---- Horizontal continuation (S-UI-1 review finding 2) ------------------
  // Seven stage columns at a legible card width do not fit the content column
  // below ~1440px, so the map scrolls there. A SILENT clip is the defect the
  // review caught: the SUBMISSION stage ended at the viewport edge with no
  // signal that anything followed. Everything below is measured — when nothing
  // has been measured yet (SSR, hidden tab, jsdom) no claim is made at all.
  const overflowing = scroll.total > scroll.client + 2;
  const moreLeft = overflowing && scroll.left > 2;
  const moreRight = overflowing && scroll.left + scroll.client < scroll.total - 2;
  const stageWindow = useMemo(
    () => visibleStageRange(geometry.columns, scroll.left, scroll.client),
    [geometry.columns, scroll.left, scroll.client],
  );
  const continuation = useMemo(() => {
    if (!overflowing || !stageWindow || stageWindow.hidden <= 0) return null;
    const total = model.stages.length;
    const nextIdx = stageWindow.last + 1 < total ? stageWindow.last + 1 : stageWindow.first - 1;
    const nextStage = model.stages[nextIdx]?.stage;
    const direction = stageWindow.last + 1 < total ? "right" : "left";
    const shown =
      stageWindow.first === stageWindow.last
        ? `stage ${stageWindow.first + 1}`
        : `stages ${stageWindow.first + 1}–${stageWindow.last + 1}`;
    return nextStage
      ? `Showing ${shown} of ${total} — scroll ${direction} for “${nextStage}”.`
      : `Showing ${shown} of ${total} — scroll to see the rest.`;
  }, [overflowing, stageWindow, model.stages]);

  // A single serialised signature keeps the GL layer's props referentially
  // stable across re-renders that changed nothing it can see (the 30s clock
  // tick being the common one) — without it, three would tear down and rebuild
  // its context twice a minute.
  const glSignature = useMemo(
    () =>
      JSON.stringify({
        w: Math.round(geometry.width),
        h: Math.round(geometry.height),
        e: edgeGeoms.map((e) => [
          e.key,
          e.state,
          Math.round(e.x1),
          Math.round(e.y1),
          Math.round(e.x2),
          Math.round(e.y2),
        ]),
        n: geometry.nodes.map((n) => [
          n.id,
          Math.round(n.x),
          Math.round(n.y),
          Math.round(n.w),
          Math.round(n.h),
          liveNodeIds.has(n.id) ? 1 : 0,
        ]),
      }),
    [geometry, edgeGeoms, liveNodeIds],
  );

  const glProps = useMemo(() => {
    const s = JSON.parse(glSignature) as {
      w: number;
      h: number;
      e: [string, EdgeState, number, number, number, number][];
      n: [string, number, number, number, number, number][];
    };
    return {
      width: s.w,
      height: s.h,
      edges: s.e.map(([key, state, x1, y1, x2, y2]) => ({ key, state, x1, y1, x2, y2 })),
      nodes: s.n.map(([id, x, y, w, h, live]) => ({ id, x, y, w, h, live: live === 1 })),
    };
  }, [glSignature]);

  return (
    <div className="relative">
      <div className="relative">
        <div
          ref={hostRef}
          data-testid={`orchestration-graph-${model.key}`}
          data-overflowing={overflowing || undefined}
          onScroll={onScroll}
          // WCAG 2.1.1: a scrollable region must be reachable from the keyboard
          // in its own right, not only by tabbing through what it contains.
          tabIndex={0}
          role="group"
          aria-label={`${model.name} stage map`}
          className="relative overflow-x-auto pb-1 snap-x outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/40 [scrollbar-width:thin] lg:snap-none"
        >
          {/* ---- Edge layer (always present; the GL layer only adds to it) ---- */}
          <svg
            data-testid={`orchestration-edges-${model.key}`}
            aria-hidden="true"
            width={geometry.width || undefined}
            height={geometry.height || undefined}
            viewBox={hasGeometry ? `0 0 ${geometry.width} ${geometry.height}` : undefined}
            style={{ width: geometry.width || undefined }}
            className="pointer-events-none absolute inset-0 h-full"
          >
            {edgeGeoms.map((e) => (
              <g key={e.key} data-edge-state={e.state} data-motion={e.state === "active" ? "pulse" : "none"}>
                <path
                  d={edgePath(e)}
                  fill="none"
                  stroke={
                    e.state === "active"
                      ? "#FF6B35"
                      : e.state === "planned"
                        ? "rgba(255,255,255,0.07)"
                        : "rgba(255,255,255,0.13)"
                  }
                  strokeWidth={e.state === "active" ? 1.75 : 1.25}
                  strokeDasharray={e.state === "planned" ? "5 5" : undefined}
                  strokeLinecap="round"
                />
                {/* Rule: nothing moves unless something real moves. The dot only
                    exists for an edge whose source stage has a live, non-stalled
                    run — and the global prefers-reduced-motion block freezes it
                    for a viewer who asked for stillness. */}
                {e.state === "active" ? (
                  <circle r="3.5" fill="#FF6B35">
                    <animateMotion dur="2.2s" repeatCount="indefinite" path={edgePath(e)} />
                  </circle>
                ) : null}
              </g>
            ))}
          </svg>

          {/* ---- Optional WebGL enhancement, drawn from the SAME geometry ---- */}
          {allowGl && hasGeometry ? (
            <OrchestrationMapGL
              mapKey={model.key}
              width={glProps.width}
              height={glProps.height}
              edges={glProps.edges}
              nodes={glProps.nodes}
            />
          ) : null}

          {/* ---- Stage columns (the semantic, accessible base) ----
              136px is the measured floor at which a node card still holds the
              verbatim "PLANNED — ROADMAP" badge and a readable name; `1fr` lets
              every column grow to fill a wider screen. 7 stages × 136 + 6 × 20px
              gaps = 1072px, which fits the real content column (viewport − the
              fixed sidebar − page padding) from ~1440px up. Below that the map
              scrolls — announced, never silently clipped. */}
          <ol className="relative grid grid-flow-col auto-cols-[minmax(136px,1fr)] gap-x-5">
            {model.stages.map((stage, i) => (
              <li
                key={stage.stage}
                ref={(el) => {
                  stageRefs.current[i] = el;
                }}
                data-testid={`orchestration-stage-${slugifyStage(stage.stage)}`}
                className="min-w-0 snap-start"
              >
                <h4 className="ag-stage-label mb-2.5 truncate">{stage.stage}</h4>
                <ol className="space-y-3">
                  {stage.nodes.map((node) => {
                    const key = node.agent.agentKey;
                    const availability = runApi
                      ? runAvailability(node, {
                          busyBackend: runApi.busyBackend,
                          dispatching: runApi.dispatchingBackend
                            ? new Set([runApi.dispatchingBackend])
                            : undefined,
                        })
                      : null;
                    return (
                      <li key={key}>
                        <NodeCard
                          node={node}
                          selected={runApi?.selected.has(key) ?? false}
                          onToggleSelect={runApi ? runApi.onToggleSelect : null}
                          run={
                            runApi && availability
                              ? {
                                  runnable: availability.runnable,
                                  reason: availability.reason,
                                  dispatching:
                                    runApi.dispatchingBackend !== null &&
                                    runApi.dispatchingBackend === node.agent.backend,
                                  outcome: runApi.outcomes[key] ?? null,
                                  sharedNote: sharedNotes[key] ?? null,
                                  onRun: () => runApi.onRunNode(key),
                                }
                              : null
                          }
                        />
                      </li>
                    );
                  })}
                </ol>
              </li>
            ))}
          </ol>
        </div>

        {/* ---- Continuation scrims: rendered ONLY while there really is more
             content in that direction, so the affordance is never decorative. */}
        {moreLeft ? (
          <span
            aria-hidden="true"
            data-testid={`orchestration-scrim-left-${model.key}`}
            className="pointer-events-none absolute inset-y-0 left-0 w-8 bg-gradient-to-r from-surface-1 to-transparent"
          />
        ) : null}
        {moreRight ? (
          <span
            aria-hidden="true"
            data-testid={`orchestration-scrim-right-${model.key}`}
            className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-surface-1 to-transparent"
          />
        ) : null}
      </div>

      {/* ---- The clipped stage, stated in words (S-UI-1 review finding 2) ----
          A fade alone is a hint; this is the fact. It names how many stages the
          viewer can actually see and which one is next, so a stage that runs
          past the fold can never be mistaken for the end of the pipeline. */}
      {continuation ? (
        <p
          data-testid={`orchestration-scroll-hint-${model.key}`}
          aria-live="polite"
          className="mt-2 flex items-center gap-1.5 text-[11px] leading-[1.5] text-aether-muted"
        >
          <i className="fa-solid fa-arrows-left-right shrink-0 text-[10px]" aria-hidden="true" />
          <span>{continuation}</span>
        </p>
      ) : null}

      {/* ---- Legend + the required, always-visible honesty footnote ---- */}
      <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-hairline pt-3.5 text-[11px] leading-[1.5] text-aether-muted-dim">
        <span className="flex items-center gap-2">
          <span
            className="h-1.5 w-1.5 rounded-full bg-aether-coral shadow-[0_0_8px_1px_rgba(255,107,53,0.8)]"
            aria-hidden="true"
          />
          live run — the only thing that moves
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-px w-5 bg-hairline-strong" aria-hidden="true" />
          solid = implemented stage transition
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-5 border-t border-dashed border-hairline-strong" aria-hidden="true" />
          dashed = planned (roadmap)
        </span>
      </div>
      <p
        data-testid={`orchestration-footnote-${model.key}`}
        className="mt-2 flex items-start gap-1.5 text-[11px] leading-[1.5] text-aether-muted-dim"
      >
        <i className="fa-solid fa-circle-info mt-[3px] shrink-0 text-[10px]" aria-hidden="true" />
        <span>
          {STAGE_ORDER_FOOTNOTE}
          {model.stalledCount > 0 ? (
            <span className="text-state-warn">
              {" "}
              {model.stalledCount} run{model.stalledCount === 1 ? " is" : "s are"} stalled — shown
              inert, never as movement.
            </span>
          ) : null}
        </span>
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ORCH-RUN — the batch runner
// ---------------------------------------------------------------------------

/**
 * One in-progress (or just-finished) run of a plan, scoped to one map.
 *
 * Everything on it is OBSERVED: `outcomes` are the notices the trigger path
 * actually returned, `index` is how far the sequential dispatch really got, and
 * `halted` records the refusal that ended it. Nothing is predicted forward.
 */
interface BatchState {
  mapKey: string;
  targets: RunTarget[];
  /** Index of the target being dispatched; `targets.length` once all are done. */
  index: number;
  outcomes: Record<string, Notice>;
  /** The refusal that ended the batch early, if one did. */
  halted: { agentKey: string; name: string; text: string } | null;
  finished: boolean;
}

export default function OrchestrationMap({
  data,
  runs = [],
  now: nowProp,
  onRunAgent,
  busyBackend = null,
}: {
  data: OrchestrationMapData;
  /** Live run history (GET /agents/runs). Absent ⇒ every node reads "Idle". */
  runs?: AgentRun[];
  /** Test seam only — production reads the shared clock. */
  now?: number;
  /**
   * The console's EXISTING per-agent trigger (`trigger(agent.backend)` in
   * `app/dashboard/agents/page.tsx`), which resolves with the same truthful
   * `agents-feedback` Notice it puts in the banner. Omitted ⇒ the map renders
   * exactly as it did before, with no run affordance anywhere: a map with no
   * way to run something must not show buttons that cannot work.
   */
  onRunAgent?: (backend: string) => Promise<Notice>;
  /**
   * The console-wide in-flight backend — the same `busy` the Run All button
   * disables itself on ("pipeline" while the full pipeline runs). Mirrored here
   * so the map runs one thing at a time, exactly as the pipeline does.
   */
  busyBackend?: string | null;
}) {
  // Staleness is a function of elapsed time, not of any server event, so the
  // map re-renders on a clock as well as on realtime refetches; otherwise a
  // run that dies while the screen is open keeps its live dot until reload.
  const clock = useNow();
  const now = nowProp ?? clock;
  const { allowGl } = useRenderCapabilities();

  const models = useMemo(
    () => data.maps.map((entry) => buildMapModel(entry, runs, now)),
    [data, runs, now],
  );

  // ---- Selection (one map at a time — the run bar is one bar) -------------
  const [selection, setSelection] = useState<{ mapKey: string; keys: string[] }>({
    mapKey: "",
    keys: [],
  });
  const [batch, setBatch] = useState<BatchState | null>(null);
  const batchLock = useRef(false);
  // Read at dispatch time, so a batch keeps using a live trigger even though
  // the page re-renders (and hands a new closure) on every `busy` transition.
  const triggerRef = useRef(onRunAgent);
  triggerRef.current = onRunAgent;

  const clearSelection = useCallback(() => setSelection({ mapKey: "", keys: [] }), []);

  useEffect(() => {
    if (selection.keys.length === 0 || typeof document === "undefined") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") clearSelection();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [selection.keys.length, clearSelection]);

  const toggleSelect = useCallback((mapKey: string, agentKey: string) => {
    setSelection((prev) => {
      // Selecting into a different map replaces the selection rather than
      // silently building one that spans two maps with two stage orders.
      if (prev.mapKey !== mapKey) return { mapKey, keys: [agentKey] };
      return prev.keys.includes(agentKey)
        ? { mapKey, keys: prev.keys.filter((k) => k !== agentKey) }
        : { mapKey, keys: [...prev.keys, agentKey] };
    });
  }, []);

  /**
   * Dispatch a plan, ONE AT A TIME, halting on the first refusal.
   *
   * That is Run All's shape, not a choice made here: `_pipeline_core` runs its
   * six nodes sequentially and an exception from any of them ends the rest. A
   * quota or spend-cap wall is exactly such a refusal, and pressing on would
   * only collect N identical rejections while the first one is the answer.
   */
  const runPlan = useCallback(async (mapKey: string, targets: RunTarget[], nameOf: Map<string, string>) => {
    const trigger = triggerRef.current;
    if (!trigger || targets.length === 0 || batchLock.current) return;
    batchLock.current = true;
    setBatch({ mapKey, targets, index: 0, outcomes: {}, halted: null, finished: false });
    try {
      for (let i = 0; i < targets.length; i += 1) {
        const target = targets[i];
        setBatch((prev) => (prev ? { ...prev, index: i } : prev));
        let outcome: Notice;
        try {
          outcome = await trigger(target.backend);
        } catch (e) {
          // The trigger path already renders its own banner; this keeps the
          // node in agreement with it using the same truthful formatter.
          outcome = runErrorNotice(e, target.backend);
        }
        const keys = [target.agentKey, ...target.alsoCovers];
        const refused = outcome.kind === "error";
        setBatch((prev) => {
          if (!prev || prev.mapKey !== mapKey) return prev;
          const outcomes = { ...prev.outcomes };
          keys.forEach((k) => {
            outcomes[k] = outcome;
          });
          return {
            ...prev,
            outcomes,
            index: i + 1,
            halted: refused
              ? {
                  agentKey: target.agentKey,
                  name: nameOf.get(target.agentKey) ?? target.backend,
                  text: outcome.text,
                }
              : prev.halted,
            finished: refused || i + 1 === targets.length,
          };
        });
        if (refused) break;
      }
    } finally {
      batchLock.current = false;
      setBatch((prev) => (prev ? { ...prev, finished: true } : prev));
    }
  }, []);

  const nameMaps = useMemo(
    () =>
      new Map(
        models.map((model) => [
          model.key,
          new Map(
            model.stages.flatMap((s) =>
              s.nodes.map((n) => [n.agent.agentKey, n.agent.name] as const),
            ),
          ),
        ]),
      ),
    [models],
  );

  const startRun = useCallback(
    (model: MapModel, only?: ReadonlySet<string>) => {
      const targets = runTargets(model, only);
      void runPlan(model.key, targets, nameMaps.get(model.key) ?? new Map());
    },
    [runPlan, nameMaps],
  );

  const batchActive = batch !== null && !batch.finished;
  const dispatchingBackend = batchActive ? (batch.targets[batch.index]?.backend ?? null) : null;

  const selectedModel = models.find((m) => m.key === selection.mapKey) ?? null;
  const selectedSet = useMemo(() => new Set(selection.keys), [selection.keys]);
  const selectionPlan = useMemo(
    () => (selectedModel ? runTargets(selectedModel, selectedSet) : []),
    [selectedModel, selectedSet],
  );

  return (
    <div className="space-y-4" data-testid="orchestration-map">
      {models.map((model) => {
        const plan = onRunAgent ? runTargets(model) : [];
        const mapBatch = batch && batch.mapKey === model.key ? batch : null;
        const runApi: MapRunApi | null = onRunAgent
          ? {
              busyBackend,
              dispatchingBackend,
              outcomes: mapBatch?.outcomes ?? {},
              selected: selection.mapKey === model.key ? selectedSet : EMPTY_SELECTION,
              onToggleSelect: (agentKey) => toggleSelect(model.key, agentKey),
              onRunNode: (agentKey) => startRun(model, new Set([agentKey])),
            }
          : null;
        const workflowBlocked = batchActive
          ? "A run is already in progress — one at a time, as Run All does"
          : busyBackend
            ? busyBackend === "pipeline"
              ? "Run All is in progress — one run at a time"
              : `${busyBackend} is running — one run at a time`
            : plan.length === 0
              ? "Nothing in this map is individually runnable"
              : null;

        return (
        <section
          key={model.key}
          data-testid={`orchestration-map-${model.key}`}
          className="ag-panel relative overflow-hidden p-5"
        >
          <header className="mb-5 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              <h3 className="text-[16px] font-semibold leading-tight tracking-[-0.022em]">
                {model.name}
              </h3>
              {model.subtitle ? (
                <p className="mt-1 max-w-[70ch] text-[12.5px] leading-[1.55] text-aether-muted">
                  {model.subtitle}
                </p>
              ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <p className="font-mono text-[11px] tabular-nums text-aether-muted-dim">
                {model.stages.length} stage{model.stages.length === 1 ? "" : "s"} ·{" "}
                {model.stages.reduce((n, s) => n + s.nodes.length, 0)} agents
                {model.liveCount > 0 ? (
                  // The map header's live count is the one place a running total
                  // gets the brand hue — it points at the node that is blooming.
                  <span className="font-semibold text-aether-coral">
                    {" "}
                    · {model.liveCount} running
                  </span>
                ) : null}
                {model.stalledCount > 0 ? (
                  <span className="text-state-warn"> · {model.stalledCount} stalled</span>
                ) : null}
              </p>
              {/* ORCH-RUN 3 — "Run All" scoped to THIS map: every runnable
                  agent it contains, in its own stage order, one at a time. The
                  count is the PLAN's, not the node count, because three nodes
                  sharing the fitScorer backend are one run. */}
              {onRunAgent ? (
                <button
                  type="button"
                  data-testid={`orchestration-run-workflow-${model.key}`}
                  onClick={() => startRun(model)}
                  disabled={workflowBlocked !== null}
                  title={
                    workflowBlocked ??
                    `Run all ${plan.length} runnable agent${plan.length === 1 ? "" : "s"} in ${model.name}, in stage order`
                  }
                  className="flex shrink-0 items-center gap-2 rounded-md border border-hairline bg-surface-1 px-2.5 py-1.5 text-[11.5px] font-medium outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-aether-coral/70 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45"
                >
                  <i className="fa-solid fa-play text-[9px]" aria-hidden="true" />
                  Run workflow
                </button>
              ) : null}
            </div>
          </header>

          {/* ---- ORCH-RUN honest progress ----
              Stage-by-stage, and every number in it measured: "running" is
              counted from the RUN STORE (a node this batch covers that the
              store independently reports live), "done"/"failed" from the
              dispatches that have actually reported back — no completion is
              ever claimed before its notice arrives. Every stage the plan
              touches is listed from the start, including the ones the dispatch
              has not reached: "0 running / 0 done" is the TRUE state of a stage
              nothing has run yet, and revealing stages one at a time would make
              the plan look shorter than it is. */}
          {mapBatch ? (
            <BatchProgress
              batch={mapBatch}
              model={model}
              mapName={model.name}
              onDismiss={() => setBatch(null)}
            />
          ) : null}

          <MapGraph model={model} allowGl={allowGl} runApi={runApi} />

          {/* The edge layer is decorative (aria-hidden); this states the same
              topology in words so a screen reader loses nothing when the
              curves — SVG or WebGL — are unavailable. */}
          <p className="sr-only" data-testid={`orchestration-topology-${model.key}`}>
            {model.name} stage order:{" "}
            {model.stages.map((s) => s.stage).join(" then ")}.{" "}
            {STAGE_ORDER_FOOTNOTE}
          </p>
        </section>
        );
      })}

      {/* ---- ORCH-RUN 2 — the multi-select run bar ----
          Appears only while a selection exists, states the count, and states
          the PLAN size beside it whenever dedup makes the two differ, so
          "3 selected · 1 run" is visible before the button is pressed rather
          than inferred from the bill afterwards. */}
      {onRunAgent && selectedModel && selection.keys.length > 0 ? (
        <div
          data-testid="orchestration-run-bar"
          role="region"
          aria-label="Selected agents"
          // Above BOTH the node popover (z-50) and the mobile tab bar (z-40),
          // and lifted clear of that tab bar below `lg` — a run bar the viewer
          // cannot reach is not an affordance. It wraps rather than clipping at
          // 390px, where "Run 3 selected" and "Clear" do not fit on one line.
          className="elev-3 fixed bottom-[76px] left-1/2 z-[60] flex w-[calc(100vw-1.5rem)] max-w-[560px] -translate-x-1/2 flex-wrap items-center justify-center gap-x-3 gap-y-2 rounded-xl border border-hairline-strong bg-surface-1 px-3.5 py-2.5 text-[12px] lg:bottom-6 lg:w-auto lg:flex-nowrap"
        >
          {/* At 390px the count and both buttons cannot share one line, so the
              count takes its own row rather than pushing "Clear" onto a third. */}
          <span className="w-full min-w-0 text-center tabular-nums text-aether-muted lg:w-auto lg:text-left">
            <span className="font-semibold text-aether-text">{selection.keys.length} selected</span>
            <span className="text-aether-muted-dim"> in {selectedModel.name}</span>
            {selectionPlan.length !== selection.keys.length ? (
              <span className="text-aether-muted-dim">
                {" "}
                · {selectionPlan.length} run{selectionPlan.length === 1 ? "" : "s"} (shared backends)
              </span>
            ) : null}
          </span>
          <button
            type="button"
            data-testid="orchestration-run-selected"
            onClick={() => startRun(selectedModel, selectedSet)}
            disabled={batchActive || busyBackend !== null || selectionPlan.length === 0}
            title={
              batchActive
                ? "A run is already in progress — one at a time, as Run All does"
                : busyBackend
                  ? `${busyBackend === "pipeline" ? "Run All" : busyBackend} is running — one run at a time`
                  : `Run the selection in ${selectedModel.name}'s stage order`
            }
            className="flex shrink-0 items-center gap-2 whitespace-nowrap rounded-md bg-aether-coral px-3 py-1.5 text-[12px] font-semibold text-black outline-none transition-opacity duration-[var(--dur-fast)] hover:opacity-90 focus-visible:ring-2 focus-visible:ring-aether-coral/70 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45"
          >
            <i className="fa-solid fa-play text-[9px]" aria-hidden="true" />
            Run {selection.keys.length} selected
          </button>
          <button
            type="button"
            data-testid="orchestration-run-clear"
            onClick={clearSelection}
            title="Clear the selection (Esc)"
            className="rounded-md border border-hairline px-2.5 py-1.5 text-[11.5px] font-medium text-aether-muted outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:text-aether-text focus-visible:ring-2 focus-visible:ring-aether-coral/70"
          >
            Clear
          </button>
        </div>
      ) : null}
    </div>
  );
}

const EMPTY_SELECTION: ReadonlySet<string> = new Set<string>();

// ---------------------------------------------------------------------------
// ORCH-RUN — stage-by-stage narration, from measured state only
// ---------------------------------------------------------------------------

function BatchProgress({
  batch,
  model,
  mapName,
  onDismiss,
}: {
  batch: BatchState;
  model: MapModel;
  mapName: string;
  onDismiss: () => void;
}) {
  const stateOf = useMemo(() => {
    const out = new Map<string, MapNode>();
    model.stages.forEach((s) => s.nodes.forEach((n) => out.set(n.agent.agentKey, n)));
    return out;
  }, [model.stages]);

  // One narration line per stage the plan touches, in the plan's own order.
  const lines = useMemo(() => {
    const byStage = new Map<string, { stage: string; keys: string[] }>();
    batch.targets.forEach((t) => {
      const bucket = byStage.get(t.stage) ?? { stage: t.stage, keys: [] };
      bucket.keys.push(...coveredKeys([t]));
      byStage.set(t.stage, bucket);
    });
    return [...byStage.values()].map(({ stage, keys }) => {
      let running = 0;
      let done = 0;
      let failed = 0;
      keys.forEach((key) => {
        // "running" is the RUN STORE's verdict on this node, never this
        // component's — a dispatch in flight is not a run in flight.
        if (stateOf.get(key)?.state === "live") running += 1;
        const outcome = batch.outcomes[key];
        if (!outcome) return;
        if (outcome.kind === "error") failed += 1;
        else done += 1;
      });
      return stageNarration(stage, { running, done, failed });
    });
  }, [batch.targets, batch.outcomes, stateOf]);

  const current = batch.targets[Math.min(batch.index, batch.targets.length - 1)];
  const headline = batch.halted
    ? `Stopped at ${batch.halted.name} — ${batch.halted.text}`
    : batch.finished
      ? `Dispatched ${batch.targets.length} of ${batch.targets.length} in ${mapName}. Each agent's own result is on its node and in the banner above.`
      : `Running ${mapName} — dispatch ${batch.index + 1} of ${batch.targets.length}: ${current?.backend ?? ""}`;

  return (
    <div
      data-testid={`orchestration-run-progress-${model.key}`}
      data-halted={batch.halted ? "true" : undefined}
      role="status"
      aria-live="polite"
      className={`mb-4 flex flex-wrap items-start gap-x-3 gap-y-1.5 rounded-lg border px-3 py-2.5 text-[11.5px] leading-[1.5] ${
        batch.halted
          ? "border-state-danger/30 bg-state-danger/[0.07] text-state-danger"
          : "border-hairline bg-surface-1 text-aether-muted"
      }`}
    >
      <span className="font-medium">{headline}</span>
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1 tabular-nums text-aether-muted-dim">
        {lines.map((line) => (
          <span key={line}>{line}</span>
        ))}
      </span>
      {batch.finished ? (
        <button
          type="button"
          data-testid={`orchestration-run-dismiss-${model.key}`}
          onClick={onDismiss}
          className="ml-auto rounded border border-hairline px-2 py-0.5 text-[11px] font-medium text-aether-muted outline-none transition-colors duration-[var(--dur-fast)] hover:border-hairline-strong hover:text-aether-text focus-visible:ring-2 focus-visible:ring-aether-coral/70"
        >
          Dismiss
        </button>
      ) : null}
    </div>
  );
}
