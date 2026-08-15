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
  // ADMIN-2.0: soft-delete state is admin-only truth. A deleted account is
  // still LISTED (its jobs, applications, runs and audit history survive) and
  // visibly flagged — hiding the row would look identical to a hard delete
  // that never happened. Optional-with-default so an older payload still parses.
  deletedAt: z.string().nullable().optional().default(null),
  /** True while the account is still on a password an admin generated for it. */
  mustChangePassword: z.boolean().optional().default(false),
  plan: z.string().nullable(),
  subStatus: z.string().nullable(),
  signupAt: z.string().nullable(),
  lastLoginAt: z.string().nullable(),
  spendUsd: z.number(),
  runCount: z.number(),
  currency: z.string(),
});
export type AdminUser = z.infer<typeof AdminUserSchema>;

/**
 * ADMIN-MGMT: the same rows sliced by lifecycle state, computed server-side
 * over the WHOLE table (not the current page) so a tab's badge is honest even
 * when the list itself is filtered by search/plan too.
 */
export const AdminUserCountsSchema = z.object({
  active: z.number(),
  suspended: z.number(),
  deleted: z.number(),
});
export type AdminUserCounts = z.infer<typeof AdminUserCountsSchema>;

const AdminUserListSchema = z.object({
  users: z.array(AdminUserSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  counts: AdminUserCountsSchema,
});
type AdminUserList = z.infer<typeof AdminUserListSchema>;

/** `active` = not suspended, not deleted (the honest default — a deleted
 *  account no longer clutters the list an operator opens by default). */
export type AdminUserView = "active" | "suspended" | "deleted" | "all";

export interface UserFilters {
  q?: string;
  plan?: string;
  /** Legacy filter — still honoured exactly as before when provided. */
  suspended?: boolean;
  view?: AdminUserView;
}

export async function fetchAdminUsers(
  filters: UserFilters = {},
  options: RequestOptions = {},
): Promise<AdminUserList> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.plan) params.set("plan", filters.plan);
  if (typeof filters.suspended === "boolean") params.set("suspended", String(filters.suspended));
  if (filters.view) params.set("view", filters.view);
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
 *
 * ``sessionsInvalidated`` is what the API MEASURED after writing, not a
 * constant: true means every token minted before ``sessionsInvalidatedBefore``
 * is already rejected. Callers must render the false case honestly instead of
 * assuming the lockout happened. A 409 means this identity's password is
 * managed by server configuration (§14.7) and cannot be set from the app.
 */
