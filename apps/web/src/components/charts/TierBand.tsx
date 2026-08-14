"use client";

/**
 * `<TierBand>` — the rigor policy as a PICTURE of itself (ANALYTICS-VIZ).
 *
 * The policy surfaces used to be read as prose: a bulleted list of trigger
 * sentences, and a scrolling list of "tier, date, conversion, sample size"
 * rows. Both are answers to a shaped question — "what has the policy been, for
 * how long, and did the metric it responds to move?" — that a reader should be
 * able to answer at a glance.
 *
 * The band draws exactly that and nothing more:
 *   · one segment per recorded tier point, WIDTH PROPORTIONAL TO RUNS, so a
 *     tier an agent obeyed for 40 runs is visibly forty runs' worth of the
 *     search and a one-run blip is a sliver. Runs are the only honest measure
 *     of "how long" available — the points are irregular in time (they exist
 *     only where the tier or its inputs changed), so spacing them by DATE would
 *     draw a continuity the data does not have;
 *   · the metric the policy responds to (interview conversion) drawn under each
 *     segment against the target line it is compared with, so "the tier
 *     escalated and the rate then moved / did not move" is visible rather than
 *     asserted;
 *   · tier meaning carried by a WORD in every segment and in the legend, never
 *     by colour alone (C-5).
 *
 * Everything the old list rows said still exists verbatim in `<ChartFrame>`'s
 * hidden data table, which is the chart's text equivalent — nothing honest was
 * traded for the picture.
 */
import type { ReactNode } from "react";

import { ChartFrame } from "./ChartFrame";
import { formatNumber } from "./geometry";
import { useChartMotion } from "./motion";
import { EmptyPlot } from "./primitives";
import { HAIRLINE_STRONG, STATE, TRACK } from "./tokens";
import type { ChartDatum } from "./types";

export interface TierBandPoint {
  /** ISO timestamp, or null when the run recorded none. */
  at?: string | null;
  tier: string;
  /** Agent runs that actually obeyed this tier. Drives segment width. */
  runs: number;
  /** Interview conversion at that point, as a percentage. */
  conversionRate: number;
  /** Submissions the rate was computed from. */
  sampleSize: number;
  dimensionsBelowFloor?: readonly string[];
}

export interface TierBandProps {
  title: string;
  /** C-3 — required. */
  windowLabel: string;
  points: readonly TierBandPoint[];
  /** The interview-conversion target the metric row is compared against, %. */
  target: number;
  /** Machine tier → reader-facing label. A tier missing from the map renders
   *  its raw key rather than being silently relabelled. */
  tierLabels: Readonly<Record<string, string>>;
  footnote?: ReactNode;
  emptyMessage?: string;
  emptyHint?: string;
  className?: string;
}

/** Tone per tier. NEVER the only carrier of the meaning — the word rides with
 *  it in the segment, the legend and the data table (C-5). */
const TIER_TONE: Record<string, string> = {
  standard: STATE.ok,
  heightened: STATE.warn,
  insufficient_data: STATE.neutral,
};

function formatWhen(at: string | null | undefined): string {
  if (!at) return "date not recorded";
  const parsed = new Date(at);
  if (Number.isNaN(parsed.getTime())) return "date not recorded";
  return parsed.toLocaleDateString("en-AU", { day: "numeric", month: "short" });
}

