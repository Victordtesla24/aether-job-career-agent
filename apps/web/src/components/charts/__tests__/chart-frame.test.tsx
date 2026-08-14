// @vitest-environment jsdom
/**
 * `<ChartFrame>` — the shared shell every chart in the kit renders inside.
 * It owns: the law assertions (see laws.test.tsx), the accessible summary,
 * the hidden data table, the window-label caption, the scale chip, and the
 * "no border / no background / no legend clutter" chrome (reference-pack
 * rule 5).
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ChartFrame } from "../ChartFrame";
import { DEFAULT_PLOT_WIDTH } from "../geometry";
import { clearMatchMedia, renderChart, stubMatchMedia } from "./testUtils";

const BASE = {
  title: "Application funnel",
  windowLabel: "all time — not affected by the period selector",
  scale: { kind: "linear" } as const,
  data: [
    { label: "Jobs found", value: 8358 },
    { label: "Applied", value: 287 },
    { label: "Screened", value: 0 },
  ],
};

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("chrome", () => {
  it("renders the title once, as the chart's own heading", () => {
    const root = renderChart(
      <ChartFrame {...BASE}>
        <div data-testid="plot-body" />
      </ChartFrame>,
    );
    const titles = root.querySelectorAll('[data-testid="chart-title"]');
    expect(titles).toHaveLength(1);
    expect(titles[0]?.textContent).toBe("Application funnel");
  });

  it("carries no border and no background — gridlines and axis labels do the framing", () => {
    const root = renderChart(
      <ChartFrame {...BASE}>
        <div />
      </ChartFrame>,
    );
    const className = root.getAttribute("class") ?? "";
    expect(className).not.toMatch(/\bborder(-|\b)/);
    expect(className).not.toMatch(/\bbg-/);
    expect(root.style.background).toBe("");
  });

  it("exposes the plot as a single labelled image to assistive tech", () => {
    const root = renderChart(
      <ChartFrame {...BASE}>
        <div />
      </ChartFrame>,
    );
    const plot = root.querySelector('[role="img"]');
    const label = plot?.getAttribute("aria-label") ?? "";
    expect(label).toContain("Application funnel");
    expect(label).toContain("all time — not affected by the period selector");
  });

  it("gives function children an svg with a responsive viewBox", () => {
    const root = renderChart(
      <ChartFrame {...BASE} height={220}>
        {(geom) => <rect data-testid="probe" width={geom.plot.width} height={geom.plot.height} />}
      </ChartFrame>,
    );
    const svg = root.querySelector("svg");
    expect(svg?.getAttribute("viewBox")).toBe(`0 0 ${DEFAULT_PLOT_WIDTH} 220`);
    expect(svg?.getAttribute("width")).toBe("100%");
    expect(root.querySelector('[data-testid="probe"]')).not.toBeNull();
  });

  it("renders node children directly for the DOM-based charts (funnel, rows, grid)", () => {
    const root = renderChart(
      <ChartFrame {...BASE}>
        <div data-testid="dom-plot">rows</div>
      </ChartFrame>,
    );
    expect(root.querySelector("svg")).toBeNull();
    expect(root.querySelector('[data-testid="dom-plot"]')).not.toBeNull();
  });
});

describe("hidden data table (the chart's text equivalent)", () => {
  it("lists every datum with its label and value", () => {
    const root = renderChart(
      <ChartFrame {...BASE}>
        <div />
      </ChartFrame>,
    );
    const rows = root.querySelectorAll('[data-testid="chart-data-table"] tbody tr');
    expect(rows).toHaveLength(3);
    expect(rows[0]?.textContent).toContain("Jobs found");
    expect(rows[0]?.textContent).toContain("8,358");
    expect(rows[2]?.textContent).toContain("Screened");
    expect(rows[2]?.textContent).toContain("0");
  });

  it("is visually hidden but present in the DOM", () => {
    const root = renderChart(
      <ChartFrame {...BASE}>
        <div />
      </ChartFrame>,
    );
    const table = root.querySelector('[data-testid="chart-data-table"]');
    expect(table).not.toBeNull();
    expect(table?.className).toContain("sr-only");
  });

  it("summarises instead of emitting thousands of rows for a large series", () => {
    const many = Array.from({ length: 2500 }, (_, i) => ({ label: `t${i}`, value: i }));
    const root = renderChart(
      <ChartFrame {...BASE} data={many} windowLabel="2,500 samples">
        <div />
      </ChartFrame>,
    );
    const table = root.querySelector('[data-testid="chart-data-table"]');
    const rows = table?.querySelectorAll("tbody tr") ?? [];
    expect(rows.length).toBeLessThan(20);
    expect(table?.textContent).toContain("2,500");
    expect(table?.textContent?.toLowerCase()).toContain("summarised");
  });
});

describe("footnote slot", () => {
  it("renders the window label and any extra footnote together in the caption", () => {
    const root = renderChart(
      <ChartFrame {...BASE} footnote="Excludes 4 jobs with no posting date.">
        <div />
      </ChartFrame>,
    );
    const caption = root.querySelector("figcaption");
    expect(caption?.textContent).toContain("all time — not affected by the period selector");
    expect(caption?.textContent).toContain("Excludes 4 jobs with no posting date.");
  });

  it("states what null means whenever the caller declared it", () => {
    const root = renderChart(
      <ChartFrame
        {...BASE}
        data={[
          { label: "Applied", value: 0 },
          { label: "Screened", value: null },
        ]}
        nullMeaning="stage not tracked before 12 Aug"
      >
        <div />
      </ChartFrame>,
    );
    expect(root.querySelector("figcaption")?.textContent).toContain(
      "stage not tracked before 12 Aug",
    );
  });
});

describe("motion", () => {
  it("marks motion on when the reader has not asked for reduced motion", () => {
    const root = renderChart(
      <ChartFrame {...BASE}>
        <div />
      </ChartFrame>,
    );
    expect(root.getAttribute("data-motion")).toBe("on");
  });

  it("marks motion off under prefers-reduced-motion", () => {
    cleanup();
    stubMatchMedia(true);
    const root = renderChart(
      <ChartFrame {...BASE}>
        <div />
      </ChartFrame>,
    );
    expect(root.getAttribute("data-motion")).toBe("off");
  });

  it("treats a missing matchMedia (SSR / old jsdom) as no motion preference, not a crash", () => {
    cleanup();
    clearMatchMedia();
    const root = renderChart(
      <ChartFrame {...BASE}>
        <div />
      </ChartFrame>,
    );
    expect(root.getAttribute("data-motion")).toBe("on");
  });
});
