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
  status: z.enum(["active", "paused", "error", "planned"]),
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
    planned: z.number().optional(),
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
  // Enriched provider-config fields (PROVIDER-CONFIG-RUN §1). Optional so the
  // client parses both a legacy env-only row and the DB-backed enriched row —
  // FE and BE ship on independent branches against this one contract.
  source: z.enum(["database", "environment", "none"]).nullish(),
  authMode: z.enum(["api_key", "subscription_oauth"]).nullish(),
  secretHint: z.string().nullish(),
  lastVerifiedAt: z.string().nullish(),
  lastVerifyStatus: z.enum(["ok", "failed"]).nullish(),
});
export type Provider = z.infer<typeof ProviderSchema>;

/** Which credential shape a provider row carries. */
export type ProviderAuthMode = "api_key" | "subscription_oauth";

/** Body for PUT /agents/providers/{id}/credential. */
export interface CredentialInput {
  authMode: ProviderAuthMode;
  secret: string;
  baseUrl?: string;
}

export const VerifyResultSchema = z.object({
  ok: z.boolean(),
  status: z.string(),
  detail: z.string(),
});
export type VerifyResult = z.infer<typeof VerifyResultSchema>;

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

/** Extended thinking effort levels a model may honour (GAP-D3). */
export type ThinkingEffort = "none" | "low" | "medium" | "high";

/** Full per-agent configuration (GAP-D3) merged over catalog defaults. */
export const AgentConfigSchema = z.object({
  key: z.string(),
  enabled: z.boolean(),
  model: z.string(),
  provider: z.string().nullish(),
  authMode: z.enum(["api_key", "subscription_oauth"]).nullish(),
  credentialRef: z.string().nullish(),
  temperature: z.number(),
  thinkingEffort: z.enum(["none", "low", "medium", "high"]),
});
export type AgentConfig = z.infer<typeof AgentConfigSchema>;

/** Patch body for PUT /agents/config/{key}; every field is optional (merge). */
export interface AgentConfigPatch {
  enabled?: boolean;
  model?: string;
  provider?: string | null;
  authMode?: ProviderAuthMode | null;
  credentialRef?: string | null;
  temperature?: number;
  thinkingEffort?: ThinkingEffort;
}

export async function fetchAgentConfig(
  key: string,
  o: RequestOptions = {},
): Promise<AgentConfig> {
  return AgentConfigSchema.parse(await apiRequest<unknown>(`/agents/config/${key}`, o));
}

export async function fetchAgentConfigList(o: RequestOptions = {}): Promise<AgentConfig[]> {
  return z.array(AgentConfigSchema).parse(await apiRequest<unknown>("/agents/config", o));
}

export async function updateAgentConfig(
  key: string,
  patch: AgentConfigPatch,
  o: RequestOptions = {},
): Promise<AgentConfig> {
  return AgentConfigSchema.parse(
    await apiRequest<unknown>(`/agents/config/${key}`, { ...o, method: "PUT", body: patch }),
  );
}

/** A user's own stored provider credential, masked (never the secret). */
export const UserCredentialSchema = z.object({
  id: z.string(),
  provider: z.string(),
  authMode: z.enum(["api_key", "subscription_oauth"]),
  secretHint: z.string().nullish(),
  baseUrl: z.string().nullish(),
  expiresAt: z.string().nullish(),
  lastVerifiedAt: z.string().nullish(),
  lastVerifyStatus: z.enum(["ok", "failed"]).nullish(),
});
export type UserCredential = z.infer<typeof UserCredentialSchema>;

export async function listUserCredentials(o: RequestOptions = {}): Promise<UserCredential[]> {
  return z.array(UserCredentialSchema).parse(
    await apiRequest<unknown>("/agents/user/providers", o),
  );
}

/**
 * Store (or rotate) THIS user's own encrypted credential for a provider, then
 * verify it server-side (GAP-NEW-001). Returns the masked row incl. the honest
 * lastVerifyStatus — never the secret.
 */
export async function putUserCredential(
  provider: string,
  body: CredentialInput,
  o: RequestOptions = {},
): Promise<UserCredential> {
  return UserCredentialSchema.partial()
    .passthrough()
    .parse(
      await apiRequest<unknown>(`/agents/user/providers/${provider}/credential`, {
        ...o,
        method: "PUT",
        body,
      }),
    ) as UserCredential;
}

export async function deleteUserCredential(
  provider: string,
  o: RequestOptions = {},
): Promise<UserCredential> {
  return UserCredentialSchema.partial()
    .passthrough()
    .parse(
      await apiRequest<unknown>(`/agents/user/providers/${provider}/credential`, {
        ...o,
        method: "DELETE",
      }),
    ) as UserCredential;
}

export async function verifyUserCredential(
  provider: string,
  o: RequestOptions = {},
): Promise<VerifyResult> {
  return VerifyResultSchema.parse(
    await apiRequest<unknown>(`/agents/user/providers/${provider}/verify`, {
      ...o,
      method: "POST",
    }),
  );
}

/** The Anthropic subscription OAuth consent URL (GAP-D1). */
export const OAuthStartSchema = z.object({
  authorizeUrl: z.string(),
  state: z.string(),
});
export type OAuthStart = z.infer<typeof OAuthStartSchema>;

/**
 * Begin the Anthropic subscription OAuth flow: GET /agents/auth/anthropic/start.
 * Returns the claude.ai consent URL to redirect the user to. Throws when the
 * server has not configured OAuth (honest 501 — never a fabricated URL).
 */
export async function startAnthropicOAuth(o: RequestOptions = {}): Promise<OAuthStart> {
  return OAuthStartSchema.parse(await apiRequest<unknown>("/agents/auth/anthropic/start", o));
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

/**
 * Save (or rotate) a provider credential in-app: PUT
 * /agents/providers/{id}/credential. The server stores the secret encrypted
 * and returns the masked provider row (last-4 hint only — never the secret).
 * Parsed as a partial passthrough so a full enriched row and a lean patch both
 * round-trip without the schema over-constraining the backend.
 */
export async function putProviderCredential(
  id: string,
  body: CredentialInput,
  o: RequestOptions = {},
): Promise<Provider> {
  return ProviderSchema.partial()
    .passthrough()
    .parse(
      await apiRequest<unknown>(`/agents/providers/${id}/credential`, {
        ...o,
        method: "PUT",
        body,
      }),
    ) as Provider;
}

/**
 * Remove an in-app provider credential: DELETE
 * /agents/providers/{id}/credential. The server drops the DB secret and
 * returns the masked row, which may fall back to an `environment` source if a
 * legacy env credential is still present (ADR-PC-4).
 */
export async function deleteProviderCredential(
  id: string,
  o: RequestOptions = {},
): Promise<Provider> {
  return ProviderSchema.partial()
    .passthrough()
    .parse(
      await apiRequest<unknown>(`/agents/providers/${id}/credential`, { ...o, method: "DELETE" }),
    ) as Provider;
}

/**
 * Test a provider credential end-to-end: POST /agents/providers/{id}/verify.
 * Performs a real provider round-trip server-side and reports the honest
 * result (no fabricated "connected").
 */
export async function verifyProvider(id: string, o: RequestOptions = {}): Promise<VerifyResult> {
  return VerifyResultSchema.parse(
    await apiRequest<unknown>(`/agents/providers/${id}/verify`, { ...o, method: "POST" }),
  );
}
