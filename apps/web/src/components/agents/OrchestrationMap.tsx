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
        <span className="flex shrink-0 items-start justify-between gap-2">
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
      <NodeDetail node={node} open={open} anchor={ref.current} id={detailId} />
    </>
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

function MapGraph({ model, allowGl }: { model: MapModel; allowGl: boolean }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const stageRefs = useRef<Array<HTMLLIElement | null>>([]);
  const [geometry, setGeometry] = useState<Geometry>(EMPTY_GEOMETRY);
  const [scroll, setScroll] = useState<ScrollState>(NO_SCROLL);
  const [focusedNode, setFocusedNode] = useState<string | null>(null);

  const stageCount = model.stages.length;

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
