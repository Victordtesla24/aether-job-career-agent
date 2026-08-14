"use client";

/**
 * The two U-AX spec surfaces round 2 left undelivered (R-06).
 *
 * (a) **Policy tier over time vs the metrics it responds to** — U-PLAN.md
 *     U-AX BUILD SPEC ADDITIONS item 2(c). Round 2 shipped only the CURRENT
 *     tier while labelling its panel "item 2(a)/(c)". Every point here is a
 *     tier an agent ACTUALLY obeyed, read from `AgentRun.policyTier` /
 *     `AgentRun.metricSnapshot` — not a reconstruction of what the policy
 *     would say today.
 * (b) **Interview-conversion progress per policy-tier cohort** — item 3
 *     ("applications under each policy tier"), reading the previously
 *     write-only `Application.policyTierAtSubmission`. This is what turns the
 *     rigor loop from a claim into a measurement: if heightened rigor works,
 *     its cohort converts better; if it does not, that is visible here too.
 *
 * Deliberately NOT a chart. Two or three tier points over a few weeks is a
 * short ordered list, and drawing a line through them would imply a
 * continuity the data does not have (points are irregular — they exist only
 * where the tier or its inputs changed). Both panels degrade to a stated
 * reason rather than an empty axis.
 */
import type { PolicyCohorts, PolicyHistory } from "../../lib/api/agentPolicy";

const TIER_LABEL: Record<string, string> = {
  standard: "Standard rigor",
  heightened: "Heightened rigor",
  insufficient_data: "Insufficient data",
};

const TIER_TONE: Record<string, string> = {
  standard: "text-aether-green border-aether-green/40",
  heightened: "text-aether-amber border-aether-amber/40",
  insufficient_data: "text-aether-muted-dim border-white/15",
};

