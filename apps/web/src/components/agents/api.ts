/**
 * Agents-screen API client (catalog, per-agent config, providers, stats,
 * test-run). Kept inside components/agents so the Agents screen owns its own
 * data layer; it reuses the shared authenticated `apiRequest` transport.
 */
import { z } from "zod";

import { ApiError, apiRequest, type RequestOptions } from "../../lib/api/client";

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
  authMode: z.enum(["api_key", "subscription_oauth", "oauth_token"]).nullish(),
  secretHint: z.string().nullish(),
  lastVerifiedAt: z.string().nullish(),
  lastVerifyStatus: z.enum(["ok", "failed"]).nullish(),
  // ML-agents-cred-002 (ADR-ML-2a DECISION-1b): true when the Anthropic
  // subscription OAuth session was marked needs_reauth (auto-refresh failed /
  // token revoked). Drives the modal's Reconnect / Renew affordance. Its
  // `status` is demoted server-side to "warning" (never "connected").
  needsReauth: z.boolean().nullish(),
});
export type Provider = z.infer<typeof ProviderSchema>;

/**
 * One row of a provider's LIVE model catalog (GAP-P7-MODEL-CHOICE-001), as
 * served by GET /agents/providers/{provider}/models. Prices are already in
 * $/M-token (prompt + completion), `contextLength` is null when the provider
 * doesn't publish one, and `tier` is the budget bucket the backend derived
 * (models arrive sorted cheapest-first within tier).
 */
export const ProviderModelSchema = z.object({
  id: z.string(),
  name: z.string(),
  promptPerM: z.number(),
  completionPerM: z.number(),
  contextLength: z.number().nullable(),
  tier: z.enum(["free", "budget", "standard", "premium"]),
  reasoning: z.boolean(),
});
export type ProviderModel = z.infer<typeof ProviderModelSchema>;

/** Budget bucket a model falls into — the picker groups the catalog by this. */
export type ModelTier = ProviderModel["tier"];

export const ProviderModelsResponseSchema = z.object({
  provider: z.string(),
  count: z.number(),
  models: z.array(ProviderModelSchema),
  // Catalog freshness (ML-catalog-002). `.nullish()` so a legacy response (or a
  // test fixture) that predates the freshness contract still parses cleanly.
  lastRefreshedAt: z.string().nullish(),
  stale: z.boolean().nullish(),
});

/**
 * A provider's live model catalog WITH freshness metadata (ML-catalog-002):
 * the models plus when they were last actually fetched from upstream and
 * whether we're serving a stale (last-good) copy because a refresh failed.
 */
export interface ProviderCatalog {
  provider: string;
  count: number;
  models: ProviderModel[];
  lastRefreshedAt: string | null;
  stale: boolean;
}

function toProviderCatalog(
  res: z.infer<typeof ProviderModelsResponseSchema>,
): ProviderCatalog {
  return {
    provider: res.provider,
    count: res.count,
    models: res.models,
    lastRefreshedAt: res.lastRefreshedAt ?? null,
    stale: res.stale ?? false,
  };
}

/** Which credential shape a provider row carries. */
export type ProviderAuthMode = "api_key" | "subscription_oauth" | "oauth_token";

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
  // MV-agents-003: the backend never returns a raw null `model` (it falls
  // back to the literal "deterministic" for non-LLM/planned agents, the same
  // fallback GET /agents/catalog applies), so this stays non-nullable. But
  // the cost/token ESTIMATE (no per-token pricing to estimate for a
  // deterministic agent) and the "actual" figures (null until the agent has
  // completed at least one real run) are honestly nullable — requiring them
  // non-null is what produced the raw Zod parse error for 18/22 agents.
  model: z.string(),
  estTokens: z.number().nullable(),
  estCost: z.number().nullable(),
  actualCost: z.number().nullable(),
  actualTokens: z.number().nullable(),
  responseSeconds: z.number().nullable(),
  creditsCharged: z.number(),
});
export type TestRunResult = z.infer<typeof TestRunSchema>;

export async function fetchCatalog(o: RequestOptions = {}): Promise<Catalog> {
  return CatalogSchema.parse(await apiRequest<unknown>("/agents/catalog", o));
}

export async function fetchProviders(o: RequestOptions = {}): Promise<Provider[]> {
  return z.array(ProviderSchema).parse(await apiRequest<unknown>("/agents/providers", o));
}

/**
 * Lift the backend's honest `detail` out of an `ApiError`'s raw wrapper
 * message (`apiRequest` embeds the response body as `… failed (<status>):
 * {"detail":"…"}`). Mirrors lib/agents-feedback's extractor so the model
 * picker can surface the server's own no-key / catalog-unreachable message
 * verbatim instead of the noisy wrapper.
 */
function liftApiDetail(message: string): string {
  const match = message.match(/\{[\s\S]*\}$/);
  if (match) {
    try {
      const parsed = JSON.parse(match[0]) as { detail?: unknown };
      if (typeof parsed.detail === "string" && parsed.detail.trim()) return parsed.detail;
    } catch {
      /* not JSON — fall through to the raw message */
    }
  }
  return message;
}

