/**
 * ADMIN-2.0 — promotion codes (BE-1).
 *
 * STRIPE IS THE SOURCE OF TRUTH. There is no local mirror of these objects, so
 * nothing here can drift out of sync with the Dashboard: the list IS what
 * `GET /admin/promos` read back from Stripe.
 *
 * MONEY SAFETY. Creating a Coupon and its PromotionCode charges nobody — money
 * only moves when a customer redeems the code at their own checkout. Removal is
 * a DEACTIVATION (`active=false`), never a coupon delete: it is reversible and
 * it preserves the redemption history of everyone who already used the code.
 * Callers must label it that way.
 *
 * A 503 from any of these routes means Stripe is not configured on this
 * deployment. That is emphatically NOT "there are no promotions", and rendering
 * it as an empty list would be a fabricated fact about the account.
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

export const PROMO_DURATIONS = ["once", "repeating", "forever"] as const;
export type PromoDuration = (typeof PROMO_DURATIONS)[number];

export const PromoSchema = z.object({
  id: z.string(),
  code: z.string(),
  active: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  couponId: OptStr,
  /** Exactly one of these two is set — a coupon is either % off or an amount off. */
  percentOff: OptNum,
  amountOffAud: OptNum,
  duration: OptStr,
  timesRedeemed: OptNum,
  maxRedemptions: OptNum,
  expiresAt: OptStr,
});
export type AdminPromo = z.infer<typeof PromoSchema>;

const PromoListSchema = z.object({
  promos: z.array(PromoSchema).nullish().transform((v) => v ?? []),
  total: z.number().nullish().transform((v) => v ?? 0),
});

export async function fetchPromos(
  options: RequestOptions = {},
): Promise<z.infer<typeof PromoListSchema>> {
  return PromoListSchema.parse(await apiRequest<unknown>("/admin/promos", options));
}

/**
 * `percentOff` XOR `amountOffAud` — the backend 422s both or neither, so the
 * caller decides which one it is sending rather than passing both as optional
 * and hoping.
 */
export interface CreatePromoInput {
  percentOff?: number;
  amountOffAud?: number;
  duration: PromoDuration;
  /** Required (and only meaningful) when `duration` is "repeating". */
  durationInMonths?: number;
  /** Omit to let Stripe generate a code. Stored uppercase either way. */
  code?: string;
  maxRedemptions?: number;
  name?: string;
}

const CreatedPromoSchema = z.object({
  promotionCodeId: z.string(),
  code: z.string(),
  couponId: OptStr,
  percentOff: OptNum,
  amountOffAud: OptNum,
  duration: OptStr,
  durationInMonths: OptNum,
  maxRedemptions: OptNum,
  expiresAt: OptStr,
  active: z.boolean().nullish().catch(true).transform((v) => v ?? true),
  currency: z.string().optional().default("AUD"),
});
export type CreatedPromo = z.infer<typeof CreatedPromoSchema>;

export async function createPromo(
  body: CreatePromoInput,
  options: RequestOptions = {},
): Promise<CreatedPromo> {
  return CreatedPromoSchema.parse(
    await apiRequest<unknown>("/admin/promos", { ...options, method: "POST", body }),
  );
}

const DeactivateSchema = z.object({
  promotionCodeId: z.string(),
  active: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
});

/** Deactivate (not delete) a promotion code. Reversible in the Stripe Dashboard. */
export async function deactivatePromo(
  promotionCodeId: string,
  options: RequestOptions = {},
): Promise<z.infer<typeof DeactivateSchema>> {
  return DeactivateSchema.parse(
    await apiRequest<unknown>(`/admin/promos/${encodeURIComponent(promotionCodeId)}`, {
      ...options,
      method: "DELETE",
    }),
  );
}

/** How a promotion reads in one line: "20% off, once" / "A$10 off, 3 months". */
export function describeDiscount(promo: {
  percentOff: number | null;
  amountOffAud: number | null;
  duration: string | null;
}): string {
  const value =
    promo.percentOff !== null
      ? `${promo.percentOff}% off`
      : promo.amountOffAud !== null
        ? `A$${promo.amountOffAud.toFixed(2)} off`
        : "discount unknown";
  const when =
    promo.duration === "forever"
      ? "every invoice"
      : promo.duration === "repeating"
        ? "repeating"
        : promo.duration === "once"
          ? "first invoice only"
          : null;
  return when ? `${value} · ${when}` : value;
}
