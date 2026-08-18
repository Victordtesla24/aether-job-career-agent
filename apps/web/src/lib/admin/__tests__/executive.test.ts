/**
 * ADMIN-2.0 FE-1 — the EXECUTIVE DASHBOARD's selectors.
 *
 * WHAT THESE TESTS ARE ACTUALLY PROTECTING. The platform has ~10 accounts and
 * ~0 external paying subscribers today. Every plausible "executive dashboard"
 * shortcut produces a confident-looking figure that is not true:
 *
 *   · a margin that quietly divides A$ revenue by US$ LLM cost — the API
 *     explicitly refuses to net them (`fxRateApplied: null`);
 *   · a step-to-step funnel drop-off — the API states its stages are
 *     INDEPENDENT milestone counts, not nested subsets;
 *   · a conversion percentage off a denominator of ten;
 *   · a tile that vanishes when its number is missing;
 *   · and the inverse error: hiding a real COUNT because the block is flagged
 *     `insufficientData`, when the API's own docstring says that flag
 *     suppresses the RATE-shaped reading, not the count.
 *
 * Each is pinned below.
 *
 * FIXTURES GO THROUGH THE REAL SCHEMA. Every fixture is a raw payload handed
 * to `AdminExecutiveMetricsSchema.parse` rather than a hand-built typed object,
 * so if the client schema ever stops producing what the selectors expect these
 * tests break here rather than in production.
 */
import { describe, expect, it } from "vitest";

import {
  MISSING_PAYLOAD_REASON,
  buildCostVsRevenue,
  buildFunnelSteps,
  buildKpiTiles,
  buildPlanMix,
  buildReferrers,
  buildRunSeries,
  buildSignupSeries,
  formatAudTabular,
  formatUsdTabular,
  rateReadable,
} from "../executive";
import {
  AdminExecutiveMetricsSchema,
  type AdminExecutiveMetrics,
  type AdminFunnelBlock,
  type AdminRevenueBlock,
  type AdminSignupsBlock,
} from "../../api/adminMetrics";

/** 30 zero-filled days ending on the given date, with `counts` applied to the tail. */
function days(counts: number[], last = "2026-08-14"): Array<{ date: string; count: number }> {
  const end = new Date(`${last}T00:00:00Z`).getTime();
  const total = 30;
  const series: Array<{ date: string; count: number }> = [];
  for (let i = total - 1; i >= 0; i -= 1) {
    const d = new Date(end - i * 86_400_000);
    series.push({ date: d.toISOString().slice(0, 10), count: 0 });
  }
  for (let i = 0; i < counts.length; i += 1) {
    series[total - counts.length + i].count = counts[i];
  }
  return series;
}