/**
 * The LIVE, curated model catalog for a provider (GAP-P7-MODEL-CHOICE-001).
 * On the honest 400 (no credential / catalog unreachable) the backend returns
 * `{detail: "<message>"}`; we re-throw an ApiError whose `message` IS that
 * detail so the caller can show it directly — never a fabricated list.
 */
export async function fetchProviderModels(
  provider: string,
  o: RequestOptions = {},
): Promise<ProviderModel[]> {
  try {
    const res = await apiRequest<unknown>(`/agents/providers/${provider}/models`, o);
    return ProviderModelsResponseSchema.parse(res).models;
  } catch (e) {
    if (e instanceof ApiError) {
      throw new ApiError(liftApiDetail(e.message), e.status, e.retryAfterSeconds);
    }
    throw e;
  }
}

/**
 * The LIVE model catalog for a provider WITH its freshness envelope
 * (ML-catalog-008/N1): the SAME GET .../models call as {@link fetchProviderModels}
 * but returning the full `{models, lastRefreshedAt, stale}` envelope instead of
 * discarding the freshness — so the page can show the REAL backend timestamp on
 * initial load, not a "not yet refreshed" placeholder. Same honest-error
 * contract (the backend serves last-good stale data on upstream failure).
 */
export async function fetchProviderCatalog(
  provider: string,
  o: RequestOptions = {},
): Promise<ProviderCatalog> {
  try {
    const res = await apiRequest<unknown>(`/agents/providers/${provider}/models`, o);
    return toProviderCatalog(ProviderModelsResponseSchema.parse(res));
  } catch (e) {
    if (e instanceof ApiError) {
      throw new ApiError(liftApiDetail(e.message), e.status, e.retryAfterSeconds);
    }
    throw e;
  }
}

/**
 * Force a fresh upstream refresh of a provider's live catalog (ML-catalog-003):
 * POST .../providers/{provider}/models/refresh. Bypasses the ~1 h TTL cache and
 * returns the updated catalog + freshness. Same honest-error contract as the
 * GET path (last-good stale data on upstream failure, never a fabricated list).
 */
export async function refreshProviderModels(
  provider: string,
  o: RequestOptions = {},
): Promise<ProviderCatalog> {
  try {
    const res = await apiRequest<unknown>(`/agents/providers/${provider}/models/refresh`, {
      ...o,
      method: "POST",
    });
    return toProviderCatalog(ProviderModelsResponseSchema.parse(res));
  } catch (e) {
    if (e instanceof ApiError) {
      throw new ApiError(liftApiDetail(e.message), e.status, e.retryAfterSeconds);
    }
    throw e;
  }
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
  authMode: z.enum(["api_key", "subscription_oauth", "oauth_token"]).nullish(),
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
  authMode: z.enum(["api_key", "subscription_oauth", "oauth_token"]),
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

/** Result of POST /agents/providers/anthropic/oauth/start. */
export const AnthropicOAuthStartSchema = z.object({ authorizeUrl: z.string() });
export type AnthropicOAuthStart = z.infer<typeof AnthropicOAuthStartSchema>;

/**
 * Begin the in-app "Connect with Anthropic" (subscription) OAuth flow
 * (ML-agents-cred-002 / ADR-ML-1): the server mints a PKCE verifier + state and
 * returns Anthropic's OWN authorize URL. The caller opens it in a new tab; the
 * operator approves with their Claude Pro/Max account and pastes back a one-time
 * code (never the long-lived token).
 */
export async function startAnthropicOAuth(
  o: RequestOptions = {},
): Promise<AnthropicOAuthStart> {
  return AnthropicOAuthStartSchema.parse(
    await apiRequest<unknown>("/agents/providers/anthropic/oauth/start", {
      ...o,
      method: "POST",
    }),
  );
}

/**
 * Complete the Connect-with-Anthropic flow: POST the pasted ``code#state`` to
 * /agents/providers/anthropic/oauth/exchange. The server exchanges it for a
 * subscription token (stored encrypted, deployment-wide) and returns the masked
 * provider row — never the token. Parsed as a partial passthrough (same as the
 * other credential mutations) so a full enriched row round-trips unchanged.
 */
export async function exchangeAnthropicOAuth(
  pastedCode: string,
  o: RequestOptions = {},
): Promise<Provider> {
  return ProviderSchema.partial()
    .passthrough()
    .parse(
      await apiRequest<unknown>("/agents/providers/anthropic/oauth/exchange", {
        ...o,
        method: "POST",
        body: { pastedCode },
      }),
    ) as Provider;
}

/**
 * Renew the stored Anthropic subscription session: POST
 * /agents/providers/anthropic/oauth/refresh. Rotates the access + refresh token
 * server-side and returns the masked provider row. On an honest refresh failure
 * the server responds 502 and the token is marked needs_reauth (never a stale
 * token, never a cross-provider fallback) — surfaced here as a thrown ApiError.
 */
export async function refreshAnthropicOAuth(o: RequestOptions = {}): Promise<Provider> {
  return ProviderSchema.partial()
    .passthrough()
    .parse(
      await apiRequest<unknown>("/agents/providers/anthropic/oauth/refresh", {
        ...o,
        method: "POST",
      }),
    ) as Provider;
}
