/**
 * ANALYTICS-VIZ — the executive summary band's SELECTORS.
 *
 * The band is the answer to "what's what, in one glance". Everything it shows
 * is derived HERE, as pure functions over the payloads
 * `app/dashboard/analytics/page.tsx` already fetches — no endpoint was added,
 * no request was moved, and the page's wiring is untouched (S-UI binding
 * constraint 1).
 *
 * THE THREE RULES THIS MODULE EXISTS TO ENFORCE
 *
 * 1. DETERMINISTIC. Every insight line is a computation over real numbers —
 *    the steepest measured drop-off, the distance to a stated target, the modal
 *    band, the change since the previous recorded policy point. There is no
 *    model in this path, no adjective that the data did not earn, and running
 *    it twice on the same payload gives the same string.
 *
 * 2. ABSENCE IS A RESULT. When a figure cannot be computed the tile reports
 *    `measured: false` and carries the REASON. It never falls back to 0, to a
 *    dash with no explanation, or to a plausible-looking estimate. A tile that
 *    cannot be measured says so on the tile, at the same size as the tiles that
 *    can.
 *
 * 3. ONE WINDOW PER TILE. A tile never mixes a period-scoped figure with an
 *    all-time one. `basis` is the tile's single declared window; it is rendered
 *    visibly AND handed to the tile's spark as its `windowLabel`, so C-3 holds
 *    for the mark and the reader is looking at the same claim the chart kit
 *    asserted against.
 */
import type { ChartDatum } from "../../components/charts";
import { NOT_MEASURED, formatNumber } from "../../components/charts";
import type { AgentPolicy, PolicyHistory } from "../api/agentPolicy";
import type {
  AgentRoi,
  AtsDistribution,
  Conversion,
  Dashboard,
  Funnel,
  Period,
} from "../api/analytics";

/** The interview-conversion target the whole product is calibrated against
 *  (1-in-5). Sourced from the policy payload when it is present, so this is a
 *  fallback for a page that has not loaded the policy yet — never a second,
 *  competing definition. */
export const INTERVIEW_TARGET_PCT = 20;

/** The ATS band a job has to reach to count as a strong match. Matches the
 *  policy's own dimension floor (`thresholds.dimensionFloor`, 80). */
export const STRONG_MATCH_FLOOR = 80;

export type DeltaTone = "up" | "down" | "neutral";

export interface ExecDelta {
  /** Short chip copy — always carries its sign or its direction as a WORD or
   *  glyph, never as colour alone (C-5). */
  text: string;
  tone: DeltaTone;
  /** The full claim, for the chip's title attribute. */
  title: string;
}

export interface ExecSpark {
  kind: "bars" | "line" | "bullet";
  data: ChartDatum[];
  target?: { value: number; label: string };
  nullMeaning?: string;
}

export interface ExecTileModel {
  id: string;
  label: string;
  /** Already formatted. `NOT_MEASURED` when `measured` is false. */
  value: string;
  unit?: string;
  spark: ExecSpark;
  /** The measured delta against a stated target or a previous measurement.
   *  Absent when neither exists — never approximated. */
  delta?: ExecDelta;
  /** ONE short deterministic line. Never a paraphrase, never an adjective. */
  insight: string;
  /** The tile's single declared window. Rendered visibly and used as the
   *  spark's `windowLabel`. */
  basis: string;
  measured: boolean;
}

export interface ExecutiveSummaryInput {
  period: Period;
  funnel: Funnel | null;
  conversion: Conversion | null;
  ats: AtsDistribution | null;
  roi: AgentRoi | null;
  policy: AgentPolicy | null;
  policyHistory: PolicyHistory | null;
  /**
   * `GET /analytics/dashboard?period=…` — the page's one PERIOD-SCOPED source
   * for the all-stages application count and for agent spend/runs (round 2,
   * finding F1). Every field on it is filtered by the selected period
   * server-side (`analytics._dashboard`: `createdAt` for applications and
   * jobs, `startedAt` for agent runs), which is what makes it safe to read
   * beside the funnel — the two are measured in the SAME window — and unsafe
   * to read beside `roi`, which has no period support at all.
   *
   * `null` when the endpoint has not answered. Every use below is guarded:
   * absence removes a chip, never a tile, and never turns into a 0.
   */
  dashboard: Dashboard | null;
}

function periodWindow(period: Period): string {
  return period === "all" ? "all time" : `the selected period (${period})`;
}

