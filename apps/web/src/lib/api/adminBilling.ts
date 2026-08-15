/**
 * ADMIN-2.0 — the per-user billing surface (BE-1).
 *
 * THREE ROUTES, ONE IDEA: the local `Subscription` row and Stripe are two
 * separate sources of truth that can disagree, and the admin panel's job is to
 * show the disagreement rather than resolve it behind the reader's back.
 *
 *   GET  /admin/users/{id}/billing                 both sides + a mismatch verdict
 *   POST /admin/users/{id}/billing/reconcile-local clear a STALE LOCAL row
 *   POST /admin/users/{id}/subscription/price      negotiated amount, no proration
 *
 * WHAT NONE OF THEM DO. `reconcile-local` performs ZERO Stripe mutations — it
 * clears our row through the same handler the webhooks use, with
 * `cancel_stripe=False`. `setCustomPrice` reprices the EXISTING subscription in
 * place with `proration_behavior="none"`: no second subscription is opened, and
 * no charge, credit or refund is raised — the amount applies from the next
 * renewal. Neither call moves money, and the UI must not imply otherwise.
 *
 * THE SCHEMA IS TOLERANT BY DESIGN, LOUDLY. Stripe payload fields arrive as
 * whatever the account really has; a missing optional is `null`, never a
 * fabricated zero. What is NOT tolerated is a silently absent verdict:
 * `mismatch.evaluated` fails CLOSED to `false`, because "no mismatch" from a
 * comparison that never ran is a claim with nothing behind it.
 */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

const OptNum = z
  .number()
  .finite()
  .nullish()
  .catch(null)
  .transform((v) => v ?? null);
const OptStr = z
  .string()
  .nullish()
  .catch(null)
  .transform((v) => (typeof v === "string" ? v : null));

/** An admin-negotiated price sitting on the local row. */
const CustomPriceSchema = z.object({
  amountAud: OptNum,
  interval: OptStr,
  stripePriceId: OptStr,
  setAt: OptStr,
  setBy: OptStr,
});
export type AdminCustomPrice = z.infer<typeof CustomPriceSchema>;

export const LocalBillingRowSchema = z.object({
  planId: OptStr,
  status: OptStr,
  billingInterval: OptStr,
  stripeCustomerId: OptStr,
  stripeSubscriptionId: OptStr,
  currentPeriodStart: OptStr,
  currentPeriodEnd: OptStr,
  cancelAtPeriodEnd: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  customPrice: CustomPriceSchema.nullish()
    .catch(null)
    .transform((v) => v ?? null),
  updatedAt: OptStr,
});
export type AdminLocalBillingRow = z.infer<typeof LocalBillingRowSchema>;

const StripeCustomerSchema = z.object({
  id: OptStr,
  email: OptStr,
  name: OptStr,
  delinquent: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  created: OptStr,
});

const StripeSubscriptionSchema = z.object({
  id: OptStr,
  status: OptStr,
  cancelAtPeriodEnd: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  currentPeriodEnd: OptStr,
  amountAud: OptNum,
  interval: OptStr,
  priceId: OptStr,
});
export type AdminStripeSubscription = z.infer<typeof StripeSubscriptionSchema>;

const StripeInvoiceSchema = z.object({
  id: OptStr,
  amountPaidAud: OptNum,
  status: OptStr,
  created: OptStr,
  hostedInvoiceUrl: OptStr.optional(),
});
export type AdminStripeInvoice = z.infer<typeof StripeInvoiceSchema>;

/** Brand + last four + expiry — the only payment-method fields Stripe exposes. */
const PaymentMethodSchema = z.object({
  brand: OptStr,
  last4: OptStr,
  expMonth: OptNum,
  expYear: OptNum,
});

function lenientRows<T extends z.ZodTypeAny>(row: T) {
  return z
    .array(z.unknown())
    .nullish()
    .catch(null)
    .transform((rows) =>
      (rows ?? []).flatMap((r) => {
        const parsed = row.safeParse(r);
        return parsed.success ? [parsed.data as z.infer<T>] : [];
      }),
    );
}