/** A healthy platform: enough accounts that rates are readable. */
function fullMetrics(): AdminExecutiveMetrics {
  const signupSeries = days([2, 3, 1, 4, 2, 3, 4, 1, 2, 0, 3, 2, 1, 2]);
  return AdminExecutiveMetricsSchema.parse({
    asOf: "2026-08-14T23:00:00Z",
    windowDays: 30,
    currencies: { revenue: "AUD", llmCost: "USD" },
    gstRegistered: false,
    insufficientDataThreshold: 20,
    revenue: {
      currency: "AUD",
      estimate: true,
      source: "local Subscription rows joined to the Plan catalogue",
      mrrAud: 348,
      arrAud: 4176,
      paidSubscribers: 6,
      customPricedCount: 1,
      unbackedPaidRows: 1,
      excludedAdminRows: 2,
      excludedDeletedRows: 0,
      byPlan: [
        { planId: "pro", name: "Pro", count: 4, mrrAud: 232 },
        { planId: "starter", name: "Starter", count: 2, mrrAud: 116 },
      ],
      sampleSize: 6,
      insufficientData: false,
    },
    signupsByDay: {
      series: signupSeries,
      total: signupSeries.reduce((a, r) => a + r.count, 0),
      windowDays: 30,
      excludes: "admin accounts and soft-deleted accounts",
      sampleSize: 30,
      insufficientData: false,
    },
    runsByDay: {
      series: days([30, 41, 22]).map((r) => ({ date: r.date, runs: r.count, costUsd: r.count * 0.1 })),
      totalRuns: 93,
      totalCostUsd: 9.3,
      currency: "USD",
      windowDays: 30,
      includes: "all accounts (admin runs cost real money too)",
      sampleSize: 93,
      insufficientData: false,
    },
    funnel: {
      window: "all time",
      stages: [
        { key: "signup", label: "Signed up", count: 40, shareOfSignups: 1 },
        { key: "firstRun", label: "Ran an agent", count: 24, shareOfSignups: 0.6 },
        // AUD-META-1 (r2): "status <> 'draft'" is preparation, not proof of a
        // send — never labelled "submitted"/"applied". The distinct verified
        // send count is its own stage, "firstTransmission".
        { key: "firstSubmission", label: "Prepared an application", count: 12, shareOfSignups: 0.3 },
        { key: "firstTransmission", label: "Sent an application", count: 8, shareOfSignups: 0.2 },
        { key: "paid", label: "Paid", count: 6, shareOfSignups: 0.15 },
      ],
      definitions: { _shape: "Stages are INDEPENDENT milestone counts, not nested subsets." },
      sampleSize: 40,
      insufficientData: false,
    },
    costVsRevenue: {
      windowDays: 30,
      llmCostUsd: 64.25,
      grossRevenueAud: 400,
      refundsAud: 52,
      revenueAud: 348,
      paymentCount: 24,
      fxRateApplied: null,
      note: "LLM cost is USD and revenue is AUD. No exchange rate is applied.",
      revenueSource: "real invoice.paid Stripe webhook events",
      unparsablePaymentEvents: 0,
      unattributedRefundEvents: 0,
      sampleSize: 24,
      insufficientData: false,
    },
    topReferrers: {
      agents: [
        {
          id: "sa_1",
          name: "Priya K",
          referralCode: "PRIYA10",
          status: "active",
          commissionPct: 0.15,
          attributedSignups: 7,
          convertedPaid: 2,
        },
      ],
      totalAgentsWithSignups: 1,
      totalAttributedSignups: 7,
      limit: 5,
      sampleSize: 7,
      insufficientData: false,
    },
    excluded: { adminAccounts: 2, deletedAccounts: 0 },
  });
}

/** Production TODAY: ten accounts, nothing paid, one stale local row. */
function tinyRealMetrics(): AdminExecutiveMetrics {
  const m = fullMetrics();
  const revenue = revenueOf(m);
  revenue.mrrAud = 0;
  revenue.arrAud = 0;
  revenue.paidSubscribers = 0;
  revenue.unbackedPaidRows = 1;
  revenue.byPlan = [];
  revenue.sampleSize = 0;
  revenue.insufficientData = true;

  const signups = signupsOf(m);
  signups.series = days([1, 0, 1, 0, 0, 2, 0, 1, 0, 0, 1, 0, 0, 0]);
  signups.total = 6;
  signups.sampleSize = 6;
  signups.insufficientData = true;

  const funnel = funnelOf(m);
  funnel.stages = [
    { key: "signup", label: "Signed up", count: 10, shareOfSignups: 1 },
    { key: "firstRun", label: "Ran an agent", count: 4, shareOfSignups: 0.4 },
    { key: "firstSubmission", label: "Prepared an application", count: 1, shareOfSignups: 0.1 },
    // Production TODAY: 1 account left an application non-draft, 0 with a
    // verified send behind it — the exact "prepared, never sent" gap
    // AUD-META-1 exists to stop the dashboard from hiding.
    { key: "firstTransmission", label: "Sent an application", count: 0, shareOfSignups: 0 },
    { key: "paid", label: "Paid", count: 0, shareOfSignups: 0 },
  ];
  funnel.sampleSize = 10;
  funnel.insufficientData = true;

  const cost = m.costVsRevenue;
  if (!cost) throw new Error("fixture has no costVsRevenue block");
  cost.llmCostUsd = 12.6;
  cost.grossRevenueAud = 0;
  cost.refundsAud = 0;
  cost.revenueAud = 0;
  cost.paymentCount = 0;
  cost.sampleSize = 0;
  cost.insufficientData = true;

  const referrers = m.topReferrers;
  if (!referrers) throw new Error("fixture has no topReferrers block");
  referrers.agents = [];
  referrers.totalAttributedSignups = 0;
  referrers.sampleSize = 0;
  referrers.insufficientData = true;
  return m;
}

