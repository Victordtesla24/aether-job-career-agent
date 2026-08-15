/**
 * ADMIN-2.0 FE-1 — the EXECUTIVE DASHBOARD's selectors.
 *
 * Pure functions over one payload (`GET /admin/metrics/executive`). No fetch,
 * no clock, no randomness: the same payload always produces the same board,
 * which is what makes the figures reviewable.
 *
 * ============================================================================
 * THE THREE RULES THIS MODULE ENFORCES, AND WHERE THEY COME FROM
 * ============================================================================
 *
 * RULE 1 — A COUNT IS NOT A RATE, AND `insufficientData` ONLY SUPPRESSES THE
 * RATE. BE-2's module docstring (`app/repositories/admin_metrics.py`) is
 * explicit: "Small numbers are shown as they are; what is suppressed is the
 * RATE-shaped reading of them." So `insufficientData: true` on a block does
 * NOT hide its counts — six signups is a true fact about a ten-account
 * platform and hiding it would be its own dishonesty. What it hides is the
 * percentage, the conversion rate, the trend reading. `rateReadable()` is the
 * one place that distinction is made.
 *
 * RULE 2 — NO CROSS-CURRENCY ARITHMETIC. Revenue is A$; LLM cost is US$. The
 * API sets `fxRateApplied: null` and refuses to net them. This module makes
 * the same refusal rather than quietly doing the division the API declined to
 * do — see `buildCostVsRevenue`.
 *
 * RULE 3 — THE FUNNEL IS NOT NESTED. `funnel.definitions._shape` states the
 * stages are INDEPENDENT milestone counts over the same signup population, so
 * a later stage can exceed an earlier one. A step-to-step "drop-off" division
 * would misread that, so every share on this board is taken against the SIGNUP
 * POPULATION (the API's own `shareOfSignups`), and the stage-to-stage figure
 * is a percentage-POINT difference between two such shares, labelled as one.
 *
 * Nothing here invents, estimates, or back-fills a number.
 */
import { NOT_MEASURED } from "../../components/charts";
import type { ChartDatum } from "../../components/charts";
import type {
  AdminExecutiveMetrics,
  AdminPlanBucket,
  AdminReferrerAgent,
} from "../api/adminMetrics";
import { SECTION_ABSENT_REASON } from "../api/adminMetrics";

/** No payload at all — the request has not answered, or it failed. */
export const MISSING_PAYLOAD_REASON = "No executive metrics payload has been loaded yet.";

/** Verbatim wherever a figure exists but cannot yet mean anything. */
export const NOT_ENOUGH_DATA = "Not enough data yet";

export type DeltaTone = "up" | "down" | "neutral";

export interface KpiDelta {
  /** Carries its direction as a sign AND a word — never colour alone (C-5). */
  text: string;
  tone: DeltaTone;
  /** The full claim, for the chip's title attribute. */
  title: string;
}

export interface KpiSpark {
  kind: "bars" | "line" | "bullet";
  data: ChartDatum[];
  /** C-3 — always the tile's own `basis`, so mark and reader agree. */
  windowLabel: string;
  nullMeaning?: string;
  target?: { value: number; label: string };
  axisMax?: number;
}

export type KpiId = "mrr" | "paid-subscribers" | "signups-7d" | "conversion" | "cost-vs-revenue";

export interface AdminKpiTile {
  id: KpiId;
  label: string;
  /** Already formatted, or `NOT_MEASURED`. Never a raw number. */
  value: string;
  unit?: string;
  measured: boolean;
  /** REQUIRED whenever `measured` is false. The API's words where it gave any. */
  reason?: string;
  delta?: KpiDelta;
  /** One deterministic line: the denominator, the caveat, the exclusion. */
  detail: string;
  /** The tile's single declared window. */
  basis: string;
  spark: KpiSpark;
}

// --------------------------------------------------------------------------- //
// Formatting
// --------------------------------------------------------------------------- //

