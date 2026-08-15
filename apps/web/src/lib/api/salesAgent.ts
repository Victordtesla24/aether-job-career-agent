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
    leadsCreated: z.number().optional(),
    sent: z.number().optional(),
    dryRunLogged: z.number().optional(),
    blocked: z.number().optional(),
    suppressed: z.number().optional(),
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
