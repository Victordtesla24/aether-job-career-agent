// @vitest-environment jsdom
/**
 * `<Histogram>` — the ATS-score distribution.
 *
 * The current analytics implementation draws a 2px violet line for every
 * EMPTY bucket (`Math.max(2, ...)`), so "no résumé scored 0-9" reads as
 * "a few résumés scored 0-9". C-1 forbids that: an empty bucket gets a 1px
 * hairline tick at the baseline and nothing in the series colour.
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Histogram } from "../Histogram";
import { ZERO_TICK_WIDTH } from "../geometry";
import { CHART_PALETTE, HAIRLINE } from "../tokens";
import {
  clearMatchMedia,
  marks,
  renderChart,
  silenceConsoleError,
  stubMatchMedia,
} from "./testUtils";

const BUCKETS = [
  { range: "0-19", count: 0 },
  { range: "20-39", count: 3 },
  { range: "40-59", count: 11 },
  { range: "60-79", count: 26 },
  { range: "80-100", count: 4 },
];

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("a real axis", () => {
  it("labels every bucket with its RANGE, not a single edge number", () => {
    const root = renderChart(
      <Histogram title="ATS scores" windowLabel="44 scored résumés" buckets={BUCKETS} />,
    );
    const labels = Array.from(root.querySelectorAll('[data-testid="bucket-label"]')).map(
      (n) => n.textContent,
    );
    expect(labels).toEqual(["0-19", "20-39", "40-59", "60-79", "80-100"]);
  });

  it("draws horizontal gridlines with numeric y-axis labels including the max", () => {
    const root = renderChart(
      <Histogram title="ATS scores" windowLabel="44 scored résumés" buckets={BUCKETS} />,
    );
    expect(root.querySelectorAll('[data-testid="gridline"]').length).toBeGreaterThanOrEqual(4);
    const axis = Array.from(root.querySelectorAll('[data-testid="axis-label"]')).map(
      (n) => n.textContent,
    );
    expect(axis).toContain("26");
    expect(axis).toContain("0");
  });

  it("uses tabular numerals for the axis so columns of numbers align", () => {
    const root = renderChart(
      <Histogram title="ATS scores" windowLabel="44 scored résumés" buckets={BUCKETS} />,
    );
    const axis = root.querySelector('[data-testid="axis-label"]');
    expect(axis?.getAttribute("class")).toContain("tabular-nums");
  });

  it("carries the count of each bucket in a hover title", () => {
    const root = renderChart(
      <Histogram
        title="ATS scores"
        windowLabel="44 scored résumés"
        buckets={BUCKETS}
        itemNoun="résumés"
      />,
    );
    const titles = Array.from(root.querySelectorAll("title")).map((n) => n.textContent);
    expect(titles).toContain("60-79: 26 résumés");
  });
});

describe("C-1 — an empty bucket", () => {
  it("renders a 1px hairline tick at the baseline, never a coloured bar", () => {
    const root = renderChart(
      <Histogram title="ATS scores" windowLabel="44 scored résumés" buckets={BUCKETS} />,
    );
    const zero = marks(root, "zero");
    expect(zero).toHaveLength(1);
    expect(zero[0]?.getAttribute("height")).toBe("1");
    expect(zero[0]?.getAttribute("fill")).toBe(HAIRLINE);
    expect(zero[0]?.getAttribute("fill")).not.toBe(CHART_PALETTE[0]);
  });

  it("sits at the baseline, not above it", () => {
    const root = renderChart(
      <Histogram title="ATS scores" windowLabel="44 scored résumés" buckets={BUCKETS} />,
    );
    const zero = marks(root, "zero")[0];
    const value = marks(root, "value")[0];
    const zeroBottom = Number(zero?.getAttribute("y")) + Number(zero?.getAttribute("height"));
    const valueBottom = Number(value?.getAttribute("y")) + Number(value?.getAttribute("height"));
    expect(zeroBottom).toBeCloseTo(valueBottom, 5);
    expect(Number(zero?.getAttribute("height"))).toBeLessThan(
      Number(value?.getAttribute("height")),
    );
  });

  it("still reports the bucket as 0 (not missing) in the data table", () => {
    const root = renderChart(
      <Histogram title="ATS scores" windowLabel="44 scored résumés" buckets={BUCKETS} />,
    );
    const row = root.querySelector('[data-testid="chart-data-table"] [data-row-mark="zero"]');
    expect(row?.textContent).toContain("0-19");
    expect(row?.textContent).toContain("0");
    expect(row?.textContent).not.toContain("not measured");
  });
});

describe("C-1 — a wide dynamic range cannot invert zero and a real value", () => {
  /**
   * The fixture the original five tests never had: a dominant bucket four
   * orders of magnitude above a real one. Proportional-only maths gives the
   * count:1 bucket 162 / 100_000 ≈ 0.0016px of height while the count:0 bucket
   * keeps its mandated 1px tick — a measured value rendered ~600x THINNER than
   * a measured nothing, which is precisely the inversion C-1 exists to forbid.
   */
  const WIDE_RANGE = [
    { range: "0-19", count: 0 },
    { range: "20-39", count: 1 },
    { range: "40-100", count: 100000 },
  ];

  it("draws a bucket of 1 STRICTLY TALLER than the zero bucket's hairline tick", () => {
    const root = renderChart(
      <Histogram title="ATS scores" windowLabel="100,001 scored résumés" buckets={WIDE_RANGE} />,
    );
    const zero = marks(root, "zero")[0];
    const zeroHeight = Number(zero?.getAttribute("height"));
    const small = root.querySelector('[data-bucket="20-39"] [data-mark="value"]');
    const smallHeight = Number(small?.getAttribute("height"));

    expect(zeroHeight).toBe(ZERO_TICK_WIDTH);
    expect(smallHeight).toBeGreaterThan(zeroHeight);
  });

  it("keeps the tiny bar on the baseline while the dominant bar still scales to the plot", () => {
    const root = renderChart(
      <Histogram title="ATS scores" windowLabel="100,001 scored résumés" buckets={WIDE_RANGE} />,
    );
    const small = root.querySelector('[data-bucket="20-39"] [data-mark="value"]');
    const dominant = root.querySelector('[data-bucket="40-100"] [data-mark="value"]');
    const bottom = (el: Element | null) =>
      Number(el?.getAttribute("y")) + Number(el?.getAttribute("height"));

    // Same baseline: the floor lifts the bar's TOP, it never floats the bar.
    expect(bottom(small)).toBeCloseTo(bottom(dominant), 5);
    // The floor is a legibility minimum, not a rescale — 1 stays far below 100,000.
    expect(Number(dominant?.getAttribute("height"))).toBeGreaterThan(
      Number(small?.getAttribute("height")) * 50,
    );
  });
});

