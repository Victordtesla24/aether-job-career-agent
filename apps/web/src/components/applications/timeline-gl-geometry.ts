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
   * Minimum lane-track width, mirroring the DOM lane's flex `min-width`. The
   * DOM track never shrinks below this, so the GL basis must not either — or
   * auras and ribbons drift off the interactive dots on narrow viewports.
   */
  trackMinW?: number;
};

function laneAccent(status: string): string {
  if (status in STATUS_NODE_COLOR) {
    return STATUS_NODE_COLOR[status as keyof typeof STATUS_NODE_COLOR];
  }
  return "#8C8A82";
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

  const trackW = Math.max(opts.width - opts.labelW, opts.trackMinW ?? 1);
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
