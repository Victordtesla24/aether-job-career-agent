// @vitest-environment jsdom
/**
 * The one segmented control — B2 round 2.
 *
 * B2's GLOBAL CONTROLS PASS made this component every tab strip in the product
 * (Jobs markets, Applications views, Analytics periods, Approvals filter, the
 * Agents tabs), and it shipped with zero direct coverage: everything asserted
 * about it was asserted through a page.
 *
 * Two things are pinned here.
 *
 * 1. IT CANNOT CLIP. The strip used to be `overflow-x-auto` over `shrink-0`
 *    tabs. Measured in the live layout at 390px, the Jobs market strip needed
 *    379px inside a 358px box, so the third tab ("Saved 0") was sliced at the
 *    right edge with no fade, chevron or "+N" hint — the same defect this round
 *    is closing on the connected-boards rail, on the same page. It now wraps,
 *    so no width and no item count can hide a tab.
 *
 * 2. REFERENCE-PACK RULE 8. The active tab is a border/underline, never a
 *    saturated fill. This is the ruling B2 closed app-wide and the thing a
 *    later "make the active tab pop" edit would quietly undo.
 *
 * Plus the ARIA tabs contract the control claims in its own docblock, which
 * nothing had ever asserted directly.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SegmentedControl from "../SegmentedControl";

const ITEMS = [
  { value: "au" as const, label: "🇦🇺 Australia (Local)", count: 3063 },
  { value: "intl" as const, label: "🌏 International", count: 889 },
  { value: "saved" as const, label: "Saved", count: 0 },
];

function renderControl(value: "au" | "intl" | "saved" = "au", onChange = vi.fn()) {
  render(
    <SegmentedControl
      items={ITEMS}
      value={value}
      onChange={onChange}
      ariaLabel="Market"
      idPrefix="market"
      testId="market-tabs"
    />,
  );
  return onChange;
}

afterEach(cleanup);

describe("the strip cannot clip a tab", () => {
  it("wraps rather than scrolling sideways", () => {
    renderControl();
    const strip = screen.getByTestId("market-tabs");
    expect(strip.className).toMatch(/\bflex-wrap\b/);
    // The geometry that produced the 390px clip.
    expect(strip.className).not.toMatch(/overflow-x-auto|overflow-x-scroll/);
  });

  it("renders every item, including the one that used to fall off the edge", () => {
    renderControl();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.length).toBe(3);
    expect(tabs[2].textContent).toContain("Saved");
    // The count is part of the tab, not a separate thing that can be lost.
    expect(tabs[2].textContent).toContain("0");
  });
});

describe("reference-pack rule 8 — active is a border, not a fill", () => {
  it("underlines the active tab and never paints it with the coral fill", () => {
    renderControl("intl");
    const active = screen.getByRole("tab", { selected: true });
    expect(active.textContent).toContain("International");
    // A 2px coral rule seated on the tablist hairline.
    expect(active.className).toMatch(/after:bg-aether-coral/);
    expect(active.className).toMatch(/after:h-0\.5/);
    // The anti-pattern: a saturated background fill on a navigation control.
    // The lookbehind is load-bearing — `after:bg-aether-coral` (the underline)
    // contains the fill's class name, and matching it would make this assertion
    // pass for the wrong reason.
    expect(active.className).not.toMatch(/(?<!after:)\bbg-aether-coral\b/);
  });

  it("leaves inactive tabs muted and unfilled", () => {
    renderControl("intl");
    const inactive = screen
      .getAllByRole("tab")
      .filter((t) => t.getAttribute("aria-selected") !== "true");
    expect(inactive.length).toBe(2);
    for (const tab of inactive) {
      expect(tab.className).toMatch(/text-aether-muted/);
      expect(tab.className).not.toMatch(/after:bg-aether-coral/);
    }
  });
});

describe("the ARIA tabs contract", () => {
  it("is a single-select tablist with roving tabindex", () => {
    renderControl("au");
    const strip = screen.getByTestId("market-tabs");
    expect(strip.getAttribute("role")).toBe("tablist");
    expect(strip.getAttribute("aria-label")).toBe("Market");

    const tabs = screen.getAllByRole("tab");
    expect(tabs.filter((t) => t.getAttribute("aria-selected") === "true").length).toBe(1);
    expect(tabs.filter((t) => t.getAttribute("tabindex") === "0").length).toBe(1);
    expect(tabs.filter((t) => t.getAttribute("tabindex") === "-1").length).toBe(2);
    // Never `aria-pressed` — that is a toggle-button contract, not single-select.
    for (const tab of tabs) expect(tab.getAttribute("aria-pressed")).toBeNull();
  });

  it("moves selection with the arrow keys and wraps around the ends", () => {
    const onChange = renderControl("au");
    const first = screen.getAllByRole("tab")[0];

    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("intl");

    fireEvent.keyDown(first, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("saved");
  });

  it("reports the clicked value verbatim", () => {
    const onChange = renderControl("au");
    fireEvent.click(screen.getByRole("tab", { name: /Saved/ }));
    expect(onChange).toHaveBeenCalledWith("saved");
  });
});
