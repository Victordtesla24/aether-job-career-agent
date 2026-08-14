/**
 * Chart-kit design tokens — S-UI-SPEC.md §2.1 (surface ladder + state colours)
 * and §2.2 (chart palette).
 *
 * These are literal values on purpose. The S-UI slice that extends
 * `tailwind.config.ts` with `surface-*` / `state-*` / `chart-heat-*` has not
 * landed yet, and this slice is bound to create NEW self-contained files only
 * (S-UI-BINDING-CONSTRAINTS §"zero regression"). Every value below matches the
 * spec byte-for-byte, so the later Tailwind slice is a rename, not a redesign.
 */

/** Ordered categorical palette — colour-blind safe on #0A0A0F. Use in
 *  sequence, never skip (S-UI-SPEC §2.2). */
export const CHART_PALETTE = [
  "#FF6B35", // c1 coral
  "#818CF8", // c2 indigo-300
  "#34D399", // c3 green
  "#F59E0B", // c4 amber
  "#A78BFA", // c5 violet-300
  "#22D3EE", // c6 cyan-300
  "#FB7185", // c7 rose-300
  "#A3E635", // c8 lime-300
] as const;

/** Sequential coral ramp (`--chart-heat-1..5`) for heatmaps and histograms. */
export const CHART_HEAT = [
  "rgba(255,107,53,0.10)",
  "rgba(255,107,53,0.25)",
  "rgba(255,107,53,0.42)",
  "rgba(255,107,53,0.62)",
  "rgba(255,107,53,0.85)",
] as const;

/** Diverging ramp for market-vs-you deltas. */
export const DIVERGING = {
  negative: "#F87171",
  neutral: "#8B8BA3",
  positive: "#34D399",
} as const;

/** Semantic state colours. `neutral` is the ONLY tone permitted for
 *  "no data / not measured" — never green, never red (Rule D-1). */
export const STATE = {
  ok: "#34D399",
  warn: "#F59E0B",
  danger: "#F87171",
  info: "#818CF8",
  neutral: "#8B8BA3",
  degraded: "#C4B5FD",
} as const;

/** Surface ladder. `s0` is the page ground; charts never paint it. */
export const SURFACE = {
  s0: "#0A0A0F",
  s1: "#101018",
  s2: "#16161F",
  s3: "#1C1C27",
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
export const EASE = "cubic-bezier(0.2, 0, 0, 1)";

/** Above this many points an SVG path stops being the right tool and the
 *  kit switches to canvas (S-UI-REBUILD-SPEC §4.1). It is the ONLY case in
 *  the kit where canvas is authorised. */
export const CANVAS_POINT_THRESHOLD = 2000;
