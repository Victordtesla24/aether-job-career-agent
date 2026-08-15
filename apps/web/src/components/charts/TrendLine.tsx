"use client";

/**
 * `<TrendLine>` — S-UI-REBUILD-SPEC §4.3 row 2.
 *
 * Three refusals are the whole point of this component:
 *   1. Fewer than 3 MEASURED points and it draws nothing. Two points are a
 *      line segment, not a trend, and a single point with a slope is a claim
 *      nobody measured.
 *   2. A gap in the data is drawn as a gap — the stroke stops, a dashed bridge
 *      spans the hole, and the legend says what the dash means. Straight-lining
 *      through a missing day invents the day.
 *   3. A baseline above zero is an axis break with a chip, never a silent
 *      exaggeration of a small change (C-4).
 *
 * Above CANVAS_POINT_THRESHOLD points it switches to canvas — the single case
 * the spec authorises canvas for — and says so if the browser cannot give it a
 * drawing context.
 */
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { ChartFrame } from "./ChartFrame";
import { formatNumber, niceTicks } from "./geometry";
import { useChartMotion } from "./motion";
import { AxisLabel, EmptyPlot, Gridlines } from "./primitives";
import { CANVAS_POINT_THRESHOLD, CHART_PALETTE, STATE } from "./tokens";
import type { ChartDatum, PlotGeometry } from "./types";

export interface TrendPoint {
  label: string;
  /** `null` = no measurement for this interval. Drawn as a gap, never as 0. */
  value: number | null;
  note?: string;
}

export interface TrendLineProps {
  title: string;
  /** C-3 — required. */
  windowLabel: string;
  points: readonly TrendPoint[];
  /** `"zero"` (default, honest) or `"data-min"`, which declares an axis break. */
  baseline?: "zero" | "data-min";
  /** C-2 — required when the series mixes a real 0 with a null. */
  nullMeaning?: string;
  height?: number;
  footnote?: string;
  className?: string;
}

const STROKE = CHART_PALETTE[1]; // c2 indigo-300
const MIN_POINTS = 3;

interface Run {
  from: number;
  to: number;
  points: Array<{ index: number; value: number }>;
}

function measuredRuns(points: readonly TrendPoint[]): Run[] {
  const runs: Run[] = [];
  let open = false;
  for (let index = 0; index < points.length; index += 1) {
    const value = points[index].value;
    if (typeof value !== "number") {
      open = false;
      continue;
    }
    if (!open) {
      runs.push({ from: index, to: index, points: [] });
      open = true;
    }
    const run = runs[runs.length - 1];
    run.to = index;
    run.points.push({ index, value });
  }
  return runs;
}

export function TrendLine({
  title,
  windowLabel,
  points,
  baseline = "zero",
  nullMeaning,
  height = 180,
  footnote,
  className,
}: TrendLineProps) {
  const motion = useChartMotion(600);
  const data: ChartDatum[] = points.map((p) => ({
    label: p.label,
    value: p.value,
    note: p.note,
  }));
  const measured = points.filter((p) => typeof p.value === "number") as Array<
    TrendPoint & { value: number }
  >;
  const values = measured.map((p) => p.value);
  const dataMin = values.length ? Math.min(...values) : 0;
  const dataMax = values.length ? Math.max(...values) : 0;
  const yMin = baseline === "data-min" && values.length ? dataMin : 0;
  const truncated = yMin !== 0;
  const oversized = points.length > CANVAS_POINT_THRESHOLD;

  const hasGap = measuredRuns(points).length > 1;
  const frameProps = {
    title,
    windowLabel,
    scale: { kind: "linear" as const, baseline: yMin, truncated },
    data,
    nullMeaning,
    height,
    footnote,
    className,
    legend: hasGap ? (
      <p
        data-prose="legend"
        data-testid="trend-gap-legend"
        className="text-[11px] text-aether-muted-dim"
        style={{ color: STATE.neutral }}
      >
        Dashed segment = no data for that interval. The line is not drawn through it, because
        nothing was measured there.
      </p>
    ) : undefined,
  };

  if (measured.length < MIN_POINTS) {
    return (
      <ChartFrame {...frameProps}>
        <EmptyPlot
          message={`A trend needs at least ${MIN_POINTS} measured points — ${formatNumber(
            measured.length,
          )} so far.`}
          hint="No line is drawn until then: interpolating between two points would invent a trend."
        />
      </ChartFrame>
    );
  }

  if (oversized) {
    return (
      <ChartFrame {...frameProps}>
        <TrendCanvas points={measured} height={height} yMin={yMin} yMax={dataMax} />
      </ChartFrame>
    );
  }

  return (
    <ChartFrame {...frameProps}>
      {(geom: PlotGeometry) => (
        <TrendSvg
          geom={geom}
          points={points}
          yMin={yMin}
          yMax={dataMax}
          motionTransition={motion.transition("stroke-dashoffset")}
          atOrigin={motion.atOrigin}
        />
      )}
    </ChartFrame>
  );
}

