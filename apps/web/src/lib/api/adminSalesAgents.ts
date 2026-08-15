/**
 * ADMIN-2.0 — sales agents, referral attribution and commission reports (BE-2).
 *
 * A sales agent is a human reseller with a referral code. Accounts that sign up
 * through `/signup?ref=CODE` are attributed to them, and the report values that
 * attribution against what those accounts REALLY paid.
 *
 * THERE IS NO DELETE FUNCTION IN THIS MODULE, and that is not an omission.
 * `DELETE /admin/sales-agents/{id}` is a 405 — there is no route to call. A
 * distributed code lives on in links and in the attribution history of every
 * account it brought in, so "remove" means `updateSalesAgent(id, {status:
 * "inactive"})`: the code stops attributing and the earned history stays
 * readable. `referralCode` is immutable after creation for the same reason.
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

export const SALES_AGENT_STATUSES = ["active", "inactive"] as const;
export type SalesAgentStatus = (typeof SALES_AGENT_STATUSES)[number];

export const SalesAgentSchema = z.object({
  id: z.string(),
  name: z.string(),
  email: OptStr,
  referralCode: z.string(),
  commissionPct: z.number(),
  status: z.string(),
  notes: OptStr,
  createdAt: OptStr,
  updatedAt: OptStr,
  createdBy: OptStr,
  /**
   * REAL counts from real rows — absent only on a payload that did not carry
   * them, in which case they are `null` and must be rendered as unknown rather
   * than as zero (an agent with 7 signups shown as 0 is a lie about their pay).
   */
  attributedSignups: OptNum,
  convertedPaid: OptNum,
});
export type SalesAgent = z.infer<typeof SalesAgentSchema>;

const SalesAgentListSchema = z.object({
  agents: z.array(SalesAgentSchema),
  total: z.number(),
});

export async function fetchSalesAgents(
  status?: SalesAgentStatus,
  options: RequestOptions = {},
): Promise<z.infer<typeof SalesAgentListSchema>> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return SalesAgentListSchema.parse(
    await apiRequest<unknown>(`/admin/sales-agents${qs}`, options),
  );
}

export interface CreateSalesAgentInput {
  name: string;
  email?: string;
  /** Omit to let the server mint one with `secrets`. */
  referralCode?: string;
  commissionPct?: number;
  notes?: string;
}

export async function createSalesAgent(
  body: CreateSalesAgentInput,
  options: RequestOptions = {},
): Promise<SalesAgent> {
  return SalesAgentSchema.parse(
    await apiRequest<unknown>("/admin/sales-agents", { ...options, method: "POST", body }),
  );
}

/**
 * Update an agent. `status: "inactive"` IS the delete. `referralCode` is
 * deliberately absent from this type: the backend 422s an attempt to change it,
 * because the code is already printed on links the agent has handed out.
 */
export async function updateSalesAgent(
  agentId: string,
  patch: {
    name?: string;
    email?: string | null;
    notes?: string | null;
    commissionPct?: number;
    status?: SalesAgentStatus;
  },
  options: RequestOptions = {},
): Promise<SalesAgent> {
  return SalesAgentSchema.parse(
    await apiRequest<unknown>(`/admin/sales-agents/${encodeURIComponent(agentId)}`, {
      ...options,
      method: "PATCH",
      body: patch,
    }),
  );
}

const ReportEntrySchema = z.object({
  userId: z.string(),
  email: OptStr,
  name: OptStr,
  signedUpAt: OptStr,
  deleted: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  planId: OptStr,
  subStatus: OptStr,
  stripeCustomerId: OptStr,
  /**
   * Non-null when two attributed accounts point at ONE Stripe customer: the
   * later account is reported at A$0 so the same money is not credited twice.
   * Shown, never netted out in silence.
   */
  sharesStripeCustomerWith: OptStr,
  converted: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  paymentCount: OptNum,
  grossPaidAud: OptNum,
  refundedAud: OptNum,
  netPaidAud: OptNum,
});
export type SalesAgentReportEntry = z.infer<typeof ReportEntrySchema>;

const ReportTotalsSchema = z.object({
  attributedUsers: OptNum,
  convertedUsers: OptNum,
  payingUsers: OptNum,
  paymentCount: OptNum,
  grossPaidAud: OptNum,
  refundedAud: OptNum,
  netPaidAud: OptNum,
  commissionAud: OptNum,
});

