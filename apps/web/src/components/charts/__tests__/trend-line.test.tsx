// @vitest-environment jsdom
/**
 * `<TrendLine>` — the sparkline / trend primitive.
 *
 * Honesty rules pinned here:
 *  - fewer than 3 measured points ⇒ the component draws NOTHING (no
 *    interpolation, no two-point "trend").
 *  - a gap in the data is drawn as a gap (dashed bridge + a legend note),
 *    never straight-lined through as if it were measured.
 *  - a truncated baseline declares itself (C-4).
 *  - markers only at meaningful points (first / min / max / last), per
 *    reference-pack rule 5.
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { TrendLine } from "../TrendLine";
import { CANVAS_POINT_THRESHOLD } from "../tokens";
import { clearMatchMedia, renderChart, stubMatchMedia } from "./testUtils";

const POINTS = [
  { label: "Mon", value: 12 },
  { label: "Tue", value: 18 },
  { label: "Wed", value: 9 },
  { label: "Thu", value: 24 },
  { label: "Fri", value: 15 },
];

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("minimum evidence", () => {
  it("renders no line at all from 2 points, and says why", () => {
    const root = renderChart(
      <TrendLine title="Jobs found" windowLabel="last 7 days" points={POINTS.slice(0, 2)} />,
    );
    expect(root.querySelector('[data-testid="trend-path"]')).toBeNull();
    const empty = root.querySelector('[data-testid="chart-empty"]');
    expect(empty?.textContent).toContain("3");
    expect(empty?.textContent?.toLowerCase()).toContain("point");
  });

  it("draws the line once 3 real points exist", () => {
    const root = renderChart(
      <TrendLine title="Jobs found" windowLabel="last 7 days" points={POINTS.slice(0, 3)} />,
    );
    const path = root.querySelector('[data-testid="trend-path"]');
    expect(path).not.toBeNull();
    expect(path?.getAttribute("d")?.startsWith("M")).toBe(true);
  });

  it("counts only MEASURED points toward the minimum", () => {
    const root = renderChart(
      <TrendLine
        title="Jobs found"
        windowLabel="last 7 days"
        points={[
          { label: "Mon", value: 12 },
          { label: "Tue", value: null },
          { label: "Wed", value: null },
          { label: "Thu", value: 24 },
        ]}
        nullMeaning="collector offline"
      />,
    );
    expect(root.querySelector('[data-testid="trend-path"]')).toBeNull();
    expect(root.querySelector('[data-testid="chart-empty"]')).not.toBeNull();
  });
});

describe("gaps are gaps", () => {
  const gapped = [
    { label: "Mon", value: 12 },
    { label: "Tue", value: 18 },
    { label: "Wed", value: null, note: "collector offline" },
    { label: "Thu", value: 24 },
    { label: "Fri", value: 20 },
  ];

  it("splits the stroke at the gap instead of drawing through it", () => {
    const root = renderChart(
      <TrendLine
        title="Jobs found"
        windowLabel="last 7 days"
        points={gapped}
        nullMeaning="collector offline"
      />,
    );
    const segments = root.querySelectorAll('[data-testid="trend-path"]');
    expect(segments.length).toBeGreaterThan(1);
  });

  it("draws the bridging segment dashed and explains the dash in the legend", () => {
    const root = renderChart(
      <TrendLine
        title="Jobs found"
        windowLabel="last 7 days"
        points={gapped}
        nullMeaning="collector offline"
      />,
    );
    const bridge = root.querySelector('[data-testid="trend-bridge"]');
    expect(bridge).not.toBeNull();
    expect(bridge?.getAttribute("stroke-dasharray")).toBeTruthy();
    expect(root.textContent?.toLowerCase()).toContain("no data");
  });

  it("puts the gap's reason in the data table", () => {
    const root = renderChart(
      <TrendLine
        title="Jobs found"
        windowLabel="last 7 days"
        points={gapped}
        nullMeaning="collector offline"
      />,
    );
    const table = root.querySelector('[data-testid="chart-data-table"]');
    expect(table?.textContent).toContain("not measured");
    expect(table?.textContent).toContain("collector offline");
  });
});

describe("framing", () => {
  it("draws horizontal gridlines only — no vertical rules, no chart border", () => {
    const root = renderChart(
      <TrendLine title="Jobs found" windowLabel="last 7 days" points={POINTS} />,
    );
    const gridlines = root.querySelectorAll('[data-testid="gridline"]');
    expect(gridlines.length).toBeGreaterThan(0);
    gridlines.forEach((line) => {
      expect(line.getAttribute("y1")).toBe(line.getAttribute("y2"));
    });
    expect(root.querySelectorAll('[data-testid="gridline-vertical"]')).toHaveLength(0);
  });

  it("fills under the line with a fading gradient, not a solid block", () => {
    const root = renderChart(
      <TrendLine title="Jobs found" windowLabel="last 7 days" points={POINTS} />,
    );
    const area = root.querySelector('[data-testid="trend-area"]');
    expect(area?.getAttribute("fill")).toMatch(/^url\(#/);
    const stops = root.querySelectorAll("linearGradient stop");
    expect(stops.length).toBeGreaterThanOrEqual(2);
    expect(stops[stops.length - 1]?.getAttribute("stop-opacity")).toBe("0");
  });

  it("places markers only at meaningful points, not on every sample", () => {
    const root = renderChart(
      <TrendLine title="Jobs found" windowLabel="last 7 days" points={POINTS} />,
    );
    const markers = root.querySelectorAll("[data-marker]");
    const kinds = Array.from(markers).map((m) => m.getAttribute("data-marker"));
    expect(markers.length).toBeLessThan(POINTS.length);
    expect(kinds).toContain("max");
    expect(kinds).toContain("min");
    expect(kinds).toContain("last");
  });

  it("declares a truncated baseline instead of silently starting above zero", () => {
    const root = renderChart(
      <TrendLine
        title="Jobs found"
        windowLabel="last 7 days"
        points={POINTS}
        baseline="data-min"
      />,
    );
    const glyph = root.querySelector('[data-testid="axis-break"]');
    expect(glyph).not.toBeNull();
    expect(glyph?.textContent).toContain("9");
  });
});

describe("very large series", () => {
  const many = Array.from({ length: CANVAS_POINT_THRESHOLD + 1 }, (_, i) => ({
    label: `t${i}`,
    value: (i % 50) + 1,
  }));

  it("switches to canvas above the 2,000-point threshold instead of 2,001 SVG nodes", () => {
    const root = renderChart(
      <TrendLine title="Score stream" windowLabel="2,001 samples" points={many} />,
    );
    expect(CANVAS_POINT_THRESHOLD).toBe(2000);
    expect(root.querySelector("canvas")).not.toBeNull();
    expect(root.querySelector('[data-testid="trend-path"]')).toBeNull();
  });

  it("says so, rather than showing an empty box, when canvas is unavailable", () => {
    // jsdom has no 2d context — the honest fallback must be visible.
    const root = renderChart(
      <TrendLine title="Score stream" windowLabel="2,001 samples" points={many} />,
    );
    expect(root.querySelector('[data-testid="canvas-unavailable"]')?.textContent).toMatch(
      /data table/i,
    );
  });

  it("keeps the sample window and the summary honest at that size", () => {
    const root = renderChart(
      <TrendLine title="Score stream" windowLabel="2,001 samples" points={many} />,
    );
    expect(root.querySelector("figcaption")?.textContent).toContain("2,001 samples");
    expect(root.querySelector('[data-testid="chart-data-table"]')?.textContent).toContain("2,001");
  });
});

describe("motion", () => {
  it("draws the path immediately under reduced motion", () => {
    cleanup();
    stubMatchMedia(true);
    const root = renderChart(
      <TrendLine title="Jobs found" windowLabel="last 7 days" points={POINTS} />,
    );
    const path = root.querySelector('[data-testid="trend-path"]') as SVGElement;
    expect(root.getAttribute("data-motion")).toBe("off");
    expect((path as unknown as HTMLElement).style.transition).toBe("");
    expect((path as unknown as HTMLElement).style.strokeDashoffset).toBe("");
  });
});
