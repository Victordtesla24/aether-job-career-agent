/**
 * ANALYTICS-VIZ — the executive band's selectors.
 *
 * The band's whole claim is that its five insight lines are DETERMINISTIC
 * readings of real numbers: no model, no adjective the data did not earn, same
 * payload in → same string out. This file is what makes that claim checkable,
 * and it concentrates on the four places a "summary" traditionally starts
 * lying:
 *
 *   1. dividing by an empty denominator and calling the result 0;
 *   2. ranking an unmeasurable stage as the worst one;
 *   3. mixing an all-time numerator with a period-scoped denominator;
 *   4. asserting what the policy is DOING without asking the policy.
 */
import { describe, expect, it } from "vitest";

import {
  INTERVIEW_TARGET_PCT,
  bucketFloor,
  conversionPolicyNote,
  executiveSummary,
  normaliseTarget,
  numberFrom,
  steepestDropOff,
  summariseAts,
  type ExecutiveSummaryInput,
} from "../executive-summary";
import type { AgentPolicy, PolicyHistory } from "../../api/agentPolicy";

const FUNNEL = {
  period: "all",
  jobs_found: 8358,
  applied: 287,
  screened: 12,
  interviewed: 2,
  offers: 0,
};

const CONVERSION = {
  period: "all",
  found_to_applied: 3.4,
  applied_to_screened: 4.2,
  screened_to_interview: 16.7,
  interview_to_offer: 0,
  interview_conversion_rate: 0.7,
  interview_conversion_healthy: false,
};

const ATS = {
  buckets: [
    { range: "0-9", count: 0 },
    { range: "60-69", count: 4 },
    { range: "70-79", count: 9 },
    { range: "80-89", count: 6 },
    { range: "90-100", count: 1 },
  ],
  total: 20,
};

const ROI = { total_cost_usd: 8.16, total_runs: 8781, avg_duration_ms: 166_000 };

const POLICY: AgentPolicy = {
  tier: "heightened",
  triggers: ["conversion_below_20pct_target"],
  behaviour: "Heightened rigor: résumé tailoring runs up to 7 scoring iterations.",
  knobs: { maxIterations: 7 },
  thresholds: { interviewConversionTarget: 0.2, dimensionFloor: 80, minSampleSize: 5 },
  metricSnapshot: {
    sampleSize: 287,
    conversionRate: 0.7,
    dimensionScores: { cultureFit: 72.5 },
    dimensionSampleSize: 42,
    dimensionsEvaluated: 1,
    available: true,
    unavailableReason: null,
    interviewCount: 2,
  },
  perAgent: [],
};

const HISTORY: PolicyHistory = {
  available: true,
  reason: null,
  runsWithoutPolicy: 8781,
  thresholds: { interviewConversionTarget: 20, dimensionFloor: 80, minSampleSize: 5 },
  points: [
    {
      at: "2026-08-01T00:00:00Z",
      tier: "standard",
      runs: 2,
      conversionRate: 0,
      sampleSize: 2,
      interviewCount: 0,
      dimensionsBelowFloor: [],
      dimensionsEvaluated: 0,
      triggers: [],
    },
    {
      at: "2026-08-10T00:00:00Z",
      tier: "heightened",
      runs: 18,
      conversionRate: 0.7,
      sampleSize: 287,
      interviewCount: 2,
      dimensionsBelowFloor: ["cultureFit"],
      dimensionsEvaluated: 1,
      triggers: ["conversion_below_20pct_target"],
    },
  ],
};

function input(overrides: Partial<ExecutiveSummaryInput> = {}): ExecutiveSummaryInput {
  return {
    period: "all",
    funnel: FUNNEL,
    conversion: CONVERSION,
    ats: ATS,
    roi: ROI,
    policy: POLICY,
    policyHistory: HISTORY,
    ...overrides,
  };
}

function tile(id: string, overrides: Partial<ExecutiveSummaryInput> = {}) {
  const found = executiveSummary(input(overrides)).find((t) => t.id === id);
  if (!found) throw new Error(`no tile "${id}"`);
  return found;
}

