// @vitest-environment jsdom
/**
 * `<Heatmap>` — the market demand grid.
 *
 * The dangerous failure here is the quiet one: rendering "we have no data for
 * Sunday 3am" as the LIGHTEST step of the heat ramp, which reads as "almost no
 * demand". C-2 forbids it — an unmeasured cell gets its own surface plus a
 * hatch, and says "no data" on hover.
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Heatmap } from "../Heatmap";
import { CHART_HEAT, SURFACE } from "../tokens";
import { clearMatchMedia, marks, renderChart, stubMatchMedia } from "./testUtils";

const ROWS = [
  { label: "Mon", cells: [{ label: "09:00", value: 12 }, { label: "13:00", value: 4 }] },
  { label: "Tue", cells: [{ label: "09:00", value: 0 }, { label: "13:00", value: 20 }] },
];

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("the grid", () => {
  it("renders one cell per row × column, each with its row and column words", () => {
    const root = renderChart(
      <Heatmap title="Demand" windowLabel="last 14 days" rows={ROWS} unit="postings" />,
    );
    expect(root.querySelectorAll("[data-cell]")).toHaveLength(4);
    expect(root.querySelector('[data-cell="Mon/09:00"]')?.getAttribute("title")).toBe(
      "Mon 09:00 — 12 postings",
    );
  });

  it("maps values onto the declared 5-step coral ramp", () => {
    const root = renderChart(
      <Heatmap title="Demand" windowLabel="last 14 days" rows={ROWS} unit="postings" />,
    );
    expect(CHART_HEAT).toHaveLength(5);
    const hottest = root.querySelector('[data-cell="Tue/13:00"]') as HTMLElement;
    expect(hottest.dataset.heatStep).toBe("5");
    expect(hottest.style.backgroundColor).toBe("rgba(255, 107, 53, 0.85)");
  });

  it("labels every heat step with the value range it stands for (C-5)", () => {
    const root = renderChart(
      <Heatmap title="Demand" windowLabel="last 14 days" rows={ROWS} unit="postings" />,
    );
    const steps = root.querySelectorAll('[data-testid="heat-step"]');
    expect(steps).toHaveLength(5);
    expect(root.querySelector('[data-testid="heat-legend"]')?.textContent).toContain("20");
    expect(root.querySelector('[data-testid="heat-legend"]')?.textContent).toContain("0");
  });
});

describe("C-1 / C-2 — an empty cell versus an unknown cell", () => {
  const rows = [
    { label: "Mon", cells: [{ label: "09:00", value: 0 }, { label: "13:00", value: 9 }] },
    {
      label: "Tue",
      cells: [
        { label: "09:00", value: null, note: "collector had not started" },
        { label: "13:00", value: 9 },
      ],
    },
  ];

  it("gives a measured zero the coldest step, and marks it as a zero", () => {
    const root = renderChart(
      <Heatmap
        title="Demand"
        windowLabel="last 14 days"
        rows={rows}
        unit="postings"
        nullMeaning="collector had not started"
      />,
    );
    const zeroCell = root.querySelector('[data-cell="Mon/09:00"]') as HTMLElement;
    expect(zeroCell.dataset.mark).toBe("zero");
    expect(zeroCell.dataset.heatStep).toBe("0");
    expect(zeroCell.getAttribute("title")).toContain("0 postings");
  });

  it("never gives an unmeasured cell a heat step — it gets its own surface and a hatch", () => {
    const root = renderChart(
      <Heatmap
        title="Demand"
        windowLabel="last 14 days"
        rows={rows}
        unit="postings"
        nullMeaning="collector had not started"
      />,
    );
    const cell = root.querySelector('[data-cell="Tue/09:00"]') as HTMLElement;
    expect(cell.dataset.mark).toBe("unmeasured");
    expect(cell.dataset.heatStep).toBeUndefined();
    expect(cell.style.backgroundColor).toBe("rgb(16, 16, 24)");
    expect(SURFACE.s1).toBe("#101018");
    expect(cell.style.backgroundImage).toContain("repeating-linear-gradient");
    expect(cell.getAttribute("title")).toContain("no data");
    expect(cell.getAttribute("title")).toContain("collector had not started");
  });

  it("keeps unmeasured cells out of the ramp maximum", () => {
    const root = renderChart(
      <Heatmap
        title="Demand"
        windowLabel="last 14 days"
        rows={rows}
        unit="postings"
        nullMeaning="collector had not started"
      />,
    );
    expect(marks(root, "unmeasured")).toHaveLength(1);
    expect(root.querySelector('[data-testid="heat-legend"]')?.textContent).toContain("9");
  });
});

describe("bounds", () => {
  it("caps the staggered rows so a tall grid cannot animate forever", () => {
    const many = Array.from({ length: 14 }, (_, r) => ({
      label: `Row ${r}`,
      cells: [{ label: "09:00", value: r }],
    }));
    const root = renderChart(
      <Heatmap title="Demand" windowLabel="last 14 days" rows={many} unit="postings" />,
    );
    const delays = Array.from(root.querySelectorAll("[data-row-index]")).map((row) =>
      Number((row as HTMLElement).style.transitionDelay.replace("ms", "")),
    );
    expect(Math.max(...delays)).toBeLessThanOrEqual(8 * 40);
  });

  it("draws a designed empty state for an empty grid", () => {
    const root = renderChart(
      <Heatmap title="Demand" windowLabel="last 14 days" rows={[]} unit="postings" />,
    );
    expect(root.querySelector('[data-testid="chart-empty"]')).not.toBeNull();
  });
});

describe("motion", () => {
  it("applies no per-row delay or transition under reduced motion", () => {
    cleanup();
    stubMatchMedia(true);
    const root = renderChart(
      <Heatmap title="Demand" windowLabel="last 14 days" rows={ROWS} unit="postings" />,
    );
    const row = root.querySelector("[data-row-index]") as HTMLElement;
    expect(row.style.transition).toBe("");
    expect(row.style.transitionProperty).toBe("");
    expect(row.style.transitionDuration).toBe("");
    expect(row.style.transitionDelay).toBe("");
    expect(row.style.opacity).toBe("");
  });
});
