// @vitest-environment jsdom
/**
 * THE FIVE HONEST-RENDERING LAWS (S-UI-REBUILD-SPEC §4.2) — the enforcement
 * suite. Every law is pinned twice: once on the pure assertion helper, once
 * through `<ChartFrame>` so a chart cannot render while violating it.
 *
 * C-1 Zero is not a colour
 * C-2 Unmeasured is not zero        (dev-throw when 0 and null mix silently)
 * C-3 The window is part of the chart
 * C-4 Scale is declared
 * C-5 Colour is redundant
 */
import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChartFrame } from "../ChartFrame";
import { ZERO_TICK_WIDTH, barLength, markKind } from "../geometry";
import { ChartLawError, assertChartLaws } from "../laws";
import { renderChart, silenceConsoleError, stubMatchMedia } from "./testUtils";

const OK_FRAME = {
  title: "Test chart",
  windowLabel: "last 50 runs",
  scale: { kind: "linear" } as const,
  data: [{ label: "Found", value: 12 }],
};

function frame(props: Partial<React.ComponentProps<typeof ChartFrame>> = {}) {
  return (
    <ChartFrame {...OK_FRAME} {...props}>
      <div data-testid="plot-body" />
    </ChartFrame>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("C-1 — zero is not a colour", () => {
  it("classifies 0 as its own mark kind, distinct from a value and from null", () => {
    expect(markKind(0)).toBe("zero");
    expect(markKind(12)).toBe("value");
    expect(markKind(null)).toBe("unmeasured");
    expect(markKind(undefined)).toBe("unmeasured");
  });

  it("gives a zero value a 1px tick — never a proportional filled length", () => {
    const zero = barLength({ value: 0, max: 8358, extent: 400, mode: "linear" });
    expect(zero.kind).toBe("zero");
    expect(zero.length).toBe(ZERO_TICK_WIDTH);
    expect(ZERO_TICK_WIDTH).toBe(1);
  });

  it("never returns a zero-length bar for a real value (a 1px tick means zero, only zero)", () => {
    const tiny = barLength({ value: 1, max: 8358, extent: 400, mode: "linear" });
    expect(tiny.kind).toBe("value");
    expect(tiny.length).toBeGreaterThan(ZERO_TICK_WIDTH);
  });

  it("gives an unmeasured value no length at all", () => {
    const none = barLength({ value: null, max: 100, extent: 400, mode: "linear" });
    expect(none.kind).toBe("unmeasured");
    expect(none.length).toBe(0);
  });
});

describe("C-2 — unmeasured is not zero", () => {
  const mixed = [
    { label: "Applied", value: 0 },
    { label: "Interviewed", value: null },
  ];

  it("throws when a series mixes 0 and null without nullMeaning", () => {
    expect(() => assertChartLaws({ ...OK_FRAME, data: mixed })).toThrowError(ChartLawError);
    try {
      assertChartLaws({ ...OK_FRAME, data: mixed });
    } catch (error) {
      expect((error as ChartLawError).law).toBe("C-2");
    }
  });

  it("accepts the same series once nullMeaning explains what null means", () => {
    expect(() =>
      assertChartLaws({ ...OK_FRAME, data: mixed, nullMeaning: "not measured before 12 Aug" }),
    ).not.toThrow();
  });

  it("accepts a series of pure nulls (nothing to confuse zero with)", () => {
    expect(() =>
      assertChartLaws({ ...OK_FRAME, data: [{ label: "Interviewed", value: null }] }),
    ).not.toThrow();
  });

  it("makes ChartFrame itself throw in dev on the ambiguous series", () => {
    const restore = silenceConsoleError();
    expect(() => renderChart(frame({ data: mixed }))).toThrowError(ChartLawError);
    restore();
  });

  it("renders 'not measured' plus the reason in the hidden data table", () => {
    stubMatchMedia(false);
    const root = renderChart(
      frame({
        data: [
          { label: "Applied", value: 0 },
          { label: "Interviewed", value: null, note: "stage not tracked before 12 Aug" },
        ],
        nullMeaning: "stage not tracked before 12 Aug",
      }),
    );
    const table = root.querySelector('[data-testid="chart-data-table"]');
    expect(table?.textContent).toContain("not measured");
    expect(table?.textContent).toContain("stage not tracked before 12 Aug");
    // and zero is still rendered as the number 0, never as "not measured"
    const zeroRow = table?.querySelector('[data-row-mark="zero"]');
    expect(zeroRow?.textContent).toContain("0");
    expect(zeroRow?.textContent).not.toContain("not measured");
  });
});

describe("C-3 — the window is part of the chart", () => {
  it("throws on an empty window label", () => {
    expect(() => assertChartLaws({ ...OK_FRAME, windowLabel: "" })).toThrowError(/C-3/);
  });

  it("throws on a whitespace-only window label", () => {
    expect(() => assertChartLaws({ ...OK_FRAME, windowLabel: "   " })).toThrowError(/C-3/);
  });

  it("makes ChartFrame throw rather than render an unlabelled window", () => {
    const restore = silenceConsoleError();
    expect(() => renderChart(frame({ windowLabel: "" }))).toThrowError(ChartLawError);
    restore();
  });

  it("renders the window label verbatim in the caption", () => {
    stubMatchMedia(false);
    const root = renderChart(
      frame({ windowLabel: "all time — not affected by the period selector" }),
    );
    const caption = root.querySelector("figcaption");
    expect(caption?.textContent).toContain("all time — not affected by the period selector");
  });
});

describe("C-4 — scale is declared", () => {
  it("throws when an axis is truncated without declaring it", () => {
    expect(() =>
      assertChartLaws({ ...OK_FRAME, scale: { kind: "linear", baseline: 40 } }),
    ).toThrowError(/C-4/);
  });

  it("accepts a truncated axis that declares itself", () => {
    expect(() =>
      assertChartLaws({ ...OK_FRAME, scale: { kind: "linear", baseline: 40, truncated: true } }),
    ).not.toThrow();
  });

  it("renders a visible LOG SCALE chip for a log scale", () => {
    stubMatchMedia(false);
    const root = renderChart(frame({ scale: { kind: "log" } }));
    expect(root.querySelector('[data-testid="scale-chip"]')?.textContent).toBe("LOG SCALE");
  });

  it("renders a visible chip for share-of-previous encoding", () => {
    stubMatchMedia(false);
    const root = renderChart(frame({ scale: { kind: "share-of-previous" } }));
    expect(root.querySelector('[data-testid="scale-chip"]')?.textContent).toBe(
      "SHARE OF PREVIOUS STEP",
    );
  });

  it("renders no chip for the default linear-from-zero scale", () => {
    stubMatchMedia(false);
    const root = renderChart(frame());
    expect(root.querySelector('[data-testid="scale-chip"]')).toBeNull();
  });

  it("renders a break glyph stating where a truncated axis starts", () => {
    stubMatchMedia(false);
    const root = renderChart(frame({ scale: { kind: "linear", baseline: 40, truncated: true } }));
    const glyph = root.querySelector('[data-testid="axis-break"]');
    expect(glyph?.textContent).toContain("40");
  });
});

describe("C-5 — colour is redundant", () => {
  it("throws when a coloured datum carries no word", () => {
    expect(() =>
      assertChartLaws({ ...OK_FRAME, data: [{ label: "  ", value: 3 }] }),
    ).toThrowError(/C-5/);
  });

  it("makes ChartFrame throw rather than render an unlabelled datum", () => {
    const restore = silenceConsoleError();
    expect(() => renderChart(frame({ data: [{ label: "", value: 3 }] }))).toThrowError(
      ChartLawError,
    );
    restore();
  });
});

describe("law enforcement in production", () => {
  it("reports loudly instead of throwing, so a violation never white-screens a paying user", () => {
    vi.stubEnv("NODE_ENV", "production");
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => assertChartLaws({ ...OK_FRAME, windowLabel: "" })).not.toThrow();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(String(spy.mock.calls[0]?.[0])).toContain("C-3");
    spy.mockRestore();
  });
});
