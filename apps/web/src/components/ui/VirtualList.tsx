"use client";

/**
 * `<VirtualList>` — the app's one windowed list (S-UI-REBUILD-SPEC §5.3).
 *
 * THE DEFECT IT CLOSES. `/dashboard/jobs` rendered every match into the
 * document at once: measured on production at 1600×1100 the page was
 * **12,172 CSS px** tall with **2,041 DOM nodes** (390px: 18,999px), against a
 * doctrine that says no authenticated page exceeds ~2,500px and everything else
 * scrolls inside a container (D-ε). The list is the only unbounded thing on
 * that screen, so it is the thing that has to be windowed.
 *
 * THE LIBRARY. `@tanstack/react-virtual` v3 (MIT, 56 kB unpacked, peer React
 * 16.8–19). Headless: it computes offsets and returns indices, and imposes no
 * markup, no styling and no ARIA of its own — which is why it can be adopted
 * without touching a single certified card. The alternative libraries all ship
 * a row renderer whose DOM we would then have to fight.
 *
 * ─── The two things virtualization usually breaks, and how this does not ───
 *
 * 1. SCREEN-READER ROW SEMANTICS. A windowed list is a lie to assistive tech by
 *    default: 12 rows are in the DOM, so a screen reader says "list, 12 items"
 *    about a list of 3,800. Every row here therefore carries `aria-setsize`
 *    (the TRUE total) and `aria-posinset` (the TRUE 1-based index), so the
 *    announcement is "item 431 of 3,800" no matter how few nodes exist. This is
 *    the same honesty rule the rest of the product follows — the UI may not
 *    state a number it cannot support, and it may not hide one it can.
 *
 * 2. KEYBOARD NAVIGATION. Tab order cannot reach a row that is not rendered, so
 *    a windowed list MUST provide the roving-focus pattern instead of relying
 *    on Tab: ArrowDown/ArrowUp/Home/End move an active index, the virtualizer
 *    scrolls that index into the window, and focus lands on it once it exists.
 *    `onActivate` reports the move so the owning page can mirror it into its own
 *    selection state.
 *
 * ─── Rendering everything when there is no layout engine ───
 *
 * A virtualizer needs a measured viewport. In two real situations there is not
 * one: server rendering (Next.js has no DOM) and jsdom (no layout, no
 * `ResizeObserver`). The correct degradation there is to render EVERY row —
 * never to render none — so the markup is complete for SSR hydration and
 * complete for tests. `canWindow` is that switch, and it is deliberately the
 * only branch in this file: in a browser with a measured viewport the list
 * windows; everywhere else it is an ordinary list.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { defaultRangeExtractor, useVirtualizer } from "@tanstack/react-virtual";

export interface VirtualListProps<T> {
  items: readonly T[];
  /** Stable identity per row — used for React keys and focus restoration. */
  getKey: (item: T, index: number) => string;
  /** Row renderer. Receives the TRUE index within `items`, never a window index. */
  children: (item: T, index: number) => ReactNode;
  /**
   * Best-guess row height in px. Only a starting point: every rendered row is
   * measured for real via `measureElement`, so variable-height cards are exact
   * after first paint.
   */
  estimateSize: number;
  /** Max height of the scroll viewport. A number is px; a string is any CSS length. */
  height: number | string;
  /** Rows rendered beyond each edge of the viewport. */
  overscan?: number;
  /**
   * Vertical space between rows, in px.
   *
   * It is applied as `padding-bottom` on the measured row wrapper, NOT as a
   * margin on the card, and that distinction is load-bearing: a child's bottom
   * margin collapses through a wrapper that has no padding or border, so
   * `measureElement` (which reads `getBoundingClientRect`) would report a
   * height that excludes it — and every row below would be positioned that many
   * pixels too high, i.e. the cards would overlap. Padding cannot collapse and
   * is inside the measured box.
   *
   * In the un-windowed fallback the container's own `gap` does the same job, so
   * spacing matches in both modes.
   */
  gap?: number;
  ariaLabel: string;
  className?: string;
  /** Applied to the scroll viewport. */
  viewportClassName?: string;
  /** Index to keep in view (e.g. the page's selected row). */
  activeIndex?: number;
  /** Fired when keyboard navigation moves the active row. */
  onActivate?: (index: number) => void;
  testId?: string;
}

/**
 * Whether this environment can window a list: it needs a `ResizeObserver` to
 * track the viewport and a real layout engine behind it. jsdom and the server
 * have neither, and both must render the complete list instead.
 */
export function canVirtualize(): boolean {
  return typeof window !== "undefined" && typeof window.ResizeObserver === "function";
}

