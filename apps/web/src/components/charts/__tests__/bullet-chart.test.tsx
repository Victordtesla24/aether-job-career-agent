// @vitest-environment jsdom
/**
 * `<BulletChart>` — the measure-against-a-target mark, and the component that
 * replaced two paragraphs of arithmetic ("8.33% … against the 20% target …
 * 11.67% to go") with a picture of the same three numbers.
 *
 * What this file pins is the honesty, not the pixels:
 *   · a withheld rate is a DASH with its reason on the row, never a 0% bar
 *     (C-2) — this is the whole reason a below-minimum-sample cohort exists;
 *   · a measured zero is a hairline tick, never a coloured bar (C-1);
 *   · the target is a labelled tick, so the comparison is never carried by
 *     colour alone (C-5);
 *   · the coverage ribbon states how much of the population the measures above
 *     actually describe, with the unattributable share as its own hatched,
 *     labelled segment — the visual form of "290 of 317 submissions predate the
 *     instrumentation";
 *   · every row, the target and every coverage segment reach the hidden data
 *     table, so the chart's text equivalent is complete.
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { BulletChart } from "../BulletChart";
import { HAIRLINE } from "../tokens";
import { clearMatchMedia, marks, renderChart, stubMatchMedia } from "./testUtils";

const TARGET = { value: 20, label: "20% target" };

const ROWS = [
  {
    label: "Standard rigor",
    value: 8.33,
    display: "8.33%",
    basis: "2 interviews from 24 submitted",
    testId: "policy-cohort-standard",
  },
  {
    label: "Heightened rigor",
    value: null,
    basis: "0 interviews from 3 submitted",
    note: "not enough data yet — at least 5 submissions are needed before a rate means anything",
    testId: "policy-cohort-heightened",
  },
];

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("the comparison the prose used to ask the reader to do", () => {
  it("draws one row per measure with its numeral and its denominator", () => {
    const root = renderChart(
      <BulletChart title="Cohorts" windowLabel="all-time" rows={ROWS} target={TARGET} />,
    );
    const standard = root.querySelector('[data-testid="policy-cohort-standard"]');
    expect(standard?.textContent).toContain("8.33%");
    // A percentage never appears without the count it was computed from.
    expect(standard?.textContent).toContain("24 submitted");
  });

  it("labels the target on the plot, so the comparison is never colour alone (C-5)", () => {
    const root = renderChart(
      <BulletChart title="Cohorts" windowLabel="all-time" rows={ROWS} target={TARGET} />,
    );
    expect(root.querySelector('[data-testid="bullet-target-label"]')?.textContent).toContain(
      "20% target",
    );
    expect(root.querySelectorAll('[data-testid="bullet-target-tick"]')).toHaveLength(ROWS.length);
  });
});

describe("C-2 — a withheld rate is not a zero", () => {
  it("renders an unmeasured row as the neutral dash, never as 0%", () => {
    const root = renderChart(
      <BulletChart title="Cohorts" windowLabel="all-time" rows={ROWS} target={TARGET} />,
    );
    const heightened = root.querySelector('[data-testid="policy-cohort-heightened"]');
    expect(heightened?.textContent).toContain("—");
    expect(heightened?.textContent).not.toContain("0%");
    expect(marks(root, "value")).toHaveLength(1); // only the measured row draws a bar
  });

  it("keeps the reason a rate was withheld ON the row", () => {
    const root = renderChart(
      <BulletChart title="Cohorts" windowLabel="all-time" rows={ROWS} target={TARGET} />,
    );
    const heightened = root.querySelector('[data-testid="policy-cohort-heightened"]');
    expect(heightened?.textContent?.toLowerCase()).toContain("not enough data yet");
    expect(heightened?.textContent).toContain("at least 5");
  });
});

describe("C-1 — a measured zero is not a colour", () => {
  it("draws a real 0 as a hairline tick, not a bar", () => {
    const root = renderChart(
      <BulletChart
        title="Cohorts"
        windowLabel="all-time"
        rows={[{ label: "Heightened rigor", value: 0, display: "0%" }]}
        target={TARGET}
      />,
    );
    const zero = marks(root, "zero")[0] as HTMLElement | undefined;
    expect(zero).toBeTruthy();
    // jsdom re-serialises the rgba() with spaces — compare on the numbers.
    expect(zero?.style.backgroundColor.replace(/\s+/g, "")).toBe(HAIRLINE.replace(/\s+/g, ""));
    expect(marks(root, "value")).toHaveLength(0);
  });
});

describe("the coverage ribbon", () => {
  const COVERAGE = [
    { label: "Standard rigor", count: 24, kind: "attributed" as const },
    { label: "Heightened rigor", count: 3, kind: "attributed" as const },
    { label: "No tier recorded", count: 290, kind: "unattributed" as const },
  ];

  it("draws the unattributable share as its own labelled segment", () => {
    const root = renderChart(
      <BulletChart
        title="Cohorts"
        windowLabel="all-time"
        rows={ROWS}
        target={TARGET}
        coverage={COVERAGE}
      />,
    );
    const segments = root.querySelectorAll('[data-testid="bullet-coverage-segment"]');
    expect(segments).toHaveLength(3);
    const unattributed = root.querySelector('[data-coverage="unattributed"]') as HTMLElement;
    expect(unattributed).toBeTruthy();
    // 290 of 317 — the segment is the majority of the ribbon, which is the
    // entire point: the rates above describe the small remainder.
    expect(Number.parseFloat(unattributed.style.width)).toBeGreaterThan(90);
    const legend = root.querySelector('[data-testid="bullet-coverage-legend"]');
    expect(legend?.textContent).toContain("No tier recorded");
    expect(legend?.textContent).toContain("290");
  });

  it("omits the ribbon entirely when there is nothing to cover", () => {
    const root = renderChart(
      <BulletChart
        title="Cohorts"
        windowLabel="all-time"
        rows={ROWS}
        target={TARGET}
        coverage={[]}
      />,
    );
    expect(root.querySelector('[data-testid="bullet-coverage"]')).toBeNull();
  });
});

describe("the text equivalent", () => {
  it("lists every row, the target and every coverage segment in the hidden table", () => {
    const root = renderChart(
      <BulletChart
        title="Cohorts"
        windowLabel="all-time"
        rows={ROWS}
        target={TARGET}
        coverage={[{ label: "No tier recorded", count: 290, kind: "unattributed" }]}
      />,
    );
    const table = root.querySelector('[data-testid="chart-data-table"]');
    expect(table?.textContent).toContain("Standard rigor");
    expect(table?.textContent).toContain("20% target (target)");
    expect(table?.textContent).toContain("No tier recorded (coverage)");
    // The unmeasured row reads as unmeasured, with its reason, in words.
    expect(table?.querySelector('[data-row-mark="unmeasured"]')?.textContent).toContain(
      "not measured",
    );
  });
});

describe("the empty state is designed (D-θ)", () => {
  it("says what is missing instead of drawing an empty axis", () => {
    const root = renderChart(
      <BulletChart
        title="Cohorts"
        windowLabel="all-time"
        rows={[]}
        target={TARGET}
        emptyMessage="No application has been submitted under a recorded policy tier yet."
        emptyHint="Cohorts appear as soon as one submission carries a tier."
      />,
    );
    expect(root.querySelector('[data-testid="chart-empty"]')?.textContent).toContain(
      "No application has been submitted under a recorded policy tier yet.",
    );
  });
});
