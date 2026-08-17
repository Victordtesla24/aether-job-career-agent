import type { CSSProperties, MouseEventHandler, ReactNode } from "react";

export type ChipTone = "neutral" | "accent" | "ok" | "warn" | "danger" | "info" | "degraded";

/**
 * A metadata chip (source badge, freshness stamp, stage marker, fit score) or a
 * filter pill when `onClick` is supplied. `neutral` is the default because an
 * unqualified chip must never borrow a semantic colour it did not earn.
 */
export interface ChipProps {
  tone?: ChipTone;
  /** Render the label in the tabular data face — use for every number. */
  mono?: boolean;
  icon?: string;
  /** Filter-pill selected state (gold hairline + gold label). */
  selected?: boolean;
  onClick?: MouseEventHandler;
  title?: string;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}

export function Chip(props: ChipProps): JSX.Element;
