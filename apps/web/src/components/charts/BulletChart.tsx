"use client";

/**
 * `<BulletChart>` — a measure against a TARGET, plus the denominator that
 * measure was computed from (ANALYTICS-VIZ; S-UI-REBUILD-SPEC §4.2 laws apply
 * through `<ChartFrame>` exactly as for every other kit member).
 *
 * It exists because "8.33%" and "the 20% target" were being related to each
 * other in a PARAGRAPH — the reader was asked to do the subtraction and then
 * to trust it. A bullet row does that comparison geometrically: the measure is
 * the bar, the target is a labelled tick, and the distance between them is the
 * claim. No sentence is required for a reader to see whether the target is met.
 *
 * THE COVERAGE RIBBON is the honesty half of this component and the reason it
 * is not just "a bar with a line on it". A per-cohort conversion rate is only
 * as trustworthy as the share of submissions it actually covers: if 290 of 317
 * submitted applications predate the instrumentation, then every rate drawn
 * above describes 27 applications, not 317. `coverage` draws that as a single
 * stacked bar with the unattributable share as its own labelled, neutral,
 * hatched segment — so the gap is a thing you SEE, in proportion, instead of a
 * footnote you might not read.
 *
 * A row with `value: null` is never drawn as 0 (C-2). It renders the neutral
 * dash and states its reason on the row, so "we do not know this cohort's rate
 * yet" can never be mistaken for "this cohort converts at zero".
 *
 * THE TARGET IS OPTIONAL. Where no published target exists the tick and its
 * label are not drawn at all, rather than drawn against an invented benchmark
 * — see the `target` prop.
 */
import type { ReactNode } from "react";

import { ChartFrame } from "./ChartFrame";
import { formatNumber, NOT_MEASURED } from "./geometry";
import { useChartMotion } from "./motion";
import { CHART_PALETTE, HAIRLINE, STATE, TRACK } from "./tokens";
import { EmptyPlot } from "./primitives";
import type { ChartDatum } from "./types";

export interface BulletRow {
  label: string;
  /** The measure. `null` = not measured — NEVER drawn as zero. */
  value: number | null;
  /** Pre-formatted numeral ("8.33%"). */
  display?: string;
  /** Why it is unmeasured, or any qualifier. Rendered verbatim, on the row. */
  note?: string;
  /** The denominator behind the measure, shown beside it so a percentage is
   *  never displayed without the count it came from. */
  basis?: string;
  /** Stable hook for callers that already pin a row by test id. */
  testId?: string;
  /** Extra content rendered at the end of the row (badges, chips). */
  trailing?: ReactNode;
}

export interface BulletCoverageSegment {
  label: string;
  count: number;
  /** `attributed` = counted toward the measures above; `unattributed` = it is
   *  not, and is drawn neutral + hatched so it can never read as a series. */
  kind: "attributed" | "unattributed";
}

export interface BulletChartProps {
  title: string;
  /** C-3 — required. */
  windowLabel: string;
  rows: readonly BulletRow[];
  /**
   * The target every row is compared against.
   *
   * OPTIONAL, and deliberately so (F3): some measures have no published
   * target, and cost per outcome is one of them — nothing in this product
   * states what an application or an interview OUGHT to cost. Drawing a tick
   * there would be inventing a benchmark, which is the fabrication the whole
   * kit exists to prevent. With no target the rows still share one linear
   * axis, so the comparison BETWEEN them (an interview costs 2.5x an
   * application) is still geometric — it simply makes no claim about whether
   * either number is good.
   */
  target?: { value: number; label: string };
  /** C-2 — required when the rows mix a real 0 with a null. */
  nullMeaning?: string;
  /** The denominator ribbon. Omit when every measure covers its whole
   *  population — an all-attributed ribbon is noise. */
  coverage?: readonly BulletCoverageSegment[];
  /** Caption under the ribbon, rendered verbatim. */
  coverageNote?: string;
  footnote?: ReactNode;
  /** Axis top. Defaults to 25% headroom over the largest of measures/target. */
  axisMax?: number;
  className?: string;
  emptyMessage?: string;
  emptyHint?: string;
}

const SERIES = CHART_PALETTE[0]; // c1 chart-gold
const MET = STATE.ok;