const AUD = new Intl.NumberFormat("en-AU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const USD = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const COUNT = new Intl.NumberFormat("en-AU");

/**
 * Money, with the currency NAMED. A$ revenue and US$ LLM cost appear within a
 * few hundred pixels of each other on this page, and the API explicitly warns
 * that the two "are NOT comparable as printed" — so a bare "$" on either would
 * be exactly the ambiguity that invites the comparison the API refused.
 */
export function formatAudTabular(value: number): string {
  return `A$${AUD.format(value)}`;
}
export function formatUsdTabular(value: number): string {
  return `US$${USD.format(value)}`;
}
export function formatCount(value: number): string {
  return COUNT.format(value);
}
/** One decimal, always — a figure that gains a decimal place when the number
 *  changes makes a column of tiles jitter between polls. */
export function formatPct(value: number): string {
  return `${value.toFixed(1)}%`;
}

function isNum(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

// --------------------------------------------------------------------------- //
// Rule 1 — the count / rate distinction
// --------------------------------------------------------------------------- //

export interface RateReadability {
  /** True when a PERCENTAGE, TREND or RATE drawn from this block is worth reading. */
  readable: boolean;
  /** Present when it is not. Names the sample and the API's own threshold. */
  reason?: string;
}

/**
 * Whether a rate-shaped reading of a block is worth putting on screen.
 *
 * The reason names BOTH the block's own sample size and the threshold the API
 * applied, so the owner learns what would change the answer instead of being
 * told a bare "not enough data". The threshold is read from the payload rather
 * than hardcoded here: a second, drifting copy of the API's constant in the
 * frontend is how two surfaces end up disagreeing about the same rule.
 */
export function rateReadable(
  block: { sampleSize: number | null; insufficientData: boolean } | null,
  threshold: number | null,
  noun: string,
): RateReadability {
  if (!block) return { readable: false, reason: SECTION_ABSENT_REASON };
  if (!block.insufficientData) return { readable: true };
  const sample = isNum(block.sampleSize) ? formatCount(block.sampleSize) : "an unreported number of";
  const bar = isNum(threshold) ? ` — the API reads a rate from ${formatCount(threshold)} or more` : "";
  return {
    readable: false,
    reason: `${sample} ${noun} so far${bar}. The counts below are real; a percentage drawn from them would not be.`,
  };
}

// --------------------------------------------------------------------------- //
// Rule 2 — cost beside revenue, never netted
// --------------------------------------------------------------------------- //

export interface CostVsRevenueModel {
  llmCostUsd: number | null;
  revenueAud: number | null;
  grossRevenueAud: number | null;
  refundsAud: number | null;
  windowDays: number | null;
  /** The API's own explanation of why the two are not combined. Verbatim. */
  note: string | null;
  /** Non-null only if the API ever takes responsibility for a rate. */
  fxRateApplied: number | null;
  /** Present when neither figure could be read at all. */
  reason?: string;
  measured: boolean;
}

/**
 * The two money figures, side by side, exactly as the API publishes them.
 *
 * There is deliberately NO margin here. The API sets `fxRateApplied: null` and
 * states in its own `note` that it applies no exchange rate and reports no
 * combined margin. Deriving one in the frontend would put a fabricated number
 * on an executive screen and would do it in the one place nobody would think
 * to look for it. If a future payload ever carries a real `fxRateApplied`, the
 * margin becomes the API's claim to make — not this module's.
 */
export function buildCostVsRevenue(metrics: AdminExecutiveMetrics | null): CostVsRevenueModel {
  const empty: CostVsRevenueModel = {
    llmCostUsd: null,
    revenueAud: null,
    grossRevenueAud: null,
    refundsAud: null,
    windowDays: null,
    note: null,
    fxRateApplied: null,
    measured: false,
  };
  if (!metrics) return { ...empty, reason: MISSING_PAYLOAD_REASON };
  const c = metrics.costVsRevenue;
  if (!c) return { ...empty, reason: SECTION_ABSENT_REASON };
  return {
    llmCostUsd: c.llmCostUsd,
    revenueAud: c.revenueAud,
    grossRevenueAud: c.grossRevenueAud,
    refundsAud: c.refundsAud,
    windowDays: c.windowDays,
    note: c.note,
    fxRateApplied: c.fxRateApplied,
    measured: isNum(c.llmCostUsd) || isNum(c.revenueAud),
    reason:
      isNum(c.llmCostUsd) || isNum(c.revenueAud)
        ? undefined
        : "Neither the LLM cost nor the received revenue was reported.",
  };
}

// --------------------------------------------------------------------------- //
// Rule 3 — the funnel, as milestone shares of one population
// --------------------------------------------------------------------------- //

export interface AdminFunnelStep {
  key: string;
  label: string;
  count: number | null;
  /** The API's `shareOfSignups`, converted from a fraction to a percentage. */
  sharePct: number | null;
  /**
   * Percentage POINTS between this stage's share and the stage above it.
   * Negative = fewer accounts reached this milestone. `null` at the top, and
   * wherever either share is missing. NOT a drop-off rate — the stages are
   * independent milestone counts, so there is no "of the previous step".
   */
  shareDeltaPoints: number | null;
  note?: string;
}

export interface AdminFunnelModel {
  steps: AdminFunnelStep[];
  /** True when the stage COUNTS are present. Counts are always shown (Rule 1). */
  measured: boolean;
  reason?: string;
  /** Rule 1 — whether the share percentages are worth reading. */
  rate: RateReadability;
  /** C-2 — set whenever any stage count is `null`. */
  nullMeaning?: string;
  windowLabel: string;
  /** The API's `definitions._shape`, verbatim. The panel prints it. */
  shapeNote: string | null;
  /**
   * The `key` of the stage with the LARGEST negative share delta, or `null`.
   * Every funnel loses people at every stage, so tinting all of them in the
   * warn tone makes the tone meaningless; the one figure worth acting on is
   * the biggest fall. Ties resolve to the earliest stage so the highlight does
   * not hop between polls.
   */
  steepestFallKey: string | null;
}

const FUNNEL_NULL_MEANING =
  "a milestone the platform does not record for this cohort — not a milestone nobody reached";

export function buildFunnelSteps(metrics: AdminExecutiveMetrics | null): AdminFunnelModel {
  const base = {
    steps: [] as AdminFunnelStep[],
    measured: false,
    windowLabel: "every account, all time",
    shapeNote: null as string | null,
    steepestFallKey: null as string | null,
  };
  if (!metrics) {
    return { ...base, reason: MISSING_PAYLOAD_REASON, rate: { readable: false, reason: MISSING_PAYLOAD_REASON } };
  }
  const f = metrics.funnel;
  if (!f) {
    return { ...base, reason: SECTION_ABSENT_REASON, rate: { readable: false, reason: SECTION_ABSENT_REASON } };
  }

  const rate = rateReadable(f, metrics.insufficientDataThreshold, "accounts");
  const windowLabel = f.window ?? base.windowLabel;
  const shapeNote = f.definitions?._shape ?? null;

  if (f.stages.length === 0) {
    return {
      ...base,
      windowLabel,
      shapeNote,
      rate,
      reason: "No funnel stage has been recorded yet.",
    };
  }

  const steps: AdminFunnelStep[] = f.stages.map((stage, index) => {
    const sharePct = isNum(stage.shareOfSignups) ? stage.shareOfSignups * 100 : null;
    const previousShare =
      index === 0 ? null : (() => {
        const prev = f.stages[index - 1]?.shareOfSignups;
        return isNum(prev) ? prev * 100 : null;
      })();
    return {
      key: stage.key,
      label: stage.label,
      count: stage.count,
      sharePct,
      shareDeltaPoints:
        index === 0 || sharePct === null || previousShare === null
          ? null
          : sharePct - previousShare,
    };
  });

  let steepest: AdminFunnelStep | null = null;
  for (const step of steps) {
    if (step.shareDeltaPoints === null || step.shareDeltaPoints >= 0) continue;
    if (steepest === null || step.shareDeltaPoints < (steepest.shareDeltaPoints as number)) {
      steepest = step;
    }
  }

  return {
    steps,
    measured: true,
    rate,
    nullMeaning: steps.some((s) => s.count === null) ? FUNNEL_NULL_MEANING : undefined,
    windowLabel,
    shapeNote,
    steepestFallKey: steepest?.key ?? null,
  };
}

// --------------------------------------------------------------------------- //
// Series
// --------------------------------------------------------------------------- //

export interface SeriesModel {
  points: Array<{ label: string; value: number | null; note?: string }>;
  /** True when there are real points to draw. Counts are always drawn (Rule 1). */
  measured: boolean;
  reason?: string;
  /** Rule 1 — whether a TREND reading of these points is worth making. */
  rate: RateReadability;
  nullMeaning?: string;
  windowLabel: string;
  /** The API's own exclusion/inclusion note for the series. Verbatim. */
  scopeNote: string | null;
  total: number | null;
}

const DAY_NULL_MEANING = "no measurement was recorded for that day — not a day with no activity";

/** "2026-08-14" → "14 Aug". Falls back to the string it was given, which is
 *  honest: a label we cannot parse is still the label the API sent. */
export function formatDayLabel(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-AU", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(date);
}

function emptySeries(windowLabel: string, reason: string): SeriesModel {
  return {
    points: [],
    measured: false,
    reason,
    rate: { readable: false, reason },
    windowLabel,
    scopeNote: null,
    total: null,
  };
}

export function buildSignupSeries(metrics: AdminExecutiveMetrics | null): SeriesModel {
  const windowLabel = "the last 30 days, by day";
  if (!metrics) return emptySeries(windowLabel, MISSING_PAYLOAD_REASON);
  const block = metrics.signupsByDay;
  if (!block) return emptySeries(windowLabel, SECTION_ABSENT_REASON);
  const rate = rateReadable(block, metrics.insufficientDataThreshold, "signups in the window");
  if (block.series.length === 0) {
    return {
      ...emptySeries(windowLabel, "No day in the window has a recorded signup count yet."),
      rate,
      scopeNote: block.excludes,
    };
  }
  const points = block.series.map((row) => ({
    label: formatDayLabel(row.date),
    value: row.count,
  }));
  return {
    points,
    measured: true,
    rate,
    nullMeaning: points.some((p) => p.value === null) ? DAY_NULL_MEANING : undefined,
    windowLabel: isNum(block.windowDays) ? `the last ${block.windowDays} days, by day` : windowLabel,
    scopeNote: block.excludes,
    total: block.total,
  };
}

export function buildRunSeries(metrics: AdminExecutiveMetrics | null): SeriesModel {
  const windowLabel = "the last 30 days, by day";
  if (!metrics) return emptySeries(windowLabel, MISSING_PAYLOAD_REASON);
  const block = metrics.runsByDay;
  if (!block) return emptySeries(windowLabel, SECTION_ABSENT_REASON);
  const rate = rateReadable(block, metrics.insufficientDataThreshold, "agent runs in the window");
  if (block.series.length === 0) {
    return {
      ...emptySeries(windowLabel, "No day in the window has a recorded agent run yet."),
      rate,
      scopeNote: block.includes,
    };
  }
  const points = block.series.map((row) => ({
    label: formatDayLabel(row.date),
    value: row.runs,
  }));
  return {
    points,
    measured: true,
    rate,
    nullMeaning: points.some((p) => p.value === null) ? DAY_NULL_MEANING : undefined,
    windowLabel: isNum(block.windowDays) ? `the last ${block.windowDays} days, by day` : windowLabel,
    scopeNote: block.includes,
    total: block.totalRuns,
  };
}

// --------------------------------------------------------------------------- //
// Plan mix
// --------------------------------------------------------------------------- //

export interface PlanMixModel {
  segments: Array<{ label: string; value: number | null; note?: string }>;
  measured: boolean;
  reason?: string;
  windowLabel: string;
  /** C-2 — `<ChartFrame>` THROWS on a series mixing a real 0 with an
   *  unexplained null, so this is load-bearing, not decorative. */
  nullMeaning?: string;
  /** The A$ each plan contributes, for the legend's second column. */
  mrrByLabel: Record<string, number | null>;
}

const PLAN_NULL_MEANING =
  "the subscriber count for that plan was not reported — not a plan with no subscribers";

function planLabel(bucket: AdminPlanBucket): string {
  const name = bucket.name?.trim();
  if (name) return name;
  const id = bucket.planId.trim();
  return id ? id.charAt(0).toUpperCase() + id.slice(1) : "Unnamed plan";
}

export function buildPlanMix(metrics: AdminExecutiveMetrics | null): PlanMixModel {
  const windowLabel = "current Stripe-backed subscriptions";
  const empty: PlanMixModel = { segments: [], measured: false, windowLabel, mrrByLabel: {} };
  if (!metrics) return { ...empty, reason: MISSING_PAYLOAD_REASON };
  if (!metrics.revenue) return { ...empty, reason: SECTION_ABSENT_REASON };
  if (metrics.revenue.byPlan.length === 0) {
    return {
      ...empty,
      reason: "No plan has a Stripe-backed subscriber yet, so there is no mix to show.",
    };
  }
  const mrrByLabel: Record<string, number | null> = {};
  const segments = metrics.revenue.byPlan.map((bucket) => {
    const label = planLabel(bucket);
    mrrByLabel[label] = bucket.mrrAud;
    return { label, value: bucket.count };
  });
  return {
    segments,
    measured: true,
    windowLabel,
    nullMeaning: segments.some((s) => s.value === null) ? PLAN_NULL_MEANING : undefined,
    mrrByLabel,
  };
}

// --------------------------------------------------------------------------- //
// Referrers
// --------------------------------------------------------------------------- //

export interface ReferrerModel {
  agents: AdminReferrerAgent[];
  measured: boolean;
  reason?: string;
  totalAttributedSignups: number | null;
}

export function buildReferrers(metrics: AdminExecutiveMetrics | null): ReferrerModel {
  if (!metrics) {
    return { agents: [], measured: false, reason: MISSING_PAYLOAD_REASON, totalAttributedSignups: null };
  }
  const block = metrics.topReferrers;
  if (!block) {
    return { agents: [], measured: false, reason: SECTION_ABSENT_REASON, totalAttributedSignups: null };
  }
  if (block.agents.length === 0) {
    return {
      agents: [],
      measured: false,
      // The API omits agents with zero attributed signups by design, so an
      // empty list means "nobody has referred anyone", not "nobody exists".
      reason: "No sales agent has brought in an account yet.",
      totalAttributedSignups: block.totalAttributedSignups,
    };
  }
  return {
    agents: block.agents,
    measured: true,
    totalAttributedSignups: block.totalAttributedSignups,
  };
}

// --------------------------------------------------------------------------- //
// The KPI band
// --------------------------------------------------------------------------- //

/**
 * The delta chip's tone.
 *
 * WHY "down" IS AMBER, NOT RED. This is the same `TONE_CLASS` the Analytics
 * executive band already ships (`components/analytics/ExecutiveSummary.tsx`),
 * and the product's two executive surfaces should not speak different colour
 * languages. Red is reserved, product-wide, for something BROKEN — a failed
 * run, a refused submission. A metric that fell week-on-week is a WARNING,
 * which is what amber means everywhere else. The direction is never carried by
 * colour alone: the chip prints a glyph and a signed number too (C-5).
 */
function delta(
  current: number | null,
  previous: number | null,
  format: (v: number) => string,
  windowWords: string,
): KpiDelta | undefined {
  if (!isNum(current) || !isNum(previous)) return undefined;
  const change = current - previous;
  const tone: DeltaTone = change > 0 ? "up" : change < 0 ? "down" : "neutral";
  const sign = change > 0 ? "+" : change < 0 ? "−" : "";
  const text =
    change === 0 ? `no change ${windowWords}` : `${sign}${format(Math.abs(change))} ${windowWords}`;
  return {
    text,
    tone,
    title:
      change === 0
        ? `Unchanged against the previous measurement (${format(previous)}).`
        : `${format(current)} now, against ${format(previous)} previously.`,
  };
}

function unmeasuredTile(
  id: KpiId,
  label: string,
  basis: string,
  reason: string,
  detail = "",
): AdminKpiTile {
  return {
    id,
    label,
    value: NOT_MEASURED,
    measured: false,
    reason,
    detail,
    basis,
    spark: { kind: "bullet", windowLabel: basis, data: [{ label, value: null, note: reason }] },
  };
}

const MRR_BASIS = "current subscriptions, normalised to a monthly figure";
const SUBS_BASIS = "current Stripe-backed subscriptions";
const SIGNUPS_BASIS = "the last 7 days";
const CONVERSION_BASIS = "every account, all time";
const COST_BASIS = "the last 30 days";

function mrrTile(metrics: AdminExecutiveMetrics | null): AdminKpiTile {
  const label = "Monthly recurring revenue";
  if (!metrics) return unmeasuredTile("mrr", label, MRR_BASIS, MISSING_PAYLOAD_REASON);
  const r = metrics.revenue;
  if (!r) return unmeasuredTile("mrr", label, MRR_BASIS, SECTION_ABSENT_REASON);

  const parts: string[] = [];
  if (isNum(r.arrAud)) parts.push(`${formatAudTabular(r.arrAud)} annualised.`);
  if (r.estimate) {
    parts.push(
      "Estimate: annual subscriptions are divided by 12 and the source is the local Stripe mirror.",
    );
  }
  /* The API publishes no prior MRR measurement, so there is no 30-day change to
     show. Saying so is the honest alternative to inventing a baseline. */
  parts.push("No prior MRR measurement is recorded, so no 30-day change can be shown.");
  const detail = parts.join(" ");

  // A COUNT-shaped money figure: shown at any sample size (Rule 1).
  if (!isNum(r.mrrAud)) {
    return unmeasuredTile("mrr", label, MRR_BASIS, "The API did not report an MRR figure.", detail);
  }
  return {
    id: "mrr",
    label,
    value: formatAudTabular(r.mrrAud),
    measured: true,
    detail,
    basis: MRR_BASIS,
    spark: {
      kind: "bullet",
      windowLabel: MRR_BASIS,
      data: [{ label, value: r.mrrAud, display: formatAudTabular(r.mrrAud) }],
    },
  };
}

function subscriberTile(metrics: AdminExecutiveMetrics | null): AdminKpiTile {
  const label = "Paid subscribers";
  if (!metrics) return unmeasuredTile("paid-subscribers", label, SUBS_BASIS, MISSING_PAYLOAD_REASON);
  const r = metrics.revenue;
  if (!r) return unmeasuredTile("paid-subscribers", label, SUBS_BASIS, SECTION_ABSENT_REASON);

  /*
   * THE DISCLOSURE THAT MATTERS MOST ON THIS TILE. Production carries at least
   * one local Subscription row reading pro/active with nothing behind it at
   * Stripe (the owner's own row). A count that folded those in would overstate
   * the business; one that dropped them silently would hide a data-integrity
   * problem the owner needs to fix. So the count excludes them AND says how
   * many were excluded, right on the tile.
   */
  const parts: string[] = [];
  if (isNum(r.unbackedPaidRows) && r.unbackedPaidRows > 0) {
    const n = r.unbackedPaidRows;
    parts.push(
      `${formatCount(n)} local ${n === 1 ? "row looks" : "rows look"} paid but ${
        n === 1 ? "has" : "have"
      } no Stripe subscription behind ${n === 1 ? "it" : "them"}.`,
    );
  }
  if (isNum(r.excludedAdminRows) && r.excludedAdminRows > 0) {
    const n = r.excludedAdminRows;
    parts.push(
      `${formatCount(n)} admin ${n === 1 ? "account is" : "accounts are"} excluded — admins are exempt from plans.`,
    );
  }
  const detail = parts.join(" ");

  if (!isNum(r.paidSubscribers)) {
    return unmeasuredTile(
      "paid-subscribers",
      label,
      SUBS_BASIS,
      "The API did not report a subscriber count.",
      detail,
    );
  }
  return {
    id: "paid-subscribers",
    label,
    value: formatCount(r.paidSubscribers),
    measured: true,
    detail,
    basis: SUBS_BASIS,
    spark: { kind: "bullet", windowLabel: SUBS_BASIS, data: [{ label, value: r.paidSubscribers }] },
  };
}

function signupTile(metrics: AdminExecutiveMetrics | null): AdminKpiTile {
  const label = "Signups (7d)";
  if (!metrics) return unmeasuredTile("signups-7d", label, SIGNUPS_BASIS, MISSING_PAYLOAD_REASON);
  const block = metrics.signupsByDay;
  if (!block) return unmeasuredTile("signups-7d", label, SIGNUPS_BASIS, SECTION_ABSENT_REASON);

  /*
   * ONE WINDOW PER TILE. The API publishes a 30-day daily series, not a 7-day
   * total, so the 7-day figure is summed HERE from the last seven real daily
   * counts — and the spark shows those same seven days, never the 30-day
   * series. A tile whose numeral and shape are measured over different windows
   * is the commonest way a dashboard lies with no wrong number on it.
   *
   * A day the API did not measure is NOT counted as zero: if any of the seven
   * is null the sum would be an undercount presented as a total, so the tile
   * reports the gap instead.
   */
  const last7 = block.series.slice(-7);
  const prev7 = block.series.slice(-14, -7);
  const sum = (rows: typeof last7): number | null => {
    if (rows.length === 0) return null;
    let total = 0;
    for (const row of rows) {
      if (!isNum(row.count)) return null;
      total += row.count;
    }
    return total;
  };
  const current = sum(last7);
  const previous = sum(prev7);

  const detail = [
    isNum(block.total) ? `${formatCount(block.total)} in the last 30 days.` : "",
    block.excludes ? `Excludes ${block.excludes}.` : "",
  ]
    .filter(Boolean)
    .join(" ");

  if (current === null) {
    return unmeasuredTile(
      "signups-7d",
      label,
      SIGNUPS_BASIS,
      last7.length === 0
        ? "The API returned no daily signup counts."
        : "At least one of the last seven days was not measured, so a 7-day total would be an undercount.",
      detail,
    );
  }

  const sparkData: ChartDatum[] = last7.map((row) => ({
    label: formatDayLabel(row.date),
    value: row.count,
  }));

  return {
    id: "signups-7d",
    label,
    value: formatCount(current),
    measured: true,
    delta: delta(current, previous, formatCount, "vs previous 7 days"),
    detail,
    basis: SIGNUPS_BASIS,
    spark:
      sparkData.length >= 2
        ? {
            kind: "bars",
            windowLabel: SIGNUPS_BASIS,
            data: sparkData,
            nullMeaning: sparkData.some((d) => d.value === null) ? DAY_NULL_MEANING : undefined,
          }
        : { kind: "bullet", windowLabel: SIGNUPS_BASIS, data: [{ label, value: current }] },
  };
}

/**
 * Signup → paid. This is the board's one genuinely RATE-shaped headline, so it
 * is the one Rule 1 suppresses: with ten accounts against the API's threshold
 * of twenty, a percentage would be noise wearing a decimal point. The COUNTS
 * behind it stay on the tile either way.
 */
function conversionTile(metrics: AdminExecutiveMetrics | null): AdminKpiTile {
  const label = "Signup → paid";
  if (!metrics) return unmeasuredTile("conversion", label, CONVERSION_BASIS, MISSING_PAYLOAD_REASON);
  const f = metrics.funnel;
  if (!f) return unmeasuredTile("conversion", label, CONVERSION_BASIS, SECTION_ABSENT_REASON);

  const signups = f.stages.find((s) => s.key === "signup")?.count ?? null;
  const paid = f.stages.find((s) => s.key === "paid")?.count ?? null;
  const detail =
    isNum(signups) && isNum(paid)
      ? `${formatCount(paid)} of ${formatCount(signups)} accounts have a paid subscription.`
      : "";

  const rate = rateReadable(f, metrics.insufficientDataThreshold, "accounts");
  if (!rate.readable) {
    return unmeasuredTile("conversion", label, CONVERSION_BASIS, rate.reason ?? NOT_ENOUGH_DATA, detail);
  }
  if (!isNum(signups) || signups <= 0 || !isNum(paid)) {
    return unmeasuredTile(
      "conversion",
      label,
      CONVERSION_BASIS,
      "No account has signed up yet, so there is nothing to convert.",
      detail,
    );
  }
  const pct = (paid / signups) * 100;
  return {
    id: "conversion",
    label,
    value: formatPct(pct),
    measured: true,
    detail,
    basis: CONVERSION_BASIS,
    spark: {
      kind: "bullet",
      windowLabel: CONVERSION_BASIS,
      data: [{ label, value: pct, display: formatPct(pct) }],
      axisMax: 100,
    },
  };
}

/**
 * LLM cost against revenue — reported as the API reports it: SIDE BY SIDE.
 *
 * The brief asked for a margin. The API refuses to produce one (no exchange
 * rate is available to it, `fxRateApplied: null`) and says so in its own
 * `note`. The honest rendering of "cost vs revenue" under that constraint is
 * the US$ figure as the headline — it is real, it is measured, and it is the
 * number that is actually moving today — with the A$ received beside it and
 * the API's refusal quoted verbatim. The one thing this tile will not do is
 * perform the division the API declined to perform.
 */
function costVsRevenueTile(metrics: AdminExecutiveMetrics | null): AdminKpiTile {
  const label = "LLM cost vs revenue";
  const model = buildCostVsRevenue(metrics);
  if (!model.measured) {
    return unmeasuredTile("cost-vs-revenue", label, COST_BASIS, model.reason ?? NOT_ENOUGH_DATA);
  }
  const basis = isNum(model.windowDays) ? `the last ${model.windowDays} days` : COST_BASIS;
  const detail = [
    isNum(model.revenueAud)
      ? `${formatAudTabular(model.revenueAud)} received in the same window.`
      : "Revenue received in this window was not reported.",
    model.note ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  if (!isNum(model.llmCostUsd)) {
    return unmeasuredTile("cost-vs-revenue", label, basis, "The API did not report an LLM cost.", detail);
  }
  return {
    id: "cost-vs-revenue",
    label,
    value: formatUsdTabular(model.llmCostUsd),
    measured: true,
    detail,
    basis,
    spark: {
      kind: "bullet",
      windowLabel: basis,
      data: [{ label: "LLM cost", value: model.llmCostUsd, display: formatUsdTabular(model.llmCostUsd) }],
    },
  };
}

/**
 * The five headline slots, ALWAYS all five, ALWAYS in this order.
 *
 * A tile is never dropped for want of a number: dropping it reflows the band
 * under the reader and, worse, hides that something is unmeasured. An
 * unmeasured tile holds its slot, prints the chart kit's em dash, and says why.
 */
export function buildKpiTiles(metrics: AdminExecutiveMetrics | null): AdminKpiTile[] {
  return [
    mrrTile(metrics),
    subscriberTile(metrics),
    signupTile(metrics),
    conversionTile(metrics),
    costVsRevenueTile(metrics),
  ];
}
