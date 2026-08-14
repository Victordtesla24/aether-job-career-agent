/**
 * Shared helpers for the chart-kit tests. NOT a test file (no `.test.` in the
 * name, so vitest does not collect it).
 */
import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { vi } from "vitest";

/**
 * Install a deterministic `window.matchMedia` stub. jsdom ships no
 * implementation at all, so every component that asks about
 * `prefers-reduced-motion` must be exercised through this.
 */
export function stubMatchMedia(reducedMotion: boolean): void {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: query.includes("prefers-reduced-motion") ? reducedMotion : false,
      media: query,
      onchange: null,
      addEventListener: (_: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.add(listener);
      },
      removeEventListener: (_: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.delete(listener);
      },
      addListener: (listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
      removeListener: (listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
      dispatchEvent: () => false,
    }),
  });
}

/** Remove the stub so a test file cannot leak matchMedia into the next one. */
export function clearMatchMedia(): void {
  Reflect.deleteProperty(window, "matchMedia");
}

/**
 * Render and return the root `<figure>` of the chart under test. Charts are
 * queried through DOM structure — never pixel snapshots.
 */
export function renderChart(ui: ReactElement): HTMLElement {
  const { container } = render(ui);
  const figure = container.querySelector("figure");
  if (!figure) throw new Error("chart did not render a <figure> root");
  return figure as HTMLElement;
}

/**
 * Silence the React "The above error occurred in ..." log emitted whenever a
 * component throws on purpose (the C-1..C-5 dev-throw tests). Returns a
 * restore function.
 */
export function silenceConsoleError(): () => void {
  const spy = vi.spyOn(console, "error").mockImplementation(() => {});
  return () => spy.mockRestore();
}

/** All `[data-mark]` elements of one kind inside a rendered chart. */
export function marks(root: HTMLElement, kind: "value" | "zero" | "unmeasured"): Element[] {
  return Array.from(root.querySelectorAll(`[data-mark="${kind}"]`));
}
