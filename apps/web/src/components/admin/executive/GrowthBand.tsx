"use client";

/**
 * ADMIN-2.0 FE-1 — the executive dashboard's REVENUE & GROWTH band.
 *
 * Drawn with the repo's certified chart kit (`components/charts`) — no new
 * charting dependency, and `package.json` carries none to reuse. Every one of
 * the kit's five honest-rendering laws therefore applies here for free: a zero
 * is a hairline tick rather than a colour, an unmeasured interval is a gap
 * rather than a zero, the sample window is printed beside every mark, the
 * scale declares itself, and no meaning is carried by colour alone.
 *
 * ============================================================================
 * COUNTS ARE DRAWN; RATE READINGS ARE GATED
 * ============================================================================
 * BE-2 flags every block with `insufficientData` when its sample is below the
 * API's own threshold, and its docstring says exactly what that flag means:
 * "Small numbers are shown as they are; what is suppressed is the RATE-shaped
 * reading of them." These panels implement precisely that split. A trend panel
 * with six signups still DRAWS its six real daily counts — hiding them would
 * hide the truth — and carries a visible notice that the shape is not yet a
 * trend, with `data-trend-readable="false"` for a reviewer to assert on. The
 * funnel likewise always shows its stage COUNTS and gates only the shares.
 *
 * ============================================================================
 * THE FUNNEL IS NOT A NESTED FUNNEL
 * ============================================================================
 * `funnel.definitions._shape` states the stages are INDEPENDENT milestone
 * counts over one signup population, so a later stage may exceed an earlier
 * one. A step-to-step "60% dropped off" division would be a misreading of the
 * data it is drawn from. So every share here is taken against the SIGNUP
 * POPULATION — the API's own `shareOfSignups` — and the stage-to-stage figure
 * is a percentage-POINT difference between two such shares, labelled "pts vs
 * stage above". The API's own shape note is printed under the panel verbatim,
 * so the reader is told the same thing the maths assumes.
 */
import { Donut, Funnel, Spark, TrendLine, NOT_MEASURED } from "../../charts";
import type { AdminFunnelModel, PlanMixModel, SeriesModel } from "../../../lib/admin/executive";
import { formatAudTabular, formatCount, formatPct } from "../../../lib/admin/executive";
import { InsufficientData, Panel } from "./panels";

/** A visible notice that the COUNTS are real but a rate reading is not yet. */
function RateNotice({ reason }: { reason: string }) {
  return (
    <p
      data-testid="rate-not-readable"
      className="mb-3 rounded-lg border border-dashed border-white/10 bg-white/[0.015] px-3 py-2 text-[11px] leading-[1.45] text-aether-muted"
    >
      <span className="font-medium text-aether-text">Not enough data yet</span> to read a rate here.{" "}
      {reason}
    </p>
  );
}

