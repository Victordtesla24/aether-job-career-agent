/** Typed agents API client (P2-S08). */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

export const AgentSummarySchema = z.object({
  name: z.string(),
  status: z.string(),
  last_run: z.string().nullish(),
  approval_gated: z.boolean(),
});

export type AgentSummary = z.infer<typeof AgentSummarySchema>;

export const AgentRunSchema = z.object({
  id: z.string(),
  agentName: z.string(),
  status: z.enum(["queued", "running", "completed", "failed"]),
  input: z.record(z.unknown()).nullish(),
  output: z.record(z.unknown()).nullish(),
  error: z.string().nullish(),
  costUsd: z.union([z.number(), z.string()]).nullish(),
  startedAt: z.string().nullish(),
  completedAt: z.string().nullish(),
  createdAt: z.string(),
});

export type AgentRun = z.infer<typeof AgentRunSchema>;

export async function fetchAgents(options: RequestOptions = {}): Promise<AgentSummary[]> {
  return z.array(AgentSummarySchema).parse(await apiRequest<unknown>("/agents", options));
}

export async function fetchAgentRuns(options: RequestOptions = {}): Promise<AgentRun[]> {
  return z.array(AgentRunSchema).parse(await apiRequest<unknown>("/agents/runs", options));
}

export async function runAgent(
  name: string,
  params: Record<string, unknown> = {},
  options: RequestOptions = {},
): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>(`/agents/${name}/run`, {
    ...options,
    method: "POST",
    body: params,
  });
}

export async function runPipeline(options: RequestOptions = {}): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>("/agents/pipeline/run", {
    ...options,
    method: "POST",
    body: {},
  });
}
