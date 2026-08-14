// @vitest-environment jsdom
/**
 * S-UI B2 — `<VirtualList>`.
 *
 * The mandate on this component is narrow and absolute: virtualization must not
 * break keyboard navigation or screen-reader row semantics. Both are asserted
 * here against a list that is GENUINELY windowed — jsdom has no layout engine,
 * so this file installs a `ResizeObserver` and fixed element rects to give the
 * virtualizer a real 400px viewport over 100px rows. Without that rig the
 * component falls back to rendering everything (see the last describe block),
 * and neither requirement would actually be exercised.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import VirtualList, { canVirtualize } from "../VirtualList";

const ROW_H = 100;
const VIEWPORT_H = 400;
const TOTAL = 500;

const ITEMS = Array.from({ length: TOTAL }, (_, i) => ({ id: `row-${i}`, label: `Row ${i}` }));

/**
 * Install the minimum layout the virtualizer needs, then remove it after.
 *
 * `@tanstack/virtual-core` sizes the viewport from `offsetWidth`/`offsetHeight`
 * and measures rows with `getBoundingClientRect()` — jsdom returns 0 for all
 * three, which is precisely why the component falls back to a full render there.
 * Supplying them is what turns this file into a genuine windowing test.
 */
function installLayoutRig() {
  const realRO = window.ResizeObserver;
  const realRect = Element.prototype.getBoundingClientRect;
  const realOffsetH = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetHeight");
  const realOffsetW = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth");

  class RO {
    constructor(private cb: ResizeObserverCallback) {}
    observe(target: Element) {
      // One synchronous delivery is enough: the viewport never resizes here.
      this.cb(
        [{ target, contentRect: target.getBoundingClientRect() } as unknown as ResizeObserverEntry],
        this as unknown as ResizeObserver,
      );
    }
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = RO as unknown as typeof ResizeObserver;

  const isRow = (el: Element) => (el as HTMLElement).dataset?.rowIndex != null;

  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return isRow(this) ? ROW_H : VIEWPORT_H;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get() {
      return 300;
    },
  });

  Element.prototype.getBoundingClientRect = function getRect(this: Element) {
    if (isRow(this)) {
      const top = Number((this as HTMLElement).dataset.rowIndex) * ROW_H;
      return { x: 0, y: top, top, left: 0, right: 300, bottom: top + ROW_H, width: 300, height: ROW_H, toJSON: () => ({}) } as DOMRect;
    }
    return { x: 0, y: 0, top: 0, left: 0, right: 300, bottom: VIEWPORT_H, width: 300, height: VIEWPORT_H, toJSON: () => ({}) } as DOMRect;
  };

  return () => {
    window.ResizeObserver = realRO;
    Element.prototype.getBoundingClientRect = realRect;
    if (realOffsetH) Object.defineProperty(HTMLElement.prototype, "offsetHeight", realOffsetH);
    if (realOffsetW) Object.defineProperty(HTMLElement.prototype, "offsetWidth", realOffsetW);
  };
}

function renderList(props: Partial<React.ComponentProps<typeof VirtualList<(typeof ITEMS)[number]>>> = {}) {
  const onActivate = vi.fn();
  render(
    <VirtualList
      items={ITEMS}
      getKey={(it) => it.id}
      estimateSize={ROW_H}
      height={VIEWPORT_H}
      ariaLabel="Discovered jobs"
      testId="vlist"
      onActivate={onActivate}
      {...props}
    >
      {(item, index) => (
        <button type="button" data-testid="row" data-label={item.label}>
          {item.label} @ {index}
        </button>
      )}
    </VirtualList>,
  );
  return { onActivate };
}

