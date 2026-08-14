"use client";

/**
 * S-UI §3.5 — ONE status badge, five tones, one shape.
 *
 * Rule D-8 (a11y + colour-blind requirement): the WORD always carries the
 * meaning; colour is redundant reinforcement only. Never render a bare
 * coloured word, and never encode a state in colour alone.
 *
 * Tone semantics are fixed and must not be re-purposed decoratively:
 *   ok        completed, connected, active, implemented
 *   warn      stalled, stale catalog, quota pressure, heightened tier
 *   danger    failed, error
 *   neutral   idle, planned, not configured, insufficient data, no runs
 *   degraded  produced-nothing-but-not-a-failure (cover-letter degrade,
 *             `available: false`) — Rule D-1: NEVER `ok`, NEVER `danger`.
 */
import type { ReactNode } from "react";

export type StatusTone = "ok" | "warn" | "danger" | "neutral" | "degraded";

const TONE: Record<StatusTone, string> = {
  ok: "border-state-ok/40 text-state-ok",
  warn: "border-state-warn/40 text-state-warn",
  danger: "border-state-danger/40 text-state-danger",
  neutral: "border-hairline-strong text-state-neutral",
  degraded: "border-state-degraded/40 text-state-degraded",
};

export default function StatusBadge({
  tone,
  children,
  dot = false,
  title,
  className = "",
  testId,
}: {
  tone: StatusTone;
  children: ReactNode;
  /** Leading dot for LIVE states only. Decorative — never the sole signal. */
  dot?: boolean;
  title?: string;
  className?: string;
  testId?: string;
}) {
  return (
    <span
      data-testid={testId}
      data-tone={tone}
      title={title}
      className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.06em] ${TONE[tone]} ${className}`}
    >
      {dot ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
