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

/**
 * R-01 (round 3) — the HEADLINE was the last consumer still rendering a
 * placeholder-contaminated ATS as a bold measurement while the row beneath it
 * honestly showed "—". `ATSScore.overall` is 0.4*keyword + 0.4*semantic +
 * 0.2*experience, i.e. 40% neutral placeholder whenever the semantic path is
 * untrusted; the same value is emitted as the "Role Alignment" dimension,
 * which already renders "—". The wire now WITHHOLDS a non-measured half
 * (`ats: null`, `atsMeasured: false` — see
 * `GET /resumes/{id}/tailoring-impact`), so the untrustworthy arm carries no
 * number for this component to leak.
 */
describe("TailoringImpact — a non-measured ATS half is never a bold number", () => {
  const before = dims([60, 55, 50, 62, 58, 70, 80, 45, 76, 61]);
  const after = dims([72, 60, 55, 70, 61, 74, 82, 50, 78, 68]);

  it("renders '—' for a withheld before-ATS and no fabricated delta", () => {
    render(
      <TailoringImpact
        beforeAts={null}
        afterAts={69}
        beforeDimensions={before}
        afterDimensions={after}
      />,
    );
    expect(screen.getByTestId("ats-before").textContent).toBe("—");
    expect(screen.getByTestId("ats-after").textContent).toBe("69");
    expect(screen.getByTestId("ats-delta").textContent).toBe("n/a");
  });

  it("renders '—' for a withheld after-ATS and no fabricated delta", () => {
    render(
      <TailoringImpact
        beforeAts={58}
        afterAts={null}
        beforeDimensions={before}
        afterDimensions={after}
      />,
    );
    expect(screen.getByTestId("ats-after").textContent).toBe("—");
    expect(screen.getByTestId("ats-delta").textContent).toBe("n/a");
  });

  it("states WHY the number is absent rather than leaving a bare dash", () => {
    render(
      <TailoringImpact
        beforeAts={null}
        afterAts={null}
        beforeDimensions={before}
        afterDimensions={after}
        atsUnmeasuredReason="The semantic scoring model was unavailable for this run."
      />,
    );
    const caveat = screen.getByTestId("ats-unmeasured-caveat");
    expect(caveat.textContent).toMatch(/semantic scoring model was unavailable/i);
    expect(caveat.textContent?.toLowerCase()).toMatch(/not measured/);
  });

  it("shows no caveat when both halves are genuine measurements", () => {
    render(
      <TailoringImpact
        beforeAts={58}
        afterAts={69}
        beforeDimensions={before}
        afterDimensions={after}
      />,
    );
    expect(screen.queryByTestId("ats-unmeasured-caveat")).toBeNull();
    expect(screen.getByTestId("ats-delta").textContent).toBe("+11 ATS");
  });
});
