/**
 * Typed client for the U-AX self-improvement-visibility endpoints.
 *
 * GET /analytics/agent-policy — the SAME deterministic rigor tier every real
 * agent obeys (`app.services.quality_policy.resolve_policy_for_user`), why it
 * is what it is, and per-agent last-run visibility.
 * GET /agents/orchestration-map — all 22 catalog agent cards placed into one or
 * more end-to-end workflow maps, honest real-vs-planned status.
 *
 * Both schemas are deliberately permissive on the server's optional/extra
 * fields (zod's default object parsing keeps unknown keys) — this client only
 * asserts the shape the U-AX UI actually reads, per ADR-GMV4-style "fail
 * closed on absence, never invent" discipline: a missing numeric/array field
 * degrades to `null`/`[]` rather than crashing the panel.
 */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

// ---------------------------------------------------------------------------
// GET /analytics/agent-policy
// ---------------------------------------------------------------------------

export const PolicyRunViewSchema = z
  .object({
    runId: z.string().nullish(),
    status: z.string().nullish(),
    startedAt: z.string().nullish(),
    completedAt: z.string().nullish(),
    costUsd: z.number().nullish(),
    jobId: z.string().nullish(),
    applicationId: z.string().nullish(),
    policyTier: z.string().nullish(),
    policyInputs: z.record(z.unknown()).nullish(),
  })
  .nullable();

export type PolicyRunView = z.infer<typeof PolicyRunViewSchema>;

export const AgentPolicyPerAgentSchema = z.object({
  agentKey: z.string(),
  name: z.string(),
  backend: z.string().nullish(),
  lastRun: PolicyRunViewSchema,
});

export type AgentPolicyPerAgent = z.infer<typeof AgentPolicyPerAgentSchema>;

export const AgentPolicyMetricSnapshotSchema = z.object({
  sampleSize: z.number().default(0),
  // Percentage (0-100) — the analytics endpoint converts the fraction at its
  // own boundary (see apps/api/app/routers/analytics.py::agent_policy).
  conversionRate: z.number().default(0),
  interviewCount: z.number().nullish(),
  dimensionScores: z.record(z.number()).default({}),
  dimensionSampleSize: z.number().nullish(),
  dimensionsEvaluated: z.number().nullish(),
  // Nullish (not `.default()`): a caller building a fixture (e.g. tests) may
  // omit it entirely, and the component below treats "absent" the same as
  // `false` — never inferring "measured" from silence.
  available: z.boolean().nullish(),
  unavailableReason: z.string().nullish(),
});

export type AgentPolicyMetricSnapshot = z.infer<typeof AgentPolicyMetricSnapshotSchema>;

export const AgentPolicySchema = z.object({
  tier: z.string(),
  triggers: z.array(z.string()).default([]),
  behaviour: z.string().nullish(),
  knobs: z.record(z.unknown()).nullish(),
  thresholds: z.record(z.unknown()).nullish(),
  metricSnapshot: AgentPolicyMetricSnapshotSchema,
  perAgent: z.array(AgentPolicyPerAgentSchema).default([]),
});

export type AgentPolicy = z.infer<typeof AgentPolicySchema>;

export async function fetchAgentPolicy(options: RequestOptions = {}): Promise<AgentPolicy> {
  return AgentPolicySchema.parse(await apiRequest<unknown>("/analytics/agent-policy", options));
}

// ---------------------------------------------------------------------------
// GET /agents/orchestration-map
// ---------------------------------------------------------------------------

export const OrchestrationTrendSchema = z
  .object({
    runs: z.number().nullish(),
    metric: z.string().nullish(),
    latest: z.number().nullish(),
    previous: z.number().nullish(),
    delta: z.number().nullish(),
    direction: z.enum(["improving", "declining", "steady"]).nullish(),
    basis: z.string().nullish(),
  })
  .nullable();

export type OrchestrationTrend = z.infer<typeof OrchestrationTrendSchema>;

