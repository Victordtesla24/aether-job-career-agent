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
import type { AgentRun } from "../../lib/api/agents";
import type { OrchestrationMapData } from "../../lib/api/agentPolicy";
import StatusBadge from "../ui/StatusBadge";
import {
  buildMapModel,
  nodeBadge,
  slugifyStage,
  STAGE_ORDER_FOOTNOTE,
  trendLabel,
  type EdgeState,
  type MapModel,
  type MapNode,
} from "./orchestration-map-model";

/**
 * Binding constraint 2 — the three.js layer is code-split and NEVER server
 * rendered. `ssr: false` also guarantees three is absent from the initial HTML
 * payload and from every route that does not mount this component.
 */
const OrchestrationMapGL = dynamic(() => import("./OrchestrationMapGL"), {
  ssr: false,
  loading: () => null,
});

const NODE_H = 92; // S-UI §3.7: fixed-height NodeCard, so columns align.

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
}: {
  node: MapNode;
  open: boolean;
  anchor: HTMLElement | null;
  id: string;
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
            <span className="mt-0.5 block">
              <span className="text-aether-muted-dim">Last run: </span>
              <span className="font-mono text-[11px] tabular-nums">
                {formatRunTime(node.lastRunAt)}
              </span>
            </span>
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

function NodeCard({
  node,
  focused,
  onFocusNode,
}: {
  node: MapNode;
  focused: boolean;
  onFocusNode: (key: string | null) => void;
}) {
  const detailId = useId();
  const [hovered, setHovered] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  const agent = node.agent;
  const isPlanned = node.state === "planned";
  const badge = nodeBadge(node);
  const open = hovered || focused;

  return (
    <>
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
        data-focused={focused || undefined}
        aria-describedby={detailId}
        aria-expanded={open}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        onClick={() => onFocusNode(focused ? null : agent.agentKey)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setHovered(false);
            onFocusNode(null);
          }
        }}
        style={{ height: NODE_H }}
        className={`group relative flex w-full flex-col justify-between rounded-xl p-3 text-left outline-none transition-[border-color,background-color] duration-[var(--dur)] focus-visible:ring-2 focus-visible:ring-aether-coral/70 ${
          isPlanned
            ? "border border-dashed border-hairline-strong bg-surface-0 opacity-75"
            : focused
              ? "border border-aether-coral/50 bg-surface-3"
              : "elev-1 hover:border-hairline-strong hover:bg-surface-2"
        }`}
      >
        <span className="flex items-start justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5">
            <i
              className={`fa-solid fa-circle-nodes shrink-0 text-[11px] ${
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
            <span
              title={agent.name}
              className="min-w-0 truncate text-[12px] font-semibold text-aether-text"
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

        <span className="flex flex-wrap items-center gap-1.5">
          <StatusBadge tone={badge.tone}>{badge.label}</StatusBadge>
          {/* A planned agent never carries a tier chip — it has never run. */}
          {!isPlanned && agent.lastRunPolicyTier ? (
            <span className="rounded border border-hairline-strong px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-aether-muted-dim">
              {agent.lastRunPolicyTier}
            </span>
          ) : null}
        </span>
      </button>
      <NodeDetail node={node} open={open} anchor={ref.current} id={detailId} />
    </>
  );
}

// ---------------------------------------------------------------------------
// One map: stage columns + edge layer (+ optional GL enhancement)
// ---------------------------------------------------------------------------

function MapGraph({ model, allowGl }: { model: MapModel; allowGl: boolean }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const stageRefs = useRef<Array<HTMLLIElement | null>>([]);
  const [geometry, setGeometry] = useState<Geometry>(EMPTY_GEOMETRY);
  const [focusedNode, setFocusedNode] = useState<string | null>(null);

  const stageCount = model.stages.length;

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

    const columns: ColumnGeom[] = [];
    for (let i = 0; i < stageCount; i++) {
      const el = stageRefs.current[i];
      if (!el) break;
      const r = el.getBoundingClientRect();
      columns.push({
        left: r.left - hostRect.left,
        right: r.right - hostRect.left,
        top: r.top - hostRect.top,
        height: r.height,
      });
    }

    const nodes: NodeGeom[] = [];
    host.querySelectorAll<HTMLElement>("[data-node-id]").forEach((el) => {
      const r = el.getBoundingClientRect();
      nodes.push({
        id: el.dataset.nodeId ?? "",
        x: r.left - hostRect.left,
        y: r.top - hostRect.top,
        w: r.width,
        h: r.height,
      });
    });

    const next: Geometry = {
      width: hostRect.width,
      height: hostRect.height,
      columns,
      nodes,
    };
    // Identity stability is what keeps the WebGL layer from remounting on a
    // clock tick or a no-op ResizeObserver callback.
    setGeometry((prev) => (sameGeometry(prev, next) ? prev : next));
  }, [stageCount]);

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
      <div
        ref={hostRef}
        data-testid={`orchestration-graph-${model.key}`}
        className="relative overflow-x-auto pb-1 snap-x [scrollbar-width:thin] lg:snap-none"
      >
        {/* ---- Edge layer (always present; the GL layer only adds to it) ---- */}
        <svg
          data-testid={`orchestration-edges-${model.key}`}
          aria-hidden="true"
          width={geometry.width || undefined}
          height={geometry.height || undefined}
          viewBox={hasGeometry ? `0 0 ${geometry.width} ${geometry.height}` : undefined}
          className="pointer-events-none absolute inset-0 h-full w-full"
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

        {/* ---- Stage columns (the semantic, accessible base) ---- */}
        <ol className="relative grid grid-flow-col auto-cols-[minmax(190px,1fr)] gap-x-10">
          {model.stages.map((stage, i) => (
            <li
              key={stage.stage}
              ref={(el) => {
                stageRefs.current[i] = el;
              }}
              data-testid={`orchestration-stage-${slugifyStage(stage.stage)}`}
              className="min-w-0 snap-start"
            >
              <h4 className="mb-2 truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-aether-muted-dim">
                {stage.stage}
              </h4>
              <ol className="space-y-3">
                {stage.nodes.map((node) => (
                  <li key={node.agent.agentKey}>
                    <NodeCard
                      node={node}
                      focused={focusedNode === node.agent.agentKey}
                      onFocusNode={setFocusedNode}
                    />
                  </li>
                ))}
              </ol>
            </li>
          ))}
        </ol>
      </div>

      {/* ---- Legend + the required, always-visible honesty footnote ---- */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-hairline pt-3 text-[11px] text-aether-muted-dim">
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-aether-coral" aria-hidden="true" />
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
// Public component
// ---------------------------------------------------------------------------

export default function OrchestrationMap({
  data,
  runs = [],
  now: nowProp,
}: {
  data: OrchestrationMapData;
  /** Live run history (GET /agents/runs). Absent ⇒ every node reads "Idle". */
  runs?: AgentRun[];
  /** Test seam only — production reads the shared clock. */
  now?: number;
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

  return (
    <div className="space-y-4" data-testid="orchestration-map">
      {models.map((model) => (
        <section
          key={model.key}
          data-testid={`orchestration-map-${model.key}`}
          className="elev-1 relative overflow-hidden rounded-2xl p-5"
        >
          <header className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              <h3 className="text-[15px] font-semibold tracking-[-0.01em]">{model.name}</h3>
              {model.subtitle ? (
                <p className="mt-0.5 text-[13px] leading-[1.5] text-aether-muted">{model.subtitle}</p>
              ) : null}
            </div>
            <p className="shrink-0 font-mono text-[11px] tabular-nums text-aether-muted-dim">
              {model.stages.length} stage{model.stages.length === 1 ? "" : "s"} ·{" "}
              {model.stages.reduce((n, s) => n + s.nodes.length, 0)} agents
              {model.liveCount > 0 ? (
                <span className="text-state-ok"> · {model.liveCount} running</span>
              ) : null}
              {model.stalledCount > 0 ? (
                <span className="text-state-warn"> · {model.stalledCount} stalled</span>
              ) : null}
            </p>
          </header>

          <MapGraph model={model} allowGl={allowGl} />

          {/* The edge layer is decorative (aria-hidden); this states the same
              topology in words so a screen reader loses nothing when the
              curves — SVG or WebGL — are unavailable. */}
          <p className="sr-only" data-testid={`orchestration-topology-${model.key}`}>
            {model.name} stage order:{" "}
            {model.stages.map((s) => s.stage).join(" then ")}.{" "}
            {STAGE_ORDER_FOOTNOTE}
          </p>
        </section>
      ))}
    </div>
  );
}
