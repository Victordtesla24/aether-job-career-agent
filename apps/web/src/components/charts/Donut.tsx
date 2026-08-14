"use client";

/**
 * `<Donut>` — S-UI-REBUILD-SPEC §4.3 row 5 (source mix).
 *
 * A share with no denominator is not a fact, so every legend row carries the
 * ABSOLUTE count next to its percentage, and the centre holds the total the
 * percentages were taken against. Slivers under 2% group into "Other" — with
 * the members named in its tooltip and still listed one by one in the data
 * table, because grouping is a layout decision and must never become a
 * disclosure decision.
 *
 * C-1: a source with zero jobs gets no arc, and its 0 is state-neutral.
 * C-2: a source that was never measured gets "—", never a 0, and never an arc;
 *      percentages are taken against the MEASURED total only.
 */
import { useId } from "react";

import { ChartFrame } from "./ChartFrame";
import { NOT_MEASURED, formatNumber, formatPercent } from "./geometry";
import { useChartMotion } from "./motion";
import { EmptyPlot } from "./primitives";
import { CHART_PALETTE, STATE, SURFACE } from "./tokens";
import type { ChartDatum } from "./types";

export interface DonutSegment {
  label: string;
  /** `null` = never measured (connector off, source not configured). */
  value: number | null;
  note?: string;
}

export interface DonutProps {
  title: string;
  /** C-3 — required. */
  windowLabel: string;
  segments: readonly DonutSegment[];
  /** Word under the centre total ("jobs", "applications"). */
  centreLabel?: string;
  /** Shares below this percentage group into "Other". */
  groupBelowPercent?: number;
  /** C-2 — required when the segments mix a real 0 with a null. */
  nullMeaning?: string;
  footnote?: string;
  className?: string;
}

const RADIUS = 42;
const STROKE_WIDTH = 14;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
/** 1px visual gap between adjacent arcs, expressed in path length. */
const GAP = 1.5;

interface RenderedArc {
  label: string;
  value: number;
  colour: string;
  members?: readonly DonutSegment[];
}