describe("C-2 — a bucket that was never scored", () => {
  const withNull = [
    { range: "0-19", count: 0 },
    { range: "20-39", count: null, note: "scores below 40 were not retained before 12 Aug" },
    { range: "40-59", count: 11 },
  ];

  it("renders an em dash above the baseline, not an empty-looking bucket", () => {
    const root = renderChart(
      <Histogram
        title="ATS scores"
        windowLabel="44 scored résumés"
        buckets={withNull}
        nullMeaning="scores below 40 were not retained before 12 Aug"
      />,
    );
    const unmeasured = marks(root, "unmeasured");
    expect(unmeasured).toHaveLength(1);
    expect(unmeasured[0]?.textContent).toBe("—");
  });

  it("is refused outright when the caller does not say what null means (C-2)", () => {
    const restore = silenceConsoleError();
    expect(() =>
      renderChart(
        <Histogram title="ATS scores" windowLabel="44 scored résumés" buckets={withNull} />,
      ),
    ).toThrowError(/C-2/);
    restore();
  });
});

describe("empty state", () => {
  it("draws a designed empty plot when there are no buckets at all", () => {
    const root = renderChart(
      <Histogram title="ATS scores" windowLabel="0 scored résumés" buckets={[]} />,
    );
    expect(root.querySelector('[data-testid="chart-empty"]')).not.toBeNull();
  });

  it("does not pretend an all-zero distribution is an empty one", () => {
    const root = renderChart(
      <Histogram
        title="ATS scores"
        windowLabel="0 scored résumés"
        buckets={[
          { range: "0-49", count: 0 },
          { range: "50-100", count: 0 },
        ]}
      />,
    );
    expect(root.querySelector('[data-testid="chart-empty"]')).toBeNull();
    expect(marks(root, "zero")).toHaveLength(2);
  });
});