/**
 * A finite number out of one of the API's permissive `Record<string, unknown>`
 * bags (`policy.thresholds`, `policy.knobs`), or `null`.
 *
 * The schema keeps unknown server keys rather than asserting a shape, so the
 * value genuinely IS `unknown` here. Coercing it (`Number(v)`) would turn a
 * missing threshold into `NaN` and an accidental `"20%"` into a silent 20 —
 * this refuses anything that is not already a finite number.
 */
export function numberFrom(
  bag: Record<string, unknown> | null | undefined,
  key: string,
): number | null {
  const value = bag?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function money(value: number): string {
  return `$${value.toFixed(2)}`;
}

function pct(value: number): string {
  // One decimal, trailing ".0" kept off integers so "20%" does not become
  // "20.0%" beside a target written as "20%".
  return Number.isInteger(value) ? `${value}%` : `${Math.round(value * 100) / 100}%`;
}

/* ------------------------------------------------------------------ */
/* 1 — PIPELINE                                                        */
/* ------------------------------------------------------------------ */

export interface DropOff {
  from: string;
  to: string;
  /** Share of the previous stage that carried through, as a percentage. */
  carriedPct: number;
}

/**
 * The steepest measured drop-off between consecutive funnel stages.
 *
 * Only pairs whose PREVIOUS stage is non-zero are considered: "0 of 0 carried
 * through" is not a 0% drop-off, it is an unmeasurable one, and ranking it as
 * the worst stage would make an empty funnel look like a catastrophic one.
 * Ties resolve to the EARLIEST pair, so the answer is stable across renders.
 */
export function steepestDropOff(steps: ReadonlyArray<{ label: string; value: number }>): DropOff | null {
  let worst: DropOff | null = null;
  for (let i = 1; i < steps.length; i += 1) {
    const previous = steps[i - 1];
    if (previous.value <= 0) continue;
    const carriedPct = (steps[i].value / previous.value) * 100;
    if (worst === null || carriedPct < worst.carriedPct) {
      worst = { from: previous.label, to: steps[i].label, carriedPct };
    }
  }
  return worst;
}

/**
 * The ALL-STAGES application count, as a chip beside the submitted one.
 *
 * These are two different measurements of the same window — `/dashboard`
 * counts every Application row the period created (draft through offer),
 * `/funnel` counts only the ones actually submitted — and the gap between
 * them is the reader's draft backlog. The chip states BOTH counts and
 * subtracts nothing: the two endpoints define "in this period" on their own
 * date columns, so a difference is a real quantity but a computed remainder
 * would be a claim neither endpoint made.
 *
 * This is where the deleted "Dashboard summary" card's one non-duplicated
 * figure lives now (round 2, F1).
 */
function createdChip(dashboard: Dashboard | null, period: Period, submitted: number | null): ExecDelta | undefined {
  if (dashboard === null) return undefined;
  const created = formatNumber(dashboard.totalApplications);
  return {
    text: `${created} created`,
    tone: "neutral",
    title:
      `${created} application records created, counted over ${periodWindow(period)} — every stage from draft to offer` +
      (submitted === null
        ? "."
        : `; ${formatNumber(submitted)} of them have been submitted.`),
  };
}

function pipelineTile(input: ExecutiveSummaryInput): ExecTileModel {
  const { funnel, period, dashboard } = input;
  const basis = `${periodWindow(period)} — funnel stages counted within it`;
  if (funnel === null) {
    return {
      id: "pipeline",
      label: "Applications submitted",
      value: NOT_MEASURED,
      spark: { kind: "bars", data: [] },
      delta: createdChip(dashboard, period, null),
      insight: "The funnel has not loaded yet — no stage has been counted.",
      basis,
      measured: false,
    };
  }
  const steps = [
    { label: "Jobs found", value: funnel.jobs_found },
    { label: "Applied", value: funnel.applied },
    { label: "Screened", value: funnel.screened },
    { label: "Interviewed", value: funnel.interviewed },
    { label: "Offers", value: funnel.offers },
  ];
  const worst = steepestDropOff(steps);
  return {
    id: "pipeline",
    label: "Applications submitted",
    value: formatNumber(funnel.applied),
    spark: {
      kind: "bars",
      data: steps.map((s) => ({ label: s.label, value: s.value })),
    },
    delta: createdChip(dashboard, period, funnel.applied),
    insight: worst
      ? `Steepest drop-off ${worst.from} → ${worst.to}: ${pct(
          Math.round(worst.carriedPct * 10) / 10,
        )} carried through.`
      : "No stage has enough volume yet to measure a drop-off.",
    basis,
    measured: true,
  };
}

/* ------------------------------------------------------------------ */
/* 2 — INTERVIEW CONVERSION vs TARGET                                  */
/* ------------------------------------------------------------------ */

/**
 * The policy's own account of what it is doing about the gap — sourced from
 * the tier the backend actually resolved, never asserted unconditionally.
 *
 * `heightened` is the ONLY tier that escalates rigor (quality_policy.py rule
 * 2); `insufficient_data` explicitly does not and must say so. This is the
 * F-UAX-04 contract, carried over verbatim from the prose it replaces.
 */
export function conversionPolicyNote(
  tier: string | null | undefined,
  atOrAbove: boolean,
): string {
  if (atOrAbove) return "At or above the 1-in-5 target.";
  if (tier === "heightened") return "Rigor escalated to heightened until this closes.";
  if (tier === "insufficient_data")
    return "Too few submissions all-time for the policy to decide on escalation.";
  return "The policy escalates rigor once its own all-time metrics cross a threshold.";
}

function conversionTile(input: ExecutiveSummaryInput): ExecTileModel {
  const { conversion, policy, period } = input;
  const declared = numberFrom(policy?.thresholds, "interviewConversionTarget");
  const target = declared === null ? INTERVIEW_TARGET_PCT : normaliseTarget(declared);
  const basis = `${periodWindow(period)} — interviews per submitted application`;
  if (conversion === null) {
    return {
      id: "conversion",
      label: "Interview conversion",
      value: NOT_MEASURED,
      spark: {
        kind: "bullet",
        data: [{ label: "Interview conversion", value: null }],
        target: { value: target, label: `${target}% target` },
      },
      insight: "Conversion has not loaded yet.",
      basis,
      measured: false,
    };
  }
  const rate = conversion.interview_conversion_rate;
  const atOrAbove = rate >= target;
  const gap = Math.round((target - rate) * 10) / 10;
  return {
    id: "conversion",
    label: "Interview conversion",
    value: pct(rate),
    spark: {
      kind: "bullet",
      data: [{ label: "Interview conversion", value: rate }],
      target: { value: target, label: `${target}% target` },
    },
    delta: {
      text: atOrAbove ? `at target` : `${gap} pts to target`,
      tone: atOrAbove ? "up" : "down",
      title: atOrAbove
        ? `Interview conversion is at or above the ${target}% (1-in-5) target.`
        : `Interview conversion is ${gap} percentage points below the ${target}% (1-in-5) target.`,
    },
    insight: conversionPolicyNote(policy?.tier, atOrAbove),
    basis,
    measured: true,
  };
}

/** The backend sends the target either as a fraction (0.2) or as a percentage
 *  (20) depending on the endpoint. Normalise to percentage points WITHOUT
 *  guessing: a value at or below 1 is a fraction, anything above is already a
 *  percentage. */
export function normaliseTarget(value: number): number {
  return value <= 1 ? Math.round(value * 1000) / 10 : value;
}

/* ------------------------------------------------------------------ */
/* 3 — MATCH QUALITY (ATS distribution)                                */
/* ------------------------------------------------------------------ */

/** The lower bound a bucket's `range` string ("80-89", "90-100") declares. */
export function bucketFloor(range: string): number {
  const parsed = Number.parseInt(range.split("-")[0] ?? "", 10);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

export interface AtsSummary {
  total: number;
  strong: number;
  strongPct: number | null;
  modalRange: string | null;
  modalCount: number;
}

/**
 * Share of scored jobs at or above the strong-match floor, plus the modal band.
 *
 * `strongPct` is `null` when nothing has been scored — a 0% "strong match"
 * share on an empty distribution would be a claim about jobs that do not
 * exist. Ties on the modal band resolve to the LOWEST band, so the answer is
 * stable and never flatters.
 */
export function summariseAts(ats: AtsDistribution, floor = STRONG_MATCH_FLOOR): AtsSummary {
  const total = ats.buckets.reduce((sum, b) => sum + b.count, 0);
  const strong = ats.buckets
    .filter((b) => bucketFloor(b.range) >= floor)
    .reduce((sum, b) => sum + b.count, 0);
  let modal: { range: string; count: number } | null = null;
  for (const bucket of ats.buckets) {
    if (bucket.count > 0 && (modal === null || bucket.count > modal.count)) {
      modal = { range: bucket.range, count: bucket.count };
    }
  }
  return {
    total,
    strong,
    strongPct: total > 0 ? Math.round((strong / total) * 1000) / 10 : null,
    modalRange: modal?.range ?? null,
    modalCount: modal?.count ?? 0,
  };
}

function qualityTile(input: ExecutiveSummaryInput): ExecTileModel {
  const { ats } = input;
  const basis = "all time — not affected by the period selector";
  if (ats === null) {
    return {
      id: "quality",
      label: `Scored ${STRONG_MATCH_FLOOR}+`,
      value: NOT_MEASURED,
      spark: { kind: "bars", data: [] },
      insight: "The ATS distribution has not loaded yet.",
      basis,
      measured: false,
    };
  }
  const summary = summariseAts(ats);
  const data = ats.buckets.map((b) => ({ label: b.range, value: b.count }));
  if (summary.strongPct === null) {
    return {
      id: "quality",
      label: `Scored ${STRONG_MATCH_FLOOR}+`,
      value: NOT_MEASURED,
      spark: { kind: "bars", data },
      insight: "No job has been scored yet, so no share can be measured.",
      basis,
      measured: false,
    };
  }
  return {
    id: "quality",
    label: `Scored ${STRONG_MATCH_FLOOR}+`,
    value: pct(summary.strongPct),
    spark: { kind: "bars", data },
    delta: {
      text: `${formatNumber(summary.strong)} of ${formatNumber(summary.total)}`,
      tone: "neutral",
      title: `${formatNumber(summary.strong)} of ${formatNumber(
        summary.total,
      )} scored jobs reach the ${STRONG_MATCH_FLOOR}+ band.`,
    },
    insight: summary.modalRange
      ? `Most jobs land in the ${summary.modalRange} band (${formatNumber(
          summary.modalCount,
        )}).`
      : "Every scored job sits outside a counted band.",
    basis,
    measured: true,
  };
}

/* ------------------------------------------------------------------ */
/* 4 — AGENT SPEND                                                     */
/* ------------------------------------------------------------------ */

function spendTile(input: ExecutiveSummaryInput): ExecTileModel {
  const { roi, funnel, dashboard, period } = input;

  /*
   * WHICH SPEND FIGURE THIS TILE IS SHOWING, and why it can change.
   *
   * `/analytics/agent-roi` has no period support server-side, so on a scoped
   * period it can only ever report an all-time total — which is why this tile
   * used to say "select the all period to compare like for like" and withhold
   * both ratios. `/analytics/dashboard?period=…` DOES scope agent spend and
   * agent runs (`AgentRun."startedAt"`), and it is the source the deleted
   * "Dashboard summary" card read (round 2, F1).
   *
   * So: on a scoped period, when that payload is present, this tile reports
   * the scoped figure and its window says so — and because the funnel beside
   * it is scoped to the SAME period, the cost-per ratios become genuinely
   * divisible instead of withheld. On "all", or when the dashboard endpoint
   * did not answer, nothing changes: the all-time ROI figure with its
   * all-time window, and the ratio rules exactly as before.
   *
   * What never happens is the mix: an all-time numerator over a
   * period-scoped denominator. `windowsAlign` is the single place that is
   * decided, and both the ratios and the tile's stated basis read it.
   */
  const scopedSource =
    period !== "all" && dashboard !== null
      ? { cost: dashboard.agentCostUsd, runs: dashboard.agentRuns }
      : null;
  const scoped = scopedSource !== null;
  const source =
    scopedSource ?? (roi === null ? null : { cost: roi.total_cost_usd, runs: roi.total_runs });
  const basis = scoped
    ? `${periodWindow(period)} — agent runs started within it`
    : "all time — agent spend has no period support server-side";

  if (source === null) {
    return {
      id: "spend",
      label: "Agent spend",
      value: NOT_MEASURED,
      spark: { kind: "bars", data: [] },
      insight: "Agent ROI has not loaded yet.",
      basis,
      measured: false,
    };
  }

  const windowsAlign = scoped || period === "all";
  const comparable = windowsAlign && funnel !== null;
  const perApplication = comparable && funnel.applied > 0 ? source.cost / funnel.applied : null;
  const perInterview =
    comparable && funnel.interviewed > 0 ? source.cost / funnel.interviewed : null;

  /*
   * WHY A RATIO IS MISSING — three different reasons, never conflated.
   *
   * The windows failing to line up and the funnel simply not having loaded are
   * not the same fact, and telling a reader to "select the all period" when the
   * funnel endpoint is the thing that is down sends them somewhere that cannot
   * help. `null` here means the stage itself is empty, which each row states in
   * its own words below.
   */
  const blocked: string | null = !windowsAlign
    ? `agent spend is all-time but the funnel is scoped to ${period}`
    : funnel === null
      ? "the funnel has not loaded, so there is no denominator to divide by"
      : null;

  const data: ChartDatum[] = [
    {
      label: "Cost per submitted application",
      value: perApplication,
      display: perApplication === null ? undefined : money(perApplication),
      note: blocked ?? "No application has been submitted yet, so there is nothing to divide by.",
    },
    {
      label: "Cost per interview",
      value: perInterview,
      display: perInterview === null ? undefined : money(perInterview),
      note:
        blocked ?? "No application has reached an interview yet, so there is nothing to divide by.",
    },
  ];

  return {
    id: "spend",
    label: "Agent spend",
    // Mercury numeral treatment (reference rule 4): the magnitude carries the
    // weight and the unit rides small beside it. It is also what keeps this
    // tile's text distinct from the Agent ROI panel's own "$8.16" — the two
    // render the SAME figure from the same field, and a page with two
    // identical strings is a page whose tests cannot tell them apart.
    value: source.cost.toFixed(2),
    unit: "USD",
    spark: {
      kind: "bars",
      data,
      nullMeaning:
        blocked === null
          ? "no application has reached that stage yet, so there is nothing to divide by"
          : !windowsAlign
            ? `agent spend is all-time and the funnel is scoped to ${period} — the two windows cannot be divided`
            : blocked,
    },
    delta:
      source.runs > 0
        ? {
            text: `${formatNumber(source.runs)} runs`,
            tone: "neutral",
            title: `${formatNumber(source.runs)} agent runs recorded, ${
              scoped ? `in ${periodWindow(period)}` : "all time"
            }.`,
          }
        : undefined,
    insight:
      perApplication !== null
        ? `${money(perApplication)} per submitted application.`
        : blocked === null
          ? "No application submitted yet, so cost per application cannot be divided."
          : !windowsAlign
            ? `Select the “all” period to compare spend with the funnel like for like.`
            : "The funnel has not loaded, so cost per application cannot be divided.",
    basis,
    measured: true,
  };
}

/* ------------------------------------------------------------------ */
/* 5 — RIGOR POLICY                                                    */
/* ------------------------------------------------------------------ */

const TIER_SHORT: Record<string, string> = {
  standard: "Standard",
  heightened: "Heightened",
  insufficient_data: "Insufficient data",
};

function rigorTile(input: ExecutiveSummaryInput): ExecTileModel {
  const { policy, policyHistory } = input;
  const basis = "all-time — the policy computes on every submission you have made";
  if (policy === null) {
    return {
      id: "rigor",
      label: "Rigor policy",
      value: NOT_MEASURED,
      spark: { kind: "bars", data: [] },
      insight: "The agent policy has not loaded yet.",
      basis,
      measured: false,
    };
  }
  const points = policyHistory?.points ?? [];
  const previous = points.length >= 2 ? points[points.length - 2] : null;
  const latest = points.length >= 1 ? points[points.length - 1] : null;
  const totalRuns = points.reduce((sum, p) => sum + p.runs, 0);

  return {
    id: "rigor",
    label: "Rigor policy",
    value: TIER_SHORT[policy.tier] ?? policy.tier,
    spark: {
      kind: "bars",
      data: points.map((p) => ({
        label: `${p.tier} · ${p.at ?? "date not recorded"}`,
        value: p.runs,
        display: `${formatNumber(p.runs)} run${p.runs === 1 ? "" : "s"}`,
      })),
    },
    delta:
      previous && latest && previous.tier !== latest.tier
        ? {
            text: `from ${TIER_SHORT[previous.tier] ?? previous.tier}`,
            tone: latest.tier === "heightened" ? "down" : "up",
            title: `The recorded tier changed from ${
              TIER_SHORT[previous.tier] ?? previous.tier
            } to ${TIER_SHORT[latest.tier] ?? latest.tier}.`,
          }
        : undefined,
    insight:
      points.length > 0
        ? `${formatNumber(totalRuns)} run${
            totalRuns === 1 ? "" : "s"
          } recorded across ${formatNumber(points.length)} tier point${
            points.length === 1 ? "" : "s"
          }.`
        : `Measured on ${formatNumber(
            policy.metricSnapshot.sampleSize,
          )} submitted application${policy.metricSnapshot.sampleSize === 1 ? "" : "s"}.`,
    basis,
    measured: true,
  };
}

/* ------------------------------------------------------------------ */

/**
 * The band, in reading order: how much went out, how much came back, how good
 * the matches were, what it cost, and what the agents are doing about it.
 *
 * Always FIVE tiles, in a fixed order, whether or not each one could be
 * measured — a band whose tiles appear and disappear as endpoints degrade
 * would reflow the page under the reader and hide the fact that something is
 * missing. An unmeasurable tile keeps its slot and states its reason.
 */
export function executiveSummary(input: ExecutiveSummaryInput): ExecTileModel[] {
  return [
    pipelineTile(input),
    conversionTile(input),
    qualityTile(input),
    spendTile(input),
    rigorTile(input),
  ];
}
