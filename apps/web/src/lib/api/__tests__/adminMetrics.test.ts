/**
 * ADMIN-2.0 FE-1 — the `GET /admin/metrics/executive` client contract.
 *
 * The shape asserted here is transcribed from BE-2's own payload builder
 * (`apps/api/app/repositories/admin_metrics.py` › `executive_metrics`), not
 * guessed — see the header of `../adminMetrics` for the three API design
 * decisions the frontend is bound by.
 *
 * WHY THE SCHEMA IS DELIBERATELY TOLERANT, AND WHY THAT IS NOT A SILENT
 * FALLBACK. BE-2 lands on the same branch as this slice and may still move. A
 * strict schema would turn any naming drift into a white screen on the owner's
 * dashboard; a *silently* lenient one would turn it into a page full of
 * confident zeroes. The rule pinned below is the third option: a block the
 * payload does not carry parses to `null`, and every consumer renders that as
 * "the API did not return this block". The absence is LOUD and it is never a
 * number.
 */
import { describe, expect, it } from "vitest";

import { AdminExecutiveMetricsSchema, SECTION_ABSENT_REASON } from "../adminMetrics";

const MINIMAL = {
  asOf: "2026-08-14T23:00:00Z",
  revenue: { mrrAud: 0, paidSubscribers: 0, insufficientData: true },
};

describe("AdminExecutiveMetricsSchema", () => {
  it("parses a payload that carries only some blocks", () => {
    const parsed = AdminExecutiveMetricsSchema.parse(MINIMAL);
    expect(parsed.revenue?.mrrAud).toBe(0);
    expect(parsed.signupsByDay).toBeNull();
    expect(parsed.funnel).toBeNull();
    expect(parsed.costVsRevenue).toBeNull();
  });

  it("keeps an absent block as null — never as an empty object of zeroes", () => {
    const parsed = AdminExecutiveMetricsSchema.parse(MINIMAL);
    expect(parsed.runsByDay).toBeNull();
    expect(SECTION_ABSENT_REASON.length).toBeGreaterThan(0);
  });

  it("ignores unknown keys so a richer BE-2 payload still parses", () => {
    const parsed = AdminExecutiveMetricsSchema.parse({
      ...MINIMAL,
      somethingBE2AddedLater: { nested: true },
      revenue: { ...MINIMAL.revenue, byStatus: { active: 2 }, customPricedCount: 1 },
    });
    expect(parsed.revenue?.paidSubscribers).toBe(0);
    expect(parsed.revenue?.customPricedCount).toBe(1);
  });

  it("coerces a non-finite number to null rather than rendering NaN", () => {
    const parsed = AdminExecutiveMetricsSchema.parse({
      ...MINIMAL,
      costVsRevenue: { llmCostUsd: Number.NaN, revenueAud: Number.POSITIVE_INFINITY },
    });
    expect(parsed.costVsRevenue?.llmCostUsd).toBeNull();
    expect(parsed.costVsRevenue?.revenueAud).toBeNull();
  });

  it("keeps fxRateApplied null — the API's refusal to apply a rate", () => {
    const parsed = AdminExecutiveMetricsSchema.parse({
      ...MINIMAL,
      costVsRevenue: { llmCostUsd: 12.5, revenueAud: 0, fxRateApplied: null, insufficientData: true },
    });
    expect(parsed.costVsRevenue?.fxRateApplied).toBeNull();
  });

  it("defaults insufficientData to true when the API does not say", () => {
    // Fail closed: an unflagged block is treated as unproven, not as proven.
    const parsed = AdminExecutiveMetricsSchema.parse({
      asOf: "2026-08-14T23:00:00Z",
      signupsByDay: { total: 3, series: [{ date: "2026-08-14", count: 3 }] },
    });
    expect(parsed.signupsByDay?.insufficientData).toBe(true);
  });

  it("still parses when the payload has no asOf stamp", () => {
    const parsed = AdminExecutiveMetricsSchema.parse({ revenue: MINIMAL.revenue });
    expect(parsed.asOf).toBeNull();
  });

  it("drops a malformed row instead of rejecting the whole dashboard", () => {
    const parsed = AdminExecutiveMetricsSchema.parse({
      ...MINIMAL,
      funnel: {
        stages: [
          { key: "signup", label: "Signed up", count: 10, shareOfSignups: 1 },
          { key: "broken" }, // no label — cannot be drawn honestly (C-5)
        ],
        insufficientData: true,
      },
    });
    expect(parsed.funnel?.stages).toHaveLength(1);
    expect(parsed.funnel?.stages[0].key).toBe("signup");
  });

  it("keeps the API's stage definitions, including the _shape caveat", () => {
    const parsed = AdminExecutiveMetricsSchema.parse({
      ...MINIMAL,
      funnel: {
        stages: [],
        definitions: { _shape: "Stages are INDEPENDENT milestone counts.", signup: "Accounts." },
        insufficientData: true,
      },
    });
    expect(parsed.funnel?.definitions?._shape).toContain("INDEPENDENT");
  });

  it("reads the threshold from the payload rather than assuming one", () => {
    const parsed = AdminExecutiveMetricsSchema.parse({
      ...MINIMAL,
      insufficientDataThreshold: 20,
      currencies: { revenue: "AUD", llmCost: "USD" },
    });
    expect(parsed.insufficientDataThreshold).toBe(20);
    expect(parsed.currencies?.llmCost).toBe("USD");
  });
});
