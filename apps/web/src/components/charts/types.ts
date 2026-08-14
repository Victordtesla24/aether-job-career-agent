/**
 * Shared chart-kit types. Kept in their own module so `laws.ts`,
 * `geometry.ts` and the components can all depend on them without a cycle.
 */

/** How a single value is allowed to be drawn. `zero` and `unmeasured` are
 *  DIFFERENT things and the kit never lets them share a rendering (C-1/C-2). */
export type MarkKind = "value" | "zero" | "unmeasured";

/**
 * One datum, as the chart's hidden data table and the law assertions see it.
 * `value: null` means NOT MEASURED — it never means zero.
 */
export interface ChartDatum {
  /** The word that carries the meaning. Colour is only ever redundant
   *  reinforcement of this (C-5), so it may not be blank. */
  label: string;
  /** A real measurement, `0` for a real zero, or `null` for not measured. */
  value: number | null;
  /** Why this datum is not measured, or any per-datum qualifier. Rendered
   *  verbatim — the kit never rewrites a caller's honesty string. */
  note?: string;
  /** Pre-formatted display string (currency, units, "+A$12,000"). When
   *  omitted the kit formats the number itself. */
  display?: string;
}

/**
 * C-4: a chart states the scale it is drawn on. There is no "figure it out
 * from the picture" — a reader must be told.
 */
export interface ScaleDeclaration {
  kind: "linear" | "log" | "share-of-previous";
  /** Where the value axis starts. Anything other than 0 is a truncated axis
   *  and must set `truncated`. */
  baseline?: number;
  /** Declares an axis that does not start at zero. */
  truncated?: boolean;
}

export interface PlotInsets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/** Geometry handed to the render-prop children of `<ChartFrame>`. */
export interface PlotGeometry {
  /** viewBox width (responsive: tracks the container when a ResizeObserver
   *  is available, otherwise the deterministic default). */
  width: number;
  /** viewBox height. */
  height: number;
  padding: PlotInsets;
  /** The drawable rectangle inside the padding. */
  plot: { x: number; y: number; width: number; height: number };
}
