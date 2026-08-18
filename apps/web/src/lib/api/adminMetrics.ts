/**
 * ADMIN-2.0 FE-1 — client for `GET /admin/metrics/executive` (BE-2).
 *
 * ============================================================================
 * THE CONTRACT, AND WHERE IT COMES FROM
 * ============================================================================
 * These types are transcribed from BE-2's own payload builder,
 * `apps/api/app/repositories/admin_metrics.py` › `executive_metrics()`, not
 * from a guess. Three of its design decisions shape this entire frontend and
 * are repeated here because they are easy to undo by accident:
 *
 * 1. NO MARGIN, NO FX. `costVsRevenue` reports `llmCostUsd` and `revenueAud`
 *    SIDE BY SIDE and sets `fxRateApplied: null`. The API refuses to net them
 *    because no exchange rate is available to it, and says so in `note`. The
 *    dashboard must not do the division the API declined to do.
 *
 * 2. `insufficientData` SUPPRESSES A RATE, NOT A COUNT. Every block carries
 *    `sampleSize` and `insufficientData` (`sampleSize < insufficientDataThreshold`,
 *    20 today). BE-2's module docstring is explicit: "Small numbers are shown
 *    as they are; what is suppressed is the RATE-shaped reading of them." So a
 *    count with `insufficientData: true` is still a real count and is still
 *    shown; a percentage, a trend reading or a conversion rate is not.
 *
 * 3. FUNNEL STAGES ARE NOT NESTED. `funnel.definitions._shape` states that the
 *    stages are INDEPENDENT milestone counts over the same signup population,
 *    so a later stage can legitimately exceed an earlier one. A step-to-step
 *    "drop-off" division would therefore be a misreading of the data; the
 *    API's own `shareOfSignups` (a FRACTION, 0..1) is the correct denominator.
 *
 * ============================================================================
 * WHY THE SCHEMA IS TOLERANT — AND WHY THAT IS NOT A SILENT FALLBACK
 * ============================================================================
 * BE-2 lands on the same branch as this slice and may still move. A strict
 * schema would turn any drift into a white screen on the owner's dashboard; a
 * quietly lenient one would fill the board with confident zeroes. So absence is
 * modelled explicitly and LOUDLY: a missing block parses to `null` and every
 * consumer renders `SECTION_ABSENT_REASON`; a missing, NaN or infinite figure
 * parses to `null`, never to 0; and `insufficientData` fails closed.
 */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

/** Rendered verbatim wherever the payload simply did not carry a block. */
export const SECTION_ABSENT_REASON =
  "GET /admin/metrics/executive did not return this block.";

/** A finite number, or `null`. NaN, Infinity, absence and garbage all → null. */
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

/** Fail closed: a block that does not declare its own sufficiency is unproven. */
const InsufficientData = z
  .boolean()
  .nullish()
  .catch(true)
  .transform((v) => (typeof v === "boolean" ? v : true));

/**
 * An array whose MALFORMED ROWS ARE DROPPED rather than taking the whole
 * dashboard down with them. Bounded deliberately: a row is kept only when it
 * parses, and a row that fails is gone — never replaced by a placeholder a
 * reader could mistake for a real record.
 */
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

/** A block that may be absent entirely. Absent → `null`, never `{}`. */
function optionalBlock<T extends z.ZodTypeAny>(block: T) {
  return block
    .nullish()
    .catch(null)
    .transform((v) => (v ?? null) as z.infer<T> | null);
}

// --------------------------------------------------------------------------- //
// Rows
// --------------------------------------------------------------------------- //

const PlanBucketSchema = z.object({
  planId: z.string(),
  name: OptStr,
  count: OptNum,
  mrrAud: OptNum,
});
export type AdminPlanBucket = z.infer<typeof PlanBucketSchema>;

const SignupDaySchema = z.object({ date: z.string(), count: OptNum });
export type AdminSignupDay = z.infer<typeof SignupDaySchema>;

const RunDaySchema = z.object({ date: z.string(), runs: OptNum, costUsd: OptNum });
export type AdminRunDay = z.infer<typeof RunDaySchema>;

/** C-5: a stage with no label cannot be drawn honestly, so it is dropped. */
const FunnelStageSchema = z.object({
  key: z.string(),
  label: z.string().min(1),
  count: OptNum,
  /** A FRACTION (0..1), not a percentage. `null` when there is no population. */
  shareOfSignups: OptNum,
});
export type AdminFunnelStage = z.infer<typeof FunnelStageSchema>;

const ReferrerAgentSchema = z.object({
  id: z.string(),
  name: OptStr,
  referralCode: OptStr,
  status: OptStr,
  commissionPct: OptNum,
  attributedSignups: OptNum,
  convertedPaid: OptNum,
});
export type AdminReferrerAgent = z.infer<typeof ReferrerAgentSchema>;

// --------------------------------------------------------------------------- //
// Blocks
// --------------------------------------------------------------------------- //

const RevenueSchema = z.object({
  currency: OptStr,
  estimate: z
    .boolean()
    .nullish()
    .catch(true)
    .transform((v) => (typeof v === "boolean" ? v : true)),
  source: OptStr,
  mrrAud: OptNum,
  arrAud: OptNum,
  paidSubscribers: OptNum,
  customPricedCount: OptNum,
  /** Local rows that read paid with nothing behind them at Stripe. */
  unbackedPaidRows: OptNum,
  excludedAdminRows: OptNum,
  excludedDeletedRows: OptNum,
  byPlan: lenientRows(PlanBucketSchema),
  sampleSize: OptNum,
  insufficientData: InsufficientData,
});
export type AdminRevenueBlock = z.infer<typeof RevenueSchema>;

