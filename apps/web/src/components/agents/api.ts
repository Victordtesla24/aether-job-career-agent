/**
 * Agents-screen API client (catalog, per-agent config, providers, stats,
 * test-run). Kept inside components/agents so the Agents screen owns its own
 * data layer; it reuses the shared authenticated `apiRequest` transport.
 */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "../../lib/api/client";

export const CatalogAgentSchema = z.object({
  key: z.string(),
  name: z.string(),
  icon: z.string(),
  accent: z.string(),
  model: z.string(),
  recommended: z.string(),
  tip: z.string(),
  runnable: z.boolean(),
  backend: z.string().nullish(),
  enabled: z.boolean(),
  status: z.enum(["active", "paused", "error"]),
  last_run: z.string().nullish(),
});
export type CatalogAgent = z.infer<typeof CatalogAgentSchema>;

export const CatalogSchema = z.object({
  agents: z.array(CatalogAgentSchema),
  counts: z.object({
    total: z.number(),
    active: z.number(),
    paused: z.number(),
    error: z.number(),
  }),
});
export type Catalog = z.infer<typeof CatalogSchema>;

export const ProviderSchema = z.object({
  id: z.string(),
  name: z.string(),
  auth: z.string(),
  status: z.enum(["connected", "warning", "unconfigured"]),
  model: z.string(),
  detail: z.string(),
  models: z.array(z.string()),
  icon: z.string(),
  color: z.string(),
});
export type Provider = z.infer<typeof ProviderSchema>;

export const StatsSchema = z.object({
  spendUsd: z.number(),
  avgCostPerRun: z.number(),
  providerCount: z.number(),
  tokensTotal: z.number(),
  tokensIn: z.number(),
  tokensOut: z.number(),
  mostActiveAgent: z.object({ name: z.string(), tasks: z.number() }).nullable(),
  successRate: z.number(),
  taskCount: z.number(),
});
export type AgentStats = z.infer<typeof StatsSchema>;

export const TestRunSchema = z.object({
  agent_key: z.string(),
  name: z.string(),
  model: z.string(),
  estTokens: z.number(),
  estCost: z.number(),
  actualCost: z.number(),
  actualTokens: z.number(),
  responseSeconds: z.number(),
  creditsCharged: z.number(),
});
export type TestRunResult = z.infer<typeof TestRunSchema>;

export async function fetchCatalog(o: RequestOptions = {}): Promise<Catalog> {
  return CatalogSchema.parse(await apiRequest<unknown>("/agents/catalog", o));
}

export async function fetchProviders(o: RequestOptions = {}): Promise<Provider[]> {
  return z.array(ProviderSchema).parse(await apiRequest<unknown>("/agents/providers", o));
}

export async function fetchAgentStats(o: RequestOptions = {}): Promise<AgentStats> {
  return StatsSchema.parse(await apiRequest<unknown>("/agents/stats", o));
}

export async function updateAgentConfig(
  key: string,
  patch: { enabled?: boolean; model?: string },
  o: RequestOptions = {},
): Promise<{ key: string; enabled: boolean; model: string }> {
  return apiRequest(`/agents/config/${key}`, { ...o, method: "PUT", body: patch });
}

export async function updateProvider(
  id: string,
  patch: { status?: "connected" | "warning" | "unconfigured"; model?: string },
  o: RequestOptions = {},
): Promise<Provider> {
  return ProviderSchema.partial()
    .passthrough()
    .parse(await apiRequest<unknown>(`/agents/providers/${id}`, { ...o, method: "PUT", body: patch })) as Provider;
}

export async function runTestRun(key: string, o: RequestOptions = {}): Promise<TestRunResult> {
  return TestRunSchema.parse(
    await apiRequest<unknown>("/agents/test-run", { ...o, method: "POST", body: { agent_key: key } }),
  );
}
