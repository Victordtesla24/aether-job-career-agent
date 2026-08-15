"use client";

/**
 * `<Radar10>` (spec alias `<RadarPlot>`) — the 10-dimension job-fit profile,
 * S-UI-REBUILD-SPEC §4.3 row 4, and the chart the spec calls "the single most
 * dangerous in the product".
 *
 * Why: a radar has a centre, and a centre means zero. Collapsing a dimension
 * nobody measured onto the centre draws a SPECIFIC FALSE CLAIM about a
 * candidate — "scored 0 on leadership" — that no data supports. So:
 *   · an unmeasured dimension gets NO vertex, at any radius;
 *   · it gets a hollow state-neutral marker parked on the outer ring, where
 *     the axis label lives, which reads as "axis present, no value";
 *   · the polygon edge that spans it is dashed;
 *   · its label is struck through (C-5: never colour alone);
 *   · the legend states how many dimensions are missing, and the data table
 *     carries each one's reason verbatim.
 *
 * `measured` is decided upstream by `lib/scoring/provenance.ts::fitDimensionsFrom`,
 * which fails closed. This component never re-derives it, and ignores any
 * `score` that arrives on a dimension flagged unmeasured.
 */
import { ChartFrame } from "./ChartFrame";
import { NOT_MEASURED, formatNumber, polarPoint } from "./geometry";
import { useChartMotion } from "./motion";
import { EmptyPlot } from "./primitives";
import { CHART_PALETTE, GRIDLINE, HAIRLINE, STATE } from "./tokens";
import type { ChartDatum, PlotGeometry } from "./types";

export type RadarDimension =
  | { label: string; measured: true; score: number; note?: string }
  | {
      label: string;
      measured: false;
      /** Tolerated but IGNORED — an unmeasured dimension has no value, and a
       *  stray number on the wire must never become a vertex. */
      score?: number | null;
      reason?: string;
    };

export interface Radar10Props {
  title: string;
  /** C-3 — required. */
  windowLabel: string;
  dimensions: readonly RadarDimension[];
  /** Full-scale value at the outer ring. */
  max?: number;
  /** How many dimensions the caller expects; a shortfall is stated, never
   *  padded with invented spokes. */
  expectedDimensions?: number;
  height?: number;
  footnote?: string;
  className?: string;
}

const RING_FRACTIONS = [0.25, 0.5, 0.75, 1] as const;
const MIN_POLYGON_VERTICES = 3;
const STROKE = CHART_PALETTE[0];

export function Radar10({
  title,
  windowLabel,
  dimensions,
  max = 100,
  expectedDimensions = 10,
  height = 300,
  footnote,
  className,
}: Radar10Props) {
  const motion = useChartMotion();
  const data: ChartDatum[] = dimensions.map((dim) =>
    dim.measured
      ? { label: dim.label, value: dim.score, note: dim.note }
      : { label: dim.label, value: null, note: dim.reason },
  );
  const unmeasuredCount = dimensions.filter((d) => !d.measured).length;
  const shortfall = Math.max(0, expectedDimensions - dimensions.length);

  return (
    <ChartFrame
      title={title}
      windowLabel={windowLabel}
      scale={{ kind: "linear" }}
      data={data}
      nullMeaning={
        unmeasuredCount > 0
          ? "dimension not measured for this job — see each row's reason"
          : undefined
      }
      height={height}
      padding={{ top: 20, right: 20, bottom: 20, left: 20 }}
      footnote={footnote}
      className={className}
      legend={
        unmeasuredCount > 0 || shortfall > 0 ? (
          <div className="flex flex-col gap-0.5 text-[11px]" style={{ color: STATE.neutral }}>
            {unmeasuredCount > 0 ? (
              <p data-prose="legend" data-testid="radar-unmeasured-note">
                {`${formatNumber(unmeasuredCount)} ${
                  unmeasuredCount === 1 ? "dimension is" : "dimensions"
                } not measured — shown as a hollow marker on the axis, not as a zero. See notes.`}
              </p>
            ) : null}
            {shortfall > 0 ? (
              <p data-prose="legend" data-testid="radar-shortfall">
                {`Only ${formatNumber(dimensions.length)} of ${formatNumber(
                  expectedDimensions,
                )} dimensions were returned for this job.`}
              </p>
            ) : null}
          </div>
        ) : undefined
      }
    >
      {dimensions.length === 0 ? (
        <EmptyPlot
          message="No fit dimensions have been calculated for this job yet."
          hint="Dimensions appear once the job has been scored against your résumé."
        />
      ) : (
        (geom: PlotGeometry) => (
          <RadarPlotBody
            geom={geom}
            dimensions={dimensions}
            max={max}
            atOrigin={motion.atOrigin}
            transition={motion.transition("transform")}
          />
        )
      )}
    </ChartFrame>
  );
}

interface RadarPoint {
  x: number;
  y: number;
}

type RadarVertex =
  | { index: number; label: string; measured: false; reason?: string; point: RadarPoint }
  | {
      index: number;
      label: string;
      measured: true;
      score: number;
      point: RadarPoint;
      at: RadarPoint;
    };

