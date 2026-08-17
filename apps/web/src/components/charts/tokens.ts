/**
 * Chart-kit design tokens — the validated obsidian-and-gilt palette
 * (UI-BRAND run, RULINGS.md R-VIZ; DS ground truth
 * `design/aether-design-system/tokens/colors.css`).
 *
 * R-VIZ was validated with the dataviz-skill colour validator in dark mode
 * against BOTH the page ground #08080A and the card ground #0F0F12, including
 * adjacent-pair separation: ALL PASS. These are literal values on purpose —
 * the chart kit is self-contained, so the later Tailwind slice that lifts
 * `surface-*` / `state-*` / `chart-heat-*` into the theme is a rename, not a
 * redesign. Geometry rules still follow S-UI-SPEC §2.1/§2.2.
 */

export const CHART_PALETTE = [
  "#AE8E32", // c1 chart-gold — brand gold snapped into the OKLCH chart L band
  "#4F74B5", // c2 chart-sapphire (hue 261)
  "#C16F7B", // c3 chart-rose (burgundy-light, hue 11)
  "#439FC8", // c4 chart-sky (light sapphire step)
] as const;

/** Overflow / "Other" bucket. A chart that needs more than four hues shows
 *  top-4 + Other — never a fifth hue (R-VIZ). Same tone as `STATE.neutral`. */
export const CHART_OTHER = "#8C8A82";

/** Sequential gilt alpha ramp (`--chart-heat-1..5`) for heatmaps and
 *  histograms — one measure, so an alpha ramp, not a hue ramp (R-VIZ). */
export const CHART_HEAT = [
  "rgba(201,168,76,0.10)",
  "rgba(201,168,76,0.25)",
  "rgba(201,168,76,0.42)",
  "rgba(201,168,76,0.62)",
  "rgba(201,168,76,0.85)",
] as const;

/** Diverging ramp for market-vs-you deltas. */
export const DIVERGING = {
  negative: "#B9544B",
  neutral: "#8C8A82",
  positive: "#6FAF8D",
} as const;

/** Semantic state colours. `neutral` is the ONLY tone permitted for
 *  "no data / not measured" — never green, never red (Rule D-1). */
export const STATE = {
  ok: "#6FAF8D",
  warn: "#C8873A",
  danger: "#B9544B",
  info: "#7C93BE",
  neutral: "#8C8A82",
  degraded: "#A08CB4",
} as const;

/** Surface ladder — the DS ink ladder. `s0` is the page ground; charts never
 *  paint it. `s1` is the card ground point-halos and donut gaps cut back to. */
export const SURFACE = {
  s0: "#08080A",
  s1: "#0F0F12",
  s2: "#16161A",
  s3: "#1E1E23",
} as const;

/** 1px borders / ticks. A zero mark is drawn in HAIRLINE, never in a series
 *  colour (C-1). */
export const HAIRLINE = "rgba(255,255,255,0.07)";
export const HAIRLINE_STRONG = "rgba(255,255,255,0.13)";

/** Gridlines sit behind the marks, horizontal only, never vertical. */
export const GRIDLINE = "rgba(255,255,255,0.06)";

/** Track behind a bar (S-UI-SPEC §3.3). */
export const TRACK = "rgba(255,255,255,0.04)";

/** Axis + meta type. Numerals are `font-mono tabular-nums` everywhere
 *  (Rule D-6); footnotes are 11px at full muted-dim (Rule D-7). */
export const AXIS_TEXT_CLASS = "font-mono tabular-nums text-[10px]";
export const META_TEXT_CLASS = "text-[11px] text-aether-muted-dim";
export const METRIC_TEXT_CLASS = "font-mono tabular-nums";

/** Motion durations (S-UI-SPEC §2.7 / REBUILD §2.2). */
export const DUR_FAST = 120;
export const DUR = 180;
export const DUR_SLOW = 260;
export const DUR_REVEAL = 500;
export const EASE = "cubic-bezier(0.25, 1, 0.5, 1)";

/** Above this many points an SVG path stops being the right tool and the
 *  kit switches to canvas (S-UI-REBUILD-SPEC §4.1). It is the ONLY case in
 *  the kit where canvas is authorised. */
export const CANVAS_POINT_THRESHOLD = 2000;
