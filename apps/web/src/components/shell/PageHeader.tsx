"use client";

/**
 * S-UI-REBUILD §1.7 — the one page header.
 *
 * `H1` + subtitle + a right action slot + an optional control row (usually a
 * `<SegmentedControl>`). Every page adopts it in its own batch; no page
 * hand-rolls an `<h1>` again. Presentational only — it holds no state, makes
 * no request, and imposes no copy.
 *
 * The `footnote` slot exists for the same reason `<Section footnote>` does
 * (Rule D-7 / D-ζ): a sample-window or "not affected by the period selector"
 * disclosure needs a reserved home at readable size, not a 10px afterthought
 * squeezed into the heading.
 */
import type { ReactNode } from "react";

export function PageHeader({
  title,
  subtitle,
  action,
  controls,
  footnote,
  className = "",
  testId,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  /** Row below the title — segmented control, filter chips, tabs. */
  controls?: ReactNode;
  /** Disclosure text, rendered at `type-meta` (11px, full opacity). */
  footnote?: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <header data-testid={testId} className={`mb-5 ${className}`}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h1 className="type-page min-w-0">{title}</h1>
          {subtitle ? <p className="type-page-sub mt-1">{subtitle}</p> : null}
        </div>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </div>
      {controls ? <div className="mt-3">{controls}</div> : null}
      {footnote ? <p className="type-meta mt-2">{footnote}</p> : null}
    </header>
  );
}

export default PageHeader;
