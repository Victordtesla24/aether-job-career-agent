"use client";

/**
 * MetricTooltip — GAP-E3. Attaches an accessible (i) info popover to a
 * metric's value: hover or keyboard focus reveals the popover, Escape
 * closes it and returns focus to the trigger (mirrors the tooltip pattern
 * already used in components/agents/AgentConfigGrid.tsx, but implemented
 * with real open/close state rather than CSS-only hover so keyboard users
 * get an explicit close key).
 */
import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

interface MetricTooltipProps {
  /** Optional label shown before the value (e.g. "Interview Rate"). */
  label?: string;
  /** The metric value itself, e.g. "42%" or a number. */
  value: ReactNode;
  /** Popover explanation copy for the metric. */
  tooltip: string;
  className?: string;
}

/**
 * U-UI TOOLTIP-CLIP-BOTTOM-01: a tile near the bottom of the viewport (e.g.
 * the Applied→Screened stage-conversion card) opened its popover 8px below
 * the trigger unconditionally, clipping its bottom edge past the viewport
 * (measured 7.6px past a 900px-tall viewport). Flip above the trigger
 * whenever the popover's own height plus a margin doesn't fit below it.
 */
export function computeFlip(triggerBottom: number, popoverHeight: number, viewportHeight: number, gap = 8, margin = 8): boolean {
  return triggerBottom + gap + popoverHeight + margin > viewportHeight;
}

/**
 * U-UI TOOLTIP-CLIP-BOTTOM-01 ("keep within horizontal bounds too"): the
 * popover is centred on the trigger by default; near a viewport edge that
 * pushes it off-screen. Returns the extra pixel offset (added on top of the
 * base -50% centring transform) needed to keep both edges on-screen.
 */
export function computeHorizontalShift(
  triggerCenterX: number,
  popoverWidth: number,
  viewportWidth: number,
  margin = 8,
): number {
  const left = triggerCenterX - popoverWidth / 2;
  const right = triggerCenterX + popoverWidth / 2;
  if (left < margin) return margin - left;
  if (right > viewportWidth - margin) return viewportWidth - margin - right;
  return 0;
}

export default function MetricTooltip({ label, value, tooltip, className }: MetricTooltipProps) {
  const tipId = useId();
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<"below" | "above">("below");
  const [shiftX, setShiftX] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLSpanElement>(null);

  // Measure only while open — jsdom/SSR report zero-size rects, so this is a
  // no-op there and defaults to the original below/centred placement.
  useLayoutEffect(() => {
    if (!open) return;
    const trigger = triggerRef.current;
    const popover = popoverRef.current;
    if (!trigger || !popover) return;
    const triggerRect = trigger.getBoundingClientRect();
    const popoverRect = popover.getBoundingClientRect();
    const popoverHeight = popoverRect.height || popover.offsetHeight;
    const popoverWidth = popoverRect.width || popover.offsetWidth;
    setPlacement(
      computeFlip(triggerRect.bottom, popoverHeight, window.innerHeight) ? "above" : "below",
    );
    setShiftX(
      computeHorizontalShift(triggerRect.left + triggerRect.width / 2, popoverWidth, window.innerWidth),
    );
  }, [open]);

  const handleKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    }
  };

  return (
    <span className={`inline-flex items-center gap-1.5 ${className ?? ""}`} data-testid="metric-tooltip">
      {label ? <span>{label}</span> : null}
      <span>{value}</span>
      <span className="relative inline-flex">
        <button
          ref={triggerRef}
          type="button"
          data-testid="metric-tooltip-trigger"
          aria-describedby={tipId}
          aria-expanded={open}
          aria-label={label ? `More about ${label}` : "More information"}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={handleKeyDown}
          className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-aether-muted-dim outline-none transition hover:text-white focus-visible:ring-2 focus-visible:ring-aether-coral/60"
        >
          <i className="fa-solid fa-circle-info text-[10px]" aria-hidden="true" />
        </button>
        <span
          ref={popoverRef}
          id={tipId}
          role="tooltip"
          data-testid="metric-tooltip-popover"
          data-placement={placement}
          style={{ transform: `translateX(calc(-50% + ${shiftX}px))` }}
          className={`pointer-events-none absolute left-1/2 z-20 w-56 max-w-[calc(100vw-2rem)] rounded-lg border border-white/10 bg-[#1C1C29] p-3 text-[11px] font-normal leading-relaxed text-aether-muted shadow-2xl transition-opacity duration-150 ${
            /* U-UI TOOLTIP-CLIP-BOTTOM-01: flip above the trigger when there
             * isn't enough room below (see computeFlip / the useLayoutEffect
             * above) instead of always anchoring `top-6`, which clipped the
             * popover's bottom edge past the viewport near the page bottom. */
            placement === "above" ? "bottom-6" : "top-6"
          } ${
            /* GAP-P6-UI-001: closed popovers must be display:none (not just
             * opacity-0) — an absolutely positioned w-56 box left in the
             * layout still inflates the ancestor's scrollWidth even while
             * invisible, which is exactly what produced the horizontal
             * overflow on /dashboard at a 390px mobile viewport (multiple
             * MetricTooltip instances in DashboardStats + MarketPulse). */
            open ? "opacity-100" : "hidden opacity-0"
          }`}
        >
          {tooltip}
        </span>
      </span>
    </span>
  );
}