function TrendSvg({
  geom,
  points,
  yMin,
  yMax,
  motionTransition,
  atOrigin,
}: {
  geom: PlotGeometry;
  points: readonly TrendPoint[];
  yMin: number;
  yMax: number;
  motionTransition: string | undefined;
  atOrigin: boolean;
}) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const { plot } = geom;
  const span = yMax - yMin > 0 ? yMax - yMin : 1;
  const stepX = points.length > 1 ? plot.width / (points.length - 1) : 0;
  const x = (index: number) => plot.x + index * stepX;
  const y = (value: number) => plot.y + plot.height - ((value - yMin) / span) * plot.height;

  const runs = measuredRuns(points);
  const ticks = niceTicks(yMax - yMin, 4).map((t) => t + yMin);
  const gradientId = `trend-fill-${uid}`;

  const measured = points
    .map((point, index) => ({ index, value: point.value, label: point.label }))
    .filter((p): p is { index: number; value: number; label: string } => typeof p.value === "number");
  const minPoint = measured.reduce((a, b) => (b.value < a.value ? b : a));
  const maxPoint = measured.reduce((a, b) => (b.value > a.value ? b : a));
  const firstPoint = measured[0];
  const lastPoint = measured[measured.length - 1];
  const markers = new Map<number, string>();
  markers.set(firstPoint.index, "first");
  markers.set(minPoint.index, "min");
  markers.set(maxPoint.index, "max");
  markers.set(lastPoint.index, "last");

  const areaPath = runs
    .filter((run) => run.points.length > 1)
    .map((run) => {
      const head = run.points
        .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.index)},${y(p.value)}`)
        .join(" ");
      const baseY = plot.y + plot.height;
      return `${head} L${x(run.points[run.points.length - 1].index)},${baseY} L${x(
        run.points[0].index,
      )},${baseY} Z`;
    })
    .join(" ");

  return (
    <>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={STROKE} stopOpacity={0.28} />
          <stop offset="100%" stopColor={STROKE} stopOpacity={0} />
        </linearGradient>
      </defs>

      <Gridlines geom={geom} ticks={ticks} max={yMax} min={yMin} />
      <AxisLabel x={plot.x - 6} y={plot.y + plot.height}>
        {formatNumber(Math.round(yMin))}
      </AxisLabel>
      <AxisLabel x={plot.x - 6} y={plot.y + 4}>
        {formatNumber(Math.round(yMax))}
      </AxisLabel>

      {areaPath ? (
        <path data-testid="trend-area" d={areaPath} fill={`url(#${gradientId})`} stroke="none" />
      ) : null}

      {/* A gap is a gap: the bridge is dashed and explained in the legend. */}
      {runs.slice(0, -1).map((run, index) => {
        const next = runs[index + 1];
        const a = run.points[run.points.length - 1];
        const b = next.points[0];
        return (
          <line
            key={`bridge-${a.index}-${b.index}`}
            data-testid="trend-bridge"
            x1={x(a.index)}
            y1={y(a.value)}
            x2={x(b.index)}
            y2={y(b.value)}
            stroke={STATE.neutral}
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        );
      })}

      {runs
        .filter((run) => run.points.length > 1)
        .map((run) => {
          const d = run.points
            .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.index)},${y(p.value)}`)
            .join(" ");
          return (
            <path
              key={`run-${run.from}-${run.to}`}
              data-testid="trend-path"
              d={d}
              fill="none"
              stroke={STROKE}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              pathLength={1}
              style={
                atOrigin || motionTransition
                  ? {
                      strokeDasharray: 1,
                      strokeDashoffset: atOrigin ? 1 : 0,
                      transition: motionTransition,
                    }
                  : undefined
              }
            />
          );
        })}

      {/* Markers only at meaningful points (reference-pack rule 5). */}
      {Array.from(markers.entries()).map(([index, kind]) => {
        const point = measured.find((p) => p.index === index);
        if (!point) return null;
        return (
          <circle
            key={`marker-${kind}-${index}`}
            data-marker={kind}
            cx={x(index)}
            cy={y(point.value)}
            r={3}
            fill={STROKE}
            stroke="#0F0F12"
            strokeWidth={1}
          >
            <title>{`${point.label}: ${formatNumber(point.value)}`}</title>
          </circle>
        );
      })}
    </>
  );
}

/**
 * The one authorised canvas path (S-UI-REBUILD-SPEC §4.1): above 2,000 points
 * an SVG path is 2,000 DOM nodes for no visual gain. If the browser refuses a
 * 2d context the component SAYS so and points at the data table rather than
 * leaving a convincing empty rectangle on screen.
 */
function TrendCanvas({
  points,
  height,
  yMin,
  yMax,
}: {
  points: ReadonlyArray<{ label: string; value: number }>;
  height: number;
  yMin: number;
  yMax: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [drawn, setDrawn] = useState(false);
  const series = useMemo(() => points.map((p) => p.value), [points]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let context: CanvasRenderingContext2D | null = null;
    try {
      context = canvas.getContext("2d");
    } catch {
      context = null;
    }
    if (!context) {
      setDrawn(false);
      return;
    }
    const width = canvas.clientWidth || canvas.width;
    const ratio = typeof window === "undefined" ? 1 : Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.max(1, Math.round(width * ratio));
    canvas.height = Math.max(1, Math.round(height * ratio));
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);

    const span = yMax - yMin > 0 ? yMax - yMin : 1;
    const stepX = series.length > 1 ? width / (series.length - 1) : 0;
    context.beginPath();
    series.forEach((value, index) => {
      const px = index * stepX;
      const py = height - ((value - yMin) / span) * height;
      if (index === 0) context.moveTo(px, py);
      else context.lineTo(px, py);
    });
    context.strokeStyle = STROKE;
    context.lineWidth = 1.5;
    context.stroke();
    setDrawn(true);
  }, [series, height, yMin, yMax]);

  return (
    <div className="relative w-full" style={{ height }}>
      <canvas ref={canvasRef} className="h-full w-full" data-testid="trend-canvas" />
      {!drawn ? (
        <p
          data-prose="status"
          data-testid="canvas-unavailable"
          className="absolute inset-0 flex items-center justify-center px-4 text-center text-[12px]"
          style={{ color: STATE.neutral }}
        >
          This browser did not provide a drawing surface for {formatNumber(series.length)} points —
          the values are listed in this chart&apos;s data table.
        </p>
      ) : null}
    </div>
  );
}
