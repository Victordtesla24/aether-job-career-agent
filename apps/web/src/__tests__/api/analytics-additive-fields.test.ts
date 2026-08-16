/**
 * TRACK D / D3+D4 (audit wf_9a87f76f-eaa, Architect decision CLI-D3) — the
 * ADDITIVE analytics fields Track C landed on the API:
 *
 *   - GET /analytics/funnel now also returns `transmitted` — DISTINCT jobs
 *     with a VERIFIED send (`Application.transmittedAt IS NOT NULL`, stamped
 *     only by the real send path). `applied` keeps its exact prior meaning
 *     (applications that left draft — preparation, not proof of sending).
 *   - GET /analytics/conversion now also returns `transmitted` and
 *     `verified_interview_conversion_rate` (interviews over TRANSMITTED —
 *     the rate a user can trust as "of what actually went out").
 *
 * The FE zod schemas must DECLARE these fields (z.object strips undeclared
 * keys — the exact silent-loss defect G-C already documented on this file's
 * neighbours) and must declare them OPTIONAL, so the frontend tolerates an
 * older API build during a rolling deploy: absence parses fine and simply
 * withholds the "sent (verified)" surfaces.
 */
import { describe, expect, it } from "vitest";

import { ConversionSchema, FunnelSchema } from "../../lib/api/analytics";

const FUNNEL_BASE = {
  period: "all",
  jobs_found: 847,
  applied: 412,
  screened: 133,
  interviewed: 19,
  offers: 4,
};

const CONVERSION_BASE = {
  period: "all",
  found_to_applied: 48.6,
  applied_to_screened: 32.3,
  screened_to_interview: 14.3,
  interview_to_offer: 21.1,
  interview_conversion_rate: 4.61,
  interview_conversion_healthy: false,
};

describe("FunnelSchema — additive `transmitted` (CLI-D3)", () => {
  it("declares and keeps `transmitted` when the API sends it (never silently stripped)", () => {
    const parsed = FunnelSchema.parse({ ...FUNNEL_BASE, transmitted: 21 });
    expect(parsed.transmitted).toBe(21);
  });

  it("tolerates an OLDER API that does not send it (rolling-deploy safety)", () => {
    const parsed = FunnelSchema.parse(FUNNEL_BASE);
    expect(parsed.transmitted).toBeUndefined();
    // Pre-existing fields keep their exact prior contract.
    expect(parsed.applied).toBe(412);
  });

  it("still rejects a malformed value — optional never means unvalidated", () => {
    expect(() => FunnelSchema.parse({ ...FUNNEL_BASE, transmitted: "lots" })).toThrow();
  });
});

describe("ConversionSchema — additive `transmitted` + `verified_interview_conversion_rate` (CLI-D3)", () => {
  it("declares and keeps both fields when the API sends them", () => {
    const parsed = ConversionSchema.parse({
      ...CONVERSION_BASE,
      transmitted: 21,
      verified_interview_conversion_rate: 90.48,
    });
    expect(parsed.transmitted).toBe(21);
    expect(parsed.verified_interview_conversion_rate).toBe(90.48);
  });

  it("tolerates an OLDER API that sends neither (rolling-deploy safety)", () => {
    const parsed = ConversionSchema.parse(CONVERSION_BASE);
    expect(parsed.transmitted).toBeUndefined();
    expect(parsed.verified_interview_conversion_rate).toBeUndefined();
    // The legacy rate keeps its exact prior meaning (denominator = prepared).
    expect(parsed.interview_conversion_rate).toBe(4.61);
  });

  it("still rejects malformed values — optional never means unvalidated", () => {
    expect(() =>
      ConversionSchema.parse({ ...CONVERSION_BASE, verified_interview_conversion_rate: "high" }),
    ).toThrow();
  });
});
