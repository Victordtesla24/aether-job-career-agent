// @vitest-environment jsdom
/**
 * `<Radar10>` (spec alias `<RadarPlot>`) — the 10-dimension job-fit profile.
 *
 * S-UI-REBUILD-SPEC §4.3 calls this "the single most dangerous chart in the
 * product": collapsing an UNMEASURED dimension to the centre draws a specific
 * false claim about a candidate ("scored 0 on leadership"). Every test in the
 * first block exists to make that impossible.
 *
 * The prop shape is structurally identical to `lib/scoring/provenance.ts`
 * `FitDimension`, whose fail-closed parser already decides `measured` — the
 * chart never re-derives it.
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Radar10, type RadarDimension } from "../Radar10";
import { STATE } from "../tokens";
import { clearMatchMedia, renderChart, stubMatchMedia } from "./testUtils";

const TEN: RadarDimension[] = [
  { label: "Skills", measured: true, score: 82 },
  { label: "Seniority", measured: true, score: 71 },
  { label: "Domain", measured: true, score: 64 },
  { label: "Location", measured: true, score: 90 },
  { label: "Salary", measured: true, score: 55 },
  { label: "Culture", measured: true, score: 48 },
  { label: "Growth", measured: true, score: 77 },
  { label: "Stability", measured: true, score: 61 },
  { label: "Leadership", measured: true, score: 43 },
  { label: "Tooling", measured: true, score: 88 },
];

function withUnmeasured(...indexes: number[]): RadarDimension[] {
  return TEN.map((dim, i) =>
    indexes.includes(i)
      ? { label: dim.label, measured: false, reason: "no evidence in the posting" }
      : dim,
  );
}

/** Centre + radius are read off the outer ring, so the tests never re-derive
 *  the component's own geometry from its own constants. */
function outerRing(root: HTMLElement): { cx: number; cy: number; r: number } {
  const ring = root.querySelector('[data-testid="radar-ring-outer"]');
  return {
    cx: Number(ring?.getAttribute("cx")),
    cy: Number(ring?.getAttribute("cy")),
    r: Number(ring?.getAttribute("r")),
  };
}

function distanceFromCentre(root: HTMLElement, el: Element): number {
  const { cx, cy } = outerRing(root);
  const dx = Number(el.getAttribute("cx")) - cx;
  const dy = Number(el.getAttribute("cy")) - cy;
  return Math.sqrt(dx * dx + dy * dy);
}

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("an unmeasured dimension is never a zero", () => {
  it("puts no polygon vertex on the unmeasured spoke", () => {
    const root = renderChart(
      <Radar10 title="Fit profile" windowLabel="this job" dimensions={withUnmeasured(8)} />,
    );
    const vertices = root.querySelectorAll("[data-spoke-vertex]");
    const spokes = Array.from(vertices).map((v) => v.getAttribute("data-spoke-vertex"));
    expect(spokes).not.toContain("8");
    expect(spokes).toHaveLength(9);
  });

  it("never places any mark for that dimension at the centre", () => {
    const root = renderChart(
      <Radar10 title="Fit profile" windowLabel="this job" dimensions={withUnmeasured(8)} />,
    );
    const marker = root.querySelector('[data-unmeasured-spoke="8"]');
    expect(marker).not.toBeNull();
    expect(distanceFromCentre(root, marker as Element)).toBeGreaterThan(1);
  });

  it("draws it as a hollow state-neutral marker at the outer ring", () => {
    const root = renderChart(
      <Radar10 title="Fit profile" windowLabel="this job" dimensions={withUnmeasured(8)} />,
    );
    const marker = root.querySelector('[data-unmeasured-spoke="8"]') as Element;
    expect(marker.getAttribute("fill")).toBe("none");
    expect(marker.getAttribute("stroke")).toBe(STATE.neutral);
    expect(distanceFromCentre(root, marker)).toBeCloseTo(outerRing(root).r, 5);
  });

  it("strikes the axis label so colour is not the only signal (C-5)", () => {
    const root = renderChart(
      <Radar10 title="Fit profile" windowLabel="this job" dimensions={withUnmeasured(8)} />,
    );
    const label = root.querySelector('[data-axis-label="8"]');
    expect(label?.textContent).toContain("Leadership");
    expect(label?.getAttribute("text-decoration")).toBe("line-through");
    expect(label?.getAttribute("fill")).toBe(STATE.neutral);
  });

  it("dashes the polygon edge that bridges the missing spoke", () => {
    const root = renderChart(
      <Radar10 title="Fit profile" windowLabel="this job" dimensions={withUnmeasured(8)} />,
    );
    const bridged = root.querySelectorAll('[data-bridged="true"]');
    expect(bridged.length).toBeGreaterThan(0);
    expect(bridged[0]?.getAttribute("stroke-dasharray")).toBeTruthy();
  });

  it("states the count of unmeasured dimensions in the legend", () => {
    const root = renderChart(
      <Radar10 title="Fit profile" windowLabel="this job" dimensions={withUnmeasured(4, 8)} />,
    );
    expect(root.querySelector('[data-testid="radar-unmeasured-note"]')?.textContent).toContain(
      "2 dimensions not measured",
    );
  });

  it("carries each dimension's reason into the data table", () => {
    const root = renderChart(
      <Radar10 title="Fit profile" windowLabel="this job" dimensions={withUnmeasured(8)} />,
    );
    const table = root.querySelector('[data-testid="chart-data-table"]');
    expect(table?.textContent).toContain("Leadership");
    expect(table?.textContent).toContain("not measured");
    expect(table?.textContent).toContain("no evidence in the posting");
  });

  it("ignores a score that arrives on a dimension flagged unmeasured (fail closed)", () => {
    // The unmeasured arm of RadarDimension tolerates a stray `score` on the
    // wire precisely so the chart can prove it ignores it.
    const sneaky: RadarDimension[] = TEN.map((dim, i) =>
      i === 8 ? { label: dim.label, measured: false, score: 0 } : dim,
    );
    const root = renderChart(
      <Radar10 title="Fit profile" windowLabel="this job" dimensions={sneaky} />,
    );
    const spokes = Array.from(root.querySelectorAll("[data-spoke-vertex]")).map((v) =>
      v.getAttribute("data-spoke-vertex"),
    );
    expect(spokes).not.toContain("8");
  });
});

