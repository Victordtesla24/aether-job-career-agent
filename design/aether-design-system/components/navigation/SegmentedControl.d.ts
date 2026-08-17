import type { CSSProperties } from "react";

export interface SegmentedItem {
  value: string;
  label: string;
  /** Trailing count, rendered in tabular numerals. Omit when unknown — never 0 as a placeholder. */
  count?: number | null;
  /** Font Awesome 6 class. */
  icon?: string;
}

/**
 * Every tab strip in the product — period selectors, board/flow switches, filter
 * tabs. The active tab carries a 2px gold underline seated on the strip's own
 * hairline; it is never a saturated pill, so navigation never spends the
 * screen's single loud-colour budget.
 */
export interface SegmentedControlProps {
  items: ReadonlyArray<SegmentedItem>;
  value: string;
  onChange: (next: string) => void;
  ariaLabel: string;
  idPrefix?: string;
  size?: "sm" | "md";
  className?: string;
  style?: CSSProperties;
}

export function SegmentedControl(props: SegmentedControlProps): JSX.Element;
