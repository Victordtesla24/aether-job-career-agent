"use client";

/**
 * `<DivergingBar>` — S-UI-REBUILD-SPEC §4.3 row 6 (market-vs-you rows).
 *
 * Every row here compares the user against a live external source, so most of
 * the component is about the rows that CANNOT be drawn:
 *   · `available === false` or `connected === false` ⇒ "—" plus the caller's
 *     reason, VERBATIM. Never 0, never "no difference", never a bar of any
 *     length — those are all claims about the market that nobody measured.
 *   · a genuine 0 ⇒ a 1px hairline tick on the shared axis (C-1), with the
 *     row's own words ("0 days") kept intact.
 * The freshness stamp travels with the value, because a market number without
 * a date is a number of unknown age.
 */
import { ChartFrame } from "./ChartFrame";
import { NOT_MEASURED, ZERO_TICK_WIDTH, barLength, barPercent, formatNumber } from "./geometry";
import { useChartMotion } from "./motion";
import { EmptyPlot } from "./primitives";
import { DIVERGING, HAIRLINE, HAIRLINE_STRONG, STATE, TRACK } from "./tokens";
import type { ChartDatum } from "./types";

export interface DivergingRow {
  label: string;
  /** Signed delta versus the market. `null` = not measured. */
  value: number | null;
  /** Pre-formatted value ("+A$12,000", "-8 pts"). */
  display?: string;
  /** Freshness stamp, rendered verbatim next to the value. */
  freshness?: string;
  /** `false` ⇒ the source has no snapshot for this row. */
  available?: boolean;
  /** `false` ⇒ the user has not connected the source this row needs. */
  connected?: boolean;
  /** Why the row cannot be drawn — rendered verbatim, never paraphrased. */
  reason?: string;
}

export interface DivergingBarProps {
  title: string;
  /** C-3 — required. */
  windowLabel: string;
  rows: readonly DivergingRow[];
  /** C-2 — required when the rows mix a real 0 with a null. */
  nullMeaning?: string;
  footnote?: string;
  className?: string;
}

function rowValue(row: DivergingRow): number | null {
  // Fail closed: an unavailable or unconnected row has no value, whatever
  // number happens to be attached to it.
  if (row.available === false || row.connected === false) return null;
  return typeof row.value === "number" ? row.value : null;
}

export function DivergingBar({
  title,
  windowLabel,
  rows,
  nullMeaning,
  footnote,
  className,
}: DivergingBarProps) {
  const motion = useChartMotion();
  const data: ChartDatum[] = rows.map((row) => ({
    label: row.label,
    value: rowValue(row),
    note: row.reason,
    display: row.display,
  }));
  const maxAbs = Math.max(
    1,
    ...rows.map((row) => Math.abs(rowValue(row) ?? 0)),
  );

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
        <EmptyPlot
          message="No market comparisons are available for your search yet."
          hint="They appear once a market snapshot covers your role and location."
        />
      ) : (
        <div className="relative flex flex-col gap-1.5" data-chart="diverging">
          {/* One shared zero axis behind every row. The label and value
              columns are the same width, so the track — and therefore the
              zero — is exactly at the container's midpoint. */}
          <div
            data-testid="zero-axis"
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 left-1/2"
            style={{ width: "1px", backgroundColor: HAIRLINE_STRONG }}
          />
          {rows.map((row, index) => {
            const value = rowValue(row);
            // Half the track per side, so `extent` is 50 (percent). The length
            // comes from `barLength` — the kit's one floor — so a row that is
            // four orders of magnitude below the widest one is still drawn
            // longer than the 1px tick that means "level with the market".
            const { kind, length } = barLength({
              value,
              max: maxAbs,
              extent: 50,
              mode: "linear",
            });
            const direction = kind === "value" && (value as number) < 0 ? "negative" : "positive";
            const reason = row.reason;

            return (
              <div
                key={`${row.label}-${index}`}
                data-row={row.label}
                className="flex items-center gap-3"
              >
                <span
                  className="w-28 shrink-0 truncate text-[13px] text-aether-muted sm:w-40"
                  title={row.label}
                >
                  {row.label}
                </span>

                <div className="relative h-6 flex-1 rounded-md" style={{ backgroundColor: TRACK }}>
                  {kind === "value" ? (
                    <div
                      data-testid="bar"
                      data-mark="value"
                      data-direction={direction}
                      className="absolute inset-y-1 rounded-sm"
                      style={{
                        width: barPercent(length),
                        left: direction === "positive" ? "50%" : undefined,
                        right: direction === "negative" ? "50%" : undefined,
                        backgroundColor:
                          direction === "positive" ? DIVERGING.positive : DIVERGING.negative,
                        transformOrigin: direction === "positive" ? "left" : "right",
                        transform: motion.atOrigin ? "scaleX(0)" : undefined,
                        transition: motion.transition("transform", motion.stagger(index)),
                      }}
                    />
                  ) : null}

                  {kind === "zero" ? (
                    <div
                      data-mark="zero"
                      data-tone="neutral"
                      className="absolute inset-y-1 left-1/2"
                      style={{ width: `${ZERO_TICK_WIDTH}px`, backgroundColor: HAIRLINE }}
                      title={`${row.label}: level with the market`}
                    />
                  ) : null}

                  {kind === "unmeasured" ? (
                    <span
                      data-mark="unmeasured"
                      data-tone="neutral"
                      className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 font-mono text-[12px]"
                      style={{ color: STATE.neutral }}
                      title={reason ?? nullMeaning ?? "not measured"}
                    >
                      {NOT_MEASURED}
                    </span>
                  ) : null}
                </div>

                <span className="flex w-28 shrink-0 flex-col items-end sm:w-40">
                  <span
                    className="font-mono text-[13px] tabular-nums"
                    style={{ color: kind === "value" ? undefined : STATE.neutral }}
                  >
                    {kind === "unmeasured"
                      ? NOT_MEASURED
                      : (row.display ?? formatNumber(value as number))}
                  </span>
                  {kind === "unmeasured" && reason ? (
                    <span className="text-right text-[11px]" style={{ color: STATE.neutral }}>
                      {reason}
                    </span>
                  ) : null}
                  {row.freshness ? (
                    <span className="text-[11px]" style={{ color: STATE.neutral }}>
                      {row.freshness}
                    </span>
                  ) : null}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </ChartFrame>
  );
}
