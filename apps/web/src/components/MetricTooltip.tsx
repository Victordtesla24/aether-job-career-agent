"use client";

/**
 * MetricTooltip — GAP-E3. Attaches an accessible (i) info popover to a
 * metric's value: hover or keyboard focus reveals the popover, Escape
 * closes it and returns focus to the trigger (mirrors the tooltip pattern
 * already used in components/agents/AgentConfigGrid.tsx, but implemented
 * with real open/close state rather than CSS-only hover so keyboard users
 * get an explicit close key).
 */
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

interface MetricTooltipProps {
  /** Optional label shown before the value (e.g. "Interview Rate"). */
  label?: string;
  /** The metric value itself, e.g. "42%" or a number. */
  value: ReactNode;
  /** Popover explanation copy for the metric. */
  tooltip: string;
  className?: string;
}

export default function MetricTooltip({ label, value, tooltip, className }: MetricTooltipProps) {
  const tipId = useId();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

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
          id={tipId}
          role="tooltip"
          data-testid="metric-tooltip-popover"
          className={`pointer-events-none absolute left-1/2 top-6 z-20 w-56 max-w-[calc(100vw-2rem)] -translate-x-1/2 rounded-lg border border-white/10 bg-[#1C1C29] p-3 text-[11px] font-normal leading-relaxed text-aether-muted shadow-2xl transition-opacity duration-150 ${
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
