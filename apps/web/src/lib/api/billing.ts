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

export const GstBreakdownSchema = z.object({
  total: z.number(),
  gst: z.number(),
  net: z.number(),
});
export type GstBreakdown = z.infer<typeof GstBreakdownSchema>;

export const PlanSchema = z.object({
  id: z.string(),
  name: z.string(),
  modelTier: z.string(),
  runsPerMonth: z.number(),
  monthly: GstBreakdownSchema,
  annual: GstBreakdownSchema.nullable(),
  features: z.array(z.string()),
  purchasable: z.boolean(),
});
export type Plan = z.infer<typeof PlanSchema>;

export const PlansResponseSchema = z.object({
  currency: z.string(),
  gstIncluded: z.boolean(),
  plans: z.array(PlanSchema),
});
export type PlansResponse = z.infer<typeof PlansResponseSchema>;

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
export interface CheckoutRedirectResult {
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
export interface CheckoutSwitchedResult {
  switched: true;
  planId: string;
  message: string;
}

export type CheckoutResult = CheckoutRedirectResult | CheckoutSwitchedResult;

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

export const SubscriptionStateSchema = z.object({
  plan: z
    .object({ id: z.string(), name: z.string(), modelTier: z.string() })
    .nullable(),
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
export const EntitlementSchema = z.object({
  active_paid: z.boolean(),
  plan: z.object({ id: z.string(), status: z.string() }).nullable(),
  requiresSubscription: z.boolean(),
});
export type Entitlement = z.infer<typeof EntitlementSchema>;

export async function fetchEntitlement(
  options: RequestOptions = {},
): Promise<Entitlement> {
  return EntitlementSchema.parse(
    await apiRequest<unknown>("/billing/entitlement", options),
  );
}