export const OrchestrationMapAgentSchema = z.object({
  agentKey: z.string(),
  name: z.string(),
  backend: z.string().nullish(),
  // Structurally derived server-side: "real" iff the catalog entry has a
  // backend implementation, "planned" otherwise — never a fake "running".
  status: z.enum(["real", "planned"]),
  runnable: z.boolean().nullish(),
  metricsConsumed: z.array(z.string()).default([]),
  thresholds: z.array(z.string()).default([]),
  lastRunPolicyTier: z.string().nullish(),
  lastRunAt: z.string().nullish(),
  lastRunStatus: z.string().nullish(),
  trend: OrchestrationTrendSchema.nullish(),
});

export type OrchestrationMapAgent = z.infer<typeof OrchestrationMapAgentSchema>;

export const OrchestrationMapStageSchema = z.object({
  stage: z.string(),
  agents: z.array(OrchestrationMapAgentSchema).default([]),
});

export type OrchestrationMapStage = z.infer<typeof OrchestrationMapStageSchema>;

export const OrchestrationMapEntrySchema = z.object({
  key: z.string(),
  name: z.string(),
  subtitle: z.string().nullish(),
  stages: z.array(OrchestrationMapStageSchema).default([]),
});

export type OrchestrationMapEntry = z.infer<typeof OrchestrationMapEntrySchema>;

export const OrchestrationMapDataSchema = z.object({
  maps: z.array(OrchestrationMapEntrySchema).default([]),
});

export type OrchestrationMapData = z.infer<typeof OrchestrationMapDataSchema>;

export async function fetchOrchestrationMap(
  options: RequestOptions = {},
): Promise<OrchestrationMapData> {
  return OrchestrationMapDataSchema.parse(
    await apiRequest<unknown>("/agents/orchestration-map", options),
  );
}

// ---------------------------------------------------------------------------
// GET /analytics/agent-policy/history — U-AX item 2(c)
// ---------------------------------------------------------------------------

export const PolicyHistoryPointSchema = z.object({
  at: z.string().nullish(),
  tier: z.string(),
  /** How many consecutive runs this unchanged point covers — repeats are
   *  collapsed server-side so a flat period reads as flat, not as activity. */
  runs: z.number().default(1),
  /** Percentage (0-100), converted at the API boundary like every other
   *  analytics surface. */
  conversionRate: z.number().default(0),
  sampleSize: z.number().default(0),
  interviewCount: z.number().default(0),
  dimensionsBelowFloor: z.array(z.string()).default([]),
  dimensionsEvaluated: z.number().default(0),
  triggers: z.array(z.string()).default([]),
});

export type PolicyHistoryPoint = z.infer<typeof PolicyHistoryPointSchema>;

export const PolicyHistorySchema = z.object({
  available: z.boolean().default(false),
  reason: z.string().nullish(),
  /** Runs that recorded NO tier (everything predating the loop). Reported so
   *  the series can say how much history is genuinely un-instrumented instead
   *  of implying it is complete. */
  runsWithoutPolicy: z.number().default(0),
  thresholds: z
    .object({
      interviewConversionTarget: z.number().nullish(),
      dimensionFloor: z.number().nullish(),
      minSampleSize: z.number().nullish(),
    })
    .nullish(),
  points: z.array(PolicyHistoryPointSchema).default([]),
});

export type PolicyHistory = z.infer<typeof PolicyHistorySchema>;

export async function fetchPolicyHistory(
  options: RequestOptions = {},
): Promise<PolicyHistory> {
  return PolicyHistorySchema.parse(
    await apiRequest<unknown>("/analytics/agent-policy/history", options),
  );
}

// ---------------------------------------------------------------------------
// GET /analytics/agent-policy/cohorts — U-AX item 3
// ---------------------------------------------------------------------------

