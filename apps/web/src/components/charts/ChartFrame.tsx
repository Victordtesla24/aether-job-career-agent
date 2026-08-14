"use client";

/**
 * `<ChartFrame>` — the shell every chart in the kit renders inside, and the
 * place the five honest-rendering laws are enforced (S-UI-REBUILD-SPEC §4.2).
 *
 * It owns, in one implementation instead of seven:
 *   · the law assertions (C-2..C-5 throw in dev, report in production)
 *   · the accessible summary (`role="img"` + aria-label)
 *   · the visually-hidden data table — the chart's exact text equivalent,
 *     where "not measured" and its reason are spelled out in words
 *   · the window label (C-3) in a reserved footnote slot
 *   · the scale chip / axis-break glyph (C-4)
 *   · a responsive viewBox via ResizeObserver
 *
 * It deliberately owns NO border, NO background and NO card chrome: the
 * gridlines and axis labels do all the framing (reference-pack rule 5). The
 * card around a chart is `<Section>`'s job, not the chart's.
 */
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

import { DEFAULT_PLOT_WIDTH, NOT_MEASURED, formatNumber, plotGeometry } from "./geometry";
import { assertChartLaws } from "./laws";
import { useChartMotion } from "./motion";
import { HAIRLINE_STRONG, META_TEXT_CLASS, STATE } from "./tokens";
import type { ChartDatum, PlotGeometry, PlotInsets, ScaleDeclaration } from "./types";

/** Above this many rows the hidden table summarises instead of listing —
 *  a 2,000-row table is not an accessible equivalent, it is a wall. */
const MAX_TABLE_ROWS = 200;

export interface ChartFrameProps {
  /** The chart's own heading. */
  title: string;
  /** C-3 — REQUIRED. The sample window this chart was drawn from. */
  windowLabel: string;
  /** C-4 — REQUIRED. How values map onto length/position. */
  scale: ScaleDeclaration;
  /** Everything the chart draws, in reading order. Powers the hidden table
   *  and the C-2/C-5 assertions. */
  data: readonly ChartDatum[];
  /** C-2 — REQUIRED whenever the series contains both 0 and null. */
  nullMeaning?: string;
  /** Overrides the generated aria-label. */
  summary?: string;
  height?: number;
  padding?: Partial<PlotInsets>;
  legend?: ReactNode;
  action?: ReactNode;
  footnote?: ReactNode;
  className?: string;
  /** A function child receives plot geometry and is wrapped in an `<svg>`;
   *  a node child (funnel rows, heat grid) is rendered as-is. */
  children: ReactNode | ((geom: PlotGeometry) => ReactNode);
}

function displayValue(datum: ChartDatum): string {
  if (datum.display !== undefined) return datum.display;
  if (datum.value === null || datum.value === undefined) return NOT_MEASURED;
  return formatNumber(datum.value);
}

function rowMark(datum: ChartDatum): "value" | "zero" | "unmeasured" {
  if (datum.value === null || datum.value === undefined) return "unmeasured";
  return datum.value === 0 ? "zero" : "value";
}

/** The text equivalent of the plot. Long series are summarised — and the
 *  caption says so, so nobody mistakes the summary for the whole series. */
