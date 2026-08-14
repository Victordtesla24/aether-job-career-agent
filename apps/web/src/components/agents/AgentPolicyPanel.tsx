"use client";

/**
 * "Agent Performance Policy" panel — U-AX build spec item 2(a), re-expressed
 * as a VISUAL for ANALYTICS-VIZ.
 *
 * It renders the SAME deterministic rigor tier every real agent obeys
 * (`GET /analytics/agent-policy`, backed by
 * `app.services.quality_policy.resolve_policy_for_user`): the current tier,
 * WHICH metrics triggered it (conversion vs the 20% target, dimension scores
 * vs the 80% floor), and what the agents are doing differently at this tier.
 *
 * WHAT CHANGED, AND WHAT DID NOT (ANALYTICS-VIZ). The panel used to answer
 * those three questions in prose: a subtitle sentence, a bulleted list of
 * trigger sentences, and a 290-character paragraph of server copy describing
 * the tier's behaviour. Every one of those facts is still here and still
 * sourced from the same field — they are now a LADDER (where this tier sits
 * among the three the backend can resolve), CHIPS (one per trigger, one per
 * knob the tier actually changed) and a BULLET CHART (each evaluated dimension
 * against the 80% floor that is what "below floor" means). Nothing was
 * paraphrased and nothing was dropped: the two strings that are the server's
 * own honesty copy — `behaviour`, and the reason a snapshot is unavailable —
 * are rendered VERBATIM as captions attached to the visual they qualify.
 *
 * Honesty rules mirrored from the backend module this renders:
 * - `standard` never shows a trigger (there is none to show — the empty
 *   "why this tier" state below it, not a below-target/floor sentence).
 * - `insufficient_data` is a DISTINCT tier, never dressed up as "standard" or
 *   "healthy" — a user with too few submissions has no trustworthy rate.
 */
import { BulletChart, type BulletRow } from "../charts";
import type { AgentDirective, AgentPolicy } from "../../lib/api/agentPolicy";

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
 * The three states `resolve_policy_for_user` can return, in the order a search
 * moves through them: too little evidence to judge → judged and meeting the
 * thresholds → judged and escalated. Drawing them as a ladder is what makes
 * "which of the three is this, and what is on either side of it" answerable
 * without reading a definition.
 */
const TIER_LADDER = ["insufficient_data", "standard", "heightened"] as const;

