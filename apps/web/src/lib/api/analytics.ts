/** Typed analytics API client (P2-S10). */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

export type Period = "7d" | "30d" | "90d" | "all";

export const FunnelSchema = z.object({
  period: z.string(),
  jobs_found: z.number(),
  applied: z.number(),
  screened: z.number(),
  interviewed: z.number(),
  offers: z.number(),
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
