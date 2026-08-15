"use client";

/**
 * `<Heatmap>` — S-UI-REBUILD-SPEC §4.3 row 7 (market demand grid).
 *
 * The quiet lie this component refuses: painting "we have no data for Sunday
 * 03:00" as the LIGHTEST step of the heat ramp, which reads as "almost no
 * demand". An unmeasured cell gets its own surface plus a diagonal hatch, says
 * "no data" and its reason on hover, and is excluded from the ramp maximum so
 * it cannot even change the colour of the cells around it (C-2).
 *
 * A measured zero is different and looks different: an empty cell with a
 * hairline edge, never step 1 of the chart-heat gilt ramp (C-1).
 */
import { ChartFrame } from "./ChartFrame";
import { formatNumber, heatStep, markKind } from "./geometry";
import { useChartMotion } from "./motion";
import { EmptyPlot } from "./primitives";
import { CHART_HEAT, HAIRLINE, STATE, SURFACE } from "./tokens";
import type { ChartDatum } from "./types";

export interface HeatmapCell {
  /** Column word (hour, day part, band). */
  label: string;
  /** `null` = never measured. NOT zero, and NOT the coldest colour. */
  value: number | null;
  note?: string;
}

export interface HeatmapRow {
  label: string;
  cells: readonly HeatmapCell[];
}

export interface HeatmapProps {
  title: string;
  /** C-3 — required. */
  windowLabel: string;
  rows: readonly HeatmapRow[];
  /** What a cell counts ("postings", "responses"). */
  unit?: string;
  /** C-2 — required when the grid mixes a real 0 with a null. */
  nullMeaning?: string;
  footnote?: string;
  className?: string;
}

/** Rows past this index share the last stagger step, so a tall grid cannot
 *  animate forever (spec: "cap 8 rows"). */
const STAGGER_CAP = 8;
const STAGGER_STEP = 40;

export function Heatmap({
  title,
  windowLabel,
  rows,
  unit = "items",
  nullMeaning,
  footnote,
  className,
}: HeatmapProps) {
  const motion = useChartMotion();
  const data: ChartDatum[] = rows.flatMap((row) =>
    row.cells.map((cell) => ({
      label: `${row.label} ${cell.label}`,
      value: cell.value,
      note: cell.note,
    })),
  );
  const measured = data
    .map((d) => d.value)
    .filter((value): value is number => typeof value === "number");
  const max = measured.length ? Math.max(...measured) : 0;
  const min = measured.length ? Math.min(...measured) : 0;
  const columns = rows[0]?.cells.length ?? 0;

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
        rows.length > 0 ? (
          <div
            data-testid="heat-legend"
            className="flex items-center gap-2 text-[11px]"
            style={{ color: STATE.neutral }}
          >
            <span className="font-mono tabular-nums">{`${formatNumber(min)} ${unit}`}</span>
            <span className="flex items-center gap-0.5">
              {CHART_HEAT.map((colour, index) => (
                <span
                  key={colour}
                  data-testid="heat-step"
                  data-step={index + 1}
                  title={`step ${index + 1} of 5`}
                  className="h-2.5 w-4 rounded-[2px]"
                  style={{ backgroundColor: colour }}
                />
              ))}
            </span>
            <span className="font-mono tabular-nums">{`${formatNumber(max)} ${unit}`}</span>
            <span className="ml-2 flex items-center gap-1">
              <span
                aria-hidden="true"
                className="h-2.5 w-4 rounded-[2px]"
                style={{
                  backgroundColor: SURFACE.s1,
                  backgroundImage: `repeating-linear-gradient(45deg, ${HAIRLINE} 0 2px, transparent 2px 4px)`,
                }}
              />
              <span>no data</span>
            </span>
          </div>
        ) : undefined
      }
    >
      {rows.length === 0 ? (
        <EmptyPlot
          message="No demand grid has been collected for this search yet."
          hint="The grid fills in as the market collector records postings."
        />
      ) : (
        <div className="flex flex-col gap-1" data-chart="heatmap">
          <div
            className="grid gap-1 pl-12 text-[10px]"
            style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`, color: STATE.neutral }}
          >
            {rows[0]?.cells.map((cell) => (
              <span key={`col-${cell.label}`} className="truncate text-center font-mono">
                {cell.label}
              </span>
            ))}
          </div>

          {rows.map((row, rowIndex) => (
            <div
              key={row.label}
              data-row-index={rowIndex}
              className="flex items-center gap-1"
              style={{
                opacity: motion.atOrigin ? 0 : undefined,
                ...motion.transitionParts(
                  "opacity",
                  motion.stagger(rowIndex, STAGGER_STEP, STAGGER_CAP),
                ),
              }}
            >
              <span
                className="w-11 shrink-0 truncate text-right font-mono text-[10px]"
                style={{ color: STATE.neutral }}
              >
                {row.label}
              </span>
              <div
                className="grid flex-1 gap-1"
                style={{ gridTemplateColumns: `repeat(${row.cells.length}, minmax(0, 1fr))` }}
              >
                {row.cells.map((cell) => {
                  const kind = markKind(cell.value);
                  const step = kind === "unmeasured" ? null : heatStep(cell.value as number, max);
                  const title =
                    kind === "unmeasured"
                      ? `${row.label} ${cell.label} — no data${
                          cell.note ?? nullMeaning ? `: ${cell.note ?? nullMeaning}` : ""
                        }`
                      : `${row.label} ${cell.label} — ${formatNumber(
                          cell.value as number,
                        )} ${unit}`;

                  return (
                    <span
                      key={`${row.label}-${cell.label}`}
                      data-cell={`${row.label}/${cell.label}`}
                      data-mark={kind}
                      data-heat-step={step === null ? undefined : String(step)}
                      title={title}
                      className="aspect-square rounded-[3px]"
                      style={
                        kind === "unmeasured"
                          ? {
                              backgroundColor: SURFACE.s1,
                              backgroundImage: `repeating-linear-gradient(45deg, ${HAIRLINE} 0 2px, transparent 2px 4px)`,
                            }
                          : step === 0
                            ? { backgroundColor: "transparent", boxShadow: `inset 0 0 0 1px ${HAIRLINE}` }
                            : { backgroundColor: CHART_HEAT[(step as number) - 1] }
                      }
                    />
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </ChartFrame>
  );
}