export function GrowthFunnelPanel({ model }: { model: AdminFunnelModel }) {
  return (
    <Panel
      testId="admin-exec-funnel"
      measured={model.measured}
      title="Signup → paid milestones"
      caption={model.windowLabel}
    >
      {model.measured ? (
        <>
          {model.rate.readable ? null : <RateNotice reason={model.rate.reason ?? ""} />}
          <Funnel
            title="Signup → paid milestones"
            windowLabel={model.windowLabel}
            steps={model.steps.map((s) => ({ label: s.label, value: s.count, note: s.note }))}
            mode="linear"
            nullMeaning={model.nullMeaning}
          />

          <div
            className="mt-4 border-t border-white/[0.07] pt-3"
            data-testid="admin-exec-shares"
            data-trend-readable={model.rate.readable ? "true" : "false"}
          >
            <p className="type-section mb-2">Share of all signups</p>
            <ul className="flex flex-col gap-1.5">
              {model.steps.map((step, index) => {
                const shareShown = model.rate.readable && step.sharePct !== null;
                const deltaShown = model.rate.readable && step.shareDeltaPoints !== null;
                const steepest = deltaShown && step.key === model.steepestFallKey;
                return (
                  <li
                    key={step.key}
                    data-testid={`admin-exec-share-${step.key}`}
                    data-measured={shareShown ? "true" : "false"}
                    data-steepest={steepest ? "true" : undefined}
                    className="flex items-baseline justify-between gap-3 text-[12px]"
                  >
                    <span className="min-w-0 truncate text-aether-muted">{step.label}</span>
                    <span className="flex shrink-0 items-baseline gap-2">
                      {/* Only the biggest fall carries the warn tone, and it says
                          "biggest fall" in words too — colour is never the only
                          signal (C-5). */}
                      {steepest ? (
                        <span className="type-mono-micro rounded border border-aether-amber/40 px-1 py-px uppercase tracking-wide text-aether-amber">
                          biggest fall
                        </span>
                      ) : null}
                      <span
                        className="mono font-semibold tabular-nums"
                        style={shareShown ? undefined : { color: "#8B8BA3" }}
                        title={
                          shareShown
                            ? `${formatPct(step.sharePct as number)} of all signups reached this milestone`
                            : (model.rate.reason ?? step.note)
                        }
                      >
                        {shareShown ? formatPct(step.sharePct as number) : NOT_MEASURED}
                      </span>
                      <span
                        className="type-mono-micro w-28 text-right"
                        style={steepest ? { color: "#F59E0B" } : { color: "#8B8BA3" }}
                      >
                        {deltaShown
                          ? `${(step.shareDeltaPoints as number) > 0 ? "+" : "−"}${Math.abs(
                              step.shareDeltaPoints as number,
                            ).toFixed(1)} pts vs above`
                          : index === 0
                            ? "first milestone"
                            : "—"}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
            {model.shapeNote ? (
              <p
                data-testid="admin-exec-funnel-shape-note"
                className="type-meta mt-3 max-w-prose text-aether-muted-dim"
              >
                {model.shapeNote}
              </p>
            ) : null}
          </div>
        </>
      ) : (
        <InsufficientData
          reason={model.reason ?? "The funnel could not be measured."}
          nextStep="Milestones appear as accounts sign up, run an agent and submit an application."
        />
      )}
    </Panel>
  );
}

export function PlanMixPanel({ model }: { model: PlanMixModel }) {
  return (
    <Panel
      testId="admin-exec-plan-mix"
      measured={model.measured}
      title="Plan mix"
      caption={model.windowLabel}
    >
      {model.measured ? (
        <>
          <Donut
            title="Plan mix"
            windowLabel={model.windowLabel}
            segments={model.segments}
            nullMeaning={model.nullMeaning}
            centreLabel="subscribers"
          />
          <ul className="mt-3 flex flex-col gap-1">
            {model.segments.map((segment) => {
              const mrr = model.mrrByLabel[segment.label];
              return (
                <li
                  key={segment.label}
                  className="flex items-baseline justify-between gap-3 text-[12px] text-aether-muted"
                >
                  <span className="min-w-0 truncate">{segment.label}</span>
                  <span className="mono shrink-0 tabular-nums text-aether-muted-dim">
                    {typeof mrr === "number" ? formatAudTabular(mrr) : NOT_MEASURED} / month
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <InsufficientData
          reason={model.reason ?? "The plan mix could not be measured."}
          nextStep="A slice appears for each plan as soon as it has a Stripe-backed subscriber."
        />
      )}
    </Panel>
  );
}

export function SignupTrendPanel({ model }: { model: SeriesModel }) {
  return (
    <Panel
      testId="admin-exec-signup-trend"
      measured={model.measured}
      title="Signups by day"
      caption={model.windowLabel}
    >
      {model.measured ? (
        <div data-trend-readable={model.rate.readable ? "true" : "false"}>
          {model.rate.readable ? null : <RateNotice reason={model.rate.reason ?? ""} />}
          <TrendLine
            title="Signups by day"
            windowLabel={model.windowLabel}
            points={model.points}
            nullMeaning={model.nullMeaning}
            height={168}
            footnote={model.scopeNote ? `Excludes ${model.scopeNote}.` : undefined}
          />
          <p className="type-meta mt-2">
            {typeof model.total === "number"
              ? `${formatCount(model.total)} in the window.`
              : "Window total not reported."}
          </p>
        </div>
      ) : (
        <InsufficientData reason={model.reason ?? "Signups by day could not be measured."} />
      )}
    </Panel>
  );
}

export function RunVolumePanel({ model }: { model: SeriesModel }) {
  return (
    <Panel
      testId="admin-exec-run-volume"
      measured={model.measured}
      title="Agent run volume"
      caption={model.windowLabel}
    >
      {model.measured ? (
        <div data-trend-readable={model.rate.readable ? "true" : "false"}>
          <p className="mono text-[22px] font-semibold leading-none tabular-nums">
            {typeof model.total === "number" ? formatCount(model.total) : NOT_MEASURED}
          </p>
          <p className="type-meta mt-1">
            {typeof model.total === "number"
              ? "runs in the window"
              : "window run count not reported"}
          </p>
          <div className="mt-3">
            <Spark
              title="Agent runs by day"
              windowLabel={model.windowLabel}
              kind="bars"
              data={model.points}
              nullMeaning={model.nullMeaning}
              height={56}
            />
          </div>
          {model.scopeNote ? <p className="type-meta mt-2">Includes {model.scopeNote}.</p> : null}
        </div>
      ) : (
        <InsufficientData reason={model.reason ?? "Run volume could not be measured."} compact />
      )}
    </Panel>
  );
}
