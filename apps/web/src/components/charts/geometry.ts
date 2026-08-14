/**
 * Chart geometry — the pure maths behind every primitive, and the single
 * place where C-1 ("zero is not a colour") is decided. Every bar-shaped chart
 * in the kit routes its lengths through `barLength`, so a zero can never
 * acquire a proportional filled length by accident in one chart while behaving
 * in another.
 */
import type { MarkKind, PlotGeometry, PlotInsets } from "./types";

/** A zero draws a 1px tick at the origin — never a filled coloured mark. */
export const ZERO_TICK_WIDTH = 1;

/** Deterministic viewBox width used on the server and before the first
 *  ResizeObserver measurement. */
export const DEFAULT_PLOT_WIDTH = 640;

export const DEFAULT_PADDING: PlotInsets = { top: 12, right: 16, bottom: 26, left: 40 };

/** The decision that keeps 0 and null apart everywhere. */
export function markKind(value: number | null | undefined): MarkKind {
  if (value === null || value === undefined || Number.isNaN(value)) return "unmeasured";
  return value === 0 ? "zero" : "value";
}

export interface BarLengthInput {
  value: number | null | undefined;
  /** Largest value in the series (for linear/log). */
  max: number;
  /** Pixels (or percent) available for a full-scale bar. */
  extent: number;
  mode: "linear" | "log" | "share-of-previous";
  /** Previous step's value — required by share-of-previous. */
  previous?: number | null;
}

export interface BarLength {
  kind: MarkKind;
  length: number;
}

/**
 * Length of one bar, plus what kind of mark it is.
 *  - unmeasured → length 0 (the caller draws "—", not a bar)
 *  - zero       → exactly ZERO_TICK_WIDTH, in hairline, never a series colour
 *  - value      → strictly greater than ZERO_TICK_WIDTH, so a 1px mark can
 *                 only ever mean zero
 */
export function barLength({ value, max, extent, mode, previous }: BarLengthInput): BarLength {
  const kind = markKind(value);
  if (kind !== "value") {
    return { kind, length: kind === "zero" ? ZERO_TICK_WIDTH : 0 };
  }
  const v = value as number;
  let fraction: number;
  if (mode === "share-of-previous") {
    const base = previous ?? null;
    fraction = base === null || base <= 0 ? 1 : Math.min(1, v / base);
  } else if (mode === "log") {
    const safeMax = Math.max(max, 1);
    fraction = Math.log10(Math.abs(v) + 1) / Math.log10(safeMax + 1);
  } else {
    const safeMax = max > 0 ? max : Math.abs(v);
    fraction = safeMax > 0 ? Math.abs(v) / safeMax : 0;
  }
  const length = Math.max(ZERO_TICK_WIDTH + 0.5, fraction * extent);
  return { kind: "value", length };
}

/** Round, human axis ticks from 0 to max, always including both ends. */
export function niceTicks(max: number, count = 4): number[] {
  if (!Number.isFinite(max) || max <= 0) return [0];
  const step = max / count;
  const ticks: number[] = [];
  for (let i = 0; i <= count; i += 1) {
    ticks.push(Math.round(step * i * 100) / 100);
  }
  return ticks;
}

/**
 * 0 = a measured zero (drawn as an empty cell, NOT the coldest heat colour),
 * 1..5 = the five coral ramp steps. `null` never reaches this function — an
 * unmeasured cell has no heat step at all (C-2).
 */
export function heatStep(value: number, max: number): 0 | 1 | 2 | 3 | 4 | 5 {
  if (value <= 0) return 0;
  if (max <= 0) return 1;
  const ratio = Math.min(1, value / max);
  const step = Math.ceil(ratio * 5);
  return Math.min(5, Math.max(1, step)) as 1 | 2 | 3 | 4 | 5;
}

/** Point on a radar spoke. Spoke 0 points straight up; spokes run clockwise. */
export function polarPoint(
  cx: number,
  cy: number,
  radius: number,
  index: number,
  count: number,
): { x: number; y: number } {
  const angle = (index / Math.max(1, count)) * Math.PI * 2 - Math.PI / 2;
  return { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius };
}

/** Frame geometry for a given viewBox size. */
export function plotGeometry(
  width: number,
  height: number,
  padding: Partial<PlotInsets> = {},
): PlotGeometry {
  const pad = { ...DEFAULT_PADDING, ...padding };
  return {
    width,
    height,
    padding: pad,
    plot: {
      x: pad.left,
      y: pad.top,
      width: Math.max(0, width - pad.left - pad.right),
      height: Math.max(0, height - pad.top - pad.bottom),
    },
  };
}

/** Locale-stable number formatting (en-AU, matching MarketPulse) so SSR and
 *  the browser never disagree. */
export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-AU").format(value);
}

/** The em dash the whole kit uses for "not measured". Never "0", never "N/A". */
export const NOT_MEASURED = "—";

/** One decimal percentage, or NOT_MEASURED when the denominator cannot
 *  support a percentage at all. */
export function formatPercent(numerator: number | null, denominator: number | null): string {
  if (numerator === null || denominator === null || denominator <= 0) return NOT_MEASURED;
  return `${((numerator / denominator) * 100).toFixed(1)}%`;
}