const SignupsByDaySchema = z.object({
  series: lenientRows(SignupDaySchema),
  total: OptNum,
  windowDays: OptNum,
  /** The API's own words for what the series leaves out. Rendered verbatim. */
  excludes: OptStr,
  sampleSize: OptNum,
  insufficientData: InsufficientData,
});
export type AdminSignupsBlock = z.infer<typeof SignupsByDaySchema>;

const RunsByDaySchema = z.object({
  series: lenientRows(RunDaySchema),
  totalRuns: OptNum,
  totalCostUsd: OptNum,
  currency: OptStr,
  windowDays: OptNum,
  includes: OptStr,
  sampleSize: OptNum,
  insufficientData: InsufficientData,
});
export type AdminRunsBlock = z.infer<typeof RunsByDaySchema>;

const FunnelSchema = z.object({
  window: OptStr,
  stages: lenientRows(FunnelStageSchema),
  /**
   * The API's own definition of each stage, INCLUDING `_shape` — the statement
   * that the stages are independent milestone counts rather than nested
   * subsets. Kept as a permissive record because BE-2 owns these keys.
   */
  definitions: z
    .record(z.string())
    .nullish()
    .catch(null)
    .transform((v) => v ?? null),
  sampleSize: OptNum,
  insufficientData: InsufficientData,
});
export type AdminFunnelBlock = z.infer<typeof FunnelSchema>;

const CostVsRevenueSchema = z.object({
  windowDays: OptNum,
  llmCostUsd: OptNum,
  grossRevenueAud: OptNum,
  refundsAud: OptNum,
  revenueAud: OptNum,
  paymentCount: OptNum,
  /**
   * `null` means the API applied NO exchange rate — so the two money figures
   * above are not comparable as printed, and no margin may be derived from
   * them. A non-null value would be the API taking responsibility for a rate.
   */
  fxRateApplied: OptNum,
  /** The API's own explanation. Rendered verbatim on the tile. */
  note: OptStr,
  revenueSource: OptStr,
  unparsablePaymentEvents: OptNum,
  unattributedRefundEvents: OptNum,
  sampleSize: OptNum,
  insufficientData: InsufficientData,
});
export type AdminCostVsRevenueBlock = z.infer<typeof CostVsRevenueSchema>;

const TopReferrersSchema = z.object({
  agents: lenientRows(ReferrerAgentSchema),
  totalAgentsWithSignups: OptNum,
  totalAttributedSignups: OptNum,
  limit: OptNum,
  sampleSize: OptNum,
  insufficientData: InsufficientData,
});
export type AdminTopReferrersBlock = z.infer<typeof TopReferrersSchema>;

const ExcludedSchema = z.object({
  adminAccounts: OptNum,
  deletedAccounts: OptNum,
});
export type AdminExcludedBlock = z.infer<typeof ExcludedSchema>;

const FailedRuns24hSchema = z.object({
  failed: OptNum,
  total: OptNum,
  rate: OptNum,
  windowHours: OptNum,
  sampleSize: OptNum,
  insufficientData: InsufficientData,
});
export type AdminFailedRuns24hBlock = z.infer<typeof FailedRuns24hSchema>;

const SalesAiSchema = z.object({
  enabled: z.boolean().nullish().catch(null).transform((v) => (typeof v === "boolean" ? v : null)),
  dryRun: z.boolean().nullish().catch(null).transform((v) => (typeof v === "boolean" ? v : null)),
  emailsSent: OptNum,
  dryRunLogged: OptNum,
  repliesObserved: OptNum,
  replyRate: OptNum,
  leads: OptNum,
  linkedinDraftsQueued: OptNum,
  llmCostUsd30d: OptNum,
  attributedSignups: OptNum,
  attributedPaid: OptNum,
  cannotAttributeSignups: z
    .boolean()
    .nullish()
    .catch(null)
    .transform((v) => (typeof v === "boolean" ? v : null)),
  cannotAttributeReason: OptStr,
  sampleSize: OptNum,
  insufficientData: InsufficientData,
});
export type AdminSalesAiBlock = z.infer<typeof SalesAiSchema>;

export const AdminExecutiveMetricsSchema = z.object({
  asOf: OptStr,
  windowDays: OptNum,
  currencies: optionalBlock(z.object({ revenue: OptStr, llmCost: OptStr })),
  gstRegistered: z
    .boolean()
    .nullish()
    .catch(null)
    .transform((v) => (typeof v === "boolean" ? v : null)),
  /** The sample size below which the API considers a RATE unreadable. */
  insufficientDataThreshold: OptNum,
  revenue: optionalBlock(RevenueSchema),
  signupsByDay: optionalBlock(SignupsByDaySchema),
  runsByDay: optionalBlock(RunsByDaySchema),
  funnel: optionalBlock(FunnelSchema),
  costVsRevenue: optionalBlock(CostVsRevenueSchema),
  topReferrers: optionalBlock(TopReferrersSchema),
  failedRuns24h: optionalBlock(FailedRuns24hSchema),
  salesAi: optionalBlock(SalesAiSchema),
  excluded: optionalBlock(ExcludedSchema),
});
export type AdminExecutiveMetrics = z.infer<typeof AdminExecutiveMetricsSchema>;

/**
 * One read. A GET with no side effects, which is what makes it safe to poll
 * every 30 seconds from an admin tab left open all day.
 */
export async function fetchAdminExecutiveMetrics(
  options: RequestOptions = {},
): Promise<AdminExecutiveMetrics> {
  return AdminExecutiveMetricsSchema.parse(
    await apiRequest<unknown>("/admin/metrics/executive", options),
  );
}
