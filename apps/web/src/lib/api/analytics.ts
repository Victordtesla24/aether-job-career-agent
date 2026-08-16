/** Typed analytics API client (P2-S10). */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

export type Period = "7d" | "30d" | "90d" | "all";

export const FunnelSchema = z.object({
  period: z.string(),
  jobs_found: z.number(),
  // CLI-D3 (audit wf_9a87f76f-eaa): `applied` counts applications that LEFT
  // DRAFT — preparation, not proof of sending (analytics.py
  // get_application_counts: status <> 'draft'). Surfaces labeling this count
  // must say "prepared", never "submitted"/"sent".
  applied: z.number(),
  screened: z.number(),
  interviewed: z.number(),
  offers: z.number(),
  // CLI-D3 ADDITIVE: DISTINCT jobs with a VERIFIED send (`transmittedAt IS
  // NOT NULL`, stamped only by the real send path — never by a status
  // change). Optional so the FE tolerates an older API during a rolling
  // deploy: absence withholds every "sent (verified)" surface instead of
  // fabricating a 0.
  transmitted: z.number().optional(),
});

export type Funnel = z.infer<typeof FunnelSchema>;

export const AtsDistributionSchema = z.object({
  buckets: z.array(z.object({ range: z.string(), count: z.number() })),
  total: z.number(),
});

export type AtsDistribution = z.infer<typeof AtsDistributionSchema>;

export const AgentRoiSchema = z.object({
  total_cost_usd: z.number(),
  total_runs: z.number(),
  avg_duration_ms: z.number(),
});

export type AgentRoi = z.infer<typeof AgentRoiSchema>;

export async function fetchFunnel(period: Period = "all", options: RequestOptions = {}): Promise<Funnel> {
  return FunnelSchema.parse(await apiRequest<unknown>(`/analytics/funnel?period=${period}`, options));
}

export async function fetchAtsDistribution(options: RequestOptions = {}): Promise<AtsDistribution> {
  return AtsDistributionSchema.parse(await apiRequest<unknown>("/analytics/ats-distribution", options));
}

export async function fetchAgentRoi(options: RequestOptions = {}): Promise<AgentRoi> {
  return AgentRoiSchema.parse(await apiRequest<unknown>("/analytics/agent-roi", options));
}

/** Stage-to-stage conversion rates (audit defect D9 — endpoint had no UI consumer). */
export const ConversionSchema = z.object({
  period: z.string(),
  found_to_applied: z.number(),
  applied_to_screened: z.number(),
  screened_to_interview: z.number(),
  interview_to_offer: z.number(),
  // GOLD-MASTER V4 §6 / G-C: the backend has always computed and returned
  // both fields (see analytics.py conversion()) — this schema simply never
  // declared them, so zod's default z.object() behavior silently stripped
  // them before the Analytics page ever saw them. Declaring them here is
  // the entire fix; the value itself is untouched, API-derived data.
  interview_conversion_rate: z.number(),
  interview_conversion_healthy: z.boolean(),
  // CLI-D3 ADDITIVE (audit wf_9a87f76f-eaa): the verified-send count for the
  // same window, and interviews over TRANSMITTED — the rate a user can trust
  // as "of what actually went out, how much converted". The legacy
  // `interview_conversion_rate` above keeps its exact prior meaning (its
  // denominator includes recorded-but-never-sent applications; the UI labels
  // it "prepared"). Both optional so an older API during deploy still parses
  // — absence withholds the verified surfaces, never fabricates them.
  transmitted: z.number().optional(),
  verified_interview_conversion_rate: z.number().optional(),
});

export type Conversion = z.infer<typeof ConversionSchema>;

export async function fetchConversion(
  period: Period = "all",
  options: RequestOptions = {},
): Promise<Conversion> {
  return ConversionSchema.parse(
    await apiRequest<unknown>(`/analytics/conversion?period=${period}`, options),
  );
}

/* ------------------------------- Dashboard ------------------------------- */

export const DashboardSchema = z.object({
  totalApplications: z.number(),
  interviews: z.number(),
  offers: z.number(),
  jobsFound: z.number(),
  avgFitScore: z.number(),
  agentRuns: z.number(),
  agentCostUsd: z.number(),
});

export type Dashboard = z.infer<typeof DashboardSchema>;

export async function fetchDashboard(
  period: Period = "all",
  options: RequestOptions = {},
): Promise<Dashboard> {
  // The backend has always accepted ?period= here (see analytics.py
  // _dashboard()); the client simply never forwarded it, so the Analytics
  // page's period selector silently left this panel on "all" (MV-analytics-004).
  return DashboardSchema.parse(
    await apiRequest<unknown>(`/analytics/dashboard?period=${period}`, options),
  );
}