describe("VirtualList — windowed (real layout rig)", () => {
  let teardown: () => void;

  beforeEach(() => {
    teardown = installLayoutRig();
  });

  afterEach(() => {
    cleanup();
    teardown();
  });

  it("windows the list: far fewer nodes than items", async () => {
    renderList();
    const viewport = await screen.findByTestId("vlist");
    // The effect that turns windowing on has run.
    expect(viewport.getAttribute("data-windowed")).toBe("true");

    const rows = screen.getAllByTestId("row");
    expect(rows.length).toBeGreaterThan(0);
    // 400px viewport / 100px rows = 4 visible + overscan on both edges. The
    // exact number is the virtualizer's business; that it is nothing like 500
    // is the point.
    expect(rows.length).toBeLessThan(40);
    expect(rows.length).toBeLessThan(TOTAL);
  });

  it("tells a screen reader the TRUE list size and row position, not the window's", () => {
    renderList();
    const listitems = document.querySelectorAll('[role="listitem"]');
    expect(listitems.length).toBeGreaterThan(0);
    expect(listitems.length).toBeLessThan(TOTAL);

    for (const el of Array.from(listitems)) {
      // Every rendered row claims the size of the WHOLE list…
      expect(el.getAttribute("aria-setsize")).toBe(String(TOTAL));
      // …and its own true 1-based position within it.
      const index = Number((el as HTMLElement).dataset.rowIndex);
      expect(el.getAttribute("aria-posinset")).toBe(String(index + 1));
    }

    // The container is still a list to assistive tech.
    const list = screen.getByRole("list", { name: "Discovered jobs" });
    expect(list).not.toBeNull();
  });

  it("ArrowDown walks past the end of the rendered window: the next row is mounted and focused", () => {
    const { onActivate } = renderList();

    const rowsBefore = screen.getAllByTestId("row").length;
    const lastRendered = Array.from(document.querySelectorAll("[data-row-index]")).at(-1) as HTMLElement;
    const lastIndex = Number(lastRendered.dataset.rowIndex);
    expect(lastIndex).toBeLessThan(TOTAL - 1); // there IS a row beyond the window

    lastRendered.focus();
    fireEvent.keyDown(lastRendered, { key: "ArrowDown" });

    // The row past the window boundary now exists…
    const next = document.querySelector<HTMLElement>(`[data-row-index="${lastIndex + 1}"]`);
    expect(next).not.toBeNull();
    // …carries focus…
    expect(document.activeElement).toBe(next);
    // …and the owner was told, so page selection can follow the keyboard.
    expect(onActivate).toHaveBeenCalledWith(lastIndex + 1);
    // Still windowed — walking one row did not unspool the list.
    expect(screen.getAllByTestId("row").length).toBeLessThan(rowsBefore + 10);
  });

  it("End jumps to the final row and focuses it; Home comes back", () => {
    const { onActivate } = renderList();
    const first = document.querySelector<HTMLElement>('[data-row-index="0"]')!;

    fireEvent.keyDown(first, { key: "End" });
    expect(onActivate).toHaveBeenLastCalledWith(TOTAL - 1);
    const last = document.querySelector<HTMLElement>(`[data-row-index="${TOTAL - 1}"]`);
    expect(last).not.toBeNull();
    expect(document.activeElement).toBe(last);

    fireEvent.keyDown(last!, { key: "Home" });
    expect(onActivate).toHaveBeenLastCalledWith(0);
    expect(document.activeElement).toBe(document.querySelector('[data-row-index="0"]'));
  });

  it("spaces rows with PADDING on the measured wrapper, never a collapsing margin", () => {
    // Regression guard for a defect found in this component's own first cut.
    // `measureElement` reads `getBoundingClientRect()`, which excludes margin —
    // and a card's `margin-bottom` collapses straight through a wrapper that
    // has no padding or border. So a gap expressed as a margin makes every row
    // below sit `gap` pixels too high: the cards overlap. Padding cannot
    // collapse and is inside the measured box, which is why `gap` must land
    // there.
    renderList({ gap: 10 });
    const wrappers = Array.from(document.querySelectorAll<HTMLElement>("[data-row-index]"));
    expect(wrappers.length).toBeGreaterThan(0);
    for (const w of wrappers) {
      expect(w.style.paddingBottom).toBe("10px");
      expect(w.style.marginBottom).toBe("");
    }
  });

  it("adds no spacing box at all when no gap is asked for", () => {
    renderList();
    const wrapper = document.querySelector<HTMLElement>("[data-row-index]")!;
    expect(wrapper.style.paddingBottom).toBe("");
  });

  it("ArrowUp at the top and ArrowDown at the bottom stay in range", () => {
    const { onActivate } = renderList();
    const first = document.querySelector<HTMLElement>('[data-row-index="0"]')!;
    fireEvent.keyDown(first, { key: "ArrowUp" });
    expect(onActivate).toHaveBeenLastCalledWith(0);

    fireEvent.keyDown(document.querySelector('[data-row-index="0"]')!, { key: "End" });
    const last = document.querySelector<HTMLElement>(`[data-row-index="${TOTAL - 1}"]`)!;
    fireEvent.keyDown(last, { key: "ArrowDown" });
    expect(onActivate).toHaveBeenLastCalledWith(TOTAL - 1);
  });
});

describe("VirtualList — no layout engine (SSR / jsdom default)", () => {
  afterEach(cleanup);

  it("renders EVERY row rather than none when it cannot measure a viewport", () => {
    // No ResizeObserver installed — this is the environment Next.js renders in
    // on the server and the one the page tests run in.
    expect(canVirtualize()).toBe(false);
    render(
      <VirtualList
        items={ITEMS.slice(0, 30)}
        getKey={(it) => it.id}
        estimateSize={ROW_H}
        height={VIEWPORT_H}
        ariaLabel="Discovered jobs"
        testId="vlist"
      >
        {(item) => <span data-testid="row">{item.label}</span>}
      </VirtualList>,
    );
    expect(screen.getAllByTestId("row").length).toBe(30);
    expect(screen.getByTestId("vlist").getAttribute("data-windowed")).toBe("false");
    // Row semantics hold in this mode too.
    const listitems = document.querySelectorAll('[role="listitem"]');
    expect(listitems[0].getAttribute("aria-setsize")).toBe("30");
    expect(listitems[29].getAttribute("aria-posinset")).toBe("30");
  });
});
