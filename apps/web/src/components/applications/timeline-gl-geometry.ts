/**
 * Timeline WebGL geometry — pure functions (SESSION TL-VIZ-R2).
 *
 * DOM and Three.js share this layout so the GPU layer cannot invent a node,
 * edge, colour, or highlight the accessible view does not already own.
 */
import type { TimelineModel } from "./timeline-model";
import { STATUS_NODE_COLOR } from "./timeline-model";

export type TimelineGlNode = {
  id: string;
  applicationId: string;
  x: number;
  y: number;
  color: string;
  highlighted: boolean;
  genesis: boolean;
};

export type TimelineGlEdge = {
  key: string;
  applicationId: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
  highlighted: boolean;
};

export type TimelineGlRail = {
  applicationId: string;
  y: number;
  x0: number;
  x1: number;
  color: string;
  highlighted: boolean;
};

export type TimelineGlGeometry = {
  nodes: TimelineGlNode[];
  edges: TimelineGlEdge[];
  rails: TimelineGlRail[];
};

export type TimelineGlBuildOpts = {
  width: number;
  labelW: number;
  padX: number;
  laneH: number;
  hoverId: string | null;
  hoverAppId: string | null;
  /**
   * Minimum lane-track width. The DOM lane track's inline `minWidth` is
   * computed by this same {@link laneTrackWidth} function with the same
   * floor, so the GL basis can never drift from what is actually rendered
   * (TL-VIZ-R4 / D2 — GL/DOM x-misalignment).
   */
  trackMinW: number;
};

function laneAccent(status: string): string {
  if (status in STATUS_NODE_COLOR) {
    return STATUS_NODE_COLOR[status as keyof typeof STATUS_NODE_COLOR];
  }
  return "#8C8A82";
}

/**
 * Single source of truth for the lane-track width, shared by the DOM lane
 * track's inline `minWidth` style and this module's GL geometry basis. Both
 * call sites must feed this the same `rowWidth` (the measured full-row
 * width), `labelW`, and `trackMinW` — never re-derive the formula locally —
 * or the WebGL auras/ribbons drift off the interactive DOM dots on narrow
 * viewports (TL-VIZ-R4 / D2).
 */
export function laneTrackWidth(
  rowWidth: number,
  labelW: number,
  trackMinW: number,
): number {
  return Math.max(rowWidth - labelW, trackMinW);
}

/**
 * Map model lanes into CSS-pixel GL geometry (y increases downward).
 */
export function buildTimelineGlGeometry(
  model: TimelineModel,
  opts: TimelineGlBuildOpts,
): TimelineGlGeometry {
  if (model.empty || opts.width <= 0) {
    return { nodes: [], edges: [], rails: [] };
  }

  const trackW = laneTrackWidth(opts.width, opts.labelW, opts.trackMinW);
  const usable = Math.max(trackW - opts.padX * 2, 1);
  const nodes: TimelineGlNode[] = [];
  const edges: TimelineGlEdge[] = [];
  const rails: TimelineGlRail[] = [];

  model.lanes.forEach((lane, i) => {
    const y = i * opts.laneH + opts.laneH / 2;
    const laneHot =
      opts.hoverAppId === lane.applicationId ||
      lane.nodes.some((n) => n.id === opts.hoverId);
    const accent = laneAccent(lane.status);

    rails.push({
      applicationId: lane.applicationId,
      y,
      x0: opts.labelW + opts.padX,
      x1: opts.labelW + opts.padX + usable,
      color: accent,
      highlighted: laneHot,
    });

    const placed: TimelineGlNode[] = [];
    for (const n of lane.nodes) {
      const node: TimelineGlNode = {
        id: n.id,
        applicationId: lane.applicationId,
        x: opts.labelW + opts.padX + usable * n.x,
        y,
        color: n.color,
        highlighted: opts.hoverId === n.id,
        genesis: n.genesis,
      };
      nodes.push(node);
      placed.push(node);
    }

    for (let j = 0; j < placed.length - 1; j++) {
      const a = placed[j]!;
      const b = placed[j + 1]!;
      edges.push({
        key: `${a.id}-${b.id}`,
        applicationId: lane.applicationId,
        x1: a.x,
        y1: a.y,
        x2: b.x,
        y2: b.y,
        color: b.color,
        highlighted: laneHot,
      });
    }
  });

  return { nodes, edges, rails };
}
