/**
 * Sales Agent admin API client — /api/admin/sales-agent/* (AdminUser-gated:
 * anonymous 401, non-admin 403). Same zod + apiRequest pattern as admin.ts.
 *
 * Honesty contract mirrored from the backend: `replyRate` is `null` (not 0)
 * when it is genuinely not observable, and every number is a live DB query.
 */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

// ---------------------------------------------------------------- overview
export const SalesOverviewSchema = z.object({
  signups: z.number(),
  paidConversions: z.number(),
  mrrAud: z.number(),
  leads: z.number(),
  emailsSent: z.number(),
  repliesObserved: z.number(),
  replyRate: z.number().nullable(),
  dryRunLogged: z.number(),
  linkedinDraftsQueued: z.number(),
  suppressionCount: z.number(),
});
export type SalesOverview = z.infer<typeof SalesOverviewSchema>;

export async function fetchSalesOverview(options: RequestOptions = {}): Promise<SalesOverview> {
  return SalesOverviewSchema.parse(
    await apiRequest<unknown>("/admin/sales-agent/overview", options),
  );
}

// ------------------------------------------------------------------- leads
export const SalesLeadSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string().nullable(),
  source: z.string(),
  sourceThreadId: z.string().nullable(),
  userId: z.string().nullable(),
  consentType: z.string(),
  consentEvidence: z.string(),
  status: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
});
export type SalesLead = z.infer<typeof SalesLeadSchema>;

const LeadListSchema = z.object({
  leads: z.array(SalesLeadSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type SalesLeadList = z.infer<typeof LeadListSchema>;

export async function fetchSalesLeads(
  params: { status?: string; limit?: number; offset?: number } = {},
  options: RequestOptions = {},
): Promise<SalesLeadList> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return LeadListSchema.parse(
    await apiRequest<unknown>(`/admin/sales-agent/leads${suffix}`, options),
  );
}

// --------------------------------------------------------------- campaigns
export const SalesCampaignSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.string(),
  templateBody: z.string(),
  active: z.boolean(),
  createdAt: z.string(),
  updatedAt: z.string(),
});
export type SalesCampaign = z.infer<typeof SalesCampaignSchema>;

export async function fetchSalesCampaigns(options: RequestOptions = {}): Promise<SalesCampaign[]> {
  const data = z
    .object({ campaigns: z.array(SalesCampaignSchema) })
    .parse(await apiRequest<unknown>("/admin/sales-agent/campaigns", options));
  return data.campaigns;
}

export async function updateSalesCampaign(
  id: string,
  patch: { name?: string; templateBody?: string; active?: boolean },
  options: RequestOptions = {},
): Promise<SalesCampaign> {
  return SalesCampaignSchema.parse(
    await apiRequest<unknown>(`/admin/sales-agent/campaigns/${id}`, {
      ...options,
      method: "PUT",
      body: patch,
    }),
  );
}

// ---------------------------------------------------------- branded preview
export const SalesCampaignPreviewSchema = z.object({
  campaignId: z.string(),
  name: z.string(),
  sampleName: z.string(),
  html: z.string(),
});
export type SalesCampaignPreview = z.infer<typeof SalesCampaignPreviewSchema>;

export async function fetchSalesCampaignPreview(
  id: string,
  options: RequestOptions = {},
): Promise<SalesCampaignPreview> {
  return SalesCampaignPreviewSchema.parse(
    await apiRequest<unknown>(`/admin/sales-agent/campaigns/${id}/preview`, options),
  );
}

// ---------------------------------------------------------------- generate
export const SalesGenerateResultSchema = z
  .object({
    ran: z.boolean(),
    reason: z.string().optional(),
    model: z.string().optional(),
    modelSource: z.string().optional(),
    campaignsCreated: z
      .array(
        z.object({
          id: z.string(),
          name: z.string(),
          type: z.string(),
          active: z.boolean(),
          note: z.string().optional(),
        }),
      )
      .optional()
      .default([]),
    campaignsSkipped: z.array(z.string()).optional().default([]),
    promosCreated: z
      .array(
        z.object({
          id: z.string(),
          code: z.string(),
          percentOff: z.number().optional(),
          active: z.boolean(),
          note: z.string().optional(),
        }),
      )
      .optional()
      .default([]),
    promosSkipped: z.array(z.string()).optional().default([]),
    linkedinDrafts: z.number().optional(),
    errors: z.array(z.string()).optional().default([]),
  })
  .passthrough();
export type SalesGenerateResult = z.infer<typeof SalesGenerateResultSchema>;

export async function generateSalesContent(
  options: RequestOptions = {},
): Promise<SalesGenerateResult> {
  return SalesGenerateResultSchema.parse(
    await apiRequest<unknown>("/admin/sales-agent/generate", {
      ...options,
      method: "POST",
    }),
  );
}

// ----------------------------------------------------------- brand documents
export const BrandDocumentKindSchema = z.object({
  kind: z.string(),
  title: z.string(),
  description: z.string(),
  needsPlan: z.boolean(),
  allowsImg: z.boolean().optional(),
});
export type BrandDocumentKind = z.infer<typeof BrandDocumentKindSchema>;

