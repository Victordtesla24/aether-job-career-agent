/**
 * Billing API client (GAP-P6-BILL-001 / PRICING-001).
 *
 * `fetchPlans` is PUBLIC — it hits GET /billing/plans with no bearer token, so
 * the /pricing page renders for logged-out visitors (the generic authenticated
 * `apiRequest` would redirect them to /login). `startCheckout`,
 * `fetchSubscription` and `openBillingPortal` are authenticated and reuse the
 * shared `apiRequest`.
 */
import { z } from "zod";

import { apiBaseUrl, apiRequest, type RequestOptions } from "./client";

const GstBreakdownSchema = z.object({
  total: z.number(),
  gst: z.number(),
  net: z.number(),
});

/**
 * AUD-MON-1: the public plan catalog carries ONLY the two facts the backend
 * enforces — the monthly agent-run quota (`runsPerMonth`) and the monthly AI
 * spend cap (`spendCapUsdMonthly`), plus `features` bullets derived from them
 * server-side (apps/api/app/routers/billing.py `_enforced_facts`). The old
 * unenforced `modelTier` label is gone from the payload, so it is gone from
 * this contract too; per-plan feature/model gating is deferred, not shipped.
 */
export const PlanSchema = z.object({
  id: z.string(),
  name: z.string(),
  runsPerMonth: z.number(),
  spendCapUsdMonthly: z.number(),
  monthly: GstBreakdownSchema,
  annual: GstBreakdownSchema.nullable(),
  features: z.array(z.string()),
  purchasable: z.boolean(),
});
export type Plan = z.infer<typeof PlanSchema>;

const PlansResponseSchema = z.object({
  currency: z.string(),
  gstIncluded: z.boolean(),
  plans: z.array(PlanSchema),
});
type PlansResponse = z.infer<typeof PlansResponseSchema>;

/** PUBLIC — no auth token attached. */
export async function fetchPlans(baseUrl: string = apiBaseUrl()): Promise<PlansResponse> {
  const res = await fetch(`${baseUrl}/billing/plans`, {
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    throw new Error(`Failed to load plans (${res.status})`);
  }
  return PlansResponseSchema.parse(await res.json());
}

/** The default outcome — redirect the browser to Stripe Checkout. */
interface CheckoutRedirectResult {
  checkoutUrl: string;
  sessionId: string;
}

/**
 * The alternative outcome for an existing paid subscriber who chose a
 * DIFFERENT plan (PAY-R3-01 fix): the backend switches the existing Stripe
 * subscription's price server-side instead of starting a second, independent
 * subscription (which previously double-billed the customer). No redirect —
 * the caller re-fetches subscription state and shows `message` in place of
 * a Checkout redirect.
 */
interface CheckoutSwitchedResult {
  switched: true;
  planId: string;
  message: string;
}

type CheckoutResult = CheckoutRedirectResult | CheckoutSwitchedResult;

/** Narrows a `CheckoutResult` to the "switched in place" branch. */
export function isCheckoutSwitchedResult(
  result: CheckoutResult,
): result is CheckoutSwitchedResult {
  return (result as CheckoutSwitchedResult).switched === true;
}

export async function startCheckout(
  planId: string,
  interval: "month" | "year",
  options: RequestOptions = {},
): Promise<CheckoutResult> {
  return apiRequest<CheckoutResult>("/billing/checkout", {
    ...options,
    method: "POST",
    body: { planId, interval },
  });
}

/**
 * The ONE server-side entitlement verdict (ADMIN-FULL), echoed onto both
 * `/billing/subscription` and `/billing/entitlement`. `unlimited` means the
 * backend enforces NO quota, spend cap, paywall or per-user rate limit for this
 * account — admins/owners, and users an admin granted an unlimited entitlement.
 *
 * `activePaid` deliberately keeps reporting the REAL billing truth, so an
 * entitlement grant is always visibly a grant and never masquerades as a
 * payment. Every field is optional-with-default so an older API build still
 * parses (the UI then renders exactly what it rendered before).
 */
export const EntitlementViewSchema = z.object({
  unlimited: z.boolean().optional().default(false),
  entitled: z.boolean().optional().default(false),
  source: z.string().optional().default("plan"),
  isAdmin: z.boolean().optional().default(false),
  planId: z.string().nullable().optional().default(null),
  activePaid: z.boolean().optional().default(false),
  overrideActive: z.boolean().optional().default(false),
  overrideKind: z.string().nullable().optional().default(null),
  overridePlanId: z.string().nullable().optional().default(null),
  overrideNote: z.string().nullable().optional().default(null),
  overrideSetBy: z.string().nullable().optional().default(null),
  overrideSetAt: z.string().nullable().optional().default(null),
});
export type EntitlementView = z.infer<typeof EntitlementViewSchema>;

export const SubscriptionStateSchema = z.object({
  // AUD-MON-1: identity only — the backend no longer transmits the unenforced
  // `modelTier` label here either (the enforced numbers live in `quota`).
  plan: z.object({ id: z.string(), name: z.string() }).nullable(),
  status: z.string().nullable(),
  interval: z.string().nullable(),
  currentPeriodEnd: z.string().nullable(),
  cancelAtPeriodEnd: z.boolean(),
  quota: z
    .object({
      runsUsed: z.number(),
      runsAllowed: z.number(),
      spendUsedUsd: z.number(),
      spendCapUsd: z.number(),
      periodEnd: z.string().nullable(),
    })
    .nullable(),
  entitlement: EntitlementViewSchema.optional().default({}),
});
export type SubscriptionState = z.infer<typeof SubscriptionStateSchema>;

export async function fetchSubscription(
  options: RequestOptions = {},
): Promise<SubscriptionState> {
  return SubscriptionStateSchema.parse(
    await apiRequest<unknown>("/billing/subscription", options),
  );
}

export async function openBillingPortal(
  options: RequestOptions = {},
): Promise<{ portalUrl: string }> {
  return apiRequest<{ portalUrl: string }>("/billing/portal", {
    ...options,
    method: "POST",
    body: {},
  });
}

/**
 * Subscription entitlement (GAP-P6-PAYWALL). `active_paid` mirrors the backend
 * gate (status='active' AND planId != 'free'); `requiresSubscription` reflects
 * the operator flag, so the dashboard shows its paywall IFF the gate is enforced.
 */
const EntitlementSchema = z.object({
  active_paid: z.boolean(),
  plan: z.object({ id: z.string(), status: z.string() }).nullable(),
  requiresSubscription: z.boolean(),
  // ADMIN-FULL: the resolver's verdict. `unlimited` is what suppresses the
  // paywall for an admin/owner — a real server-side exemption reflected in the
  // UI, never a frontend-only bypass. Optional-with-default so an older API
  // build behaves exactly as it did before.
  unlimited: z.boolean().optional().default(false),
  entitled: z.boolean().optional().default(false),
  source: z.string().optional().default("plan"),
  isAdmin: z.boolean().optional().default(false),
  overrideActive: z.boolean().optional().default(false),
  overrideKind: z.string().nullable().optional().default(null),
});
type Entitlement = z.infer<typeof EntitlementSchema>;

export async function fetchEntitlement(
  options: RequestOptions = {},
): Promise<Entitlement> {
  return EntitlementSchema.parse(
    await apiRequest<unknown>("/billing/entitlement", {
      timeoutMs: 12_000,
      ...options,
    }),
  );
}