describe("the ten dimensions", () => {
  it("draws ten spokes and ten labels for a complete profile", () => {
    const root = renderChart(<Radar10 title="Fit profile" windowLabel="this job" dimensions={TEN} />);
    expect(root.querySelectorAll("[data-spoke]")).toHaveLength(10);
    expect(root.querySelectorAll("[data-axis-label]")).toHaveLength(10);
    expect(root.querySelector('[data-testid="radar-unmeasured-note"]')).toBeNull();
  });

  it("draws four labelled concentric rings so a radius can be read as a number", () => {
    const root = renderChart(<Radar10 title="Fit profile" windowLabel="this job" dimensions={TEN} />);
    expect(root.querySelectorAll("[data-ring]")).toHaveLength(4);
    const ringLabels = Array.from(root.querySelectorAll('[data-testid="ring-label"]')).map(
      (n) => n.textContent,
    );
    expect(ringLabels).toEqual(["25", "50", "75", "100"]);
  });

  it("scales a measured score to its share of the outer ring", () => {
    const root = renderChart(<Radar10 title="Fit profile" windowLabel="this job" dimensions={TEN} />);
    const ring = outerRing(root).r;
    const location = root.querySelector('[data-spoke-vertex="3"]') as Element; // 90
    const culture = root.querySelector('[data-spoke-vertex="5"]') as Element; // 48
    expect(distanceFromCentre(root, location)).toBeCloseTo(ring * 0.9, 1);
    expect(distanceFromCentre(root, culture)).toBeCloseTo(ring * 0.48, 1);
  });

  it("says so when fewer than ten dimensions came back, instead of padding the shape", () => {
    const root = renderChart(
      <Radar10 title="Fit profile" windowLabel="this job" dimensions={TEN.slice(0, 6)} />,
    );
    expect(root.querySelectorAll("[data-spoke]")).toHaveLength(6);
    expect(root.querySelector('[data-testid="radar-shortfall"]')?.textContent).toContain(
      "6 of 10",
    );
  });

  it("refuses to draw a polygon from fewer than three measured dimensions", () => {
    const root = renderChart(
      <Radar10
        title="Fit profile"
        windowLabel="this job"
        dimensions={withUnmeasured(0, 1, 2, 3, 4, 5, 6, 7)}
      />,
    );
    expect(root.querySelector('[data-testid="radar-polygon"]')).toBeNull();
    expect(root.querySelectorAll("[data-unmeasured-spoke]")).toHaveLength(8);
  });

  it("draws a designed empty state for an empty dimension list", () => {
    const root = renderChart(
      <Radar10 title="Fit profile" windowLabel="this job" dimensions={[]} />,
    );
    expect(root.querySelector('[data-testid="chart-empty"]')).not.toBeNull();
  });
});

describe("motion", () => {
  it("skips the reveal transform under reduced motion", () => {
    cleanup();
    stubMatchMedia(true);
    const root = renderChart(<Radar10 title="Fit profile" windowLabel="this job" dimensions={TEN} />);
    const polygon = root.querySelector('[data-testid="radar-polygon"]') as unknown as HTMLElement;
    expect(root.getAttribute("data-motion")).toBe("off");
    expect(polygon.style.transition).toBe("");
    expect(polygon.style.transform).toBe("");
  });
});
