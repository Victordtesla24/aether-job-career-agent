/**
 * Admin API client (GAP-P6-ADMIN-001/003, SEC-001).
 *
 * Authenticated calls over the shared `apiRequest` (bearer token + /login
 * redirect on 401). A non-admin caller gets a 403 `ApiError` from the backend
 * `AdminUser` gate; the /admin AdminGuard resolves `isAdmin` from /auth/me first
 * so non-admins never render the panel. All spend figures are USD (§14.8).
 */
import { z } from "zod";

import { EntitlementViewSchema } from "./billing";
import { apiRequest, type RequestOptions } from "./client";

// --------------------------------------------------------------------------- //
// Identity (used by the AdminGuard)
// --------------------------------------------------------------------------- //

const MeSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string().optional().default(""),
  isAdmin: z.boolean().optional().default(false),
  // F-02: the profile columns that say what THIS user is job-hunting for.
  // GET /auth/me has always returned them (apps/api/app/routers/auth.py:me);
  // they were simply dropped on the floor here, which is why Job Discovery had
  // nothing to derive a search from and posted a hardcoded persona instead.
  // Optional-with-default so an older payload still parses.
  targetRole: z.string().optional().default(""),
  location: z.string().optional().default(""),
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
  // ADMIN-FULL: username is a real login identity an admin can search and edit.
  // Optional-with-default so an older API payload still parses.
  username: z.string().nullable().optional().default(null),
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
  entitlement: EntitlementViewSchema.optional().default({}),
});
export type AdminUserDetail = z.infer<typeof AdminUserDetailSchema>;

// --------------------------------------------------------------------------- //
// User management (ADMIN-FULL)
//
// Plan changes are ENTITLEMENT OVERRIDES — immediate, Stripe-independent, and
// visibly an override in the panel + the audit trail. Stripe-linked actions
// (cancel / refund) route through the backend's existing billing service, which
// is why there is no client-side Stripe anything here.
// --------------------------------------------------------------------------- //

/** `none` clears any existing override and returns the user to their real plan. */
export type EntitlementOverrideKind = "comp" | "tier" | "unlimited" | "none";

const EntitlementResponseSchema = z.object({
  userId: z.string(),
  entitlement: EntitlementViewSchema,
});

export async function setEntitlementOverride(
  userId: string,
  body: { kind: EntitlementOverrideKind; planId?: string; note?: string },
  options: RequestOptions = {},
): Promise<z.infer<typeof EntitlementResponseSchema>> {
  return EntitlementResponseSchema.parse(
    await apiRequest<unknown>(`/admin/users/${encodeURIComponent(userId)}/entitlement`, {
      ...options,
      method: "POST",
      body,
    }),
  );
}

/**
 * Set a user's password on their behalf. The plaintext is sent once over the
 * authenticated HTTPS call, hashed server-side by the app's own hasher, and
 * never stored, echoed or audited by value — the audit records the EVENT.
 * Existing sessions for that user are invalidated by the change.
 */
export async function setUserPassword(
  userId: string,
  newPassword: string,
  options: RequestOptions = {},
): Promise<{ userId: string; passwordChanged: boolean; sessionsInvalidated: boolean }> {
  return apiRequest(`/admin/users/${encodeURIComponent(userId)}/password`, {
    ...options,
    method: "POST",
    body: { newPassword },
  });
}

const IdentityFieldsSchema = z.object({
  email: z.string().nullable(),
  username: z.string().nullable(),
  name: z.string().nullable(),
});

const IdentityResponseSchema = z.object({
  userId: z.string(),
  before: IdentityFieldsSchema,
  after: IdentityFieldsSchema,
});

export async function updateUserIdentity(
  userId: string,
  patch: { email?: string; username?: string; name?: string },
  options: RequestOptions = {},
): Promise<z.infer<typeof IdentityResponseSchema>> {
  return IdentityResponseSchema.parse(
    await apiRequest<unknown>(`/admin/users/${encodeURIComponent(userId)}/identity`, {
      ...options,
      method: "POST",
      body: patch,
    }),
  );
}

export async function cancelUserSubscription(
  userId: string,
  atPeriodEnd: boolean,
  options: RequestOptions = {},
): Promise<{ userId: string; atPeriodEnd: boolean; cancelAtPeriodEnd: boolean; planId: string }> {
  return apiRequest(`/admin/users/${encodeURIComponent(userId)}/subscription/cancel`, {
    ...options,
    method: "POST",
    body: { atPeriodEnd },
  });
}

export async function refundUserSubscription(
  userId: string,
  options: RequestOptions = {},
): Promise<{ userId: string; refundId: string | null; status: string | null; planId: string }> {
  return apiRequest(`/admin/users/${encodeURIComponent(userId)}/subscription/refund`, {
    ...options,
    method: "POST",
    body: {},
  });
}

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
  // QA M-05: human-readable actor identity (older API builds omit these).
  actorName: z.string().nullable().optional(),
  actorEmail: z.string().nullable().optional(),
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

/** The append-only audit trail for ONE user (ADMIN-FULL user panel). */
export async function fetchUserAuditLog(
  userId: string,
  limit = 25,
  options: RequestOptions = {},
): Promise<AuditLog> {
  return AuditLogSchema.parse(
    await apiRequest<unknown>(
      `/admin/users/${encodeURIComponent(userId)}/audit?limit=${limit}`,
      options,
    ),
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
