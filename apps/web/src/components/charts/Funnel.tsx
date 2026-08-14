"use client";

/**
 * `<Funnel>` (spec alias `<FunnelBars>`) — S-UI-REBUILD-SPEC §4.3 row 1.
 *
 * The funnel is where the product's numbers are least readable and most
 * dangerous: 8,358 → 287 → 0. On a linear scale the second bar is 3% of the
 * track and the third used to render as a filled coloured pill, which is a
 * picture of "a few" where the truth is "none".
 *
 * Three answers, all of them declared rather than implied:
 *   · `mode="linear"`            — honest but flat; the default.
 *   · `mode="log"`               — readable magnitudes, with a LOG SCALE chip.
 *   · `mode="share-of-previous"` — each bar is its share of the step above,
 *                                  with a chip saying exactly that (C-4).
 * The absolute numeral always sits OUTSIDE the fill in its own mono column, so
 * it is legible at every magnitude, and the conversion column carries the
 * percentage that the bar length alone could never prove.
 */
import { ZERO_TICK_WIDTH, barLength, formatNumber, formatPercent, NOT_MEASURED } from "./geometry";
import { ChartFrame } from "./ChartFrame";
import { EmptyPlot } from "./primitives";
import { useChartMotion } from "./motion";
import { CHART_PALETTE, HAIRLINE, STATE, TRACK } from "./tokens";
import type { ChartDatum } from "./types";

export interface FunnelStep {
  label: string;
  /** `null` = this stage was never measured. It is NOT zero. */
  value: number | null;
  /** Why it was not measured, or any qualifier — rendered verbatim. */
  note?: string;
  /** Pre-formatted numeral, when the caller owns the formatting. */
  display?: string;
}

export interface FunnelProps {
  title: string;
  /** C-3 — required. */
  windowLabel: string;
  steps: readonly FunnelStep[];
  mode?: "linear" | "log" | "share-of-previous";
  /** C-2 — required when the steps mix a real 0 with a null. */
  nullMeaning?: string;
  /** Rows drawn before the "N more" note. Everything stays in the data table. */
  maxRows?: number;
  footnote?: string;
  className?: string;
}

export function Funnel({
  title,
  windowLabel,
  steps,
  mode = "linear",
  nullMeaning,
  maxRows = 8,
  footnote,
  className,
}: FunnelProps) {
  const motion = useChartMotion();
  const data: ChartDatum[] = steps.map((step) => ({
    label: step.label,
    value: step.value,
    note: step.note,
    display: step.display,
  }));
  const max = Math.max(0, ...steps.map((s) => (typeof s.value === "number" ? s.value : 0)));
  const shown = steps.slice(0, maxRows);
  const withheld = steps.length - shown.length;

  return (
    <ChartFrame
      title={title}
      windowLabel={windowLabel}
      scale={{ kind: mode }}
      data={data}
      nullMeaning={nullMeaning}
      footnote={
        withheld > 0
          ? `${footnote ? `${footnote} · ` : ""}${formatNumber(withheld)} more ${
              withheld === 1 ? "step is" : "steps are"
            } listed in this chart's data table.`
          : footnote
      }
      className={className}
    >
      {steps.length === 0 ? (
        <EmptyPlot
          message="No funnel stages have been recorded yet."
          hint="Stages appear here as soon as the first job is scored."
        />
      ) : (
        <div className="flex flex-col gap-2" data-chart="funnel">
          {shown.map((step, index) => {
            const previous = index === 0 ? null : (shown[index - 1]?.value ?? null);
            const { kind, length } = barLength({
              value: step.value,
              max,
              extent: 100,
              mode,
              previous,
            });
            const conversion =
              index === 0
                ? ""
                : formatPercent(
                    typeof step.value === "number" ? step.value : null,
                    typeof previous === "number" ? previous : null,
                  );
            const numeral =
              kind === "unmeasured"
                ? NOT_MEASURED
                : (step.display ?? formatNumber(step.value as number));

            return (
              <div
                key={`${step.label}-${index}`}
                data-testid="funnel-row"
                data-step={step.label}
                className="flex items-center gap-3"
              >
                <span
                  className="w-24 shrink-0 truncate text-[13px] leading-[1.5] text-aether-muted sm:w-40"
                  title={step.label}
                >
                  {step.label}
                </span>

                <div
                  data-testid="funnel-track"
                  className="relative h-8 flex-1 overflow-hidden rounded-lg"
                  style={{ backgroundColor: TRACK }}
                >
                  {kind === "value" ? (
                    <div
                      data-testid="funnel-fill"
                      data-mark="value"
                      className="absolute inset-y-0 left-0 rounded-lg"
                      style={{
                        width: `${Math.round(length * 100) / 100}%`,
                        background: `linear-gradient(90deg, ${CHART_PALETTE[0]}B3, #7C3AEDB3)`,
                        transformOrigin: "left",
                        transform: motion.atOrigin ? "scaleX(0)" : undefined,
                        transition: motion.transition("transform"),
                      }}
                    />
                  ) : null}
                  {kind === "zero" ? (
                    <div
                      data-mark="zero"
                      data-tone="neutral"
                      title={`${step.label}: 0`}
                      className="absolute inset-y-1 left-0"
                      style={{ width: `${ZERO_TICK_WIDTH}px`, backgroundColor: HAIRLINE }}
                    />
                  ) : null}
                  {kind === "unmeasured" ? (
                    <span
                      data-mark="unmeasured"
                      data-tone="neutral"
                      title={step.note ?? nullMeaning ?? "not measured"}
                      className="absolute left-2 top-1/2 -translate-y-1/2 font-mono text-[12px]"
                      style={{ color: STATE.neutral }}
                    >
                      {NOT_MEASURED}
                    </span>
                  ) : null}
                </div>

                <span
                  data-testid="funnel-value"
                  data-tone={kind === "value" ? "series" : "neutral"}
                  className="w-16 shrink-0 text-right font-mono text-[13px] tabular-nums sm:w-20"
                  style={{ color: kind === "value" ? undefined : STATE.neutral }}
                >
                  {numeral}
                </span>

                {/* The conversion % is a truth column, not a desktop luxury: it
                    narrows at 390px, it never disappears. */}
                <span
                  data-testid="funnel-conversion"
                  className="w-12 shrink-0 text-right text-[11px] text-aether-muted-dim sm:w-28"
                  title={index === 0 ? undefined : "share of the step above"}
                >
                  {conversion}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </ChartFrame>
  );
}

/** Spec name (S-UI-REBUILD-SPEC §4.3) for the same component. */
export { Funnel as FunnelBars };
