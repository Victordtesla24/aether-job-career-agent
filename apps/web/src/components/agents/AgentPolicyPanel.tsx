"use client";

/**
 * "Agent Performance Policy" panel — U-AX build spec item 2(a).
 *
 * Renders the SAME deterministic rigor tier every real agent obeys
 * (`GET /analytics/agent-policy`, backed by
 * `app.services.quality_policy.resolve_policy_for_user`): the current tier,
 * WHICH metrics triggered it (conversion vs the 20% target, dimension scores
 * vs the 80% floor), and what the agents are doing differently at this tier.
 *
 * Honesty rules mirrored from the backend module this renders:
 * - `standard` never shows a trigger (there is none to show — the empty
 *   "why this tier" state below it, not a below-target/floor sentence).
 * - `insufficient_data` is a DISTINCT tier, never dressed up as "standard" or
 *   "healthy" — a user with too few submissions has no trustworthy rate.
 */
import type { AgentPolicy } from "../../lib/api/agentPolicy";

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

/**
 * Machine trigger strings (e.g. `conversion_below_20pct_target`,
 * `dimension_below_80pct_floor:cultureFit`) become readable copy without
 * touching letter casing — only separators become spaces — so dimension keys
 * such as `cultureFit` stay intact for anyone matching on them downstream.
 */
function humanizeTrigger(trigger: string): string {
  return trigger.replace(/[_:]+/g, " ").trim();
}

function formatConversion(rate: number): string {
  return `${Math.round(rate * 10) / 10}%`;
}

export default function AgentPolicyPanel({ policy }: { policy: AgentPolicy }) {
  const tierLabel = TIER_LABEL[policy.tier] ?? policy.tier;
  const tone = TIER_TONE[policy.tier] ?? "text-aether-muted-dim border-white/15";
  const snapshot = policy.metricSnapshot;
  const hasTriggers = policy.triggers.length > 0;

  return (
    <section
      className="glass rounded-2xl border border-white/10 p-5"
      data-testid="agent-policy-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted-dim">
            Agent Performance Policy
          </h2>
          <p className="mt-0.5 text-xs text-aether-muted-dim">
            The rigor tier every real agent is currently obeying — one computation,
            shown here and enforced on every run.
          </p>
        </div>
        <span
          data-testid="agent-policy-tier"
          className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${tone}`}
        >
          {tierLabel}
        </span>
      </div>

      {hasTriggers ? (
        <div className="mt-3" data-testid="agent-policy-triggers">
          <p className="text-xs font-semibold text-aether-muted-dim">Why this tier:</p>
          <ul className="mt-1 space-y-1 text-xs text-aether-muted">
            {policy.triggers.map((trigger, i) => (
              <li key={i} className="flex gap-1.5">
                <span className="text-aether-amber">•</span>
                <span>{humanizeTrigger(trigger)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : policy.tier === "standard" ? (
        <p className="mt-3 text-xs text-aether-muted-dim">
          No triggers — every measured threshold is currently being met.
        </p>
      ) : (
        <p className="mt-3 text-xs text-aether-muted-dim">No triggers recorded.</p>
      )}

      {policy.behaviour ? (
        <p className="mt-3 rounded-lg border border-white/10 bg-white/5 p-3 text-xs leading-relaxed text-aether-muted">
          {policy.behaviour}
        </p>
      ) : null}

      <dl className="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-aether-muted-dim">Sample size</dt>
          <dd className="mono font-semibold">{snapshot.sampleSize}</dd>
        </div>
        <div>
          <dt className="text-aether-muted-dim">Conversion rate</dt>
          <dd className="mono font-semibold">{formatConversion(snapshot.conversionRate)}</dd>
        </div>
        <div>
          <dt className="text-aether-muted-dim">Dimensions evaluated</dt>
          <dd className="mono font-semibold">{snapshot.dimensionsEvaluated ?? Object.keys(snapshot.dimensionScores).length}</dd>
        </div>
        <div>
          <dt className="text-aether-muted-dim">Measured</dt>
          <dd className="mono font-semibold">
            {snapshot.available === false ? (
              <span className="text-aether-amber" title={snapshot.unavailableReason ?? undefined}>
                unavailable
              </span>
            ) : (
              "yes"
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
}
