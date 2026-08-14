// @vitest-environment jsdom
/**
 * `<Spark>` — the kit's micro mark, and the one component whose scale makes it
 * tempting to skip the laws. This file is the reason it does not.
 *
 * A 30px-tall figure inside a stat tile has room for exactly one thing: the
 * shape. So the temptations are specific — draw an unmeasured column as a very
 * short bar (it "looks fine" at 30px), draw two points as a trend, or leave the
 * window off because there is nowhere to print it. Each is pinned closed here.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Spark } from "../Spark";
import { ChartLawError } from "../laws";
import { clearMatchMedia, silenceConsoleError, stubMatchMedia } from "./testUtils";

beforeEach(() => stubMatchMedia(false));
afterEach(() => {
  cleanup();
  clearMatchMedia();
});

function renderSpark(ui: React.ReactElement): HTMLElement {
  const { container } = render(ui);
  const spark = container.querySelector('[data-testid="spark"]');
  if (!spark) throw new Error("spark did not render");
  return spark as HTMLElement;
}

describe("C-3 — the window is part of the mark", () => {
  it("throws in dev when a spark is drawn without stating its sample window", () => {
    const restore = silenceConsoleError();
    expect(() =>
      render(
        <Spark
          title="Pipeline"
          windowLabel=""
          kind="bars"
          data={[{ label: "Applied", value: 3 }]}
        />,
      ),
    ).toThrow(ChartLawError);
    restore();
  });

  it("carries the window into the accessible name and onto the element", () => {
    const spark = renderSpark(
      <Spark
        title="Pipeline"
        windowLabel="the selected period (7d)"
        kind="bars"
        data={[{ label: "Applied", value: 3 }]}
      />,
    );
    expect(spark.getAttribute("aria-label")).toContain("Sample window: the selected period (7d).");
    expect(spark.getAttribute("data-window")).toBe("the selected period (7d)");
  });
});

describe("C-5 — every mark has a word", () => {
  it("throws in dev when a datum has no label", () => {
    const restore = silenceConsoleError();
    expect(() =>
      render(
        <Spark title="Pipeline" windowLabel="all time" kind="bars" data={[{ label: "", value: 1 }]} />,
      ),
    ).toThrow(ChartLawError);
    restore();
  });
});

describe("C-1 / C-2 — zero, unmeasured and small are three different things", () => {
  const MIXED = [
    { label: "Applied", value: 40 },
    { label: "Screened", value: 0 },
    { label: "Interviewed", value: null },
  ];

  it("throws when a series mixes a real 0 with a null and does not say what the null means", () => {
    const restore = silenceConsoleError();
    expect(() =>
      render(<Spark title="Funnel" windowLabel="all time" kind="bars" data={MIXED} />),
    ).toThrow(ChartLawError);
    restore();
  });

  it("draws a zero and an unmeasured column as distinguishable non-series marks", () => {
    const spark = renderSpark(
      <Spark
        title="Funnel"
        windowLabel="all time"
        kind="bars"
        data={MIXED}
        nullMeaning="this stage was never counted"
      />,
    );
    const bars = Array.from(spark.querySelectorAll('[data-testid="spark-bar"]')) as HTMLElement[];
    expect(bars.map((b) => b.getAttribute("data-mark"))).toEqual(["value", "zero", "unmeasured"]);
    expect(bars[1].getAttribute("data-tone")).toBe("neutral");
    expect(bars[2].getAttribute("data-tone")).toBe("neutral");
    // The unmeasured column is a dotted stub — never a short solid bar that
    // would read as a small measured value.
    expect(bars[2].style.borderTop).toContain("dotted");
    expect(bars[2].getAttribute("title")).toContain("not measured");
  });
});

describe("the line refuses to invent a trend", () => {
  it("draws nothing and says why below three measured points", () => {
    const spark = renderSpark(
      <Spark
        title="Conversion"
        windowLabel="all-time"
        kind="line"
        data={[
          { label: "w1", value: 3 },
          { label: "w2", value: 5 },
        ]}
      />,
    );
    expect(spark.getAttribute("data-spark-state")).toBe("too-few-points");
    expect(spark.querySelector('[data-testid="spark-path"]')).toBeNull();
    expect(spark.textContent).toContain("fewer than 3 measured points");
  });

  it("draws the path once there are three", () => {
    const spark = renderSpark(
      <Spark
        title="Conversion"
        windowLabel="all-time"
        kind="line"
        data={[
          { label: "w1", value: 3 },
          { label: "w2", value: 5 },
          { label: "w3", value: 4 },
        ]}
      />,
    );
    expect(spark.querySelector('[data-testid="spark-path"]')).not.toBeNull();
  });
});

describe("the bullet", () => {
  it("draws the measure against a labelled target tick", () => {
    const spark = renderSpark(
      <Spark
        title="Interview conversion"
        windowLabel="all time"
        kind="bullet"
        data={[{ label: "Interview conversion", value: 5 }]}
        target={{ value: 20, label: "20% target" }}
      />,
    );
    expect(spark.querySelector('[data-testid="spark-target"]')).not.toBeNull();
    expect(spark.querySelector('[data-testid="spark-target-label"]')?.textContent).toBe(
      "20% target",
    );
    expect(spark.getAttribute("aria-label")).toContain("20% target");
  });

  it("renders an unmeasured measure as the dash, never as a zero-length bar", () => {
    const spark = renderSpark(
      <Spark
        title="Interview conversion"
        windowLabel="all time"
        kind="bullet"
        data={[{ label: "Interview conversion", value: null, note: "conversion has not loaded" }]}
        target={{ value: 20, label: "20% target" }}
      />,
    );
    expect(spark.querySelector('[data-mark="unmeasured"]')).not.toBeNull();
    expect(spark.querySelector('[data-mark="value"]')).toBeNull();
  });
});

describe("reduced motion", () => {
  it("renders marks at their final size with no transition when motion is reduced", () => {
    clearMatchMedia();
    stubMatchMedia(true);
    const spark = renderSpark(
      <Spark
        title="Pipeline"
        windowLabel="all time"
        kind="bars"
        data={[
          { label: "Applied", value: 4 },
          { label: "Screened", value: 2 },
        ]}
      />,
    );
    const bar = spark.querySelector('[data-testid="spark-bar"]') as HTMLElement;
    expect(bar.style.transform).toBe("");
    expect(bar.style.transition).toBe("");
  });
});