export const PolicyCohortSchema = z.object({
  tier: z.string(),
  label: z.string(),
  /** AUD-META-1: applications that left `draft` under this tier — PREPARED.
   *  Preparation is not proof of sending, so this is never called "submitted",
   *  "applied" or "sent" on any surface that renders it. Required (no
   *  `.default()`): a payload that stopped sending it must fail loudly here
   *  rather than render a silent 0. */
  prepared: z.number(),
  /** Applications under this tier carrying a real `transmittedAt` — a VERIFIED
   *  send, and the only denominator `conversionRate` is computed over. */
  transmitted: z.number(),
  interviewed: z.number().default(0),
  /** `null` when the cohort has fewer than `minSampleSize` VERIFIED sends: one
   *  application that did not convert is not "0%", and printing a rate there
   *  would invite the wrong conclusion about the tier that produced it. */
  conversionRate: z.number().nullish(),
  sufficientSample: z.boolean().default(false),
  meetsTarget: z.boolean().nullish(),
  gapPoints: z.number().nullish(),
});

export type PolicyCohort = z.infer<typeof PolicyCohortSchema>;

export const PolicyCohortsSchema = z.object({
  target: z.number().default(20),
  minSampleSize: z.number().default(5),
  cohorts: z.array(PolicyCohortSchema).default([]),
  untagged: z
    .object({
      // AUD-META-1: same prepared-vs-transmitted split as a cohort row.
      prepared: z.number(),
      transmitted: z.number(),
      interviewed: z.number().default(0),
      reason: z.string().nullish(),
    })
    .default({ prepared: 0, transmitted: 0, interviewed: 0 }),
});

export type PolicyCohorts = z.infer<typeof PolicyCohortsSchema>;

export async function fetchPolicyCohorts(
  options: RequestOptions = {},
): Promise<PolicyCohorts> {
  return PolicyCohortsSchema.parse(
    await apiRequest<unknown>("/analytics/agent-policy/cohorts", options),
  );
}

// ---------------------------------------------------------------------------
// GET /agents/directives — B1b (ADR-AGI-2 P1,
// ORCH-B1-BLUEPRINT-2026-08-14.md §5.2/§8). The Supervisor's bounded,
// whitelisted, ratcheted amendments to an agent's rigor policy — "active
// directive + the metrics that caused it" per the ADR's transparency pillar.
// ---------------------------------------------------------------------------

export const AgentDirectiveSchema = z.object({
  id: z.string(),
  agentKey: z.string(),
  status: z.string(),
  // Only whitelisted numeric/enum knobs ever land here (server-enforced) —
  // kept permissive (`z.unknown()`) rather than re-declaring the whitelist
  // client-side, which would be a second copy of the security boundary.
  directive: z.record(z.unknown()).default({}),
  clamped: z.record(z.unknown()).default({}),
  rejectedKeys: z.array(z.string()).default([]),
  // Rendered VERBATIM (§8.2) — the FE never composes its own explanation.
  rationale: z.string().nullish(),
  metricsCited: z.record(z.unknown()).default({}),
  issuedBy: z.string().nullish(),
  supersededById: z.string().nullish(),
  outcome: z.record(z.unknown()).nullish(),
  issuedAt: z.string().nullish(),
  expiresAt: z.string().nullish(),
});

export type AgentDirective = z.infer<typeof AgentDirectiveSchema>;

export const AgentDirectivesResponseSchema = z.object({
  directives: z.array(AgentDirectiveSchema).default([]),
  // true while AETHER_AGI_DIRECTIVES_ENABLED is off on the deployment — the
  // array is still returned (history is never a lie); the FE renders these
  // as "not currently applied" rather than hiding them.
  paused: z.boolean().default(false),
  pausedReason: z.string().nullish(),
});

export type AgentDirectivesResponse = z.infer<typeof AgentDirectivesResponseSchema>;

export async function fetchAgentDirectives(
  options: RequestOptions = {},
): Promise<AgentDirectivesResponse> {
  return AgentDirectivesResponseSchema.parse(
    await apiRequest<unknown>("/agents/directives", options),
  );
}