export const BrandAssetSchema = z.object({
  name: z.string(),
  path: z.string(),
  description: z.string(),
});
export type BrandAsset = z.infer<typeof BrandAssetSchema>;

export const BrandDocumentsSchema = z.object({
  documents: z.array(BrandDocumentKindSchema),
  plans: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      priceAudMonthly: z.number(),
      priceAudAnnual: z.number().nullable(),
    }),
  ),
  assets: z.array(BrandAssetSchema),
});
export type BrandDocuments = z.infer<typeof BrandDocumentsSchema>;

export const BrandTemplateSchema = z.object({
  kind: z.string(),
  body: z.string(),
  footnote: z.string(),
  footer: z.string(),
  updatedAt: z.string().nullable(),
  isDefault: z.boolean().optional(),
});
export type BrandTemplate = z.infer<typeof BrandTemplateSchema>;

export async function fetchBrandTemplates(options: RequestOptions = {}): Promise<BrandTemplate[]> {
  const data = z.object({ templates: z.array(BrandTemplateSchema) }).parse(
    await apiRequest<unknown>("/admin/sales-agent/brand/templates", options),
  );
  return data.templates;
}

export async function updateBrandTemplate(
  kind: string,
  patch: Pick<BrandTemplate, "body" | "footnote" | "footer">,
  options: RequestOptions = {},
): Promise<BrandTemplate> {
  return BrandTemplateSchema.parse(
    await apiRequest<unknown>(`/admin/sales-agent/brand/templates/${kind}`, {
      ...options,
      method: "PUT",
      body: patch,
    }),
  );
}

export async function fetchBrandDocuments(
  options: RequestOptions = {},
): Promise<BrandDocuments> {
  return BrandDocumentsSchema.parse(
    await apiRequest<unknown>("/admin/sales-agent/brand/documents", options),
  );
}

export const BrandDocumentPreviewSchema = z.object({
  kind: z.string(),
  title: z.string(),
  planId: z.string().nullable(),
  interval: z.string().nullable(),
  html: z.string(),
});
export type BrandDocumentPreview = z.infer<typeof BrandDocumentPreviewSchema>;

export async function fetchBrandDocumentPreview(
  kind: string,
  params: { plan?: string; interval?: string } = {},
  options: RequestOptions = {},
): Promise<BrandDocumentPreview> {
  const qs = new URLSearchParams();
  if (params.plan) qs.set("plan", params.plan);
  if (params.interval) qs.set("interval", params.interval);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return BrandDocumentPreviewSchema.parse(
    await apiRequest<unknown>(
      `/admin/sales-agent/brand/documents/${kind}/preview${suffix}`,
      options,
    ),
  );
}

// ------------------------------------------------------------ outreach log
export const SalesOutreachSchema = z.object({
  id: z.string(),
  leadId: z.string().nullable(),
  campaignId: z.string().nullable(),
  channel: z.string(),
  gmailMessageId: z.string().nullable(),
  gmailThreadId: z.string().nullable(),
  subject: z.string().nullable(),
  body: z.string().nullable(),
  recipient: z.string().nullable(),
  sentAt: z.string().nullable(),
  outcome: z.string().nullable(),
  detail: z.string().nullable(),
  createdAt: z.string(),
});
export type SalesOutreach = z.infer<typeof SalesOutreachSchema>;