export default function VirtualList<T>({
  items,
  getKey,
  children,
  estimateSize,
  height,
  overscan = 6,
  gap = 0,
  ariaLabel,
  className = "",
  viewportClassName = "",
  activeIndex,
  onActivate,
  testId,
}: VirtualListProps<T>) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [windowed, setWindowed] = useState(false);
  /** Row index that should receive DOM focus once it is rendered. */
  const focusTarget = useRef<number | null>(null);
  /**
   * Indices that must be in the DOM regardless of where the viewport is: the
   * page's selected row, and the row the keyboard just moved to.
   *
   * This is what makes roving focus deterministic. Relying on `scrollToIndex`
   * alone would make focus depend on a scroll EVENT arriving before the next
   * commit — which it may not (smooth scrolling defers it by frames), leaving
   * focus stranded on the row the user just left.
   */
  const [pinnedIndex, setPinnedIndex] = useState<number | null>(null);

  // Deferred to an effect so the FIRST paint is always the complete list: the
  // server and the client agree on that markup, so hydration cannot mismatch,
  // and the window is applied on the commit right after.
  useEffect(() => {
    if (canVirtualize()) setWindowed(true);
  }, []);

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateSize,
    overscan,
    enabled: windowed,
    rangeExtractor: useCallback(
      (range: Parameters<typeof defaultRangeExtractor>[0]) => {
        const base = new Set(defaultRangeExtractor(range));
        for (const pin of [pinnedIndex, activeIndex]) {
          if (pin != null && pin >= 0 && pin < range.count) base.add(pin);
        }
        return Array.from(base).sort((a, b) => a - b);
      },
      [pinnedIndex, activeIndex],
    ),
  });

  const virtualRows = virtualizer.getVirtualItems();
  /**
   * The rows actually committed to the DOM. Windowed: whatever the virtualizer
   * asked for. Not windowed (SSR / jsdom / no ResizeObserver): all of them.
   */
  const rendered = useMemo(() => {
    if (!windowed) return items.map((_, index) => ({ index, start: 0 }));
    return virtualRows.map((row) => ({ index: row.index, start: row.start }));
  }, [windowed, items, virtualRows]);

  const totalSize = windowed ? virtualizer.getTotalSize() : undefined;

  /** Bring `index` into the window, then focus its row element. */
  const moveTo = useCallback(
    (index: number) => {
      if (items.length === 0) return;
      const clamped = Math.max(0, Math.min(items.length - 1, index));
      focusTarget.current = clamped;
      // Pin FIRST: the row is guaranteed to exist on the next commit whether or
      // not the scroll lands in time.
      setPinnedIndex(clamped);
      if (windowed) virtualizer.scrollToIndex(clamped, { align: "auto" });
      onActivate?.(clamped);
      // If the row is already mounted, focus it now; otherwise the layout
      // effect below picks it up on the commit that mounts it.
      const el = scrollRef.current?.querySelector<HTMLElement>(`[data-row-index="${clamped}"]`);
      if (el) {
        el.focus();
        focusTarget.current = null;
      }
    },
    [items.length, onActivate, virtualizer, windowed],
  );

  // Focus a row that was scrolled into the window by `moveTo` but did not exist
  // in the DOM at the time. Runs before paint so focus never visibly lands on
  // the wrong element first.
  useLayoutEffect(() => {
    const target = focusTarget.current;
    if (target == null) return;
    const el = scrollRef.current?.querySelector<HTMLElement>(`[data-row-index="${target}"]`);
    if (el) {
      el.focus();
      focusTarget.current = null;
    }
  });

  // Keep the page's own selection in view when it changes from outside (a
  // click, a deep link) — without stealing focus, which belongs to whatever
  // the user is actually operating.
  useEffect(() => {
    if (!windowed || activeIndex == null || activeIndex < 0) return;
    virtualizer.scrollToIndex(activeIndex, { align: "auto" });
  }, [activeIndex, virtualizer, windowed]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const row = (event.target as HTMLElement).closest<HTMLElement>("[data-row-index]");
    const current = row ? Number(row.dataset.rowIndex) : (activeIndex ?? -1);
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        moveTo(current + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        moveTo(current - 1);
        break;
      case "Home":
        event.preventDefault();
        moveTo(0);
        break;
      case "End":
        event.preventDefault();
        moveTo(items.length - 1);
        break;
      default:
    }
  };

  return (
    <div
      ref={scrollRef}
      data-testid={testId}
      data-windowed={windowed ? "true" : "false"}
      className={`min-h-0 overflow-y-auto overscroll-contain ${viewportClassName}`}
      style={{ maxHeight: typeof height === "number" ? `${height}px` : height }}
      onKeyDown={onKeyDown}
    >
      <div
        role="list"
        aria-label={ariaLabel}
        className={className}
        style={
          windowed
            ? { height: totalSize, position: "relative", width: "100%" }
            : undefined
        }
      >
        {rendered.map(({ index, start }) => {
          const item = items[index];
          if (item === undefined) return null;
          return (
            <div
              key={getKey(item, index)}
              role="listitem"
              // The honest count, independent of how many nodes exist.
              aria-setsize={items.length}
              aria-posinset={index + 1}
              data-row-index={index}
              tabIndex={-1}
              ref={windowed ? virtualizer.measureElement : undefined}
              data-index={index}
              className="outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/70"
              style={
                windowed
                  ? {
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateY(${start}px)`,
                      // See the `gap` prop: padding, never margin.
                      paddingBottom: gap || undefined,
                    }
                  : undefined
              }
            >
              {children(item, index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