export function Donut({
  title,
  windowLabel,
  segments,
  centreLabel = "total",
  groupBelowPercent = 2,
  nullMeaning,
  footnote,
  className,
}: DonutProps) {
  const motion = useChartMotion();
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const data: ChartDatum[] = segments.map((s) => ({
    label: s.label,
    value: s.value,
    note: s.note,
  }));

  const measured = segments.filter(
    (s): s is DonutSegment & { value: number } => typeof s.value === "number",
  );
  const total = measured.reduce((sum, s) => sum + s.value, 0);
  const positives = measured.filter((s) => s.value > 0);
  const small = positives.filter((s) => (s.value / (total || 1)) * 100 < groupBelowPercent);
  const large = positives.filter((s) => (s.value / (total || 1)) * 100 >= groupBelowPercent);

  const arcs: RenderedArc[] = large.map((segment, index) => ({
    label: segment.label,
    value: segment.value,
    colour: CHART_PALETTE[index % CHART_PALETTE.length],
  }));
  if (small.length > 0) {
    arcs.push({
      label: "Other",
      value: small.reduce((sum, s) => sum + s.value, 0),
      colour: CHART_PALETTE[(large.length + 1) % CHART_PALETTE.length],
      members: small,
    });
  }

  let offset = 0;

  return (
    <ChartFrame
      title={title}
      windowLabel={windowLabel}
      scale={{ kind: "linear" }}
      data={data}
      nullMeaning={nullMeaning}
      footnote={footnote}
      className={className}
      legend={
        segments.length > 0 ? (
          <ul className="flex flex-col gap-1">
            {segments.map((segment) => {
              const grouped = small.some((s) => s.label === segment.label);
              const colour = arcs.find((a) => a.label === segment.label)?.colour;
              const unmeasured = typeof segment.value !== "number";
              const zero = segment.value === 0;
              return (
                <li
                  key={segment.label}
                  data-testid="legend-row"
                  data-segment={segment.label}
                  title={
                    unmeasured
                      ? `not measured — ${segment.note ?? nullMeaning ?? "reason not provided"}`
                      : grouped
                        ? `grouped into Other (below ${groupBelowPercent}%)`
                        : undefined
                  }
                  className="flex items-center gap-2 text-[12px]"
                >
                  <span
                    data-testid="legend-swatch"
                    aria-hidden="true"
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{
                      backgroundColor: unmeasured || zero ? "transparent" : (colour ?? STATE.neutral),
                      border: unmeasured || zero ? `1px solid ${STATE.neutral}` : undefined,
                    }}
                  />
                  <span className="flex-1 truncate text-aether-muted">{segment.label}</span>
                  <span
                    data-testid="legend-value"
                    data-mark={unmeasured ? "unmeasured" : zero ? "zero" : "value"}
                    data-tone={unmeasured || zero ? "neutral" : "series"}
                    className="w-16 text-right font-mono text-[12px] tabular-nums"
                    style={{ color: unmeasured || zero ? STATE.neutral : undefined }}
                  >
                    {typeof segment.value === "number"
                      ? formatNumber(segment.value)
                      : NOT_MEASURED}
                  </span>
                  <span
                    className="w-16 text-right font-mono text-[11px] tabular-nums"
                    style={{ color: STATE.neutral }}
                  >
                    {typeof segment.value === "number"
                      ? formatPercent(segment.value, total > 0 ? total : null)
                      : NOT_MEASURED}
                  </span>
                </li>
              );
            })}
            {small.length > 0 ? (
              <li
                data-testid="legend-row"
                data-segment="Other"
                title={`Other = ${small.map((s) => s.label).join(", ")}`}
                className="flex items-center gap-2 text-[12px]"
              >
                <span
                  data-testid="legend-swatch"
                  aria-hidden="true"
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: arcs[arcs.length - 1]?.colour }}
                />
                <span className="flex-1 truncate text-aether-muted">
                  {`Other (${small.length} ${small.length === 1 ? "source" : "sources"} below ${groupBelowPercent}%)`}
                </span>
                <span className="w-16 text-right font-mono text-[12px] tabular-nums">
                  {formatNumber(arcs[arcs.length - 1]?.value ?? 0)}
                </span>
                <span
                  className="w-16 text-right font-mono text-[11px] tabular-nums"
                  style={{ color: STATE.neutral }}
                >
                  {formatPercent(arcs[arcs.length - 1]?.value ?? 0, total > 0 ? total : null)}
                </span>
              </li>
            ) : null}
          </ul>
        ) : undefined
      }
    >
      {segments.length === 0 || arcs.length === 0 ? (
        <EmptyPlot
          message="No sources have returned a job yet."
          hint="Connect a source or run discovery to populate this mix."
        />
      ) : (
        <div className="relative mx-auto" style={{ width: 200, height: 200 }} data-chart="donut">
          <svg viewBox="0 0 100 100" width="100%" height="100%" aria-hidden="true">
            <circle
              cx={50}
              cy={50}
              r={RADIUS}
              fill="none"
              stroke={SURFACE.s2}
              strokeWidth={STROKE_WIDTH}
            />
            {arcs.map((arc) => {
              const length = total > 0 ? (arc.value / total) * CIRCUMFERENCE : 0;
              const visible = Math.max(0, length - GAP);
              const dashOffset = -offset;
              offset += length;
              return (
                <circle
                  key={`${uid}-${arc.label}`}
                  data-arc=""
                  data-segment-name={arc.label}
                  cx={50}
                  cy={50}
                  r={RADIUS}
                  fill="none"
                  stroke={arc.colour}
                  strokeWidth={STROKE_WIDTH}
                  strokeDasharray={`${visible} ${CIRCUMFERENCE - visible}`}
                  strokeDashoffset={motion.atOrigin ? dashOffset - visible : dashOffset}
                  transform="rotate(-90 50 50)"
                  style={{ transition: motion.transition("stroke-dashoffset") }}
                >
                  <title>
                    {arc.members
                      ? `Other (${arc.members.map((m) => m.label).join(", ")}): ${formatNumber(
                          arc.value,
                        )}`
                      : `${arc.label}: ${formatNumber(arc.value)}`}
                  </title>
                </circle>
              );
            })}
          </svg>
          <div
            data-testid="donut-centre"
            className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center"
          >
            <span className="font-mono text-[22px] font-bold tabular-nums text-aether-text">
              {formatNumber(total)}
            </span>
            <span className="text-[11px]" style={{ color: STATE.neutral }}>
              {centreLabel}
            </span>
          </div>
        </div>
      )}
    </ChartFrame>
  );
}
