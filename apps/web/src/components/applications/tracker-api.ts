/**
 * Application Tracker — screen-scoped API clients.
 *
 * Extends the shared application schema with the tracker fields the router
 * now returns (`answers` jsonb metadata + joined `fitScore`) and adds the
 * canonical sankey + agent-config fetchers, without touching shared clients.
 */
import { z } from "zod";

import { ApplicationSchema } from "../../lib/api/applications";
import { apiRequest, type RequestOptions } from "../../lib/api/client";

export const TrackerApplicationSchema = ApplicationSchema.extend({
  answers: z.record(z.unknown()).nullish(),
  fitScore: z.number().nullish(),
});

export type TrackerApplication = z.infer<typeof TrackerApplicationSchema>;

export async function fetchTrackerApplications(
  options: RequestOptions = {},
): Promise<TrackerApplication[]> {
  return z
    .array(TrackerApplicationSchema)
    .parse(await apiRequest<unknown>("/applications", options));
}

export async function fetchTrackerApplication(
  id: string,
  options: RequestOptions = {},
): Promise<TrackerApplication> {
  return TrackerApplicationSchema.parse(
    await apiRequest<unknown>(`/applications/${id}`, options),
  );
}

// ---- Canonical sankey (REQ-R2: 847 → 412 → 156 → 23 → 4) -------------------

export const SankeyStageSchema = z.object({
  key: z.string(),
  label: z.string(),
  value: z.number(),
  color: z.string(),
});

export const SankeyDataSchema = z.object({
  stages: z.array(SankeyStageSchema).min(2),
  dropoffs: z.array(
    z.object({ after: z.string(), count: z.number(), reason: z.string() }),
  ),
  insight: z.string(),
});

export type SankeyData = z.infer<typeof SankeyDataSchema>;

export async function fetchSankey(options: RequestOptions = {}): Promise<SankeyData> {
  return SankeyDataSchema.parse(
    await apiRequest<unknown>("/applications/funnel/sankey", options),
  );
}

// ---- Agent guardrail state (auto-apply banner) ------------------------------

export const AgentConfigSchema = z.object({
  autoApply: z.boolean(),
  approvalGate: z.boolean(),
  matchThreshold: z.number(),
});

export type AgentConfig = z.infer<typeof AgentConfigSchema>;

export async function fetchAgentConfig(
  options: RequestOptions = {},
): Promise<AgentConfig> {
  const settings = await apiRequest<{ agentConfig?: unknown }>(
    "/workspaces/settings",
    options,
  );
  return AgentConfigSchema.parse(settings.agentConfig);
}
