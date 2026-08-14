"use client";

/**
 * Per-run "policy inputs consumed" — U-AX build spec item 2(b) / item 5.
 *
 * Every tailor/cover (and, per item 5, every real agent's) run stamps the
 * SAME object it obeyed onto `AgentRun.input.qualityPolicy`
 * (`apps/api/app/routers/agents.py::_with_quality_policy`): the resolved
 * `resolve_policy_for_user()` result, `{tier, triggers, metrics, ...}`. A run
 * recorded before this instrumentation existed carries no `qualityPolicy` key
 * at all — this component says so honestly ("not recorded") rather than
 * rendering a fabricated tier for it.
 *
 * Reads `metricSnapshot` OR `metrics` (the raw stamped key on `AgentRun.input`
 * is `metrics`; `metricSnapshot` is accepted too so a caller feeding the
 * `/analytics/agent-policy` shape works unchanged) — never invents whichever
 * is absent.
 */
import type { AgentRun } from "../../lib/api/agents";

interface QualityPolicySnapshot {
  tier?: unknown;
  triggers?: unknown;
  metricSnapshot?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readQualityPolicy(run: AgentRun): QualityPolicySnapshot | null {
  const input = run.input as { qualityPolicy?: unknown } | null | undefined;
  const qp = input?.qualityPolicy;
  return qp && typeof qp === "object" ? (qp as QualityPolicySnapshot) : null;
}

export default function RunPolicyInputs({ run }: { run: AgentRun }) {
  const qp = readQualityPolicy(run);
  const tier = typeof qp?.tier === "string" ? qp.tier : null;

  if (!qp || tier === null) {
    return (
      <p className="text-xs text-aether-muted-dim" data-testid="run-policy-inputs">
        Policy inputs consumed: not recorded — this run predates rigor-policy
        instrumentation.
      </p>
    );
  }

  // The raw AgentRun.input.qualityPolicy.metrics conversion rate is a
  // FRACTION (0.2 == 20%, `app.services.quality_policy.collect_policy_metrics`);
  // this component reads that raw stamp, so it always converts to a percentage
  // for display rather than trusting an ambiguous magnitude.
  const snapshot = qp.metricSnapshot ?? qp.metrics ?? {};
  const sampleSize = asNumber(snapshot.sampleSize);
  const conversionFraction = asNumber(snapshot.conversionRate);
  const conversionPct =
    conversionFraction !== null ? `${Math.round(conversionFraction * 1000) / 10}%` : null;
  const triggers = Array.isArray(qp.triggers) ? (qp.triggers as unknown[]) : [];

  return (
    <div className="text-xs text-aether-muted" data-testid="run-policy-inputs">
      <p>
        <span className="font-semibold text-aether-muted-dim">Policy inputs consumed:</span>{" "}
        tier <span className="font-semibold">{tier}</span>
        {sampleSize !== null ? ` · sample size ${sampleSize}` : ""}
        {conversionPct !== null ? ` · conversion ${conversionPct}` : ""}
      </p>
      {triggers.length > 0 ? (
        <p className="mt-0.5 text-aether-muted-dim">
          Trigger: {triggers.map((t) => String(t).replace(/[_:]+/g, " ")).join("; ")}
        </p>
      ) : null}
    </div>
  );
}