function RadarPlotBody({
  geom,
  dimensions,
  max,
  atOrigin,
  transition,
}: {
  geom: PlotGeometry;
  dimensions: readonly RadarDimension[];
  max: number;
  atOrigin: boolean;
  transition: string | undefined;
}) {
  const { plot } = geom;
  const cx = plot.x + plot.width / 2;
  const cy = plot.y + plot.height / 2;
  const radius = Math.max(10, Math.min(plot.width, plot.height) / 2 - 34);
  const count = dimensions.length;

  const vertices: RadarVertex[] = dimensions.map((dim, index) => {
    const point = polarPoint(cx, cy, radius, index, count);
    // Fail closed: `measured: false` wins over any score that rode along.
    if (!dim.measured) {
      return { index, label: dim.label, measured: false, reason: dim.reason, point };
    }
    const ratio = Math.max(0, Math.min(1, dim.score / (max || 1)));
    return {
      index,
      label: dim.label,
      measured: true,
      score: dim.score,
      point,
      at: polarPoint(cx, cy, radius * ratio, index, count),
    };
  });

  const measuredVertices = vertices.filter(
    (v): v is Extract<RadarVertex, { measured: true }> => v.measured,
  );
  const canDrawPolygon = measuredVertices.length >= MIN_POLYGON_VERTICES;

  const edges = canDrawPolygon
    ? measuredVertices.map((vertex, i) => {
        const next = measuredVertices[(i + 1) % measuredVertices.length];
        const bridged = (vertex.index + 1) % count !== next.index;
        return { from: vertex, to: next, bridged };
      })
    : [];

  const polygonPoints = measuredVertices.map((v) => `${v.at.x},${v.at.y}`).join(" ");

  return (
    <g
      style={
        atOrigin || transition
          ? {
              transformOrigin: `${cx}px ${cy}px`,
              transform: atOrigin ? "scale(0.92)" : undefined,
              transition,
            }
          : undefined
      }
    >
      {RING_FRACTIONS.map((fraction, index) => {
        const isOuter = index === RING_FRACTIONS.length - 1;
        return (
          <circle
            key={`ring-${fraction}`}
            data-ring={String(Math.round(fraction * max))}
            data-testid={isOuter ? "radar-ring-outer" : "radar-ring"}
            cx={cx}
            cy={cy}
            r={radius * fraction}
            fill="none"
            stroke={isOuter ? HAIRLINE : GRIDLINE}
            strokeWidth={1}
          />
        );
      })}

      {RING_FRACTIONS.map((fraction) => (
        <text
          key={`ring-label-${fraction}`}
          data-testid="ring-label"
          x={cx + 4}
          y={cy - radius * fraction}
          className="font-mono text-[10px] tabular-nums"
          fill={STATE.neutral}
          dominantBaseline="middle"
        >
          {formatNumber(Math.round(fraction * max))}
        </text>
      ))}

      {vertices.map((vertex) => (
        <line
          key={`spoke-${vertex.index}`}
          data-spoke={String(vertex.index)}
          x1={cx}
          y1={cy}
          x2={vertex.point.x}
          y2={vertex.point.y}
          stroke={GRIDLINE}
          strokeWidth={1}
        />
      ))}

      {canDrawPolygon ? (
        <polygon
          data-testid="radar-polygon"
          data-partial={measuredVertices.length < count ? "true" : "false"}
          points={polygonPoints}
          fill={STROKE}
          fillOpacity={measuredVertices.length < count ? 0.1 : 0.18}
          stroke="none"
        />
      ) : null}

      {edges.map((edge) => (
        <line
          key={`edge-${edge.from.index}-${edge.to.index}`}
          data-edge={`${edge.from.index}-${edge.to.index}`}
          data-bridged={edge.bridged ? "true" : "false"}
          x1={edge.from.at.x}
          y1={edge.from.at.y}
          x2={edge.to.at.x}
          y2={edge.to.at.y}
          stroke={edge.bridged ? STATE.neutral : STROKE}
          strokeWidth={2}
          strokeDasharray={edge.bridged ? "4 3" : undefined}
        />
      ))}

      {vertices.map((vertex) =>
        vertex.measured ? (
          <circle
            key={`vertex-${vertex.index}`}
            data-spoke-vertex={String(vertex.index)}
            cx={vertex.at.x}
            cy={vertex.at.y}
            r={3}
            fill={STROKE}
          >
            <title>{`${vertex.label}: ${formatNumber(vertex.score)} of ${formatNumber(
              max,
            )}`}</title>
          </circle>
        ) : (
          <circle
            key={`unmeasured-${vertex.index}`}
            data-unmeasured-spoke={String(vertex.index)}
            data-mark="unmeasured"
            cx={vertex.point.x}
            cy={vertex.point.y}
            r={4}
            fill="none"
            stroke={STATE.neutral}
            strokeWidth={1}
            strokeDasharray="2 2"
          >
            <title>{`${vertex.label}: not measured — ${
              vertex.reason ?? "reason not provided"
            }`}</title>
          </circle>
        ),
      )}

      {vertices.map((vertex) => {
        const label = polarPoint(cx, cy, radius + 18, vertex.index, count);
        const anchor =
          Math.abs(label.x - cx) < 4 ? "middle" : label.x > cx ? "start" : "end";
        return (
          <text
            key={`label-${vertex.index}`}
            data-axis-label={String(vertex.index)}
            x={label.x}
            y={label.y}
            textAnchor={anchor}
            dominantBaseline="middle"
            className="text-[10px]"
            fill={vertex.measured ? "rgba(245,241,232,0.62)" : STATE.neutral}
            textDecoration={vertex.measured ? undefined : "line-through"}
          >
            {vertex.measured ? vertex.label : `${vertex.label} ${NOT_MEASURED}`}
          </text>
        );
      })}
    </g>
  );
}

/** Spec name (S-UI-REBUILD-SPEC §4.3) for the same component. */
export { Radar10 as RadarPlot };
