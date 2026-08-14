// @vitest-environment jsdom
/**
 * `<DivergingBar>` — the market-vs-you rows.
 *
 * Every row is a comparison against a live external source, so the honesty
 * surface is large: a row whose source is not connected, or whose snapshot is
 * not available, renders "—" plus the caller's VERBATIM reason (never 0, never
 * "no change"), and the freshness stamp travels with the value.
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DivergingBar } from "../DivergingBar";
import { ZERO_TICK_WIDTH } from "../geometry";
import { DIVERGING, HAIRLINE } from "../tokens";
import { clearMatchMedia, marks, renderChart, stubMatchMedia } from "./testUtils";

const ROWS = [
  { label: "Median salary", value: 12, display: "+A$12,000", freshness: "data as of 13 Aug 2026" },
  { label: "Response rate", value: -8, display: "-8 pts", freshness: "data as of 13 Aug 2026" },
  { label: "Time to interview", value: 0, display: "0 days", freshness: "data as of 13 Aug 2026" },
];

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("shared zero axis", () => {
  it("draws exactly one zero axis that every row is measured from", () => {
    const root = renderChart(
      <DivergingBar title="Market vs you" windowLabel="last 30 days" rows={ROWS} />,
    );
    expect(root.querySelectorAll('[data-testid="zero-axis"]')).toHaveLength(1);
  });

  it("puts a positive bar right of the axis and a negative bar left of it", () => {
    const root = renderChart(
      <DivergingBar title="Market vs you" windowLabel="last 30 days" rows={ROWS} />,
    );
    const positive = root.querySelector('[data-row="Median salary"] [data-testid="bar"]') as HTMLElement;
    const negative = root.querySelector('[data-row="Response rate"] [data-testid="bar"]') as HTMLElement;
    expect(positive.dataset.direction).toBe("positive");
    expect(negative.dataset.direction).toBe("negative");
    expect(positive.style.left).toBe("50%");
    expect(negative.style.right).toBe("50%");
  });

  it("colours the two directions apart AND labels the value, so colour is redundant (C-5)", () => {
    const root = renderChart(
      <DivergingBar title="Market vs you" windowLabel="last 30 days" rows={ROWS} />,
    );
    const positive = root.querySelector('[data-row="Median salary"] [data-testid="bar"]') as HTMLElement;
    const negative = root.querySelector('[data-row="Response rate"] [data-testid="bar"]') as HTMLElement;
    expect(positive.style.backgroundColor).toBe("rgb(52, 211, 153)");
    expect(negative.style.backgroundColor).toBe("rgb(248, 113, 113)");
    expect(DIVERGING.positive).toBe("#34D399");
    expect(DIVERGING.negative).toBe("#F87171");
    expect(root.querySelector('[data-row="Median salary"]')?.textContent).toContain("+A$12,000");
    expect(root.querySelector('[data-row="Response rate"]')?.textContent).toContain("-8 pts");
  });
});

describe("C-1 — a row that is genuinely level", () => {
  it("draws a 1px hairline tick on the axis, not a coloured bar", () => {
    const root = renderChart(
      <DivergingBar title="Market vs you" windowLabel="last 30 days" rows={ROWS} />,
    );
    const zero = marks(root, "zero");
    expect(zero).toHaveLength(1);
    const tick = zero[0] as HTMLElement;
    expect(tick.style.width).toBe("1px");
    expect(tick.style.backgroundColor).toBe("rgba(255, 255, 255, 0.07)");
    expect(HAIRLINE).toBe("rgba(255,255,255,0.07)");
    expect(root.querySelector('[data-row="Time to interview"] [data-testid="bar"]')).toBeNull();
  });

  it("keeps the row's own words — 0 days is still shown", () => {
    const root = renderChart(
      <DivergingBar title="Market vs you" windowLabel="last 30 days" rows={ROWS} />,
    );
    expect(root.querySelector('[data-row="Time to interview"]')?.textContent).toContain("0 days");
  });
});

describe("C-1 — a wide dynamic range cannot invert zero and a real value", () => {
  /**
   * The fixture the original tests never had: a dominant row four orders of
   * magnitude above a real one. Proportional-only maths gives the value:1 row
   * (1 / 100_000) * 50 = 0.0005% of the track, and the 2dp rounding on the
   * style then writes a literal "0%" — the row disappears entirely while the
   * genuinely level (value:0) row keeps its mandated 1px tick. A measured
   * value must never be LESS visible than a measured nothing.
   */
  const WIDE_RANGE = [
    { label: "Time to interview", value: 0, display: "0 days" },
    { label: "Response rate", value: 1, display: "+1 pt" },
    { label: "Median salary", value: 100000, display: "+A$100,000" },
  ];

  /** jsdom performs no layout, so the bar's percentage is converted at the
   *  NARROWEST track the kit is reviewed at (390px viewport ⇒ ~100px track,
   *  S-UI doctrine D-ι). The comparison must hold even there. */
  const NARROWEST_TRACK_PX = 100;

  it("never rounds a real value's bar down to a literal 0% width", () => {
    const root = renderChart(
      <DivergingBar title="Market vs you" windowLabel="last 30 days" rows={WIDE_RANGE} />,
    );
    const small = root.querySelector(
      '[data-row="Response rate"] [data-testid="bar"]',
    ) as HTMLElement;
    expect(small).not.toBeNull();
    expect(small.style.width).not.toBe("0%");
    expect(Number.parseFloat(small.style.width)).toBeGreaterThan(0);
  });

  it("renders the value:1 row STRICTLY WIDER than the level row's hairline tick", () => {
    const root = renderChart(
      <DivergingBar title="Market vs you" windowLabel="last 30 days" rows={WIDE_RANGE} />,
    );
    const tick = marks(root, "zero")[0] as HTMLElement;
    const small = root.querySelector(
      '[data-row="Response rate"] [data-testid="bar"]',
    ) as HTMLElement;

    expect(tick.style.width).toBe(`${ZERO_TICK_WIDTH}px`);
    const smallPx = (Number.parseFloat(small.style.width) / 100) * NARROWEST_TRACK_PX;
    expect(smallPx).toBeGreaterThan(ZERO_TICK_WIDTH);
  });

  it("floors for legibility without rescaling — 100,000 still dwarfs 1", () => {
    const root = renderChart(
      <DivergingBar title="Market vs you" windowLabel="last 30 days" rows={WIDE_RANGE} />,
    );
    const small = root.querySelector(
      '[data-row="Response rate"] [data-testid="bar"]',
    ) as HTMLElement;
    const dominant = root.querySelector(
      '[data-row="Median salary"] [data-testid="bar"]',
    ) as HTMLElement;
    expect(Number.parseFloat(dominant.style.width)).toBeGreaterThan(
      Number.parseFloat(small.style.width) * 20,
    );
  });
});

