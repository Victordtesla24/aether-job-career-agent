// @vitest-environment jsdom
/**
 * `<BulletChart>` WITHOUT A TARGET — the shape the Agent ROI panel needed
 * (ANALYTICS-VIZ round 3, F3), and the two defects that shape exposed.
 *
 * The judge's must-fix replaced a five-numeral tile grid with a real chart of
 * cost per submitted application vs cost per interview. Nothing in this
 * product publishes what either OUGHT to cost, so the chart has no target —
 * and a component built around a target turned out to make two silent
 * assumptions that only a targetless, sub-dollar series could reveal:
 *
 *   1. THE AXIS WAS A CONSTANT. `Math.max(…measured, target, 1) * 1.25` never
 *      bound on a percentage series, because every percentage and every target
 *      exceeds 1. On dollars-and-cents it dominated: $0.03 drew a 2.7% bar
 *      against an invented $1.25 axis. A mark that small says "negligible"
 *      about the only number on the row.
 *
 *   2. TWO ROWS COULD BE DRAWN ON DIFFERENT-LENGTH TRACKS. `note` carried
 *      `flex-1`, the same as the track, so a row whose reason-for-"—" was a
 *      sentence gave up hundreds of pixels of track to it. Two bars on tracks
 *      of different lengths are not on one scale, which is the single
 *      guarantee a bullet row exists to make.
 *
 * Both are pinned here rather than in `bullet-chart.test.tsx`, which stays
 * untouched: every assertion in that file is about the WITH-target behaviour
 * and must keep passing exactly as written.
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { BulletChart } from "../BulletChart";
import { clearMatchMedia, renderChart, stubMatchMedia } from "./testUtils";

/** The real shape of the ROI panel: one measured cent-scale ratio, one honest
 *  "—" whose reason is a full sentence. */
const COST_ROWS = [
  {
    testId: "roi-cost-per-application",
    label: "Cost per application",
    value: 0.034256,
    display: "$0.03",
    basis: "$11.75 over 343 submitted",
  },
  {
    testId: "roi-cost-per-interview",
    label: "Cost per interview",
    value: null,
    note: "No application has reached this stage yet — nothing to divide by.",
  },
];

const WINDOW = "all time — total agent spend over the all-time funnel";

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("a chart with no published target draws no target", () => {
  it("renders neither the tick nor its label, and claims no target in the data table", () => {
    const root = renderChart(
      <BulletChart title="Cost per outcome" windowLabel={WINDOW} rows={COST_ROWS} />,
    );

    expect(root.querySelector('[data-testid="bullet-target-tick"]')).toBeNull();
    expect(root.querySelector('[data-testid="bullet-target-label"]')).toBeNull();
    // The text equivalent must not invent one either.
    expect(root.querySelector('[data-testid="chart-data-table"]')?.textContent).not.toContain(
      "(target)",
    );
  });

  it("still draws the measure, so 'no target' never means 'no chart'", () => {
    const root = renderChart(
      <BulletChart title="Cost per outcome" windowLabel={WINDOW} rows={COST_ROWS} />,
    );
    expect(root.querySelectorAll('[data-mark="value"]')).toHaveLength(1);
    expect(root.querySelectorAll('[data-mark="unmeasured"]')).toHaveLength(1);
  });
});

describe("the axis is scaled to the data, not to a constant floor", () => {
  it("draws a sub-dollar measure as a real bar instead of a sliver", () => {
    const root = renderChart(
      <BulletChart title="Cost per outcome" windowLabel={WINDOW} rows={COST_ROWS} />,
    );
    const bar = root.querySelector('[data-testid="bullet-measure"]') as HTMLElement;
    expect(bar).toBeTruthy();
    // Axis = the largest measure + 25% headroom, so the largest measure lands
    // at 80% of the track. Against the old `1` floor this was 2.7%.
    const width = Number.parseFloat(bar.style.width);
    expect(width).toBeGreaterThan(70);
    expect(width).toBeLessThanOrEqual(100);
  });

  it("keeps a finite axis when nothing has been measured at all", () => {
    const root = renderChart(
      <BulletChart
        title="Cost per outcome"
        windowLabel={WINDOW}
        rows={[{ label: "Cost per interview", value: null, note: "nothing to divide by" }]}
      />,
    );
    // No bar, no NaN width, and the dash still carries its reason.
    expect(root.querySelector('[data-testid="bullet-measure"]')).toBeNull();
    expect(root.querySelector('[data-mark="unmeasured"]')).toBeTruthy();
    expect(root.textContent).toContain("nothing to divide by");
  });

  it("leaves a percentage series exactly where it was (no regression for the target charts)", () => {
    const root = renderChart(
      <BulletChart
        title="Cohorts"
        windowLabel="all-time"
        rows={[{ label: "Standard rigor", value: 8.33, display: "8.33%" }]}
        target={{ value: 20, label: "20% target" }}
      />,
    );
    // top = max(8.33, 20) * 1.25 = 25 — identical to the previous
    // max(8.33, 20, 1) * 1.25, because the floor never bound here.
    const bar = root.querySelector('[data-testid="bullet-measure"]') as HTMLElement;
    expect(Number.parseFloat(bar.style.width)).toBeCloseTo((8.33 / 25) * 100, 4);
  });
});

describe("every row is drawn on the same track", () => {
  it("gives the measure line exactly one flexible element — the track", () => {
    const root = renderChart(
      <BulletChart title="Cost per outcome" windowLabel={WINDOW} rows={COST_ROWS} />,
    );
    const rows = Array.from(
      root.querySelectorAll('[data-testid^="roi-cost-per-"]'),
    ) as HTMLElement[];
    expect(rows).toHaveLength(2);

    for (const row of rows) {
      const flexible = Array.from(row.children).filter((child) =>
        child.className.toString().split(/\s+/).includes("flex-1"),
      );
      // Before: the note was `flex-1` too, so the row carrying a sentence had
      // TWO competitors for the free space and a visibly shorter track.
      expect(flexible).toHaveLength(1);
      expect(flexible[0].querySelector('[data-testid="bullet-track"]')).toBeTruthy();
    }
  });

  it("moves the denominator and the reason to their own full-width line", () => {
    const root = renderChart(
      <BulletChart title="Cost per outcome" windowLabel={WINDOW} rows={COST_ROWS} />,
    );
    const basis = root.querySelector('[data-testid="bullet-basis"]') as HTMLElement;
    const note = root.querySelector('[data-testid="bullet-note"]') as HTMLElement;

    expect(basis.parentElement?.className).toContain("w-full");
    expect(note.parentElement?.className).toContain("w-full");
    // …and they are still ON the row they qualify, not floated elsewhere.
    expect(basis.closest('[data-testid="roi-cost-per-application"]')).toBeTruthy();
    expect(note.closest('[data-testid="roi-cost-per-interview"]')).toBeTruthy();
    expect(note.textContent).toContain("nothing to divide by");
  });
});