export function BulletChart({
  title,
  windowLabel,
  rows,
  target,
  nullMeaning,
  coverage,
  coverageNote,
  footnote,
  axisMax,
  className,
  emptyMessage = "Nothing has been measured against this target yet.",
  emptyHint,
}: BulletChartProps) {
  const motion = useChartMotion();

  const data: ChartDatum[] = [
    ...rows.map((row) => ({
      label: row.label,
      value: row.value,
      note: row.note ?? row.basis,
      display: row.display,
    })),
    ...(target ? [{ label: `${target.label} (target)`, value: target.value }] : []),
    ...(coverage ?? []).map((segment) => ({
      label: `${segment.label} (coverage)`,
      value: segment.count,
    })),
  ];

  const measured = rows
    .map((r) => r.value)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  /*
   * THE AXIS COMES FROM THE DATA, not from a constant.
   *
   * This used to be `Math.max(…measured, target, 1) * 1.25`, where the `1` was
   * only ever meant to keep an all-unmeasured chart from computing an axis of
   * 0. On a percentage series it never bound (every value and target exceeds
   * 1) — but on a series measured in dollars-and-cents it DOMINATED: a $0.03
   * cost per application drew a 2.7% bar against an invented $1.25 axis, so
   * the mark said "almost nothing" about a number that is the whole row. The
   * floor now applies only when there is genuinely nothing to scale to.
   */
  const dataTop = Math.max(...measured, target?.value ?? 0);
  const top = axisMax ?? (dataTop > 0 ? dataTop * 1.25 : 1);
  const targetPct = target ? Math.min(100, (target.value / top) * 100) : null;
  const coverageTotal = (coverage ?? []).reduce((sum, s) => sum + Math.max(0, s.count), 0);

  return (
    <ChartFrame
      title={title}
      windowLabel={windowLabel}
      scale={{ kind: "linear" }}
      data={data}
      nullMeaning={nullMeaning}
      footnote={footnote}
      className={className}
    >
      {rows.length === 0 ? (
        <EmptyPlot message={emptyMessage} hint={emptyHint} />
      ) : (
        <div className="flex flex-col gap-2" data-chart="bullet">
          {rows.map((row, index) => {
            const isMeasured = typeof row.value === "number" && Number.isFinite(row.value);
            const isZero = row.value === 0;
            const pct = isMeasured ? Math.min(100, ((row.value as number) / top) * 100) : 0;
            const meetsTarget =
              target !== undefined && isMeasured && (row.value as number) >= target.value;
            return (
              <div
                key={`${row.label}-${index}`}
                data-testid={row.testId ?? "bullet-row"}
                data-row={row.label}
                className="flex flex-wrap items-center gap-x-3 gap-y-1"
              >
                {/* The label keeps its own column at EVERY width. A
                    `w-full` label wrapped each row onto three lines at 390px,
                    which turned a ten-dimension chart into 600px of stacked
                    text — the density defect the chart was drawn to remove. */}
                <span
                  className="w-24 shrink-0 truncate text-[13px] leading-[1.5] text-aether-muted sm:w-40"
                  title={row.label}
                >
                  {row.label}
                </span>

                <div className="relative min-w-[120px] flex-1">
                  <div
                    data-testid="bullet-track"
                    className="relative h-4 w-full overflow-hidden rounded-md"
                    style={{ backgroundColor: TRACK }}
                  >
                    {isMeasured && !isZero ? (
                      <div
                        data-testid="bullet-measure"
                        data-mark="value"
                        className="absolute inset-y-0 left-0 rounded-md"
                        style={{
                          width: `${pct}%`,
                          backgroundColor: meetsTarget ? MET : SERIES,
                          transformOrigin: "left",
                          transform: motion.atOrigin ? "scaleX(0)" : undefined,
                          transition: motion.transition(
                            "transform",
                            motion.stagger(index, 45, 6),
                          ),
                        }}
                      />
                    ) : null}
                    {isZero ? (
                      <div
                        data-mark="zero"
                        data-tone="neutral"
                        title={`${row.label}: 0`}
                        className="absolute inset-y-1 left-0"
                        style={{ width: "1px", backgroundColor: HAIRLINE }}
                      />
                    ) : null}
                    {!isMeasured ? (
                      <span
                        data-mark="unmeasured"
                        data-tone="neutral"
                        title={row.note ?? nullMeaning ?? "not measured"}
                        className="absolute left-2 top-1/2 -translate-y-1/2 font-mono text-[11px] leading-none"
                        style={{ color: STATE.neutral }}
                      >
                        {NOT_MEASURED}
                      </span>
                    ) : null}
                  </div>
                  {/* The target tick spans the full row height so a reader can
                      sight down it across every cohort at once. It is drawn
                      only where a target actually exists — see `target`. */}
                  {target && targetPct !== null ? (
                    <span
                      data-testid="bullet-target-tick"
                      aria-hidden="true"
                      className="pointer-events-none absolute -top-0.5 block h-5 w-px"
                      style={{ left: `${targetPct}%`, backgroundColor: STATE.warn }}
                      title={target.label}
                    />
                  ) : null}
                </div>

                <span
                  data-testid="bullet-value"
                  data-tone={isMeasured && !isZero ? "series" : "neutral"}
                  className="w-16 shrink-0 text-right font-mono text-[13px] tabular-nums sm:w-20"
                  style={{
                    color: isMeasured
                      ? meetsTarget
                        ? MET
                        : undefined
                      : STATE.neutral,
                  }}
                >
                  {isMeasured ? (row.display ?? formatNumber(row.value as number)) : NOT_MEASURED}
                </span>

                {row.trailing}

                {/*
                 * THE DENOMINATOR AND THE REASON GET THEIR OWN LINE.
                 *
                 * They used to sit in the measure line, where `flex-1` on the
                 * note competed with `flex-1` on the track: a row carrying a
                 * long "nothing to divide by" reason ended up with a track
                 * ~350px SHORTER than the row above it, and two bars drawn on
                 * different-length tracks are not on the same scale — the one
                 * thing a bullet row exists to guarantee. Wrapping them to a
                 * full-width second line, indented to the track's left edge,
                 * makes every row's measure line identical by construction.
                 */}
                {row.basis || row.note ? (
                  <div className="flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[11px] leading-[1.5] text-aether-muted-dim sm:pl-[172px]">
                    {row.basis ? <span data-testid="bullet-basis">{row.basis}</span> : null}
                    {row.note ? (
                      <span data-testid="bullet-note" className="min-w-0">
                        {row.note}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}

          {/* C-5: the target's meaning is a word on the plot, not a colour a
              reader has to decode from a legend that may be scrolled away.
              No target, no tick and no label row — an empty 12px strip under
              a targetless chart is the dead void composition rule 6 forbids. */}
          {target && targetPct !== null ? (
            <div className="relative mt-1 h-3 sm:ml-[172px]">
              <span
                data-testid="bullet-target-label"
                className="absolute top-0 whitespace-nowrap font-mono text-[10px] leading-none"
                style={{
                  left: `${targetPct}%`,
                  transform: targetPct > 60 ? "translateX(-100%)" : "translateX(-50%)",
                  color: STATE.warn,
                }}
              >
                {`▲ ${target.label}`}
              </span>
            </div>
          ) : null}

          {coverage && coverageTotal > 0 ? (
            <div className="mt-2" data-testid="bullet-coverage">
              <div
                className="flex h-3 w-full overflow-hidden rounded-md"
                style={{ backgroundColor: TRACK }}
                role="img"
                aria-label={coverage
                  .map((s) => `${s.label}: ${formatNumber(s.count)}`)
                  .join("; ")}
              >
                {coverage.map((segment, index) => (
                  <span
                    key={`${segment.label}-${index}`}
                    data-testid="bullet-coverage-segment"
                    data-coverage={segment.kind}
                    title={`${segment.label}: ${formatNumber(segment.count)}`}
                    style={{
                      width: `${(Math.max(0, segment.count) / coverageTotal) * 100}%`,
                      backgroundColor:
                        segment.kind === "attributed" ? SERIES : "transparent",
                      // The unattributable share is HATCHED, not tinted: a
                      // solid neutral block still reads as a measured category.
                      backgroundImage:
                        segment.kind === "unattributed"
                          ? `repeating-linear-gradient(45deg, ${STATE.neutral}55 0 3px, transparent 3px 6px)`
                          : undefined,
                      opacity: segment.kind === "attributed" ? 0.9 : 1,
                    }}
                  />
                ))}
              </div>
              <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1" data-testid="bullet-coverage-legend">
                {coverage.map((segment, index) => (
                  <li
                    key={`legend-${segment.label}-${index}`}
                    className="flex items-center gap-1.5 text-[11px] text-aether-muted-dim"
                  >
                    <span
                      aria-hidden="true"
                      className="h-2 w-2 shrink-0 rounded-[2px]"
                      style={{
                        backgroundColor:
                          segment.kind === "attributed" ? SERIES : "transparent",
                        backgroundImage:
                          segment.kind === "unattributed"
                            ? `repeating-linear-gradient(45deg, ${STATE.neutral}88 0 2px, transparent 2px 4px)`
                            : undefined,
                        border:
                          segment.kind === "unattributed"
                            ? `1px solid ${STATE.neutral}`
                            : undefined,
                      }}
                    />
                    <span>{segment.label}</span>
                    <span className="font-mono tabular-nums">{formatNumber(segment.count)}</span>
                  </li>
                ))}
              </ul>
              {coverageNote ? (
                <p
                  data-prose="caption"
                  data-testid="bullet-coverage-note"
                  className="mt-1.5 text-[11px] leading-[1.5] text-aether-muted-dim"
                >
                  {coverageNote}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </ChartFrame>
  );
}