export async function setUserPassword(
  userId: string,
  newPassword: string,
  options: RequestOptions = {},
): Promise<{
  userId: string;
  passwordChanged: boolean;
  sessionsInvalidated: boolean;
  sessionsInvalidatedBefore?: string | null;
}> {
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

// --------------------------------------------------------------------------- //
// Account lifecycle (ADMIN-2.0 BE-1)
// --------------------------------------------------------------------------- //

const CreatedUserSchema = z.object({
  userId: z.string(),
  email: z.string(),
  name: z.string().nullable(),
  /**
   * The generated temporary password. Returned EXACTLY ONCE by
   * `POST /admin/users` — the API hashes it, never stores the plaintext, never
   * writes it to the audit row, and exposes no route that can read it back. A
   * caller that drops this value has lost it for good; the only remedy is
   * `setUserPassword`. Never log it, never persist it, never put it in a URL.
   */
  tempPassword: z.string(),
  mustChangePassword: z.boolean(),
  createdAt: z.string().nullable(),
});
export type CreatedUser = z.infer<typeof CreatedUserSchema>;

/**
 * Create an account on a user's behalf. An admin-created account is an ORDINARY
 * account: `isAdmin` is not settable through this route at any cost, so a single
 * compromised admin session cannot mint a second operator in one call.
 */
export async function createAdminUser(
  body: { email: string; name?: string },
  options: RequestOptions = {},
): Promise<CreatedUser> {
  return CreatedUserSchema.parse(
    await apiRequest<unknown>("/admin/users", { ...options, method: "POST", body }),
  );
}

const DeleteUserSchema = z.object({
  userId: z.string(),
  deleted: z.boolean(),
  mode: z.string(),
  deletedAt: z.string().nullable(),
  suspended: z.boolean(),
  note: z.string().optional().default(""),
});

/**
 * SOFT-delete an account. `confirmEmail` must match the target's own address —
 * the backend re-checks it and 422s a mismatch, so a mis-routed id cannot
 * delete the wrong person.
 *
 * Soft, not hard, and the caller must not describe it otherwise: every child
 * table cascades from `User.id`, so the account is stamped `deletedAt` AND
 * suspended (the enforcement every authenticated route already honours) while
 * its work and billing/audit history are preserved. `restoreAdminUser` reverses
 * it. An admin account or the §14.7 owner is refused server-side with a 409.
 */
export async function deleteAdminUser(
  userId: string,
  confirmEmail: string,
  options: RequestOptions = {},
): Promise<z.infer<typeof DeleteUserSchema>> {
  return DeleteUserSchema.parse(
    await apiRequest<unknown>(`/admin/users/${encodeURIComponent(userId)}`, {
      ...options,
      method: "DELETE",
      body: { confirmEmail },
    }),
  );
}

const RestoreUserSchema = z.object({
  userId: z.string(),
  deleted: z.boolean(),
  deletedAt: z.string().nullable(),
  suspended: z.boolean(),
  note: z.string().optional().default(""),
});

/**
 * Reverse a soft delete. Deliberately does NOT lift the suspension — restoring
 * the record and handing the account its access back are two decisions, and
 * silently un-suspending would also erase a suspension that predated the
 * delete. The response reports the surviving `suspended` flag; render it.
 */
export async function restoreAdminUser(
  userId: string,
  options: RequestOptions = {},
): Promise<z.infer<typeof RestoreUserSchema>> {
  return RestoreUserSchema.parse(
    await apiRequest<unknown>(`/admin/users/${encodeURIComponent(userId)}/restore`, {
      ...options,
      method: "POST",
      body: {},
    }),
  );
}

// --------------------------------------------------------------------------- //
// Hard deletion & orphan cleanup (ADMIN-MGMT E1/E2) — step TWO after a soft
// delete, and cleanup for billing rows a soft delete never reaches.
// --------------------------------------------------------------------------- //

const PurgeUserSchema = z.object({
  userId: z.string(),
  purged: z.literal(true),
  /** Per-child-table deleted row counts — the API's own receipt. */
  tables: z.record(z.number()),
  note: z.string().optional().default(""),
});
export type PurgeUserResult = z.infer<typeof PurgeUserSchema>;

/**
 * HARD-deletes an account and every row keyed to it, in one transaction.
 * `confirmEmail` must match the target's own address (the server re-checks
 * and 422s a mismatch — nothing is written on that path). The server also
 * refuses with an honest 409 when: the account is not ALREADY soft-deleted
 * ("purge is step two"); it is a protected admin/owner identity; or its
 * Subscription still carries a billable Stripe state. Surface those messages
 * verbatim — they are instructions, not failures to paraphrase.
 *
 * `AdminAuditLog` rows for this user are deliberately KEPT — the trail
 * survives the account it describes.
 */
export async function purgeUser(
  userId: string,
  confirmEmail: string,
  options: RequestOptions = {},
): Promise<PurgeUserResult> {
  return PurgeUserSchema.parse(
    await apiRequest<unknown>(`/admin/users/${encodeURIComponent(userId)}/purge`, {
      ...options,
      method: "POST",
      body: { confirmEmail },
    }),
  );
}

const DeleteSubscriptionRecordSchema = z.object({
  userId: z.string(),
  deleted: z.object({
    subscription: z.number(),
    usageQuota: z.number(),
  }),
});
export type DeleteSubscriptionRecordResult = z.infer<typeof DeleteSubscriptionRecordSchema>;

/**
 * Deletes the local Subscription + UsageQuota rows for a `userId` — including
 * an ORPHAN pair whose `User` row is already gone (this is the route that
 * cleans up a single one of those by id; `purgeOrphans` below sweeps the
 * whole class). Refused with the same honest 409 as `purgeUser` while the row
 * is billable-live: cancel the Stripe subscription first.
 */
export async function deleteSubscriptionRecord(
  userId: string,
  options: RequestOptions = {},
): Promise<DeleteSubscriptionRecordResult> {
  return DeleteSubscriptionRecordSchema.parse(
    await apiRequest<unknown>(`/admin/users/${encodeURIComponent(userId)}/subscription`, {
      ...options,
      method: "DELETE",
    }),
  );
}

const HygieneSampleUserSchema = z.object({
  id: z.string(),
  email: z.string().nullable().optional().default(null),
  deletedAt: z.string().nullable().optional().default(null),
});

const HygieneSchema = z.object({
  softDeletedUsers: z.object({
    count: z.number(),
    sample: z.array(HygieneSampleUserSchema).optional().default([]),
  }),
  orphanedBillingPairs: z.object({
    count: z.number(),
    sample: z.array(z.string()).optional().default([]),
  }),
  canceledSubscriptions: z.object({ count: z.number() }),
  neverLoggedIn30d: z.object({ count: z.number() }),
});
export type AdminHygiene = z.infer<typeof HygieneSchema>;

/** Read-only stale-data report. Cheap SQL only — no writes, safe to poll. */
export async function fetchHygiene(options: RequestOptions = {}): Promise<AdminHygiene> {
  return HygieneSchema.parse(await apiRequest<unknown>("/admin/hygiene", options));
}

/**
 * Deletes ONLY the orphaned-billing-pairs class `fetchHygiene` reports
 * (Subscription/UsageQuota rows whose userId has no User row) — nothing else.
 * The success body beyond an OK response is not pinned by the fixed contract,
 * so this resolves to whatever the server sends and callers should
 * re-`fetchHygiene` to see the effect rather than trust a shape here.
 */
export async function purgeOrphans(
  options: RequestOptions = {},
): Promise<Record<string, unknown>> {
  const res = await apiRequest<Record<string, unknown> | null>(
    "/admin/hygiene/purge-orphans",
    { ...options, method: "POST", body: { confirm: true } },
  );
  return res ?? {};
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
// Billing summary (revenue — AUD, distinct from LLM spend above, which is USD)
// --------------------------------------------------------------------------- //

export const AdminBillingSummarySchema = z.object({
  currency: z.string(),
  asOf: z.string().nullable().optional().default(null),
  source: z.string().optional().default(""),
  estimate: z.boolean().optional().default(true),
  gstRegistered: z.boolean().optional().default(false),
  mrrAud: z.number(),
  arrAud: z.number(),
  paidSubscribers: z.number(),
  customPricedCount: z.number().optional().default(0),
  unbackedPaidRows: z.number().optional().default(0),
  excludedAdminRows: z.number().optional().default(0),
  excludedDeletedRows: z.number().optional().default(0),
  byPlan: z
    .array(
      z.object({
        planId: z.string(),
        name: z.string().nullable().optional().default(null),
        count: z.number(),
        mrrAud: z.number(),
      }),
    )
    .optional()
    .default([]),
  byStatus: z.record(z.number()).optional().default({}),
});
export type AdminBillingSummary = z.infer<typeof AdminBillingSummarySchema>;

export async function fetchAdminBillingSummary(
  options: RequestOptions = {},
): Promise<AdminBillingSummary> {
  return AdminBillingSummarySchema.parse(
    await apiRequest<unknown>("/admin/billing/summary", options),
  );
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
