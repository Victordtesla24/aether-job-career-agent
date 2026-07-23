/**
 * Admin API client (GAP-P6-ADMIN-001/003, SEC-001).
 *
 * Authenticated calls over the shared `apiRequest` (bearer token + /login
 * redirect on 401). A non-admin caller gets a 403 `ApiError` from the backend
 * `AdminUser` gate; the /admin AdminGuard resolves `isAdmin` from /auth/me first
 * so non-admins never render the panel. All spend figures are USD (§14.8).
 */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

// --------------------------------------------------------------------------- //
// Identity (used by the AdminGuard)
// --------------------------------------------------------------------------- //

const MeSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string().optional().default(""),
  isAdmin: z.boolean().optional().default(false),
});
type Me = z.infer<typeof MeSchema>;

export async function fetchMe(options: RequestOptions = {}): Promise<Me> {
  return MeSchema.parse(await apiRequest<unknown>("/auth/me", options));
}

// --------------------------------------------------------------------------- //
// Health overview
// --------------------------------------------------------------------------- //

export const AdminHealthSchema = z.object({
  services: z.object({ api: z.string(), database: z.string() }),
  agents: z.object({
    totalRuns: z.number(),
    succeeded: z.number(),
    failed: z.number(),
    running: z.number(),
    queued: z.number().optional().default(0),
    successRate: z.number().nullable(),
  }),
  llm: z.object({ mode: z.string() }),
  cron: z.object({ status: z.string(), detail: z.string() }),
  providers: z.object({ configuredTiers: z.array(z.string()), count: z.number() }),
});
export type AdminHealth = z.infer<typeof AdminHealthSchema>;

export async function fetchAdminHealth(options: RequestOptions = {}): Promise<AdminHealth> {
  return AdminHealthSchema.parse(await apiRequest<unknown>("/admin/health", options));
}

// --------------------------------------------------------------------------- //
// Users
// --------------------------------------------------------------------------- //

export const AdminUserSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string().nullable(),
  isAdmin: z.boolean(),
  suspended: z.boolean(),
  plan: z.string().nullable(),
  subStatus: z.string().nullable(),
  signupAt: z.string().nullable(),
  lastLoginAt: z.string().nullable(),
  spendUsd: z.number(),
  runCount: z.number(),
  currency: z.string(),
});
export type AdminUser = z.infer<typeof AdminUserSchema>;

const AdminUserListSchema = z.object({
  users: z.array(AdminUserSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
type AdminUserList = z.infer<typeof AdminUserListSchema>;

export interface UserFilters {
  q?: string;
  plan?: string;
  suspended?: boolean;
}

export async function fetchAdminUsers(
  filters: UserFilters = {},
  options: RequestOptions = {},
): Promise<AdminUserList> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.plan) params.set("plan", filters.plan);
  if (typeof filters.suspended === "boolean") params.set("suspended", String(filters.suspended));
  const qs = params.toString();
  return AdminUserListSchema.parse(
    await apiRequest<unknown>(`/admin/users${qs ? `?${qs}` : ""}`, options),
  );
}

export const AdminUserDetailSchema = z.object({
  user: AdminUserSchema,
  subscription: z
    .object({
      planId: z.string(),
      status: z.string(),
      billingInterval: z.string().nullable(),
      currentPeriodEnd: z.string().nullable(),
      cancelAtPeriodEnd: z.boolean(),
    })
    .nullable(),
  quota: z
    .object({
      planId: z.string(),
      runsUsed: z.number(),
      runsAllowed: z.number(),
      spendUsedUsd: z.number(),
      spendCapUsd: z.number(),
      periodEnd: z.string().nullable(),
      currency: z.string(),
    })
    .nullable(),
  recentRuns: z.array(
    z.object({
      id: z.string(),
      agentName: z.string(),
      status: z.string(),
      costUsd: z.number(),
      createdAt: z.string().nullable(),
    }),
  ),
  spendUsd: z.number(),
  runCount: z.number(),
  currency: z.string(),
});
export type AdminUserDetail = z.infer<typeof AdminUserDetailSchema>;

export async function fetchAdminUser(
  userId: string,
  options: RequestOptions = {},
): Promise<AdminUserDetail> {
  return AdminUserDetailSchema.parse(
    await apiRequest<unknown>(`/admin/users/${encodeURIComponent(userId)}`, options),
  );
}

export async function setSpendCap(
  userId: string,
  spendCapUsd: number,
  options: RequestOptions = {},
): Promise<{ userId: string; spendCapUsd: number; currency: string }> {
  return apiRequest(`/admin/users/${encodeURIComponent(userId)}/spend-cap`, {
    ...options,
    method: "POST",
    body: { spendCapUsd },
  });
}

export async function setSuspended(
  userId: string,
  suspend: boolean,
  options: RequestOptions = {},
): Promise<{ userId: string; suspended: boolean }> {
  const verb = suspend ? "suspend" : "unsuspend";
  return apiRequest(`/admin/users/${encodeURIComponent(userId)}/${verb}`, {
    ...options,
    method: "POST",
    body: {},
  });
}

// --------------------------------------------------------------------------- //
// Spend
// --------------------------------------------------------------------------- //

export const AdminSpendSchema = z.object({
  totalUsd: z.number(),
  currency: z.string(),
  perUser: z.array(
    z.object({
      userId: z.string(),
      email: z.string().nullable(),
      name: z.string().nullable(),
      spendUsd: z.number(),
      runCount: z.number(),
    }),
  ),
});
export type AdminSpend = z.infer<typeof AdminSpendSchema>;

export async function fetchAdminSpend(options: RequestOptions = {}): Promise<AdminSpend> {
  return AdminSpendSchema.parse(await apiRequest<unknown>("/admin/spend", options));
}

// --------------------------------------------------------------------------- //
// Settings
// --------------------------------------------------------------------------- //

export const AdminSettingsSchema = z.object({
  signupEnabled: z.boolean(),
  emailVerificationEnabled: z.boolean(),
});
export type AdminSettings = z.infer<typeof AdminSettingsSchema>;

export async function fetchAdminSettings(options: RequestOptions = {}): Promise<AdminSettings> {
  return AdminSettingsSchema.parse(await apiRequest<unknown>("/admin/settings", options));
}

export async function updateAdminSettings(
  patch: Partial<AdminSettings>,
  options: RequestOptions = {},
): Promise<AdminSettings> {
  return AdminSettingsSchema.parse(
    await apiRequest<unknown>("/admin/settings", {
      ...options,
      method: "POST",
      body: patch,
    }),
  );
}

// --------------------------------------------------------------------------- //
// Audit log (append-only)
// --------------------------------------------------------------------------- //

export const AuditEntrySchema = z.object({
  id: z.string(),
  actorUserId: z.string(),
  action: z.string(),
  targetType: z.string().nullable(),
  targetId: z.string().nullable(),
  detail: z.unknown().nullable(),
  ip: z.string().nullable(),
  createdAt: z.string().nullable(),
});
export type AuditEntry = z.infer<typeof AuditEntrySchema>;

const AuditLogSchema = z.object({
  entries: z.array(AuditEntrySchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
type AuditLog = z.infer<typeof AuditLogSchema>;

export async function fetchAuditLog(
  limit = 50,
  offset = 0,
  options: RequestOptions = {},
): Promise<AuditLog> {
  return AuditLogSchema.parse(
    await apiRequest<unknown>(`/admin/audit-log?limit=${limit}&offset=${offset}`, options),
  );
}

/** US$ formatter — LLM spend is billed in USD, never AUD (§14.8). */
export function formatUsd(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(amount);
}
