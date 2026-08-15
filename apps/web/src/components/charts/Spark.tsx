"use client";

/**
 * `<Spark>` — the kit's MICRO mark, for a stat tile that must carry a shape as
 * well as a numeral (ANALYTICS-VIZ executive summary band).
 *
 * It is a full member of the kit, not a decoration:
 *   · it runs `assertChartLaws` exactly like `<ChartFrame>` does, so a spark
 *     that mislabels its window or draws an unlabelled series still dev-throws;
 *   · zero and unmeasured stay different marks (C-1/C-2) — a zero bar is the
 *     hairline tick, an unmeasured one is a neutral dash, never an empty gap
 *     that reads as "small";
 *   · it refuses to draw a `line` from fewer than three measured points, the
 *     same refusal `<TrendLine>` makes, because two points are a segment and
 *     not a trend.
 *
 * WHY IT HAS NO VISIBLE WINDOW LABEL OF ITS OWN. C-3 says the window is part of
 * the chart, and it still is: `windowLabel` is REQUIRED here, it is asserted,
 * and it is what the mark's accessible name is built from. The visible copy of
 * that same string is rendered by the tile (`<ExecTile basis=…>` passes ONE
 * string to both), so a 44px-tall mark inside a stat tile does not print its
 * window twice. `executive-summary.test.tsx` pins that the visible basis text
 * and the spark's accessible name agree.
 */
import { useId } from "react";

import { barLength, formatNumber, markKind, NOT_MEASURED } from "./geometry";
import { assertChartLaws } from "./laws";
import { useChartMotion } from "./motion";
import { CHART_PALETTE, HAIRLINE, HAIRLINE_STRONG, STATE, TRACK } from "./tokens";
import type { ChartDatum, ScaleDeclaration } from "./types";

export type SparkKind = "bars" | "line" | "bullet";

export interface SparkTarget {
  value: number;
  /** C-5 — the tick's meaning in words, never colour alone. */
  label: string;
}

export interface SparkProps {
  /** What the mark shows. Part of its accessible name. */
  title: string;
  /** C-3 — REQUIRED, asserted, and surfaced in the accessible name. The tile
   *  renders the same string visibly. */
  windowLabel: string;
  kind: SparkKind;
  data: readonly ChartDatum[];
  /** C-2 — REQUIRED when the series mixes a real 0 with a null. */
  nullMeaning?: string;
  /** `bullet` only. Drawn as a labelled tick, never as a coloured threshold
   *  a reader has to infer. */
  target?: SparkTarget;
  /** `bullet` only — the top of the value axis. Defaults to the larger of the
   *  measure and the target, with headroom so a met target is still legible. */
  axisMax?: number;
  height?: number;
  className?: string;
}

const SERIES = CHART_PALETTE[0]; // c1 chart-gold — the page's one series hue
const LINE = CHART_PALETTE[1]; // c2 chart-sapphire — the overlay against the bars
const MIN_LINE_POINTS = 3;

function measuredValues(data: readonly ChartDatum[]): number[] {
  return data
    .map((d) => d.value)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
}

/** The accessible name. Says how many marks, how many are NOT measured, and the
 *  window — the same three facts `<ChartFrame>` puts in its own aria-label. */
function sparkLabel(
  title: string,
  data: readonly ChartDatum[],
  windowLabel: string,
  target?: SparkTarget,
): string {
  const unmeasured = data.filter((d) => markKind(d.value) === "unmeasured").length;
  const head = `${title} — ${formatNumber(data.length)} value${data.length === 1 ? "" : "s"}`;
  const gap = unmeasured > 0 ? `, ${formatNumber(unmeasured)} not measured` : "";
  const tgt = target ? `. ${target.label}` : "";
  return `${head}${gap}${tgt}. Sample window: ${windowLabel}.`;
}