function DataTable({
  title,
  windowLabel,
  data,
  nullMeaning,
}: {
  title: string;
  windowLabel: string;
  data: readonly ChartDatum[];
  nullMeaning?: string;
}) {
  const summarised = data.length > MAX_TABLE_ROWS;
  const measured = data.filter((d) => typeof d.value === "number") as Array<
    ChartDatum & { value: number }
  >;
  const unmeasuredCount = data.length - measured.length;

  const rows: ChartDatum[] = summarised
    ? [
        { label: "Values", value: data.length },
        { label: "Not measured", value: unmeasuredCount },
        {
          label: "Minimum",
          value: measured.length ? Math.min(...measured.map((d) => d.value)) : null,
        },
        {
          label: "Maximum",
          value: measured.length ? Math.max(...measured.map((d) => d.value)) : null,
        },
        { label: `First (${data[0]?.label ?? "—"})`, value: data[0]?.value ?? null },
        {
          label: `Last (${data[data.length - 1]?.label ?? "—"})`,
          value: data[data.length - 1]?.value ?? null,
        },
      ]
    : [...data];

  return (
    <table className="sr-only" data-testid="chart-data-table">
      <caption>
        {`${title} — ${windowLabel}`}
        {summarised
          ? ` — summarised: ${formatNumber(data.length)} values, listed in full only up to ${formatNumber(MAX_TABLE_ROWS)}`
          : ""}
      </caption>
      <thead>
        <tr>
          <th scope="col">Label</th>
          <th scope="col">Value</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((datum, index) => {
          const mark = rowMark(datum);
          return (
            <tr key={`${datum.label}-${index}`} data-row-mark={mark}>
              <th scope="row">{datum.label}</th>
              <td>
                {mark === "unmeasured"
                  ? `not measured — ${datum.note ?? nullMeaning ?? "reason not provided"}`
                  : displayValue(datum)}
                {mark !== "unmeasured" && datum.note ? ` (${datum.note})` : ""}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function ChartFrame({
  title,
  windowLabel,
  scale,
  data,
  nullMeaning,
  summary,
  height = 200,
  padding,
  legend,
  action,
  footnote,
  className,
  children,
}: ChartFrameProps) {
  // C-2..C-5. Throws in dev/test, reports in production. Runs before anything
  // is drawn, so a violating chart cannot reach a screenshot.
  assertChartLaws({ windowLabel, scale, data, nullMeaning });

  const motion = useChartMotion();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(DEFAULT_PLOT_WIDTH);
  const labelId = useId();

  useEffect(() => {
    const element = containerRef.current;
    if (!element || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver((entries) => {
      const measured = Math.round(entries[0]?.contentRect.width ?? 0);
      if (measured > 0) setWidth(measured);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const geom = useMemo(() => plotGeometry(width, height, padding), [width, height, padding]);

  const unmeasured = data.filter((d) => d.value === null || d.value === undefined).length;
  const ariaLabel =
    summary ??
    `${title} — ${formatNumber(data.length)} values` +
      (unmeasured > 0 ? `, ${formatNumber(unmeasured)} not measured` : "") +
      `. Sample window: ${windowLabel}. Values are listed in the table that follows.`;

  const scaleChip =
    scale.kind === "log"
      ? "LOG SCALE"
      : scale.kind === "share-of-previous"
        ? "SHARE OF PREVIOUS STEP"
        : null;

  const body =
    typeof children === "function" ? (
      <svg
        role="img"
        aria-label={ariaLabel}
        viewBox={`0 0 ${geom.width} ${geom.height}`}
        width="100%"
        height={geom.height}
        preserveAspectRatio="xMidYMid meet"
        data-testid="chart-svg"
      >
        {(children as (g: PlotGeometry) => ReactNode)(geom)}
      </svg>
    ) : (
      <div role="img" aria-label={ariaLabel} data-testid="chart-plot">
        {children}
      </div>
    );

  return (
    <figure
      data-chart-frame=""
      data-motion={motion.enabled ? "on" : "off"}
      aria-labelledby={labelId}
      className={`m-0 flex w-full flex-col gap-3 ${className ?? ""}`.trim()}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3
            id={labelId}
            data-testid="chart-title"
            className="text-[15px] font-semibold tracking-[-0.01em] text-aether-text"
          >
            {title}
          </h3>
          {scaleChip ? (
            <span
              data-testid="scale-chip"
              className="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em]"
              style={{ border: `1px solid ${HAIRLINE_STRONG}`, color: STATE.neutral }}
            >
              {scaleChip}
            </span>
          ) : null}
          {scale.truncated ? (
            <span
              data-testid="axis-break"
              className="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em]"
              style={{ border: `1px solid ${HAIRLINE_STRONG}`, color: STATE.warn }}
              title="The value axis does not start at zero."
            >
              {`⤒ AXIS STARTS AT ${formatNumber(scale.baseline ?? 0)}`}
            </span>
          ) : null}
        </div>
        {action}
      </div>

      <div ref={containerRef} className="w-full">
        {body}
      </div>

      {legend}

      <figcaption className={`${META_TEXT_CLASS} flex flex-col gap-0.5`}>
        <span data-testid="window-label">{windowLabel}</span>
        {nullMeaning ? (
          <span data-testid="null-meaning">{`${NOT_MEASURED} = ${nullMeaning}`}</span>
        ) : null}
        {footnote ? <span data-testid="chart-footnote">{footnote}</span> : null}
      </figcaption>

      <DataTable
        title={title}
        windowLabel={windowLabel}
        data={data}
        nullMeaning={nullMeaning}
      />
    </figure>
  );
}
