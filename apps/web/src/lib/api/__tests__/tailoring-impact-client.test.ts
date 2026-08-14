/**
 * U-AX round-3 — R-01/R-03: the ONE before/after authority, client side.
 *
 * `GET /resumes/{id}/tailoring-impact` returns both halves of the pair already
 * blended and rounded by the SAME server-side code (`routers/jobs.py::
 * build_fit_dimensions` + `_round`), which is what removes the mixed
 * granularity (integer "before" vs 1-dp "after") and the duplicated
 * client-side blend that produced the fabricated deltas.
 *
 * This client's job is therefore narrow and strict: fail CLOSED. A half that
 * does not explicitly attest `atsMeasured: true` alongside a real number
 * yields `ats: null`, so no downstream component can render a
 * placeholder-contaminated score as a measurement — the same discipline as
 * `lib/scoring/provenance.ts`.
 */
import { describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import { fetchTailoringImpact } from "../resumes";

const DIMS = [
  { label: "Technical Skills", score: 61, degraded: false },
  { label: "Culture Fit", score: 0, degraded: true },
];

function payload(overrides: Record<string, unknown> = {}) {
  return {
    resumeId: "r1",
    jobId: "j1",
    jobTitle: "Delivery Lead",
    company: "ExampleCorp",
    before: { ats: 58, atsMeasured: true, dimensions: DIMS },
    after: { ats: 61, atsMeasured: true, dimensions: DIMS },
    ...overrides,
  };
}

describe("fetchTailoringImpact — fail-closed provenance", () => {
  it("passes through a fully attested pair", async () => {
    apiRequest.mockResolvedValueOnce(payload());
    const impact = await fetchTailoringImpact("r1");
    expect(apiRequest).toHaveBeenCalledWith("/resumes/r1/tailoring-impact", {});
    expect(impact.before.ats).toBe(58);
    expect(impact.after.ats).toBe(61);
    expect(impact.after.dimensions[1].degraded).toBe(true);
  });

  it("withholds an ATS number whose half is not attested measured", async () => {
    apiRequest.mockResolvedValueOnce(
      payload({ before: { ats: 58, atsMeasured: false, dimensions: DIMS } }),
    );
    const impact = await fetchTailoringImpact("r1");
    expect(impact.before.ats).toBeNull();
    expect(impact.after.ats).toBe(61);
  });

  it("withholds an ATS number when the attestation is missing entirely", async () => {
    apiRequest.mockResolvedValueOnce(
      payload({ after: { ats: 61, dimensions: DIMS } }),
    );
    const impact = await fetchTailoringImpact("r1");
    expect(impact.after.ats).toBeNull();
  });

  it("treats a dimension with no explicit degraded flag as not measured", async () => {
    apiRequest.mockResolvedValueOnce(
      payload({
        after: {
          ats: 61,
          atsMeasured: true,
          dimensions: [{ label: "Role Alignment", score: 77 }],
        },
      }),
    );
    const impact = await fetchTailoringImpact("r1");
    expect(impact.after.dimensions[0].degraded).toBe(true);
  });
});