export function Spark({
  title,
  windowLabel,
  kind,
  data,
  nullMeaning,
  target,
  axisMax,
  height = 34,
  className,
}: SparkProps) {
  const scale: ScaleDeclaration = { kind: "linear" };
  assertChartLaws({ windowLabel, scale, data, nullMeaning });

  const motion = useChartMotion();
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const ariaLabel = sparkLabel(title, data, windowLabel, target);
  const values = measuredValues(data);

  const common = {
    "data-testid": "spark",
    "data-spark-kind": kind,
    "data-window": windowLabel,
    role: "img" as const,
    "aria-label": ariaLabel,
    className: `w-full ${className ?? ""}`.trim(),
  };

  if (kind === "bullet") {
    const measure = data[0];
    const measureValue = typeof measure?.value === "number" ? measure.value : null;
    const top =
      axisMax ??
      Math.max(measureValue ?? 0, target?.value ?? 0, 1) * (measureValue === null ? 1 : 1.15);
    const measurePct = measureValue === null ? 0 : Math.min(100, (measureValue / top) * 100);
    const targetPct = target ? Math.min(100, (target.value / top) * 100) : null;
    const kindOfMeasure = markKind(measureValue);

    return (
      <div {...common} style={{ height }}>
        <div
          className="relative h-2.5 w-full overflow-hidden rounded-full"
          style={{ backgroundColor: TRACK }}
        >
          {kindOfMeasure === "value" ? (
            <div
              data-mark="value"
              className="absolute inset-y-0 left-0 rounded-full"
              style={{
                width: `${measurePct}%`,
                backgroundColor: SERIES,
                transformOrigin: "left",
                transform: motion.atOrigin ? "scaleX(0)" : undefined,
                transition: motion.transition("transform"),
              }}
            />
          ) : null}
          {kindOfMeasure === "zero" ? (
            <div
              data-mark="zero"
              data-tone="neutral"
              className="absolute inset-y-0 left-0"
              style={{ width: "1px", backgroundColor: HAIRLINE }}
              title={`${measure?.label ?? title}: 0`}
            />
          ) : null}
          {kindOfMeasure === "unmeasured" ? (
            <span
              data-mark="unmeasured"
              data-tone="neutral"
              className="absolute left-1 top-1/2 -translate-y-1/2 font-mono text-[10px] leading-none"
              style={{ color: STATE.neutral }}
              title={measure?.note ?? nullMeaning ?? "not measured"}
            >
              {NOT_MEASURED}
            </span>
          ) : null}
        </div>
        {targetPct !== null && target ? (
          <div className="relative mt-1 h-3">
            <span
              data-testid="spark-target"
              className="absolute top-0 block h-1.5 w-px"
              style={{ left: `${targetPct}%`, backgroundColor: STATE.warn }}
              aria-hidden="true"
            />
            {/* C-5: the tick is never colour alone — its meaning is a word,
                positioned under it and clamped inside the tile. */}
            <span
              data-testid="spark-target-label"
              className="absolute top-[7px] whitespace-nowrap font-mono text-[9px] leading-none"
              style={{
                left: `${targetPct}%`,
                transform: targetPct > 70 ? "translateX(-100%)" : undefined,
                color: STATE.warn,
              }}
            >
              {target.label}
            </span>
          </div>
        ) : null}
      </div>
    );
  }

  if (kind === "line") {
    if (values.length < MIN_LINE_POINTS) {
      // The same refusal <TrendLine> makes, at tile scale: no line, and the
      // reason is in the accessible name rather than an invented slope.
      return (
        <div
          {...common}
          data-spark-state="too-few-points"
          className={`${common.className} flex items-center`}
          style={{ height }}
        >
          <span
            className="font-mono text-[10px]"
            style={{ color: STATE.neutral }}
            data-tone="neutral"
          >
            {`${NOT_MEASURED} fewer than ${MIN_LINE_POINTS} measured points`}
          </span>
        </div>
      );
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min > 0 ? max - min : 1;
    const stepX = data.length > 1 ? 100 / (data.length - 1) : 0;
    const pts = data
      .map((d, i) => ({ i, v: d.value }))
      .filter((p): p is { i: number; v: number } => typeof p.v === "number");
    const path = pts
      .map((p, i) => `${i === 0 ? "M" : "L"}${(p.i * stepX).toFixed(2)},${(
        100 -
        ((p.v - min) / span) * 100
      ).toFixed(2)}`)
      .join(" ");
    const last = pts[pts.length - 1];
    const gradientId = `spark-fill-${uid}`;

    return (
      <svg
        {...common}
        viewBox="0 0 100 100"
        height={height}
        preserveAspectRatio="none"
        style={{ height }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={LINE} stopOpacity={0.3} />
            <stop offset="100%" stopColor={LINE} stopOpacity={0} />
          </linearGradient>
        </defs>
        <path
          data-testid="spark-area"
          d={`${path} L100,100 L0,100 Z`}
          fill={`url(#${gradientId})`}
          stroke="none"
          vectorEffect="non-scaling-stroke"
        />
        <path
          data-testid="spark-path"
          d={path}
          fill="none"
          stroke={LINE}
          strokeWidth={2}
          vectorEffect="non-scaling-stroke"
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength={1}
          style={
            motion.atOrigin || motion.transition("stroke-dashoffset")
              ? {
                  strokeDasharray: 1,
                  strokeDashoffset: motion.atOrigin ? 1 : 0,
                  transition: motion.transition("stroke-dashoffset"),
                }
              : undefined
          }
        />
        <circle
          data-marker="last"
          cx={(last.i * stepX).toFixed(2)}
          cy={(100 - ((last.v - min) / span) * 100).toFixed(2)}
          r={2.5}
          fill={LINE}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    );
  }

  // kind === "bars"
  const max = values.length ? Math.max(...values) : 0;
  return (
    <div {...common} className={`${common.className} flex items-end gap-[3px]`} style={{ height }}>
      {data.map((datum, index) => {
        const { kind: markType, length } = barLength({
          value: datum.value,
          max,
          extent: height,
          mode: "linear",
        });
        const title_ =
          markType === "unmeasured"
            ? `${datum.label}: not measured — ${datum.note ?? nullMeaning ?? "reason not provided"}`
            : `${datum.label}: ${datum.display ?? formatNumber(datum.value as number)}`;
        return (
          <span
            key={`${datum.label}-${index}`}
            data-testid="spark-bar"
            data-mark={markType}
            data-tone={markType === "value" ? "series" : "neutral"}
            title={title_}
            className="min-w-0 flex-1 rounded-[1px]"
            style={{
              height: markType === "unmeasured" ? 1 : Math.max(1, length),
              backgroundColor:
                markType === "value"
                  ? SERIES
                  : markType === "zero"
                    ? HAIRLINE
                    : HAIRLINE_STRONG,
              // An unmeasured column is a dotted stub, never a short solid bar
              // that reads as a small measured value.
              borderTop:
                markType === "unmeasured" ? `1px dotted ${STATE.neutral}` : undefined,
              transformOrigin: "bottom",
              transform: motion.atOrigin ? "scaleY(0)" : undefined,
              transition: motion.transition("transform", motion.stagger(index, 24, 10)),
            }}
          />
        );
      })}
    </div>
  );
}