describe("determinism", () => {
  it("produces byte-identical tiles for the same payload", () => {
    expect(JSON.stringify(executiveSummary(input()))).toBe(
      JSON.stringify(executiveSummary(input())),
    );
  });

  it("always renders the same five slots, in the same order, even when every endpoint failed", () => {
    const degraded = executiveSummary(
      input({ funnel: null, conversion: null, ats: null, roi: null, policy: null, policyHistory: null }),
    );
    expect(degraded.map((t) => t.id)).toEqual([
      "pipeline",
      "conversion",
      "quality",
      "spend",
      "rigor",
    ]);
    // A tile that could not be measured keeps its slot and says so — it never
    // falls back to 0 and never disappears.
    expect(degraded.every((t) => t.measured === false)).toBe(true);
    expect(degraded.every((t) => t.value === "—")).toBe(true);
    expect(degraded.every((t) => t.insight.length > 0)).toBe(true);
  });
});

describe("steepestDropOff", () => {
  it("finds the worst measured stage transition by SHARE CARRIED, not by absolute loss", () => {
    // Jobs found → Applied loses 8,071 rows but carries 3.43%; Applied →
    // Screened loses only 275 and carries 4.18%. The steeper transition is the
    // first one, and ranking by the raw number lost would have named the wrong
    // stage on every real funnel this product produces.
    expect(
      steepestDropOff([
        { label: "Jobs found", value: 8358 },
        { label: "Applied", value: 287 },
        { label: "Screened", value: 12 },
      ]),
    ).toMatchObject({ from: "Jobs found", to: "Applied" });
  });

  it("SKIPS a pair whose previous stage is zero — '0 of 0' is unmeasurable, not catastrophic", () => {
    expect(
      steepestDropOff([
        { label: "Jobs found", value: 0 },
        { label: "Applied", value: 0 },
      ]),
    ).toBeNull();
  });

  it("resolves ties to the earliest pair, so the answer is stable across renders", () => {
    const result = steepestDropOff([
      { label: "A", value: 10 },
      { label: "B", value: 5 },
      { label: "C", value: 2.5 },
    ]);
    expect(result).toMatchObject({ from: "A", to: "B" });
  });

  it("states the absence rather than a stage when nothing has volume", () => {
    expect(
      tile("pipeline", {
        funnel: { period: "all", jobs_found: 0, applied: 0, screened: 0, interviewed: 0, offers: 0 },
      }).insight,
    ).toContain("No stage has enough volume");
  });
});

describe("summariseAts", () => {
  it("computes the strong-match share and the modal band from the buckets", () => {
    expect(summariseAts(ATS)).toMatchObject({
      total: 20,
      strong: 7,
      strongPct: 35,
      modalRange: "70-79",
      modalCount: 9,
    });
  });

  it("returns a NULL share (never 0%) when nothing has been scored", () => {
    const empty = summariseAts({ buckets: [{ range: "0-9", count: 0 }], total: 0 });
    expect(empty.strongPct).toBeNull();
    expect(empty.modalRange).toBeNull();
  });

  it("reports the quality tile as unmeasured, not as 0%, on an empty distribution", () => {
    const t = tile("quality", { ats: { buckets: [{ range: "0-9", count: 0 }], total: 0 } });
    expect(t.measured).toBe(false);
    expect(t.value).toBe("—");
    expect(t.insight).toContain("No job has been scored yet");
  });

  it("reads the band floor out of the range string", () => {
    expect(bucketFloor("80-89")).toBe(80);
    expect(bucketFloor("90-100")).toBe(90);
    expect(Number.isNaN(bucketFloor("junk"))).toBe(true);
  });
});

describe("the spend tile refuses to divide two different windows", () => {
  it("computes cost per application only on the 'all' period", () => {
    const t = tile("spend");
    expect(t.insight).toBe("$0.03 per submitted application.");
    expect(t.spark.data[0].display).toBe("$0.03");
  });

  it("withholds the ratio on a scoped period and names the two windows that failed to line up", () => {
    const t = tile("spend", { period: "7d" });
    expect(t.spark.data[0].value).toBeNull();
    expect(t.insight).toContain("all");
    expect(t.spark.nullMeaning).toContain("all-time");
    expect(t.spark.nullMeaning).toContain("7d");
  });

  it("withholds the ratio when the denominator is empty, and says why", () => {
    const t = tile("spend", {
      funnel: { period: "all", jobs_found: 3, applied: 0, screened: 0, interviewed: 0, offers: 0 },
    });
    expect(t.spark.data[0].value).toBeNull();
    expect(t.insight).toContain("cannot be divided");
  });
});