export const SalesAgentReportSchema = z.object({
  agent: SalesAgentSchema,
  asOf: OptStr,
  currency: z.string().optional().default("AUD"),
  commissionPct: z.number(),
  /** Always true. This endpoint writes nothing and pays nobody. */
  reportOnly: z.boolean().nullish().catch(true).transform((v) => v ?? true),
  payoutPerformed: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  gstRegistered: z.boolean().nullish().catch(false).transform((v) => Boolean(v)),
  source: OptStr,
  attributedUsers: z.array(ReportEntrySchema).nullish().transform((v) => v ?? []),
  totals: ReportTotalsSchema,
  otherCurrencies: z.record(z.unknown()).nullish().transform((v) => v ?? {}),
  /**
   * A FRACTION (0..1), or `null` when the sample is below `rateSampleFloor`.
   * The money totals above stay EXACT at any N — only this derived rate is
   * suppressed, because a percentage of three accounts reads as precision the
   * data does not have.
   */
  conversionRate: OptNum,
  sampleSize: OptNum,
  rateSampleFloor: OptNum,
  insufficientData: z.boolean().nullish().catch(true).transform((v) => v ?? true),
  // Disclosure counters — a record the report could not read is SHOWN.
  unparsablePaymentEvents: OptNum,
  refundEventsWithNoCustomer: OptNum,
  sharedStripeCustomerAccounts: OptNum,
});
export type SalesAgentReport = z.infer<typeof SalesAgentReportSchema>;

export async function fetchSalesAgentReport(
  agentId: string,
  options: RequestOptions = {},
): Promise<SalesAgentReport> {
  return SalesAgentReportSchema.parse(
    await apiRequest<unknown>(
      `/admin/sales-agents/${encodeURIComponent(agentId)}/report`,
      options,
    ),
  );
}

// --------------------------------------------------------------------------- //
// Referral codes and links
// --------------------------------------------------------------------------- //

/** The backend's own alphabet: no I/L/O/0/1, so a code read aloud is unambiguous. */
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

/** Mirrors the server's `normalize_referral_code` so the admin sees what will be stored. */
export function normalizeReferralCode(raw: string): string {
  return raw.trim().toUpperCase();
}

/** 2-32 chars of A-Z/0-9/'-', not starting with '-' — the server's own rule. */
export function isValidReferralCode(code: string): boolean {
  return /^[A-Z0-9][A-Z0-9-]{1,31}$/.test(normalizeReferralCode(code));
}

/**
 * Suggest a referral code for `name`, in the server's `SLUG-XXXXXXXX` shape.
 *
 * CSPRNG OR NOTHING. The backend mints codes with `secrets` precisely because a
 * guessable referral code is an attribution somebody else can claim, so this
 * suggestion uses `crypto.getRandomValues` — and returns `null` rather than
 * falling back to `Math.random` when no CSPRNG is present. A null suggestion
 * simply leaves the field blank, and the server mints the code instead; a weak
 * one would look identical to a strong one while being worth less.
 */
export function suggestReferralCode(name: string): string | null {
  const slug = (name || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8) || "REF";
  const cryptoObj = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (!cryptoObj || typeof cryptoObj.getRandomValues !== "function") return null;
  const bytes = new Uint8Array(8);
  cryptoObj.getRandomValues(bytes);
  // Rejection-free indexing would bias the alphabet slightly; the bias here is
  // over a 31-symbol alphabet from 256 values (≈0.4%) and does not weaken the
  // code meaningfully, but the modulo is applied to a fresh CSPRNG byte per
  // character rather than to one seed.
  const suffix = Array.from(bytes, (b) => CODE_ALPHABET[b % CODE_ALPHABET.length]).join("");
  return `${slug}-${suffix}`;
}

/**
 * The link an agent distributes. `origin` defaults to the deployment the admin
 * is looking at, so a code copied from a staging host never points at prod.
 */
export function referralLink(code: string, origin?: string): string {
  const base =
    origin ?? (typeof window !== "undefined" ? window.location.origin : "");
  return `${base}/signup?ref=${encodeURIComponent(normalizeReferralCode(code))}`;
}
