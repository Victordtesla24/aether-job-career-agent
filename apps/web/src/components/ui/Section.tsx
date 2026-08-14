"use client";

/**
 * S-UI §3.1 — `<Section>`: `elev-1 rounded-2xl p-5` with an eyebrow, a title,
 * an action slot and — load-bearing — a RESERVED `footnote` slot.
 *
 * The footnote slot is why this component exists. Sample-window and
 * "not affected by the period selector" disclosures are currently squeezed
 * into headings at 10px/70% opacity, which makes the most important text on
 * screen the least legible (Rule D-7). Giving them a consistent, reserved home
 * at `type-meta` (11px, full muted-dim) is how those honesty contracts survive
 * a redesign becoming MORE visible, not less.
 */
import type { ReactNode } from "react";

export default function Section({
  eyebrow,
  title,
  subtitle,
  action,
  footnote,
  children,
  className = "",
  bodyClassName = "",
  testId,
  accent = false,
  as: Tag = "section",
  labelledById,
}: {
  eyebrow?: ReactNode;
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  /** Window label / disclosure. Rendered at `type-meta`, bottom-left. */
  footnote?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
  testId?: string;
  /** S-UI §2.5 accent-edge: a 2px top-inset gradient for a section that owns a status. */
  accent?: boolean;
  as?: "section" | "div" | "article";
  labelledById?: string;
}) {
  return (
    <Tag
      data-testid={testId}
      aria-labelledby={labelledById}
      className={`elev-1 relative overflow-hidden rounded-2xl p-5 ${
        accent
          ? "before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-aether-coral/60 before:via-aether-coral/10 before:to-transparent"
          : ""
      } ${className}`}
    >
      {eyebrow || title || subtitle || action ? (
        <header className="mb-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            {eyebrow ? (
              <p className="text-[13px] font-semibold uppercase tracking-[0.08em] text-aether-muted-dim">
                {eyebrow}
              </p>
            ) : null}
            {title ? (
              <h3 className="text-[15px] font-semibold tracking-[-0.01em]">{title}</h3>
            ) : null}
            {subtitle ? (
              <p className="mt-0.5 text-[13px] leading-[1.5] text-aether-muted">{subtitle}</p>
            ) : null}
          </div>
          {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
        </header>
      ) : null}

      <div className={bodyClassName}>{children}</div>

      {footnote ? (
        <p
          data-prose="caption"
          className="mt-3 flex items-start gap-1.5 text-[11px] leading-[1.5] text-aether-muted-dim"
        >
          <i className="fa-solid fa-circle-info mt-[3px] shrink-0 text-[10px]" aria-hidden="true" />
          <span className="min-w-0">{footnote}</span>
        </p>
      ) : null}
    </Tag>
  );
}
