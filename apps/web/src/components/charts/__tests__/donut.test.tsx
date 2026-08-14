// @vitest-environment jsdom
/**
 * `<Donut>` — the source-mix chart.
 *
 * Rules pinned: absolute counts always accompany percentages (a share with no
 * denominator is not a fact), slivers below 2% group into a named "Other"
 * whose members stay individually listed, a zero segment is not a colour
 * (C-1), and an unmeasured source is not a zero (C-2).
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Donut } from "../Donut";
import { clearMatchMedia, marks, renderChart, stubMatchMedia } from "./testUtils";

const SEGMENTS = [
  { label: "Adzuna", value: 520 },
  { label: "SmartRecruiters", value: 260 },
  { label: "Greenhouse", value: 200 },
  { label: "Lever", value: 12 },
  { label: "Workable", value: 8 },
];

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("arcs", () => {
  it("draws one arc per rendered segment, using dash geometry on a single circle radius", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="1,000 jobs found" segments={SEGMENTS} />,
    );
    const arcs = root.querySelectorAll("[data-arc]");
    // 3 real segments + the grouped "Other"
    expect(arcs).toHaveLength(4);
    arcs.forEach((arc) => {
      expect(arc.getAttribute("stroke-dasharray")).toBeTruthy();
      expect(arc.getAttribute("fill")).toBe("none");
    });
  });

  it("holds the total and its label in the centre", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="1,000 jobs found" segments={SEGMENTS} centreLabel="jobs" />,
    );
    const centre = root.querySelector('[data-testid="donut-centre"]');
    expect(centre?.textContent).toContain("1,000");
    expect(centre?.textContent).toContain("jobs");
  });

  it("groups sub-2% slivers into Other and names its members", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="1,000 jobs found" segments={SEGMENTS} />,
    );
    const other = root.querySelector('[data-segment="Other"]');
    expect(other).not.toBeNull();
    expect(other?.textContent).toContain("Other");
    expect(other?.getAttribute("title")).toContain("Lever");
    expect(other?.getAttribute("title")).toContain("Workable");
  });

  it("still lists every grouped member individually in the data table", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="1,000 jobs found" segments={SEGMENTS} />,
    );
    const table = root.querySelector('[data-testid="chart-data-table"]');
    expect(table?.textContent).toContain("Lever");
    expect(table?.textContent).toContain("Workable");
  });
});

describe("legend", () => {
  it("pairs every colour with a word (C-5)", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="1,000 jobs found" segments={SEGMENTS} />,
    );
    const swatches = root.querySelectorAll('[data-testid="legend-swatch"]');
    const rows = root.querySelectorAll('[data-testid="legend-row"]');
    expect(swatches.length).toBe(rows.length);
    rows.forEach((row) => {
      expect((row.textContent ?? "").trim().length).toBeGreaterThan(0);
    });
  });

  it("never gives a measured source the neutral swatch reserved for 'not measured'", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="1,000 jobs found" segments={SEGMENTS} />,
    );
    const lever = root.querySelector(
      '[data-segment="Lever"] [data-testid="legend-swatch"]',
    ) as HTMLElement;
    const other = root.querySelector(
      '[data-segment="Other"] [data-testid="legend-swatch"]',
    ) as HTMLElement;
    // Lever is grouped into Other, but it is still a MEASURED source: it wears
    // Other's colour. state-neutral means "no data" (Rule D-1) and must never
    // land on a source that returned 12 jobs.
    expect(lever.style.backgroundColor).not.toBe("rgb(139, 139, 163)");
    expect(lever.style.backgroundColor).toBe(other.style.backgroundColor);
  });

  it("shows the absolute count next to every percentage", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="1,000 jobs found" segments={SEGMENTS} />,
    );
    const adzuna = root.querySelector('[data-segment="Adzuna"]');
    expect(adzuna?.textContent).toContain("52.0%");
    expect(adzuna?.textContent).toContain("520");
    expect(
      root.querySelector('[data-segment="Adzuna"] [data-testid="legend-value"]')?.className,
    ).toContain("tabular-nums");
  });
});

describe("C-1 / C-2", () => {
  const edge = [
    { label: "Adzuna", value: 520 },
    { label: "Seek", value: 0 },
    { label: "Indeed", value: null, note: "connector not configured" },
  ];

  it("draws no arc for a zero segment and shows its 0 in state-neutral", () => {
    const root = renderChart(
      <Donut
        title="Source mix"
        windowLabel="520 jobs found"
        segments={edge}
        nullMeaning="connector not configured"
      />,
    );
    expect(root.querySelector('[data-arc][data-segment-name="Seek"]')).toBeNull();
    const zero = marks(root, "zero")[0] as HTMLElement;
    expect(zero.textContent).toContain("0");
    expect(zero.dataset.tone).toBe("neutral");
  });

  it("draws an em dash — never a 0 and never an arc — for an unmeasured source", () => {
    const root = renderChart(
      <Donut
        title="Source mix"
        windowLabel="520 jobs found"
        segments={edge}
        nullMeaning="connector not configured"
      />,
    );
    const unmeasured = marks(root, "unmeasured")[0] as HTMLElement;
    expect(unmeasured.textContent).toContain("—");
    expect(unmeasured.textContent).not.toContain("0");
    expect(root.querySelector('[data-arc][data-segment-name="Indeed"]')).toBeNull();
    expect(root.querySelector('[data-segment="Indeed"]')?.getAttribute("title")).toContain(
      "connector not configured",
    );
  });

  it("computes percentages against the measured total only, and says so", () => {
    const root = renderChart(
      <Donut
        title="Source mix"
        windowLabel="520 jobs found"
        segments={edge}
        nullMeaning="connector not configured"
      />,
    );
    expect(root.querySelector('[data-segment="Adzuna"]')?.textContent).toContain("100.0%");
    expect(root.querySelector("figcaption")?.textContent).toContain("connector not configured");
  });
});

describe("C-1 — a wide dynamic range cannot invert a real 'Other' arc and a genuine absence", () => {
  /**
   * The reviewer's exact repro (REVIEW-02-chart-kit-reverify.md Part 2, and
   * CLOSE-01-completion-round-manifest.txt's filed-not-fixed observation):
   * one real, measured source at 30 / 10030 ≈ 0.3% share falls below the 2%
   * grouping default and alone becomes "Other". Pre-fix, `length ≈ 0.79`
   * against `GAP = 1.5` computed `visible = 0` — the ring's own
   * `stroke-dasharray` read `"0 263.89…"`, zero visible pixels for a real,
   * disclosed, nonzero value, indistinguishable from a genuine `value === 0`
   * segment (which by design draws no arc at all — see "C-1 / C-2" above).
   */
  const WIDE_RANGE = [
    { label: "Adzuna", value: 10000 },
    { label: "Workable", value: 30 },
  ];

  it("never renders the 'Other' arc's stroke-dasharray with a 0 visible-length first value", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="10,030 jobs found" segments={WIDE_RANGE} />,
    );
    const other = root.querySelector('[data-arc][data-segment-name="Other"]');
    expect(other).not.toBeNull();
    const [visible] = (other?.getAttribute("stroke-dasharray") ?? "")
      .split(" ")
      .map(Number);
    expect(visible).toBeGreaterThan(0);
  });

  it("floors the 'Other' arc for legibility without rescaling — Adzuna's arc still dwarfs it", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="10,030 jobs found" segments={WIDE_RANGE} />,
    );
    const other = root.querySelector('[data-arc][data-segment-name="Other"]');
    const adzuna = root.querySelector('[data-arc][data-segment-name="Adzuna"]');
    const visibleOf = (el: Element | null) =>
      Number((el?.getAttribute("stroke-dasharray") ?? "0").split(" ")[0]);

    expect(visibleOf(adzuna)).toBeGreaterThan(visibleOf(other) * 20);
  });
});

describe("empty state", () => {
  it("draws a designed empty state when nothing has been found yet", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="0 jobs found" segments={[]} />,
    );
    expect(root.querySelector('[data-testid="chart-empty"]')).not.toBeNull();
    expect(root.querySelectorAll("[data-arc]")).toHaveLength(0);
  });
});

describe("motion", () => {
  it("leaves arc geometry alone and only offsets the sweep, so a refetch cannot re-animate", () => {
    const root = renderChart(
      <Donut title="Source mix" windowLabel="1,000 jobs found" segments={SEGMENTS} />,
    );
    const arc = root.querySelector("[data-arc]") as unknown as HTMLElement;
    const dash = arc.getAttribute("stroke-dasharray");
    cleanup();
    stubMatchMedia(true);
    const still = renderChart(
      <Donut title="Source mix" windowLabel="1,000 jobs found" segments={SEGMENTS} />,
    );
    const reduced = still.querySelector("[data-arc]") as unknown as HTMLElement;
    expect(reduced.getAttribute("stroke-dasharray")).toBe(dash);
    expect(reduced.style.transition).toBe("");
  });
});