describe("the conversion tile is judged against the policy's OWN target", () => {
  it("reads the target from the policy payload, normalising a fraction to points", () => {
    expect(normaliseTarget(0.2)).toBe(20);
    expect(normaliseTarget(20)).toBe(20);
    expect(tile("conversion").spark.target).toEqual({ value: 20, label: "20% target" });
  });

  it("falls back to the product-wide 1-in-5 target when no policy has loaded", () => {
    expect(tile("conversion", { policy: null }).spark.target).toEqual({
      value: INTERVIEW_TARGET_PCT,
      label: `${INTERVIEW_TARGET_PCT}% target`,
    });
  });

  it("states the gap as a measured delta chip, never as an invented trend", () => {
    expect(tile("conversion").delta).toMatchObject({ text: "19.3 pts to target", tone: "down" });
  });

  it("reports a met target without a negative gap", () => {
    const t = tile("conversion", {
      conversion: { ...CONVERSION, interview_conversion_rate: 24, interview_conversion_healthy: true },
    });
    expect(t.delta?.text).toBe("at target");
    expect(t.insight).toBe("At or above the 1-in-5 target.");
  });

  it("sources the escalation claim from the tier the backend resolved (F-UAX-04)", () => {
    expect(conversionPolicyNote("heightened", false)).toContain("escalated to heightened");
    // `insufficient_data` explicitly does NOT escalate (quality_policy.py rule
    // 2) and must never be described as if it had.
    expect(conversionPolicyNote("insufficient_data", false)).not.toContain("escalated");
    expect(conversionPolicyNote("insufficient_data", false)).toContain("Too few submissions");
    expect(conversionPolicyNote(undefined, false)).toContain("escalates rigor once");
    expect(conversionPolicyNote("heightened", true)).toBe("At or above the 1-in-5 target.");
  });
});

describe("the rigor tile", () => {
  it("counts the runs the recorded tiers actually cover", () => {
    expect(tile("rigor").value).toBe("Heightened");
    expect(tile("rigor").insight).toBe("20 runs recorded across 2 tier points.");
  });

  it("reports a tier CHANGE only when two recorded points genuinely differ", () => {
    expect(tile("rigor").delta).toMatchObject({ text: "from Standard" });
    expect(
      tile("rigor", { policyHistory: { ...HISTORY, points: [HISTORY.points[1]] } }).delta,
    ).toBeUndefined();
  });

  it("falls back to the policy's own sample size when no history was recorded", () => {
    expect(tile("rigor", { policyHistory: null }).insight).toBe(
      "Measured on 287 submitted applications.",
    );
  });
});

describe("numberFrom refuses to coerce", () => {
  it("returns null for a missing key, a string or a NaN", () => {
    expect(numberFrom({ a: 1 }, "a")).toBe(1);
    expect(numberFrom({ a: "20" }, "a")).toBeNull();
    expect(numberFrom({ a: Number.NaN }, "a")).toBeNull();
    expect(numberFrom(null, "a")).toBeNull();
    expect(numberFrom(undefined, "a")).toBeNull();
  });
});

describe("one window per tile", () => {
  it("declares a period-scoped window on the period-scoped tiles and an all-time one on the rest", () => {
    const tiles = executiveSummary(input({ period: "7d" }));
    const byId = Object.fromEntries(tiles.map((t) => [t.id, t.basis]));
    expect(byId.pipeline).toContain("7d");
    expect(byId.conversion).toContain("7d");
    // These three have no period support server-side and must say so rather
    // than inheriting the selector's window by silence.
    expect(byId.quality).toContain("all time");
    expect(byId.spend).toContain("all time");
    expect(byId.rigor).toContain("all-time");
  });
});
