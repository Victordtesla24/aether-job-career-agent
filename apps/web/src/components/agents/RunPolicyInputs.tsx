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

/**
 * PRESENTATION VARIANT (S-UI aesthetics slice — no fact changes).
 *
 * `variant="block"` (the default) is the original rendition, byte-for-byte.
 *
 * `variant="row"` is for a dense table cell: the SAME sentences, clamped to
 * one line inside a native `<details>` disclosure. Nothing is deleted,
 * reworded or hidden — the full text is always in the DOM (so `textContent`,
 * screen readers, find-in-page and every existing assertion see it unchanged),
 * always in the `title` attribute, and one click from being fully legible.
 * This is the SUI1-P1 density fix: unclamped, this cell alone made every
 * Recent-Runs row 359px tall (measured), against a 28–48px reference band.
 */
export type RunPolicyVariant = "block" | "row";

export default function RunPolicyInputs({
  run,
  variant = "block",
}: {
  run: AgentRun;
  variant?: RunPolicyVariant;
}) {
  const qp = readQualityPolicy(run);
  const tier = typeof qp?.tier === "string" ? qp.tier : null;

  if (!qp || tier === null) {
    const notRecorded =
      "Policy inputs consumed: not recorded — this run predates rigor-policy instrumentation.";
    if (variant === "row") {
      return (
        <details className="ag-disc text-[11px] text-aether-muted-dim" data-testid="run-policy-inputs">
          <summary title={notRecorded}>
            <i className="ag-disc-caret fa-solid fa-chevron-right" aria-hidden="true" />
            <span className="ag-disc-line">{notRecorded}</span>
          </summary>
        </details>
      );
    }
    return (
      <p className="text-xs text-aether-muted-dim" data-testid="run-policy-inputs">
        {notRecorded}
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
  const triggerText =
    triggers.length > 0
      ? `Trigger: ${triggers.map((t) => String(t).replace(/[_:]+/g, " ")).join("; ")}`
      : null;

  const headline = (
    <>
      <span className="font-semibold text-aether-muted-dim">Policy inputs consumed:</span>{" "}
      tier <span className="font-semibold">{tier}</span>
      {sampleSize !== null ? ` · sample size ${sampleSize}` : ""}
      {conversionPct !== null ? ` · conversion ${conversionPct}` : ""}
    </>
  );

  if (variant === "row") {
    const headlineText =
      `Policy inputs consumed: tier ${tier}` +
      (sampleSize !== null ? ` · sample size ${sampleSize}` : "") +
      (conversionPct !== null ? ` · conversion ${conversionPct}` : "");
    return (
      <details className="ag-disc text-[11px] text-aether-muted" data-testid="run-policy-inputs">
        <summary title={triggerText ? `${headlineText}\n${triggerText}` : headlineText}>
          <i className="ag-disc-caret fa-solid fa-chevron-right" aria-hidden="true" />
          <span className="ag-disc-line">{headline}</span>
        </summary>
        {triggerText ? (
          <p className="ag-disc-more text-aether-muted-dim">{triggerText}</p>
        ) : null}
      </details>
    );
  }

  return (
    <div className="text-xs text-aether-muted" data-testid="run-policy-inputs">
      <p>{headline}</p>
      {triggerText ? <p className="mt-0.5 text-aether-muted-dim">{triggerText}</p> : null}
    </div>
  );
}