function tierBadge(tier: string) {
  return (
    <span
      className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        TIER_TONE[tier] ?? "text-aether-muted-dim border-white/15"
      }`}
    >
      {TIER_LABEL[tier] ?? tier}
    </span>
  );
}

function formatWhen(at: string | null | undefined): string {
  if (!at) return "date not recorded";
  const parsed = new Date(at);
  if (Number.isNaN(parsed.getTime())) return "date not recorded";
  return parsed.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function pct(value: number): string {
  return `${Math.round(value * 100) / 100}%`;
}

export function PolicyTierHistory({ history }: { history: PolicyHistory }) {
  const target = history.thresholds?.interviewConversionTarget ?? 20;
  return (
    <section
      className="glass rounded-2xl border border-white/10 p-5"
      data-testid="policy-tier-history"
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted-dim">
        Policy tier over time
      </h2>
      <p className="mt-0.5 text-xs text-aether-muted-dim">
        Every tier an agent actually ran under, next to the measurements that
        forced it. Unchanged runs are grouped — a flat stretch reads as flat.
      </p>

      {history.points.length === 0 ? (
        <p className="mt-3 rounded-xl border border-white/10 p-3 text-xs text-aether-muted-dim">
          {history.reason ?? "No policy history recorded yet."}
          {history.runsWithoutPolicy > 0 ? (
            <>
              {" "}
              {history.runsWithoutPolicy} earlier run
              {history.runsWithoutPolicy === 1 ? "" : "s"} predate this
              instrumentation and carry no tier — they are not back-filled with
              today&apos;s verdict.
            </>
          ) : null}
        </p>
      ) : (
        <>
          <ol className="mt-3 space-y-2">
            {history.points.map((point, index) => (
              <li
                key={`${point.at ?? "unknown"}-${index}`}
                data-testid="policy-tier-history-point"
                className="rounded-xl border border-white/10 p-3 text-xs"
              >
                <div className="flex flex-wrap items-center gap-2">
                  {tierBadge(point.tier)}
                  <span className="text-aether-muted">{formatWhen(point.at)}</span>
                  <span className="text-aether-muted-dim">
                    · {point.runs} run{point.runs === 1 ? "" : "s"}
                  </span>
                </div>
                <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-aether-muted-dim">
                  <div className="flex gap-1">
                    <dt>Interview conversion</dt>
                    <dd className="mono text-aether-muted">{pct(point.conversionRate)}</dd>
                    <dd>vs {pct(target)} target</dd>
                  </div>
                  <div className="flex gap-1">
                    <dt>Submissions measured</dt>
                    <dd className="mono text-aether-muted">{point.sampleSize}</dd>
                  </div>
                  {point.dimensionsBelowFloor.length > 0 ? (
                    <div className="flex gap-1">
                      <dt>Dimensions at/below floor</dt>
                      <dd className="text-aether-muted">
                        {point.dimensionsBelowFloor.join(", ")}
                      </dd>
                    </div>
                  ) : null}
                </dl>
              </li>
            ))}
          </ol>
          {history.runsWithoutPolicy > 0 ? (
            <p className="mt-2 text-[11px] text-aether-muted-dim">
              {history.runsWithoutPolicy} earlier run
              {history.runsWithoutPolicy === 1 ? "" : "s"} recorded no tier (they
              predate this instrumentation) and are excluded rather than guessed.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

export function PolicyCohortProgress({ cohorts }: { cohorts: PolicyCohorts }) {
  const rows = cohorts.cohorts;
  return (
    <section
      className="glass rounded-2xl border border-white/10 p-5"
      data-testid="policy-cohorts"
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted-dim">
        Interview conversion by policy tier
      </h2>
      <p className="mt-0.5 text-xs text-aether-muted-dim">
        Applications grouped by the rigor tier they were submitted under, each
        against the {pct(cohorts.target)} (1-in-5) target. This is how you can
        tell whether escalating rigor is actually working.
      </p>

      {rows.length === 0 ? (
        <p className="mt-3 rounded-xl border border-white/10 p-3 text-xs text-aether-muted-dim">
          No application has been submitted under a recorded policy tier yet.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {rows.map((cohort) => (
            <li
              key={cohort.tier}
              data-testid={`policy-cohort-${cohort.tier}`}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 p-3 text-xs"
            >
              <div className="flex flex-wrap items-center gap-2">
                {tierBadge(cohort.tier)}
                <span className="text-aether-muted">
                  {cohort.interviewed} interview
                  {cohort.interviewed === 1 ? "" : "s"} from {cohort.submitted}{" "}
                  submitted
                </span>
              </div>
              {cohort.conversionRate === null || cohort.conversionRate === undefined ? (
                <span className="text-right text-aether-muted-dim">
                  <span className="mono mr-1 text-base font-bold">—</span>
                  not enough data yet — at least {cohorts.minSampleSize} submissions
                  are needed before a rate means anything
                </span>
              ) : (
                <span className="text-right">
                  <span
                    className={`mono text-base font-bold ${
                      cohort.meetsTarget ? "text-aether-green" : "text-aether-amber"
                    }`}
                  >
                    {pct(cohort.conversionRate)}
                  </span>
                  <span className="ml-1 text-aether-muted-dim">
                    {cohort.meetsTarget
                      ? `at or above the ${pct(cohorts.target)} target`
                      : `${pct(cohort.gapPoints ?? 0)} to go`}
                  </span>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {cohorts.untagged.submitted > 0 ? (
        <p
          className="mt-2 rounded-xl border border-white/10 p-3 text-[11px] text-aether-muted-dim"
          data-testid="policy-cohort-untagged"
        >
          {cohorts.untagged.submitted} further submitted application
          {cohorts.untagged.submitted === 1 ? " was" : "s were"}{" "}
          {cohorts.untagged.reason ??
            "submitted before the rigor policy was instrumented"}
          , so {cohorts.untagged.submitted === 1 ? "its" : "their"} outcome
          {cohorts.untagged.interviewed > 0
            ? ` (${cohorts.untagged.interviewed} interview${
                cohorts.untagged.interviewed === 1 ? "" : "s"
              })`
            : ""}{" "}
          cannot honestly be credited to any tier.
        </p>
      ) : null}
    </section>
  );
}
