import type { CSSProperties, ReactNode } from "react";

export type StatusTone = "ok" | "warn" | "danger" | "info" | "neutral" | "degraded" | "gold";

/**
 * Ticket/run/pipeline status. Tone semantics are fixed and must not be
 * repurposed decoratively: `ok` completed·connected·running · `warn` stalled·
 * quota pressure · `danger` failed · `neutral` idle·not measured (NEVER ok) ·
 * `degraded` produced-nothing-but-not-a-failure · `gold` brand/ceremonial only.
 * Colour is redundant reinforcement — the word always states the state.
 */
export interface StatusBadgeProps {
  tone?: StatusTone;
  /** Leading dot. Use for live states only. */
  dot?: boolean;
  /** Animates the dot. Permitted only with tone="ok" and a genuinely live thing. */
  live?: boolean;
  title?: string;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}

export function StatusBadge(props: StatusBadgeProps): JSX.Element;
