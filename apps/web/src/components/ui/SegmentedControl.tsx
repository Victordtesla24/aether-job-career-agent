"use client";

/**
 * S-UI §3.8 — the ONE segmented control (period selectors, board/sankey
 * switches, filter chips, and the Agents page's three tabs all used to be
 * separate implementations).
 *
 * `role="tablist"` with roving tabindex + arrow-key navigation, per the
 * WAI-ARIA tabs pattern. The active item uses a solid coral fill; note that
 * `globals.css` (DEF-053) already forces dark text on `bg-aether-coral` for
 * contrast, so no per-item text colour is set here.
 */
import { useRef } from "react";

export interface SegmentedItem<T extends string> {
  value: T;
  label: string;
  /** Optional trailing count — rendered in tabular numerals. */
  count?: number | null;
  /** FontAwesome class, e.g. "fa-diagram-project". */
  icon?: string;
}

export default function SegmentedControl<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  idPrefix,
  panelIdPrefix,
  size = "md",
  testId,
}: {
  items: ReadonlyArray<SegmentedItem<T>>;
  value: T;
  onChange: (next: T) => void;
  ariaLabel: string;
  /** Stable id prefix so `aria-controls`/`aria-labelledby` can pair up. */
  idPrefix: string;
  /** When set, each tab points `aria-controls` at `${panelIdPrefix}-${value}`. */
  panelIdPrefix?: string;
  size?: "sm" | "md";
  testId?: string;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  const move = (delta: number) => {
    const i = items.findIndex((it) => it.value === value);
    if (i < 0) return;
    const next = items[(i + delta + items.length) % items.length];
    onChange(next.value);
    // Focus follows selection (automatic activation) — the ARIA tabs pattern's
    // recommended behaviour when switching panels is cheap, which it is here:
    // every panel is already mounted.
    requestAnimationFrame(() => refs.current[next.value]?.focus());
  };

  const pad = size === "sm" ? "px-2.5 py-1 text-[11px]" : "px-3 py-1.5 text-[12px]";

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      data-testid={testId}
      className="elev-1 inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-lg p-1"
    >
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            ref={(el) => {
              refs.current[item.value] = el;
            }}
            type="button"
            role="tab"
            id={`${idPrefix}-${item.value}`}
            aria-selected={active}
            aria-controls={panelIdPrefix ? `${panelIdPrefix}-${item.value}` : undefined}
            tabIndex={active ? 0 : -1}
            data-testid={`${idPrefix}-tab-${item.value}`}
            onClick={() => onChange(item.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                e.preventDefault();
                move(1);
              } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                e.preventDefault();
                move(-1);
              }
            }}
            className={`flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md font-medium outline-none transition-[background-color,color] duration-150 focus-visible:ring-2 focus-visible:ring-aether-coral/70 ${pad} ${
              active
                ? "bg-aether-coral font-semibold"
                : "text-aether-muted hover:bg-surface-3 hover:text-aether-text"
            }`}
          >
            {item.icon ? <i className={`fa-solid ${item.icon} text-[10px]`} aria-hidden="true" /> : null}
            {item.label}
            {typeof item.count === "number" ? (
              <span className="font-mono text-[10px] tabular-nums opacity-70">{item.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
