// @vitest-environment jsdom
/**
 * `<Funnel>` (spec alias `<FunnelBars>`) — the application funnel.
 *
 * The truth problem this component exists to solve: 8,358 → 287 → 0 is
 * unreadable on a linear scale (the 287 bar is 3% of the track and the 0 bar
 * used to render as a filled coloured pill). The kit answers with a
 * quantitatively readable encoding that DECLARES itself (C-4) and a zero that
 * is a 1px tick, never a colour (C-1).
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Funnel } from "../Funnel";
import { HAIRLINE, STATE } from "../tokens";
import { clearMatchMedia, marks, renderChart, stubMatchMedia } from "./testUtils";

const STEPS = [
  { label: "Jobs found", value: 8358 },
  { label: "Applied", value: 287 },
  { label: "Screened", value: 0 },
];

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("readability", () => {
  it("renders one row per step with the label, the numeral and the conversion column", () => {
    const root = renderChart(<Funnel title="Funnel" windowLabel="all time" steps={STEPS} />);
    const rows = root.querySelectorAll('[data-testid="funnel-row"]');
    expect(rows).toHaveLength(3);
    expect(rows[1]?.textContent).toContain("Applied");
    expect(rows[1]?.textContent).toContain("287");
    // 287 / 8358 = 3.4% of the previous step
    expect(rows[1]?.textContent).toContain("3.4%");
  });

  it("puts the numeral outside the fill, in its own tabular-nums column", () => {
    const root = renderChart(<Funnel title="Funnel" windowLabel="all time" steps={STEPS} />);
    const numeral = root.querySelectorAll('[data-testid="funnel-value"]')[1];
    expect(numeral?.className).toContain("tabular-nums");
    expect(numeral?.closest('[data-testid="funnel-track"]')).toBeNull();
  });

  it("keeps a small-but-real step visible in share-of-previous mode and says so", () => {
    const root = renderChart(
      <Funnel title="Funnel" windowLabel="all time" steps={STEPS} mode="share-of-previous" />,
    );
    expect(root.querySelector('[data-testid="scale-chip"]')?.textContent).toBe(
      "SHARE OF PREVIOUS STEP",
    );
    const fills = root.querySelectorAll('[data-testid="funnel-fill"]');
    // first step is the reference (100%), second is 3.4% OF THE PREVIOUS step,
    // which is a legible fraction rather than 3% of the whole track.
    expect(fills[0]?.getAttribute("style")).toContain("width: 100%");
    const secondWidth = Number(
      /width:\s*([\d.]+)%/.exec(fills[1]?.getAttribute("style") ?? "")?.[1] ?? "0",
    );
    expect(secondWidth).toBeGreaterThan(3);
    expect(secondWidth).toBeLessThan(4);
  });

  it("declares a log scale with a visible chip and never silently log-scales", () => {
    const linear = renderChart(<Funnel title="Funnel" windowLabel="all time" steps={STEPS} />);
    expect(linear.querySelector('[data-testid="scale-chip"]')).toBeNull();
    cleanup();
    const log = renderChart(
      <Funnel title="Funnel" windowLabel="all time" steps={STEPS} mode="log" />,
    );
    expect(log.querySelector('[data-testid="scale-chip"]')?.textContent).toBe("LOG SCALE");
  });
});

describe("C-1 — a zero step", () => {
  it("draws a 1px hairline tick, not a filled coloured bar", () => {
    const root = renderChart(<Funnel title="Funnel" windowLabel="all time" steps={STEPS} />);
    const zero = marks(root, "zero");
    expect(zero).toHaveLength(1);
    const tick = zero[0] as HTMLElement;
    expect(tick.style.width).toBe("1px");
    expect(tick.style.backgroundColor).toBe("rgba(255, 255, 255, 0.07)");
    expect(HAIRLINE).toBe("rgba(255,255,255,0.07)");
    // the zero row has no series-coloured fill at all
    const zeroRow = tick.closest('[data-testid="funnel-row"]');
    expect(zeroRow?.querySelector('[data-testid="funnel-fill"]')).toBeNull();
  });

  it("renders the zero numeral in state-neutral, never in a series colour", () => {
    const root = renderChart(<Funnel title="Funnel" windowLabel="all time" steps={STEPS} />);
    const numeral = root.querySelectorAll('[data-testid="funnel-value"]')[2] as HTMLElement;
    expect(numeral.textContent).toBe("0");
    expect(numeral.dataset.tone).toBe("neutral");
    expect(numeral.style.color).toBe("rgb(139, 139, 163)");
    expect(STATE.neutral).toBe("#8B8BA3");
  });

  it("shows a dash, not 0%, for the conversion into a zero-denominator step", () => {
    const root = renderChart(
      <Funnel
        title="Funnel"
        windowLabel="all time"
        steps={[
          { label: "Screened", value: 0 },
          { label: "Offered", value: 0 },
        ]}
      />,
    );
    const conversions = root.querySelectorAll('[data-testid="funnel-conversion"]');
    expect(conversions[1]?.textContent).toBe("—");
  });
});

describe("C-2 — an unmeasured step", () => {
  const withNull = [
    { label: "Jobs found", value: 8358 },
    { label: "Screened", value: 0 },
    { label: "Offered", value: null, note: "offer stage not tracked before 12 Aug" },
  ];

  it("renders an em dash instead of a bar, and never a zero-length bar", () => {
    const root = renderChart(
      <Funnel
        title="Funnel"
        windowLabel="all time"
        steps={withNull}
        nullMeaning="offer stage not tracked before 12 Aug"
      />,
    );
    const unmeasured = marks(root, "unmeasured");
    expect(unmeasured).toHaveLength(1);
    expect(unmeasured[0]?.textContent).toBe("—");
    expect((unmeasured[0] as HTMLElement).dataset.tone).toBe("neutral");
  });

  it("is textually distinguishable from the zero step in the data table", () => {
    const root = renderChart(
      <Funnel
        title="Funnel"
        windowLabel="all time"
        steps={withNull}
        nullMeaning="offer stage not tracked before 12 Aug"
      />,
    );
    const table = root.querySelector('[data-testid="chart-data-table"]');
    expect(table?.textContent).toContain("not measured");
    expect(table?.textContent).toContain("offer stage not tracked before 12 Aug");
  });
});

describe("bounds and empty state", () => {
  it("caps the rendered rows and says how many were withheld", () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ label: `Step ${i}`, value: 100 - i }));
    const root = renderChart(
      <Funnel title="Funnel" windowLabel="all time" steps={many} maxRows={8} />,
    );
    expect(root.querySelectorAll('[data-testid="funnel-row"]')).toHaveLength(8);
    expect(root.textContent).toContain("4 more");
  });

  it("draws a designed empty state, never a bare 'No data'", () => {
    const root = renderChart(<Funnel title="Funnel" windowLabel="all time" steps={[]} />);
    const empty = root.querySelector('[data-testid="chart-empty"]');
    expect(empty).not.toBeNull();
    expect(empty?.textContent).not.toBe("No data");
    expect(empty?.textContent?.length ?? 0).toBeGreaterThan(10);
  });
});

describe("motion", () => {
  it("does not transition bar widths when the reader asked for reduced motion", () => {
    cleanup();
    stubMatchMedia(true);
    const root = renderChart(<Funnel title="Funnel" windowLabel="all time" steps={STEPS} />);
    expect(root.getAttribute("data-motion")).toBe("off");
    const fill = root.querySelector('[data-testid="funnel-fill"]') as HTMLElement;
    expect(fill.style.transition).toBe("");
    // and the bar is at its final geometry immediately — no "grow from 0" frame
    expect(fill.style.transform).toBe("");
    expect(fill.style.width).toBe("100%");
  });
});