/* A fixture missing the block it is about is a broken fixture, so these throw
 * rather than letting a test silently assert nothing. */
function revenueOf(m: AdminExecutiveMetrics): AdminRevenueBlock {
  if (!m.revenue) throw new Error("fixture has no revenue block");
  return m.revenue;
}
function signupsOf(m: AdminExecutiveMetrics): AdminSignupsBlock {
  if (!m.signupsByDay) throw new Error("fixture has no signupsByDay block");
  return m.signupsByDay;
}
function funnelOf(m: AdminExecutiveMetrics): AdminFunnelBlock {
  if (!m.funnel) throw new Error("fixture has no funnel block");
  return m.funnel;
}

describe("money formatting", () => {
  it("names both currencies, because the API says they are not comparable", () => {
    expect(formatAudTabular(1234.5)).toBe("A$1,234.50");
    expect(formatUsdTabular(12.6)).toBe("US$12.60");
    expect(formatAudTabular(0)).toBe("A$0.00");
  });
});

describe("rateReadable — a count is not a rate", () => {
  it("passes a block the API considers sufficient", () => {
    expect(rateReadable({ sampleSize: 40, insufficientData: false }, 20, "accounts").readable).toBe(
      true,
    );
  });

  it("refuses a rate below the API's threshold, naming BOTH numbers", () => {
    const out = rateReadable({ sampleSize: 10, insufficientData: true }, 20, "accounts");
    expect(out.readable).toBe(false);
    expect(out.reason).toContain("10");
    expect(out.reason).toContain("20");
    // …and says the counts themselves are still real.
    expect(out.reason).toMatch(/counts below are real/i);
  });

  it("refuses when the block is absent entirely", () => {
    expect(rateReadable(null, 20, "accounts").readable).toBe(false);
  });
});

describe("buildCostVsRevenue — the API refuses to net the currencies, and so do we", () => {
  it("reports both figures side by side without combining them", () => {
    const out = buildCostVsRevenue(fullMetrics());
    expect(out.measured).toBe(true);
    expect(out.llmCostUsd).toBe(64.25);
    expect(out.revenueAud).toBe(348);
    expect(out.fxRateApplied).toBeNull();
    expect(out.note).toMatch(/no exchange rate/i);
  });

  it("exposes no margin field at all — there is no place to put a fabricated one", () => {
    const out = buildCostVsRevenue(fullMetrics());
    expect(Object.keys(out)).not.toContain("marginPct");
    expect(Object.keys(out)).not.toContain("margin");
  });

  it("says the payload is missing rather than reporting zeroes", () => {
    const out = buildCostVsRevenue(null);
    expect(out.measured).toBe(false);
    expect(out.reason).toBe(MISSING_PAYLOAD_REASON);
    expect(out.llmCostUsd).toBeNull();
    expect(out.revenueAud).toBeNull();
  });
});

