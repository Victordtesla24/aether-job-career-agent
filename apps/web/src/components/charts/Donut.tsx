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
 * C-1: a source with zero jobs gets no arc, and its 0 is state-neutral. The
 *      inverse holds too: `arcs` only ever holds segments whose value is > 0
 *      (see `positives`/`small`/`large` below — a genuine `value === 0` is
 *      filtered out before this point and never reaches the ring), so every
 *      arc this component draws, including a grouped "Other" whose total is
 *      a fraction of a percent, must render with strictly nonzero visible
 *      length — see `MIN_ARC_LENGTH`. A real, disclosed, nonzero value must
 *      never collapse to the same "nothing on the ring" rendering as a
 *      genuine zero.
 * C-2: a source that was never measured gets "—", never a 0, and never an arc;
 *      percentages are taken against the MEASURED total only.
 */
import { useId } from "react";

import { ChartFrame } from "./ChartFrame";
import { NOT_MEASURED, formatNumber, formatPercent } from "./geometry";
import { useChartMotion } from "./motion";
import { EmptyPlot } from "./primitives";
import { CHART_OTHER, CHART_PALETTE, STATE, SURFACE } from "./tokens";
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
export const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
/** 1px visual gap between adjacent arcs, expressed in path length. */
export const GAP = 1.5;
/**
 * The shortest a REAL arc may ever render, after `GAP` is subtracted —
 * analogous to `geometry.ts`'s `MIN_VALUE_LENGTH` for the bar-shaped charts,
 * but local to `<Donut>` because the arc encoding (angle/path-length, with
 * its own inter-segment `GAP`) has no shared unit with `barLength()`'s
 * extent-based lengths. Every arc reaching the render loop below represents
 * a real, disclosed, nonzero value — a genuine zero is filtered out long
 * before `arcs` is built — so `visible` must never legitimately be 0 there.
 * Without this floor, a "Other" group whose combined share is small enough
 * (e.g. ~0.3%) computes a raw length below `GAP` and `Math.max(0, length -
 * GAP)` collapses to exactly 0: the ring renders zero visible pixels for
 * that arc, identical to a genuine absence. Set to `GAP + 0.5` so the floor
 * stays strictly above the gap it follows regardless of how `GAP` is tuned.
 */
export const MIN_ARC_LENGTH = GAP + 0.5;

interface RenderedArc {
  label: string;
  value: number;
  colour: string;
  members?: readonly DonutSegment[];
}

export interface ArcLayoutResult {
  length: number;
  /** Drawn stroke length. Always `<= length`, by construction — see
   *  `layoutDonutArcs`. */
  visible: number;
  /** Cumulative start position on the ring, matching how `stroke-dashoffset`
   *  measures distance (0 at the rotated origin, increasing clockwise). */
  offset: number;
}

/**
 * Lay out every arc's slice of the ring, floor included, WITHOUT ever
 * letting a floored arc's drawn (`visible`) length exceed the raw slice
 * (`length`) it was proportionally allotted.
 *
 * Round 2 of this fix floored `visible` in isolation
 * (`Math.max(MIN_ARC_LENGTH, length - GAP)`) and shipped a second defect:
 * for a group whose raw `length` is itself below `MIN_ARC_LENGTH` (share
 * below `(GAP + MIN_ARC_LENGTH) / CIRCUMFERENCE`, ≈1.33% at this file's
 * constants), the floored `visible` came out LARGER than the arc's own raw
 * slice on the ring. Because each arc's start `offset` only ever advances by
 * the raw, unadjusted `length` (never by the floored `visible`), an
 * over-floored arc's drawn stroke ran past the boundary where the next
 * arc's slice begins — for the LAST arc in ring order that means wrapping
 * past 360° back into the FIRST arc's own drawn stroke. Two real, disclosed,
 * nonzero arcs overlapping on the primary visual is strictly worse than the
 * one-real-arc-invisible defect this floor was added to fix.
 *
 * The fix: a floor can buy legibility only with pixels it takes from
 * somewhere real, never for free. When an arc needs flooring, the exact
 * delta (`minSlot - length`) is subtracted from the single LARGEST arc's own
 * `length` — the arc with the most slack to give up without needing a floor
 * itself. That keeps `sum(length)` pinned at exactly `circumference`
 * (nothing borrowed from outside the ring, nothing left over), which in turn
 * guarantees `visible <= length` for every arc — no overlap, no wrap past
 * 360°, by construction rather than by coincidence of the input data.
 *
 * Every `segment.value` handed in must be `> 0` — Donut filters a genuine
 * `value === 0` out of `arcs` long before this function is called (see the
 * component's C-1 docstring); this function has no zero/null case.
 */
