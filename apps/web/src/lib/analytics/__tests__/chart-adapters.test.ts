/**
 * S-UI-REBUILD §4 — the chart data adapters, as pure functions.
 *
 * These map already-fetched API shapes onto the chart kit's props. They are
 * pure so the honesty rules that live in the DATA (rather than the rendering)
 * can be pinned without mounting a page: a `0` must stay a `0`, a `null` must
 * stay a `null`, and an unmeasured dimension must never acquire a score.
 *
 * The kit enforces C-1..C-5 at render time; these tests pin that we hand it
 * truthful input in the first place. Rendering a zero honestly is worthless if
 * the adapter invented the zero.
 */
import { describe, expect, it } from "vitest";

import type { AtsDistribution, Funnel } from "../../api/analytics";
import { atsBuckets, fitDimensions, funnelSteps } from "../chart-adapters";

function funnel(overrides: Partial<Funnel> = {}): Funnel {
  return {
    period: "all",
    jobs_found: 8358,
    applied: 287,
    screened: 0,
    interviewed: 0,
    offers: 0,
    ...overrides,
  };
}

describe("funnelSteps — a measured zero stays a zero", () => {
  it("keeps 0 as 0 and never converts it to null", () => {
    const steps = funnelSteps(funnel());
    expect(steps.map((s) => s.label)).toEqual([
      "Jobs found",
      "Applied",
      "Screened",
      "Interviewed",
      "Offers",
    ]);
    // These stages were genuinely measured and are genuinely zero. Turning them
    // into `null` would claim we never looked (C-2 in reverse) and would strip
    // the C-1 zero tick the kit draws.
    expect(steps.slice(2).every((s) => s.value === 0)).toBe(true);
    expect(steps.some((s) => s.value === null)).toBe(false);
  });

  it("carries the exact API values through untouched", () => {
    const steps = funnelSteps(funnel({ jobs_found: 12, applied: 5, screened: 3 }));
    expect(steps.map((s) => s.value)).toEqual([12, 5, 3, 0, 0]);
  });

  it("explains the 'Jobs found' superset rather than leaving two numbers to look like a bug", () => {
    // M-04/M-06: the funnel's top stage is cumulative all-time discovery, which
    // is legitimately larger than the live Jobs board list.
    const [jobsFound] = funnelSteps(funnel());
    expect(jobsFound.note).toMatch(/all time|discovered/i);
  });
});

describe("atsBuckets — an empty bucket is not an unmeasured bucket", () => {
  const ats: AtsDistribution = {
    buckets: [
      { range: "0-19", count: 0 },
      { range: "20-39", count: 4 },
      { range: "40-59", count: 120 },
    ],
    total: 124,
  };

  it("passes a real 0 through as 0, never as null", () => {
    const buckets = atsBuckets(ats);
    expect(buckets[0]).toMatchObject({ range: "0-19", count: 0 });
    expect(buckets.some((b) => b.count === null)).toBe(false);
  });

  it("keeps the RANGE label the API gave, not a single edge value", () => {
    // The current page renders `bucket.range.split("-")[0]`, i.e. "0" for the
    // 0-19 bucket — which reads as an axis value rather than a band.
    expect(atsBuckets(ats).map((b) => b.range)).toEqual(["0-19", "20-39", "40-59"]);
  });

  it("returns an empty list for an empty distribution rather than inventing bands", () => {
    expect(atsBuckets({ buckets: [], total: 0 })).toEqual([]);
  });
});

describe("fitDimensions — the most dangerous chart in the product", () => {
  it("marks a dimension the server did not evaluate as unmeasured, with no score", () => {
    const dims = fitDimensions({ "Role alignment": 82, Seniority: 61 }, 10);
    const measured = dims.filter((d) => d.measured);
    const unmeasured = dims.filter((d) => !d.measured);

    expect(measured).toHaveLength(2);
    expect(unmeasured).toHaveLength(8);
    // Collapsing an unmeasured dimension to 0 would draw a specific false claim
    // about the candidate — the spec calls this out by name.
    for (const dim of unmeasured) {
      expect(dim).not.toHaveProperty("score");
      // `reason` is the kit's field on the unmeasured arm; it reaches the
      // hidden data table as "not measured — <reason>".
      expect("reason" in dim && dim.reason).toMatch(/not|no /i);
    }
  });

  it("never pads beyond the dimensions the server actually names", () => {
    const dims = fitDimensions({ "Role alignment": 82 }, 2);
    expect(dims).toHaveLength(2);
    expect(dims.filter((d) => d.measured)).toHaveLength(1);
  });

  it("reports an empty score map as entirely unmeasured, not as a zero profile", () => {
    const dims = fitDimensions({}, 10);
    expect(dims).toHaveLength(10);
    expect(dims.every((d) => !d.measured)).toBe(true);
    // A radar of ten zeroes is a portrait of a terrible candidate. A radar of
    // ten hollow markers is the truth: we have not scored this yet.
    expect(dims.some((d) => "score" in d && d.score === 0)).toBe(false);
  });

  it("keeps a genuine zero score as a measured zero", () => {
    const [dim] = fitDimensions({ "Role alignment": 0 }, 1);
    expect(dim.measured).toBe(true);
    expect(dim).toMatchObject({ score: 0 });
  });
});