describe("buildFunnelSteps — shares of ONE population, not step-to-step drop-off", () => {
  it("converts the API's fractional share into a percentage", () => {
    const out = buildFunnelSteps(fullMetrics());
    expect(out.measured).toBe(true);
    expect(out.steps.map((s) => s.label)).toEqual([
      "Signed up",
      "Ran an agent",
      "Prepared an application",
      "Sent an application",
      "Paid",
    ]);
    expect(out.steps[0].sharePct).toBeCloseTo(100, 5);
    expect(out.steps[1].sharePct).toBeCloseTo(60, 5);
    expect(out.steps[4].sharePct).toBeCloseTo(15, 5);
  });

  it("reports the stage-to-stage figure in percentage POINTS, not as a rate", () => {
    const out = buildFunnelSteps(fullMetrics());
    expect(out.steps[0].shareDeltaPoints).toBeNull(); // nothing above the first
    // 100 → 60 is a fall of 40 POINTS (it is NOT "40% of the previous step").
    expect(out.steps[1].shareDeltaPoints).toBeCloseTo(-40, 5);
    expect(out.steps[2].shareDeltaPoints).toBeCloseTo(-30, 5);
    // 30% prepared → 20% verifiably sent is a further fall of 10 POINTS.
    expect(out.steps[3].shareDeltaPoints).toBeCloseTo(-10, 5);
    expect(out.steps[4].shareDeltaPoints).toBeCloseTo(-5, 5);
  });

  it("carries the API's own 'stages are independent' caveat verbatim", () => {
    expect(buildFunnelSteps(fullMetrics()).shapeNote).toContain("INDEPENDENT");
  });

  it("keeps the COUNTS but gates the SHARES when the sample is small", () => {
    const out = buildFunnelSteps(tinyRealMetrics());
    // Counts survive — six real accounts is a real fact.
    expect(out.measured).toBe(true);
    expect(out.steps.map((s) => s.count)).toEqual([10, 4, 1, 0, 0]);
    // The rate reading does not.
    expect(out.rate.readable).toBe(false);
    expect(out.rate.reason).toContain("10");
  });

  it("names the single biggest fall so the warn tone means one thing", () => {
    // Falls of 40, 30 and 15 points: the first is the biggest.
    expect(buildFunnelSteps(fullMetrics()).steepestFallKey).toBe("firstRun");
  });

  it("names no biggest fall when no stage falls", () => {
    const m = fullMetrics();
    funnelOf(m).stages = [
      { key: "signup", label: "Signed up", count: 40, shareOfSignups: 1 },
      { key: "firstRun", label: "Ran an agent", count: 40, shareOfSignups: 1 },
    ];
    expect(buildFunnelSteps(m).steepestFallKey).toBeNull();
  });

  it("treats an unmeasured stage as unmeasured, never as zero", () => {
    const m = fullMetrics();
    funnelOf(m).stages[2].count = null;
    funnelOf(m).stages[2].shareOfSignups = null;
    const out = buildFunnelSteps(m);
    expect(out.steps[2].count).toBeNull();
    expect(out.steps[2].sharePct).toBeNull();
    expect(out.steps[3].shareDeltaPoints).toBeNull();
    expect(out.nullMeaning).toBeTruthy();
  });

  it("says the payload is missing rather than drawing an empty funnel", () => {
    const out = buildFunnelSteps(null);
    expect(out.measured).toBe(false);
    expect(out.reason).toBe(MISSING_PAYLOAD_REASON);
    expect(out.steps).toEqual([]);
    expect(out.steepestFallKey).toBeNull();
  });
});