describe("C-2 — a row with no live source", () => {
  const rows = [
    { label: "Median salary", value: 12, display: "+A$12,000" },
    {
      label: "Applications per posting",
      value: null,
      available: false,
      reason: "Adzuna does not publish applicant counts",
    },
    {
      label: "Recruiter response",
      value: null,
      connected: false,
      reason: "connect your mailbox to measure this",
    },
  ];

  it("renders an em dash and the caller's reason verbatim — never a zero bar", () => {
    const root = renderChart(
      <DivergingBar
        title="Market vs you"
        windowLabel="last 30 days"
        rows={rows}
        nullMeaning="source not connected or not published"
      />,
    );
    const unmeasured = marks(root, "unmeasured");
    expect(unmeasured).toHaveLength(2);
    expect(unmeasured[0]?.textContent).toBe("—");
    expect(root.textContent).toContain("Adzuna does not publish applicant counts");
    expect(root.textContent).toContain("connect your mailbox to measure this");
    expect(root.querySelector('[data-row="Recruiter response"] [data-testid="bar"]')).toBeNull();
  });

  it("keeps the reason in the data table too", () => {
    const root = renderChart(
      <DivergingBar
        title="Market vs you"
        windowLabel="last 30 days"
        rows={rows}
        nullMeaning="source not connected or not published"
      />,
    );
    const table = root.querySelector('[data-testid="chart-data-table"]');
    expect(table?.textContent).toContain("not measured");
    expect(table?.textContent).toContain("Adzuna does not publish applicant counts");
  });

  it("treats an unavailable row as unmeasured even if a number rides along", () => {
    const root = renderChart(
      <DivergingBar
        title="Market vs you"
        windowLabel="last 30 days"
        rows={[{ label: "Ghost", value: 9, available: false, reason: "snapshot unavailable" }]}
      />,
    );
    expect(marks(root, "unmeasured")).toHaveLength(1);
    expect(root.querySelector('[data-testid="bar"]')).toBeNull();
    expect(root.textContent).toContain("snapshot unavailable");
  });
});

describe("freshness", () => {
  it("keeps each row's freshness stamp right next to its value", () => {
    const root = renderChart(
      <DivergingBar title="Market vs you" windowLabel="last 30 days" rows={ROWS} />,
    );
    const row = root.querySelector('[data-row="Median salary"]');
    expect(row?.textContent).toContain("data as of 13 Aug 2026");
  });
});

describe("motion", () => {
  it("does not transition bar widths under reduced motion", () => {
    cleanup();
    stubMatchMedia(true);
    const root = renderChart(
      <DivergingBar title="Market vs you" windowLabel="last 30 days" rows={ROWS} />,
    );
    const bar = root.querySelector('[data-testid="bar"]') as HTMLElement;
    expect(bar.style.transition).toBe("");
    expect(bar.style.transform).toBe("");
  });
});
