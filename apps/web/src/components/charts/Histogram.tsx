"use client";

/**
 * `<Histogram>` — S-UI-REBUILD-SPEC §4.3 row 3 (ATS score distribution).
 *
 * The bug this component retires: today's analytics histogram draws every bar
 * at `Math.max(2, (count / max) * 100)%`, so a bucket containing NOTHING still
 * paints a 2px violet line. "No résumé scored 0-19" renders as "a couple did".
 *
 * Here an empty bucket gets a 1px HAIRLINE tick on the baseline — visible as
 * structure, never as data (C-1) — and a bucket that was never scored at all
 * gets an em dash instead (C-2). The spec's "zero-count buckets render nothing
 * above the baseline" and this slice's "1px tick" are the same rule: the tick
 * marks where the bucket is, in the border colour, and rises nothing above the
 * axis in any series colour.
 */
import { ChartFrame } from "./ChartFrame";
import { barLength, formatNumber, niceTicks } from "./geometry";
import { useChartMotion } from "./motion";
import { AxisLabel, EmptyPlot, Gridlines, UnmeasuredMark, ZeroTickRect } from "./primitives";
import { CHART_PALETTE } from "./tokens";
import type { ChartDatum, PlotGeometry } from "./types";

export interface HistogramBucket {
  /** A RANGE, e.g. "0-19" — never a single edge value. */
  range: string;
  /** `null` = this bucket was never measured. It is NOT an empty bucket. */
  count: number | null;
  note?: string;
}

export interface HistogramProps {
  title: string;
  /** C-3 — required. */
  windowLabel: string;
  buckets: readonly HistogramBucket[];
  /** What the counted things are, for tooltips: "résumés", "jobs", "runs". */
  itemNoun?: string;
  /** C-2 — required when the buckets mix a real 0 with a null. */
  nullMeaning?: string;
  height?: number;
  footnote?: string;
  className?: string;
}

const BAR_COLOUR = CHART_PALETTE[4]; // c5 violet-300

export function Histogram({
  title,
  windowLabel,
  buckets,
  itemNoun = "items",
  nullMeaning,
  height = 200,
  footnote,
  className,
}: HistogramProps) {
  const motion = useChartMotion();
  const data: ChartDatum[] = buckets.map((b) => ({
    label: b.range,
    value: b.count,
    note: b.note,
  }));
  const max = Math.max(0, ...buckets.map((b) => (typeof b.count === "number" ? b.count : 0)));

  return (
    <ChartFrame
      title={title}
      windowLabel={windowLabel}
      scale={{ kind: "linear" }}
      data={data}
      nullMeaning={nullMeaning}
      height={height}
      footnote={footnote}
      className={className}
    >
      {buckets.length === 0 ? (
        <EmptyPlot
          message="Nothing has been scored yet, so there is no distribution to draw."
          hint="The first scored résumé creates the first bucket."
        />
      ) : (
        (geom: PlotGeometry) => {
          const { plot } = geom;
          const baselineY = plot.y + plot.height;
          const band = plot.width / buckets.length;
          const barWidth = Math.max(2, band * 0.68);
          const ticks = niceTicks(max, 4);

          return (
            <>
              <Gridlines geom={geom} ticks={ticks} max={max} />
              {ticks.map((tick) => (
                <AxisLabel
                  key={`y-${tick}`}
                  x={plot.x - 6}
                  y={baselineY - (max > 0 ? (tick / max) * plot.height : 0)}
                >
                  {formatNumber(Math.round(tick))}
                </AxisLabel>
              ))}

              {buckets.map((bucket, index) => {
                const x = plot.x + index * band + (band - barWidth) / 2;
                // Heights come from `barLength` for the same reason the funnel's
                // widths do: it is the one place that guarantees a real value is
                // drawn longer than a zero's tick, whatever the dynamic range.
                const { kind, length } = barLength({
                  value: bucket.count,
                  max,
                  extent: plot.height,
                  mode: "linear",
                });
                const centre = x + barWidth / 2;

                return (
                  <g key={`${bucket.range}-${index}`} data-bucket={bucket.range}>
                    {kind === "value" ? (
                      <rect
                        data-mark="value"
                        x={x}
                        y={baselineY - length}
                        width={barWidth}
                        height={length}
                        rx={2}
                        fill={BAR_COLOUR}
                        fillOpacity={0.6}
                        style={{
                          transformOrigin: `${centre}px ${baselineY}px`,
                          transform: motion.atOrigin ? "scaleY(0)" : undefined,
                          transition: motion.transition("transform", motion.stagger(index, 25)),
                        }}
                      >
                        <title>{`${bucket.range}: ${formatNumber(
                          bucket.count as number,
                        )} ${itemNoun}`}</title>
                      </rect>
                    ) : null}

                    {kind === "zero" ? (
                      <g>
                        <ZeroTickRect x={x} baselineY={baselineY} width={barWidth} />
                        <rect
                          x={x}
                          y={baselineY - 12}
                          width={barWidth}
                          height={12}
                          fill="transparent"
                        >
                          <title>{`${bucket.range}: 0 ${itemNoun}`}</title>
                        </rect>
                      </g>
                    ) : null}

                    {kind === "unmeasured" ? (
                      <UnmeasuredMark
                        x={centre}
                        y={baselineY - 10}
                        title={`${bucket.range}: not measured — ${
                          bucket.note ?? nullMeaning ?? "reason not provided"
                        }`}
                      />
                    ) : null}

                    <AxisLabel x={centre} y={baselineY + 12} anchor="middle" testId="bucket-label">
                      {bucket.range}
                    </AxisLabel>
                  </g>
                );
              })}
            </>
          );
        }
      )}
    </ChartFrame>
  );
}
