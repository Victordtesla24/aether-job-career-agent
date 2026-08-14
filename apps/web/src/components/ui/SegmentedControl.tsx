"use client";

/**
 * S-UI §3.8 — the ONE segmented control (period selectors, board/sankey
 * switches, filter chips, and the Agents page's three tabs all used to be
 * separate implementations).
 *
 * `role="tablist"` with roving tabindex + arrow-key navigation, per the
 * WAI-ARIA tabs pattern.
 *
 * ─── B2 GLOBAL CONTROLS PASS — the active state is a border, not a fill ───
 *
 * Reference-pack rule 8, measured across the whole study set: *"active-state
 * indicators are minimal — a border or underline, never a full background
 * fill"*. Attio's stepper is a thin coloured left border against 40%-opacity
 * text; Superhuman's tab bar is a bottom-border underline and nothing else;
 * PostHog's one filled pill is on an interactive DEMO, not on navigation. The
 * Agents-console certification left this as a deferred "tab-pill ruling"; this
 * closes it, and closes it APP-WIDE rather than per page, because a control
 * that looks different on two screens is two controls.
 *
 * What replaced what: `bg-aether-coral` (a saturated fill, which also spent the
 * screen's single loud-colour budget on a *navigation* affordance) → a coral
 * underline + `surface-2` seat + full-opacity text, with inactive items at
 * muted weight. The coral is still present and still unambiguous; it is simply
 * no longer the loudest thing on a page whose data has more to say.
 *
 * Contrast note: the old fill relied on `globals.css` DEF-053 forcing dark text
 * on `bg-aether-coral`. With the fill gone, the active label is `aether-text`
 * (#F4F4F8) on the page ground — 15.9:1 — so that override no longer applies
 * to this control and none is needed.
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
  testIdFor,
  className = "",
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
  /**
   * Per-item `data-testid`. Defaults to `${idPrefix}-tab-${value}`.
   *
   * Exists so a page that already has a *pinned* testid contract (Applications'
   * `view-board` / `view-sankey` / …, asserted by tests this batch may not
   * edit) can adopt the shared control without renaming anything. Adapting the
   * component to the existing contract is the correct direction: the contract
   * is the tested surface, the class names are not.
   */
  testIdFor?: (value: T) => string;
  className?: string;
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

  const pad = size === "sm" ? "px-2.5 pb-1.5 pt-1 text-[11px]" : "px-3 pb-2 pt-1.5 text-[12px]";

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      data-testid={testId}
      className={`inline-flex max-w-full items-stretch gap-0.5 overflow-x-auto rounded-lg border-b border-hairline ${className}`}
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
            data-testid={testIdFor ? testIdFor(item.value) : `${idPrefix}-tab-${item.value}`}
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
            className={`relative flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-t-md outline-none transition-[color,background-color] duration-[--dur-fast] focus-visible:ring-2 focus-visible:ring-aether-coral/70 ${pad} ${
              active
                ? // Rule 8: a 2px coral underline seated on the tablist's own
                  // hairline, plus a barely-there surface lift. `-bottom-px`
                  // puts the rule ON the hairline rather than above it, so the
                  // active tab reads as continuous with its panel.
                  "bg-surface-2/60 font-semibold text-aether-text after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:rounded-full after:bg-aether-coral after:content-['']"
                : "font-medium text-aether-muted hover:bg-surface-3/50 hover:text-aether-text"
            }`}
          >
            {item.icon ? (
              <i
                className={`fa-solid ${item.icon} text-[10px] ${active ? "text-aether-coral" : ""}`}
                aria-hidden="true"
              />
            ) : null}
            {item.label}
            {typeof item.count === "number" ? (
              <span
                className={`font-mono text-[10px] tabular-nums ${
                  active ? "text-aether-coral" : "text-aether-muted-dim"
                }`}
              >
                {item.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