describe("buildKpiTiles — five slots, always, in one order", () => {
  it("renders every headline figure from the payload", () => {
    const tiles = buildKpiTiles(fullMetrics());
    expect(tiles.map((t) => t.id)).toEqual([
      "mrr",
      "paid-subscribers",
      "signups-7d",
      "conversion",
      "cost-vs-revenue",
    ]);
    expect(tiles[0].value).toBe("A$348.00");
    expect(tiles[1].value).toBe("6");
    // The last seven daily counts of the fixture series: 1+2+0+3+2+1+2 = 11.
    expect(tiles[2].value).toBe("11");
    expect(tiles[3].value).toBe("15.0%");
    expect(tiles[4].value).toBe("US$64.25");
  });

  it("keeps all five slots when the payload never arrived, each with a reason", () => {
    const tiles = buildKpiTiles(null);
    expect(tiles).toHaveLength(5);
    for (const tile of tiles) {
      expect(tile.measured).toBe(false);
      expect(tile.value).toBe("—");
      expect(tile.reason).toBe(MISSING_PAYLOAD_REASON);
    }
  });

  it("still shows the COUNT tiles at ten accounts — small is not unmeasured", () => {
    const tiles = buildKpiTiles(tinyRealMetrics());
    expect(tiles.find((t) => t.id === "mrr")?.value).toBe("A$0.00");
    expect(tiles.find((t) => t.id === "paid-subscribers")?.value).toBe("0");
    expect(tiles.find((t) => t.id === "signups-7d")?.measured).toBe(true);
    expect(tiles.find((t) => t.id === "cost-vs-revenue")?.value).toBe("US$12.60");
  });

  it("gates ONLY the rate-shaped tile, with the API's own threshold in the reason", () => {
    const conversion = buildKpiTiles(tinyRealMetrics()).find((t) => t.id === "conversion");
    expect(conversion?.measured).toBe(false);
    expect(conversion?.value).toBe("—");
    expect(conversion?.reason).toContain("20");
    // The counts behind the refused rate stay on the tile.
    expect(conversion?.detail).toContain("0");
    expect(conversion?.detail).toContain("10");
  });

  it("never invents an MRR delta the API does not publish, and says why", () => {
    const mrr = buildKpiTiles(fullMetrics()).find((t) => t.id === "mrr");
    expect(mrr?.delta).toBeUndefined();
    expect(mrr?.detail).toMatch(/no prior MRR measurement/i);
  });

  it("labels the MRR estimate as an estimate", () => {
    expect(buildKpiTiles(fullMetrics()).find((t) => t.id === "mrr")?.detail).toMatch(/estimate/i);
  });

  it("discloses local rows that look paid but have nothing behind them at Stripe", () => {
    const subs = buildKpiTiles(tinyRealMetrics()).find((t) => t.id === "paid-subscribers");
    expect(subs?.detail).toMatch(/no Stripe subscription/i);
  });

  it("quotes the API's refusal to net the two currencies on the cost tile", () => {
    const tile = buildKpiTiles(fullMetrics()).find((t) => t.id === "cost-vs-revenue");
    expect(tile?.detail).toMatch(/no exchange rate/i);
    expect(tile?.detail).toContain("A$348.00");
  });

  it("derives the 7-day signup delta from the two real weeks, never from nothing", () => {
    // Fixture's last 14 days: [2,3,1,4,2,3,4] then [1,2,0,3,2,1,2].
    // Previous 7 = 19, last 7 = 11, so the change is −8.
    const tile = buildKpiTiles(fullMetrics()).find((t) => t.id === "signups-7d");
    expect(tile?.delta?.tone).toBe("down");
    expect(tile?.delta?.text).toContain("8");
    expect(tile?.delta?.title).toContain("19");
  });

  it("marks a rise as a rise and a flat fortnight as neither", () => {
    const up = fullMetrics();
    signupsOf(up).series = days([0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1]);
    expect(buildKpiTiles(up).find((t) => t.id === "signups-7d")?.delta?.tone).toBe("up");

    const flat = fullMetrics();
    flat.signupsByDay!.series = days([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]);
    expect(buildKpiTiles(flat).find((t) => t.id === "signups-7d")?.delta?.tone).toBe("neutral");
  });

  it("refuses a 7-day TOTAL when a day inside the week was never measured", () => {
    const m = fullMetrics();
    const series = signupsOf(m).series;
    series[series.length - 3].count = null;
    const tile = buildKpiTiles(m).find((t) => t.id === "signups-7d");
    expect(tile?.measured).toBe(false);
    expect(tile?.reason).toMatch(/undercount/i);
  });

  it("declares one window per tile and hands the SAME string to the spark", () => {
    for (const tile of buildKpiTiles(fullMetrics())) {
      expect(tile.basis.trim().length).toBeGreaterThan(0);
      expect(tile.spark.windowLabel).toBe(tile.basis);
    }
  });

  it("never emits a spark datum with a blank label (chart law C-5)", () => {
    for (const tile of buildKpiTiles(fullMetrics())) {
      for (const datum of tile.spark.data) {
        expect(datum.label.trim().length).toBeGreaterThan(0);
      }
    }
  });

  it("declares what null means whenever a spark mixes a real 0 with a null", () => {
    const m = fullMetrics();
    const series = signupsOf(m).series;
    series[series.length - 1].count = null;
    series[series.length - 2].count = 0;
    // The 7-day total is refused (see above), so the tile falls back to a
    // single-datum bullet — which cannot mix 0 and null and needs no
    // nullMeaning. What must never happen is a `bars` spark with both and no
    // declaration, which would dev-throw inside <ChartFrame>.
    const tile = buildKpiTiles(m).find((t) => t.id === "signups-7d");
    const mixes =
      tile!.spark.data.some((d) => d.value === 0) && tile!.spark.data.some((d) => d.value === null);
    expect(mixes ? Boolean(tile!.spark.nullMeaning) : true).toBe(true);
  });
});

