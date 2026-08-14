/**
 * F-UAX-03 — parity test for `deriveTailoredDimensions` (`resume/page.tsx`).
 *
 * The re-fix finding: this function re-implements the SAME server-side
 * blends `apps/api/app/routers/jobs.py::_build_insights` owns (Culture Fit
 * 0.5*sem+0.5*exp, North Star 0.6*overall+0.4*sem, Career Growth
 * 0.6*seniority+0.4*overall) with ZERO test coverage, used
 * `baselineScore.get(label) ?? 0` (manufacturing a false catastrophic delta
 * if a label ever went missing), and rounded to 1 decimal with no [0,100]
 * clamp (mixing "76" with "78.4", letting Career Growth exceed 100) instead
 * of matching the backend's integer, clamped `_round`.
 *
 * This test calls the EXACT function the page renders from (exported for
 * this purpose) and pins it against the backend's own formulas.
 */
import { describe, expect, it } from "vitest";

import { deriveTailoredDimensions, type JobInsightsDimension } from "../page";

const BASELINE: JobInsightsDimension[] = [
  { label: "Technical Skills", score: 60, degraded: false },
  { label: "Experience Level", score: 55, degraded: false },
  { label: "Industry Match", score: 50, degraded: false },
  { label: "Role Alignment", score: 62, degraded: false },
  { label: "Culture Fit", score: 58, degraded: false },
  { label: "Salary Fit", score: 70, degraded: false },
  { label: "Location Match", score: 80, degraded: false },
  { label: "Career Growth", score: 45, degraded: false },
  { label: "Company Stability", score: 76, degraded: false },
  { label: "North Star Align", score: 61, degraded: false },
];
const BASELINE_OVERALL = 62;

const TAILORED = {
  overall: 74,
  keyword_match: 80,
  semantic_similarity: 68,
  experience_gap: 66,
  semantic_path: "local",
};

function dim(result: ReturnType<typeof deriveTailoredDimensions>, label: string) {
  const found = result.find((d) => d.label === label);
  if (!found) throw new Error(`missing dimension ${label}`);
  return found;
}

describe("deriveTailoredDimensions — parity with jobs.py::_build_insights", () => {
  it("Technical Skills / Experience Level pass the raw ATS subscores through, never degraded", () => {
    const result = deriveTailoredDimensions(BASELINE, BASELINE_OVERALL, TAILORED);
    expect(dim(result, "Technical Skills")).toEqual({ label: "Technical Skills", score: 80, degraded: false });
    expect(dim(result, "Experience Level")).toEqual({ label: "Experience Level", score: 66, degraded: false });
  });

  it("Culture Fit matches the backend blend exactly: round(0.5*sem + 0.5*exp)", () => {
    const result = deriveTailoredDimensions(BASELINE, BASELINE_OVERALL, TAILORED);
    // 0.5*68 + 0.5*66 = 67
    expect(dim(result, "Culture Fit").score).toBe(67);
  });

  it("North Star Align matches the backend blend exactly: round(0.6*overall + 0.4*sem)", () => {
    const result = deriveTailoredDimensions(BASELINE, BASELINE_OVERALL, TAILORED);
    // 0.6*74 + 0.4*68 = 44.4 + 27.2 = 71.6 -> round 72
    expect(dim(result, "North Star Align").score).toBe(72);
  });

  it("Career Growth blends the baseline seniority term with 0.4x the overall movement", () => {
    const result = deriveTailoredDimensions(BASELINE, BASELINE_OVERALL, TAILORED);
    // baseline 45 + 0.4*(74-62) = 45 + 4.8 = 49.8 -> round 50
    expect(dim(result, "Career Growth").score).toBe(50);
  });

  it("Salary Fit / Location Match / Company Stability are job-only — unchanged by tailoring", () => {
    const result = deriveTailoredDimensions(BASELINE, BASELINE_OVERALL, TAILORED);
    expect(dim(result, "Salary Fit").score).toBe(70);
    expect(dim(result, "Location Match").score).toBe(80);
    expect(dim(result, "Company Stability").score).toBe(76);
  });

  it("clamps to [0,100] and rounds to an INTEGER, matching the backend's granularity — never a mix of int/decimal", () => {
    const nearCeiling: JobInsightsDimension[] = BASELINE.map((d) =>
      d.label === "Career Growth" ? { ...d, score: 99 } : d,
    );
    const result = deriveTailoredDimensions(nearCeiling, 10, { ...TAILORED, overall: 100 });
    // 99 + 0.4*(100-10) = 99 + 36 = 135 -> clamped to 100, never > 100.
    expect(dim(result, "Career Growth").score).toBe(100);
    for (const d of result) {
      expect(Number.isInteger(d.score)).toBe(true);
      expect(d.score).toBeGreaterThanOrEqual(0);
      expect(d.score).toBeLessThanOrEqual(100);
    }
  });

  it("flags the 5 semantic-dependent dimensions degraded when semantic_path is untrusted (whitelist, fail-closed)", () => {
    const degraded = deriveTailoredDimensions(BASELINE, BASELINE_OVERALL, {
      ...TAILORED,
      semantic_path: "degraded",
    });
    for (const label of ["Industry Match", "Role Alignment", "Culture Fit", "North Star Align", "Career Growth"]) {
      expect(dim(degraded, label).degraded).toBe(true);
    }
    // Job-only dimensions are never degraded by a resume-side placeholder.
    expect(dim(degraded, "Salary Fit").degraded).toBe(false);
    expect(dim(degraded, "Location Match").degraded).toBe(false);
    expect(dim(degraded, "Company Stability").degraded).toBe(false);
    // A missing semantic_path fails CLOSED (untrusted), never open.
    const missing = deriveTailoredDimensions(BASELINE, BASELINE_OVERALL, {
      ...TAILORED,
      semantic_path: undefined,
    });
    expect(dim(missing, "Culture Fit").degraded).toBe(true);
  });

  it("never fabricates a 0 for a dimension the baseline doesn't carry — drops it instead", () => {
    const missingCultureFit = BASELINE.filter((d) => d.label !== "Culture Fit");
    const result = deriveTailoredDimensions(missingCultureFit, BASELINE_OVERALL, TAILORED);
    expect(result.find((d) => d.label === "Culture Fit")).toBeUndefined();
    expect(result).toHaveLength(9);
  });
});