export function TierBand({
  title,
  windowLabel,
  points,
  target,
  tierLabels,
  footnote,
  emptyMessage = "No agent run has recorded a rigor tier yet.",
  emptyHint,
  className,
}: TierBandProps) {
  const motion = useChartMotion();

  const totalRuns = points.reduce((sum, p) => sum + Math.max(0, p.runs), 0);

  /**
   * A segment's share of the band, and whether it is wide enough to hold text.
   *
   * A real user's history is not two tidy points: production carries 14, and
   * printing a tier name, a run count AND a date into every one of them
   * produced three rows of overlapping ellipses ("HEIGH… H… HEI…") where a
   * band should be. Narrow segments therefore draw the MARK only — their tier,
   * runs, date and metrics stay reachable on the segment's own tooltip and, in
   * full, in the hidden data table, which is the chart's text equivalent.
   */
  const share = (point: TierBandPoint): number =>
    totalRuns > 0 ? (Math.max(0, point.runs) / totalRuns) * 100 : 100 / points.length;
  /** Roughly the width a 10px uppercase tier label needs at a 600px band. */
  const LABEL_MIN_SHARE = 12;
  /** Roughly the width a 3-digit mono numeral needs. */
  const NUMERAL_MIN_SHARE = 6;
  const maxRate = Math.max(target, ...points.map((p) => p.conversionRate), 1) * 1.2;

  const data: ChartDatum[] = points.map((point) => ({
    label: `${formatWhen(point.at)} · ${tierLabels[point.tier] ?? point.tier}`,
    value: point.runs,
    display: `${formatNumber(point.runs)} run${point.runs === 1 ? "" : "s"}`,
    note:
      `interview conversion ${point.conversionRate}% of ${formatNumber(point.sampleSize)} ` +
      `submission${point.sampleSize === 1 ? "" : "s"} vs the ${target}% target` +
      ((point.dimensionsBelowFloor?.length ?? 0) > 0
        ? `; dimensions at or below floor: ${(point.dimensionsBelowFloor ?? []).join(", ")}`
        : ""),
  }));

  /** Distinct tiers, in first-appearance order — the legend, C-5. */
  const tiersPresent = points.reduce<string[]>((acc, p) => {
    if (!acc.includes(p.tier)) acc.push(p.tier);
    return acc;
  }, []);

  return (
    <ChartFrame
      title={title}
      windowLabel={windowLabel}
      scale={{ kind: "linear" }}
      data={data}
      footnote={footnote}
      className={className}
      legend={
        points.length > 0 ? (
          <ul className="flex flex-wrap gap-x-4 gap-y-1" data-testid="tier-band-legend">
            {tiersPresent.map((tier) => (
              <li
                key={tier}
                className="flex items-center gap-1.5 text-[11px] text-aether-muted-dim"
              >
                <span
                  aria-hidden="true"
                  className="h-2 w-2 shrink-0 rounded-[2px]"
                  style={{ backgroundColor: TIER_TONE[tier] ?? STATE.neutral }}
                />
                <span>{tierLabels[tier] ?? tier}</span>
              </li>
            ))}
            <li className="flex items-center gap-1.5 text-[11px] text-aether-muted-dim">
              <span
                aria-hidden="true"
                className="h-px w-4 shrink-0"
                style={{ backgroundColor: STATE.warn }}
              />
              <span>{`${target}% interview-conversion target`}</span>
            </li>
          </ul>
        ) : undefined
      }
    >
      {points.length === 0 ? (
        <EmptyPlot message={emptyMessage} hint={emptyHint} />
      ) : (
        <div className="flex flex-col gap-2" data-chart="tier-band">
          {/* THE BAND — one segment per recorded tier, sized by runs. */}
          <div
            className="flex h-9 w-full gap-px overflow-hidden rounded-lg"
            style={{ backgroundColor: TRACK }}
          >
            {points.map((point, index) => {
              const width = share(point);
              const tone = TIER_TONE[point.tier] ?? STATE.neutral;
              const label = tierLabels[point.tier] ?? point.tier;
              return (
                <div
                  key={`band-${index}`}
                  data-testid="tier-band-segment"
                  data-tier={point.tier}
                  title={`${label} — ${formatWhen(point.at)}, ${formatNumber(point.runs)} run${
                    point.runs === 1 ? "" : "s"
                  }`}
                  className="relative flex min-w-[3px] items-center justify-center overflow-hidden"
                  style={{
                    width: `${width}%`,
                    backgroundColor: `${tone}33`,
                    borderTop: `2px solid ${tone}`,
                    transformOrigin: "left",
                    transform: motion.atOrigin ? "scaleX(0)" : undefined,
                    transition: motion.transition("transform", motion.stagger(index, 45, 8)),
                  }}
                >
                  {width >= LABEL_MIN_SHARE ? (
                    <span
                      className="truncate px-1.5 text-[10px] font-semibold uppercase tracking-[0.04em]"
                      style={{ color: tone }}
                    >
                      {label}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>

          {/* RUNS — the numeral under each segment, so the width is provable. */}
          <div className="flex w-full gap-px" data-testid="tier-band-runs">
            {points.map((point, index) => {
              const width = share(point);
              return (
                <div
                  key={`runs-${index}`}
                  className="min-w-0 overflow-hidden text-center font-mono text-[10px] tabular-nums text-aether-muted-dim"
                  style={{ width: `${width}%` }}
                >
                  {width >= NUMERAL_MIN_SHARE ? formatNumber(point.runs) : ""}
                </div>
              );
            })}
          </div>

          {/* THE METRIC the policy responds to, on the same x-partition, with
              the target as a dashed line across the whole plot. */}
          <div
            className="relative mt-1 flex h-16 w-full items-end gap-px"
            data-testid="tier-band-metric"
          >
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 block h-px"
              style={{
                bottom: `${Math.min(100, (target / maxRate) * 100)}%`,
                backgroundImage: `repeating-linear-gradient(90deg, ${STATE.warn} 0 3px, transparent 3px 6px)`,
              }}
            />
            {points.map((point, index) => {
              const width = share(point);
              const h = Math.max(1, (point.conversionRate / maxRate) * 64);
              const met = point.conversionRate >= target;
              return (
                <div
                  key={`metric-${index}`}
                  className="flex min-w-0 flex-col justify-end"
                  style={{ width: `${width}%` }}
                >
                  <span
                    data-testid="tier-band-metric-bar"
                    data-mark={point.conversionRate === 0 ? "zero" : "value"}
                    title={`${formatWhen(point.at)}: interview conversion ${
                      point.conversionRate
                    }% of ${formatNumber(point.sampleSize)} submissions`}
                    className="block w-full"
                    style={{
                      height: point.conversionRate === 0 ? 1 : h,
                      backgroundColor:
                        point.conversionRate === 0
                          ? HAIRLINE_STRONG
                          : met
                            ? STATE.ok
                            : STATE.info,
                      transformOrigin: "bottom",
                      transform: motion.atOrigin ? "scaleY(0)" : undefined,
                      transition: motion.transition("transform", motion.stagger(index, 45, 8)),
                    }}
                  />
                </div>
              );
            })}
          </div>

          {/* The x labels: when each tier point was recorded. */}
          <div className="flex w-full gap-px" data-testid="tier-band-dates">
            {points.map((point, index) => {
              const width = share(point);
              return (
                <div
                  key={`date-${index}`}
                  className="min-w-0 truncate text-center font-mono text-[10px] text-aether-muted-dim"
                  style={{ width: `${width}%` }}
                >
                  {width >= LABEL_MIN_SHARE ? formatWhen(point.at) : ""}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </ChartFrame>
  );
}