export function layoutDonutArcs<T extends { label: string; value: number }>(
  segments: readonly T[],
  circumference: number,
  gap: number,
  minArcLength: number,
): (T & ArcLayoutResult)[] {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  if (segments.length === 0 || total <= 0) return [];

  // The minimum raw slice an arc needs so its floored `visible` never has to
  // borrow: exactly enough for the gap plus the visibility floor.
  const minSlot = gap + minArcLength;
  const rawLengths = segments.map((s) => (s.value / total) * circumference);
  const lengths = [...rawLengths];

  let totalDeficit = 0;
  lengths.forEach((length, index) => {
    if (length < minSlot) {
      totalDeficit += minSlot - length;
      lengths[index] = minSlot;
    }
  });

  if (totalDeficit > 0) {
    let donor = -1;
    let donorRaw = -Infinity;
    rawLengths.forEach((length, index) => {
      // Only an arc that did NOT itself need flooring may lend — otherwise
      // we would be taking pixels from an arc that has none to spare.
      if (length >= minSlot && length > donorRaw) {
        donorRaw = length;
        donor = index;
      }
    });
    if (donor === -1) {
      // No arc is large enough to fund every floor without going below its
      // own — a genuine geometry impossibility for this data + these
      // constants. Fail loudly rather than render an overlapping ring.
      throw new Error(
        `layoutDonutArcs: cannot floor every undersized arc to ${minArcLength} — ` +
          `no arc is large enough to lend the difference without breaching its own floor.`,
      );
    }
    lengths[donor] -= totalDeficit;
    if (lengths[donor] < minSlot) {
      throw new Error(
        `layoutDonutArcs: flooring the undersized arcs would push the donor arc ` +
          `"${segments[donor]?.label}" below its own visibility floor.`,
      );
    }
  }

  // Total-arc-length invariant: the ring can neither gain nor lose length —
  // every pixel a floor adds was taken from the donor, never manufactured.
  const totalLength = lengths.reduce((sum, l) => sum + l, 0);
  if (Math.abs(totalLength - circumference) > 1e-6) {
    throw new Error(
      `layoutDonutArcs: redistributed arc lengths sum to ${totalLength}, not the ring's ` +
        `circumference ${circumference} — the ring would overlap or leave a gap.`,
    );
  }

  let offset = 0;
  return segments.map((segment, index) => {
    const length = lengths[index] as number;
    const visible = Math.max(0, length - gap);
    const laidOut = { ...segment, length, visible, offset };
    offset += length;
    return laidOut;
  });
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

  // R-VIZ: a chart never shows a fifth hue. The palette is walked in fixed
  // order and NEVER cycled — a 5th large slice would otherwise repeat
  // CHART_PALETTE[0] and two differently-labelled arcs would render in the
  // same colour. Anything past the top four folds into "Other" alongside the
  // sub-threshold slivers, and "Other" is always CHART_OTHER — the one
  // reserved overflow tone, not the next palette step.
  const primary = large.slice(0, CHART_PALETTE.length);
  const overflow = large.slice(CHART_PALETTE.length);
  const otherMembers = [...overflow, ...small];

  const arcs: RenderedArc[] = primary.map((segment, index) => ({
    label: segment.label,
    value: segment.value,
    colour: CHART_PALETTE[index],
  }));
  if (otherMembers.length > 0) {
    arcs.push({
      label: "Other",
      value: otherMembers.reduce((sum, s) => sum + s.value, 0),
      colour: CHART_OTHER,
      members: otherMembers,
    });
  }

  const laidOutArcs = layoutDonutArcs(arcs, CIRCUMFERENCE, GAP, MIN_ARC_LENGTH);

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
              const grouped = otherMembers.some((s) => s.label === segment.label);
              // A grouped source is still MEASURED, so it wears the colour of
              // the arc it was folded into — CHART_OTHER, the overflow tone
              // R-VIZ reserves for the "Other" bucket. Rule D-1's "neutral is
              // never a measured value" is honoured by the MARK, not the hue:
              // a grouped source keeps its real count and its own legend row,
              // while a genuinely unmeasured source renders "—" with a hollow
              // swatch and a zero renders as a zero (see below).
              const colour =
                arcs.find((a) => a.label === segment.label)?.colour ??
                (grouped ? arcs[arcs.length - 1]?.colour : undefined);
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
                        ? small.some((s) => s.label === segment.label)
                          ? `grouped into Other (below ${groupBelowPercent}%)`
                          : "grouped into Other"
                        : undefined
                  }
                  className="flex items-center gap-2 text-[12px]"
                >
                  <span
                    data-testid="legend-swatch"
                    aria-hidden="true"
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{
                      backgroundColor: unmeasured || zero || !colour ? "transparent" : colour,
                      border: unmeasured || zero || !colour ? `1px solid ${STATE.neutral}` : undefined,
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
            {otherMembers.length > 0 ? (
              <li
                data-testid="legend-row"
                data-segment="Other"
                title={`Other = ${otherMembers.map((s) => s.label).join(", ")}`}
                className="flex items-center gap-2 text-[12px]"
              >
                <span
                  data-testid="legend-swatch"
                  aria-hidden="true"
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: arcs[arcs.length - 1]?.colour }}
                />
                <span className="flex-1 truncate text-aether-muted">
                  {overflow.length > 0
                    ? `Other (${otherMembers.length} ${otherMembers.length === 1 ? "source" : "sources"})`
                    : `Other (${small.length} ${small.length === 1 ? "source" : "sources"} below ${groupBelowPercent}%)`}
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
            {laidOutArcs.map((arc) => {
              const dashOffset = -arc.offset;
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
                  strokeDasharray={`${arc.visible} ${CIRCUMFERENCE - arc.visible}`}
                  strokeDashoffset={motion.atOrigin ? dashOffset - arc.visible : dashOffset}
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
