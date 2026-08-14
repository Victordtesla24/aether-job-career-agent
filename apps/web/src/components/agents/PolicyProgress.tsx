"use client";

/**
 * The two U-AX spec surfaces round 2 left undelivered (R-06), re-expressed as
 * VISUALS for ANALYTICS-VIZ.
 *
 * (a) **Policy tier over time vs the metrics it responds to** — U-PLAN.md
 *     U-AX BUILD SPEC ADDITIONS item 2(c). Every point here is a tier an agent
 *     ACTUALLY obeyed, read from `AgentRun.policyTier` /
 *     `AgentRun.metricSnapshot` — not a reconstruction of what the policy would
 *     say today.
 * (b) **Interview-conversion progress per policy-tier cohort** — item 3
 *     ("applications under each policy tier"), reading the previously
 *     write-only `Application.policyTierAtSubmission`. This is what turns the
 *     rigor loop from a claim into a measurement: if heightened rigor works,
 *     its cohort converts better; if it does not, that is visible here too.
 *
 * WHY THESE ARE NOW CHARTS. Round 3 deliberately shipped both as lists, on the
 * argument that "two or three tier points over a few weeks is a short ordered
 * list, and drawing a LINE through them would imply a continuity the data does
 * not have". That argument was right about the line and wrong about the
 * picture. `<TierBand>` draws no line: it partitions the band by RUNS, which
 * is a measured quantity that exists at every point, and leaves the irregular
 * dates as labels rather than as an axis. `<BulletChart>` draws each cohort
 * against the target it is judged by, which is the comparison the reader was
 * previously asked to perform in their head from a paragraph.
 *
 * The tier-point LIST is kept beneath the band, unchanged, because it carries
 * per-point detail (dimensions at or below floor) at a fidelity a 9px band
 * segment cannot, and because it is what `__tests__/policy-progress.test.tsx`
 * pins as this panel's honesty contract.
 */
import { BulletChart, TierBand, type BulletRow } from "../charts";
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
  const untracked = history.runsWithoutPolicy;
  return (
    <section
      className="glass rounded-2xl border border-white/10 p-5"
      data-testid="policy-tier-history"
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted-dim">
        Policy tier over time
      </h2>

      <div className="mt-3">
        <TierBand
          title="Tier bands, sized by the runs that obeyed them"
          windowLabel="all-time — every recorded tier point, oldest first"
          points={history.points}
          target={target}
          tierLabels={TIER_LABEL}
          emptyMessage={history.reason ?? "No policy history recorded yet."}
          emptyHint={
            untracked > 0
              ? `${untracked} earlier run${
                  untracked === 1 ? "" : "s"
                } predate this instrumentation and carry no tier — they are not back-filled with today's verdict.`
              : undefined
          }
          footnote={
            untracked > 0
              ? `${untracked} earlier run${
                  untracked === 1 ? "" : "s"
                } recorded no tier (they predate this instrumentation) and are excluded rather than guessed.`
              : undefined
          }
        />
      </div>

      {history.points.length > 0 ? (
        /*
          D-ε ("the page ends"): this list grows one row per recorded tier
          point and had no bound. Scroll containment, not truncation — every
          point stays in the DOM and reachable. The band above now carries the
          shape, so the list needs less of the page than it did: 16rem instead
          of 26rem.
        */
        <ol className="mt-4 max-h-[16rem] space-y-2 overflow-y-auto pr-1">
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
      ) : null}
    </section>
  );
}

export function PolicyCohortProgress({ cohorts }: { cohorts: PolicyCohorts }) {
  const rows: BulletRow[] = cohorts.cohorts.map((cohort) => ({
    label: TIER_LABEL[cohort.tier] ?? cohort.tier,
    value: cohort.conversionRate ?? null,
    display:
      cohort.conversionRate === null || cohort.conversionRate === undefined
        ? undefined
        : pct(cohort.conversionRate),
    basis: `${cohort.interviewed} interview${
      cohort.interviewed === 1 ? "" : "s"
    } from ${cohort.submitted} submitted`,
    // A withheld rate keeps its reason ON the row — the same words the list
    // used, so "we will not print a rate from 3 submissions" survives the
    // move from prose to chart intact.
    note:
      cohort.conversionRate === null || cohort.conversionRate === undefined
        ? `not enough data yet — at least ${cohorts.minSampleSize} submissions are needed before a rate means anything`
        : undefined,
    testId: `policy-cohort-${cohort.tier}`,
    trailing:
      cohort.conversionRate === null || cohort.conversionRate === undefined ? null : (
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
            cohort.meetsTarget
              ? "border-aether-green/40 text-aether-green"
              : "border-aether-amber/40 text-aether-amber"
          }`}
        >
          {cohort.meetsTarget
            ? `at or above the ${pct(cohorts.target)} target`
            : `${pct(cohort.gapPoints ?? 0)} to go`}
        </span>
      ),
  }));

  /**
   * The denominator ribbon. Every tier's submissions, plus the ones that
   * predate the instrumentation drawn as their own hatched segment — which is
   * how "these rates describe 27 of 317 applications" becomes a proportion you
   * can see rather than a sentence you might skip.
   */
  const coverage = [
    ...cohorts.cohorts.map((cohort) => ({
      label: TIER_LABEL[cohort.tier] ?? cohort.tier,
      count: cohort.submitted,
      kind: "attributed" as const,
    })),
    ...(cohorts.untagged.submitted > 0
      ? [
          {
            label: "No tier recorded",
            count: cohorts.untagged.submitted,
            kind: "unattributed" as const,
          },
        ]
      : []),
  ];

  return (
    <section
      className="glass rounded-2xl border border-white/10 p-5"
      data-testid="policy-cohorts"
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted-dim">
        Interview conversion by policy tier
      </h2>

      <div className="mt-3">
        <BulletChart
          title="Each tier's cohort against the target"
          windowLabel="all-time — applications grouped by the tier they were submitted under"
          rows={rows}
          target={{ value: cohorts.target, label: `${pct(cohorts.target)} target` }}
          coverage={coverage}
          emptyMessage="No application has been submitted under a recorded policy tier yet."
          emptyHint="Cohorts appear here as soon as one submission carries a recorded tier."
        />
      </div>

      {cohorts.untagged.submitted > 0 ? (
        <p
          data-prose="caption"
          className="mt-2 text-[11px] leading-[1.45] text-aether-muted-dim"
          data-testid="policy-cohort-untagged"
        >
          {`${cohorts.untagged.submitted} not creditable to any tier${
            cohorts.untagged.interviewed > 0
              ? `, including ${cohorts.untagged.interviewed} interview${
                  cohorts.untagged.interviewed === 1 ? "" : "s"
                }`
              : ""
          } — ${
            cohorts.untagged.reason ?? "submitted before the rigor policy was instrumented"
          }.`}
        </p>
      ) : null}
    </section>
  );
}
