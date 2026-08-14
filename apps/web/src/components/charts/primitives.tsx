"use client";

/**
 * Shared marks. Reference-pack rule 5: "charts have no border, no background,
 * no legend clutter — the gridlines and axis labels do all the framing".
 * Everything in this file is therefore either a gridline, an axis label, or a
 * mark that carries data.
 */
import type { ReactNode } from "react";

import { GRIDLINE, HAIRLINE, STATE, AXIS_TEXT_CLASS } from "./tokens";
import type { PlotGeometry } from "./types";

/** Horizontal gridlines only — never vertical (S-UI-SPEC §2.2). */
export function Gridlines({
  geom,
  ticks,
  max,
  min = 0,
}: {
  geom: PlotGeometry;
  ticks: readonly number[];
  max: number;
  /** Non-zero only on a chart that has DECLARED a truncated axis (C-4). */
  min?: number;
}) {
  const { plot } = geom;
  const span = max - min > 0 ? max - min : 1;
  return (
    <g aria-hidden="true">
      {ticks.map((tick) => {
        const y = plot.y + plot.height - ((tick - min) / span) * plot.height;
        return (
          <line
            key={`grid-${tick}`}
            data-testid="gridline"
            x1={plot.x}
            x2={plot.x + plot.width}
            y1={y}
            y2={y}
            stroke={GRIDLINE}
            strokeWidth={1}
          />
        );
      })}
    </g>
  );
}

/** Small grey mono axis label. Numerals are tabular so columns align. */
export function AxisLabel({
  x,
  y,
  children,
  anchor = "end",
  testId = "axis-label",
  fill = STATE.neutral,
}: {
  x: number;
  y: number;
  children: ReactNode;
  anchor?: "start" | "middle" | "end";
  testId?: string;
  fill?: string;
}) {
  return (
    <text
      data-testid={testId}
      x={x}
      y={y}
      textAnchor={anchor}
      dominantBaseline="middle"
      className={AXIS_TEXT_CLASS}
      fill={fill}
    >
      {children}
    </text>
  );
}

/** C-1 in SVG form: a zero is a 1px hairline tick sitting on the baseline. */
export function ZeroTickRect({
  x,
  baselineY,
  width,
}: {
  x: number;
  baselineY: number;
  width: number;
}) {
  return (
    <rect
      data-mark="zero"
      x={x}
      y={baselineY - 1}
      width={width}
      height={1}
      fill={HAIRLINE}
    />
  );
}

/** C-2 in SVG form: an em dash in state-neutral where a mark would have been. */
export function UnmeasuredMark({
  x,
  y,
  title,
  hitWidth = 24,
  hitHeight = 20,
}: {
  x: number;
  y: number;
  title?: string;
  hitWidth?: number;
  hitHeight?: number;
}) {
  return (
    <g>
      <text
        data-mark="unmeasured"
        data-tone="neutral"
        x={x}
        y={y}
        textAnchor="middle"
        dominantBaseline="middle"
        className={AXIS_TEXT_CLASS}
        fill={STATE.neutral}
      >
        —
      </text>
      {/* The dash is a 6px glyph; the hover target must not be. The reason
          lives on this transparent rect so the mark's own text stays exactly
          "—" — the one thing a reader is meant to see. */}
      {title ? (
        <rect
          x={x - hitWidth / 2}
          y={y - hitHeight / 2}
          width={hitWidth}
          height={hitHeight}
          fill="transparent"
        >
          <title>{title}</title>
        </rect>
      ) : null}
    </g>
  );
}

/** 1px dashed reference line with a right-edge label. */
export function ThresholdLine({
  geom,
  value,
  max,
  label,
}: {
  geom: PlotGeometry;
  value: number;
  max: number;
  label: string;
}) {
  const { plot } = geom;
  const y = plot.y + plot.height - (value / (max > 0 ? max : 1)) * plot.height;
  return (
    <g data-testid="threshold-line">
      <line
        x1={plot.x}
        x2={plot.x + plot.width}
        y1={y}
        y2={y}
        stroke={STATE.warn}
        strokeWidth={1}
        strokeDasharray="3 3"
      />
      <AxisLabel x={plot.x + plot.width} y={y - 7} fill={STATE.warn} testId="threshold-label">
        {label}
      </AxisLabel>
    </g>
  );
}

/**
 * Doctrine D-θ: the empty state is DESIGNED. Never a bare "No data" — one line
 * of what this is, one line of what to do about it.
 */
export function EmptyPlot({
  message,
  hint,
  action,
}: {
  message: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div
      data-testid="chart-empty"
      className="flex min-h-[120px] flex-col items-center justify-center gap-1 px-4 py-8 text-center"
    >
      <div
        aria-hidden="true"
        className="mb-1 h-px w-16"
        style={{ backgroundColor: HAIRLINE }}
      />
      <p
        data-prose="empty"
        className="text-[13px] leading-[1.5]"
        style={{ color: STATE.neutral }}
      >
        {message}
      </p>
      {hint ? (
        <p
          data-prose="empty"
          className="text-[11px] text-aether-muted-dim"
          style={{ color: STATE.neutral }}
        >
          {hint}
        </p>
      ) : null}
      {action}
    </div>
  );
}
