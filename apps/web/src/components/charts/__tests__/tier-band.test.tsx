// @vitest-environment jsdom
/**
 * `<TierBand>` — the rigor policy drawn as itself.
 *
 * The design question this file pins: WHAT is the x-axis allowed to be? The
 * tier points are irregular in time (they exist only where the tier or its
 * inputs changed), so spacing them by date would draw a continuity nobody
 * measured. The band therefore partitions by RUNS — a quantity that exists at
 * every point and is what "how long did the agents obey this tier" actually
 * means — and leaves the dates as labels.
 *
 * It also pins the two things a picture of a policy must never do: relabel a
 * tier it does not recognise, and carry a tier's meaning in colour alone.
 */
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { TierBand } from "../TierBand";
import { clearMatchMedia, renderChart, stubMatchMedia } from "./testUtils";

const TIER_LABELS = {
  standard: "Standard rigor",
  heightened: "Heightened rigor",
  insufficient_data: "Insufficient data",
};

const POINTS = [
  {
    at: "2026-08-01T00:00:00Z",
    tier: "insufficient_data",
    runs: 2,
    conversionRate: 0,
    sampleSize: 2,
    dimensionsBelowFloor: [],
  },
  {
    at: "2026-08-10T00:00:00Z",
    tier: "heightened",
    runs: 18,
    conversionRate: 5,
    sampleSize: 40,
    dimensionsBelowFloor: ["cultureFit"],
  },
];

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

describe("the band", () => {
  it("draws one segment per recorded tier point", () => {
    const root = renderChart(
      <TierBand
        title="Tier bands"
        windowLabel="all-time"
        points={POINTS}
        target={20}
        tierLabels={TIER_LABELS}
      />,
    );
    const segments = root.querySelectorAll('[data-testid="tier-band-segment"]');
    expect(segments).toHaveLength(2);
    expect(segments[0].getAttribute("data-tier")).toBe("insufficient_data");
    expect(segments[1].getAttribute("data-tier")).toBe("heightened");
  });

  it("sizes each segment by the RUNS that obeyed it, not by elapsed time", () => {
    const root = renderChart(
      <TierBand
        title="Tier bands"
        windowLabel="all-time"
        points={POINTS}
        target={20}
        tierLabels={TIER_LABELS}
      />,
    );
    const segments = Array.from(
      root.querySelectorAll('[data-testid="tier-band-segment"]'),
    ) as HTMLElement[];
    // 2 runs and 18 runs out of 20 → 10% and 90%.
    expect(Number.parseFloat(segments[0].style.width)).toBeCloseTo(10, 5);
    expect(Number.parseFloat(segments[1].style.width)).toBeCloseTo(90, 5);
  });

  it("prints the run count under each segment, so the width is provable", () => {
    const root = renderChart(
      <TierBand
        title="Tier bands"
        windowLabel="all-time"
        points={POINTS}
        target={20}
        tierLabels={TIER_LABELS}
      />,
    );
    expect(root.querySelector('[data-testid="tier-band-runs"]')?.textContent).toBe("218");
  });

  it("falls back to an equal partition when no point recorded a run, rather than collapsing every segment to zero width", () => {
    const root = renderChart(
      <TierBand
        title="Tier bands"
        windowLabel="all-time"
        points={POINTS.map((p) => ({ ...p, runs: 0 }))}
        target={20}
        tierLabels={TIER_LABELS}
      />,
    );
    const segments = Array.from(
      root.querySelectorAll('[data-testid="tier-band-segment"]'),
    ) as HTMLElement[];
    expect(Number.parseFloat(segments[0].style.width)).toBeCloseTo(50, 5);
  });
});

describe("C-5 — a tier's meaning is a word", () => {
  it("names every tier in its segment and in the legend", () => {
    const root = renderChart(
      <TierBand
        title="Tier bands"
        windowLabel="all-time"
        points={POINTS}
        target={20}
        tierLabels={TIER_LABELS}
      />,
    );
    const segments = root.querySelectorAll('[data-testid="tier-band-segment"]');
    expect(segments[1].textContent).toContain("Heightened rigor");
    const legend = root.querySelector('[data-testid="tier-band-legend"]');
    expect(legend?.textContent).toContain("Insufficient data");
    expect(legend?.textContent).toContain("Heightened rigor");
    // The target line is in the legend too — a dashed rule with no word is a
    // rule nobody can read.
    expect(legend?.textContent).toContain("20% interview-conversion target");
  });

  it("renders an unrecognised tier key verbatim rather than silently relabelling it", () => {
    const root = renderChart(
      <TierBand
        title="Tier bands"
        windowLabel="all-time"
        points={[{ at: null, tier: "experimental", runs: 3, conversionRate: 1, sampleSize: 4 }]}
        target={20}
        tierLabels={TIER_LABELS}
      />,
    );
    expect(root.querySelector('[data-testid="tier-band-segment"]')?.textContent).toContain(
      "experimental",
    );
  });
});

describe("the metric the policy responds to", () => {
  it("draws one conversion mark per point, with a real zero as a hairline rather than a bar", () => {
    const root = renderChart(
      <TierBand
        title="Tier bands"
        windowLabel="all-time"
        points={POINTS}
        target={20}
        tierLabels={TIER_LABELS}
      />,
    );
    const bars = Array.from(
      root.querySelectorAll('[data-testid="tier-band-metric-bar"]'),
    ) as HTMLElement[];
    expect(bars).toHaveLength(2);
    expect(bars[0].getAttribute("data-mark")).toBe("zero");
    expect(bars[0].style.height).toBe("1px");
    expect(bars[1].getAttribute("data-mark")).toBe("value");
  });
});

describe("the text equivalent", () => {
  it("carries each point's tier, runs, conversion, sample size and floor breaches into the hidden table", () => {
    const root = renderChart(
      <TierBand
        title="Tier bands"
        windowLabel="all-time"
        points={POINTS}
        target={20}
        tierLabels={TIER_LABELS}
      />,
    );
    const table = root.querySelector('[data-testid="chart-data-table"]');
    expect(table?.textContent).toContain("Heightened rigor");
    expect(table?.textContent).toContain("18 runs");
    expect(table?.textContent).toContain("interview conversion 5% of 40 submissions");
    expect(table?.textContent).toContain("cultureFit");
  });
});

describe("the empty state", () => {
  it("states the server's own reason instead of drawing an empty band", () => {
    const root = renderChart(
      <TierBand
        title="Tier bands"
        windowLabel="all-time"
        points={[]}
        target={20}
        tierLabels={TIER_LABELS}
        emptyMessage="no agent run has recorded a rigor policy yet"
        emptyHint="12 earlier runs predate this instrumentation."
      />,
    );
    expect(root.querySelector('[data-testid="chart-empty"]')?.textContent).toContain(
      "no agent run has recorded a rigor policy yet",
    );
    expect(root.querySelectorAll('[data-testid="tier-band-segment"]')).toHaveLength(0);
  });
});
