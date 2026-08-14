// @vitest-environment jsdom
/**
 * U-AX build spec item 3 — BEFORE/AFTER HONESTY (Resume Studio + analytics).
 *
 * U-PLAN.md U-AX BUILD SPEC ADDITIONS item 3: "every tailored version shows
 * before->after ATS score AND before->after 10-dimensional scores (all 10
 * dimensions, baseline vs tailored, with the >80% threshold line marked);
 * deltas honest (including negative/no-change)."
 *
 * The 10 dimensions are the EXISTING fit-radar set (jobs.py:424-435 /
 * `dashboard/jobs/page.tsx` `Dimension[]`) — this component compares that
 * same set computed against the baseline resume vs the tailored one, not a
 * new taxonomy.
 *
 * Component does not exist on `main` yet —
 * `../TailoringImpact` (test-author-chosen path, sibling of `MarketPulse.tsx`).
 * Written BEFORE implementation.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import TailoringImpact from "../TailoringImpact";

afterEach(cleanup);

interface Dimension {
  label: string;
  score: number;
  degraded?: boolean;
}

const TEN_DIMENSION_LABELS = [
  "Technical Skills", "Experience Level", "Industry Match", "Role Alignment",
  "Culture Fit", "Salary Fit", "Location Match", "Career Growth",
  "Company Stability", "North Star Align",
];

function dims(scores: number[]): Dimension[] {
  return TEN_DIMENSION_LABELS.map((label, i) => ({ label, score: scores[i] }));
}

describe("TailoringImpact — honest before/after ATS + 10-dimension display", () => {
  it("renders the before and after ATS scores", () => {
    render(
      <TailoringImpact
        beforeAts={57.3}
        afterAts={69.5}
        beforeDimensions={dims([60, 55, 50, 62, 58, 70, 80, 45, 76, 61])}
        afterDimensions={dims([72, 60, 55, 70, 61, 74, 82, 50, 78, 68])}
      />,
    );
    const el = screen.getByTestId("tailoring-impact");
    expect(el.textContent).toMatch(/57\.3/);
    expect(el.textContent).toMatch(/69\.5/);
  });

  it("renders all 10 dimensions, baseline vs tailored", () => {
    render(
      <TailoringImpact
        beforeAts={57.3}
        afterAts={69.5}
        beforeDimensions={dims([60, 55, 50, 62, 58, 70, 80, 45, 76, 61])}
        afterDimensions={dims([72, 60, 55, 70, 61, 74, 82, 50, 78, 68])}
      />,
    );
    const rows = screen.getAllByTestId("dimension-row");
    expect(rows).toHaveLength(10);
    for (const label of TEN_DIMENSION_LABELS) {
      expect(screen.getByText(new RegExp(label, "i"))).toBeTruthy();
    }
  });

  it("marks the >80% threshold line", () => {
    render(
      <TailoringImpact
        beforeAts={57.3}
        afterAts={69.5}
        beforeDimensions={dims([60, 55, 50, 62, 58, 70, 80, 45, 76, 61])}
        afterDimensions={dims([72, 60, 55, 70, 61, 74, 82, 50, 78, 68])}
      />,
    );
    expect(screen.getByTestId("dimension-threshold-line")).toBeTruthy();
  });

  it("shows an honest NEGATIVE delta when a dimension regressed — never clamps or hides it", () => {
    render(
      <TailoringImpact
        beforeAts={70}
        afterAts={68} // overall ATS also regressed slightly — must be shown, not hidden
        beforeDimensions={dims([60, 55, 50, 62, 58, 70, 80, 90, 76, 61])}
        afterDimensions={dims([72, 60, 55, 70, 61, 74, 82, 81, 78, 68])} // Career Growth 90 -> 81
      />,
    );
    const row = screen
      .getAllByTestId("dimension-row")
      .find((r) => /career growth/i.test(r.textContent ?? ""));
    expect(row).toBeTruthy();
    expect(row!.textContent).toMatch(/-9|−9/); // negative delta rendered, not suppressed
  });

  // F-UAX-02: a degraded dimension is a placeholder, not a measurement — it
  // must render as "—", never as a number that could satisfy or trip the
  // >80% floor.
  it("renders a degraded dimension as '—' with no fabricated delta, not a number", () => {
    const before = dims([60, 55, 50, 62, 58, 70, 80, 45, 76, 61]).map((d) =>
      d.label === "Culture Fit" ? { ...d, degraded: true } : d,
    );
    const after = dims([72, 60, 55, 70, 61, 74, 82, 50, 78, 68]).map((d) =>
      d.label === "Culture Fit" ? { ...d, degraded: true } : d,
    );
    render(
      <TailoringImpact beforeAts={57.3} afterAts={69.5} beforeDimensions={before} afterDimensions={after} />,
    );
    const row = screen
      .getAllByTestId("dimension-row")
      .find((r) => /culture fit/i.test(r.textContent ?? ""));
    expect(row).toBeTruthy();
    expect(row!.querySelector('[data-testid="dimension-before"]')!.textContent).toBe("—");
    expect(row!.querySelector('[data-testid="dimension-after"]')!.textContent).toBe("—");
    expect(row!.querySelector('[data-testid="dimension-delta"]')!.textContent).toBe("n/a");
    expect(row!.textContent).not.toMatch(/\b58\b|\b61\b/); // the real numbers never leak through
  });

  // F-UAX-05: pairing must be by LABEL, never by array index — a genuinely
  // missing counterpart (arrays out of sync) must read as "not available",
  // never a fabricated "±0, no change".
  it("shows 'n/a' instead of a fabricated ±0 delta when a dimension has no after counterpart", () => {
    const before = dims([60, 55, 50, 62, 58, 70, 80, 45, 76, 61]);
    const after = dims([72, 60, 55, 70, 61, 74, 82, 50, 78, 68]).filter(
      (d) => d.label !== "Culture Fit",
    );
    render(
      <TailoringImpact beforeAts={57.3} afterAts={69.5} beforeDimensions={before} afterDimensions={after} />,
    );
    const row = screen
      .getAllByTestId("dimension-row")
      .find((r) => /culture fit/i.test(r.textContent ?? ""));
    expect(row).toBeTruthy();
    expect(row!.querySelector('[data-testid="dimension-delta"]')!.textContent).toBe("n/a");
    expect(row!.textContent).not.toMatch(/±0/);
  });

  // F-UAX-05: reordering `afterDimensions` must not scramble the pairing —
  // an index-based fallback would silently mismatch here.
  it("pairs correctly by label even when afterDimensions is reordered", () => {
    const before = dims([60, 55, 50, 62, 58, 70, 80, 45, 76, 61]);
    const after = [...dims([72, 60, 55, 70, 61, 74, 82, 50, 78, 68])].reverse();
    render(
      <TailoringImpact beforeAts={57.3} afterAts={69.5} beforeDimensions={before} afterDimensions={after} />,
    );
    const row = screen
      .getAllByTestId("dimension-row")
      .find((r) => /^technical skills/i.test(r.textContent ?? ""));
    expect(row).toBeTruthy();
    // Technical Skills: before=60, after=72 (from the un-reversed source) — a
    // correct label pairing finds 72 regardless of array order.
    expect(row!.querySelector('[data-testid="dimension-after"]')!.textContent).toBe("72");
  });
});
