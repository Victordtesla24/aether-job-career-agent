"use client";

/**
 * ADMIN-2.0 FE-1 — the executive dashboard's surfaces.
 *
 * These are the two things every band on the board is made of: a `<Panel>`
 * (the certified `.elev-1` dark card with a section-cap heading) and an
 * `<InsufficientData>` body that takes a panel's place when its figure cannot
 * honestly be drawn.
 *
 * WHY THE EMPTY STATE IS A FIRST-CLASS COMPONENT AND NOT AN AFTERTHOUGHT. On
 * a platform with ten accounts, MOST panels on this board are in the empty
 * state on day one. If "not enough data yet" is a small grey line, the board
 * reads as broken; if it is a fabricated zero, the board reads as a lie. So
 * the empty state occupies the panel at the panel's own size, states the
 * reason in the API's own words, and — where there is one — names the
 * condition that would make the figure measurable. That is the difference
 * between a dashboard that is honestly early and one that looks broken.
 */
import type { ReactNode } from "react";

import { DecisionGuidance } from "../../ui/decision-guidance";

export function Panel({
  title,
  caption,
  action,
  children,
  className,
  testId,
  measured,
  guidance,
}: {
  title: string;
  /** The declared window / basis. Always rendered — C-3 applies to panels too. */
  caption?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
  /** Mirrored to `data-measured` so a reviewer can assert honesty from the DOM. */
  measured?: boolean;
  /**
   * R1.2 — the panel's "what this tells you / what to do next" affordance.
   * Copy must state only what the figure establishes and a concrete action.
   */
  guidance?: { tellsYou: string; next: string };
}) {
  return (
    <section
      data-testid={testId}
      data-measured={measured === undefined ? undefined : measured ? "true" : "false"}
      className={`elev-1 flex min-w-0 flex-col rounded-2xl p-4 ${className ?? ""}`}
    >
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="type-section truncate" title={title}>
            {title}
          </h2>
          {caption ? <p className="type-meta mt-1 truncate" title={caption}>{caption}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </header>
      <div className="min-w-0 flex-1">{children}</div>
      {guidance ? <DecisionGuidance tellsYou={guidance.tellsYou} next={guidance.next} /> : null}
    </section>
  );
}

/**
 * The honest empty state.
 *
 * `reason` is rendered VERBATIM — it is usually the API's own sentence, and
 * rewriting it here would put a second, competing explanation in front of the
 * owner. `nextStep` is this page's own deterministic note about what would
 * make the figure appear; it is omitted rather than guessed.
 */
export function InsufficientData({
  reason,
  nextStep,
  compact,
}: {
  reason: string;
  nextStep?: string;
  compact?: boolean;
}) {
  return (
    <div
      data-testid="insufficient-data"
      className={`flex flex-col items-start justify-center rounded-xl border border-dashed border-white/10 bg-white/[0.015] px-4 ${
        compact ? "py-4" : "py-8"
      }`}
    >
      <p className="text-[13px] font-medium text-aether-muted">Not enough data yet</p>
      <p className="type-meta mt-1.5 max-w-prose">{reason}</p>
      {nextStep ? <p className="type-meta mt-1 max-w-prose text-aether-muted-dim">{nextStep}</p> : null}
    </div>
  );
}

/** A loading placeholder that claims nothing: no zeroes, no shapes, no units. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      data-testid="admin-exec-skeleton"
      aria-hidden="true"
      className={`animate-pulse rounded-lg bg-white/[0.055] ${className ?? ""}`}
    />
  );
}