const LADDER_TONE: Record<string, { fill: string; text: string }> = {
  insufficient_data: { fill: "bg-white/15", text: "text-aether-muted-dim" },
  standard: { fill: "bg-aether-green/60", text: "text-aether-green" },
  heightened: { fill: "bg-aether-amber/70", text: "text-aether-amber" },
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

/** A finite number out of the API's permissive `thresholds` bag, or `null`.
 *  The schema keeps unknown server keys rather than asserting a shape, so the
 *  value genuinely is `unknown` here — coercing it would turn a missing floor
 *  into `NaN` and draw a target tick nobody set. */
function thresholdNumber(bag: Record<string, unknown> | null | undefined, key: string): number | null {
  const value = bag?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The knobs the tier actually changed, as chips. Only entries the server sent
 *  as a number or a string are rendered — an object-valued knob is not
 *  stringified into something that looks like a setting. */
const KNOB_LABEL: Record<string, string> = {
  maxIterations: "scoring iterations",
  targetScore: "ATS target",
  coverLetterRetries: "cover-letter retries",
};

function knobChips(knobs: Record<string, unknown> | null | undefined) {
  if (!knobs) return [];
  return Object.entries(knobs)
    .filter(([, value]) => typeof value === "number" || typeof value === "string")
    .map(([key, value]) => ({
      key,
      label: KNOB_LABEL[key] ?? key,
      value: String(value),
    }));
}

/**
 * B1b (ADR-AGI-2 P1, ORCH-B1-BLUEPRINT-2026-08-14.md §8.1) — "Supervisor
 * directives" block. A directive AMENDS the tier's baseline for one agent;
 * it is never shown AS the tier (§8's honesty rule), so every knob it
 * touches is rendered beside the tier's own baseline value for that same
 * field, sourced from `policy.knobs` — the one computation this panel
 * already renders above, never a re-derived number.
 */
const DIRECTIVE_AGENT_LABEL: Record<string, string> = {
  tailor: "Résumé Tailoring",
  coverLetter: "Cover Letter",
  storyExtractor: "Story Extraction",
};

function directiveKnobPhrases(
  directive: Record<string, unknown>,
  baselineKnobs: Record<string, unknown> | null | undefined,
): string[] {
  return Object.entries(directive)
    .filter(([, value]) => typeof value === "number" || typeof value === "string")
    .map(([key, value]) => {
      const label = KNOB_LABEL[key] ?? key;
      const baseline = baselineKnobs?.[key];
      const hasBaseline = typeof baseline === "number" || typeof baseline === "string";
      return `${value} ${label}${hasBaseline ? ` (baseline ${String(baseline)})` : ""}`;
    });
}

export default function AgentPolicyPanel({
  policy,
  directives = [],
  directivesPaused = false,
}: {
  policy: AgentPolicy;
  /** Active `AgentDirective` rows for this user, from `GET /agents/directives`
   *  (§5.2). Additive and optional: a caller that has not wired the fetch yet
   *  (or the fetch itself failed — additive endpoints degrade to absent, not
   *  to a blanked panel) simply omits this and the panel renders exactly as
   *  it did before B1b. */
  directives?: AgentDirective[];
  /** `GET /agents/directives`'s own `paused` flag (reflects
   *  `AETHER_AGI_DIRECTIVES_ENABLED`) — directives may still be LISTED while
   *  paused (history is never a lie); this only changes how they are
   *  captioned. */
  directivesPaused?: boolean;
}) {
  const tierLabel = TIER_LABEL[policy.tier] ?? policy.tier;
  const tone = TIER_TONE[policy.tier] ?? "text-aether-muted-dim border-white/15";
  const snapshot = policy.metricSnapshot;
  const hasTriggers = policy.triggers.length > 0;
  const knobs = knobChips(policy.knobs);
  const floor = thresholdNumber(policy.thresholds, "dimensionFloor") ?? 80;

  const dimensionRows: BulletRow[] = Object.entries(snapshot.dimensionScores).map(
    ([label, score]) => ({
      label,
      value: score,
      display: `${Math.round(score * 10) / 10}`,
    }),
  );

  return (
    <section
      className="glass rounded-2xl border border-white/10 p-5"
      data-testid="agent-policy-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-aether-muted-dim">
          Agent Performance Policy
          {/* F-UAX-04: this panel's metrics are computed ALL-TIME
              (quality_policy.resolve_policy_for_user has no period filter),
              which can legitimately disagree with any period-filtered
              figure shown elsewhere on the page — label the window so the
              two are never read as the same measurement. */}
          <span
            className="ml-1.5 align-middle text-[10px] font-normal normal-case text-aether-muted-dim"
            data-testid="agent-policy-window"
          >
            (all-time)
          </span>
        </h2>
        <span
          data-testid="agent-policy-tier"
          className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${tone}`}
        >
          {tierLabel}
        </span>
      </div>

      {/* THE LADDER — where this tier sits among the three the backend can
          resolve. The current stop is filled and named; the others stay
          visible and named so the reader can see what "next" would mean. */}
      <ol className="mt-4 flex gap-1.5" data-testid="agent-policy-ladder" aria-label="Rigor ladder">
        {TIER_LADDER.map((tier) => {
          const active = tier === policy.tier;
          const palette = LADDER_TONE[tier];
          return (
            <li
              key={tier}
              data-testid={`agent-policy-ladder-${tier}`}
              data-active={active ? "true" : "false"}
              aria-current={active ? "step" : undefined}
              className="min-w-0 flex-1"
            >
              <span
                aria-hidden="true"
                className={`block h-1.5 w-full rounded-full ${
                  active ? palette.fill : "bg-white/[0.06]"
                }`}
              />
              <span
                className={`mt-1.5 block truncate text-[10px] font-semibold uppercase tracking-[0.05em] ${
                  active ? palette.text : "text-aether-muted-dim/60"
                }`}
              >
                {TIER_LABEL[tier]}
              </span>
            </li>
          );
        })}
      </ol>
      <p data-prose="caption" className="mt-2 text-[11px] leading-[1.4] text-aether-muted-dim">
        One computation — shown here and enforced on every agent run.
      </p>

      {/* WHY THIS TIER — one chip per trigger the backend actually recorded.
          The container is always present so an empty state is a stated empty
          state, never a missing region. */}
      <div className="mt-4" data-testid="agent-policy-triggers">
        <h3 className="type-mono-micro text-aether-muted-dim">Why this tier</h3>
        {/* D-ε ("the page ends"): a real account carries nine triggers, one
            per dimension at or below the floor, and each is a full server
            sentence — five rows of chips before the panel's own charts begin.
            The doctrine's remedy is scroll containment, not truncation: every
            trigger stays in the DOM, reachable and readable, inside its own
            two-row box. The dimension chart below draws the same nine
            measurements against the same floor. */}
        <ul className="mt-1.5 flex max-h-[4.75rem] flex-wrap gap-1.5 overflow-y-auto">
          {hasTriggers ? (
            policy.triggers.map((trigger, i) => (
              <li
                key={i}
                data-testid="agent-policy-trigger-chip"
                className="flex items-center gap-1.5 rounded-full border border-aether-amber/30 bg-aether-amber/[0.08] px-2.5 py-1 text-[11px] text-aether-amber"
              >
                <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-aether-amber" />
                {humanizeTrigger(trigger)}
              </li>
            ))
          ) : (
            <li className="rounded-full border border-white/10 px-2.5 py-1 text-[11px] text-aether-muted-dim">
              {policy.tier === "standard"
                ? "No trigger fired — every measured threshold is being met"
                : "No trigger recorded"}
            </li>
          )}
        </ul>
      </div>

      {/* WHAT THE AGENTS DO DIFFERENTLY — the tier's knobs as chips, with the
          server's own sentence kept verbatim beneath them as the caption that
          qualifies them. */}
      {knobs.length > 0 ? (
        <ul className="mt-4 flex flex-wrap gap-1.5" data-testid="agent-policy-knobs">
          {knobs.map((knob) => (
            <li
              key={knob.key}
              className="flex items-baseline gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1"
            >
              <span className="mono text-[13px] font-semibold tabular-nums">{knob.value}</span>
              <span className="text-[11px] text-aether-muted-dim">{knob.label}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {policy.behaviour ? (
        <p
          data-prose="caption"
          data-prose-source="server"
          data-testid="agent-policy-behaviour"
          className="mt-2 text-[11px] leading-[1.45] text-aether-muted-dim"
        >
          {policy.behaviour}
        </p>
      ) : null}

      {/* SUPERVISOR DIRECTIVES (B1b, §8.1) — bounded amendments on top of the
          tier above. Absent entirely when there are none: an empty region is
          never rendered as a stated empty state here, because "the
          Supervisor issued nothing" is the default, unremarkable case, not a
          fact worth a dedicated row the way "no trigger fired" is. */}
      {directives.length > 0 ? (
        <div
          className={`mt-4 rounded-xl border p-3 ${
            directivesPaused
              ? "border-white/10 bg-white/[0.02] opacity-70"
              : "border-aether-amber/25 bg-aether-amber/[0.05]"
          }`}
          data-testid="agent-policy-directives"
          data-paused={directivesPaused ? "true" : "false"}
        >
          <h3 className="type-mono-micro text-aether-muted-dim">
            Supervisor directive{directives.length === 1 ? "" : "s"} ({directives.length}{" "}
            active)
          </h3>
          <p data-prose="caption" className="mt-1 text-[11px] leading-[1.4] text-aether-muted-dim">
            {directivesPaused
              ? "Not currently applied — directive issuance is paused."
              : "The tier above is the baseline; these tighten it further."}
          </p>
          <ul className="mt-2 space-y-2">
            {directives.map((directive) => {
              const phrases = directiveKnobPhrases(directive.directive, policy.knobs);
              const clampedEntries = Object.entries(directive.clamped ?? {});
              return (
                <li key={directive.id} data-testid="agent-policy-directive-row" className="text-[12px]">
                  <span className="font-semibold text-aether-muted">
                    {DIRECTIVE_AGENT_LABEL[directive.agentKey] ?? directive.agentKey}
                  </span>
                  {phrases.length > 0 ? (
                    <span className="text-aether-muted-dim"> — {phrases.join(", ")}</span>
                  ) : null}
                  {directive.rationale ? (
                    <p
                      data-prose="caption"
                      data-prose-source="server"
                      data-testid="agent-policy-directive-rationale"
                      className="mt-0.5 text-[11px] leading-[1.4] text-aether-muted-dim"
                    >
                      {directive.rationale}
                    </p>
                  ) : null}
                  {clampedEntries.length > 0 ? (
                    <ul className="mt-0.5" data-testid="agent-policy-directive-clamped">
                      {clampedEntries.map(([field, info]) => {
                        const record = info as { requested?: unknown; applied?: unknown };
                        return (
                          <li key={field} className="text-[11px] text-aether-muted-dim">
                            Supervisor asked for {String(record.requested)} {KNOB_LABEL[field] ?? field};
                            {" "}the ceiling is {String(record.applied)}.
                          </li>
                        );
                      })}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {/* THE DIMENSIONS the "below floor" triggers are talking about, drawn
          against that floor. A dimension the scorer never evaluated is absent
          from `dimensionScores` and is therefore absent here too — it is not
          drawn at zero, which would be a specific false claim. */}
      {dimensionRows.length > 0 ? (
        <div className="mt-4" data-testid="agent-policy-dimensions">
          <BulletChart
            title="Dimension scores vs the floor"
            windowLabel={
              snapshot.dimensionSampleSize
                ? `all-time — ${snapshot.dimensionSampleSize} evaluated application${
                    snapshot.dimensionSampleSize === 1 ? "" : "s"
                  }`
                : "all-time — the dimensions the scorer has evaluated for you"
            }
            rows={dimensionRows}
            target={{ value: floor, label: `${floor} floor` }}
            axisMax={100}
          />
        </div>
      ) : null}

      <dl className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
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
      {snapshot.available === false && snapshot.unavailableReason ? (
        <p
          data-prose="caption"
          data-prose-source="server"
          data-testid="agent-policy-unavailable-reason"
          className="mt-2 text-[11px] leading-[1.45] text-aether-muted-dim"
        >
          {snapshot.unavailableReason}
        </p>
      ) : null}
    </section>
  );
}
