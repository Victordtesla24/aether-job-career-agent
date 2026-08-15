import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

const AdminPlanSchema = z.object({
  id: z.string(),
  name: z.string(),
  priceAudMonthly: z.number().finite(),
  priceAudAnnual: z.number().finite().nullable(),
  stripeProductId: z.string().nullable(),
  stripePriceIdMonthly: z.string().nullable(),
  stripePriceIdAnnual: z.string().nullable(),
  active: z.boolean(),
});

export type AdminPlan = z.infer<typeof AdminPlanSchema>;

const AdminPlansResponseSchema = z.object({ plans: z.array(AdminPlanSchema) });

export async function fetchAdminPlans(
  options: RequestOptions = {},
): Promise<z.infer<typeof AdminPlansResponseSchema>> {
  return AdminPlansResponseSchema.parse(await apiRequest<unknown>("/admin/plans", options));
}

export interface PlanPricingUpdate {
  priceAudMonthly?: number;
  priceAudAnnual?: number | null;
}

const UpdatedPricingSchema = z.object({
  id: z.string(),
  name: z.string(),
  priceAudMonthly: z.number().finite(),
  priceAudAnnual: z.number().finite().nullable(),
  currency: z.literal("AUD"),
});

export async function updatePlanPricing(
  planId: string,
  pricing: PlanPricingUpdate,
  options: RequestOptions = {},
): Promise<z.infer<typeof UpdatedPricingSchema>> {
  return UpdatedPricingSchema.parse(
    await apiRequest<unknown>(`/admin/plans/${encodeURIComponent(planId)}/pricing`, {
      ...options,
      method: "PUT",
      body: pricing,
    }),
  );
}