const OutreachListSchema = z.object({
  entries: z.array(SalesOutreachSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type SalesOutreachList = z.infer<typeof OutreachListSchema>;

export async function fetchSalesOutreach(
  params: { outcome?: string; channel?: string; limit?: number; offset?: number } = {},
  options: RequestOptions = {},
): Promise<SalesOutreachList> {
  const qs = new URLSearchParams();
  if (params.outcome) qs.set("outcome", params.outcome);
  if (params.channel) qs.set("channel", params.channel);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return OutreachListSchema.parse(
    await apiRequest<unknown>(`/admin/sales-agent/outreach-log${suffix}`, options),
  );
}

// ------------------------------------------------------------------ health
export const SalesHealthSchema = z.object({
  enabled: z.boolean(),
  dryRun: z.boolean(),
  sendingAccounts: z.number(),
  intervalMinutes: z.number(),
  staleAfterMinutes: z.number(),
  status: z.string(),
  detail: z.string(),
  lastRunAt: z.string().nullable().optional().default(null),
});
export type SalesHealth = z.infer<typeof SalesHealthSchema>;

export async function fetchSalesHealth(options: RequestOptions = {}): Promise<SalesHealth> {
  return SalesHealthSchema.parse(
    await apiRequest<unknown>("/admin/sales-agent/health", options),
  );
}

// ----------------------------------------------------------------- run-now
export const SalesRunResultSchema = z
  .object({
    ran: z.boolean(),
    reason: z.string().optional(),
    dryRun: z.boolean().optional(),
    inboundScanned: z.number().optional(),
    inboundSkippedAutomated: z.number().optional(),
    inboundClassifiedLlm: z.number().optional(),
    inboundSkippedNoise: z.number().optional(),
    classifierDegraded: z.number().optional(),
    // Additive (S3): per-mailbox scan facts + one founder-readable sentence,
    // so a run reporting zeros always says why it reports zeros.
    explanation: z.string().optional(),
    accounts: z
      .array(
        z
          .object({
            email: z.string().optional(),
            scanned: z.number().optional(),
            skippedAutomated: z.number().optional(),
            backlogRemaining: z.boolean().optional(),
            scanWindow: z
              .object({ fromEpoch: z.number(), toEpoch: z.number() })
              .partial()
              .optional(),
            // Additive: same-second tie blocks. `tieDrained` records a whole
            // second fetched in full before the walk stepped below it;
            // `tieOverflow` is the honest disclosure that MORE messages share
            // that second than the per-second cap allows, so the oldest of
            // them were not scanned. Both are absent in the normal case.
            tieDrained: z
              .object({ epoch: z.number(), messages: z.number() })
              .partial()
              .optional(),
            tieOverflow: z
              .object({ epoch: z.number(), cap: z.number() })
              .partial()
              .optional(),
            // `tieDrainUnverified` is the third outcome, and the one that must
            // never be silent: the drain of that second could not be proven to
            // have reached it (it did not return messages already known to sit
            // there), so the walk HELD its window instead of stepping over
            // mail nobody read. It always ships with an error line too.
            tieDrainUnverified: z
              .object({
                epoch: z.number(),
                known: z.number(),
                returned: z.number(),
              })
              .partial()
              .optional(),
          })
          .passthrough(),
      )
      .optional(),
    linkedinCadence: z
      .object({
        perWeek: z.number().optional(),
        queuedLast7d: z.number().optional(),
        drafted: z.number().optional(),
        nextEligibleAt: z.string().nullable().optional(),
        reason: z.string().optional(),
      })
      .passthrough()
      .optional(),
    watermarksPruned: z.number().optional(),
    leadsCreated: z.number().optional(),
    sent: z.number().optional(),
    dryRunLogged: z.number().optional(),
    blocked: z.number().optional(),
    suppressed: z.number().optional(),
    repliesObserved: z.number().optional(),
    linkedinDrafts: z.number().optional(),
    digest: z.boolean().optional(),
    noSendingAccount: z.boolean().optional(),
    model: z.string().optional(),
    errors: z.array(z.string()).optional().default([]),
  })
  .passthrough();
export type SalesRunResult = z.infer<typeof SalesRunResultSchema>;

export async function runSalesAgentNow(options: RequestOptions = {}): Promise<SalesRunResult> {
  return SalesRunResultSchema.parse(
    await apiRequest<unknown>("/admin/sales-agent/run-now", {
      ...options,
      method: "POST",
    }),
  );
}

export const SalesStrategySchema = z.object({
  productUrl: z.string(),
  enabled: z.boolean(),
  dryRun: z.boolean(),
  lastRunAt: z.string().nullable().optional().default(null),
  healthStatus: z.string().optional(),
  healthDetail: z.string().optional(),
  emailsSent: z.number(),
  dryRunLogged: z.number(),
  repliesObserved: z.number(),
  replyRate: z.number().nullable(),
  leads: z.number(),
  campaignsActive: z.number(),
  campaignsInactive: z.number(),
  inactiveGeneratedNames: z.array(z.string()),
  linkedinDraftsQueued: z.number(),
  suppressionCount: z.number(),
  llmCostUsd30d: z.number(),
  cannotAttribute: z.boolean(),
  cannotAttributeReason: z.string(),
  nextActions: z.array(z.string()),
});
export type SalesStrategy = z.infer<typeof SalesStrategySchema>;

export async function fetchSalesStrategy(options: RequestOptions = {}): Promise<SalesStrategy> {
  return SalesStrategySchema.parse(
    await apiRequest<unknown>("/admin/sales-agent/strategy", options),
  );
}

// --------------------------------------------------------- sending accounts
export const SalesSendingAccountSchema = z.object({
  id: z.string(),
  accountEmail: z.string().nullable(),
  isPrimary: z.boolean(),
  usedForSalesAgent: z.boolean(),
  syncStatus: z.string().nullable(),
});
export type SalesSendingAccount = z.infer<typeof SalesSendingAccountSchema>;

export async function fetchSalesSendingAccounts(
  options: RequestOptions = {},
): Promise<SalesSendingAccount[]> {
  const data = z
    .object({ accounts: z.array(SalesSendingAccountSchema) })
    .parse(await apiRequest<unknown>("/admin/sales-agent/sending-accounts", options));
  return data.accounts;
}

export async function setSalesSendingAccount(
  accountId: string,
  enabled: boolean,
  options: RequestOptions = {},
): Promise<void> {
  await apiRequest<unknown>(`/admin/sales-agent/sending-accounts/${accountId}`, {
    ...options,
    method: "POST",
    body: { enabled },
  });
}
