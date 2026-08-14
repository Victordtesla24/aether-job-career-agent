// @vitest-environment jsdom
/**
 * D-ι — "It survives 390px. No horizontal page scroll, ever."
 *
 * MEASURED DEFECT (browser, not theory). `<ChartFrame>` renders its
 * accessibility data table as `<table className="sr-only">`. Tailwind's
 * `sr-only` hides an element by giving it `width:1px; height:1px;
 * overflow:hidden; clip:rect(0,0,0,0)` — which works for a `<div>` but NOT for
 * a `<table>`: under the default `table-layout: auto`, a table's used width is
 * its min-content width, so `width:1px` is ignored and the table grows to fit
 * its widest row.
 *
 * A live probe of the built app (Chromium, logged in) measured that table at
 * **1115px wide** on both `/dashboard` and `/dashboard/analytics`, and the page
 * genuinely scrolled sideways: `window.scrollTo(500,0)` moved `window.scrollX`
 * to 123 at a 1600px viewport. Evidence:
 * `uat/reports/evidence/market-perf/s-ui/b1/after/hscroll-probe-*.json`.
 *
 * The fix: the sr-only box must be an element that actually honours
 * `width:1px` + `overflow:hidden` — a wrapper `<div>` — with the table laid out
 * `table-fixed` inside it so it cannot push the wrapper open either.
 *
 * jsdom computes no layout, so this test pins the STRUCTURE that makes the
 * browser behaviour correct; the browser probe above is the measurement.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Funnel } from "../Funnel";

function renderFunnel() {
  const { container } = render(
    <Funnel
      title="Application funnel"
      windowLabel="all time — every stage counted since your first discovery run"
      steps={[
        { label: "Jobs found", value: 8358, note: "A deliberately long note so the hidden table has a wide row to lay out." },
        { label: "Applied", value: 287 },
        { label: "Screened", value: 0 },
      ]}
    />,
  );
  return container;
}

describe("the hidden data table cannot force horizontal page scroll", () => {
  it("puts the sr-only box on a wrapper element, not on the table itself", () => {
    const container = renderFunnel();
    const table = container.querySelector('[data-testid="chart-data-table"]');
    expect(table).not.toBeNull();

    // A `<table>` under auto layout ignores `width:1px`, so `sr-only` must not
    // be the thing holding the table's box — a wrapper has to.
    const wrapper = table!.parentElement;
    expect(wrapper).not.toBeNull();
    expect(wrapper!.className).toMatch(/\bsr-only\b/);
  });

  it("lays the table out fixed so it cannot push its wrapper open", () => {
    const container = renderFunnel();
    const table = container.querySelector('[data-testid="chart-data-table"]') as HTMLElement;
    // `table-fixed` + a 1px width is what makes the column widths stop being
    // derived from content.
    expect(table.className).toMatch(/\btable-fixed\b/);
  });

  it("keeps every value in the table — containment must not cost accessibility", () => {
    const container = renderFunnel();
    const rows = container.querySelectorAll('[data-testid="chart-data-table"] tbody tr');
    expect(rows).toHaveLength(3);
    const text = container.querySelector('[data-testid="chart-data-table"]')!.textContent ?? "";
    expect(text).toMatch(/Jobs found/);
    expect(text).toMatch(/8,?358/);
    expect(text).toMatch(/Screened/);
  });
});