describe("series, plan mix and referrers", () => {
  it("turns signups-by-day into labelled points and keeps the API's exclusion note", () => {
    const out = buildSignupSeries(fullMetrics());
    expect(out.measured).toBe(true);
    expect(out.points).toHaveLength(30);
    expect(out.points[0].label.trim().length).toBeGreaterThan(0);
    expect(out.scopeNote).toContain("admin accounts");
  });

  it("draws the real daily counts but refuses the TREND reading when the sample is small", () => {
    const out = buildSignupSeries(tinyRealMetrics());
    expect(out.measured).toBe(true); // the counts are real and are drawn
    expect(out.rate.readable).toBe(false); // the shape is not yet a trend
    expect(out.rate.reason).toContain("20");
  });

  it("refuses an empty series rather than drawing a flat line at zero", () => {
    const m = fullMetrics();
    signupsOf(m).series = [];
    const out = buildSignupSeries(m);
    expect(out.measured).toBe(false);
    expect(out.points).toEqual([]);
    expect(out.reason).toBeTruthy();
  });

  it("reads run volume from the runs block, counting runs rather than cost", () => {
    const out = buildRunSeries(fullMetrics());
    expect(out.measured).toBe(true);
    expect(out.total).toBe(93);
    expect(out.scopeNote).toContain("all accounts");
  });

  it("builds the plan mix from real per-plan counts", () => {
    const out = buildPlanMix(fullMetrics());
    expect(out.measured).toBe(true);
    expect(out.segments.map((s) => s.label)).toEqual(["Pro", "Starter"]);
    expect(out.segments[0].value).toBe(4);
  });

  it("reports an empty plan mix as unmeasured, not as an empty ring", () => {
    const out = buildPlanMix(tinyRealMetrics());
    expect(out.measured).toBe(false);
    expect(out.reason).toBeTruthy();
    expect(out.segments).toEqual([]);
  });

  it("declares what a null plan count means, so <Donut> cannot dev-throw on it", () => {
    // <ChartFrame> THROWS on a series that mixes a real 0 with a null and does
    // not say what the null means (C-2). One empty plan plus one unreported
    // plan is exactly that series.
    const m = fullMetrics();
    revenueOf(m).byPlan = [
      { planId: "pro", name: "Pro", count: 0, mrrAud: 0 },
      { planId: "power", name: "Power", count: null, mrrAud: null },
    ];
    expect(buildPlanMix(m).nullMeaning).toBeTruthy();
    expect(buildPlanMix(fullMetrics()).nullMeaning).toBeUndefined();
  });

  it("lists referrers the API returned, and says so honestly when there are none", () => {
    expect(buildReferrers(fullMetrics()).agents).toHaveLength(1);
    const empty = buildReferrers(tinyRealMetrics());
    expect(empty.measured).toBe(false);
    expect(empty.reason).toMatch(/no sales agent/i);
  });
});
