// @vitest-environment jsdom
/**
 * MON-018 / U-UI — TOOLTIP-CLIP-BOTTOM-01.
 *
 * Live audit: hovering the info icon on the "Applied→Screened" stage
 * tile at 1440x900 opened the MetricTooltip popover at
 * y=828..907.6 — 7.6px past the 900px viewport bottom — because the
 * popover has no logic to flip above the trigger when there isn't enough
 * room below (components/MetricTooltip.tsx always renders at a fixed
 * `top-6`, unconditionally). Screenshot:
 * uat/reports/evidence/agents-uplift/u-ui-audit/dashboard_analytics/
 * dashboard_analytics__tooltip-10__hover.png (visibly cut off).
 *
 * jsdom does not compute real layout, so `getBoundingClientRect` is mocked
 * on the trigger to simulate "insufficient room below" (per the audit's own
 * note that geometry itself isn't testable in jsdom — this pins the
 * FIXABLE behavior instead): when the trigger's measured position plus the
 * popover's height would overflow `window.innerHeight`, the popover must
 * flip to render ABOVE the trigger instead of below.
 *
 * Contract pinned here (data-attribute rather than a specific Tailwind
 * class list, so the fixer is free to choose the exact CSS as long as the
 * component exposes which side it actually placed the popover on):
 *   `data-testid="metric-tooltip-popover"` gains `data-placement="top"` when
 *   flipped, vs. the default `data-placement="bottom"` when there's room.
 * This does not exist in the component today — every assertion below fails
 * because there is no placement logic (and no `data-placement` attribute)
 * at all yet.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MetricTooltip from "../components/MetricTooltip";

const ORIGINAL_INNER_HEIGHT = window.innerHeight;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    value: ORIGINAL_INNER_HEIGHT,
  });
});

describe("MetricTooltip flip-on-overflow (TOOLTIP-CLIP-BOTTOM-01)", () => {
  it("defaults to placement=bottom when there is ample room below the trigger", () => {
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
    render(
      <MetricTooltip
        label="Applied→Screened"
        value="42%"
        tooltip="Share of applications that reached the screened stage."
      />,
    );
    const trigger = screen.getByRole("button", { name: /applied→screened/i });
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      top: 100,
      bottom: 116,
      left: 200,
      right: 216,
      width: 16,
      height: 16,
      x: 200,
      y: 100,
      toJSON() {
        return this;
      },
    } as DOMRect);

    fireEvent.mouseEnter(trigger);
    const popover = screen.getByTestId("metric-tooltip-popover");
    expect(popover.getAttribute("data-placement")).toBe("bottom");
  });

  it("flips to placement=top when opening below would overflow the viewport bottom (same defect class as the live TOOLTIP-CLIP-BOTTOM-01 measurement: trigger at y=804 on a 900px viewport, popover bottom landed at 907.6 — 7.6px past the fold)", () => {
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
    render(
      <MetricTooltip
        label="Applied→Screened"
        value="42%"
        tooltip="Share of applications that reached the screened stage."
      />,
    );
    const trigger = screen.getByRole("button", { name: /applied→screened/i });
    // jsdom can't measure the popover's real rendered height, so — rather
    // than guess the fixer's internal gap/margin constant — this pins an
    // UNAMBIGUOUS case: the trigger sits 2px from the viewport bottom, so
    // *any* popover with positive height opening downward overflows,
    // regardless of exactly how "insufficient room" gets computed.
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      top: 890,
      bottom: 898,
      left: 611.25,
      right: 627.25,
      width: 16,
      height: 8,
      x: 611.25,
      y: 890,
      toJSON() {
        return this;
      },
    } as DOMRect);

    fireEvent.mouseEnter(trigger);
    const popover = screen.getByTestId("metric-tooltip-popover");
    expect(popover.getAttribute("data-placement")).toBe("top");
  });
});
