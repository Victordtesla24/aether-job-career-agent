/**
 * The Aether chart kit — hand-built SVG/DOM primitives, no charting library
 * (S-UI-REBUILD-SPEC §4.1). Import from here, not from the individual files.
 *
 * Every chart enforces the five honest-rendering laws through `<ChartFrame>`;
 * see `README.md` in this folder for each law and the test that pins it.
 */
export { ChartFrame, type ChartFrameProps } from "./ChartFrame";
export { Funnel, FunnelBars, type FunnelProps, type FunnelStep } from "./Funnel";
export { TrendLine, type TrendLineProps, type TrendPoint } from "./TrendLine";
export { Histogram, type HistogramBucket, type HistogramProps } from "./Histogram";
export { Radar10, RadarPlot, type Radar10Props, type RadarDimension } from "./Radar10";
export { Donut, type DonutProps, type DonutSegment } from "./Donut";
export { DivergingBar, type DivergingBarProps, type DivergingRow } from "./DivergingBar";
export { Heatmap, type HeatmapCell, type HeatmapProps, type HeatmapRow } from "./Heatmap";
export {
  BulletChart,
  type BulletChartProps,
  type BulletCoverageSegment,
  type BulletRow,
} from "./BulletChart";
export { Spark, type SparkKind, type SparkProps, type SparkTarget } from "./Spark";
export { TierBand, type TierBandPoint, type TierBandProps } from "./TierBand";

export { AxisLabel, EmptyPlot, Gridlines, ThresholdLine, UnmeasuredMark, ZeroTickRect } from "./primitives";
export {
  ChartLawError,
  assertChartLaws,
  assertColourRedundancy,
  assertNullMeaning,
  assertScaleDeclared,
  assertWindowLabel,
  type ChartLaw,
} from "./laws";
export {
  DEFAULT_PLOT_WIDTH,
  MIN_VALUE_LENGTH,
  NOT_MEASURED,
  ZERO_TICK_WIDTH,
  barLength,
  barPercent,
  formatNumber,
  formatPercent,
  heatStep,
  markKind,
  niceTicks,
  plotGeometry,
  polarPoint,
} from "./geometry";
export { useChartMotion, prefersReducedMotion, type MotionPhase } from "./motion";
export {
  AXIS_TEXT_CLASS,
  CANVAS_POINT_THRESHOLD,
  CHART_HEAT,
  CHART_PALETTE,
  DIVERGING,
  GRIDLINE,
  HAIRLINE,
  HAIRLINE_STRONG,
  META_TEXT_CLASS,
  STATE,
  SURFACE,
  TRACK,
} from "./tokens";
export type {
  ChartDatum,
  MarkKind,
  PlotGeometry,
  PlotInsets,
  ScaleDeclaration,
} from "./types";