export const StripeTruthSchema = z.object({
  /**
   * FALSE means Stripe could not be read — NOT that Stripe holds nothing. The
   * two look identical in an empty payload and confusing them could talk an
   * admin into clearing a live customer's row, so `reason` carries the why.
   */
  available: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  reason: OptStr,
  customer: StripeCustomerSchema.nullish()
    .catch(null)
    .transform((v) => v ?? null),
  subscription: StripeSubscriptionSchema.nullish()
    .catch(null)
    .transform((v) => v ?? null),
  subscriptions: lenientRows(z.object({ id: OptStr, status: OptStr })),
  invoices: lenientRows(StripeInvoiceSchema),
  paymentMethod: PaymentMethodSchema.nullish()
    .catch(null)
    .transform((v) => v ?? null),
  note: OptStr.optional(),
});
export type AdminStripeTruth = z.infer<typeof StripeTruthSchema>;

export const MismatchSchema = z.object({
  /** Fails CLOSED: an absent verdict means the comparison did not run. */
  evaluated: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  hasMismatch: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  reasons: z
    .array(z.string())
    .nullish()
    .catch(null)
    .transform((v) => v ?? []),
});
export type AdminBillingMismatch = z.infer<typeof MismatchSchema>;

export const UserBillingSchema = z.object({
  userId: z.string(),
  currency: z.string().optional().default("AUD"),
  local: LocalBillingRowSchema.nullish()
    .catch(null)
    .transform((v) => v ?? null),
  stripe: StripeTruthSchema,
  mismatch: MismatchSchema,
});
export type AdminUserBilling = z.infer<typeof UserBillingSchema>;

export async function fetchUserBilling(
  userId: string,
  options: RequestOptions = {},
): Promise<AdminUserBilling> {
  return UserBillingSchema.parse(
    await apiRequest<unknown>(`/admin/users/${encodeURIComponent(userId)}/billing`, options),
  );
}

const ReconcileSchema = z.object({
  userId: z.string(),
  reconciled: z.boolean(),
  before: z.record(z.unknown()).nullish().transform((v) => v ?? {}),
  after: z.record(z.unknown()).nullish().transform((v) => v ?? {}),
  /** Which Stripe answer authorised the clear — never assumed, always reported. */
  stripeChecked: OptStr,
  /** Always false. The route makes no Stripe call; the flag proves it in the payload. */
  stripeMutated: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
});

/**
 * Clear a stale LOCAL subscription row. Makes no Stripe call whatsoever.
 *
 * Stripe is consulted FIRST and its answer is binding: a live subscription is a
 * 409 (the row is correct, not stale), and a Stripe read that cannot be
 * performed is a 503 rather than an assumption. Surface both verbatim.
 */
export async function reconcileLocalBilling(
  userId: string,
  options: RequestOptions = {},
): Promise<z.infer<typeof ReconcileSchema>> {
  return ReconcileSchema.parse(
    await apiRequest<unknown>(
      `/admin/users/${encodeURIComponent(userId)}/billing/reconcile-local`,
      { ...options, method: "POST", body: {} },
    ),
  );
}

const CustomPriceResponseSchema = z.object({
  userId: z.string(),
  amountAud: z.number(),
  interval: z.string(),
  currency: z.string().optional().default("AUD"),
  planId: OptStr,
  stripePriceId: OptStr,
  stripeSubscriptionId: OptStr,
  prorationBehavior: OptStr,
  /** "next_renewal" — this call raises no invoice today. */
  effectiveFrom: OptStr,
  note: OptStr,
});

/**
 * Set a negotiated subscription amount for ONE customer.
 *
 * The customer's existing Stripe subscription is repriced IN PLACE: a new Price
 * (a catalogue entry that charges nobody) is created and the subscription's
 * single line item points at it, with no proration. A second subscription is
 * never opened — the failure PAY-R1-02 / PAY-R3-01 exist to prevent. An account
 * with no live Stripe subscription is an honest 409; the lever for that case is
 * an entitlement override.
 */
export async function setCustomPrice(
  userId: string,
  body: { amountAud: number; interval: "month" | "year" },
  options: RequestOptions = {},
): Promise<z.infer<typeof CustomPriceResponseSchema>> {
  return CustomPriceResponseSchema.parse(
    await apiRequest<unknown>(
      `/admin/users/${encodeURIComponent(userId)}/subscription/price`,
      { ...options, method: "POST", body },
    ),
  );
}
